from dataclasses import dataclass

import pytest

import config
from analyzer.clip import validate_range
from analyzer.cost import UsageMeter
from analyzer.errors import AnalyzerError, RateLimitedError
from analyzer.ratelimit import SlidingWindowLimiter


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def test_cost_uses_real_usage():
    meter = UsageMeter(model="claude-opus-5")
    meter.add(FakeUsage(input_tokens=1_000_000, output_tokens=100_000))
    # $5 (입력) + $2.5 (출력)
    assert meter.usd == pytest.approx(7.5)
    assert meter.calls == 1


def test_cost_accumulates_across_calls():
    meter = UsageMeter(model="claude-opus-5")
    meter.add(FakeUsage(input_tokens=500_000))
    meter.add(FakeUsage(input_tokens=500_000, output_tokens=40_000))
    assert meter.input_tokens == 1_000_000
    assert meter.usd == pytest.approx(5 + 1.0)
    assert meter.calls == 2


def test_cache_reads_are_cheaper():
    meter = UsageMeter(model="claude-opus-5")
    meter.add(FakeUsage(cache_read_input_tokens=1_000_000))
    assert meter.usd == pytest.approx(0.5)  # 입력가의 10%


def test_unknown_model_falls_back():
    meter = UsageMeter(model="some-future-model")
    meter.add(FakeUsage(input_tokens=1_000_000))
    assert meter.usd > 0


def test_meter_ignores_none():
    meter = UsageMeter()
    meter.add(None)
    assert meter.calls == 0


def test_krw_conversion():
    meter = UsageMeter(model="claude-opus-5")
    meter.add(FakeUsage(input_tokens=1_000_000))
    assert meter.krw == round(5.0 * config.USD_TO_KRW)


# ---- 클립 구간 검증 ----


def test_clip_range_valid():
    assert validate_range("02:35", "05:10") == (155, 155)


def test_clip_end_before_start_rejected():
    with pytest.raises(AnalyzerError):
        validate_range("05:10", "02:35")


def test_clip_equal_times_rejected():
    with pytest.raises(AnalyzerError):
        validate_range("02:35", "02:35")


def test_clip_too_long_rejected():
    limit = config.CLIP_MAX_DURATION_SEC
    with pytest.raises(AnalyzerError):
        validate_range("00:00", f"00:{limit // 60 + 5}:00")


def test_clip_bad_format_rejected():
    with pytest.raises(AnalyzerError):
        validate_range("99:99", "05:10")


# ---- 레이트 리밋 ----


def test_rate_limiter_blocks_after_limit():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(RateLimitedError):
        limiter.check("1.2.3.4")


def test_rate_limiter_is_per_key():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("a")
    limiter.check("b")
    with pytest.raises(RateLimitedError):
        limiter.check("a")
