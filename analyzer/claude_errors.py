"""Anthropic API 오류를 원인별로 분류합니다.

`analyzer/ytdlp_errors.py`와 같은 이유입니다. "AI 분석 중 오류가 발생했습니다"
로는 크레딧이 없는 건지, 키가 틀린 건지, 모델 ID가 잘못된 건지 알 수 없어
매번 서버 로그를 봐야 합니다. 상태 코드와 API가 준 오류 유형으로 갈라
운영자가 바로 조치할 수 있는 메시지를 만듭니다.
"""

from __future__ import annotations

import anthropic

from analyzer.errors import UpstreamError

# 400 응답 본문에서 찾을 문자열 → 사용자 메시지
_BAD_REQUEST_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("credit balance", "insufficient credit", "billing"),
        "Anthropic 계정의 크레딧이 부족합니다. "
        "console.anthropic.com → Billing 에서 충전해 주세요.",
    ),
    (
        ("prompt is too long", "exceed", "context window", "too many tokens"),
        "영상이 너무 길어 한 번에 처리할 수 없습니다. "
        "더 짧은 영상으로 시도해 주세요.",
    ),
    (
        ("data retention", "zero data retention"),
        "이 모델은 조직의 데이터 보존 설정 때문에 사용할 수 없습니다. "
        "Anthropic Console에서 설정을 확인해 주세요.",
    ),
]


def classify(exc: Exception) -> UpstreamError:
    """Anthropic 예외를 사용자에게 보여줄 수 있는 오류로 바꿉니다.

    구체적인 하위 클래스부터 검사합니다(모두 APIStatusError의 자식이라
    순서가 뒤바뀌면 전부 뭉뚱그려집니다).
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return UpstreamError(
            "Anthropic API 키가 올바르지 않습니다. "
            "ANTHROPIC_API_KEY 값을 다시 확인해 주세요.",
            503,
        )

    if isinstance(exc, anthropic.PermissionDeniedError):
        return UpstreamError(
            "이 API 키로는 해당 모델을 쓸 수 없습니다. "
            "Anthropic Console에서 키 권한과 결제 상태를 확인해 주세요.",
            503,
        )

    if isinstance(exc, anthropic.NotFoundError):
        return UpstreamError(
            "설정된 모델을 찾을 수 없습니다. ANALYSIS_MODEL 값을 확인해 주세요.",
            503,
        )

    if isinstance(exc, anthropic.RateLimitError):
        return UpstreamError(
            "AI 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.", 429
        )

    if isinstance(exc, anthropic.BadRequestError):
        text = (getattr(exc, "message", "") or str(exc)).lower()
        for needles, message in _BAD_REQUEST_RULES:
            if any(needle in text for needle in needles):
                return UpstreamError(message, 400)
        return UpstreamError("AI 요청이 거부되었습니다. 설정을 확인해 주세요.", 400)

    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        if status >= 500:
            return UpstreamError(
                "AI 서버가 일시적으로 불안정합니다. 잠시 후 다시 시도해 주세요."
            )
        return UpstreamError("AI 분석 중 오류가 발생했습니다.")

    if isinstance(exc, anthropic.APIConnectionError):
        return UpstreamError("AI 서버에 연결하지 못했습니다.")

    return UpstreamError("AI 분석 중 오류가 발생했습니다.")


def log_context(exc: Exception) -> str:
    """로그에 남길 상세 정보(응답 본문 포함). 사용자에게는 보내지 않습니다."""
    status = getattr(exc, "status_code", None)
    error_type = getattr(exc, "type", None)
    message = getattr(exc, "message", None) or str(exc)
    request_id = getattr(exc, "request_id", None)
    parts = [f"status={status}", f"type={error_type}", f"request_id={request_id}"]
    return " ".join(parts) + f" message={message}"
