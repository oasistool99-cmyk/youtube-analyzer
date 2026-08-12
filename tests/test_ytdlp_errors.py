import pytest

import config
from analyzer import youtube
from analyzer.errors import VideoUnavailableError
from analyzer.ytdlp_errors import classify, is_bot_check


class FakeDownloadError(Exception):
    pass


@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        (
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication.",
            "봇으로 판단",
        ),
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "비공개"),
        ("ERROR: [youtube] abc: Video unavailable", "삭제"),
        ("ERROR: [youtube] abc: This video has been removed by the uploader", "삭제"),
        ("ERROR: [youtube] abc: Sign in to confirm your age", "연령"),
        ("ERROR: [youtube] abc: The uploader has not made this video available in your country", "지역"),
        ("ERROR: [youtube] abc: Join this channel to get access to members-only content", "멤버십"),
        ("ERROR: [youtube] abc: This live event will begin in 3 hours", "예정"),
        ("ERROR: unable to download webpage: HTTP Error 429: Too Many Requests", "제한"),
        ("ERROR: unable to download webpage: The read operation timed out", "연결"),
    ],
)
def test_classification(raw, expected_fragment):
    error = classify(FakeDownloadError(raw))
    assert isinstance(error, VideoUnavailableError)
    assert expected_fragment in error.message


def test_unknown_error_uses_fallback():
    error = classify(FakeDownloadError("ERROR: something entirely new"))
    assert "가져오지 못했습니다" in error.message


def test_custom_fallback():
    error = classify(FakeDownloadError("ERROR: unknown"), "영상을 내려받지 못했습니다.")
    assert error.message == "영상을 내려받지 못했습니다."


def test_bot_check_detection():
    assert is_bot_check(FakeDownloadError("Sign in to confirm you're not a bot"))
    assert not is_bot_check(FakeDownloadError("Private video"))


def test_internal_details_never_leak():
    """원문에 담긴 경로/URL이 사용자 메시지로 새지 않아야 합니다."""
    raw = (
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot; "
        "file /srv/app/analyzer/youtube.py line 42; https://internal.example/token=xyz"
    )
    message = classify(FakeDownloadError(raw)).message
    assert "/srv/app" not in message
    assert "token=xyz" not in message


# ---- 접근 설정 ----


@pytest.fixture(autouse=True)
def reset_cookie_cache():
    youtube._cookiefile_cache = False
    yield
    youtube._cookiefile_cache = False


def test_no_cookies_by_default(monkeypatch):
    monkeypatch.setattr(config, "YTDLP_COOKIES_FILE", "/nonexistent/cookies.txt")
    monkeypatch.setattr(config, "YTDLP_COOKIES_B64", "")
    assert youtube.resolve_cookiefile() is None
    assert "cookiefile" not in youtube.base_opts()


def test_cookie_file_is_copied_to_writable_location(monkeypatch, tmp_path):
    source = tmp_path / "cookies.txt"
    source.write_text("# Netscape HTTP Cookie File\n")
    source.chmod(0o444)  # Render Secret Files처럼 읽기 전용
    monkeypatch.setattr(config, "YTDLP_COOKIES_FILE", str(source))

    resolved = youtube.resolve_cookiefile()
    assert resolved is not None
    # 원본을 그대로 쓰면 yt-dlp가 쿠키를 되쓸 때 실패합니다.
    assert resolved != str(source)
    with open(resolved, "a") as fh:  # 쓰기 가능해야 합니다.
        fh.write("")
    assert youtube.base_opts()["cookiefile"] == resolved


def test_cookie_base64_fallback(monkeypatch):
    import base64

    monkeypatch.setattr(config, "YTDLP_COOKIES_FILE", "/nonexistent/cookies.txt")
    monkeypatch.setattr(
        config,
        "YTDLP_COOKIES_B64",
        base64.b64encode(b"# Netscape HTTP Cookie File\n").decode(),
    )
    resolved = youtube.resolve_cookiefile()
    assert resolved is not None
    with open(resolved) as fh:
        assert "Netscape" in fh.read()


def test_broken_cookie_config_does_not_crash(monkeypatch):
    monkeypatch.setattr(config, "YTDLP_COOKIES_FILE", "/nonexistent/cookies.txt")
    monkeypatch.setattr(config, "YTDLP_COOKIES_B64", "!!! not base64 !!!")
    assert youtube.resolve_cookiefile() is None


def test_proxy_and_player_client_are_passed(monkeypatch):
    monkeypatch.setattr(config, "YTDLP_PROXY", "http://proxy.example:8080")
    monkeypatch.setattr(config, "YTDLP_PLAYER_CLIENT", "android, web")
    opts = youtube.base_opts()
    assert opts["proxy"] == "http://proxy.example:8080"
    assert opts["extractor_args"]["youtube"]["player_client"] == ["android", "web"]


def test_access_status_hides_secrets(monkeypatch):
    monkeypatch.setattr(config, "YTDLP_PROXY", "http://user:pass@proxy.example:8080")
    status = youtube.access_status()
    assert status["proxy"] is True
    assert "pass" not in str(status)
