"""점검 오케스트레이션: 대상 레코드 수집 → 배치 호출 → DB 저장 → SSE 큐 push."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from backend import state
from backend.database import DEFAULT_PROMPT, get_connection, transaction
from backend.services import gemini_service


logger = logging.getLogger(__name__)


# 점검 대상 영역 (교과성적은 본문이 없으므로 제외)
INSPECTABLE_AREAS = ("subject_details", "creative_activities", "volunteer_activities", "behavior_opinion")

AREA_TABLE = {
    "subject_details": "subject_details",
    "creative_activities": "creative_activities",
    "volunteer_activities": "volunteer_activities",
    "behavior_opinion": "behavior_opinion",
}


def _fetch_targets(
    areas: list[str],
    grade: Optional[int] = None,
    class_no: Optional[int] = None,
    student_ids: Optional[list[int]] = None,
) -> list[dict[str, Any]]:
    """점검 대상 레코드 (id, student, content, ...) 리스트 반환."""
    out: list[dict[str, Any]] = []
    conn = get_connection()
    try:
        for area in areas:
            table = AREA_TABLE.get(area)
            if not table:
                continue

            # 영역별 SELECT (subject 컬럼 유무 분기)
            if area == "subject_details":
                cols = "r.id, r.student_id, r.subject, r.content"
            elif area == "creative_activities":
                cols = "r.id, r.student_id, r.area AS subject, r.content"
            elif area == "volunteer_activities":
                # organization과 content 모두 가져옴 (content 없어도 기관명으로 점검)
                cols = "r.id, r.student_id, r.organization, COALESCE(r.content,'') AS content"
            elif area == "behavior_opinion":
                cols = "r.id, r.student_id, NULL AS subject, r.content"
            else:
                continue

            sql = (
                f"SELECT {cols}, s.grade, s.class_no, s.number, s.name "
                f"FROM {table} r JOIN students s ON s.id = r.student_id "
                "WHERE 1=1 "
            )
            params: list[Any] = []
            if grade is not None:
                sql += "AND s.grade = ? "
                params.append(grade)
            if class_no is not None:
                sql += "AND s.class_no = ? "
                params.append(class_no)
            if student_ids:
                placeholders = ",".join(["?"] * len(student_ids))
                sql += f"AND s.id IN ({placeholders}) "
                params.extend(student_ids)
            sql += "ORDER BY s.grade, s.class_no, s.number, r.id"

            for row in conn.execute(sql, params).fetchall():
                if area == "volunteer_activities":
                    org = str(row["organization"] or "").strip()
                    raw = str(row["content"] or "").strip()
                    # 기관명 또는 활동내용 중 하나라도 있으면 점검 대상
                    if not org and not raw:
                        continue
                    # Gemini에게 기관명과 내용을 모두 제공
                    parts = []
                    if org:
                        parts.append(f"기관명: {org}")
                    if raw:
                        parts.append(raw)
                    effective_content = "\n".join(parts)
                    out.append({
                        "record_id": row["id"],
                        "student_id": row["student_id"],
                        "student_name": row["name"],
                        "grade": row["grade"],
                        "class_no": row["class_no"],
                        "number": row["number"],
                        "area": area,
                        "subject": org or None,
                        "content": effective_content,
                    })
                else:
                    content = row["content"]
                    if not content or not str(content).strip():
                        continue
                    out.append({
                        "record_id": row["id"],
                        "student_id": row["student_id"],
                        "student_name": row["name"],
                        "grade": row["grade"],
                        "class_no": row["class_no"],
                        "number": row["number"],
                        "area": area,
                        "subject": row.get("subject"),
                        "content": content,
                    })
    finally:
        conn.close()
    return out


def _get_system_prompt() -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT prompt_text FROM system_prompt ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prompt = row["prompt_text"] if row else ""
        return (prompt or "").strip() or DEFAULT_PROMPT
    finally:
        conn.close()


def create_inspection(model: str, batch_size: int) -> int:
    """inspections 행을 생성하고 id 반환."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO inspections(started_at, status, model, batch_size, total_records, violations) "
            "VALUES (?, 'running', ?, ?, 0, 0)",
            (datetime.now().isoformat(), model, batch_size),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


