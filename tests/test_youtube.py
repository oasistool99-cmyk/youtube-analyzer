import pytest

from analyzer.errors import InvalidURLError, SubtitlesUnavailableError
from analyzer.youtube import extract_video_id, select_subtitle_track


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=10",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ],
)
def test_extract_valid(url):
    assert extract_video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        # 문자열 포함 검사만 하던 기존 구현은 이걸 통과시켰습니다.
        "https://evil.example.com/?ref=youtube.com",
        "https://vimeo.com/12345",
        "not a url",
        "",
        "https://www.youtube.com/watch?v=short",
    ],
)
def test_extract_invalid(url):
    with pytest.raises(InvalidURLError):
        extract_video_id(url)


def _track(url="https://sub", ext="vtt"):
    return [{"ext": ext, "url": url}]


def test_manual_subtitles_preferred_over_automatic():
    info = {
        "subtitles": {"en": _track("https://manual-en")},
        "automatic_captions": {"ko": _track("https://auto-ko")},
    }
    url, lang = select_subtitle_track(info)
    assert url == "https://manual-en"
    assert lang == "en"


def test_language_priority_within_manual():
    info = {
        "subtitles": {
            "en": _track("https://manual-en"),
            "ko": _track("https://manual-ko"),
        },
        "automatic_captions": {},
    }
    url, lang = select_subtitle_track(info)
    assert (url, lang) == ("https://manual-ko", "ko")


def test_region_variants_match_base_language():
    info = {"subtitles": {"ko-KR": _track("https://ko-kr")}, "automatic_captions": {}}
    assert select_subtitle_track(info)[0] == "https://ko-kr"


def test_falls_back_to_other_language():
    info = {"subtitles": {"ja": _track("https://ja")}, "automatic_captions": {}}
    assert select_subtitle_track(info)[0] == "https://ja"


def test_non_vtt_tracks_ignored():
    info = {
        "subtitles": {"ko": _track("https://json3", ext="json3")},
        "automatic_captions": {"ko": _track("https://auto-vtt")},
    }
    assert select_subtitle_track(info)[0] == "https://auto-vtt"


def test_no_subtitles_raises():
    with pytest.raises(SubtitlesUnavailableError):
        select_subtitle_track({"subtitles": {}, "automatic_captions": {}})
