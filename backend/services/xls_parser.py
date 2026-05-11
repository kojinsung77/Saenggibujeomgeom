"""NEIS 학생부 XLS/XLSX 파서.

각 영역(교과성적/세특/창체/봉사/행특)별로 파일을 읽어 표준화된
dict 리스트를 반환한다. NEIS 의 실제 컬럼명은 파일 버전에 따라 다를
수 있으므로 후보 컬럼명 리스트와 매칭하여 정규화한다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd


logger = logging.getLogger(__name__)


# 표준 키 -> 후보 컬럼명 (정규화 후 매칭)
COLUMN_MAPS: dict[str, list[str]] = {
    # NEIS XLS의 '학년' 컬럼은 기록학년(grade_year)을 의미한다.
    # 현재 학년(grade)은 파일 상단 헤더 셀 "X학년 Y반"에서 _extract_class_info로 추출한다.
    # grade_year를 먼저 처리해 '학년' 컬럼을 선점하면,
    # grade 매핑이 실패해 fallback_grade(현재 학년)를 올바르게 사용한다.
    "grade_year": ["학년", "학년도", "기록학년"],
    "grade": ["학년", "학년도"],          # grade_year가 선점 후 남은 컬럼으로 매핑됨
    "class_no": ["반"],
    "number": ["번호", "번"],
    "name": ["성명", "이름"],
    "subject": ["과목명", "과목"],
    "curriculum": ["교과"],
    "original_score": ["원점수"],
    "achievement": ["성취도"],
    "rank_grade": ["석차등급", "등급"],
    "semester": ["학기"],
    "content": [
        "세부능력및특기사항",
        "특기사항",
        "활동내용",
        "내용",
        "세특",
        "행동특성및종합의견",
        "종합의견",
    ],
    "area": ["영역", "활동영역"],
    "hours": ["시간", "이수시간", "활동시간"],
    "organization": ["기관명", "봉사기관명", "장소", "주관기관명"],
    "date": ["날짜", "봉사일", "일자", "기간"],
    "academic_year": ["학년도", "연도"],
}


def detect_engine(path: str | Path) -> str:
    """확장자에 따른 pandas read_excel engine 선택."""
    ext = Path(path).suffix.lower()
    if ext == ".xls":
        return "xlrd"
    return "openpyxl"


def _norm(s: Any) -> str:
    """컬럼명 정규화: 공백/줄바꿈/괄호/특수문자 제거."""
    if s is None:
        return ""
    text = str(s)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\(\)\[\]\{\}\.\:,/\-_]", "", text)
    return text


def _extract_class_info(raw: pd.DataFrame) -> tuple[Optional[int], Optional[int]]:
    """NEIS XLS 헤더 셀(예: '1학년 3반 교과학습발달상황')에서 현재 학년/반 추출.

    NEIS 출력 파일은 데이터 행에 '반' 컬럼이 없고, 파일 상단(보통 2~4행)
    어딘가의 셀에 'X학년 Y반' 패턴으로 현재 반 정보가 기입된다.
    영역별 파일마다 셀 위치가 다르므로 전체 상단 영역을 스캔한다.
    """
    scan_rows = min(10, len(raw))
    scan_cols = len(raw.columns)  # 모든 열 스캔 (세특 등은 학년/반 셀이 우측에 있음)
    for i in range(scan_rows):
        for j in range(scan_cols):
            val = raw.iloc[i, j]
            if val is None:
                continue
            try:
                if isinstance(val, float) and pd.isna(val):
                    continue
            except Exception:
                pass
            cell_str = str(val).strip()
            m = re.search(r'(\d+)\s*학년\s*(\d+)\s*반', cell_str)
            if m:
                return int(m.group(1)), int(m.group(2))
    return None, None


def read_with_header_autodetect(
    path: str | Path,
    sheet: int | str = 0,
) -> tuple[pd.DataFrame, Optional[int], Optional[int]]:
    """헤더 행을 자동 탐지하여 DataFrame + (current_grade, current_class) 반환.

    NEIS 학생부 XLS는 데이터 행에 '반' 컬럼이 없고 파일 상단 셀에
    'X학년 Y반' 형태로 반 정보가 있다. 이를 먼저 추출한 뒤,
    실제 컬럼 헤더 행을 탐지한다.

    헤더 탐지 규칙:
    - 셀 텍스트가 needle 단어와 '근접' 일치(len <= needle*2+2)하는 셀이 2개 이상인 행
    - 이 조건은 '1학년3반교과학습발달상황' 같은 복합 셀이 오탐지되는 것을 방지한다.
    """
    engine = detect_engine(path)
    raw = pd.read_excel(path, header=None, engine=engine, sheet_name=sheet, dtype=object)

    current_grade, current_class = _extract_class_info(raw)

    header_row: Optional[int] = None
    needles = {"학년", "반", "번호", "성명", "이름", "번", "학년도"}
    scan_limit = min(10, len(raw))
    for i in range(scan_limit):
        cells = [_norm(v) for v in raw.iloc[i].tolist()]
        # 셀 길이가 needle의 2배+2 이하인 경우만 헤더 셀로 인정
        # → '1학년3반교과학습발달상황'(15자) 같은 복합 셀 오탐지 방지
        header_cells = sum(
            1 for c in cells
            if c and any(n in c and len(c) <= len(n) * 2 + 2 for n in needles)
        )
        if header_cells >= 2:
            header_row = i
            break

    if header_row is None:
        header_row = 0
        logger.warning("[xls_parser] 헤더 자동탐지 실패 → 첫 행을 헤더로 간주: %s", path)

    df = pd.read_excel(path, header=header_row, engine=engine, sheet_name=sheet, dtype=object)
    df.columns = [str(c) for c in df.columns]

    # NEIS 창체 등은 이중 헤더를 사용한다:
    #   header_row  : 번 호 | 성  명 | 학년 | 창의적체험활동 | (empty) | (empty)
    #   header_row+1: (empty) | (empty) | 영역 | (empty) | 시간 | 특기사항
    # pandas는 header_row의 빈 셀을 "Unnamed: N"으로 만들고 header_row+1이
    # 데이터 첫 행으로 들어가 content/area 등 매핑이 실패한다.
    # 안전 조건: '번 호' 컬럼이 첫 행에서 NaN인 경우(= 실제 학생 번호가 없는 경우)만
    # 서브헤더 행으로 인정해 Unnamed 열의 이름을 보완한다.
    if len(df) > 0 and any(c.startswith("Unnamed:") for c in df.columns):
        num_col = next(
            (c for c in df.columns if _norm(c) in ("번호", "번")),
            None,
        )
        first_val = df.iloc[0][num_col] if num_col else None
        first_row_is_subheader = first_val is None or (
            isinstance(first_val, float) and pd.isna(first_val)
        ) or str(first_val).strip() in ("", "nan")

        if first_row_is_subheader:
            sub = df.iloc[0]
            rename: dict[str, str] = {}
            for col in df.columns:
                v = sub[col]
                if v is None:
                    continue
                try:
                    if isinstance(v, float) and pd.isna(v):
                        continue
                except Exception:
                    pass
                s = str(v).strip()
                if not s or s == "nan" or len(s) > 20:
                    continue
                if col.startswith("Unnamed:"):
                    rename[col] = s
                else:
                    # 명명된 컬럼도 서브헤더 값이 COLUMN_MAP 후보와 일치하면 교체
                    # (예: '창의적체험활동' → '영역' for 창체 이중헤더)
                    sn = _norm(s)
                    if sn != _norm(col):
                        for cands in COLUMN_MAPS.values():
                            if any(_norm(c) == sn for c in cands):
                                rename[col] = s
                                break
            if rename:
                df = df.rename(columns=rename)
                logger.info("[xls_parser] 이중헤더 탐지 — 서브헤더 행에서 컬럼명 보완: %s", list(rename.values()))

    return df, current_grade, current_class


def normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """원본 컬럼명을 표준 키로 매핑한 새 DF 반환.

    Returns:
        (renamed_df, mapping(std_key -> original), unmatched_originals)
    """
    norm_to_orig: dict[str, str] = {}
    for orig in df.columns:
        norm_to_orig[_norm(orig)] = orig

    # 학생 식별 키는 오탐지 방지를 위해 정확 일치만 허용한다.
    # 예: "누계시간(학년별)"이 부분 일치로 grade에 매핑되는 오류를 방지.
    EXACT_ONLY_KEYS = {"grade", "class_no", "number", "name"}

    mapping: dict[str, str] = {}
    used_orig: set[str] = set()
    for std_key, candidates in COLUMN_MAPS.items():
        for cand in candidates:
            n = _norm(cand)
            # 정확히 일치 우선
            if n in norm_to_orig and norm_to_orig[n] not in used_orig:
                mapping[std_key] = norm_to_orig[n]
                used_orig.add(norm_to_orig[n])
                break
        else:
            if std_key in EXACT_ONLY_KEYS:
                continue  # 학생 식별 키는 부분 일치 시도 안 함
            # 부분 일치 fallback (content, area 등 기술 컬럼에만 적용)
            for n_orig, orig in norm_to_orig.items():
                if orig in used_orig:
                    continue
                if any(_norm(c) and _norm(c) in n_orig for c in candidates):
                    mapping[std_key] = orig
                    used_orig.add(orig)
                    break

    unmatched = [c for c in df.columns if c not in used_orig]
    rename_map = {orig: std for std, orig in mapping.items()}
    renamed = df.rename(columns=rename_map)
    return renamed, mapping, unmatched


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        # 양의 정수만 추출 (학년/반/번호/학기는 양수여야 함)
        m = re.search(r"\d+", s)
        if not m:
            return None
        val = int(m.group())
        return val if val > 0 else None
    except Exception:
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    try:
        s = str(v).strip()
        if not s or s.lower() == "nan":
            return None
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group(0)) if m else None
    except Exception:
        return None


def _to_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _student_key(
    row: dict[str, Any],
    fallback_grade: Optional[int] = None,
    fallback_class: Optional[int] = None,
) -> Optional[tuple[int, int, int, str]]:
    g = _to_int(row.get("grade")) or fallback_grade
    c = _to_int(row.get("class_no")) or fallback_class
    n = _to_int(row.get("number"))
    name = _to_str(row.get("name"))
    if g is None or c is None or n is None or not name:
        return None
    return (g, c, n, name)


def _iter_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame 의 각 행을 dict 로 변환 — to_dict('records')가 iterrows()보다 ~100배 빠름."""
    return df.to_dict("records")


