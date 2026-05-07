"""점검 결과 조회 / Excel 내보내기 라우터."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.database import get_connection
from backend.models import ResultRow
from backend.services import export_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["results"])


@router.get("/results", response_model=list[ResultRow])
def list_results(
    inspection_id: int = Query(...),
    filter: Optional[str] = Query(None, description="all|violations|normals"),
) -> list[ResultRow]:
    sql = (
        "SELECT r.id, r.inspection_id, r.student_id, r.area, r.record_id, "
        "r.violation, r.category, r.reason, r.evidence, r.suggested_text, r.processed_at, "
        "s.grade, s.class_no, s.number, s.name AS student_name "
        "FROM inspection_results r JOIN students s ON s.id = r.student_id "
        "WHERE r.inspection_id = ?"
    )
    params: list = [inspection_id]
    if filter == "violations":
        sql += " AND r.violation = 1"
    elif filter == "normals":
        sql += " AND r.violation = 0"
    sql += " ORDER BY r.violation DESC, s.grade, s.class_no, s.number, r.area"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [
            ResultRow(
                id=r["id"],
                inspection_id=r["inspection_id"],
                student_id=r["student_id"],
                student_name=r["student_name"],
                grade=r["grade"],
                class_no=r["class_no"],
                number=r["number"],
                area=r["area"],
                record_id=r["record_id"],
                violation=bool(r["violation"]),
                category=r["category"],
                reason=r["reason"],
                evidence=r["evidence"],
                suggested_text=r["suggested_text"],
                processed_at=r["processed_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/results/export")
async def export_results(
    inspection_id: int = Query(...),
    filter: Optional[str] = Query("all"),
):
    try:
        data, filename = await asyncio.to_thread(
            export_service.export_inspection, inspection_id, filter or "all"
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.exception("[results/export] 실패")
        raise HTTPException(500, f"Excel 생성 실패: {e}") from e

    quoted = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
    }
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
