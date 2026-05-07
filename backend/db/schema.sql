-- 학생 마스터 (교과성적 업로드 시 생성)
CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    grade       INTEGER NOT NULL,
    class_no    INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(grade, class_no, number, name)
);
CREATE INDEX IF NOT EXISTS idx_students_grade_class ON students(grade, class_no);

-- 교과성적
CREATE TABLE IF NOT EXISTS subject_grades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject         TEXT,
    original_score  REAL,
    achievement     TEXT,
    rank_grade      TEXT,
    semester        INTEGER,
    grade_year      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_grades_student ON subject_grades(student_id);

-- 세부능력및특기사항 (세특)
CREATE TABLE IF NOT EXISTS subject_details (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject     TEXT,
    content     TEXT NOT NULL,
    semester    INTEGER,
    grade_year  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_details_student ON subject_details(student_id);

-- 창의적체험활동 (창체)
CREATE TABLE IF NOT EXISTS creative_activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    area        TEXT,
    content     TEXT NOT NULL,
    hours       REAL,
    grade_year  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_creative_student ON creative_activities(student_id);

-- 봉사활동상황
CREATE TABLE IF NOT EXISTS volunteer_activities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    organization    TEXT,
    content         TEXT,
    hours           REAL,
    date            TEXT,
    grade_year      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_volunteer_student ON volunteer_activities(student_id);

-- 행동특성및종합의견 (행특)
CREATE TABLE IF NOT EXISTS behavior_opinion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    grade_year  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_behavior_student ON behavior_opinion(student_id);

-- 학년반이력 (선택적 — 학생별 학년/반 이력)
CREATE TABLE IF NOT EXISTS grade_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    grade_year  INTEGER,
    class_no    INTEGER,
    number      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_grade_history_student ON grade_history(student_id);

-- 시스템 프롬프트 (단일 행)
CREATE TABLE IF NOT EXISTS system_prompt (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_text  TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- 점검 세션
CREATE TABLE IF NOT EXISTS inspections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    status          TEXT NOT NULL,
    model           TEXT NOT NULL,
    batch_size      INTEGER NOT NULL,
    total_records   INTEGER NOT NULL DEFAULT 0,
    violations      INTEGER NOT NULL DEFAULT 0
);

-- 점검 결과 레코드
CREATE TABLE IF NOT EXISTS inspection_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id   INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    student_id      INTEGER NOT NULL REFERENCES students(id),
    area            TEXT NOT NULL,
    record_id       INTEGER NOT NULL,
    violation       INTEGER NOT NULL,
    category        TEXT,
    reason          TEXT,
    evidence        TEXT,
    suggested_text  TEXT,
    processed_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_results_inspection ON inspection_results(inspection_id);
CREATE INDEX IF NOT EXISTS idx_results_violation ON inspection_results(inspection_id, violation);
CREATE INDEX IF NOT EXISTS idx_results_student ON inspection_results(student_id);
