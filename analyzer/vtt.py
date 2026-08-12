"""WebVTT 자막 파싱.

유튜브 자동 생성 자막은 "롤링" 방식이라 같은 문장이 조금씩 길어지며 반복됩니다.

    00:00:01.000 --> 00:00:03.000   안녕하세요 오늘은
    00:00:03.000 --> 00:00:05.000   안녕하세요 오늘은 파이썬을

전역 중복 제거(set)로 걸러내면 영상 뒷부분에서 정당하게 반복된 문장까지
사라지므로, 여기서는 직전 큐와의 접두사 관계만 보고 병합합니다.
"""

import re
from dataclasses import dataclass

_TIMESTAMP_RE = re.compile(
    r"^(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_INDEX_RE = re.compile(r"^\d+$")
_HEADER_PREFIXES = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")


@dataclass(frozen=True)
class Cue:
    start: int  # 초
    text: str

    @property
    def timestamp(self) -> str:
        h, rem = divmod(self.start, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


def _clean(line: str) -> str:
    line = _TAG_RE.sub("", line)
    return " ".join(line.split())


def parse_vtt(vtt_text: str) -> list[Cue]:
    """VTT 문자열을 시간순 큐 목록으로 변환합니다."""
    cues: list[Cue] = []
    current_start: int | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current_start is None or not buffer:
            buffer = []
            return
        text = _clean(" ".join(buffer))
        if text:
            cues.append(Cue(start=current_start, text=text))
        buffer = []

    for raw in vtt_text.splitlines():
        line = raw.strip()
        match = _TIMESTAMP_RE.match(line)
        if match:
            flush()
            hours, minutes, seconds = match.group(1), match.group(2), match.group(3)
            current_start = (
                int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
            )
            continue
        if not line:
            continue
        if line.startswith(_HEADER_PREFIXES) or _CUE_INDEX_RE.match(line):
            continue
        buffer.append(line)

    flush()
    return _collapse_rolling(cues)


def _collapse_rolling(cues: list[Cue]) -> list[Cue]:
    """직전 큐를 확장하기만 한 롤링 자막을 하나로 합칩니다."""
    merged: list[Cue] = []
    for cue in cues:
        if merged:
            previous = merged[-1]
            if cue.text == previous.text:
                continue
            if cue.text.startswith(previous.text):
                # 직전 큐가 현재 큐의 접두사 → 더 완전한 쪽으로 교체.
                merged[-1] = Cue(start=previous.start, text=cue.text)
                continue
            if previous.text.startswith(cue.text):
                # 이미 더 긴 문장을 갖고 있음.
                continue
        merged.append(cue)
    return merged


def to_transcript(cues: list[Cue]) -> str:
    """`[HH:MM:SS] 문장` 형태의 평문 트랜스크립트."""
    return "\n".join(f"[{cue.timestamp}] {cue.text}" for cue in cues)


def chunk_transcript(cues: list[Cue], chunk_chars: int) -> list[str]:
    """자막을 잘라내지 않고, 문자 수 기준으로 청크 목록을 만듭니다.

    타임스탬프 경계에서만 나누므로 각 청크는 그 자체로 읽을 수 있습니다.
    """
    if chunk_chars <= 0:
        return [to_transcript(cues)] if cues else []

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for cue in cues:
        line = f"[{cue.timestamp}] {cue.text}"
        if current and size + len(line) + 1 > chunk_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
