"""Google Gemini 호출 래퍼."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import google.generativeai as genai


logger = logging.getLogger(__name__)


async def connect_and_list_models(api_key: str) -> list[str]:
    """API 키 검증 + 사용 가능한 generateContent 모델 목록 반환."""
    genai.configure(api_key=api_key)
    models = await asyncio.to_thread(lambda: list(genai.list_models()))
    out: list[str] = []
    for m in models:
        name = getattr(m, "name", "") or ""
        methods = getattr(m, "supported_generation_methods", []) or []
        if "generateContent" not in methods:
            continue
        # gemini-2.x 만 노출
        if "gemini-2" in name or "gemini-1.5" in name:
            out.append(name)
    # 보기 편하게 정렬
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
    genai.configure(api_key=api_key)

    # 모델명은 'models/' prefix 가 있을 수 있음 → 그대로 전달 가능.
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
    )

    records_text_parts = []
    for r in records:
        subject = r.get("subject") or ""
        records_text_parts.append(
            f"[ID:{r['record_id']}|영역:{r['area']}|과목:{subject}]\n{r['content']}"
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

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                model.generate_content,
                user_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            text = getattr(response, "text", None)
            if text is None:
                # 일부 SDK 버전 fallback
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
