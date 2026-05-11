"""항목별 글자수·바이트 검증."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.config import RULES_DIR
from backend.database import get_connection

logger = logging.getLogger(__name__)

AREA_LABEL = {
    "subject_details": "세부능력및특기사항",
    "creative_activities": "창의적체험활동",
    "volunteer_activities": "봉사활동상황",
    "behavior_opinion": "행동특성및종합의견",
}


def _load_limits(year: int) -> dict[str, Any]:
    path = RULES_DIR / f"limits_{year}.json"
    if not path.exists():
        # 가장 최신 파일로 fallback
        files = sorted(RULES_DIR.glob("limits_*.json"), reverse=True)
        if not files:
            return {}
        path = files[0]
        logger.warning("[char_validator] %d년 한도 파일 없음 → %s 사용", year, path.name)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("areas", {})


def _available_years() -> list[int]:
    return sorted(
        int(p.stem.split("_")[1])
        for p in RULES_DIR.glob("limits_*.json")
        if p.stem.split("_")[1].isdigit()
    )


def validate_chars(
    year: int,
    grade: Optional[int] = None,
    class_no: Optional[int] = None,
) -> dict[str, Any]:
    """DB의 모든 항목을 글자수/바이트 기준으로 검증."""
    limits = _load_limits(year)
    conn = get_connection()
    results: list[dict[str, Any]] = []

    try:
        queries = {
            "subject_details": (
                "SELECT r.id, r.student_id, r.subject AS subject, r.content, "
                "s.grade, s.class_no, s.number, s.name "
                "FROM subject_details r JOIN students s ON s.id = r.student_id"
            ),
            "creative_activities": (
                "SELECT r.id, r.student_id, r.area AS subject, r.content, "
                "s.grade, s.class_no, s.number, s.name "
                "FROM creative_activities r JOIN students s ON s.id = r.student_id"
            ),
            "behavior_opinion": (
                "SELECT r.id, r.student_id, NULL AS subject, r.content, "
                "s.grade, s.class_no, s.number, s.name "
                "FROM behavior_opinion r JOIN students s ON s.id = r.student_id"
            ),
            "volunteer_activities": (
                "SELECT r.id, r.student_id, r.organization AS subject, "
                "COALESCE(r.content,'') AS content, "
                "s.grade, s.class_no, s.number, s.name "
                "FROM volunteer_activities r JOIN students s ON s.id = r.student_id"
            ),
        }

        for area, base_sql in queries.items():
            area_limits = limits.get(area, {})
            char_limit: Optional[int] = area_limits.get("chars")
            byte_limit: Optional[int] = area_limits.get("bytes")

            sql = base_sql + " WHERE 1=1"
            params: list[Any] = []
            if grade is not None:
                sql += " AND s.grade = ?"
                params.append(grade)
            if class_no is not None:
                sql += " AND s.class_no = ?"
                params.append(class_no)
            sql += " ORDER BY s.grade, s.class_no, s.number"

            for row in conn.execute(sql, params).fetchall():
                content = str(row["content"] or "")
                char_count = len(content)
                byte_count = len(content.encode("utf-8"))

                char_over = (char_count - char_limit) if char_limit and char_count > char_limit else 0
                byte_over = (byte_count - byte_limit) if byte_limit and byte_count > byte_limit else 0
                is_over = char_over > 0 or byte_over > 0

                results.append({
                    "area": area,
                    "area_label": AREA_LABEL.get(area, area),
                    "student_id": row["student_id"],
                    "student_name": row["name"],
                    "grade": row["grade"],
                    "class_no": row["class_no"],
                    "number": row["number"],
                    "subject": row["subject"] or "",
                    "char_count": char_count,
                    "char_limit": char_limit,
                    "char_over": char_over,
                    "byte_count": byte_count,
                    "byte_limit": byte_limit,
                    "byte_over": byte_over,
                    "is_over": is_over,
                })
    finally:
        conn.close()

    over_count = sum(1 for r in results if r["is_over"])
    return {
        "year": year,
        "total": len(results),
        "over_count": over_count,
        "results": results,
        "available_years": _available_years(),
    }
