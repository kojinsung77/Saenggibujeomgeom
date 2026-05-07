"""점검 결과 Excel 내보내기 (xlsxwriter)."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

import xlsxwriter

from backend.database import get_connection


COLUMNS = [
    ("학년", "grade"),
    ("반", "class_no"),
    ("번호", "number"),
    ("성명", "student_name"),
    ("영역", "area"),
    ("위반", "violation_label"),
    ("카테고리", "category"),
    ("사유", "reason"),
    ("근거(위반 발췌)", "evidence"),
    ("수정 제안", "suggested_text"),
    ("처리시각", "processed_at"),
]

AREA_LABEL = {
    "subject_details": "세부능력및특기사항",
    "creative_activities": "창의적체험활동",
    "volunteer_activities": "봉사활동상황",
    "behavior_opinion": "행동특성및종합의견",
}


def _fetch_results(inspection_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conn = get_connection()
    try:
        meta_row = conn.execute(
            "SELECT * FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()
        if not meta_row:
            raise ValueError(f"inspection_id={inspection_id} 점검을 찾을 수 없습니다")
        meta = dict(meta_row)
        rows = conn.execute(
            """SELECT r.*, s.grade, s.class_no, s.number, s.name AS student_name
            FROM inspection_results r
            JOIN students s ON s.id = r.student_id
            WHERE r.inspection_id = ?
            ORDER BY r.violation DESC, s.grade, s.class_no, s.number, r.area""",
            (inspection_id,),
        ).fetchall()
        return meta, [dict(r) for r in rows]
    finally:
        conn.close()


def _write_table(ws, rows: Iterable[dict[str, Any]], formats: dict[str, Any]) -> None:
    headers = [c[0] for c in COLUMNS]
    for col, name in enumerate(headers):
        ws.write(0, col, name, formats["header"])

    widths = [6, 6, 6, 12, 18, 8, 18, 40, 40, 40, 20]
    for col, w in enumerate(widths):
        ws.set_column(col, col, w)

    r_idx = 1
    for row in rows:
        is_violation = bool(row.get("violation"))
        cell_fmt = formats["violation"] if is_violation else formats["normal"]
        row["violation_label"] = "위반" if is_violation else "정상"
        row["area"] = AREA_LABEL.get(row.get("area"), row.get("area", ""))
        for col, (_label, key) in enumerate(COLUMNS):
            ws.write(r_idx, col, row.get(key) if row.get(key) is not None else "", cell_fmt)
        r_idx += 1
    ws.freeze_panes(1, 0)


def export_inspection(inspection_id: int, filter_mode: str = "all") -> tuple[bytes, str]:
    """Excel 바이트와 권장 파일명을 반환."""
    meta, all_rows = _fetch_results(inspection_id)

    violations = [r for r in all_rows if r.get("violation")]
    normals = [r for r in all_rows if not r.get("violation")]

    if filter_mode == "violations":
        target_all = violations
    elif filter_mode == "normals":
        target_all = normals
    else:
        target_all = all_rows

    buf = BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    formats = {
        "header": wb.add_format({"bold": True, "bg_color": "#E8EDF7", "border": 1, "align": "center"}),
        "violation": wb.add_format({"font_color": "#C62828", "text_wrap": True, "valign": "top"}),
        "normal": wb.add_format({"font_color": "#424242", "text_wrap": True, "valign": "top"}),
        "label": wb.add_format({"bold": True, "bg_color": "#F5F5F5"}),
    }

    # 1) 요약 시트
    ws = wb.add_worksheet("요약")
    ws.set_column(0, 0, 18)
    ws.set_column(1, 1, 32)
    ws.write(0, 0, "점검 ID", formats["label"]); ws.write(0, 1, meta["id"])
    ws.write(1, 0, "시작 시각", formats["label"]); ws.write(1, 1, meta["started_at"])
    ws.write(2, 0, "완료 시각", formats["label"]); ws.write(2, 1, meta["completed_at"] or "")
    ws.write(3, 0, "상태", formats["label"]); ws.write(3, 1, meta["status"])
    ws.write(4, 0, "모델", formats["label"]); ws.write(4, 1, meta["model"])
    ws.write(5, 0, "배치 크기", formats["label"]); ws.write(5, 1, meta["batch_size"])
    ws.write(6, 0, "전체 레코드", formats["label"]); ws.write(6, 1, len(all_rows))
    ws.write(7, 0, "위반", formats["label"]); ws.write(7, 1, len(violations))
    ws.write(8, 0, "정상", formats["label"]); ws.write(8, 1, len(normals))

    # 2) 위반
    ws = wb.add_worksheet("위반")
    _write_table(ws, violations, formats)

    # 3) 정상
    ws = wb.add_worksheet("정상")
    _write_table(ws, normals, formats)

    # 4) 전체 (필터 무관하게 항상 전체 레코드)
    ws = wb.add_worksheet("전체")
    _write_table(ws, all_rows, formats)

    wb.close()
    data = buf.getvalue()
    buf.close()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"생기부점검결과_{ts}.xlsx"
    return data, filename
