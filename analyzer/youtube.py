"""yt-dlp / ffmpeg 래퍼.

CLI를 subprocess로 호출하는 대신 yt-dlp의 파이썬 API를 씁니다. 다운로드된
파일의 실제 경로를 info dict에서 받아오므로, 확장자를 추측하다 어긋나는
문제가 생기지 않습니다.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

import yt_dlp

import config
from analyzer.errors import (
    InvalidURLError,
    SubtitlesUnavailableError,
    UpstreamError,
    VideoTooLongError,
    VideoUnavailableError,
)
from analyzer.vtt import Cue, parse_vtt

log = logging.getLogger(__name__)

_VIDEO_ID_PATTERNS = [
    re.compile(r"youtube\.com/watch\?(?:.*&)?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/live/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/v/([A-Za-z0-9_-]{11})"),
]


def extract_video_id(url: str) -> str:
    """유튜브 URL에서 11자리 영상 ID를 뽑습니다.

    문자열 포함 검사(`"youtube.com" in url`)와 달리, 실제 ID 패턴에
    매칭되지 않으면 통과시키지 않습니다.
    """
    if not url or not isinstance(url, str):
        raise InvalidURLError("YouTube 주소를 입력해 주세요.")
    candidate = url.strip()
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    raise InvalidURLError("올바른 YouTube 주소가 아닙니다.")


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def ffmpeg_path() -> str:
    """번들된 ffmpeg를 우선 쓰고, 없으면 시스템 ffmpeg로 폴백합니다."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - 환경 의존
        found = shutil.which("ffmpeg")
        if not found:
            raise UpstreamError("서버에 ffmpeg가 설치되어 있지 않습니다.")
        return found


@dataclass
class VideoInfo:
    video_id: str
    title: str
    author: str
    duration: int
    thumbnail: str

    def as_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "author": self.author,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
        }


def base_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg_path(),
        "socket_timeout": 30,
        "retries": 2,
    }


def fetch_info(video_id: str) -> tuple[VideoInfo, dict]:
    """영상 메타데이터를 가져오고 길이 제한을 검사합니다."""
    opts = base_opts() | {"skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(canonical_url(video_id), download=False)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("메타데이터 조회 실패 %s: %s", video_id, exc)
        raise VideoUnavailableError(
            "영상 정보를 가져오지 못했습니다. 비공개이거나 삭제된 영상일 수 있습니다."
        ) from exc

    if raw.get("is_live"):
        raise VideoUnavailableError("실시간 방송은 분석할 수 없습니다.")

    duration = int(raw.get("duration") or 0)
    if duration > config.MAX_VIDEO_DURATION_SEC:
        limit_min = config.MAX_VIDEO_DURATION_SEC // 60
        raise VideoTooLongError(
            f"영상이 너무 깁니다. {limit_min}분 이하만 분석할 수 있습니다."
        )

    info = VideoInfo(
        video_id=video_id,
        title=raw.get("title") or "",
        author=raw.get("uploader") or raw.get("channel") or "",
        duration=duration,
        thumbnail=raw.get("thumbnail") or "",
    )
    return info, raw


def _normalize_lang(lang: str) -> str:
    return lang.split("-")[0].lower()


def select_subtitle_track(raw_info: dict) -> tuple[str, str]:
    """(자막 URL, 언어)를 고릅니다.

    수동 자막을 자동 생성 자막보다, 설정된 언어 우선순위를 그 외 언어보다
    우선합니다.
    """
    manual = raw_info.get("subtitles") or {}
    automatic = raw_info.get("automatic_captions") or {}

    def pick(tracks: dict, langs: list[str] | None) -> tuple[str, str] | None:
        if langs is None:
            candidates = list(tracks.items())
        else:
            candidates = [
                (lang, entries)
                for wanted in langs
                for lang, entries in tracks.items()
                if _normalize_lang(lang) == wanted
            ]
        for lang, entries in candidates:
            for entry in entries or []:
                if entry.get("ext") == "vtt" and entry.get("url"):
                    return entry["url"], lang
        return None

    for tracks in (manual, automatic):
        for langs in (config.SUBTITLE_LANG_PRIORITY, None):
            found = pick(tracks, langs)
            if found:
                return found

    raise SubtitlesUnavailableError(
        "이 영상에는 사용할 수 있는 자막이 없습니다. "
        "자막이 있는 영상으로 다시 시도해 주세요."
    )


def fetch_subtitles(raw_info: dict) -> tuple[list[Cue], str]:
    """자막을 내려받아 큐 목록으로 파싱합니다."""
    url, lang = select_subtitle_track(raw_info)
    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            body = ydl.urlopen(url).read().decode("utf-8", errors="ignore")
    except Exception as exc:
        log.warning("자막 다운로드 실패: %s", exc)
        raise SubtitlesUnavailableError("자막을 내려받지 못했습니다.") from exc

    cues = parse_vtt(body)
    if not cues:
        raise SubtitlesUnavailableError("자막이 비어 있습니다.")
    return cues, lang


def download_video(video_id: str, work_dir: str) -> str:
    """프레임 캡처용으로 저화질 영상을 내려받고 실제 파일 경로를 반환합니다."""
    height = config.FRAME_SOURCE_HEIGHT
    opts = base_opts() | {
        "format": f"bv*[height<={height}]+ba/b[height<={height}]/b",
        "outtmpl": os.path.join(work_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(video_id), download=True)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("영상 다운로드 실패 %s: %s", video_id, exc)
        raise VideoUnavailableError("영상을 내려받지 못했습니다.") from exc

    downloads = info.get("requested_downloads") or []
    for entry in downloads:
        path = entry.get("filepath")
        if path and os.path.exists(path):
            return path

    # 구버전 yt-dlp 폴백: 작업 폴더에서 실제 생성된 파일을 찾습니다.
    for name in sorted(os.listdir(work_dir)):
        if name.startswith("source."):
            return os.path.join(work_dir, name)

    raise VideoUnavailableError("영상 파일을 찾을 수 없습니다.")


def capture_frame(video_path: str, second: int, work_dir: str) -> str | None:
    """지정 시점의 프레임을 JPEG base64로 반환합니다. 실패 시 None."""
    out_path = os.path.join(work_dir, f"frame_{second}.jpg")
    cmd = [
        ffmpeg_path(),
        "-nostdin",
        "-y",
        "-ss", str(second),
        "-i", video_path,
        "-frames:v", "1",
        # 가로 폭을 제한해 이미지 토큰(=비용)을 통제합니다.
        "-vf", f"scale='min(iw,{config.FRAME_MAX_WIDTH})':-2",
        "-q:v", "3",
        out_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired:
        log.warning("프레임 캡처 시간 초과: %ss", second)
        return None

    if result.returncode != 0 or not os.path.exists(out_path):
        log.warning("프레임 캡처 실패 %ss: %s", second, (result.stderr or "")[-300:])
        return None

    with open(out_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    os.remove(out_path)
    return encoded
