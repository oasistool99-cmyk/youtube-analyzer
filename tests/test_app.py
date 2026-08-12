import json

import pytest

import app as app_module
import config
from analyzer import pipeline
from analyzer.errors import SubtitlesUnavailableError
from analyzer.ratelimit import analysis_limiter


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    analysis_limiter.reset()
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


def _sse_events(response) -> list[dict]:
    events = []
    for block in response.get_data(as_text=True).split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_health_reports_model(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["model"] == config.ANALYSIS_MODEL


def test_home_serves_analyzer_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"YouTube \xec\x8a\xa4\xeb\xa7\x88\xed\x8a\xb8" in response.data


def test_clip_page_is_reachable(client):
    assert client.get("/clip").status_code == 200


def test_security_headers_present(client):
    headers = client.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_invalid_url_returns_400(client):
    response = client.post("/api/analyze", json={"url": "https://evil.com/?a=youtube.com"})
    assert response.status_code == 400
    assert "YouTube" in response.get_json()["error"]


def test_missing_api_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    response = client.post(
        "/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
    )
    assert response.status_code == 503
    # 환경 변수 이름 같은 내부 정보는 노출하지 않습니다.
    assert "ANTHROPIC_API_KEY" not in response.get_json()["error"]


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(
        pipeline, "run_to_completion", lambda video_id, mode: {"ok": True}
    )
    for _ in range(config.RATE_LIMIT_REQUESTS):
        assert (
            client.post(
                "/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
            ).status_code
            == 200
        )
    response = client.post("/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert response.status_code == 429


def test_analyze_text_forces_fast_mode(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        pipeline,
        "run_to_completion",
        lambda video_id, mode: seen.update(video_id=video_id, mode=mode) or {},
    )
    client.post("/api/analyze-text", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert seen == {"video_id": "dQw4w9WgXcQ", "mode": pipeline.MODE_FAST}


def test_stream_emits_progress_then_result(client, monkeypatch):
    def fake_run(video_id, mode):
        yield {"type": "progress", "step": "info", "message": "시작", "percent": 5}
        yield {"type": "result", "data": {"video_info": {"title": "테스트"}}}

    monkeypatch.setattr(pipeline, "run", fake_run)
    response = client.get("/api/analyze/stream?url=https://youtu.be/dQw4w9WgXcQ")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"

    events = _sse_events(response)
    assert [event["type"] for event in events] == ["progress", "result"]
    assert events[1]["data"]["video_info"]["title"] == "테스트"


def test_stream_reports_pipeline_error_as_event(client, monkeypatch):
    def fake_run(video_id, mode):
        yield {"type": "progress", "step": "info", "message": "시작", "percent": 5}
        raise SubtitlesUnavailableError("자막이 없습니다.")

    monkeypatch.setattr(pipeline, "run", fake_run)
    events = _sse_events(
        client.get("/api/analyze/stream?url=https://youtu.be/dQw4w9WgXcQ")
    )
    assert events[-1] == {"type": "error", "message": "자막이 없습니다."}


def test_stream_hides_unexpected_error_details(client, monkeypatch):
    def fake_run(video_id, mode):
        raise ValueError("/srv/app/secret/path.py 내부 오류")
        yield  # pragma: no cover

    monkeypatch.setattr(pipeline, "run", fake_run)
    events = _sse_events(
        client.get("/api/analyze/stream?url=https://youtu.be/dQw4w9WgXcQ")
    )
    assert events[-1]["type"] == "error"
    assert "/srv/app" not in events[-1]["message"]


def test_clip_requires_times(client):
    response = client.post("/api/clip", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert response.status_code == 400


def test_unexpected_error_is_not_leaked(client, monkeypatch):
    def boom(video_id, mode):
        raise ValueError("/srv/app/analyzer/pipeline.py:42 내부 상태")

    monkeypatch.setattr(pipeline, "run_to_completion", boom)
    app_module.app.config.update(TESTING=False)
    try:
        response = client.post(
            "/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
        )
        assert response.status_code == 500
        assert response.get_json()["error"] == "서버에서 오류가 발생했습니다."
    finally:
        app_module.app.config.update(TESTING=True)
