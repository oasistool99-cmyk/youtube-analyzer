# 🎬 YouTube 스마트 분석기

YouTube 링크 하나로 **자막 추출 → AI 분석 → 핵심 장면 자동 캡처 → 화면 분석 →
리포트**까지 처리하는 Flask 서버입니다. 웹 UI가 함께 들어 있어 배포하면 바로
쓸 수 있습니다.

## 🏗️ 구성

| 파일/폴더 | 역할 |
| --- | --- |
| `app.py` | HTTP 라우팅 (페이지, REST, SSE) |
| `config.py` | 환경 변수 기반 설정 |
| `analyzer/youtube.py` | yt-dlp 연동 (메타데이터·자막·다운로드·프레임 캡처) |
| `analyzer/vtt.py` | WebVTT 파싱, 롤링 자막 병합, 청크 분할 |
| `analyzer/claude.py` | Claude 호출 (구조화 출력 스키마 포함) |
| `analyzer/pipeline.py` | 분석 파이프라인 + 진행 이벤트 |
| `analyzer/clip.py` | 구간 잘라내기(부가 기능) |
| `analyzer/cost.py` | 실제 토큰 사용량 기반 비용 계산 |
| `analyzer/cache.py`, `ratelimit.py` | TTL 캐시, IP 단위 레이트 리밋 |
| `static/` | 웹 UI (HTML/CSS/JS) |
| `tests/` | 단위 테스트 |

기술 스택: **Python + Flask**, **yt-dlp**, **ffmpeg**(imageio-ffmpeg 번들),
**Claude API**(기본 `claude-opus-5`).

## 🚀 Render 배포

1. **Anthropic API 키 발급** — https://console.anthropic.com
2. **저장소 연결** — https://render.com → New → Web Service → 이 저장소 선택
3. **설정** — Runtime `Docker`, Instance Type `Free`
4. **Environment 탭에서 키 추가**
   - Key: `ANTHROPIC_API_KEY` / Value: 발급받은 키
5. **Create Web Service**

배포가 끝나면 `https://<서비스명>.onrender.com` 에 접속해 바로 사용합니다.
`render.yaml`에 헬스체크 경로(`/api/health`)와 기본 환경 변수가 정의돼 있습니다.

### 로컬 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python app.py            # http://localhost:5000
pytest                   # 테스트
```

## ⚙️ 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | (필수) | 없으면 분석 요청이 503으로 거부됩니다 |
| `ANALYSIS_MODEL` | `claude-opus-5` | 사용할 모델 |
| `ANALYSIS_EFFORT` | `medium` | `low`\|`medium`\|`high`\|`xhigh`\|`max`. 높일수록 분석이 깊어지고 비용/시간이 늘어납니다 |
| `MAX_VIDEO_DURATION_SEC` | `3600` | 이보다 긴 영상은 거부 |
| `MAX_FRAMES` | `8` | 캡처할 최대 장면 수 |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SEC` | `5` / `600` | IP당 요청 제한 |
| `CACHE_TTL_SEC` | `3600` | 같은 영상 재분석 시 캐시 유효 시간 |
| `USD_TO_KRW` | `1400` | 비용 표시 환율(근사치) |
| `CORS_ORIGINS` | (없음) | 비우면 동일 출처만 허용. 외부 호출이 필요하면 쉼표로 나열 |
| `SUBTITLE_LANG_PRIORITY` | `ko,en` | 자막 언어 우선순위 |
| `CLIP_MAX_DURATION_SEC` | `600` | 한 번에 자를 수 있는 최대 길이 |

## 📡 API

### `GET /api/analyze/stream?url=...&mode=smart|fast`

진행 상황을 실시간으로 받는 **SSE 엔드포인트**(웹 UI가 사용). 각 이벤트는
`data:` 한 줄의 JSON입니다.

```
data: {"type":"progress","step":"subtitles","message":"자막을 추출하는 중...","percent":15}
data: {"type":"result","data":{...}}
data: {"type":"error","message":"이 영상에는 사용할 수 있는 자막이 없습니다."}
```

### `POST /api/analyze` — 스마트 분석 (자막 + 화면)

```json
{ "url": "https://www.youtube.com/watch?v=...", "capture_frames": true }
```

### `POST /api/analyze-text` — 빠른 분석 (자막만)

```json
{ "url": "https://www.youtube.com/watch?v=..." }
```

두 엔드포인트의 응답 형식은 동일합니다.

```json
{
  "video_info": { "video_id": "...", "title": "...", "author": "...", "duration": 612, "thumbnail": "..." },
  "subtitle_language": "ko",
  "analysis": { "summary": "...", "topic": "...", "keywords": ["..."], "visual_moments_count": 4 },
  "image_analyses": [ { "timestamp": "00:03:20", "reason": "...", "description": "..." } ],
  "report": {
    "headline": "...", "topic": "...",
    "summary_points": ["..."], "visual_notes": ["..."],
    "keywords": ["..."], "takeaway": "..."
  },
  "stats": {
    "subtitle_cues": 412, "transcript_chunks": 2, "frames_captured": 4,
    "model": "claude-opus-5", "api_calls": 3,
    "input_tokens": 18240, "output_tokens": 2130,
    "estimated_cost_usd": 0.1445, "estimated_cost_krw": 202
  },
  "cached": false
}
```

리포트는 마크다운 문자열이 아니라 **구조화된 필드**로 돌아옵니다. 클라이언트가
모델 출력을 파싱해 HTML로 넣을 필요가 없습니다.

### `POST /api/clip` — 구간 잘라 내려받기 (부가 기능, UI는 `/clip`)

```json
{ "url": "https://www.youtube.com/watch?v=...", "start": "02:35", "end": "05:10" }
```

성공하면 `video/mp4` 바이너리를 반환합니다.

### `GET /api/health`

모델, effort, API 키 설정 여부를 반환합니다.

## 💰 비용

비용은 **실제 응답의 토큰 사용량**으로 계산해 `stats`에 담습니다(고정 상수를
쓰지 않습니다). 대략적인 감각은 다음과 같습니다.

- 서버: ₩0 (Render 무료 플랜)
- 빠른 분석(자막만): 10분 영상 기준 수십 원대
- 스마트 분석(자막 + 캡처 8장): 위의 2~4배

비용을 더 낮추려면 `ANALYSIS_EFFORT=low`, `MAX_FRAMES`를 줄이거나
`ANALYSIS_MODEL=claude-sonnet-5`로 바꾸세요. 같은 영상을 다시 분석하면
캐시(`CACHE_TTL_SEC`)가 적용되어 추가 비용이 들지 않습니다.

## ⚠️ 주의사항

- Render 무료 플랜은 15분 미사용 시 슬립됩니다 (첫 요청이 30초~1분 느릴 수 있음).
- 캐시와 레이트 리밋은 **워커 프로세스 메모리** 기준입니다. 여러 인스턴스로
  확장한다면 Redis 같은 공용 저장소로 옮겨야 합니다.
- 자막이 없는 영상은 분석할 수 없습니다 (자동 생성 자막도 없는 경우).
- 실시간 방송은 지원하지 않습니다.
- 저작권이 있는 콘텐츠는 개인 학습/분석 목적으로만 사용하세요.
