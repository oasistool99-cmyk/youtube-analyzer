"""환경 변수 기반 설정.

모든 값은 배포 환경에서 덮어쓸 수 있습니다. 기본값은 Render 무료 플랜
(512MB RAM, 임시 디스크, 2 워커)에서 안전하게 동작하도록 잡았습니다.
"""

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# ---- Claude ----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# 모델 ID는 여기 한 곳에서만 관리합니다.
ANALYSIS_MODEL = os.environ.get("ANALYSIS_MODEL", "claude-opus-5").strip()

# low | medium | high | xhigh | max
# medium은 자막 요약 수준의 작업에서 품질 대비 비용이 가장 좋습니다.
# 더 깊은 분석이 필요하면 high 이상으로 올리세요.
ANALYSIS_EFFORT = os.environ.get("ANALYSIS_EFFORT", "medium").strip()

MAX_TOKENS = _int("MAX_TOKENS", 16000)

# ---- 영상 제약 ----
MAX_VIDEO_DURATION_SEC = _int("MAX_VIDEO_DURATION_SEC", 3600)
MAX_FRAMES = _int("MAX_FRAMES", 8)
FRAME_SOURCE_HEIGHT = _int("FRAME_SOURCE_HEIGHT", 480)
FRAME_MAX_WIDTH = _int("FRAME_MAX_WIDTH", 1024)

# 자막이 길면 잘라내지 않고 청크로 나눠 분석합니다.
TRANSCRIPT_CHUNK_CHARS = _int("TRANSCRIPT_CHUNK_CHARS", 12000)
MAX_TRANSCRIPT_CHUNKS = _int("MAX_TRANSCRIPT_CHUNKS", 12)

SUBTITLE_LANG_PRIORITY = [
    lang.strip()
    for lang in os.environ.get("SUBTITLE_LANG_PRIORITY", "ko,en").split(",")
    if lang.strip()
]

# ---- 클리핑 ----
CLIP_MAX_DURATION_SEC = _int("CLIP_MAX_DURATION_SEC", 600)
CLIP_HEIGHT = _int("CLIP_HEIGHT", 720)

# ---- 캐시 / 레이트 리밋 ----
CACHE_TTL_SEC = _int("CACHE_TTL_SEC", 3600)
CACHE_MAX_ENTRIES = _int("CACHE_MAX_ENTRIES", 64)
RATE_LIMIT_REQUESTS = _int("RATE_LIMIT_REQUESTS", 5)
RATE_LIMIT_WINDOW_SEC = _int("RATE_LIMIT_WINDOW_SEC", 600)

# ---- 기타 ----
# 비용 표시는 환율에 따라 달라지므로 근사치입니다.
USD_TO_KRW = _float("USD_TO_KRW", 1400.0)

SUBPROCESS_TIMEOUT_SEC = _int("SUBPROCESS_TIMEOUT_SEC", 600)

# CORS 허용 출처. 기본은 동일 출처만(프론트엔드를 이 서버가 서빙하므로 충분).
# 외부 페이지에서 호출하려면 쉼표로 구분해 명시하세요.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]


def require_api_key() -> str:
    """분석 기능 사용 전 API 키를 확인합니다."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다. "
            "Render 대시보드의 Environment 탭에서 추가하세요."
        )
    return ANTHROPIC_API_KEY
