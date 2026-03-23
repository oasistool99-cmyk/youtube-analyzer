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
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

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
