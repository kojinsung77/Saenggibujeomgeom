"""Configuration constants for the school-life-record backend.

Loads paths and limits from environment (.env supported) and ensures
required directories exist on import.

frozen 모드(PyInstaller exe) 지원:
  - BUNDLE_DIR : sys._MEIPASS (읽기 전용 번들 리소스)
  - APP_DIR    : exe 옆 디렉터리 (쓰기 가능, DB·로그 저장)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _bundle_dir() -> Path:
    """읽기 전용 리소스 루트 (frozen: _MEIPASS, 개발: 프로젝트 루트)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _app_dir() -> Path:
    """쓰기 가능 루트 (frozen: exe 옆, 개발: 프로젝트 루트)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BUNDLE_DIR: Path = _bundle_dir()
APP_DIR: Path = _app_dir()
PROJECT_ROOT: Path = APP_DIR  # 하위 호환성

# 읽기 전용 리소스
FRONTEND_DIR: Path = BUNDLE_DIR / "frontend"
RULES_DIR: Path = BUNDLE_DIR / "rules"
SCHEMA_PATH: Path = BUNDLE_DIR / "backend" / "db" / "schema.sql"

# 쓰기 가능 경로
def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = APP_DIR / p
    return p


DB_PATH: Path = _resolve(os.environ.get("DB_PATH", "data/record.db"))
UPLOAD_DIR: Path = _resolve(os.environ.get("UPLOAD_DIR", "data/uploads"))
LOG_DIR: Path = _resolve(os.environ.get("LOG_DIR", "logs"))
API_KEY_FILE: Path = APP_DIR / "data" / ".apikey"

# Constraints
MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS: set[str] = {".xls", ".xlsx"}

# Upload area identifiers (must match xls_parser/db_builder dispatch keys).
AREAS: tuple[str, ...] = (
    "subject_grades",      # 교과학습발달상황 (필수)
    "subject_details",     # 세부능력및특기사항
    "creative_activities", # 창의적체험활동
    "volunteer_activities",# 봉사활동상황
    "behavior_opinion",    # 행동특성및종합의견
    "grade_history",       # 학년반이력 (선택)
)

REQUIRED_AREA: str = "subject_grades"


def ensure_dirs() -> None:
    """Create runtime directories if missing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


# Eager directory creation so other modules can rely on existence.
ensure_dirs()
