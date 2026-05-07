"""SQLite connection helpers and schema initialization."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from backend.config import DB_PATH


DEFAULT_PROMPT = """당신은 학교생활기록부 기재요령 전문가입니다.
학생의 생활기록부 항목을 교육부 기재요령에 따라 검토하세요.
점검 영역은 세부능력및특기사항(세특), 창의적체험활동(창체), 봉사활동상황(봉사), 행동특성및종합의견(행특)입니다.

[검토 기준]
1. 기관명·상호명·기업명 직접 기재 금지 (예: 삼성전자, 네이버, OO병원)
   - 봉사활동 '기관명' 필드도 동일 기준 적용: 특정 기관명 대신 '○○ 기관', '지역 복지시설' 등으로 표기해야 함
2. 특정 대학명 기재 금지 (예: 서울대, 연세대, KAIST)
3. 학생 성명 외 타인 실명 기재 금지
4. 저작물 제목 과도한 나열 금지 (1~2개 예시는 허용)
5. 구체적 점수·등수 직접 기재 금지
6. 의미 불명확한 약어 사용 금지
7. ★ 학교 고유 명칭 직접 기재 금지 (봉사활동 기관명 제외): ○○고등학교, ○○고
   → 이 항목의 학교명(○○고등학교)을 반드시 본교 이름으로 변경하세요.

[봉사활동 특이사항]
- 기관명이 '기관명: OO' 형태로 제공된 경우, 해당 기관명이 특정 기업·병원·단체명인지 검토
- 활동 내용에 특정 기관·기업명이 언급된 경우도 위반

[주의] 위반 의심이나 확실하지 않으면 violation=false, reason 에 의심 내용 기재.
"""


def get_connection() -> sqlite3.Connection:
    """Open a new SQLite connection with WAL + FK + Row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Apply schema.sql (idempotent) and seed default system prompt if missing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).parent / "db" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        # 마이그레이션: suggested_text 컬럼이 없는 이전 DB 대응
        cols = [r[1] for r in conn.execute("PRAGMA table_info(inspection_results)").fetchall()]
        if "suggested_text" not in cols:
            conn.execute("ALTER TABLE inspection_results ADD COLUMN suggested_text TEXT")
            conn.commit()
        row = conn.execute("SELECT 1 FROM system_prompt LIMIT 1").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO system_prompt(prompt_text, updated_at) VALUES (?, ?)",
                (DEFAULT_PROMPT, datetime.now().isoformat()),
            )
        conn.commit()
    finally:
        conn.close()


def backup_db() -> Path | None:
    """Snapshot the current DB file (if any) to record.db.bak.{timestamp}."""
    if not DB_PATH.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = DB_PATH.parent / f"{DB_PATH.name}.bak.{ts}"
    shutil.copy2(str(DB_PATH), str(target))
    return target


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Context manager: BEGIN IMMEDIATE → commit on success, rollback on error."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
