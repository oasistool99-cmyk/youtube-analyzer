"""IP 단위 슬라이딩 윈도우 레이트 리밋.

인증이 없는 공개 엔드포인트가 영상 다운로드와 유료 API 호출을 유발하므로,
최소한의 남용 방지 장치가 필요합니다. 프로세스 메모리 기반이라 워커마다
독립적으로 동작합니다(정확한 전역 제한이 필요하면 Redis로 옮기세요).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

import config
from analyzer.errors import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                retry_after = int(self._window - (now - hits[0])) + 1
                raise RateLimitedError(
                    f"요청이 너무 잦습니다. {retry_after}초 후에 다시 시도해 주세요."
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


analysis_limiter = SlidingWindowLimiter(
    config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW_SEC
)


def client_key(request) -> str:
    """프록시(Render) 뒤에서도 동작하도록 X-Forwarded-For를 우선 사용합니다."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"
