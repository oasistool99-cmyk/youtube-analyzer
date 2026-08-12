from analyzer.vtt import Cue, chunk_transcript, parse_vtt, to_transcript

ROLLING = """WEBVTT
Kind: captions
Language: ko

00:00:01.000 --> 00:00:03.000
안녕하세요 오늘은

00:00:03.000 --> 00:00:05.000
안녕하세요 오늘은 파이썬을

00:00:05.000 --> 00:00:07.000
안녕하세요 오늘은 파이썬을 다룹니다

00:00:20.000 --> 00:00:22.000
그럼 시작하겠습니다
"""


def test_rolling_captions_collapse():
    cues = parse_vtt(ROLLING)
    assert [cue.text for cue in cues] == [
        "안녕하세요 오늘은 파이썬을 다룹니다",
        "그럼 시작하겠습니다",
    ]
    assert cues[0].start == 1
    assert cues[0].timestamp == "00:00:01"


def test_repeated_phrase_is_kept():
    """전역 중복 제거였다면 뒤쪽 '감사합니다'가 사라졌을 것입니다."""
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
감사합니다

00:01:00.000 --> 00:01:02.000
본론입니다

00:02:00.000 --> 00:02:02.000
감사합니다
"""
    texts = [cue.text for cue in parse_vtt(vtt)]
    assert texts == ["감사합니다", "본론입니다", "감사합니다"]


def test_tags_and_cue_numbers_removed():
    vtt = """WEBVTT

1
00:00:01.000 --> 00:00:02.000
<c.colorE5E5E5>코드를</c> <00:00:01.500>보면
"""
    assert [cue.text for cue in parse_vtt(vtt)] == ["코드를 보면"]


def test_short_timestamp_form():
    vtt = "WEBVTT\n\n01:05.000 --> 01:07.000\n짧은 형식\n"
    cues = parse_vtt(vtt)
    assert cues[0].start == 65


def test_hours_over_99():
    vtt = "WEBVTT\n\n100:00:00.000 --> 100:00:02.000\n아주 긴 영상\n"
    assert parse_vtt(vtt)[0].start == 360000


def test_empty_input():
    assert parse_vtt("WEBVTT\n\n") == []


def test_to_transcript():
    cues = [Cue(start=0, text="첫째"), Cue(start=61, text="둘째")]
    assert to_transcript(cues) == "[00:00:00] 첫째\n[00:01:01] 둘째"


def test_chunk_transcript_splits_without_dropping_content():
    cues = [Cue(start=i * 5, text=f"문장{i}" * 10) for i in range(40)]
    chunks = chunk_transcript(cues, 400)
    assert len(chunks) > 1
    # 잘라내기가 아니라 나누기이므로 모든 큐가 남아 있어야 합니다.
    joined = "\n".join(chunks)
    for cue in cues:
        assert cue.text in joined
    for chunk in chunks:
        assert chunk.startswith("[")


def test_chunk_single_when_short():
    cues = [Cue(start=0, text="짧음")]
    assert chunk_transcript(cues, 10000) == ["[00:00:00] 짧음"]
