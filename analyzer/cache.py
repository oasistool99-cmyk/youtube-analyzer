"""분석 결과 TTL 캐시.

같은 영상을 다시 분석하면 API 비용이 그대로 다시 나갑니다. 프로세스 메모리에
짧게 보관해 중복 요청을 막습니다(워커별로 독립이며 재시작하면 사라집니다).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

import config


class TTLCache:
    def __init__(self, max_entries: int, ttl_seconds: int):
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if now - stored_at > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: dict) -> None:
        now = time.monotonic()
        with self._lock:
            self._data[key] = (now, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


results = TTLCache(config.CACHE_MAX_ENTRIES, config.CACHE_TTL_SEC)


def make_key(video_id: str, mode: str) -> str:
    return f"{config.ANALYSIS_MODEL}:{mode}:{video_id}"
