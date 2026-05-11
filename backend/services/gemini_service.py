"""Google Gemini 호출 래퍼 (google-genai SDK v1 사용)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types


logger = logging.getLogger(__name__)


async def connect_and_list_models(api_key: str) -> list[str]:
    """API 키 검증 + 사용 가능한 generateContent 모델 목록 반환."""
    client = genai.Client(api_key=api_key)
    models = await asyncio.to_thread(lambda: list(client.models.list()))
    # 텍스트 생성에 부적합한 모델 키워드 (TTS, 이미지생성, 컴퓨터비전 등)
    _EXCLUDE = ("tts", "image", "computer-use", "embedding", "aqa", "audio")
    out: list[str] = []
    for m in models:
        name = getattr(m, "name", "") or ""
        short = name.replace("models/", "")
        # gemini- 계열 모델만 포함 (타 제품군 제외)
        if not short.startswith("gemini-"):
            continue
        if any(kw in short.lower() for kw in _EXCLUDE):
            continue
        out.append(short)
    out.sort()
    return out


async def inspect_batch(
    api_key: str,
    model_name: str,
    system_prompt: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """한 배치(records)를 Gemini 로 점검하여 JSON 결과 리스트 반환.

    각 record 는 최소 다음 키를 가진다:
        - record_id (int): 호출자 측 식별자
        - area (str)
        - content (str)
        - subject (str | None)
    """
    client = genai.Client(api_key=api_key)

    # 모델명에 'models/' prefix 가 있으면 제거 (신규 SDK는 prefix 없이 사용)
    clean_model = model_name.replace("models/", "")

    records_text_parts = []
    for r in records:
        subject = r.get("subject") or ""
        grade_year = r.get("grade_year")
        year_tag = f"|{grade_year}학년기록" if grade_year else ""
        records_text_parts.append(
            f"[ID:{r['record_id']}|영역:{r['area']}|과목:{subject}{year_tag}]\n{r['content']}"
        )
    records_text = "\n\n".join(records_text_parts)

    user_prompt = (
        f"다음 {len(records)}개 기록을 검토하고 JSON 배열로만 응답하세요.\n"
        f"각 항목은 record_id, violation(true/false), category, reason, evidence, suggested_text 키를 가집니다.\n"
        f"- evidence: 위반으로 판단된 원문 발췌 (없으면 null)\n"
        f"- suggested_text: 위반 부분의 수정 제안 문장 (없으면 null)\n\n"
        f"{records_text}\n\n"
        '응답 형식 예시:\n'
        '[{"record_id": 1, "violation": true, "category": "기관명 명시", '
        '"reason": "특정 기업명 직접 기재", "evidence": "...삼성전자...", '
        '"suggested_text": "특정 기업과 협력하여 프로젝트를 진행함"}]'
    )

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        temperature=0.1,
    )

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=clean_model,
                contents=user_prompt,
                config=config,
            )
            text = getattr(response, "text", None)
            if text is None:
                try:
                    text = response.candidates[0].content.parts[0].text
                except Exception:
                    text = ""
            text = (text or "").strip()
            if not text:
                raise ValueError("Gemini 응답이 비어 있습니다")
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "results" in parsed:
                parsed = parsed["results"]
            if not isinstance(parsed, list):
                raise ValueError(f"예상치 못한 응답 구조: {type(parsed).__name__}")
            return parsed
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            logger.warning(
                "[gemini] 배치 호출 실패 (attempt %d/3): %s (재시도 %ds)",
                attempt + 1, e, wait,
            )
            if attempt == 2:
                break
            await asyncio.sleep(wait)
    assert last_err is not None
    raise last_err
