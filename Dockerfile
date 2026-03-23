FROM python:3.12-slim

# ffmpeg 설치 (프레임 캡처용)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render는 PORT 환경변수를 자동 설정
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --timeout 300 --workers 2 app:app
