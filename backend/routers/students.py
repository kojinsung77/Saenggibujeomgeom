"""학생 조회 / 검색 라우터."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.database import get_connection
from backend.models import (
    RecordDetail,
    SearchHit,
    StudentDetailsResponse,
    StudentSummary,
)


router = APIRouter(prefix="/api", tags=["students"])


AREA_TABLES = {
    "subject_grades": "subject_grades",
    "subject_details": "subject_details",
    "creative_activities": "creative_activities",
    "volunteer_activities": "volunteer_activities",
    "behavior_opinion": "behavior_opinion",
}


@router.get("/students", response_model=list[StudentSummary])
def list_students(
    grade: Optional[int] = Query(None),
    class_no: Optional[int] = Query(None),
    name: Optional[str] = Query(None),
) -> list[StudentSummary]:
    sql = "SELECT id, grade, class_no, number, name FROM students WHERE 1=1"
    params: list = []
    if grade is not None:
        sql += " AND grade = ?"
        params.append(grade)
    if class_no is not None:
        sql += " AND class_no = ?"
        params.append(class_no)
    if name:
        sql += " AND name LIKE ?"
        params.append(f"%{name}%")
    sql += " ORDER BY grade, class_no, number"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return []
        ids = [r["id"] for r in rows]

        # 영역별 작성여부 조회
        areas_present: dict[int, dict[str, bool]] = {sid: {a: False for a in AREA_TABLES} for sid in ids}
        placeholders = ",".join(["?"] * len(ids))
        for area, table in AREA_TABLES.items():
            q = f"SELECT DISTINCT student_id FROM {table} WHERE student_id IN ({placeholders})"
            for r in conn.execute(q, ids).fetchall():
                areas_present[r["student_id"]][area] = True

        out = []
        for r in rows:
            out.append(StudentSummary(
                id=r["id"],
                grade=r["grade"],
                class_no=r["class_no"],
                number=r["number"],
                name=r["name"],
                areas=areas_present[r["id"]],
            ))
        return out
    finally:
        conn.close()


@router.get("/students/{student_id}/details", response_model=StudentDetailsResponse)
def student_details(
    student_id: int,
    area: Optional[str] = Query(None),
) -> StudentDetailsResponse:
    conn = get_connection()
    try:
        s = conn.execute(
            "SELECT id, grade, class_no, number, name FROM students WHERE id=?",
            (student_id,),
        ).fetchone()
        if not s:
            raise HTTPException(404, "학생을 찾을 수 없습니다")

        # 영역별 데이터 수집
        areas_present = {a: False for a in AREA_TABLES}
        for a, t in AREA_TABLES.items():
            row = conn.execute(
                f"SELECT 1 FROM {t} WHERE student_id=? LIMIT 1", (student_id,)
            ).fetchone()
            areas_present[a] = bool(row)

        records: list[RecordDetail] = []
        target_areas = [area] if area else list(AREA_TABLES.keys())
        for a in target_areas:
            if a not in AREA_TABLES:
                continue
            t = AREA_TABLES[a]
            if a == "subject_grades":
                rows = conn.execute(
                    f"SELECT id, subject, original_score, achievement, rank_grade, semester, grade_year "
                    f"FROM {t} WHERE student_id=? ORDER BY grade_year, semester, subject",
                    (student_id,),
                ).fetchall()
                for r in rows:
                    parts = []
                    if r["original_score"] is not None:
                        parts.append(f"원점수 {r['original_score']}")
                    if r["achievement"]:
                        parts.append(f"성취도 {r['achievement']}")
                    if r["rank_grade"]:
                        parts.append(f"등급 {r['rank_grade']}")
                    records.append(RecordDetail(
                        area=a,
                        content=" / ".join(parts),
                        subject=r["subject"],
                        grade_year=r["grade_year"],
                        semester=r["semester"],
                        record_id=r["id"],
                    ))
            elif a == "subject_details":
                rows = conn.execute(
                    f"SELECT id, subject, content, semester, grade_year FROM {t} WHERE student_id=? ORDER BY grade_year, semester",
                    (student_id,),
                ).fetchall()
                for r in rows:
                    records.append(RecordDetail(
                        area=a, content=r["content"], subject=r["subject"],
                        grade_year=r["grade_year"], semester=r["semester"], record_id=r["id"],
                    ))
            elif a == "creative_activities":
                rows = conn.execute(
                    f"SELECT id, area, content, hours, grade_year FROM {t} WHERE student_id=? ORDER BY grade_year",
                    (student_id,),
                ).fetchall()
                for r in rows:
                    records.append(RecordDetail(
                        area=a, content=r["content"], subject=r["area"],
                        grade_year=r["grade_year"], record_id=r["id"],
                        extra={"hours": r["hours"]},
                    ))
            elif a == "volunteer_activities":
                rows = conn.execute(
                    f"SELECT id, organization, content, hours, date, grade_year FROM {t} WHERE student_id=? ORDER BY grade_year, date",
                    (student_id,),
                ).fetchall()
                for r in rows:
                    records.append(RecordDetail(
                        area=a,
                        content=r["content"] or r["organization"] or "",
                        subject=r["organization"],
                        grade_year=r["grade_year"],
                        record_id=r["id"],
                        extra={"hours": r["hours"], "date": r["date"]},
                    ))
            elif a == "behavior_opinion":
                rows = conn.execute(
                    f"SELECT id, content, grade_year FROM {t} WHERE student_id=? ORDER BY grade_year",
                    (student_id,),
                ).fetchall()
                for r in rows:
                    records.append(RecordDetail(
                        area=a, content=r["content"], grade_year=r["grade_year"], record_id=r["id"],
                    ))

        summary = StudentSummary(
            id=s["id"], grade=s["grade"], class_no=s["class_no"],
            number=s["number"], name=s["name"], areas=areas_present,
        )
        return StudentDetailsResponse(student=summary, records=records)
    finally:
        conn.close()


@router.get("/search", response_model=list[SearchHit])
def search(
    keyword: str = Query(..., min_length=1),
    area: Optional[str] = Query(None),
) -> list[SearchHit]:
    """본문/과목명 LIKE 검색."""
    needle = f"%{keyword}%"
    out: list[SearchHit] = []
    conn = get_connection()
    try:
        target_areas = [area] if area and area in AREA_TABLES else list(AREA_TABLES.keys())
        for a in target_areas:
            if a == "subject_grades":
                continue  # 본문 없음
            t = AREA_TABLES[a]
            if a == "volunteer_activities":
                content_col = "COALESCE(r.content,'') || ' ' || COALESCE(r.organization,'')"
            else:
                content_col = "r.content"
            sql = (
                f"SELECT r.id AS record_id, s.id AS student_id, s.grade, s.class_no, "
                f"s.number, s.name, {content_col} AS content "
                f"FROM {t} r JOIN students s ON s.id = r.student_id "
                f"WHERE {content_col} LIKE ? "
                "ORDER BY s.grade, s.class_no, s.number LIMIT 200"
            )
            for r in conn.execute(sql, (needle,)).fetchall():
                content = (r["content"] or "")
                idx = content.lower().find(keyword.lower())
                if idx == -1:
                    snippet = content[:80]
                else:
                    start = max(0, idx - 20)
                    end = min(len(content), idx + len(keyword) + 40)
                    snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
                out.append(SearchHit(
                    record_id=r["record_id"],
                    student_id=r["student_id"],
                    student_name=r["name"],
                    grade=r["grade"],
                    class_no=r["class_no"],
                    number=r["number"],
                    area=a,
                    snippet=snippet,
                ))
        return out
    finally:
        conn.close()
