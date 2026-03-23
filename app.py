"""
YouTube Smart Analyzer Backend
- yt-dlp: 영상 다운로드 + 자막 추출
- ffmpeg: 특정 타임스탬프 프레임 캡처
- Claude API: 자막 분석 + 이미지 분석
"""

import os
import re
import json
import base64
import tempfile
import subprocess
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

# index.html의 절대 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# ───────────────────────────── 유틸리티 ─────────────────────────────

def extract_video_id(url):
    patterns = [
        r'(?:youtube\.com/watch\?v=)([^&\s]+)',
        r'(?:youtu\.be/)([^?\s]+)',
        r'(?:youtube\.com/embed/)([^?\s]+)',
        r'(?:youtube\.com/shorts/)([^?\s]+)',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def download_subtitles(video_url, tmp_dir):
    """yt-dlp로 자막 추출 (자동생성 자막 포함)"""
    output_path = os.path.join(tmp_dir, "subs")
    cmd = [
        "yt-dlp",
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang", "ko,en",
        "--sub-format", "vtt",
        "--skip-download",
        "-o", output_path,
        video_url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)

    # 생성된 자막 파일 찾기
    for ext in [".ko.vtt", ".en.vtt", ".vtt"]:
        for f in os.listdir(tmp_dir):
            if f.endswith(ext):
                filepath = os.path.join(tmp_dir, f)
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    return parse_vtt(fh.read())
    return None


def parse_vtt(vtt_text):
    """VTT 자막을 타임스탬프 + 텍스트 배열로 파싱"""
    lines = vtt_text.split("\n")
    entries = []
    current_time = None
    current_text = []

    for line in lines:
        line = line.strip()
        # 타임스탬프 라인 (00:00:05.000 --> 00:00:08.000)
        time_match = re.match(r'(\d{2}:\d{2}:\d{2})\.\d+\s*-->', line)
        if time_match:
            if current_time and current_text:
                text = " ".join(current_text).strip()
                # VTT 태그 제거
                text = re.sub(r'<[^>]+>', '', text)
                if text:
                    entries.append({"time": current_time, "text": text})
            current_time = time_match.group(1)
            current_text = []
        elif line and not line.startswith("WEBVTT") and not line.startswith("Kind:") and not line.startswith("Language:") and not re.match(r'^\d+$', line):
            current_text.append(line)

    # 마지막 항목
    if current_time and current_text:
        text = " ".join(current_text).strip()
        text = re.sub(r'<[^>]+>', '', text)
        if text:
            entries.append({"time": current_time, "text": text})

    # 중복 제거
    seen = set()
    unique = []
    for e in entries:
        if e["text"] not in seen:
            seen.add(e["text"])
            unique.append(e)

    return unique


def get_video_info(video_url):
    """yt-dlp로 영상 정보 가져오기"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-download",
        video_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        info = json.loads(result.stdout)
        return {
            "title": info.get("title", ""),
            "author": info.get("uploader", ""),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
        }
    return None


def capture_frame(video_url, timestamp_str, tmp_dir):
    """yt-dlp + ffmpeg로 특정 타임스탬프 프레임 캡처"""
    video_path = os.path.join(tmp_dir, "video.mp4")

    # 영상 다운로드 (아직 안 됐으면)
    if not os.path.exists(video_path):
        cmd = [
            "yt-dlp",
            "-f", "worst[ext=mp4]",  # 최소 화질로 용량 절약
            "-o", video_path,
            video_url,
        ]
        subprocess.run(cmd, capture_output=True, timeout=300)

    if not os.path.exists(video_path):
        return None

    # ffmpeg로 프레임 캡처
    frame_path = os.path.join(tmp_dir, f"frame_{timestamp_str.replace(':', '-')}.jpg")
    cmd = [
        "ffmpeg",
        "-ss", timestamp_str,
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "3",
        "-y",
        frame_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)

    if os.path.exists(frame_path):
        with open(frame_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    return None


def timestamp_to_seconds(ts):
    """HH:MM:SS 또는 MM:SS를 초로 변환"""
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


# ───────────────── Claude AI 분석 함수 ─────────────────

def analyze_transcript(subtitle_entries, video_info):
    """1단계: 자막 분석 + 캡처 필요 구간 찾기"""
    # 자막 텍스트를 타임스탬프 포함하여 합침
    transcript_text = "\n".join(
        [f"[{e['time']}] {e['text']}" for e in subtitle_entries[:500]]
    )

    if len(transcript_text) > 15000:
        transcript_text = transcript_text[:15000] + "\n...(이하 생략)"

    title_info = f"\n영상 제목: {video_info['title']}\n채널: {video_info['author']}" if video_info else ""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""YouTube 영상 자막을 분석해주세요.{title_info}

자막:
{transcript_text}

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만:
{{"transcript_summary":"영상 전체 내용 상세 요약 (한국어, 최소 300자)","visual_moments":[{{"timestamp":"HH:MM:SS","reason":"이 시점의 화면을 봐야 하는 이유","context":"해당 자막 내용"}}],"topic":"핵심 주제","keywords":["키워드1","키워드2","키워드3","키워드4","키워드5"]}}

visual_moments 규칙:
- "화면을 보시면", "이 그래프", "코드를 보면", "여기 보이는", "보여드리겠습니다", "화면에", "슬라이드" 등 시각적 표현이 나오는 구간만
- 최대 10개까지만 (가장 중요한 것 우선)
- 없으면 빈 배열 []
- timestamp는 반드시 HH:MM:SS 형식"""
        }]
    )

    text = response.content[0].text
    # JSON 파싱
    try:
        clean = re.sub(r'```json\s*', '', text)
        clean = re.sub(r'```\s*', '', clean).strip()
        return json.loads(clean)
    except:
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except:
                pass
    # 폴백
    return {
        "transcript_summary": text[:2000],
        "visual_moments": [],
        "topic": "",
        "keywords": [],
    }


