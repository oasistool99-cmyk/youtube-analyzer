"""사용자에게 그대로 보여줄 수 있는 오류 타입.

내부 경로나 스택 트레이스가 클라이언트로 새지 않도록, 표면에 노출할 메시지는
반드시 이 예외에 담고 상세 내용은 로그로만 남깁니다.
"""


class AnalyzerError(Exception):
    """클라이언트에 메시지를 그대로 전달해도 안전한 오류."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InvalidURLError(AnalyzerError):
    status_code = 400


class VideoTooLongError(AnalyzerError):
    status_code = 400


class SubtitlesUnavailableError(AnalyzerError):
    status_code = 404


class VideoUnavailableError(AnalyzerError):
    status_code = 502


class RateLimitedError(AnalyzerError):
    status_code = 429


class UpstreamError(AnalyzerError):
    """Claude API 또는 ffmpeg 등 외부 의존성 실패."""

    status_code = 502