async def _push(queue: asyncio.Queue, event: str, data: dict[str, Any]) -> None:
    await queue.put((event, data))


def _update_total_records(inspection_id: int, total: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inspections SET total_records=? WHERE id=?",
            (total, inspection_id),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_batch_results(rows: list[tuple]) -> None:
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT INTO inspection_results
            (inspection_id, student_id, area, record_id,
             violation, category, reason, evidence, suggested_text, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _finalize_inspection(
    inspection_id: int, status: str, violations: int, processed: int
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inspections SET status=?, completed_at=?, violations=?, total_records=? WHERE id=?",
            (status, datetime.now().isoformat(), violations, processed, inspection_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_inspection_error(inspection_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inspections SET status='error', completed_at=? WHERE id=?",
            (datetime.now().isoformat(), inspection_id),
        )
        conn.commit()
    finally:
        conn.close()


async def _run(
    inspection_id: int,
    api_key: str,
    model: str,
    batch_size: int,
    targets: list[dict[str, Any]],
) -> None:
    queue = state.get_queue(inspection_id)
    cancel = state.get_cancel_event(inspection_id)
    assert queue is not None and cancel is not None

    started = time.time()
    total = len(targets)
    processed = 0
    violations = 0
    normals = 0

    system_prompt = await asyncio.to_thread(_get_system_prompt)

    # inspections.total_records 갱신
    await asyncio.to_thread(_update_total_records, inspection_id, total)

    def _eta(proc: int) -> Optional[float]:
        """남은 시간(초) 예측. 아직 처리된 게 없으면 None."""
        if proc <= 0:
            return None
        elapsed = time.time() - started
        avg = elapsed / proc
        remaining = max(0, total - proc)
        return round(avg * remaining, 1)

    try:
        if total == 0:
            await _push(queue, "progress", {"processed": 0, "total": 0, "eta_sec": None})
        for batch_start in range(0, total, batch_size):
            if cancel.is_set():
                logger.info("[inspector] 점검 %s 취소 요청 감지", inspection_id)
                break
            batch = targets[batch_start: batch_start + batch_size]
            current = batch[0]
            await _push(queue, "progress", {
                "processed": processed,
                "total": total,
                "current_student": f"{current['grade']}-{current['class_no']}-{current['number']} {current['student_name']}",
                "current_area": current["area"],
                "eta_sec": _eta(processed),
            })

            try:
                results = await gemini_service.inspect_batch(
                    api_key=api_key,
                    model_name=model,
                    system_prompt=system_prompt,
                    records=batch,
                )
            except Exception as e:
                logger.exception("[inspector] 배치 호출 실패")
                await _push(queue, "error", {
                    "message": "배치 호출 실패",
                    "detail": str(e),
                })
                # 실패 배치는 violation=null 로 기록하지 않고 건너뜀
                processed += len(batch)
                continue

            # record_id → 결과 dict 매핑
            by_id: dict[int, dict[str, Any]] = {}
            for r in results:
                try:
                    rid = int(r.get("record_id"))
                    by_id[rid] = r
                except Exception:
                    continue

            # DB 저장용 row + SSE 이벤트 payload 구성
            rows_to_insert: list[tuple] = []
            result_events: list[dict[str, Any]] = []
            now_iso = datetime.now().isoformat()
            for item in batch:
                rid = item["record_id"]
                if rid not in by_id:
                    # Gemini 응답에서 누락된 항목: 오류로 기록, 정상/위반 어느 쪽에도 포함하지 않음
                    rows_to_insert.append((
                        inspection_id,
                        item["student_id"],
                        item["area"],
                        rid,
                        0,
                        "검토오류",
                        "Gemini 응답에서 해당 항목 누락",
                        None,
                        None,
                        now_iso,
                    ))
                    result_events.append({
                        "student_id": item["student_id"],
                        "student_name": item["student_name"],
                        "grade": item["grade"],
                        "class_no": item["class_no"],
                        "number": item["number"],
                        "area": item["area"],
                        "record_id": rid,
                        "violation": False,
                        "category": "검토오류",
                        "reason": "Gemini 응답에서 해당 항목 누락",
                        "evidence": None,
                        "suggested_text": None,
                    })
                    continue

                res = by_id[rid]
                is_violation = bool(res.get("violation"))
                category = res.get("category")
                reason = res.get("reason")
                evidence = res.get("evidence")
                suggested_text = res.get("suggested_text")
                rows_to_insert.append((
                    inspection_id,
                    item["student_id"],
                    item["area"],
                    rid,
                    1 if is_violation else 0,
                    category,
                    reason,
                    evidence,
                    suggested_text,
                    now_iso,
                ))
                if is_violation:
                    violations += 1
                else:
                    normals += 1
                result_events.append({
                    "student_id": item["student_id"],
                    "student_name": item["student_name"],
                    "grade": item["grade"],
                    "class_no": item["class_no"],
                    "number": item["number"],
                    "area": item["area"],
                    "record_id": rid,
                    "violation": is_violation,
                    "category": category,
                    "reason": reason,
                    "evidence": evidence,
                    "suggested_text": suggested_text,
                })

            # DB 저장 (동기 SQLite 작업은 스레드로)
            if rows_to_insert:
                await asyncio.to_thread(_insert_batch_results, rows_to_insert)

            for ev in result_events:
                await _push(queue, "result", ev)

            processed += len(batch)
            await _push(queue, "progress", {
                "processed": processed,
                "total": total,
                "eta_sec": _eta(processed),
            })

        # 종료
        duration = time.time() - started
        status = "cancelled" if cancel.is_set() else "done"
        await asyncio.to_thread(
            _finalize_inspection, inspection_id, status, violations, processed
        )

        await _push(queue, "done", {
            "inspection_id": inspection_id,
            "total_violations": violations,
            "total_normal": normals,
            "duration_sec": round(duration, 2),
        })
    except Exception as e:
        logger.exception("[inspector] 치명적 오류")
        await asyncio.to_thread(_mark_inspection_error, inspection_id)
        await _push(queue, "error", {"message": "검사 중 오류", "detail": str(e)})
        await _push(queue, "done", {
            "inspection_id": inspection_id,
            "total_violations": violations,
            "total_normal": normals,
            "duration_sec": round(time.time() - started, 2),
        })
    finally:
        # 스트림 종료 sentinel
        await queue.put(None)


async def start_inspection(
    api_key: str,
    model: str,
    batch_size: int,
    areas: list[str],
    grade: Optional[int] = None,
    class_no: Optional[int] = None,
    student_ids: Optional[list[int]] = None,
) -> tuple[int, int]:
    """점검 시작. (inspection_id, total_targets) 반환."""
    valid_areas = [a for a in areas if a in INSPECTABLE_AREAS]
    if not valid_areas:
        raise ValueError("점검 가능한 영역이 없습니다")

    targets = await asyncio.to_thread(
        _fetch_targets,
        valid_areas,
        grade,
        class_no,
        student_ids,
    )
    inspection_id = await asyncio.to_thread(create_inspection, model, batch_size)
    state.register(inspection_id)

    task = asyncio.create_task(_run(
        inspection_id=inspection_id,
        api_key=api_key,
        model=model,
        batch_size=batch_size,
        targets=targets,
    ))
    state.set_task(inspection_id, task)
    return inspection_id, len(targets)


def cancel_inspection(inspection_id: int) -> bool:
    ev = state.get_cancel_event(inspection_id)
    if ev is None:
        return False
    ev.set()
    return True


async def event_stream(inspection_id: int) -> AsyncIterator[bytes]:
    """SSE 텍스트 스트림 (event:/data: 라인 쌍)."""
    queue = state.get_queue(inspection_id)
    if queue is None:
        # 이미 종료되었거나 존재하지 않음 → 즉시 종료 이벤트
        yield _format_sse("error", {"message": f"unknown inspection_id: {inspection_id}"})
        yield _format_sse("done", {"inspection_id": inspection_id, "total_violations": 0, "total_normal": 0, "duration_sec": 0})
        return

    try:
        # heartbeat 를 위해 wait_for 사용 (15초 타임아웃)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # SSE 주석으로 keep-alive
                yield b": keep-alive\n\n"
                continue
            if item is None:
                # sentinel
                break
            event, data = item
            yield _format_sse(event, data)
    finally:
        state.cleanup(inspection_id)


def _format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
