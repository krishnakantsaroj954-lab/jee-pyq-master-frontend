#!/usr/bin/env python3
"""Verify the pinned Jan 22 source-page bundle and its generated OCR derivative.

The repository root PDF is a different paper (Jan 28) and is intentionally not used.
This gate confirms the existing 24 source-page JPEGs match their checksums in the
Jan 22 asset manifest and that the OCR derivative was built from those exact pages.
It does NOT claim that the derivative PDF is byte-identical to the original source PDF.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path("representative-config.json")
MANIFEST_PATH = Path("data/quarantine/2026-01-22-shift1/asset-manifest.json")
REPORT_PATH = Path("pipeline-output/source/22jan-source-page-verification.json")
EXPECTED_ORIGINAL_PDF = "BPD4dLYdvGj7xm8cDL66.pdf"
EXPECTED_ORIGINAL_SHA256 = "7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3"
EXPECTED_PAGE_COUNT = 24


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main() -> int:
    errors = []
    if not CONFIG_PATH.is_file():
        errors.append(f"config missing: {CONFIG_PATH}")
        config = {}
    else:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    if not MANIFEST_PATH.is_file():
        errors.append(f"Jan 22 asset manifest missing: {MANIFEST_PATH}")
        manifest = {}
    else:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    expected_hash = str(config.get("expected_source_sha256", "")).lower()
    manifest_hash = str(manifest.get("source_pdf_sha256", "")).lower()
    if config.get("release") != "2026-01-22-shift1":
        errors.append("release identity is not 2026-01-22-shift1")
    if config.get("exam") != "JEE-MAIN" or config.get("year") != 2026:
        errors.append("exam/year identity does not match JEE Main 2026")
    if "22 January 2026" not in config.get("session", "") or "Shift 1" not in config.get("session", ""):
        errors.append("session identity does not match 22 January 2026 Shift 1")
    if config.get("expected_question_count") != 75:
        errors.append("expected question count must be 75")

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
    if config.get("expected_question_numbers") != expected_keys:
        errors.append("question-number mapping must be Mathematics 1–25, Physics 26–50, Chemistry 51–75")
    if config.get("question_type_ranges") != expected_ranges:
        errors.append("MCQ/numerical source-number bands do not match the paper")
    if manifest.get("paper_id") != "jee-main-2026-01-22-s1":
        errors.append("asset manifest paper_id is not the pinned Jan 22 Shift 1")
    if manifest.get("asset_count") != 50:
        errors.append("asset manifest asset_count is not 50")
    if expected_hash != EXPECTED_ORIGINAL_SHA256 or manifest_hash != EXPECTED_ORIGINAL_SHA256:
        errors.append("config and pinned bundle manifest must both match the original Jan 22 PDF SHA-256")

    page_entries = {
        item.get("path"): item for item in manifest.get("assets", [])
        if isinstance(item, dict)
    }
    if len([p for p in page_entries if p.startswith("images/pages/page_") and p.endswith(".jpg")]) != EXPECTED_PAGE_COUNT:
        errors.append("asset manifest does not contain exactly 24 numbered source-page JPEGs")
    source_dir = Path("data/quarantine/2026-01-22-shift1")
    verified_pages = 0
    for page_no in range(1, EXPECTED_PAGE_COUNT + 1):
        rel = f"images/pages/page_{page_no:02d}.jpg"
        entry = page_entries.get(rel)
        path = source_dir / rel
        if entry is None or not path.is_file():
            errors.append(f"source page missing: {rel}")
            continue
        if path.stat().st_size != entry.get("bytes") or sha256(path) != entry.get("sha256"):
            errors.append(f"source page SHA-256/size mismatch: {rel}")
        else:
            verified_pages += 1
    if verified_pages != EXPECTED_PAGE_COUNT:
        errors.append(f"only {verified_pages}/{EXPECTED_PAGE_COUNT} source-page JPEGs verified")

    if not REPORT_PATH.is_file():
        errors.append(f"generated-page verification report missing: {REPORT_PATH}; run scripts/prepare_jan22_source_pdf.py first")
        prepared = {}
    else:
        prepared = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    pdf_path = Path(config.get("source_pdf", ""))
    if not pdf_path.is_file():
        errors.append(f"verified OCR derivative PDF is missing: {pdf_path}")
        actual_derivative_sha = ""
        page_count = 0
    else:
        actual_derivative_sha = sha256(pdf_path)
        try:
            import fitz
            with fitz.open(pdf_path) as document:
                page_count = len(document)
        except Exception as error:
            errors.append(f"cannot read generated OCR derivative PDF: {error}")
            page_count = 0
        if page_count != EXPECTED_PAGE_COUNT:
            errors.append(f"generated OCR derivative has {page_count} pages; expected {EXPECTED_PAGE_COUNT}")
    if prepared.get("status") != "VERIFIED_PAGE_IMAGES":
        errors.append("source-page preparation report is not verified")
    if prepared.get("original_source_pdf_sha256_from_manifest") != EXPECTED_ORIGINAL_SHA256:
        errors.append("preparation report is not tied to the pinned original source PDF SHA-256")
    if prepared.get("ocr_derivative_pdf") != str(pdf_path):
        errors.append("preparation report derivative path does not match representative-config.json")
    if prepared.get("ocr_derivative_pdf_sha256") != actual_derivative_sha:
        errors.append("generated OCR derivative hash differs from preparation report")

    print("=== JEE Main · 22 January 2026 · Shift 1 · source gate ===")
    print(f"Original PDF recorded in bundle: {EXPECTED_ORIGINAL_PDF}")
    print(f"Original PDF SHA-256 (bundle metadata): {manifest_hash}")
    print(f"Verified source-page JPEGs: {verified_pages}/{EXPECTED_PAGE_COUNT}")
    print(f"OCR derivative PDF: {pdf_path}")
    print(f"OCR derivative SHA-256: {actual_derivative_sha or 'unavailable'}")
    print(f"OCR derivative pages: {page_count}")
    print("Identity: " + ("PASS" if not errors else "BLOCKED"))
    for error in errors:
        print(f"- {error}")

    verified = not errors
    write_output({
        "verified": "true" if verified else "false",
        "source_sha256": manifest_hash,
        "derived_pdf_sha256": actual_derivative_sha,
        "page_count": str(page_count),
        "verified_source_pages": str(verified_pages),
        "reason": "pass" if verified else "source_page_or_config_mismatch",
    })
    if not verified:
        print("No OCR extraction should run. Do not change pinned hashes to force a pass.")
        return 2

    print("Source gate passed for the checksum-verified page-image derivative. This does not certify extracted text/answers/solutions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
