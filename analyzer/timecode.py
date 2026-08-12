"""타임코드 파싱/포맷.

`MM:SS`, `HH:MM:SS`, `HH:MM:SS.mmm`을 받아 초로 바꿉니다. 기존 정규식
`^\\d{1,2}(:\\d{1,2}){1,2}$`는 `99:99` 같은 값을 통과시켰기 때문에, 여기서는
분/초가 60 미만인지까지 검사합니다.
"""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")


class InvalidTimecode(ValueError):
    pass


def parse_timecode(value: str) -> int:
    """`MM:SS` 또는 `HH:MM:SS`를 초로 변환합니다."""
    if not isinstance(value, str):
        raise InvalidTimecode("시간 형식이 올바르지 않습니다. (예: 02:35)")
    match = _TIME_RE.match(value.strip())
    if not match:
        raise InvalidTimecode("시간 형식이 올바르지 않습니다. (예: 02:35)")

    hours, minutes, seconds, _ = match.groups()
    minutes_i, seconds_i = int(minutes), int(seconds)

    if hours is None:
        # MM:SS - 분은 60 이상도 허용(예: 90:00 = 1시간 30분).
        if seconds_i >= 60:
            raise InvalidTimecode("초는 59를 넘을 수 없습니다.")
        return minutes_i * 60 + seconds_i

    if minutes_i >= 60 or seconds_i >= 60:
        raise InvalidTimecode("분과 초는 59를 넘을 수 없습니다.")
    return int(hours) * 3600 + minutes_i * 60 + seconds_i


def format_timecode(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