def analyze_image(image_base64, reason):
    """이미지 한 장 분석"""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64,
                    }
                },
                {
                    "type": "text",
                    "text": f"이 이미지는 YouTube 영상의 캡처 화면입니다.\n캡처 이유: {reason}\n이미지에 보이는 내용을 한국어로 간단히 설명해주세요. (2~3문장)"
                }
            ]
        }]
    )
    return response.content[0].text


def generate_final_report(summary, topic, keywords, image_analyses):
    """최종 통합 분석 리포트 생성"""
    img_section = ""
    if image_analyses:
        img_section = "\n\n화면 캡처 분석 결과:\n" + "\n".join(
            [f"- [{a['timestamp']}] {a['description']}" for a in image_analyses]
        )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""YouTube 영상 분석 결과를 정리해주세요.

영상 요약: {summary}
핵심 주제: {topic}
키워드: {', '.join(keywords)}
{img_section}

초보자도 이해하기 쉽게 아래 형식으로 한국어 분석을 작성해주세요:

📌 핵심 주제
(1~2문장)

📝 내용 요약
(주요 내용 3~5개, 각각 - 로 시작, 각 항목 2문장 이상)
{"" if not image_analyses else chr(10) + "🖼️ 주요 화면 설명" + chr(10) + "(캡처된 화면에서 확인된 내용 정리)"}

💡 핵심 키워드
(3~5개)

