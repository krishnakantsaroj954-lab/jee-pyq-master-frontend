#!/usr/bin/env python3
"""Verify the exact pinned 22 Jan 2026 Shift 1 PDF before any OCR extraction.

This check intentionally fails closed: matching filename or page count alone is not
proof that a PDF is the expected paper. The SHA-256 is taken from the already
reviewed bundle metadata; content verification is still required after extraction.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


CONFIG_PATH = Path("representative-config.json")
EXPECTED_PAGE_COUNT = 24


def write_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"BLOCKED: config file missing: {CONFIG_PATH}", file=sys.stderr)
        write_output({"verified": "false", "reason": "config_missing"})
        return 2

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    pdf_path = Path(config["source_pdf"])
    if not pdf_path.is_file():
        print(f"BLOCKED: expected source PDF is missing: {pdf_path}", file=sys.stderr)
        write_output({"verified": "false", "reason": "pdf_missing"})
        return 2

    expected_hash = str(config.get("expected_source_sha256", "")).lower()
    actual_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    try:
        import fitz
    except ImportError:
        print("BLOCKED: PyMuPDF is not installed; cannot inspect PDF.", file=sys.stderr)
        write_output({"verified": "false", "reason": "pymupdf_missing"})
        return 2

    with fitz.open(pdf_path) as document:
        page_count = len(document)
        scan_pages = sum(1 for page in document if not page.get_text("words"))
        image_pages = sum(1 for page in document if page.get_image_info(xrefs=True))

    expected_keys = (
        [f"Mathematics:{n}" for n in range(1, 26)]
        + [f"Physics:{n}" for n in range(26, 51)]
        + [f"Chemistry:{n}" for n in range(51, 76)]
    )
    expected_ranges = [
        {"start": 1, "end": 20, "type": "MCQ"},
        {"start": 21, "end": 25, "type": "NUMERICAL"},
        {"start": 26, "end": 45, "type": "MCQ"},
        {"start": 46, "end": 50, "type": "NUMERICAL"},
        {"start": 51, "end": 70, "type": "MCQ"},
        {"start": 71, "end": 75, "type": "NUMERICAL"},
    ]
    config_errors = []
    if config.get("release") != "2026-01-22-shift1":
        config_errors.append("release identity is not 2026-01-22-shift1")
    if config.get("exam") != "JEE-MAIN" or config.get("year") != 2026:
        config_errors.append("exam/year identity does not match JEE Main 2026")
    if "22 January 2026" not in config.get("session", "") or "Shift 1" not in config.get("session", ""):
        config_errors.append("session identity does not match 22 January 2026 Shift 1")
    if config.get("expected_question_count") != 75:
        config_errors.append("expected question count must be 75")
    if config.get("expected_question_numbers") != expected_keys:
        config_errors.append("question-number-to-subject mapping must be 1–25 Maths, 26–50 Physics, 51–75 Chemistry")
    if config.get("question_type_ranges") != expected_ranges:
        config_errors.append("MCQ/numerical source-number ranges do not match the paper configuration")
    if config.get("page_range") != [1, EXPECTED_PAGE_COUNT] or page_count != EXPECTED_PAGE_COUNT:
        config_errors.append(f"expected exactly {EXPECTED_PAGE_COUNT} configured/source pages; config={config.get('page_range')} PDF={page_count}")
    if actual_hash != expected_hash:
        config_errors.append("PDF SHA-256 differs from the pinned source hash in the existing Jan 22 bundle metadata")

    print("=== JEE Main · 22 January 2026 · Shift 1 · source gate ===")
    print(f"PDF: {pdf_path}")
    print(f"Actual SHA-256:   {actual_hash}")
    print(f"Expected SHA-256: {expected_hash}")
    print(f"PDF pages: {page_count}; pages with no selectable text: {scan_pages}; pages containing image placements: {image_pages}")
    print("Identity: " + ("PASS" if not config_errors else "BLOCKED"))
    for error in config_errors:
        print(f"- {error}")

    verified = not config_errors
    write_output({
        "verified": "true" if verified else "false",
        "source_sha256": actual_hash,
        "page_count": str(page_count),
        "scan_pages": str(scan_pages),
        "image_pages": str(image_pages),
        "reason": "pass" if verified else "source_identity_or_config_mismatch",
    })
    if not verified:
        print("No extraction was run. Do not override this gate by renaming the PDF or editing the expected hash.")
        return 2

    print("Source gate passed. This confirms file identity only, not the accuracy of extracted questions/answers/solutions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
