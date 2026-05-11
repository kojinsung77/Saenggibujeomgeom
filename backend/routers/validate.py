"""통합검사 라우터: 글자수 검증 / 로컬 규칙 검사 / 중복문장 / Ollama 띄어쓰기 / 규칙 업데이트."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import RULES_DIR
from backend.services import char_validator, duplicate_checker, ollama_service, rule_checker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/validate", tags=["validate"])


# ---------- Pydantic 요청 모델 ----------

class CharValidateRequest(BaseModel):
    year: int = 2025
    grade: Optional[int] = None
    class_no: Optional[int] = None


class RuleCheckRequest(BaseModel):
    year: int = 2025
    areas: Optional[list[str]] = None
    grade: Optional[int] = None
    class_no: Optional[int] = None


class DuplicateCheckRequest(BaseModel):
    areas: Optional[list[str]] = None
    grade: Optional[int] = None
    class_no: Optional[int] = None
    threshold: float = 0.7
    cross_student: bool = True
    within_student: bool = True


# 띄어쓰기 검사: 한 번에 처리할 최대 레코드 수 (서버 점거 방지)
SPACING_MAX_RECORDS = 200
# 전체 엔드포인트 최대 허용 시간 (초)
SPACING_TOTAL_TIMEOUT = 600  # 10분


class SpacingRequest(BaseModel):
    model: str
    student_ids: Optional[list[int]] = None
    areas: Optional[list[str]] = None
    grade: Optional[int] = None
    class_no: Optional[int] = None
    max_records: Optional[int] = None  # None이면 SPACING_MAX_RECORDS 적용


class RuleUpdateRequest(BaseModel):
    github_raw_url: str
    rule_type: str = "violations"  # "violations" | "limits"


# ---------- 엔드포인트 ----------

@router.post("/chars")
async def validate_chars(req: CharValidateRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            char_validator.validate_chars, req.year, req.grade, req.class_no
        )
    except Exception as e:
        logger.exception("[validate/chars] 실패")
        raise HTTPException(500, f"글자수 검증 실패: {e}") from e


@router.post("/rules")
async def check_rules(req: RuleCheckRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            rule_checker.check_rules, req.year, req.areas, req.grade, req.class_no
        )
    except Exception as e:
        logger.exception("[validate/rules] 실패")
        raise HTTPException(500, f"규칙 검사 실패: {e}") from e


@router.post("/duplicates")
async def check_duplicates(req: DuplicateCheckRequest) -> dict[str, Any]:
    if not (0.0 < req.threshold <= 1.0):
        raise HTTPException(400, "threshold는 0 초과 1 이하여야 합니다")
    try:
        return await asyncio.to_thread(
            duplicate_checker.check_duplicates,
            req.areas, req.grade, req.class_no,
            req.threshold, req.cross_student, req.within_student,
        )
    except Exception as e:
        logger.exception("[validate/duplicates] 실패")
        raise HTTPException(500, f"중복 검사 실패: {e}") from e


@router.post("/spacing")
async def check_spacing(req: SpacingRequest) -> dict[str, Any]:
    if not ollama_service.is_available():
        raise HTTPException(503, "Ollama가 실행 중이지 않습니다. 'ollama serve'를 먼저 실행하세요.")

    limit = min(req.max_records or SPACING_MAX_RECORDS, SPACING_MAX_RECORDS)

    from backend.database import get_connection
    conn = get_connection()
    records: list[dict[str, Any]] = []
    target_areas = req.areas or ["subject_details", "creative_activities", "behavior_opinion", "volunteer_activities"]

    AREA_LABEL = {
        "subject_details": "세부능력및특기사항",
        "creative_activities": "창의적체험활동",
        "volunteer_activities": "봉사활동상황",
        "behavior_opinion": "행동특성및종합의견",
    }
    queries: dict[str, str] = {
        "subject_details": (
            "SELECT r.id, r.student_id, r.subject AS label, r.content, "
            "s.grade, s.class_no, s.number, s.name "
            "FROM subject_details r JOIN students s ON s.id = r.student_id"
        ),
        "creative_activities": (
            "SELECT r.id, r.student_id, r.area AS label, r.content, "
            "s.grade, s.class_no, s.number, s.name "
            "FROM creative_activities r JOIN students s ON s.id = r.student_id"
        ),
        "behavior_opinion": (
            "SELECT r.id, r.student_id, NULL AS label, r.content, "
            "s.grade, s.class_no, s.number, s.name "
            "FROM behavior_opinion r JOIN students s ON s.id = r.student_id"
        ),
        "volunteer_activities": (
            "SELECT r.id, r.student_id, r.organization AS label, "
            "COALESCE(r.content,'') AS content, "
            "s.grade, s.class_no, s.number, s.name "
            "FROM volunteer_activities r JOIN students s ON s.id = r.student_id"
        ),
    }

    try:
        for area in target_areas:
            base_sql = queries.get(area)
            if not base_sql:
                continue
            sql = base_sql + " WHERE 1=1"
            params: list[Any] = []
            if req.grade is not None:
                sql += " AND s.grade = ?"
                params.append(req.grade)
            if req.class_no is not None:
                sql += " AND s.class_no = ?"
                params.append(req.class_no)
            if req.student_ids:
                phs = ",".join(["?"] * len(req.student_ids))
                sql += f" AND s.id IN ({phs})"
                params.extend(req.student_ids)
            sql += " ORDER BY s.grade, s.class_no, s.number"

            for row in conn.execute(sql, params).fetchall():
                content = str(row["content"] or "").strip()
                if not content:
                    continue
                records.append({
                    "record_id": row["id"],
                    "student_id": row["student_id"],
                    "student_name": row["name"],
                    "grade": row["grade"],
                    "class_no": row["class_no"],
                    "number": row["number"],
                    "area": area,
                    "area_label": AREA_LABEL.get(area, area),
                    "label": row["label"] or "",
                    "content": content,
                })
    finally:
        conn.close()

    # 레코드 수 제한 적용 (서버 점거 방지)
    total_in_db = len(records)
    records = records[:limit]
    if total_in_db > limit:
        logger.warning("[validate/spacing] 레코드 %d개 중 %d개만 검사 (최대 %d개 제한)",
                       total_in_db, limit, limit)

    results: list[dict[str, Any]] = []
    model = req.model
    error_count_total = 0

    async def _run_all() -> None:
        nonlocal error_count_total
        for rec in records:
            try:
                check_result = await asyncio.to_thread(
                    ollama_service.check_spacing, rec["content"], model
                )
            except ConnectionError as e:
                raise HTTPException(503, str(e)) from e
            except Exception as e:
                logger.warning("[validate/spacing] record_id=%s 실패: %s", rec["record_id"], e)
                check_result = {"errors": [], "corrected_text": rec["content"], "error_count": 0}

            results.append({
                **{k: rec[k] for k in ["record_id", "student_id", "student_name",
                                        "grade", "class_no", "number", "area",
                                        "area_label", "label"]},
                "error_count": check_result.get("error_count", 0),
                "errors": check_result.get("errors", []),
                "corrected_text": check_result.get("corrected_text", rec["content"]),
            })
            error_count_total += check_result.get("error_count", 0)

    try:
        await asyncio.wait_for(_run_all(), timeout=float(SPACING_TOTAL_TIMEOUT))
    except asyncio.TimeoutError:
        logger.warning("[validate/spacing] 전체 타임아웃 (%ds) - 처리된 %d/%d건 반환",
                       SPACING_TOTAL_TIMEOUT, len(results), len(records))

    return {
        "total_records": len(results),
        "total_in_db": total_in_db,
        "limit_applied": total_in_db > limit,
        "total_errors": error_count_total,
        "model": model,
        "results": results,
    }


# ---------- Ollama 상태 ----------

@router.get("/ollama/status")
def ollama_status() -> dict[str, Any]:
    available = ollama_service.is_available()
    models = ollama_service.list_models() if available else []
    return {"available": available, "models": models}


# ---------- 규칙 파일 목록 ----------

@router.get("/rules/list")
def list_rules() -> dict[str, Any]:
    return {
        "violations": rule_checker.list_rule_files(),
        "limits": _list_limits(),
    }


def _list_limits() -> list[dict[str, Any]]:
    out = []
    for p in sorted(RULES_DIR.glob("limits_*.json"), reverse=True):
        try:
            year_str = p.stem.split("_")[1]
            if not year_str.isdigit():
                continue
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
            out.append({
                "year": int(year_str),
                "source": meta.get("source", ""),
                "updated": meta.get("updated", ""),
            })
        except Exception:
            pass
    return out


# ---------- GitHub 규칙 업데이트 ----------

MAX_RULE_SIZE = 500_000  # 500KB


_ALLOWED_RULE_HOSTS = {"raw.githubusercontent.com", "github.com"}


@router.post("/rules/update")
async def update_rules(req: RuleUpdateRequest) -> dict[str, Any]:
    import urllib.parse
    url = req.github_raw_url.strip()
    if not url.startswith("https://"):
        raise HTTPException(400, "https:// URL만 허용됩니다")
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.hostname not in _ALLOWED_RULE_HOSTS:
        raise HTTPException(400, "github.com 또는 raw.githubusercontent.com URL만 허용됩니다")

    def _fetch() -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = resp.read(MAX_RULE_SIZE + 1)
            if len(data) > MAX_RULE_SIZE:
                raise ValueError("파일 크기가 500KB를 초과합니다")
            return data
        except urllib.error.URLError as e:
            raise ConnectionError(f"다운로드 실패: {e}") from e

    try:
        raw = await asyncio.to_thread(_fetch)
        parsed = json.loads(raw.decode("utf-8"))
    except ConnectionError as e:
        raise HTTPException(502, str(e)) from e
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON 파싱 실패: {e}") from e
    except ValueError as e:
        raise HTTPException(413, str(e)) from e

    rule_type = req.rule_type
    if rule_type not in ("violations", "limits"):
        raise HTTPException(400, "rule_type은 'violations' 또는 'limits' 중 하나여야 합니다")

    year = parsed.get("year")
    if not isinstance(year, int) or year < 2020 or year > 2099:
        raise HTTPException(400, "JSON에 유효한 'year' 필드(2020~2099)가 필요합니다")

    RULES_DIR.mkdir(parents=True, exist_ok=True)
    save_path = RULES_DIR / f"{rule_type}_{year}.json"
    save_path.write_bytes(raw)

    logger.info("[rules/update] %s 저장 완료", save_path.name)
    return {
        "ok": True,
        "saved": str(save_path.name),
        "year": year,
        "source": parsed.get("source", ""),
    }
