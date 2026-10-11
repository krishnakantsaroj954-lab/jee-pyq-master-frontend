from pathlib import Path
from types import SimpleNamespace
import fitz

from jee_pyq_pipeline.extract import extract
from jee_pyq_pipeline.validate import validate

def make_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    lines = [
        "Physics",
        "Question 1: Source question one",
        "(A) one (B) two (C) three (D) four",
        "Question 2: Source question two",
        "(A) one (B) two (C) three (D) four",
        "Solutions",
        "Solution 1: Answer A. Source solution one",
        "Solution 2: Answer B. Source solution two",
    ]
    y = 40
    for line in lines:
        page.insert_text((40, y), line, fontsize=11)
        y += 28
    doc.save(path)
    doc.close()

def cfg(pdf):
    return SimpleNamespace(
        source_pdf=pdf,
        release="test",
        exam="JEE-MAIN",
        year=2026,
        session="test",
        paper="test",
        subject="Physics",
        page_range=(1, 1),
        expected_question_count=2,
        expected_question_numbers=("Physics:1", "Physics:2"),
        subject_order=("Physics",),
        source_has_solutions=True,
        render_dpi=90,
        require_answers=True,
        source_zip=None,
    )

def test_image_first_round_trip(tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_pdf(pdf)
    questions, assets, extraction_issues, page_count = extract(cfg(pdf), tmp_path / "assets")

    assert page_count == 1
    assert not extraction_issues
    assert len(questions) == 2
    assert all(q.text == "" for q in questions)
    assert all(q.options == {"A":"A","B":"B","C":"C","D":"D"} for q in questions)
    assert all(q.assets and all(Path(a["path"]).is_file() for a in q.assets) for q in questions)
    assert all(q.solution and q.solution["mode"] == "source_pdf_image" for q in questions)
    assert all(q.solution["assets"] for q in questions)
    assert [q.answer for q in questions] == ["A", "B"]
    assert not validate(cfg(pdf), questions, page_count)

def test_validator_rejects_synthetic_question_text(tmp_path):
    pdf = tmp_path / "paper.pdf"
    make_pdf(pdf)
    questions, _, _, page_count = extract(cfg(pdf), tmp_path / "assets")
    questions[0].text = "invented question"
    issues = validate(cfg(pdf), questions, page_count)
    assert any(i.code == "QUESTION_TEXT_NOT_EMPTY" for i in issues)


def make_two_column_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=800, height=900)
    left = [
        "Physics", "Question 1: Left question one",
        "(A) one (B) two (C) three (D) four",
        "Question 2: Left question two",
        "(A) one (B) two (C) three (D) four",
    ]
    right = [
        "Question 3: Right question three",
        "(A) one (B) two (C) three (D) four",
        "Question 4: Right question four",
        "(A) one (B) two (C) three (D) four",
    ]
    y = 50
    for line in left:
        page.insert_text((40, y), line, fontsize=11)
        y += 32
    y = 50
    for line in right:
        page.insert_text((430, y), line, fontsize=11)
        y += 32
    y = 250
    for line in ("Solutions", "Solution 1: Answer A", "Solution 2: Answer B",
                 "Solution 3: Answer C", "Solution 4: Answer D"):
        page.insert_text((40, y), line, fontsize=11)
        y += 24
    doc.save(path)
    doc.close()

def cfg_two_column(pdf):
    return SimpleNamespace(
        source_pdf=pdf, release="test", exam="JEE-MAIN", year=2026,
        session="test", paper="test", subject="PCM", page_range=(1, 1),
        expected_question_count=4,
        expected_question_numbers=("Physics:1","Physics:2","Physics:3","Physics:4"),
        subject_order=("Physics",), source_has_solutions=True,
        render_dpi=90, require_answers=True, source_zip=None,
    )

def test_two_column_headers_are_not_merged(tmp_path):
    pdf = tmp_path / "two-column.pdf"
    make_two_column_pdf(pdf)
    questions, _, extraction_issues, page_count = extract(cfg_two_column(pdf), tmp_path / "assets")
    assert page_count == 1
    assert not extraction_issues
    assert [q.source_question_number for q in questions] == [1, 2, 3, 4]
