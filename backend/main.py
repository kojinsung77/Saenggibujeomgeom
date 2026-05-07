"""FastAPI 진입점.

- lifespan 에서 DB 초기화
- API 라우터 등록 후 frontend/ 정적 마운트
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import API_KEY_FILE, LOG_DIR, UPLOAD_DIR
from backend.database import init_db
from backend.routers import export, inspect, students, upload, validate
from backend import state


def _configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        str(LOG_DIR / "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(logging.INFO)


def _cleanup_upload_dir() -> None:
    """24시간 이상 지난 임시 업로드 파일 삭제."""
    cutoff = time.time() - 86400
    deleted = 0
    for f in UPLOAD_DIR.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    if deleted:
        logging.getLogger(__name__).info("[startup] 임시 파일 %d개 삭제", deleted)


def _restore_api_key() -> None:
    """저장된 API 키가 있으면 복원."""
    try:
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            state.set_api_key(key)
            logging.getLogger(__name__).info("[startup] API 키 복원 완료")
    except FileNotFoundError:
        pass
    except Exception:
        logging.getLogger(__name__).warning("[startup] API 키 복원 실패", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    init_db()
    _cleanup_upload_dir()
    _restore_api_key()
    logging.getLogger(__name__).info("Application startup complete")
    yield


app = FastAPI(title="생활기록부 점검 웹서비스", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

# 1) API 라우터 등록 (정적 마운트보다 먼저)
app.include_router(upload.router)
app.include_router(students.router)
app.include_router(inspect.router)
app.include_router(export.router)
app.include_router(validate.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# 2) 정적 파일 마운트 (마지막)
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
