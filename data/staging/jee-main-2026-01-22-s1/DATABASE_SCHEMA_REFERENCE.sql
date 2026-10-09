-- SQLite-oriented relational schema for JEE PYQ Master.
-- Image paths stored here are relative to the extracted dataset bundle root.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    exam TEXT NOT NULL,
    year INTEGER NOT NULL,
    session TEXT,
    exam_date TEXT,
    shift INTEGER,
    paper_type TEXT,
    source_file TEXT,
    source_sha256 TEXT,
    source_match_status TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    question_number INTEGER NOT NULL,
    subject TEXT NOT NULL,
    chapter TEXT,
    topic TEXT,
    subtopic TEXT,
    question_type TEXT NOT NULL,
    question_text TEXT,
    question_ocr_raw TEXT,
    options_json TEXT,
    options_ocr_raw TEXT,
    correct_answer TEXT,
    correct_answer_raw_from_pdf TEXT,
    correct_answer_status TEXT,
    answer_text TEXT,
    solution_text TEXT,
    solution_ocr_raw TEXT,
    difficulty TEXT,
    marks_correct REAL,
    marks_incorrect REAL,
    extraction_status TEXT,
    options_extraction_method TEXT,
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (paper_id, question_number)
);

CREATE TABLE IF NOT EXISTS question_assets (
    asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('question_image', 'solution_image', 'source_page_image')),
    relative_path TEXT NOT NULL,
    UNIQUE (question_id, asset_type)
);

CREATE INDEX IF NOT EXISTS idx_questions_subject_chapter
    ON questions(subject, chapter);
CREATE INDEX IF NOT EXISTS idx_questions_year_subject
    ON questions(paper_id, subject, question_number);