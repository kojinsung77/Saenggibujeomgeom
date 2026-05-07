"""연도별 기재요령 규칙 DB 기반 로컬 위반 검사."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
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


def _load_rules(year: int) -> list[dict[str, Any]]:
    path = RULES_DIR / f"violations_{year}.json"
    if not path.exists():
        files = sorted(RULES_DIR.glob("violations_*.json"), reverse=True)
        if not files:
            return []
        path = files[0]
        logger.warning("[rule_checker] %d년 규칙 파일 없음 → %s 사용", year, path.name)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("patterns", [])


def list_rule_files() -> list[dict[str, Any]]:
    out = []
    for p in sorted(RULES_DIR.glob("violations_*.json"), reverse=True):
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
                "pattern_count": len(meta.get("patterns", [])),
            })
        except Exception:
            pass
    return out


def _check_content(content: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = []
    for rule in rules:
        try:
            matches = re.findall(rule["regex"], content)
        except re.error:
            continue
        if matches:
            hits.append({
                "rule_id": rule.get("id", ""),
                "type": rule.get("type", ""),
                "severity": rule.get("severity", "medium"),
                "evidence": ", ".join(dict.fromkeys(str(m) for m in matches if m)),
                "note": rule.get("note", ""),
            })
    return hits


def check_rules(
    year: int,
    areas: Optional[list[str]] = None,
    grade: Optional[int] = None,
    class_no: Optional[int] = None,
) -> dict[str, Any]:
    """DB 항목을 규칙 DB와 대조하여 로컬에서 위반 여부 판단."""
    rules = _load_rules(year)
    if not rules:
        return {"year": year, "total": 0, "violations": 0, "results": [], "error": "규칙 파일을 찾을 수 없습니다"}

    target_areas = areas or list(AREA_LABEL.keys())
    conn = get_connection()
    results: list[dict[str, Any]] = []

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
            if grade is not None:
                sql += " AND s.grade = ?"
                params.append(grade)
            if class_no is not None:
                sql += " AND s.class_no = ?"
                params.append(class_no)
            sql += " ORDER BY s.grade, s.class_no, s.number"

            for row in conn.execute(sql, params).fetchall():
                content = str(row["content"] or "")
                if not content.strip():
                    continue
                hits = _check_content(content, rules)
                results.append({
                    "area": area,
                    "area_label": AREA_LABEL.get(area, area),
                    "record_id": row["id"],
                    "student_id": row["student_id"],
                    "student_name": row["name"],
                    "grade": row["grade"],
                    "class_no": row["class_no"],
                    "number": row["number"],
                    "label": row["label"] or "",
                    "violation": len(hits) > 0,
                    "hits": hits,
                })
    finally:
        conn.close()

    violation_count = sum(1 for r in results if r["violation"])
    return {
        "year": year,
        "total": len(results),
        "violations": violation_count,
        "results": results,
    }