🎯 한줄 결론
(핵심 메시지 한 문장)"""
        }]
    )
    return response.content[0].text


# ───────────────────────── API 라우트 ─────────────────────────

@app.route("/", methods=["GET"])
def home():
    return Response(FRONTEND_HTML, mimetype="text/html")


FRONTEND_HTML = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YouTube 스마트 분석기</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}body{background:#0a0a0f;font-family:'Outfit',sans-serif;color:#e8e8ee;min-height:100vh}::selection{background:#ff3e5544}input:focus{outline:none;border-color:#ff3e5566!important}@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}@keyframes pulse{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}.wrap{max-width:640px;margin:0 auto;padding:28px 16px}.header{text-align:center;margin-bottom:24px}.logo-row{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:6px}.logo{font-size:22px;font-weight:700;letter-spacing:-.5px;background:linear-gradient(135deg,#ff3e55,#ff8a65);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.sub{font-size:13px;color:#777}.card{background:#13131f;border:1px solid #1f1f32;border-radius:14px;padding:18px;margin-bottom:12px;animation:fadeUp .4s ease}.label{font-size:12px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;display:block}.row{display:flex;gap:8px}.input{flex:1;background:#0c0c15;border:1px solid #2a2a3a;border-radius:10px;padding:11px 14px;color:#e8e8ee;font-size:13px;font-family:'JetBrains Mono',monospace}.hint{font-size:11px;color:#555;margin-top:6px}.btn{background:linear-gradient(135deg,#ff3e55,#e62e45);border:none;border-radius:10px;padding:11px 18px;color:#fff;font-size:13px;font-weight:600;font-family:'Outfit';cursor:pointer;white-space:nowrap}.btn:hover{filter:brightness(1.1)}.btn:disabled{opacity:.5;cursor:not-allowed}.btn-ghost{background:transparent;border:1px solid #2a2a3a;border-radius:10px;padding:9px 16px;color:#999;font-size:12px;font-weight:500;font-family:'Outfit';cursor:pointer}.btn-sm{background:#1a1a2e;border:1px solid #2a2a3a;border-radius:8px;padding:7px 12px;color:#ccc;font-size:12px;font-family:'Outfit';cursor:pointer}.mode-toggle{display:flex;gap:4px;margin-bottom:14px;padding:4px;background:#0c0c15;border-radius:12px;border:1px solid #1f1f32}.mode-btn{flex:1;padding:9px 10px;border:none;border-radius:10px;background:transparent;color:#666;font-size:13px;font-weight:600;font-family:'Outfit';cursor:pointer}.mode-btn.on{background:#1a1a2e;color:#ff6b7a;box-shadow:0 2px 8px rgba(255,62,85,.12)}.badge{font-size:12px;font-weight:600;padding:4px 12px;border-radius:20px}.thumb{width:100px;height:56px;border-radius:6px;object-fit:cover;background:#1a1a2a;flex-shrink:0}.stat{background:#0c0c15;border-radius:10px;padding:12px 14px;text-align:center}.stat-label{font-size:11px;color:#666;margin-bottom:4px}.stat-val{font-size:16px;font-weight:600;font-family:'JetBrains Mono'}.dots{display:flex;gap:6px;justify-content:center;padding:16px}.dots span{width:8px;height:8px;border-radius:50%;background:#ff3e55;animation:pulse 1.2s ease-in-out infinite}.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}.result h3{font-size:16px;font-weight:700;color:#f0f0f5;margin-top:16px;margin-bottom:8px}.result p{font-size:14px;color:#bbb;margin-bottom:4px;line-height:1.7}.result .bullet{padding-left:8px}.stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px}.img-item{background:#0c0c15;border:1px solid #1f1f32;border-radius:8px;padding:12px;margin-bottom:8px}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="logo-row">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none"><rect x="2" y="4" width="20" height="16" rx="4" fill="#ff3e55"/><polygon points="10,8 10,16 16,12" fill="#fff"/></svg>
      <span class="logo">YouTube 완전 자동 분석기</span>
    </div>
    <p class="sub">링크만 넣으면 자막 추출 &rarr; AI 분석 &rarr; 화면 캡처까지 전부 자동</p>
  </div>
  <div class="mode-toggle" id="modeSection">
    <button class="mode-btn on" id="smartBtn" onclick="setMode('smart')">&#x1F9E0; 스마트 분석</button>
    <button class="mode-btn" id="fastBtn" onclick="setMode('fast')">&#x26A1; 빠른 분석</button>
  </div>
  <div class="card" id="inputCard">
    <label class="label">YouTube 링크</label>
    <div class="row">
      <input class="input" id="urlInput" placeholder="https://www.youtube.com/watch?v=..." onkeydown="if(event.key==='Enter')analyze()">
      <button class="btn" id="analyzeBtn" onclick="analyze()">&#x1F50D; 분석</button>
    </div>
    <p class="hint" id="modeHint">자막 분석 + 핵심 장면 자동 캡처 + 화면 분석 (1~3분 소요, ~&#8361;600)</p>
  </div>
  <div class="card" id="loadingCard" style="display:none">
    <div class="dots"><span></span><span></span><span></span></div>
    <p style="text-align:center;color:#aaa;font-size:13px" id="loadingMsg"></p>
  </div>
  <div class="card" id="errorCard" style="display:none;border-color:#ff3e5544">
    <p style="color:#ff6b7a;font-size:14px" id="errorMsg"></p>
    <button class="btn-sm" style="margin-top:10px" onclick="hideError()">확인</button>
  </div>
  <div id="resultSection" style="display:none">
    <div class="card" id="videoInfoCard" style="display:none">
      <div style="display:flex;gap:12px;align-items:center">
        <img id="videoThumb" class="thumb" src="">
        <div style="flex:1;min-width:0">
          <p style="font-size:15px;font-weight:600;line-height:1.4" id="videoTitle"></p>
          <p style="font-size:12px;color:#777;margin-top:2px" id="videoAuthor"></p>
          <p style="font-size:12px;color:#555;margin-top:2px" id="videoDuration"></p>
        </div>
      </div>
    </div>
    <div class="stats-grid" id="statsGrid" style="display:none">
      <div class="stat"><div class="stat-label">자막</div><div class="stat-val" id="statSubs">0</div></div>
      <div class="stat"><div class="stat-label">캡처</div><div class="stat-val" id="statFrames">0</div></div>
      <div class="stat"><div class="stat-label">비용</div><div class="stat-val" id="statCost">&#8361;0</div></div>
    </div>
    <div class="card" id="imageCard" style="display:none">
      <span class="badge" style="background:#ff3e5522;color:#ff6b7a" id="imageBadge"></span>
      <div id="imageList" style="margin-top:12px"></div>
    </div>
    <div class="card" id="reportCard" style="border-color:#ff3e5533">
      <span class="badge" style="background:#ff3e5522;color:#ff6b7a" id="reportBadge"></span>
      <div class="result" id="reportContent" style="margin-top:14px;line-height:1.8"></div>
    </div>
    <div style="text-align:center;margin-top:10px">
      <button class="btn-ghost" onclick="resetAll()">&#8634; 새로운 영상 분석하기</button>
    </div>
  </div>
</div>
<script>
let mode='smart',msgTimer=null;const API_BASE=window.location.origin;
const smartMsgs=["서버가 영상 정보를 가져오고 있어요...","yt-dlp로 자막을 추출하고 있어요...","AI가 자막을 분석하고 있어요...","핵심 장면을 찾아서 자동 캡처 중...","캡처한 화면을 AI가 분석하고 있어요...","최종 리포트를 정리하고 있어요..."];
const fastMsgs=["서버가 영상 정보를 가져오고 있어요...","yt-dlp로 자막을 추출하고 있어요...","AI가 자막을 분석하고 있어요...","최종 리포트 정리 중..."];
function setMode(m){mode=m;document.getElementById('smartBtn').className='mode-btn'+(m==='smart'?' on':'');document.getElementById('fastBtn').className='mode-btn'+(m==='fast'?' on':'');document.getElementById('modeHint').textContent=m==='smart'?'자막 분석 + 핵심 장면 자동 캡처 + 화면 분석 (1~3분 소요)':'자막만 분석 (30초~1분 소요)';}
function showLoading(msgs){document.getElementById('loadingCard').style.display='block';document.getElementById('inputCard').style.display='none';document.getElementById('modeSection').style.display='none';let i=0;document.getElementById('loadingMsg').textContent=msgs[0];msgTimer=setInterval(()=>{i=Math.min(i+1,msgs.length-1);document.getElementById('loadingMsg').textContent=msgs[i];},8000);}
function hideLoading(){document.getElementById('loadingCard').style.display='none';if(msgTimer){clearInterval(msgTimer);msgTimer=null;}}
function showError(msg){document.getElementById('errorCard').style.display='block';document.getElementById('errorMsg').textContent=msg;}
function hideError(){document.getElementById('errorCard').style.display='none';document.getElementById('inputCard').style.display='block';document.getElementById('modeSection').style.display='flex';}
function resetAll(){document.getElementById('urlInput').value='';document.getElementById('resultSection').style.display='none';document.getElementById('inputCard').style.display='block';document.getElementById('modeSection').style.display='flex';document.getElementById('errorCard').style.display='none';hideLoading();}
function renderReport(text){return text.split('\\n').map(line=>{if(line.match(/^[\\u{1F4CC}\\u{1F4DD}\\u{1F4A1}\\u{1F3AF}\\u{1F5BC}]/u))return'<h3>'+line+'</h3>';if(line.trim().startsWith('-')||line.trim().startsWith('\\u2022'))return'<p class="bullet">'+line+'</p>';if(line.trim())return'<p>'+line+'</p>';return'<div style="height:6px"></div>';}).join('');}
async function analyze(){const url=document.getElementById('urlInput').value.trim();if(!url){showError('YouTube URL을 입력해주세요.');return;}const endpoint=mode==='smart'?'/api/analyze':'/api/analyze-text';showLoading(mode==='smart'?smartMsgs:fastMsgs);document.getElementById('errorCard').style.display='none';document.getElementById('resultSection').style.display='none';try{const res=await fetch(API_BASE+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,capture_frames:true})});const data=await res.json();hideLoading();if(data.error){showError(data.error);document.getElementById('inputCard').style.display='block';document.getElementById('modeSection').style.display='flex';return;}document.getElementById('resultSection').style.display='block';if(data.video_info){document.getElementById('videoInfoCard').style.display='block';document.getElementById('videoThumb').src=data.video_info.thumbnail||'';document.getElementById('videoTitle').textContent=data.video_info.title||'분석 완료';document.getElementById('videoAuthor').textContent=data.video_info.author||'';if(data.video_info.duration>0){document.getElementById('videoDuration').textContent=Math.floor(data.video_info.duration/60)+'분 '+(data.video_info.duration%60)+'초';}}if(data.stats){document.getElementById('statsGrid').style.display='grid';document.getElementById('statSubs').textContent=(data.stats.subtitles_count||0)+'개';document.getElementById('statFrames').textContent=(data.stats.frames_captured||0)+'장';document.getElementById('statCost').textContent='~₩'+(data.stats.estimated_cost_krw||0);}if(data.image_analyses&&data.image_analyses.length>0){document.getElementById('imageCard').style.display='block';document.getElementById('imageBadge').textContent='자동 캡처 + 화면 분석 ('+data.image_analyses.length+'장)';document.getElementById('imageList').innerHTML=data.image_analyses.map(a=>'<div class="img-item"><div style="display:flex;gap:8px;align-items:baseline;margin-bottom:6px"><span style="font-family:JetBrains Mono;font-size:12px;color:#ff6b7a;font-weight:500">'+a.timestamp+'</span><span style="font-size:12px;color:#888">'+a.reason+'</span></div><p style="font-size:13px;color:#bbb;line-height:1.6">'+a.description+'</p></div>').join('');}if(data.final_report){document.getElementById('reportBadge').textContent=(mode==='smart'?'스마트':'빠른')+' 분석 완료';document.getElementById('reportContent').innerHTML=renderReport(data.final_report);}document.getElementById('resultSection').scrollIntoView({behavior:'smooth'});}catch(e){hideLoading();showError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');document.getElementById('inputCard').style.display='block';document.getElementById('modeSection').style.display='flex';}}
</script>
</body>
</html>'''


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    전체 분석 파이프라인 (자동):
    1. 영상 정보 + 자막 추출
    2. 자막 AI 분석 → 캡처 필요 구간 판별
    3. 필요 구간만 프레임 캡처
    4. 캡처 이미지 AI 분석
    5. 최종 통합 리포트
    """
    data = request.json
    video_url = data.get("url", "")

    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({"error": "올바른 YouTube URL이 아닙니다."}), 400

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # Step 1: 영상 정보
            video_info = get_video_info(canonical_url)

            # Step 2: 자막 추출
            subtitles = download_subtitles(canonical_url, tmp_dir)
            if not subtitles:
                return jsonify({
                    "error": "자막을 추출할 수 없습니다. 이 영상에 자막이 없을 수 있습니다.",
                    "video_info": video_info,
                }), 404

            # Step 3: 자막 AI 분석
            first_pass = analyze_transcript(subtitles, video_info)

            # Step 4: 핵심 장면 프레임 캡처 + 분석
            image_analyses = []
            visual_moments = first_pass.get("visual_moments", [])

            if visual_moments and data.get("capture_frames", True):
                for moment in visual_moments[:8]:  # 최대 8장
                    ts = moment.get("timestamp", "00:00:00")
                    reason = moment.get("reason", "")

                    frame_b64 = capture_frame(canonical_url, ts, tmp_dir)
                    if frame_b64:
                        try:
                            desc = analyze_image(frame_b64, reason)
                            image_analyses.append({
                                "timestamp": ts,
                                "reason": reason,
                                "description": desc,
                                "thumbnail": frame_b64[:200] + "...",  # 미리보기용
                            })
                        except Exception as e:
                            image_analyses.append({
                                "timestamp": ts,
                                "reason": reason,
                                "description": f"이미지 분석 실패: {str(e)}",
                            })

            # Step 5: 최종 리포트
            final_report = generate_final_report(
                first_pass.get("transcript_summary", ""),
                first_pass.get("topic", ""),
                first_pass.get("keywords", []),
                image_analyses,
            )

            return jsonify({
                "video_info": video_info,
                "first_pass": {
                    "summary": first_pass.get("transcript_summary", ""),
                    "topic": first_pass.get("topic", ""),
                    "keywords": first_pass.get("keywords", []),
                    "visual_moments_count": len(visual_moments),
                },
                "image_analyses": [
                    {"timestamp": a["timestamp"], "reason": a["reason"], "description": a["description"]}
                    for a in image_analyses
                ],
                "final_report": final_report,
                "stats": {
                    "subtitles_count": len(subtitles),
                    "frames_captured": len(image_analyses),
                    "estimated_cost_krw": len(image_analyses) * 30 + 200,
                },
            })

        except Exception as e:
            return jsonify({"error": f"분석 중 오류 발생: {str(e)}"}), 500


