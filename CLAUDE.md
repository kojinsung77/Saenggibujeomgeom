# 생활기록부 점검 웹 서비스

## 프로젝트 개요

원본 데스크톱 exe 2종(`생기부_DB_생성기(v1.2).exe` + `생기부_AI_Inspector(v1.2).exe`)의 기능을 모두 반영하고 웹 환경의 편의 기능을 추가한 재구현 프로젝트. **구현 완료 상태** (v1.2, 2026-04-21).

**원본 프로그램 제작:** 대전복수고등학교 박영준 교사
**기술 스택:** Python FastAPI + SQLite + Google Gemini API + Vanilla JS
**GitHub:** https://github.com/tigerjk9/school-life-record
**실행:** `생기부점검_실행.bat` 더블클릭 → `http://127.0.0.1:8000`
**PRD:** `docs/PRD.md`

## 원본 exe 대비 반영 매트릭스

### 원본에서 가져온 기능 (동등 or 개선)

- 세특/창체/봉사/행특 **4개 영역** AI 점검
- 위반 근거(evidence, Before) + **수정 제안(suggested_text, After)**
- 학년/반/학생 단위 필터 점검
- 배치 크기 1~5 조정(기본값 3), API 키 검증 + 모델 자동 로드
- **학년반이력(6번째 파일)** DB 저장 지원
- **남은 시간 예상 표시** (ETA)
- 결과 Excel 내보내기 (원본 1시트 → 4시트로 개선)
- 상세 모달 비교 뷰

### 웹에서 추가한 기능

- 학생 조회 + 본문 키워드 **전문 검색**
- **검사 이력 DB 관리** (여러 차수 비교)
- **다크/라이트 모드**
- DB 자동 백업 (`record.db.bak.{timestamp}`)
- 프롬프트 웹 UI 편집 + **기본값 복원** 버튼
- 5개 탭 UI (업로드/조회/점검/결과/안내)

### 해결된 핵심 버그

- B-001: NEIS XLS 헤더 셀(`"1학년 3반 교과학습발달상황"`) 오감지 → 복합 셀 길이 조건 추가
- B-002: NEIS XLS 데이터 행에 "반" 컬럼이 없어 모든 학생 스킵 → `_extract_class_info` fallback
- B-003: 봉사 content 없으면 기관명이 있어도 스킵 → organization 기반 점검 로직 추가

## 작업 시 참고

- 프론트엔드 3파일: `frontend/index.html`, `frontend/style.css`, `frontend/app.js`
- 백엔드 진입점: `backend/main.py` (FastAPI + StaticFiles mount)
- DB 스키마: `backend/db/schema.sql`
- CSS 캐시 무효화: 현재 `?v=9` — 프론트 변경 시 버전 번호 올릴 것 (`index.html`의 2개 위치)
- 테마: `[data-theme="dark"]` 속성을 `<html>`에 설정, `localStorage`로 저장
- DEFAULT_PROMPT 변경 시: `backend/database.py` 수정 → 기존 사용자는 **기본값 복원** 버튼으로 반영
- Gemini 응답 필드 변경 시: `gemini_service.py` 프롬프트 + `inspector.py` 저장 로직 + `models.py` 동시 수정

## 자주 쓰는 디렉토리

```
backend/services/xls_parser.py   — NEIS XLS 파서 (헤더 자동 탐지 + 학년/반 추출)
backend/services/inspector.py    — 점검 오케스트레이션 + SSE + ETA 계산
backend/services/gemini_service.py — Gemini 배치 호출 (재시도)
backend/services/export_service.py — Excel 4시트 생성
backend/database.py              — DB 연결 + DEFAULT_PROMPT
backend/routers/inspect.py       — 프롬프트 GET/PUT/RESET + 점검 API
frontend/app.js                  — 단일 페이지 앱 (5탭)
docs/PRD.md                      — 제품 요구사항 문서
```

## 하네스

**목표:** NEIS XLS 업로드 → DB 구축 → Gemini AI 점검(4영역) → 결과 Excel 내보내기를 웹으로 제공

**트리거:** 추가 기능 개발·버그 수정·디자인 변경 요청 시 직접 처리. 원본 exe 동작과 충돌 의심 시 `_extracted/` 디렉토리의 pyc 바이트코드를 참고.

**변경 이력:**
| 날짜 | 버전 | 변경 내용 | 사유 |
|------|------|----------|------|
| 2026-04-20 | 1.0 | 초기 구현 완료 & GitHub 배포 | MVP 완성 |
| 2026-04-21 | 1.1 | NEIS XLS 파싱 버그(B-001/B-002) 수정 + suggested_text 전 스택 반영 | 원본 실행기와 비교 분석 결과 |
| 2026-04-21 | 1.2 | 봉사 점검 누락(B-003) 수정 + ETA 표시 + 프롬프트 기본값 복원 | 원본 AI Inspector 바이트코드 분석 |
| 2026-04-26 | 1.3 | 레드팀 감사: DB 중복 적재·Excel 필터 버그 수정, API 키 영속화(data/.apikey), DB 초기화 버튼, 임시 파일 자동 정리 | 보안·안정성 감사 |
