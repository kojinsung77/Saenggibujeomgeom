# PRD — 생활기록부 점검 웹서비스

**버전**: 1.2 (2026-04-21 기준)
**원본**: 대전복수고등학교 박영준 교사 제작 `생기부_DB_생성기.exe` + `생기부_AI_Inspector(v1.1).exe`
**재구현**: https://github.com/tigerjk9/school-life-record

---

## 1. 배경 및 목적

### 1.1 문제 정의

- 교사는 학년말·학기말 학생부 기재 내용을 교육부 기재요령에 맞게 검토해야 함
- 전통적으로 학교별 자체 점검 or 수작업으로 진행 → 시간 소모 + 누락 위험
- 원본 박영준 교사 exe는 Windows 전용, 배포 관리 어려움, 기능 확장 제약

### 1.2 목표

1. NEIS에서 내보낸 XLS 5종을 로컬 웹 UI로 업로드·검토
2. Gemini AI로 기재요령 위반 여부 자동 판정 (세특·창체·봉사·행특 4개 영역)
3. 원본 exe의 핵심 기능을 모두 유지하면서 웹 환경의 이점(검색, 이력 관리, 다크 모드) 추가
4. 학교 네트워크 외부 노출 없이 `127.0.0.1`에서만 동작 (개인정보 보호)

---

## 2. 사용자 & 시나리오

### 2.1 주요 사용자

- **고등학교 교사** (담임/교과 담당) — Windows 10/11 PC 사용
- Python 기본 지식 없음 → 배치 파일 더블클릭으로만 실행 가능해야 함

### 2.2 핵심 시나리오

1. **학기말 일괄 점검**: 담임이 본인 반 전체 학생의 세특·창체·봉사·행특을 30분 내에 점검
2. **내용 검색**: "OO기업", "특정 대학명" 같은 금지 키워드가 본문에 있는지 빠르게 검색
3. **수정 가이드**: 위반 발견 시 AI의 수정 제안(After)을 참고하여 기재 내용 개선
4. **결과 공유**: 점검 결과 Excel을 교무부 or 관리자와 공유

---

## 3. 기능 요구사항

### 3.1 필수 기능 (P0)

| ID | 기능 | 구현 상태 |
|----|------|----------|
| F-001 | NEIS XLS 6종 업로드 (교과/세특/창체/봉사/행특/학년반이력) | ✅ |
| F-002 | XLS 헤더 자동 탐지 + 학년/반 정보 추출 | ✅ |
| F-003 | SQLite DB 구축 (6개 테이블, students 마스터) | ✅ |
| F-004 | Gemini API 키 입력 + 모델 목록 로드 | ✅ |
| F-005 | 4개 영역 중 선택적 일괄 점검 (세특/창체/봉사/행특) | ✅ |
| F-006 | 학년/반 필터 점검 | ✅ |
| F-007 | 위반 여부 + 유형 + 사유 + 근거(evidence) + 수정 제안(suggested_text) | ✅ |
| F-008 | 점검 결과 Excel 내보내기 (요약/위반/정상/전체 4시트) | ✅ |

### 3.2 추가 편의 기능 (P1)

| ID | 기능 | 구현 상태 |
|----|------|----------|
| F-101 | 학생 조회 (학년/반/이름 필터) | ✅ |
| F-102 | 본문 키워드 전문 검색 (세특/창체/봉사/행특) | ✅ |
| F-103 | 검사 이력 DB 관리 + 드롭다운 선택 | ✅ |
| F-104 | SSE 실시간 진행 표시 + 라이브 위반 목록 | ✅ |
| F-105 | 남은 시간 예상 (ETA) 표시 | ✅ |
| F-106 | 검사 취소 기능 | ✅ |
| F-107 | 다크/라이트 모드 토글 (localStorage 저장) | ✅ |
| F-108 | 시스템 프롬프트 편집 + 기본값 복원 | ✅ |
| F-109 | DB 자동 백업 (`record.db.bak.{timestamp}`) | ✅ |
| F-110 | 결과 모달 상세 뷰 (원문 + Before + After) | ✅ |
| F-111 | 사용 안내 탭 (설치·NEIS·탭별·FAQ) | ✅ |
| F-112 | DB 초기화 버튼 (업로드 탭, 전체 학생·점검 데이터 삭제) | ✅ |

### 3.3 해결된 버그

