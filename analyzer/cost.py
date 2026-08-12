"""실제 토큰 사용량 기반 비용 계산.

기존 구현은 `프레임수 * 30 + 200` 같은 임의 상수를 썼습니다. 여기서는 응답의
`usage`를 누적해 모델 공개 단가로 계산합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config

# USD / 100만 토큰 (input, output)
_PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_DEFAULT_PRICING = (5.0, 25.0)

_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_MULTIPLIER = 1.25


@dataclass
class UsageMeter:
    """여러 API 호출에 걸친 토큰 사용량을 누적합니다."""

    model: str = field(default_factory=lambda: config.ANALYSIS_MODEL)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0

    def add(self, usage) -> None:
        if usage is None:
            return
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    @property
    def usd(self) -> float:
        price_in, price_out = _PRICING.get(self.model, _DEFAULT_PRICING)
        billable_input = (
            self.input_tokens
            + self.cache_read_tokens * _CACHE_READ_MULTIPLIER
            + self.cache_write_tokens * _CACHE_WRITE_MULTIPLIER
        )
        return (
            billable_input * price_in + self.output_tokens * price_out
        ) / 1_000_000

    @property
    def krw(self) -> int:
        return round(self.usd * config.USD_TO_KRW)

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "api_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "estimated_cost_usd": round(self.usd, 4),
            # 환율 변동이 있으므로 근사치입니다.
            "estimated_cost_krw": self.krw,
        }
