import httpx
import pytest

import anthropic
from analyzer.claude_errors import classify, log_context


def _response(status: int) -> httpx.Response:
    return httpx.Response(
        status_code=status, request=httpx.Request("POST", "https://api.anthropic.com")
    )


def _status_error(cls, status: int, message: str, error_type: str = "invalid_request_error"):
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return cls(message=message, response=_response(status), body=body)


def test_missing_credits_is_actionable():
    exc = _status_error(
        anthropic.BadRequestError,
        400,
        "Your credit balance is too low to access the Anthropic API.",
    )
    error = classify(exc)
    assert "크레딧" in error.message
    assert "Billing" in error.message
    assert error.status_code == 400


def test_invalid_api_key():
    exc = _status_error(
        anthropic.AuthenticationError, 401, "invalid x-api-key", "authentication_error"
    )
    error = classify(exc)
    assert "API 키가 올바르지 않습니다" in error.message
    assert error.status_code == 503


def test_permission_denied_mentions_key_permissions():
    exc = _status_error(
        anthropic.PermissionDeniedError, 403, "not allowed", "permission_error"
    )
    assert "모델을 쓸 수 없습니다" in classify(exc).message


def test_unknown_model():
    exc = _status_error(anthropic.NotFoundError, 404, "model not found", "not_found_error")
    error = classify(exc)
    assert "ANALYSIS_MODEL" in error.message


def test_rate_limit_maps_to_429():
    exc = _status_error(
        anthropic.RateLimitError, 429, "rate limited", "rate_limit_error"
    )
    error = classify(exc)
    assert error.status_code == 429
    assert "잠시 후" in error.message


def test_prompt_too_long():
    exc = _status_error(
        anthropic.BadRequestError, 400, "prompt is too long: 2000000 tokens"
    )
    assert "너무 길어" in classify(exc).message


def test_server_error_suggests_retry():
    exc = _status_error(anthropic.InternalServerError, 500, "internal", "api_error")
    assert "잠시 후" in classify(exc).message


def test_connection_error():
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    assert "연결하지 못했습니다" in classify(exc).message


def test_unknown_bad_request_has_generic_but_scoped_message():
    exc = _status_error(anthropic.BadRequestError, 400, "some new validation rule")
    error = classify(exc)
    assert error.status_code == 400
    assert "설정을 확인" in error.message


def test_raw_body_never_reaches_the_user():
    """응답 본문에 담긴 키 조각이나 내부 정보가 새지 않아야 합니다."""
    exc = _status_error(
        anthropic.BadRequestError,
        400,
        "credit balance too low for key sk-ant-api03-SECRET at /srv/app/x.py",
    )
    message = classify(exc).message
    assert "sk-ant" not in message
    assert "/srv/app" not in message


def test_log_context_keeps_details_for_operators():
    exc = _status_error(anthropic.BadRequestError, 400, "credit balance is too low")
    context = log_context(exc)
    assert "status=400" in context
    assert "credit balance is too low" in context
