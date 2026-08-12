"""yt-dlp 오류를 원인별로 분류합니다.

"영상 정보를 가져오지 못했습니다"라는 뭉뚱그린 메시지로는 운영자가 무엇을
고쳐야 할지 알 수 없습니다. yt-dlp가 남기는 원문을 패턴으로 분류해, 사용자가
할 수 있는 일(다른 영상 시도)과 운영자가 할 일(쿠키/프록시 설정)을 구분해
안내합니다. 원문 자체는 로그에만 남습니다.
"""

from __future__ import annotations

from analyzer.errors import AnalyzerError, VideoUnavailableError

# (판별 문자열들, 사용자에게 보여줄 메시지)
_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "sign in to confirm you're not a bot",
            "sign in to confirm youre not a bot",
            "confirm you're not a bot",
            "not a bot",
            "failed to extract any player response",
        ),
        "유튜브가 이 서버의 접속을 봇으로 판단해 차단했습니다. "
        "서버에 유튜브 쿠키(YTDLP_COOKIES_FILE)를 설정하면 해결됩니다.",
    ),
    (
        ("private video", "this video is private"),
        "비공개 영상입니다.",
    ),
    (
        (
            "video unavailable",
            "has been removed",
            "no longer available",
            "account associated with this video has been terminated",
        ),
        "삭제되었거나 더 이상 볼 수 없는 영상입니다.",
    ),
    (
        ("age-restricted", "inappropriate for some users", "confirm your age"),
        "연령 제한이 걸린 영상이라 분석할 수 없습니다.",
    ),
    (
        (
            # yt-dlp 원문이 여러 형태라 공통 부분으로 잡습니다:
            # "not available in your country",
            # "has not made this video available in your country"
            "available in your country",
            "blocked it in your country",
            "geo restricted",
            "geo-restricted",
        ),
        "이 서버가 있는 지역에서는 볼 수 없는 영상입니다.",
    ),
    (
        ("members-only", "join this channel", "paid content", "purchase"),
        "멤버십/유료 회원 전용 영상이라 분석할 수 없습니다.",
    ),
    (
        ("this live event will begin", "premieres in", "live event will begin"),
        "아직 시작하지 않은 예정 영상입니다.",
    ),
    (
        ("is not a valid url", "unsupported url"),
        "지원하지 않는 주소입니다.",
    ),
    (
        ("timed out", "timeout", "connection reset", "temporary failure"),
        "유튜브에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ),
    (
        ("http error 429", "too many requests"),
        "유튜브가 이 서버의 요청을 일시적으로 제한했습니다. "
        "잠시 후 다시 시도해 주세요.",
    ),
]

_FALLBACK = "영상 정보를 가져오지 못했습니다. 비공개이거나 삭제된 영상일 수 있습니다."


def classify(exc: Exception, fallback: str | None = None) -> AnalyzerError:
    """yt-dlp 예외를 사용자에게 보여줄 수 있는 오류로 바꿉니다."""
    text = str(exc).lower()
    for needles, message in _RULES:
        if any(needle in text for needle in needles):
            return VideoUnavailableError(message)
    return VideoUnavailableError(fallback or _FALLBACK)


def is_bot_check(exc: Exception) -> bool:
    """봇 차단 여부. 로그 경고 수위를 높이는 데 씁니다."""
    text = str(exc).lower()
    return any(needle in text for needle in _RULES[0][0])
