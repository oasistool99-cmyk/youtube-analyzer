"""분석 파이프라인.

진행 상황을 이벤트로 흘려보내는 제너레이터입니다. SSE 엔드포인트는 이벤트를
그대로 클라이언트에 전달하고, 일반 POST 엔드포인트는 끝까지 소비한 뒤 마지막
결과만 반환합니다. 덕분에 진행 표시가 실제 단계와 일치합니다(기존 프론트엔드는
8초 타이머로 문구만 바꾸고 있었습니다).
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Iterator

import config
from analyzer import cache, claude, vtt, youtube
from analyzer.cost import UsageMeter
from analyzer.errors import VideoTooLongError
from analyzer.timecode import format_timecode, parse_timecode

log = logging.getLogger(__name__)

MODE_SMART = "smart"
MODE_FAST = "fast"


def _progress(step: str, message: str, percent: int) -> dict:
    return {"type": "progress", "step": step, "message": message, "percent": percent}


def _moment_second(timestamp: str, duration: int) -> int | None:
    """모델이 준 타임스탬프를 초로 바꾸고 영상 길이 안으로 제한합니다."""
    try:
        second = parse_timecode(timestamp)
    except ValueError:
        return None
    if duration and second >= duration:
        second = max(0, duration - 2)
    return second


def run(video_id: str, mode: str) -> Iterator[dict]:
    """분석을 실행하며 진행 이벤트와 최종 결과를 순서대로 yield 합니다."""
    cache_key = cache.make_key(video_id, mode)
    cached = cache.results.get(cache_key)
    if cached is not None:
        yield _progress("cache", "이전 분석 결과를 불러왔어요.", 100)
        yield {"type": "result", "data": cached | {"cached": True}}
        return

    meter = UsageMeter()

    yield _progress("info", "영상 정보를 가져오는 중...", 5)
    info, raw_info = youtube.fetch_info(video_id)

    yield _progress("subtitles", "자막을 추출하는 중...", 15)
    cues, lang = youtube.fetch_subtitles(raw_info)

    chunks = vtt.chunk_transcript(cues, config.TRANSCRIPT_CHUNK_CHARS)
    if len(chunks) > config.MAX_TRANSCRIPT_CHUNKS:
        raise VideoTooLongError(
            "자막이 너무 길어 한 번에 분석할 수 없습니다. "
            "더 짧은 영상으로 시도해 주세요."
        )

    if len(chunks) == 1:
        yield _progress("transcript", "AI가 자막을 분석하는 중...", 30)
    else:
        yield _progress(
            "transcript",
            f"자막이 길어 {len(chunks)}개 구간으로 나눠 분석하는 중...",
            30,
        )
    analysis = claude.analyze_transcript(chunks, info.title, info.author, meter)

    frame_descriptions: list[claude.FrameDescription] = []
    moments_used: list[claude.VisualMoment] = []

    if mode == MODE_SMART and analysis.visual_moments:
        moments = analysis.visual_moments[: config.MAX_FRAMES]
        yield _progress(
            "capture", f"핵심 장면 {len(moments)}곳을 캡처하는 중...", 55
        )
        frames, moments_used = _capture_frames(video_id, moments, info.duration)
        if frames:
            yield _progress("vision", "캡처한 화면을 AI가 분석하는 중...", 75)
            frame_descriptions = claude.analyze_frames(frames, meter)

    yield _progress("report", "최종 리포트를 정리하는 중...", 90)
    report = claude.generate_report(analysis, frame_descriptions, meter)

    image_analyses = _match_descriptions(moments_used, frame_descriptions)

    result = {
        "video_info": info.as_dict(),
        "subtitle_language": lang,
        "analysis": {
            "summary": analysis.summary,
            "topic": analysis.topic,
            "keywords": analysis.keywords,
            "visual_moments_count": len(analysis.visual_moments),
        },
        "image_analyses": image_analyses,
        "report": report.model_dump(),
        "stats": {
            "subtitle_cues": len(cues),
            "transcript_chunks": len(chunks),
            "frames_captured": len(image_analyses),
            **meter.as_dict(),
        },
        "cached": False,
    }

    cache.results.set(cache_key, result)
    yield _progress("done", "분석이 끝났어요.", 100)
    yield {"type": "result", "data": result}


def _match_descriptions(
    moments: list[claude.VisualMoment],
    descriptions: list[claude.FrameDescription],
) -> list[dict]:
    """캡처 시점과 화면 설명을 짝지어 줍니다.

    프롬프트에서 순서와 timestamp를 유지하라고 했지만, 모델이 timestamp를
    다르게 표기하면 매칭이 통째로 실패합니다. 개수가 맞으면 순서로 짝짓고,
    그렇지 않을 때만 timestamp로 대조합니다.
    """
    if len(descriptions) == len(moments):
        pairs = zip(moments, (frame.description for frame in descriptions))
    else:
        by_timestamp = {frame.timestamp: frame.description for frame in descriptions}
        pairs = ((moment, by_timestamp.get(moment.timestamp, "")) for moment in moments)

    return [
        {
            "timestamp": moment.timestamp,
            "reason": moment.reason,
            "description": description,
        }
        for moment, description in pairs
        if description
    ]


def _capture_frames(
    video_id: str,
    moments: list[claude.VisualMoment],
    duration: int,
) -> tuple[list[tuple[str, str, str]], list[claude.VisualMoment]]:
    """영상을 한 번만 내려받아 지정된 시점들의 프레임을 캡처합니다."""
    work_dir = tempfile.mkdtemp(prefix="ytanalyzer_")
    frames: list[tuple[str, str, str]] = []
    used: list[claude.VisualMoment] = []
    try:
        video_path = youtube.download_video(video_id, work_dir)
        for moment in moments:
            second = _moment_second(moment.timestamp, duration)
            if second is None:
                continue
            encoded = youtube.capture_frame(video_path, second, work_dir)
            if encoded:
                normalized = format_timecode(second)
                frames.append((normalized, moment.reason, encoded))
                used.append(
                    claude.VisualMoment(
                        timestamp=normalized,
                        reason=moment.reason,
                        context=moment.context,
                    )
                )
    except Exception as exc:  # 캡처 실패가 전체 분석을 막지 않도록.
        log.warning("프레임 캡처 단계 실패 %s: %s", video_id, exc)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return frames, used


def run_to_completion(video_id: str, mode: str) -> dict:
    """진행 이벤트를 버리고 최종 결과만 반환합니다(일반 POST용)."""
    result: dict | None = None
    for event in run(video_id, mode):
        if event["type"] == "result":
            result = event["data"]
    if result is None:  # pragma: no cover - run()은 항상 result를 낸다.
        raise RuntimeError("파이프라인이 결과를 생성하지 않았습니다.")
    return result
