"""Claude 호출 계층.

이전 구현은 모델에게 "JSON만 응답하라"고 부탁한 뒤 정규식과 중괄호 위치로
파싱하고, 실패하면 조용히 빈 결과를 돌려줬습니다. 여기서는 구조화 출력
(`output_config.format`)으로 스키마를 강제하므로 그 파싱 계층 자체가 없습니다.
"""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

import config
from analyzer.cost import UsageMeter
from analyzer.errors import UpstreamError

log = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.require_api_key())
    return _client


# --------------------------------------------------------------------------
# 응답 스키마
# --------------------------------------------------------------------------


class VisualMoment(BaseModel):
    timestamp: str = Field(description="HH:MM:SS 형식의 시점")
    reason: str = Field(description="이 시점의 화면을 봐야 하는 이유")
    context: str = Field(description="해당 시점의 자막 내용")


class ChunkSummary(BaseModel):
    """긴 영상을 나눠 분석할 때의 부분 결과."""

    summary: str
    key_points: list[str]
    visual_moments: list[VisualMoment]


class TranscriptAnalysis(BaseModel):
    summary: str = Field(description="영상 전체 내용의 상세 요약 (한국어)")
    topic: str = Field(description="핵심 주제 한 줄")
    keywords: list[str] = Field(description="핵심 키워드 3~6개")
    visual_moments: list[VisualMoment] = Field(
        description="화면을 확인해야 이해되는 시점들"
    )


class FrameDescription(BaseModel):
    timestamp: str
    description: str = Field(description="화면에 보이는 내용 설명 (한국어 2~3문장)")


class FrameAnalyses(BaseModel):
    frames: list[FrameDescription]


# 리포트를 마크다운 한 덩어리가 아니라 구조화된 필드로 받습니다. 클라이언트가
# 모델 출력을 파싱해 innerHTML로 넣을 필요가 없어져 XSS 표면이 사라집니다.
# (docstring은 스키마 description으로 모델에 전달되므로, 구현 메모는 주석으로 둡니다.)
class FinalReport(BaseModel):
    """영상 분석 리포트."""

    headline: str = Field(description="한 줄 제목")
    topic: str = Field(description="핵심 주제 1~2문장")
    summary_points: list[str] = Field(description="주요 내용 3~5개, 각 2문장 이상")
    visual_notes: list[str] = Field(description="캡처 화면에서 확인된 내용 정리")
    keywords: list[str] = Field(description="핵심 키워드 3~5개")
    takeaway: str = Field(description="한 줄 결론")


# --------------------------------------------------------------------------
# 호출 헬퍼
# --------------------------------------------------------------------------