def _merge_continuations(
    rows: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """같은 key의 레코드를 순서 유지하며 content를 연결(페이지 분리 복원)."""
    seen: dict[tuple, int] = {}
    merged: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(str(row.get(f) if row.get(f) is not None else "") for f in key_fields)
        if key in seen:
            idx = seen[key]
            prev = (merged[idx].get("content") or "").rstrip()
            cur = (row.get("content") or "").lstrip()
            merged[idx]["content"] = prev + (" " if prev and cur else "") + cur
        else:
            seen[key] = len(merged)
            merged.append(dict(row))
    return merged


def _parse_generic(
    path: str | Path,
    *,
    area: str,
    extra_keys: tuple[str, ...] = (),
    ffill_extra: tuple[str, ...] = (),
) -> dict[str, Any]:
    """공통 파싱: header 자동탐지 → 정규화 → 행별 dict 변환.

    NEIS XLS는 데이터 행에 '반' 컬럼이 없는 경우가 많다.
    파일 상단 셀에서 추출한 (current_grade, current_class)를 fallback으로 사용.
    """
    df, current_grade, current_class = read_with_header_autodetect(path)
    df, mapping, unmatched = normalize_columns(df)
    if unmatched:
        logger.info("[xls_parser:%s] 미매칭 컬럼: %s", area, unmatched)

    if current_grade or current_class:
        logger.info("[xls_parser:%s] 파일 헤더 셀에서 현재 학년/반 추출: %s학년 %s반", area, current_grade, current_class)
    else:
        logger.warning("[xls_parser:%s] 학년/반 추출 실패 — fallback 없음. 데이터 행에 학년/반 컬럼이 있어야 합니다.", area)

    # NEIS XLS는 번호·성명이 병합 셀로 돼 있어 첫 행만 값이 있고
    # 이후 행은 NaN이 된다. forward-fill 로 빈 칸을 채워 파싱 누락을 방지한다.
    # grade/class_no 는 fallback_grade/fallback_class 로 채우므로 ffill 제외.
    for col in ("number", "name") + ffill_extra:
        if col in df.columns:
            df[col] = df[col].ffill()

    warnings: list[str] = []
    # class_no는 NEIS XLS 파일 헤더 셀에서 fallback으로 채울 수 있으므로 필수 아님
    required_keys = ("number", "name")
    missing_required = [k for k in required_keys if k not in mapping]
    if missing_required:
        msg = (
            f"[{area}] 필수 컬럼(번호/이름) 매핑 실패: missing={missing_required}. "
            "헤더 자동 탐지 결과를 확인하세요."
        )
        logger.warning(msg)
        warnings.append(msg)

    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw in _iter_rows(df):
        key = _student_key(raw, fallback_grade=current_grade, fallback_class=current_class)
        if key is None:
            skipped += 1
            continue
        rec = {
            "grade": key[0],
            "class_no": key[1],
            "number": key[2],
            "name": key[3],
        }
        for k in extra_keys:
            rec[k] = raw.get(k)
        rows.append(rec)

    if not rows:
        msg = (
            f"[{area}] 헤더 자동 탐지 후 파싱된 행이 없습니다. 파일 구조를 확인하세요. "
            f"(input_rows={len(df)}, skipped={skipped})"
        )
        logger.warning(msg)
        warnings.append(msg)

    return {
        "rows": rows,
        "mapping": mapping,
        "unmatched": unmatched,
        "skipped": skipped,
        "total_input": len(df),
        "warnings": warnings,
    }


def parse_subject_grades(path: str | Path) -> dict[str, Any]:
    """교과학습발달상황 파싱."""
    res = _parse_generic(
        path,
        area="subject_grades",
        extra_keys=("subject", "original_score", "achievement", "rank_grade", "semester", "grade_year"),
    )
    norm_rows = []
    for r in res["rows"]:
        subject = _to_str(r.get("subject"))
        original_score = _to_float(r.get("original_score"))
        achievement = _to_str(r.get("achievement"))
        rank_grade = _to_str(r.get("rank_grade"))
        # 과목·성적이 모두 없으면 파일 말미 빈/요약 행 — ffill 산물이므로 스킵.
        # 이 필터 없이는 마지막 학생(예: '하늘') 이름이 뒤따르는 빈 행에도
        # ffill 돼 유령 학생(동일 번호, 다른 이름)이 생성된다.
        if subject is None and original_score is None and achievement is None and rank_grade is None:
            continue
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "subject": subject,
            "original_score": original_score,
            "achievement": achievement,
            "rank_grade": rank_grade,
            "semester": _to_int(r.get("semester")),
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
        })
    res["rows"] = norm_rows
    return res