| ID | 버그 | 해결 |
|----|------|------|
| B-001 | NEIS XLS 헤더 오감지 ("1학년 3반 교과학습발달상황" 복합 셀을 헤더로 인식) | 길이 조건 `len(c) <= len(n)*2+2` 추가 |
| B-002 | NEIS XLS 데이터 행에 "반" 컬럼이 없어 모든 학생 스킵 | 상단 셀에서 `_extract_class_info`로 추출 후 fallback |
| B-003 | 봉사 점검 시 content 없으면 기관명이 있어도 스킵 | organization 기반 fallback + AI 프롬프트에 기관명 포함 |
| B-004 | 원본에만 있던 수정 제안(After) 누락 | `suggested_text` 전 스택 추가 (DB/API/Excel/UI) |
| B-005 | 원본에만 있던 남은 시간 예상 누락 | `ProgressEvent.eta_sec` 추가 + UI 표시 |
| B-006 | DB 재구축 시 기존 데이터 미삭제로 중복 적재 | build_db() 시작 시 DELETE 시퀀스 추가 |
| B-007 | Excel '전체' 시트가 filter_mode 영향을 받아 필터된 데이터만 출력 | `all_rows` 고정 사용 |
| B-008 | Gemini API 키가 서버 재시작 시 소실 | `data/.apikey` 파일로 영속화, 시작 시 자동 복원 |
| B-009 | 서버 재시작 시 24h 지난 임시 업로드 파일이 쌓임 | lifespan에서 자동 정리 |

---

## 4. 비기능 요구사항

### 4.1 보안

- 모든 통신은 `127.0.0.1`에서만 동작 (외부 노출 금지)
- Gemini API 키는 `data/.apikey` 파일로 영속화 (서버 재시작 후 자동 복원); 파일 시스템 외부 노출 금지
- 학생 개인정보 포함 → 로그에도 학생명 최소 출력

### 4.2 성능

- 학급 규모(30명 × 4영역 = ~120건) 점검이 5분 내 완료 (gemini-2.5-flash, 배치 3)
- Gemini API 지수 백오프 재시도 (최대 3회)
- 배치 크기 1~5 조정 가능

### 4.3 호환성

- Python 3.11+
- 브라우저: Chrome, Edge (EventSource/SSE 지원 필수)
- NEIS 학생부 항목별 조회 XLS 포맷 (.xls, .xlsx)

---

## 5. 기술 아키텍처

### 5.1 백엔드

```
FastAPI ─ uvicorn (127.0.0.1:8000)
   ├── /api/upload          (파일 업로드)
   ├── /api/db/build        (DB 구축)
   ├── /api/db/status       (DB 상태)
   ├── /api/db/reset        (DB 전체 초기화)
   ├── /api/students        (학생 목록/상세)
   ├── /api/search          (키워드 전문 검색)
   ├── /api/gemini/connect  (API 키 검증 + 모델 목록)
   ├── /api/prompt          (GET/PUT)
   ├── /api/prompt/reset    (POST — 기본값 복원)
   ├── /api/inspect/start   (점검 시작)
   ├── /api/inspect/stream  (SSE)
   ├── /api/inspect/cancel  (점검 취소)
   ├── /api/inspections     (이력 목록)
   ├── /api/results         (결과 조회)
   └── /api/results/export  (Excel)
```

### 5.2 DB 스키마 (SQLite, WAL 모드)

- `students` — 학생 마스터 (grade, class_no, number, name)
- `subject_grades` — 교과성적
- `subject_details` — 세특
- `creative_activities` — 창체
- `volunteer_activities` — 봉사 (organization, content)
- `behavior_opinion` — 행특
- `grade_history` — 학년반이력 (선택적)
- `system_prompt` — 시스템 프롬프트
- `inspections` — 점검 세션
- `inspection_results` — 점검 결과 (violation, category, reason, evidence, **suggested_text**)

### 5.3 프론트엔드

- Vanilla JS 단일 페이지 (`app.js`) + 5개 탭
- 디자인 시스템: forest green + warm neutral 팔레트
- CSS Custom Properties (`[data-theme="dark"]`)
- SSE (EventSource) 기반 실시간 진행 표시

---

## 6. 릴리스 이력

| 버전 | 날짜 | 내용 |
|------|------|------|
| 1.0 | 2026-04-20 | 초기 구현 (4개 영역 점검, Excel 내보내기, 다크모드) |
| 1.1 | 2026-04-21 | NEIS XLS 파싱 버그 수정 (헤더 오감지, 학년/반 추출) + suggested_text 추가 |
| 1.2 | 2026-04-21 | 봉사 점검 누락 버그 수정 + ETA 표시 + 프롬프트 기본값 복원 |
| 1.3 | 2026-04-26 | 레드팀 감사: DB 중복 적재·Excel 필터 버그 수정, API 키 영속화, DB 초기화 버튼 추가 |

---

## 7. 향후 개선 후보 (Out of Scope)

- 학년별 다년도 점검 결과 비교 (트렌드 분석)
- 학교 전체 단위 공유 서버 (인증/권한 필요)
- OCR 기반 수기 입력 본문 점검
- 영어 기재 항목 점검 (현재 한국어 프롬프트만)
- 모바일 최적화 (현재 반응형은 최소 지원)
