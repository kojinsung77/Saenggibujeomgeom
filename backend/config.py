"""Configuration constants for the school-life-record backend.

Loads paths and limits from environment (.env supported) and ensures
required directories exist on import.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # python-dotenv is optional at import time; failure is non-fatal.
    pass


# Project root (school-life-record/)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Resolve potentially relative paths against project root.
def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


DB_PATH: Path = _resolve(os.environ.get("DB_PATH", "data/record.db"))
UPLOAD_DIR: Path = _resolve(os.environ.get("UPLOAD_DIR", "data/uploads"))
LOG_DIR: Path = _resolve(os.environ.get("LOG_DIR", "logs"))
API_KEY_FILE: Path = _resolve("data/.apikey")

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
