"""구간 잘라내기(부가 기능).

기존 구현의 문제 세 가지를 고쳤습니다.

1. `-ss ... -to ... -i` + `-c copy` 조합은 키프레임 단위로만 잘려 시작점이
   수 초 어긋났습니다. 여기서는 입력 시크 + 재인코딩으로 정확히 자릅니다.
2. `outtmpl`이 확장자를 `.mp4`로 강제해, webm이 받아지면 `-c copy`가 실패했습니다.
   yt-dlp가 알려주는 실제 경로를 씁니다.
3. `@after_this_request`에서 파일을 지우면 응답 본문 전송 중에 삭제되어
   다운로드가 잘릴 수 있었습니다. 메모리로 읽어 반환하고 파일은 즉시 정리합니다.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile

import yt_dlp

import config
from analyzer import youtube
from analyzer.errors import AnalyzerError, UpstreamError
from analyzer.timecode import InvalidTimecode, parse_timecode

log = logging.getLogger(__name__)


def validate_range(start_text: str, end_text: str) -> tuple[int, int]:
    try:
        start = parse_timecode(start_text)
        end = parse_timecode(end_text)
    except InvalidTimecode as exc:
        raise AnalyzerError(str(exc)) from exc

    if end <= start:
        raise AnalyzerError("끝 시간은 시작 시간보다 뒤여야 합니다.")

    duration = end - start
    if duration > config.CLIP_MAX_DURATION_SEC:
        limit_min = config.CLIP_MAX_DURATION_SEC // 60
        raise AnalyzerError(f"한 번에 최대 {limit_min}분까지 자를 수 있습니다.")
    return start, duration


def make_clip(video_id: str, start_text: str, end_text: str) -> io.BytesIO:
    """지정 구간을 잘라 mp4 바이트로 반환합니다."""
    start, duration = validate_range(start_text, end_text)

    info, _ = youtube.fetch_info(video_id)
    if info.duration and start >= info.duration:
        raise AnalyzerError("시작 시간이 영상 길이를 넘습니다.")

    work_dir = tempfile.mkdtemp(prefix="ytclip_")
    try:
        source = _download(video_id, work_dir)
        output = os.path.join(work_dir, "clip.mp4")
        cmd = [
            youtube.ffmpeg_path(),
            "-nostdin",
            "-y",
            # 입력 시크 + 재인코딩 = 빠르면서도 프레임 단위로 정확합니다.
            "-ss", str(start),
            "-i", source,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=config.SUBPROCESS_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise UpstreamError("처리 시간이 초과되었습니다.") from exc

        if result.returncode != 0 or not os.path.exists(output):
            # stderr에는 서버 경로가 들어 있으므로 로그로만 남깁니다.
            log.error("ffmpeg 실패: %s", (result.stderr or "")[-1000:])
            raise UpstreamError("영상을 자르는 데 실패했습니다.")

        with open(output, "rb") as fh:
            return io.BytesIO(fh.read())
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _download(video_id: str, work_dir: str) -> str:
    height = config.CLIP_HEIGHT
    opts = youtube.base_opts() | {
        "format": f"bv*[height<={height}]+ba/b[height<={height}]/b",
        "outtmpl": os.path.join(work_dir, "source.%(ext)s"),
        "merge_output_format": "mp4",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube.canonical_url(video_id), download=True)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("클립용 다운로드 실패 %s: %s", video_id, exc)
        raise UpstreamError("영상을 내려받지 못했습니다.") from exc

    for entry in info.get("requested_downloads") or []:
        path = entry.get("filepath")
        if path and os.path.exists(path):
            return path
    for name in sorted(os.listdir(work_dir)):
        if name.startswith("source."):
            return os.path.join(work_dir, name)
    raise UpstreamError("내려받은 영상 파일을 찾을 수 없습니다.")
