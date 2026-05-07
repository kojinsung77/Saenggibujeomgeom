"""파싱된 NEIS XLS 데이터를 SQLite 로 적재."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.config import REQUIRED_AREA
from backend.database import backup_db, init_db, transaction
from backend.services import xls_parser


logger = logging.getLogger(__name__)


def _lookup_student(conn, cache: dict, key: tuple[int, int, int, str]) -> int | None:
    """학생 ID 조회만 수행 (없으면 None — 새 학생 생성 안 함)."""
    if key in cache:
        return cache[key]
    grade, class_no, number, name = key
    row = conn.execute(
        "SELECT id FROM students WHERE grade=? AND class_no=? AND number=? AND name=?",
        (grade, class_no, number, name),
    ).fetchone()
    if row:
        cache[key] = row["id"]
        return row["id"]
    return None


def _resolve_student(conn, cache: dict, key: tuple[int, int, int, str]) -> int:
    """학생 마스터 UPSERT 후 id 반환."""
    if key in cache:
        return cache[key]
    grade, class_no, number, name = key
    row = conn.execute(
        "SELECT id FROM students WHERE grade=? AND class_no=? AND number=? AND name=?",
        (grade, class_no, number, name),
    ).fetchone()
    if row:
        sid = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO students(grade, class_no, number, name) VALUES (?, ?, ?, ?)",
            (grade, class_no, number, name),
        )
        sid = cur.lastrowid
    cache[key] = sid
    return sid


def build_db(file_id_to_path: dict[str, str]) -> dict[str, Any]:
    """5개 영역 파일을 받아 DB 를 (재)구축한다.

    Args:
        file_id_to_path: area -> 업로드된 파일 절대경로

    Returns:
        {status, students, records_per_area, warnings}
    """
    if REQUIRED_AREA not in file_id_to_path or not file_id_to_path[REQUIRED_AREA]:
        raise ValueError("교과성적 파일이 필요합니다")

    # 모든 영역 파싱 (DB 트랜잭션 외부에서 — 파싱은 순수 read).
    parsed: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for area, path in file_id_to_path.items():
        if not path:
            continue
        try:
            res = xls_parser.parse_area(area, path)
            parsed[area] = res
            if res.get("unmatched"):
                warnings.append(f"{area}: 미매칭 컬럼 {res['unmatched']}")
            if res.get("skipped"):
                warnings.append(f"{area}: 학생 식별 불가로 {res['skipped']}행 건너뜀")
        except Exception as e:
            logger.exception("[db_builder] %s 파싱 실패", area)
            raise ValueError(f"{area} 파일 파싱 실패: {e}") from e

    backup_db()
    init_db()

    records_per_area: dict[str, int] = {a: 0 for a in xls_parser.PARSERS.keys()}
    student_cache: dict[tuple[int, int, int, str], int] = {}

    with transaction() as conn:
        # 기존 데이터 전체 초기화 (순서 중요: FK 제약 때문에 inspection_results → students 순)
        # students 삭제 시 CASCADE로 모든 content 테이블 자동 삭제됨
        conn.execute("DELETE FROM inspection_results")
        conn.execute("DELETE FROM inspections")
        conn.execute("DELETE FROM students")

        # 1) 교과성적 (학생 마스터 생성)
        sg_rows = parsed[REQUIRED_AREA]["rows"]
        sg_payload = []
        for r in sg_rows:
            key = (r["grade"], r["class_no"], r["number"], r["name"])
            sid = _resolve_student(conn, student_cache, key)
            sg_payload.append((
                sid,
                r.get("subject"),
                r.get("original_score"),
                r.get("achievement"),
                r.get("rank_grade"),
                r.get("semester"),
                r.get("grade_year"),
            ))
        if sg_payload:
            conn.executemany(
                """INSERT INTO subject_grades
                (student_id, subject, original_score, achievement, rank_grade, semester, grade_year)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                sg_payload,
            )
        records_per_area["subject_grades"] = len(sg_payload)

        # 2) 세특
        if "subject_details" in parsed:
            payload = []
            for r in parsed["subject_details"]["rows"]:
                key = (r["grade"], r["class_no"], r["number"], r["name"])
                sid = _resolve_student(conn, student_cache, key)
                payload.append((
                    sid,
                    r.get("subject"),
                    r.get("content"),
                    r.get("semester"),
                    r.get("grade_year"),
                ))
            if payload:
                conn.executemany(
                    """INSERT INTO subject_details
                    (student_id, subject, content, semester, grade_year)
                    VALUES (?, ?, ?, ?, ?)""",
                    payload,
                )
            records_per_area["subject_details"] = len(payload)

        # 3) 창체
        if "creative_activities" in parsed:
            payload = []
            for r in parsed["creative_activities"]["rows"]:
                key = (r["grade"], r["class_no"], r["number"], r["name"])
                sid = _resolve_student(conn, student_cache, key)
                payload.append((
                    sid,
                    r.get("area"),
                    r.get("content"),
                    r.get("hours"),
                    r.get("grade_year"),
                ))
            if payload:
                conn.executemany(
                    """INSERT INTO creative_activities
                    (student_id, area, content, hours, grade_year)
                    VALUES (?, ?, ?, ?, ?)""",
                    payload,
                )
            records_per_area["creative_activities"] = len(payload)

        # 4) 봉사
        if "volunteer_activities" in parsed:
            payload = []
            for r in parsed["volunteer_activities"]["rows"]:
                key = (r["grade"], r["class_no"], r["number"], r["name"])
                sid = _resolve_student(conn, student_cache, key)
                payload.append((
                    sid,
                    r.get("organization"),
                    r.get("content"),
                    r.get("hours"),
                    r.get("date"),
                    r.get("grade_year"),
                ))
            if payload:
                conn.executemany(
                    """INSERT INTO volunteer_activities
                    (student_id, organization, content, hours, date, grade_year)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    payload,
                )
            records_per_area["volunteer_activities"] = len(payload)

        # 5) 행특
        if "behavior_opinion" in parsed:
            payload = []
            for r in parsed["behavior_opinion"]["rows"]:
                key = (r["grade"], r["class_no"], r["number"], r["name"])
                sid = _resolve_student(conn, student_cache, key)
                payload.append((
                    sid,
                    r.get("content"),
                    r.get("grade_year"),
                ))
            if payload:
                conn.executemany(
                    """INSERT INTO behavior_opinion
                    (student_id, content, grade_year)
                    VALUES (?, ?, ?)""",
                    payload,
                )
            records_per_area["behavior_opinion"] = len(payload)

        # 6) 학년반이력 (선택적 — 학생 마스터가 없으면 스킵)
        if "grade_history" in parsed:
            payload = []
            for r in parsed["grade_history"]["rows"]:
                key = (r["grade"], r["class_no"], r["number"], r["name"])
                sid = _lookup_student(conn, student_cache, key)
                if sid is None:
                    continue
                payload.append((
                    sid,
                    r.get("grade_year"),
                    r.get("class_no"),
                    r.get("number"),
                ))
            if payload:
                conn.executemany(
                    """INSERT INTO grade_history
                    (student_id, grade_year, class_no, number)
                    VALUES (?, ?, ?, ?)""",
                    payload,
                )
            records_per_area["grade_history"] = len(payload)

    students_count = len(student_cache)
    return {
        "status": "ok",
        "students": students_count,
        "records_per_area": records_per_area,
        "warnings": warnings,
    }
