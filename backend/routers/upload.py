"""파일 업로드 및 DB 구축 라우터."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend import state
from backend.config import (
    ALLOWED_EXTENSIONS,
    AREAS,
    DB_PATH,
    MAX_UPLOAD_SIZE,
    UPLOAD_DIR,
)
from backend.database import get_connection, transaction
from backend.models import (
    DBBuildRequest,
    DBBuildResponse,
    DBStatusResponse,
    UploadResponse,
)
from backend.services import db_builder


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...), area: str = Form(...)) -> UploadResponse:
    if area not in AREAS:
        raise HTTPException(400, f"알 수 없는 영역: {area}")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "XLS/XLSX 파일만 업로드 가능합니다")

    file_id = uuid.uuid4().hex
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    try:
        async with aiofiles.open(save_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_SIZE:
                    await out.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(413, "파일 크기 초과 (50MB)")
                await out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[upload] 저장 실패")
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"업로드 저장 실패: {e}") from e

    state.register_upload(file_id, str(save_path), area, file.filename or save_path.name)
    return UploadResponse(
        file_id=file_id,
        area=area,
        filename=file.filename or save_path.name,
        size=written,
    )


@router.post("/db/build", response_model=DBBuildResponse)
async def build_database(req: DBBuildRequest) -> DBBuildResponse:
    file_id_to_path: dict[str, str] = {}
    for area, fid in req.file_ids.items():
        if not fid:
            continue
        info = state.get_upload(fid)
        if not info:
            raise HTTPException(400, f"업로드되지 않은 file_id: {fid}")
        path, registered_area, _filename = info
        if registered_area != area:
            raise HTTPException(
                400,
                f"영역 불일치: file_id={fid}는 {registered_area}로 업로드되었습니다 (요청: {area})",
            )
        file_id_to_path[area] = path

    try:
        result = await asyncio.to_thread(db_builder.build_db, file_id_to_path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("[db/build] 실패")
        raise HTTPException(500, f"DB 구축 실패: {e}") from e

    # 성공 시 업로드된 임시 파일 정리 (실패해도 무시)
    for _area, path_str in file_id_to_path.items():
        try:
            Path(path_str).unlink(missing_ok=True)
        except OSError:
            logger.warning("[db/build] 임시 파일 삭제 실패: %s", path_str)
    for fid in list(req.file_ids.values()):
        if fid:
            try:
                state.remove_upload(fid)
            except Exception:
                pass

    return DBBuildResponse(
        status=result["status"],
        students=result["students"],
        records_per_area=result["records_per_area"],
    )


@router.post("/db/reset")
async def reset_database() -> dict:
    """모든 학생·점검 데이터를 삭제한다 (시스템 프롬프트는 유지)."""
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM inspection_results")
            conn.execute("DELETE FROM inspections")
            conn.execute("DELETE FROM students")
    except Exception as e:
        logger.exception("[db/reset] 실패")
        raise HTTPException(500, f"DB 초기화 실패: {e}") from e
    return {"ok": True, "message": "DB가 초기화되었습니다"}


@router.get("/db/status", response_model=DBStatusResponse)
def db_status() -> DBStatusResponse:
    if not DB_PATH.exists():
        return DBStatusResponse(exists=False)
    conn = get_connection()
    try:
        records: dict[str, int] = {}
        students = 0
        try:
            students = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
        except Exception:
            return DBStatusResponse(exists=False)
        for table in (
            "subject_grades",
            "subject_details",
            "creative_activities",
            "volunteer_activities",
            "behavior_opinion",
            "grade_history",
        ):
            try:
                records[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            except Exception:
                records[table] = 0
        return DBStatusResponse(exists=True, students=students, records=records)
    finally:
        conn.close()