def parse_subject_details(path: str | Path) -> dict[str, Any]:
    """세부능력및특기사항 파싱."""
    res = _parse_generic(
        path,
        area="subject_details",
        extra_keys=("subject", "content", "semester", "grade_year"),
        ffill_extra=("grade_year",),
    )
    norm_rows = []
    for r in res["rows"]:
        content = _to_str(r.get("content"))
        if not content:
            continue
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "subject": _to_str(r.get("subject")),
            "content": content,
            "semester": _to_int(r.get("semester")),
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
        })
    # NEIS 인쇄 페이지 분리로 한 레코드가 여러 행으로 나뉘는 경우 병합
    norm_rows = _merge_continuations(norm_rows, ("number", "name", "grade_year", "subject"))
    res["rows"] = norm_rows
    return res


def parse_creative(path: str | Path) -> dict[str, Any]:
    """창의적체험활동 파싱."""
    res = _parse_generic(
        path,
        area="creative_activities",
        extra_keys=("area", "content", "hours", "grade_year"),
        # grade_year·area ffill: NEIS 창체는 이중헤더+인쇄 페이지 분리로
        # 연속 행에 학년·영역이 생략되므로 앞 행에서 전파한다.
        ffill_extra=("grade_year", "area"),
    )
    norm_rows = []
    for r in res["rows"]:
        content = _to_str(r.get("content"))
        if not content:
            continue
        area_val = _to_str(r.get("area"))
        # 헤더/서브헤더 행이 ffill로 전파된 메타 텍스트를 area 값으로 갖는 경우 제외
        if area_val in ("영역", "활동영역", "창의적체험활동"):
            area_val = None
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "area": area_val,
            "content": content,
            "hours": _to_float(r.get("hours")),
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
        })
    # NEIS 인쇄 페이지 분리로 한 영역 레코드가 여러 행으로 나뉘는 경우 병합
    norm_rows = _merge_continuations(norm_rows, ("number", "name", "grade_year", "area"))
    res["rows"] = norm_rows
    return res


