"""Ollama 로컬 LLM 연동 — 띄어쓰기 검사 (개인정보 외부 전송 없음)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"


def _post(path: str, body: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    url = OLLAMA_BASE + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: int = 10) -> dict[str, Any]:
    url = OLLAMA_BASE + path
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_available() -> bool:
    try:
        _get("/api/tags", timeout=3)
        return True
    except Exception:
        return False


def list_models() -> list[str]:
    try:
        data = _get("/api/tags")
        return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        logger.warning("[ollama] 모델 목록 조회 실패: %s", e)
        return []


SPACING_PROMPT = """당신은 한국어 맞춤법·띄어쓰기 교정 전문가입니다.
다음 학생부 기록의 띄어쓰기 오류만 찾아 교정하세요.
내용의 의미는 변경하지 말고 띄어쓰기만 수정합니다.

[기록]
{content}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "errors": [
    {{"wrong": "잘못된부분", "correct": "올바른 부분", "context": "주변 문장 일부"}}
  ],
  "corrected_text": "전체 교정된 문장",
  "error_count": 오류개수
}}

띄어쓰기 오류가 없으면: {{"errors": [], "corrected_text": "{content}", "error_count": 0}}"""


def check_spacing(content: str, model: str) -> dict[str, Any]:
    """단일 레코드의 띄어쓰기를 검사해 결과 dict 반환."""
    if not content.strip():
        return {"errors": [], "corrected_text": content, "error_count": 0}

    prompt = SPACING_PROMPT.format(content=content)
    try:
        resp = _post(
            "/api/generate",
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 1024},
            },
            timeout=120,
        )
        raw = resp.get("response", "").strip()
        parsed = json.loads(raw)
        return {
            "errors": parsed.get("errors", []),
            "corrected_text": parsed.get("corrected_text", content),
            "error_count": int(parsed.get("error_count", len(parsed.get("errors", [])))),
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("[ollama] 응답 파싱 실패: %s", e)
        return {"errors": [], "corrected_text": content, "error_count": 0, "parse_error": str(e)}
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama 연결 실패: {e}") from e
