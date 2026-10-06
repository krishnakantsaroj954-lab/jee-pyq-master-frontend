#!/usr/bin/env python3
"""
JEE PYQ Master - isolated image-first PDF pipeline v2.

Only source-PDF rendered page images are stored for question/solution content.
No OCR/reconstructed question text or solution text is stored.
Options are exactly A, B, C, D.
No API, D1, Cloudflare, or live-site writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


QUESTION_RE = re.compile(
    r"^\s*(?:question\s*(?:no\.?|number|#)?\s*|q\.?\s*)(\d{1,3})\b",
    re.IGNORECASE | re.MULTILINE,
)
SOLUTION_RE = re.compile(
    r"^\s*(?:solution|sol\.?|explanation)\b"
    r"(?:\s*(?:for\s*)?(?:question\s*)?(?:no\.?|number|#)?\s*(\d{1,3})\b)?",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Marker:
    page: int
    number: int | None
    offset: int


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def markers(texts: list[str], rx: re.Pattern[str]) -> list[Marker]:
    out = []
    for page_no, text in enumerate(texts, 1):
        for m in rx.finditer(text):
            out.append(Marker(page_no, int(m.group(1)) if m.group(1) else None, m.start()))
    return out


def question_starts(items: list[Marker], expected: int) -> list[Marker]:
    # Keep the first explicit occurrence of each number. Line anchoring prevents
    # ordinary "Question 4" mentions inside prose from becoming new questions.
    seen = set()
    out = []
    for item in sorted(items, key=lambda x: (x.page, x.offset)):
        if item.number is None or item.number in seen:
            continue
        seen.add(item.number)
        out.append(item)
    if len(out) != expected:
        raise ValueError(f"Expected {expected} question starts, detected {len(out)}")
    nums = [x.number for x in out]
    valid = list(range(1, expected + 1))
    if expected == 75:
        valid_patterns = (valid, list(range(1, 26)) * 3)
    else:
        valid_patterns = (valid,)
    if nums not in valid_patterns:
        raise ValueError("Question numbering is ambiguous; refusing to guess")
    return out


def solution_starts(items: list[Marker], expected: int) -> list[Marker]:
    items = sorted(items, key=lambda x: (x.page, x.offset))
    if len(items) != expected:
        raise ValueError(f"Expected {expected} solution starts, detected {len(items)}")
    nums = [x.number for x in items]
    if all(n is None for n in nums):
        return items
    if all(n is not None for n in nums):
        nums2 = [int(n) for n in nums]
        valid = list(range(1, expected + 1))
        if expected == 75:
            valid_patterns = (valid, list(range(1, 26)) * 3)
        else:
            valid_patterns = (valid,)
        if nums2 in valid_patterns:
            return items
    raise ValueError("Solution numbering is mixed/ambiguous; refusing to guess")


def span(starts: list[Marker], i: int, last_page: int) -> tuple[int, int]:
    start = starts[i].page
    if i + 1 == len(starts):
        return start, last_page
    nxt = starts[i + 1].page
    # Full-page image policy: two records on one page both reference that
    # exact source page instead of using a risky crop.
    end = start if nxt == start else nxt - 1
    if end < start:
        raise ValueError(f"Invalid page span {start}..{end}")
    return start, end


def render_pages(doc: fitz.Document, pages: set[int], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = fitz.Matrix(2.0, 2.0)  # ~144 DPI on 72-pt pages
    for page_no in sorted(pages):
        pix = doc[page_no - 1].get_pixmap(matrix=matrix, alpha=False)
        if pix.width < 600 or pix.height < 800:
            raise ValueError(f"Rendered page too small: page {page_no} -> {pix.width}x{pix.height}")
        pix.save(str(out_dir / f"page-{page_no:04d}.jpg"), output="jpeg", jpg_quality=88)


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(pdf: Path, out_dir: Path, expected_count: int, max_pages: int) -> None:
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    if pdf.stat().st_size < 100_000:
        raise ValueError("Source PDF is unexpectedly small")

    doc = fitz.open(pdf)
    try:
        page_count = len(doc)
        if not 1 <= page_count <= max_pages:
            raise ValueError(f"PDF page count {page_count} outside 1..{max_pages}")

        texts = [(p.get_text("text") or "") for p in doc]
        source_sha = sha256_file(pdf)

        q_all = markers(texts, QUESTION_RE)
        s_all = markers(texts, SOLUTION_RE)
        first_solution_page = min((m.page for m in s_all), default=None)
        if first_solution_page is None:
            raise ValueError("No solution section marker found")

        q = question_starts(
            [m for m in q_all if m.page < first_solution_page],
            expected_count,
        )
        if any(m.page >= first_solution_page for m in q_all):
            raise ValueError("Question markers continue after the solution section begins")

        s = solution_starts(
            [m for m in s_all if m.page >= first_solution_page],
            expected_count,
        )

        rows = []
        referenced_pages = set()
        for i in range(expected_count):
            q_start, q_end = span(q, i, first_solution_page - 1)
            s_start, s_end = span(s, i, page_count)
            q_pages = list(range(q_start, q_end + 1))
            s_pages = list(range(s_start, s_end + 1))
            referenced_pages.update(q_pages)
            referenced_pages.update(s_pages)

            rows.append({
                "id": f"{source_sha[:16]}-q{i+1:03d}",
                "source_question_number": q[i].number,
                "question_text": None,
                "options": [{"key": c, "label": c} for c in "ABCD"],
                "answer": None,
                "solution_text": None,
                "question": {
                    "type": "SOURCE_PDF_PAGE_IMAGE",
                    "pages": q_pages,
                    "image_refs": [f"assets/page-{p:04d}.jpg" for p in q_pages],
                },
                "solution": {
                    "type": "SOURCE_PDF_PAGE_IMAGE",
                    "pages": s_pages,
                    "image_refs": [f"assets/page-{p:04d}.jpg" for p in s_pages],
                },
                "provenance": {
                    "source_pdf": pdf.name,
                    "source_pdf_sha256": source_sha,
                    "question_pages": [q_start, q_end],
                    "solution_pages": [s_start, s_end],
                    "content_mode": "source-rendered-images-only",
                },
                "status": "VALIDATED",
            })

        render_pages(doc, referenced_pages, out_dir / "assets")

        for row in rows:
            refs = row["question"]["image_refs"] + row["solution"]["image_refs"]
            for ref in refs:
                if not (out_dir / ref).is_file():
                    raise ValueError(f"Missing referenced asset: {ref}")
            if row["question_text"] is not None or row["solution_text"] is not None:
                raise ValueError("Text content must remain empty in image-first mode")
            if [x["key"] for x in row["options"]] != list("ABCD"):
                raise ValueError("Options must be exactly A/B/C/D")

        write_json(out_dir / "validated.json", rows)
        write_json(out_dir / "review.json", {
            "source_pdf": pdf.name,
            "source_pdf_sha256": source_sha,
            "page_count": page_count,
            "question_count": len(rows),
            "solution_count": len(s),
            "first_solution_page": first_solution_page,
            "samples": [rows[0], rows[-1]],
            "text_extraction_persisted": False,
        })
        write_json(out_dir / "source-intake.json", {
            "pdf": pdf.name,
            "sha256": source_sha,
            "size_bytes": pdf.stat().st_size,
            "page_count": page_count,
            "scope": "exactly-one-source-pdf",
        })
        write_json(out_dir / "IMPORT_READY.json", {
            "status": "VALIDATED",
            "record_count": len(rows),
            "asset_count": len(referenced_pages),
            "source_pdf_sha256": source_sha,
            "database_write": False,
            "cloudflare_write": False,
            "requires_reverification_before_any_import": True,
        })
    finally:
        doc.close()


def self_test() -> None:
    root = Path("_image_first_self_test")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    pdf = root / "synthetic.pdf"

    doc = fitz.open()
    for _subject in range(3):
        for q in range(1, 26):
            p = doc.new_page()
            p.insert_text((72, 90), f"Question {q}")
    for _subject in range(3):
        for _q in range(1, 26):
            p = doc.new_page()
            p.insert_text((72, 90), "Solution")
    doc.save(pdf)
    doc.close()

    build(pdf, root / "out", 75, 200)
    rows = json.loads((root / "out" / "validated.json").read_text(encoding="utf-8"))
    assert len(rows) == 75
    assert rows[0]["options"] == [{"key": c, "label": c} for c in "ABCD"]
    assert rows[0]["question_text"] is None
    assert rows[0]["solution_text"] is None
    shutil.rmtree(root)
    print("IMAGE-FIRST SELF-TEST PASSED")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--expected-count", type=int, default=75)
    p.add_argument("--max-pages", type=int, default=150)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()

    if a.self_test:
        self_test()
        return 0
    if a.pdf is None or a.output is None:
        p.error("--pdf and --output are required unless --self-test is used")
    if a.output.exists():
        shutil.rmtree(a.output)
    a.output.mkdir(parents=True)

    try:
        build(a.pdf, a.output, a.expected_count, a.max_pages)
    except Exception as exc:
        write_json(a.output / "validation-report.json", {
            "status": "QUARANTINED",
            "error": str(exc),
            "database_write": False,
            "cloudflare_write": False,
        })
        print(f"QUARANTINED: {exc}")
        return 2

    write_json(a.output / "validation-report.json", {
        "status": "VALIDATED",
        "record_count": a.expected_count,
        "options": ["A", "B", "C", "D"],
        "content_mode": "PDF_PAGE_IMAGES_ONLY",
        "question_text_stored": False,
        "solution_text_stored": False,
        "database_write": False,
        "cloudflare_write": False,
    })
    print("IMAGE-FIRST REAL PDF VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
