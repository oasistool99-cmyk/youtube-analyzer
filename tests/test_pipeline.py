import pytest

import config
from analyzer import cache, claude, pipeline, youtube
from analyzer.errors import VideoTooLongError
from analyzer.vtt import Cue

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def clean_cache():
    cache.results.clear()
    yield
    cache.results.clear()


@pytest.fixture
def stub(monkeypatch):
    """네트워크와 API를 모두 대체하고, 호출 횟수를 기록합니다."""
    calls = {"transcript": 0, "frames": 0, "report": 0, "download": 0}

    info = youtube.VideoInfo(
        video_id=VIDEO_ID,
        title="테스트 영상",
        author="테스트 채널",
        duration=600,
        thumbnail="https://i.ytimg.com/vi/x/hq.jpg",
    )
    cues = [Cue(start=i * 10, text=f"문장 {i}") for i in range(6)]

    monkeypatch.setattr(youtube, "fetch_info", lambda vid: (info, {}))
    monkeypatch.setattr(youtube, "fetch_subtitles", lambda raw: (cues, "ko"))
    monkeypatch.setattr(
        youtube, "download_video", lambda vid, work_dir: calls.__setitem__(
            "download", calls["download"] + 1
        ) or "/tmp/fake.mp4"
    )
    monkeypatch.setattr(
        youtube, "capture_frame", lambda path, second, work_dir: "ZmFrZQ=="
    )

    analysis = claude.TranscriptAnalysis(
        summary="요약",
        topic="주제",
        keywords=["A", "B"],
        visual_moments=[
            claude.VisualMoment(timestamp="00:00:20", reason="그래프", context="자막"),
        ],
    )

    def fake_transcript(chunks, title, author, meter):
        calls["transcript"] += 1
        return analysis

    def fake_frames(frames, meter):
        calls["frames"] += 1
        return [
            claude.FrameDescription(timestamp=ts, description=f"{ts} 화면 설명")
            for ts, _, _ in frames
        ]

    def fake_report(analysis_arg, frame_descriptions, meter):
        calls["report"] += 1
        return claude.FinalReport(
            headline="제목",
            topic="주제 설명",
            summary_points=["요점 1", "요점 2"],
            visual_notes=[f.description for f in frame_descriptions],
            keywords=["A", "B"],
            takeaway="결론",
        )

    monkeypatch.setattr(claude, "analyze_transcript", fake_transcript)
    monkeypatch.setattr(claude, "analyze_frames", fake_frames)
    monkeypatch.setattr(claude, "generate_report", fake_report)
    return calls


def test_smart_mode_produces_full_result(stub):
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)

    assert result["video_info"]["title"] == "테스트 영상"
    assert result["subtitle_language"] == "ko"
    assert result["report"]["headline"] == "제목"
    assert result["report"]["takeaway"] == "결론"
    assert result["stats"]["subtitle_cues"] == 6
    assert result["stats"]["frames_captured"] == 1
    assert result["image_analyses"][0]["timestamp"] == "00:00:20"
    assert result["image_analyses"][0]["description"] == "00:00:20 화면 설명"
    assert result["cached"] is False
    assert stub["frames"] == 1


def test_fast_mode_skips_download_and_vision(stub):
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_FAST)

    assert result["image_analyses"] == []
    assert result["stats"]["frames_captured"] == 0
    assert stub["download"] == 0
    assert stub["frames"] == 0
    assert stub["report"] == 1


def test_progress_events_are_ordered_and_monotonic(stub):
    events = list(pipeline.run(VIDEO_ID, pipeline.MODE_SMART))
    progress = [e for e in events if e["type"] == "progress"]

    assert events[-1]["type"] == "result"
    assert [e["percent"] for e in progress] == sorted(e["percent"] for e in progress)
    assert progress[-1]["percent"] == 100
    steps = [e["step"] for e in progress]
    assert steps[:2] == ["info", "subtitles"]
    assert "capture" in steps and "vision" in steps


def test_second_run_is_served_from_cache(stub):
    pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert stub["transcript"] == 1

    second = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert second["cached"] is True
    # 캐시 히트에서는 유료 호출이 한 번도 더 일어나지 않아야 합니다.
    assert stub["transcript"] == 1
    assert stub["report"] == 1


def test_cache_is_per_mode(stub):
    pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_FAST)
    assert result["cached"] is False
    assert stub["transcript"] == 2


def test_capture_failure_does_not_abort_analysis(stub, monkeypatch):
    monkeypatch.setattr(
        youtube,
        "download_video",
        lambda vid, work_dir: (_ for _ in ()).throw(RuntimeError("다운로드 실패")),
    )
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    # 화면 분석은 빠지지만 리포트는 정상적으로 나옵니다.
    assert result["image_analyses"] == []
    assert result["report"]["headline"] == "제목"


def _stub_moments(monkeypatch, *timestamps):
    analysis = claude.TranscriptAnalysis(
        summary="요약",
        topic="주제",
        keywords=[],
        visual_moments=[
            claude.VisualMoment(timestamp=ts, reason="이유", context="")
            for ts in timestamps
        ],
    )
    monkeypatch.setattr(claude, "analyze_transcript", lambda chunks, t, a, m: analysis)


def test_out_of_range_timestamp_is_clamped(stub, monkeypatch):
    captured = []

    def fake_capture(path, second, work_dir):
        captured.append(second)
        return "ZmFrZQ=="

    monkeypatch.setattr(youtube, "capture_frame", fake_capture)
    # 영상 길이는 600초인데 모델이 20분 지점을 지목한 경우.
    _stub_moments(monkeypatch, "00:20:00")

    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert captured == [598]
    # 결과에는 실제 캡처한 시점이 담깁니다.
    assert result["image_analyses"][0]["timestamp"] == "00:09:58"


def test_malformed_timestamp_is_skipped(stub, monkeypatch):
    captured = []

    def fake_capture(path, second, work_dir):
        captured.append(second)
        return "ZmFrZQ=="

    monkeypatch.setattr(youtube, "capture_frame", fake_capture)
    _stub_moments(monkeypatch, "00:99:00", "00:01:30")

    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert captured == [90]  # 잘못된 타임코드는 건너뜁니다.
    assert len(result["image_analyses"]) == 1


def test_descriptions_match_by_order_even_if_timestamp_differs(stub, monkeypatch):
    """모델이 timestamp를 다르게 표기해도 짝짓기가 실패하지 않아야 합니다."""
    monkeypatch.setattr(
        claude,
        "analyze_frames",
        lambda frames, meter: [
            claude.FrameDescription(timestamp="0:20", description="다른 표기 설명")
            for _ in frames
        ],
    )
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert len(result["image_analyses"]) == 1
    assert result["image_analyses"][0]["timestamp"] == "00:00:20"
    assert result["image_analyses"][0]["description"] == "다른 표기 설명"


def test_missing_description_is_dropped(stub, monkeypatch):
    monkeypatch.setattr(claude, "analyze_frames", lambda frames, meter: [])
    result = pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
    assert result["image_analyses"] == []
    assert result["stats"]["frames_captured"] == 0


def test_long_transcript_is_rejected_not_truncated(stub, monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPT_CHUNK_CHARS", 20)
    monkeypatch.setattr(config, "MAX_TRANSCRIPT_CHUNKS", 2)
    with pytest.raises(VideoTooLongError):
        pipeline.run_to_completion(VIDEO_ID, pipeline.MODE_SMART)
