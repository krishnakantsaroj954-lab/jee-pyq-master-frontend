#!/usr/bin/env python3
"""Isolated image-first JEE PYQ pipeline.

The source PDF is a scanned/image-only document. This pipeline intentionally
does not OCR, reconstruct, paraphrase, or invent question/solution text.
Each record points to the exact rendered source PDF page image. Options are
only the four labels A/B/C/D. There are no API, D1, Cloudflare, or live-site
writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import fitz

SOURCE_NAME = "cEDaK5Wn5ILe4nOdotd6.pdf"
EXPECTED_SOURCE_BLOB = "bc7570e370d5409b62dc3fe88d2d1dcc1378a0ab"
EXPECTED_PAGES = 24
EXPECTED_QUESTIONS = 75

# Visually verified question-start page map for the supplied 28 Jan 2026 Shift 1
# source PDF. A record references the exact source page; nothing is retyped.
QUESTION_PAGE_RANGES = [
    (1, 3, 2),
    (4, 6, 3),
    (7, 10, 4),
    (11, 12, 5),
    (13, 15, 6),
    (16, 18, 7),
    (19, 21, 8),
    (22, 24, 9),
    (25, 25, 10),
    (26, 28, 11),
    (29, 33, 12),
    (34, 37, 13),
    (38, 41, 14),
    (42, 45, 15),
    (46, 50, 16),
    (51, 53, 17),
    (54, 57, 18),
    (58, 59, 19),
    (60, 63, 20),
    (64, 66, 21),
    (67, 68, 22),
    (69, 73, 23),
    (74, 75, 24),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def page_for_question(q: int) -> int:
    for lo, hi, page in QUESTION_PAGE_RANGES:
        if lo <= q <= hi:
            return page
    raise ValueError(f"No verified source-page mapping for question {q}")


def subject_for_question(q: int) -> str:
    if 1 <= q <= 25:
        return "Mathematics"
    if 26 <= q <= 50:
        return "Physics"
    if 51 <= q <= 75:
        return "Chemistry"
    raise ValueError(f"Question number out of range: {q}")


def render_source_pages(doc: fitz.Document, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Direct full-page render: no crop and therefore no clipping/reconstruction.
    matrix = fitz.Matrix(1.25, 1.25)
    for page_no in range(1, len(doc) + 1):
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        if pix.width < 1500 or pix.height < 2000:
            raise ValueError(
                f"Source render unexpectedly small on page {page_no}: "
                f"{pix.width}x{pix.height}"
            )
        pix.save(str(out_dir / f"page-{page_no:04d}.jpg"), output="jpeg", jpg_quality=92)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build(pdf: Path, out_dir: Path) -> None:
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    with pdf.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise ValueError("Source is not a valid PDF")

    source_sha = sha256_file(pdf)
    if pdf.name != SOURCE_NAME:
        raise ValueError(f"Unexpected source filename: {pdf.name}")

    doc = fitz.open(pdf)
    try:
        page_count = len(doc)
        if page_count != EXPECTED_PAGES:
            raise ValueError(
                f"Unexpected source page count: expected {EXPECTED_PAGES}, got {page_count}"
            )

        text_chars = 0
        image_count_per_page = []
        for page_no, page in enumerate(doc, 1):
            text_chars += len(page.get_text("text") or "")
            image_count_per_page.append(len(page.get_images(full=True)))

        # The supplied source is an image-only scan. A non-zero text layer would
        # mean the pinned source changed and must be reviewed instead of guessed.
        if text_chars != 0:
            raise ValueError(
                f"Pinned source is no longer image-only: {text_chars} text characters found"
            )

        if not all(n > 0 for n in image_count_per_page):
            raise ValueError("At least one source page contains no embedded images")

        render_source_pages(doc, out_dir / "assets")

        rows = []
        for q in range(1, EXPECTED_QUESTIONS + 1):
            page_no = page_for_question(q)
            ref = f"assets/page-{page_no:04d}.jpg"
            if not (out_dir / ref).is_file():
                raise ValueError(f"Missing source page render: {ref}")

            rows.append(
                {
                    "id": f"{source_sha[:16]}-q{q:03d}",
                    "source_question_number": q,
                    "subject": subject_for_question(q),
                    "question_text": None,
                    "options": [{"key": c, "label": c} for c in "ABCD"],
                    "answer": None,
                    "solution_text": None,
                    "question": {
                        "type": "SOURCE_PDF_PAGE_IMAGE",
                        "image_refs": [ref],
                    },
                    "solution": {
                        "type": "SOURCE_PDF_PAGE_IMAGE",
                        "image_refs": [ref],
                    },
                    "provenance": {
                        "source_pdf": pdf.name,
                        "source_pdf_sha256": source_sha,
                        "source_page": page_no,
                        "content_mode": "source-rendered-page-image-only",
                        "text_extraction_persisted": False,
                    },
                    "status": "VALIDATED",
                }
            )

        expected_ids = list(range(1, EXPECTED_QUESTIONS + 1))
        if [r["source_question_number"] for r in rows] != expected_ids:
            raise ValueError("Question sequence is not exactly 1..75")

        if [r["subject"] for r in rows[:25]] != ["Mathematics"] * 25:
            raise ValueError("Questions 1..25 must be Mathematics")
        if [r["subject"] for r in rows[25:50]] != ["Physics"] * 25:
            raise ValueError("Questions 26..50 must be Physics")
        if [r["subject"] for r in rows[50:75]] != ["Chemistry"] * 25:
            raise ValueError("Questions 51..75 must be Chemistry")

        for row in rows:
            if row["question_text"] is not None or row["solution_text"] is not None:
                raise ValueError("No question/solution text may be persisted")
            if [x["key"] for x in row["options"]] != list("ABCD"):
                raise ValueError("Options must be exactly A/B/C/D")
            for section in ("question", "solution"):
                if section["type"] if False else False:
                    pass
                if row[section]["type"] != "SOURCE_PDF_PAGE_IMAGE":
                    raise ValueError("Non-image content mode detected")

        page_map = {
            str(q): {"question_page": page_for_question(q), "solution_page": page_for_question(q)}
            for q in range(1, EXPECTED_QUESTIONS + 1)
        }
        write_json(out_dir / "question-page-map.json", page_map)
        write_json(out_dir / "validated.json", rows)
        write_json(out_dir / "source-intake.json", {
            "source_pdf": pdf.name,
            "source_pdf_sha256": source_sha,
            "source_page_count": page_count,
            "source_text_characters": text_chars,
            "image_object_counts": image_count_per_page,
            "page_map_verified": True,
        })
        write_json(out_dir / "validation-report.json", {
            "status": "VALIDATED",
            "record_count": EXPECTED_QUESTIONS,
            "source_page_count": page_count,
            "content_mode": "PDF_PAGE_IMAGES_ONLY",
            "question_text_stored": False,
            "solution_text_stored": False,
            "options": ["A", "B", "C", "D"],
            "ocr_used_for_content": False,
            "database_write": False,
            "cloudflare_write": False,
        })
        write_json(out_dir / "IMPORT_READY.json", {
            "status": "VALIDATED",
            "record_count": EXPECTED_QUESTIONS,
            "source_pdf_sha256": source_sha,
            "database_write": False,
            "cloudflare_write": False,
            "instruction": "Review exact source page images before any separate import implementation.",
        })
    finally:
        doc.close()


def self_test() -> None:
    root = Path("_image_first_self_test")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    pdf = root / SOURCE_NAME

    doc = fitz.open()
    for _ in range(EXPECTED_PAGES):
        p = doc.new_page(width=2479, height=3508)
        p.draw_rect(fitz.Rect(50, 50, 2400, 3450))
        p.insert_text((100, 120), "SOURCE PAGE IMAGE")
        p.insert_text((100, 180), "No stored question or solution text")
    doc.save(pdf)
    doc.close()

    build(pdf, root / "out")
    rows = json.loads((root / "out" / "validated.json").read_text(encoding="utf-8"))
    report = json.loads((root / "out" / "validation-report.json").read_text(encoding="utf-8"))
    assert len(rows) == 75
    assert report["status"] == "VALIDATED"
    assert rows[0]["options"] == [{"key": c, "label": c} for c in "ABCD"]
    assert rows[0]["question_text"] is None
    assert rows[0]["solution_text"] is None
    shutil.rmtree(root)
    print("IMAGE-FIRST SELF-TEST PASSED")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.pdf is None or args.output is None:
        p.error("--pdf and --output are required unless --self-test is used")

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)

    try:
        build(args.pdf, args.output)
    except Exception as exc:
        write_json(args.output / "validation-report.json", {
            "status": "QUARANTINED",
            "error": str(exc),
            "database_write": False,
            "cloudflare_write": False,
        })
        print(f"QUARANTINED: {exc}")
        return 2

    print("IMAGE-FIRST REAL PDF VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
