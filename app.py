import os
import subprocess
import tempfile
import uuid
import re
from flask import Flask, jsonify, request, send_file, render_template_string, after_this_request
from flask_cors import CORS
import yt_dlp
import imageio_ffmpeg

app = Flask(__name__)
CORS(app)

# imageio-ffmpeg가 제공하는 ffmpeg 실행 파일 경로
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()


# ---- HTML 페이지 (사용자 화면) ----
HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>유튜브 영상 자르기</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif;
    max-width: 640px; margin: 0 auto; padding: 24px;
    background: #f5f5f7; color: #1d1d1f;
  }
  h1 { font-size: 28px; margin-bottom: 8px; }
  .sub { color: #6e6e73; margin-bottom: 24px; }
  .card {
    background: white; padding: 24px; border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  }
  label { display: block; font-weight: 600; margin: 12px 0 6px; font-size: 14px; }
  input {
    width: 100%; padding: 12px; font-size: 16px;
    border: 1px solid #d2d2d7; border-radius: 8px;
    transition: border 0.2s;
  }
  input:focus { outline: none; border-color: #0071e3; }
  .row { display: flex; gap: 12px; }
  .row > div { flex: 1; }
  button {
    width: 100%; padding: 14px; font-size: 16px; font-weight: 600;
    background: #0071e3; color: white; border: none; border-radius: 8px;
    cursor: pointer; margin-top: 20px; transition: background 0.2s;
  }
  button:hover:not(:disabled) { background: #0058b8; }
  button:disabled { background: #999; cursor: not-allowed; }
  #status {
    margin-top: 16px; padding: 12px; border-radius: 8px;
    font-size: 14px; display: none;
  }
  #status.show { display: block; }
  #status.info { background: #e3f2fd; color: #0d47a1; }
  #status.error { background: #ffebee; color: #c62828; }
  #status.success { background: #e8f5e9; color: #2e7d32; }
  .hint { font-size: 12px; color: #6e6e73; margin-top: 4px; }
</style>
</head>
<body>
  <h1>🎬 유튜브 영상 자르기</h1>
  <p class="sub">YouTube URL과 시작/끝 시간만 입력하면 잘라서 다운로드해 드립니다.</p>

  <div class="card">
    <label>YouTube 주소</label>
    <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=...">

    <div class="row">
      <div>
        <label>시작 시간</label>
        <input type="text" id="start" placeholder="02:35">
        <div class="hint">분:초 또는 시:분:초</div>
      </div>
      <div>
        <label>끝 시간</label>
        <input type="text" id="end" placeholder="05:10">
        <div class="hint">분:초 또는 시:분:초</div>
      </div>
    </div>

    <button id="btn" onclick="clipVideo()">🎬 자르고 다운로드</button>
    <div id="status"></div>
  </div>

<script>
async function clipVideo() {
  const url = document.getElementById('url').value.trim();
  const start = document.getElementById('start').value.trim();
  const end = document.getElementById('end').value.trim();
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');

  if (!url || !start || !end) {
    showStatus('error', '모든 항목을 입력해 주세요.');
    return;
  }

  btn.disabled = true;
  btn.textContent = '⏳ 처리 중...';
  showStatus('info', '영상을 다운로드하고 자르는 중입니다. 1~3분 소요될 수 있어요.');

  try {
    const res = await fetch('/api/clip', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, start, end})
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({error: 'Unknown error'}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const blob = await res.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = `clip_${start.replace(/:/g,'')}_${end.replace(/:/g,'')}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(downloadUrl);

    showStatus('success', '✅ 다운로드 완료! 다운로드 폴더를 확인하세요.');
  } catch (e) {
    showStatus('error', '❌ 오류: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🎬 자르고 다운로드';
  }
}

function showStatus(type, msg) {
  const status = document.getElementById('status');
  status.className = 'show ' + type;
  status.textContent = msg;
}
</script>
</body>
</html>
"""


def validate_time(t):
    """시간 형식 확인: MM:SS 또는 HH:MM:SS"""
    if not re.match(r'^\d{1,2}(:\d{1,2}){1,2}$', t):
        return False
    return True


# ---- 라우트 ----
@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "ffmpeg": FFMPEG_PATH})


@app.route("/api/clip", methods=["POST"])
def clip():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    start = (data.get("start") or "").strip()
    end = (data.get("end") or "").strip()

    # 1. 입력 검증
    if not url or not start or not end:
        return jsonify({"error": "url, start, end 가 모두 필요합니다."}), 400

    if "youtube.com" not in url and "youtu.be" not in url:
        return jsonify({"error": "YouTube URL이 아닙니다."}), 400

    if not validate_time(start) or not validate_time(end):
        return jsonify({"error": "시간 형식이 올바르지 않습니다. (예: 02:35)"}), 400

    # 2. 임시 작업 폴더
    work_dir = tempfile.mkdtemp(prefix="ytclip_")
    video_id = str(uuid.uuid4())[:8]
    full_path = os.path.join(work_dir, f"{video_id}_full.mp4")
    clip_path = os.path.join(work_dir, f"{video_id}_clip.mp4")

    try:
        # 3. yt-dlp로 영상 다운로드 (720p 이하로 제한 - 속도/용량 고려)
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
            'outtmpl': full_path,
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': FFMPEG_PATH,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(full_path):
            return jsonify({"error": "영상 다운로드에 실패했습니다."}), 500

        # 4. ffmpeg로 자르기 (-c copy: 재인코딩 없이 빠르게)
        cmd = [
            FFMPEG_PATH, '-y',
            '-ss', start,
            '-to', end,
            '-i', full_path,
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            clip_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0 or not os.path.exists(clip_path):
            return jsonify({
                "error": f"영상 자르기 실패: {result.stderr[-300:] if result.stderr else 'unknown'}"
            }), 500

        # 5. 응답 후 임시 파일 정리
        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                if os.path.exists(clip_path):
                    os.remove(clip_path)
                os.rmdir(work_dir)
            except Exception as e:
                app.logger.warning(f"cleanup error: {e}")
            return response

        download_name = f"clip_{start.replace(':','')}_{end.replace(':','')}.mp4"
        return send_file(clip_path, as_attachment=True, download_name=download_name, mimetype='video/mp4')

    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": f"YouTube 다운로드 오류: {str(e)[:300]}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "처리 시간 초과 (5분). 영상이 너무 깁니다."}), 500
    except Exception as e:
        return jsonify({"error": f"오류: {str(e)[:300]}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