def _parse(
    *,
    system: str,
    content,
    output_format: type[BaseModel],
    meter: UsageMeter,
    effort: str | None = None,
):
    try:
        response = get_client().messages.parse(
            model=config.ANALYSIS_MODEL,
            max_tokens=config.MAX_TOKENS,
            output_config={"effort": effort or config.ANALYSIS_EFFORT},
            output_format=output_format,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.RateLimitError as exc:
        log.warning("Claude 레이트 리밋: %s", exc)
        raise UpstreamError(
            "AI 분석 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.", 429
        ) from exc
    except anthropic.APIStatusError as exc:
        log.error("Claude API 오류 %s: %s", exc.status_code, exc.message)
        raise UpstreamError("AI 분석 중 오류가 발생했습니다.") from exc
    except anthropic.APIConnectionError as exc:
        log.error("Claude 연결 실패: %s", exc)
        raise UpstreamError("AI 서버에 연결하지 못했습니다.") from exc

    meter.add(response.usage)

    if response.stop_reason == "refusal":
        raise UpstreamError("이 영상의 내용은 분석할 수 없습니다.")

    parsed = response.parsed_output
    if parsed is None:
        log.error("구조화 출력 파싱 실패 (stop_reason=%s)", response.stop_reason)
        raise UpstreamError("AI 응답을 해석하지 못했습니다. 다시 시도해 주세요.")
    return parsed


_VISUAL_MOMENT_RULES = """
visual_moments 규칙:
- "화면을 보시면", "이 그래프", "코드를 보면", "여기 보이는", "보여드리겠습니다",
  "화면에", "슬라이드" 처럼 시각 자료를 가리키는 표현이 나오는 시점만 고릅니다.
- 중요도가 높은 순으로 최대 10개.
- 해당하는 시점이 없으면 빈 배열을 반환합니다.
- timestamp는 반드시 자막에 실제로 등장한 HH:MM:SS 값이어야 합니다.
""".strip()

_ANALYST_SYSTEM = (
    "당신은 YouTube 영상 자막을 분석해 한국어로 정리하는 분석가입니다. "
    "자막에 실제로 담긴 내용만 사용하고, 추측을 사실처럼 쓰지 않습니다."
)


# --------------------------------------------------------------------------
# 자막 분석 (짧으면 단일 호출, 길면 맵-리듀스)
# --------------------------------------------------------------------------


def analyze_transcript_chunk(
    chunk: str, index: int, total: int, meter: UsageMeter
) -> ChunkSummary:
    prompt = f"""아래는 한 영상 자막의 {index + 1}/{total} 구간입니다.
이 구간만 놓고 요약해 주세요.

자막:
{chunk}

{_VISUAL_MOMENT_RULES}"""
    return _parse(
        system=_ANALYST_SYSTEM,
        content=prompt,
        output_format=ChunkSummary,
        meter=meter,
    )


def merge_chunk_summaries(
    summaries: list[ChunkSummary], title: str, author: str, meter: UsageMeter
) -> TranscriptAnalysis:
    parts = []
    for i, summary in enumerate(summaries):
        points = "\n".join(f"  - {point}" for point in summary.key_points)
        parts.append(f"[구간 {i + 1}]\n{summary.summary}\n{points}")
    joined = "\n\n".join(parts)

    moments = [
        f"- [{m.timestamp}] {m.reason} ({m.context})"
        for summary in summaries
        for m in summary.visual_moments
    ]
    moment_block = "\n".join(moments) if moments else "(없음)"

    prompt = f"""영상 제목: {title}
채널: {author}

아래는 같은 영상을 구간별로 요약한 결과입니다. 이를 하나의 일관된 분석으로
합쳐 주세요. 구간 사이에 중복되는 내용은 한 번만 담고, 전체 흐름이 드러나게
정리합니다.

{joined}

구간별로 뽑힌 시각 자료 시점 후보:
{moment_block}

이 중 실제로 중요한 것만 최대 10개 골라 visual_moments에 담아 주세요."""
    return _parse(
        system=_ANALYST_SYSTEM,
        content=prompt,
        output_format=TranscriptAnalysis,
        meter=meter,
    )


def analyze_transcript(
    chunks: list[str], title: str, author: str, meter: UsageMeter
) -> TranscriptAnalysis:
    """자막을 분석합니다. 길면 구간별로 나눠 처리한 뒤 합칩니다."""
    if len(chunks) == 1:
        prompt = f"""영상 제목: {title}
채널: {author}

자막:
{chunks[0]}

{_VISUAL_MOMENT_RULES}"""
        return _parse(
            system=_ANALYST_SYSTEM,
            content=prompt,
            output_format=TranscriptAnalysis,
            meter=meter,
        )

    summaries = [
        analyze_transcript_chunk(chunk, i, len(chunks), meter)
        for i, chunk in enumerate(chunks)
    ]
    return merge_chunk_summaries(summaries, title, author, meter)


# --------------------------------------------------------------------------
# 화면 분석
# --------------------------------------------------------------------------


def analyze_frames(
    frames: list[tuple[str, str, str]], meter: UsageMeter
) -> list[FrameDescription]:
    """캡처된 프레임들을 한 번의 호출로 분석합니다.

    frames: (timestamp, reason, base64_jpeg) 목록.
    프레임마다 따로 호출하면 호출 수만큼 비용이 늘고 서로의 맥락을 못 봅니다.
    """
    if not frames:
        return []

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "아래는 같은 YouTube 영상에서 캡처한 화면들입니다. "
                "각 이미지 앞에 시점과 캡처 이유가 적혀 있습니다.\n"
                "이미지마다 보이는 내용을 한국어 2~3문장으로 설명해 주세요. "
                "frames 배열의 순서와 timestamp는 입력과 동일하게 유지합니다."
            ),
        }
    ]
    for timestamp, reason, image_b64 in frames:
        content.append(
            {"type": "text", "text": f"[{timestamp}] 캡처 이유: {reason}"}
        )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            }
        )

    result = _parse(
        system=(
            "당신은 영상 캡처 화면을 보고 무엇이 담겨 있는지 한국어로 설명하는 "
            "분석가입니다. 이미지에서 실제로 확인되는 것만 설명합니다."
        ),
        content=content,
        output_format=FrameAnalyses,
        meter=meter,
    )
    return result.frames


# --------------------------------------------------------------------------
# 최종 리포트
# --------------------------------------------------------------------------


def generate_report(
    analysis: TranscriptAnalysis,
    frame_descriptions: list[FrameDescription],
    meter: UsageMeter,
) -> FinalReport:
    if frame_descriptions:
        visual_block = "\n".join(
            f"- [{frame.timestamp}] {frame.description}"
            for frame in frame_descriptions
        )
        visual_section = f"\n\n화면 캡처 분석 결과:\n{visual_block}"
    else:
        visual_section = ""

    prompt = f"""아래 분석 결과를 초보자도 이해할 수 있는 리포트로 정리해 주세요.

영상 요약: {analysis.summary}
핵심 주제: {analysis.topic}
키워드: {", ".join(analysis.keywords)}{visual_section}

- summary_points: 주요 내용 3~5개, 각 항목 2문장 이상
- visual_notes: 캡처 화면에서 확인된 내용. 캡처가 없으면 빈 배열
- takeaway: 이 영상의 핵심 메시지 한 문장"""

    return _parse(
        system=(
            "당신은 분석 결과를 쉬운 한국어로 정리하는 편집자입니다. "
            "주어진 자료에 없는 내용을 지어내지 않습니다."
        ),
        content=prompt,
        output_format=FinalReport,
        meter=meter,
    )
