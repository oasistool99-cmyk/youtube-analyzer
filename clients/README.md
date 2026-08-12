# 부가 클라이언트

## `youtube-analyzer.jsx`

원래 `files.zip` 안에 들어 있던 React 클라이언트를 꺼내 보관한 것입니다.

⚠️ **이 파일은 구버전 API 응답 형식을 기준으로 작성되어 있어 그대로는 동작하지
않습니다.** 서버가 반환하는 리포트가 마크다운 문자열(`final_report`)에서
구조화된 객체(`report`)로 바뀌었기 때문입니다.

지금 바로 쓸 수 있는 프론트엔드는 서버가 직접 서빙하는 `/` (`static/index.html`)
입니다. 이 JSX를 계속 쓰려면 다음을 맞춰야 합니다.

| 구버전 | 현재 |
| --- | --- |
| `data.final_report` (마크다운 문자열) | `data.report` (`headline`, `topic`, `summary_points[]`, `visual_notes[]`, `keywords[]`, `takeaway`) |
| `data.first_pass.summary` | `data.analysis.summary` |
| `data.stats.subtitles_count` | `data.stats.subtitle_cues` |
| `data.stats.estimated_cost_krw` (고정 상수) | `data.stats.estimated_cost_krw` (실제 토큰 사용량 기반) |
| POST `/api/analyze` 만 사용 | GET `/api/analyze/stream` 으로 실시간 진행 상황 수신 가능 |

또한 마크다운을 직접 파싱해 렌더링하던 부분은 필요 없어졌습니다. 구조화된
필드를 그대로 렌더링하되, 값은 반드시 텍스트로 넣으세요 (`dangerouslySetInnerHTML`
사용 금지).