@app.route("/api/analyze-text", methods=["POST"])
def analyze_text_only():
    """자막만으로 분석 (캡처 없이, 빠른 모드)"""
    data = request.json
    video_url = data.get("url", "")

    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({"error": "올바른 YouTube URL이 아닙니다."}), 400

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            video_info = get_video_info(canonical_url)
            subtitles = download_subtitles(canonical_url, tmp_dir)

            if not subtitles:
                return jsonify({
                    "error": "자막을 추출할 수 없습니다.",
                    "video_info": video_info,
                }), 404

            first_pass = analyze_transcript(subtitles, video_info)

            final_report = generate_final_report(
                first_pass.get("transcript_summary", ""),
                first_pass.get("topic", ""),
                first_pass.get("keywords", []),
                [],
            )

            return jsonify({
                "video_info": video_info,
                "first_pass": {
                    "summary": first_pass.get("transcript_summary", ""),
                    "topic": first_pass.get("topic", ""),
                    "keywords": first_pass.get("keywords", []),
                    "visual_moments_count": len(first_pass.get("visual_moments", [])),
                },
                "final_report": final_report,
                "stats": {
                    "subtitles_count": len(subtitles),
                    "frames_captured": 0,
                    "estimated_cost_krw": 200,
                },
            })
        except Exception as e:
            return jsonify({"error": f"분석 중 오류 발생: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
