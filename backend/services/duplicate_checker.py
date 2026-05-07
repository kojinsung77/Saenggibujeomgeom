"""학생 간·학생 내 중복문장 검사 (difflib 기반, 완전 로컬)."""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any, Optional

from backend.database import get_connection

logger = logging.getLogger(__name__)

AREA_LABEL = {
    "subject_details": "세부능력및특기사항",
    "creative_activities": "창의적체험활동",
    "volunteer_activities": "봉사활동상황",
    "behavior_opinion": "행동특성및종합의견",
}


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _common_excerpt(a: str, b: str, max_len: int = 60) -> str:
    """두 문자열의 최장 공통 부분 문자열 반환."""
    matcher = SequenceMatcher(None, a, b)
    blocks = matcher.get_matching_blocks()
    best = max(blocks, key=lambda b: b.size, default=None)
    if best and best.size >= 10:
        snippet = a[best.a: best.a + best.size].strip()
        return snippet[:max_len] + ("…" if len(snippet) > max_len else "")
    return ""


def check_duplicates(
    areas: Optional[list[str]] = None,
    grade: Optional[int] = None,
    class_no: Optional[int] = None,
    threshold: float = 0.7,
    cross_student: bool = True,
    within_student: bool = True,
) -> dict[str, Any]:
    """DB 항목 간 유사도를 계산해 중복 쌍을 반환."""
    target_areas = areas or list(AREA_LABEL.keys())
    conn = get_connection()
    records: list[dict[str, Any]] = []

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

    pairs: list[dict[str, Any]] = []
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = records[i], records[j]
            # 같은 영역끼리만 비교
            if a["area"] != b["area"]:
                continue
            same_student = a["student_id"] == b["student_id"]
            if same_student and not within_student:
                continue
            if not same_student and not cross_student:
                continue

            sim = _similarity(a["content"], b["content"])
            if sim < threshold:
                continue

            pairs.append({
                "similarity": round(sim, 3),
                "common_excerpt": _common_excerpt(a["content"], b["content"]),
                "area": a["area"],
                "area_label": a["area_label"],
                "same_student": same_student,
                "record_a": {
                    "record_id": a["record_id"],
                    "student_id": a["student_id"],
                    "student_name": a["student_name"],
                    "grade": a["grade"],
                    "class_no": a["class_no"],
                    "number": a["number"],
                    "label": a["label"],
                },
                "record_b": {
                    "record_id": b["record_id"],
                    "student_id": b["student_id"],
                    "student_name": b["student_name"],
                    "grade": b["grade"],
                    "class_no": b["class_no"],
                    "number": b["number"],
                    "label": b["label"],
                },
            })

    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    return {
        "total_records": n,
        "pairs": pairs,
        "threshold": threshold,
    }