def parse_volunteer(path: str | Path) -> dict[str, Any]:
    """봉사활동상황 파싱."""
    res = _parse_generic(
        path,
        area="volunteer_activities",
        extra_keys=("organization", "content", "hours", "date", "grade_year"),
        ffill_extra=("grade_year",),
    )
    norm_rows = []
    for r in res["rows"]:
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "organization": _to_str(r.get("organization")),
            "content": _to_str(r.get("content")),
            "hours": _to_float(r.get("hours")),
            "date": _to_str(r.get("date")),
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
        })
    res["rows"] = norm_rows
    return res


def parse_behavior(path: str | Path) -> dict[str, Any]:
    """행동특성및종합의견 파싱."""
    res = _parse_generic(
        path,
        area="behavior_opinion",
        extra_keys=("content", "grade_year"),
        ffill_extra=("grade_year",),
    )
    norm_rows = []
    for r in res["rows"]:
        content = _to_str(r.get("content"))
        if not content:
            continue
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "content": content,
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
        })
    # NEIS 인쇄 페이지 분리로 한 학생 행특이 여러 행으로 나뉘는 경우 병합
    norm_rows = _merge_continuations(norm_rows, ("number", "name", "grade_year"))
    res["rows"] = norm_rows
    return res


def parse_grade_history(path: str | Path) -> dict[str, Any]:
    """학년반이력 파싱 (선택적)."""
    res = _parse_generic(
        path,
        area="grade_history",
        extra_keys=("grade_year", "academic_year"),
    )
    norm_rows = []
    for r in res["rows"]:
        norm_rows.append({
            "grade": r["grade"],
            "class_no": r["class_no"],
            "number": r["number"],
            "name": r["name"],
            "grade_year": _to_int(r.get("grade_year")) or r["grade"],
            "academic_year": _to_int(r.get("academic_year")),
        })
    res["rows"] = norm_rows
    return res


PARSERS = {
    "subject_grades": parse_subject_grades,
    "subject_details": parse_subject_details,
    "creative_activities": parse_creative,
    "volunteer_activities": parse_volunteer,
    "behavior_opinion": parse_behavior,
    "grade_history": parse_grade_history,
}


def parse_area(area: str, path: str | Path) -> dict[str, Any]:
    fn = PARSERS.get(area)
    if not fn:
        raise ValueError(f"알 수 없는 영역: {area}")
    return fn(path)
