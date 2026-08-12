"""YouTube 스마트 분석기 — HTTP 계층.

라우팅과 입출력만 담당하고, 실제 로직은 `analyzer` 패키지에 있습니다.
"""

from __future__ import annotations

import json
import logging
import os

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

import config
from analyzer import clip, pipeline, youtube
from analyzer.errors import AnalyzerError
from analyzer.ratelimit import analysis_limiter, client_key

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", static_url_path="/static")

if config.CORS_ORIGINS:
    from flask_cors import CORS

    CORS(app, origins=config.CORS_ORIGINS)

_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://i.ytimg.com https://*.ggpht.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


@app.after_request
def security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    return response


@app.errorhandler(AnalyzerError)
def handle_analyzer_error(error: AnalyzerError):
    return jsonify({"error": error.message}), error.status_code


@app.errorhandler(Exception)
def handle_unexpected(error: Exception):
    # 내부 예외 내용은 로그에만 남기고 클라이언트에는 일반 메시지를 줍니다.
    log.exception("처리되지 않은 오류: %s", error)
    return jsonify({"error": "서버에서 오류가 발생했습니다."}), 500


# --------------------------------------------------------------------------
# 페이지
# --------------------------------------------------------------------------


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/clip")
def clip_page():
    return send_from_directory(app.static_folder, "clip.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "model": config.ANALYSIS_MODEL,
            "effort": config.ANALYSIS_EFFORT,
            "api_key_configured": bool(config.ANTHROPIC_API_KEY),
            "max_video_duration_sec": config.MAX_VIDEO_DURATION_SEC,
        }
    )


# --------------------------------------------------------------------------
# 분석
# --------------------------------------------------------------------------


def _read_url(payload: dict) -> str:
    return youtube.extract_video_id((payload.get("url") or "").strip())


def _guard() -> None:
    """레이트 리밋과 API 키를 요청 처리 전에 확인합니다."""
    try:
        config.require_api_key()
    except RuntimeError as exc:
        # 설정 누락은 서버 문제이므로 503으로, 환경 변수 이름은 로그에만 남깁니다.
        log.error("설정 오류: %s", exc)
        raise AnalyzerError(
            "서버에 AI API 키가 설정되지 않았습니다. 관리자에게 문의해 주세요.", 503
        ) from exc
    analysis_limiter.check(client_key(request))


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    video_id = _read_url(payload)
    mode = (
        pipeline.MODE_FAST
        if payload.get("capture_frames") is False
        else pipeline.MODE_SMART
    )
    _guard()
    return jsonify(pipeline.run_to_completion(video_id, mode))


@app.post("/api/analyze-text")
def analyze_text():
    payload = request.get_json(silent=True) or {}
    video_id = _read_url(payload)
    _guard()
    return jsonify(pipeline.run_to_completion(video_id, pipeline.MODE_FAST))


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/api/analyze/stream")
def analyze_stream():
    """진행 상황을 실시간으로 흘려보내는 SSE 엔드포인트.

    분석에 수 분이 걸리므로, 응답을 끝까지 붙들고 있는 대신 단계별 이벤트를
    보냅니다. 프록시/게이트웨이의 유휴 타임아웃에도 걸리지 않습니다.
    """
    video_id = youtube.extract_video_id(request.args.get("url", ""))
    mode = (
        pipeline.MODE_FAST
        if request.args.get("mode") == pipeline.MODE_FAST
        else pipeline.MODE_SMART
    )
    # 스트림을 열기 전에 검사해야 429/400이 제대로 된 HTTP 상태로 나갑니다.
    _guard()

    def generate():
        try:
            for event in pipeline.run(video_id, mode):
                yield _sse(event)
        except AnalyzerError as exc:
            yield _sse({"type": "error", "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            log.exception("분석 중 오류: %s", exc)
            yield _sse({"type": "error", "message": "서버에서 오류가 발생했습니다."})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --------------------------------------------------------------------------
# 구간 자르기(부가 기능)
# --------------------------------------------------------------------------


@app.post("/api/clip")
def make_clip():
    payload = request.get_json(silent=True) or {}
    video_id = _read_url(payload)
    start = (payload.get("start") or "").strip()
    end = (payload.get("end") or "").strip()
    if not start or not end:
        raise AnalyzerError("시작 시간과 끝 시간을 모두 입력해 주세요.")

    analysis_limiter.check(client_key(request))

    buffer = clip.make_clip(video_id, start, end)
    filename = f"clip_{start.replace(':', '')}_{end.replace(':', '')}.mp4"
    # BytesIO로 반환하므로 임시 파일 삭제와 응답 전송이 경쟁하지 않습니다.
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="video/mp4",
    )



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
