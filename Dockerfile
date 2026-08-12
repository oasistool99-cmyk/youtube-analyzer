FROM python:3.12-slim

# ffmpeg는 imageio-ffmpeg가 정적 바이너리로 함께 설치합니다.
# (apt로 또 설치하면 이미지에 두 벌이 들어가고 용량만 커집니다.)

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 루트로 실행하지 않습니다.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# gthread 워커: SSE 연결이 워커를 통째로 붙들지 않도록 스레드를 씁니다.
# 분석 한 건이 수 분 걸릴 수 있어 timeout도 넉넉히 잡습니다.
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-5000} \
    --worker-class gthread \
    --workers ${WEB_CONCURRENCY:-2} \
    --threads ${WEB_THREADS:-8} \
    --timeout ${WEB_TIMEOUT:-900} \
    --graceful-timeout 30 \
    --access-logfile -
