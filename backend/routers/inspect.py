"""AI 점검 라우터: Gemini 연결, 프롬프트 CRUD, 점검 수명주기 + SSE."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend import state
from backend.config import API_KEY_FILE
from backend.database import DEFAULT_PROMPT, get_connection
from backend.models import (
    GeminiConnectRequest,
    GeminiConnectResponse,
    InspectionStartRequest,
    InspectionStartResponse,
    InspectionSummary,
    PromptResponse,
    PromptUpdate,
)
from backend.services import gemini_service, inspector


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["inspect"])


@router.post("/gemini/connect", response_model=GeminiConnectResponse)
async def gemini_connect(req: GeminiConnectRequest) -> GeminiConnectResponse:
    if not req.api_key.strip():
        raise HTTPException(400, "API 키가 비어 있습니다")
    try:
        models = await gemini_service.connect_and_list_models(req.api_key.strip())
    except Exception as e:
        logger.exception("[gemini/connect] 실패")
        raise HTTPException(400, f"Gemini 연결 실패: {e}") from e
    state.set_api_key(req.api_key.strip())
    try:
        API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        API_KEY_FILE.write_text(req.api_key.strip(), encoding="utf-8")
    except Exception:
        logger.warning("[gemini/connect] API 키 파일 저장 실패", exc_info=True)
    return GeminiConnectResponse(ok=True, models=models)


@router.get("/prompt", response_model=PromptResponse)
def get_prompt() -> PromptResponse:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT prompt_text, updated_at FROM system_prompt ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise HTTPException(500, "시스템 프롬프트가 초기화되지 않았습니다")
        return PromptResponse(prompt_text=row["prompt_text"], updated_at=row["updated_at"])
    finally:
        conn.close()


MAX_PROMPT = 20_000


@router.post("/prompt/reset", response_model=PromptResponse)
def reset_prompt() -> PromptResponse:
    """시스템 프롬프트를 기본값(DEFAULT_PROMPT)으로 복원."""
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE system_prompt SET prompt_text=?, updated_at=? "
            "WHERE id=(SELECT id FROM system_prompt ORDER BY id DESC LIMIT 1)",
            (DEFAULT_PROMPT, now),
        )
        if conn.total_changes == 0:
            conn.execute(
                "INSERT INTO system_prompt(prompt_text, updated_at) VALUES (?, ?)",
                (DEFAULT_PROMPT, now),
            )
        conn.commit()
        return PromptResponse(prompt_text=DEFAULT_PROMPT, updated_at=now)
    finally:
        conn.close()


@router.put("/prompt", response_model=PromptResponse)
def update_prompt(body: PromptUpdate) -> PromptResponse:
    if len(body.prompt_text) > MAX_PROMPT:
        raise HTTPException(400, f"프롬프트는 {MAX_PROMPT}자 이내로 작성해주세요")
    text = body.prompt_text.strip()
    if not text:
        raise HTTPException(400, "프롬프트가 비어 있습니다")
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE system_prompt SET prompt_text=?, updated_at=? "
            "WHERE id=(SELECT id FROM system_prompt ORDER BY id DESC LIMIT 1)",
            (text, now),
        )
        if conn.total_changes == 0:
            conn.execute(
                "INSERT INTO system_prompt(prompt_text, updated_at) VALUES (?, ?)",
                (text, now),
            )
        conn.commit()
        return PromptResponse(prompt_text=text, updated_at=now)
    finally:
        conn.close()


@router.post("/inspect/start", response_model=InspectionStartResponse)
async def inspect_start(req: InspectionStartRequest) -> InspectionStartResponse:
    api_key = state.get_api_key()
    if not api_key:
        raise HTTPException(400, "Gemini API 키가 설정되지 않았습니다. 먼저 /api/gemini/connect 를 호출하세요.")
    if not req.areas:
        raise HTTPException(400, "검사 영역을 1개 이상 선택하세요")
    if req.batch_size < 1 or req.batch_size > 5:
        raise HTTPException(400, "batch_size 는 1~5 사이여야 합니다")
    try:
        inspection_id, total = await inspector.start_inspection(
            api_key=api_key,
            model=req.model,
            batch_size=req.batch_size,
            areas=req.areas,
            grade=req.grade,
            class_no=req.class_no,
            student_ids=req.student_ids,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    logger.info("[inspect/start] inspection_id=%s targets=%s", inspection_id, total)
    return InspectionStartResponse(inspection_id=inspection_id)


@router.get("/inspect/stream/{inspection_id}")
async def inspect_stream(inspection_id: int):
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        inspector.event_stream(inspection_id),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/inspect/cancel/{inspection_id}")
def inspect_cancel(inspection_id: int):
    ok = inspector.cancel_inspection(inspection_id)
    return {"ok": ok}


@router.get("/inspections", response_model=list[InspectionSummary])
def list_inspections() -> list[InspectionSummary]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, started_at, completed_at, status, model, batch_size, "
            "total_records, violations FROM inspections ORDER BY id DESC"
        ).fetchall()
        return [
            InspectionSummary(
                id=r["id"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                status=r["status"],
                model=r["model"],
                batch_size=r["batch_size"],
                total_records=r["total_records"],
                violations=r["violations"],
            )
            for r in rows
        ]
    finally:
        conn.close()
