#!/usr/bin/env python3
"""Verify the pinned Jan 22 page-image bundle and rebuild a scan PDF for OCR.

The original PDF is deliberately NOT substituted with the different Jan 28 PDF at
repository root. The 24 source-page JPEGs are individually SHA-256 checked against
the existing bundle manifest that records the original PDF SHA-256. The output is
a derivative OCR input, not a byte-identical copy of the original PDF.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

BUNDLE_DIR = Path("data/quarantine/2026-01-22-shift1")
MANIFEST_PATH = BUNDLE_DIR / "asset-manifest.json"
EXPECTED_ORIGINAL_PDF = "BPD4dLYdvGj7xm8cDL66.pdf"
EXPECTED_ORIGINAL_SHA256 = "7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3"
EXPECTED_PAPER_ID = "jee-main-2026-01-22-s1"
EXPECTED_PAGE_COUNT = 24
OUTPUT_PATH = Path("pipeline-output/source/22jan-source-pages-reconstructed.pdf")
REPORT_PATH = Path("pipeline-output/source/22jan-source-page-verification.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not MANIFEST_PATH.is_file():
        raise SystemExit(f"BLOCKED: required source-page manifest is missing: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("paper_id") != EXPECTED_PAPER_ID:
        raise SystemExit(f"BLOCKED: wrong paper_id in {MANIFEST_PATH}")
    if manifest.get("source_pdf_sha256") != EXPECTED_ORIGINAL_SHA256:
        raise SystemExit("BLOCKED: bundle manifest does not contain the pinned original Jan 22 PDF SHA-256.")
    if manifest.get("asset_count") != 50:
        raise SystemExit("BLOCKED: unexpected asset count in the pinned Jan 22 bundle manifest.")

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise SystemExit("BLOCKED: asset manifest has no assets list.")
    indexed = {item.get("path"): item for item in assets if isinstance(item, dict)}
    pages = []
    results = []
    for page_no in range(1, EXPECTED_PAGE_COUNT + 1):
        relative = f"images/pages/page_{page_no:02d}.jpg"
        entry = indexed.get(relative)
        path = BUNDLE_DIR / relative
        if entry is None or not path.is_file():
            raise SystemExit(f"BLOCKED: expected source page is missing from manifest or disk: {relative}")
        actual_size = path.stat().st_size
        actual_sha = sha256(path)
        if actual_size != entry.get("bytes") or actual_sha != entry.get("sha256"):
            raise SystemExit(f"BLOCKED: source-page hash/size mismatch: {relative}")
        pages.append(path)
        results.append({
            "page": page_no,
            "path": relative,
            "bytes": actual_size,
            "sha256": actual_sha,
            "status": "VERIFIED",
        })

    if len([p for p in indexed if p.startswith("images/pages/page_") and p.endswith(".jpg")]) != EXPECTED_PAGE_COUNT:
        raise SystemExit("BLOCKED: manifest does not contain exactly 24 numbered source-page JPEGs.")

    try:
        import fitz
    except ImportError as error:
        raise SystemExit("BLOCKED: PyMuPDF is required to build the OCR input PDF.") from error

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for image_path in pages:
            pix = fitz.Pixmap(str(image_path))
            # Preserve the portrait page aspect ratio and image pixels. OCR uses
            # these verified page images, not the mismatched root PDF.
            width = 595.276
            height = width * pix.height / pix.width
            page = doc.new_page(width=width, height=height)
            page.insert_image(page.rect, filename=str(image_path))
        doc.set_metadata({
            "title": "JEE Main 2026 - 22 January Shift 1 - verified page-image OCR derivative",
            "author": "JEE PYQ Master source-grounded pipeline",
            "subject": f"Derivative OCR input; source PDF SHA-256 {EXPECTED_ORIGINAL_SHA256}",
            "keywords": "JEE Main 2026, 22 January, Shift 1, OCR derivative",
            "creator": "prepare_jan22_source_pdf.py",
            "producer": "PyMuPDF",
            "creationDate": "",
            "modDate": "",
        })
        with tempfile.NamedTemporaryFile(
            prefix=".jan22-source-", suffix=".pdf", dir=OUTPUT_PATH.parent, delete=False
        ) as handle:
            temp_name = handle.name
        try:
            doc.save(temp_name, garbage=4, deflate=True)
        finally:
            doc.close()
        os.replace(temp_name, OUTPUT_PATH)
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        raise

    with fitz.open(OUTPUT_PATH) as generated:
        generated_page_count = len(generated)
    if generated_page_count != EXPECTED_PAGE_COUNT:
        OUTPUT_PATH.unlink(missing_ok=True)
        raise SystemExit(f"BLOCKED: generated OCR PDF has {generated_page_count} pages, expected {EXPECTED_PAGE_COUNT}.")

    report = {
        "status": "VERIFIED_PAGE_IMAGES",
        "original_source_pdf": EXPECTED_ORIGINAL_PDF,
        "original_source_pdf_sha256_from_manifest": EXPECTED_ORIGINAL_SHA256,
        "paper_id": EXPECTED_PAPER_ID,
        "page_count": EXPECTED_PAGE_COUNT,
        "page_assets_verified": len(results),
        "page_assets": results,
        "ocr_derivative_pdf": str(OUTPUT_PATH),
        "ocr_derivative_pdf_sha256": sha256(OUTPUT_PATH),
        "important_note": "The output PDF is reconstructed from SHA-256-verified source-page JPEGs; it is not byte-identical to the original PDF. It must not be described as the original PDF.",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=== Jan 22 source-page verification ===")
    print(f"Original PDF identity from pinned bundle manifest: {EXPECTED_ORIGINAL_PDF}")
    print(f"Original PDF SHA-256: {EXPECTED_ORIGINAL_SHA256}")
    print(f"Verified source-page JPEGs: {len(results)}/{EXPECTED_PAGE_COUNT}")
    print(f"OCR derivative PDF: {OUTPUT_PATH}")
    print(f"OCR derivative SHA-256: {report['ocr_derivative_pdf_sha256']}")
    print("Status: PASS — page images matched their pinned SHA-256 manifest.")
    print("Boundary: derivative PDF is not byte-identical to the original PDF; all OCR output still needs question-by-question review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
