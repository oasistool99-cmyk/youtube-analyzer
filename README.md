# 🎬 YouTube 스마트 영상 분석기 - 백엔드

YouTube 링크만 넣으면 **자막 추출 → AI 분석 → 핵심 장면 자동 캡처 → 화면 분석**까지
전부 자동으로 처리하는 백엔드 서버입니다.

## 🏗️ 기술 스택
- **Python + Flask**: API 서버
- **yt-dlp**: YouTube 자막 추출 + 영상 다운로드
- **ffmpeg**: 특정 타임스탬프 프레임 캡처
- **Claude API**: 자막 분석 + 이미지 분석

## 🚀 Render 무료 배포 방법 (초보자 가이드)

### 1단계: 준비물
- GitHub 계정 (없으면 가입: https://github.com)
- Render 계정 (없으면 가입: https://render.com, GitHub로 로그인 가능)
- Anthropic API 키 (https://console.anthropic.com 에서 발급)

### 2단계: GitHub에 코드 올리기
1. GitHub에서 "New repository" 클릭
2. 이름: `youtube-analyzer` 입력
3. "Create repository" 클릭
4. 이 폴더의 모든 파일을 업로드

### 3단계: Render에서 배포
1. https://render.com 접속 → "New" → "Web Service"
2. GitHub 저장소 연결 → `youtube-analyzer` 선택
3. 설정:
   - **Name**: youtube-analyzer-api
   - **Runtime**: Docker
   - **Instance Type**: Free
4. "Environment" 탭에서:
   - Key: `ANTHROPIC_API_KEY`
   - Value: 본인의 API 키 입력
5. "Create Web Service" 클릭

### 4단계: 완료!
배포 후 `https://youtube-analyzer-api.onrender.com` 같은 URL이 생깁니다.
프론트엔드에서 이 URL을 사용하면 됩니다.

## 📡 API 엔드포인트

### POST /api/analyze (스마트 분석 - 자막 + 화면)
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "capture_frames": true
}
```

### POST /api/analyze-text (빠른 분석 - 자막만)
```json
{
  "url": "https://www.youtube.com/watch?v=..."
}
```

### GET /api/health (서버 상태 확인)

## 💰 예상 비용
- 서버: ₩0 (Render 무료)
- 자막만 분석: 영상 1개당 ~₩200
- 자막 + 화면 캡처: 영상 1개당 ~₩600

## ⚠️ 주의사항
- Render 무료 플랜은 15분 미사용 시 슬립됩니다 (첫 요청이 30초~1분 느릴 수 있음)
- 30분 영상의 전체 분석은 약 1~3분 소요됩니다
- 저작권이 있는 콘텐츠는 개인 학습/분석 목적으로만 사용하세요
