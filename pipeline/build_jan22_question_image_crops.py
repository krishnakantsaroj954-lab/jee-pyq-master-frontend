#!/usr/bin/env python3
"""Build source-grounded question-figure and solution crops for 22 Jan 2026 JEE Main Shift 1.

The crop boxes are paper-specific manual coordinates and always require visual review.
The script never changes transcribed question text, options, answers or solution text.
It never imports data into a website or production database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageOps

SOURCE_PDF = "BPD4dLYdvGj7xm8cDL66.pdf"
SOURCE_SHA = "7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3"
PREVIEW_WIDTH = 1024.0
PREVIEW_HEIGHT = 1450.0

# (source PDF page, x0/y0/x1/y1 in 1024x1450 page-preview coordinates, description)
QUESTION_FIGURES = {
    7: (3, (562,169,965,231), "Probability distribution table in the question"),
    28: (9, (630,350,957,540), "Six-point charge diagram"),
    29: (10, (172,410,400,573), "Sliding rod and conducting loop diagram"),
    31: (10, (620,790,856,950), "Meter bridge circuit diagram"),
    34: (11, (630,1005,875,1173), "Logic-gate and LED circuit"),
    35: (12, (184,580,365,697), "Square with four corner masses"),
    37: (12, (600,935,855,1048), "Rotating gas-filled cylindrical tube"),
    38: (13, (105,925,430,1060), "Thermal-conduction rod network"),
    # Expanded on 2026-10-21 after visual QA showed the table header/bottom border clipped.
    44: (15, (85,132,510,329), "Complete List-I/List-II dimensions table"),
    45: (15, (585,90,790,280), "Three coaxial coils with current directions"),
    46: (15, (635,1030,875,1210), "Two loudspeakers and recorder positions"),
    52: (18, (100,843,242,965), "HNO3 Lewis structure with numbered atoms"),
    57: (19, (574,895,939,1185), "Four candidate graphs"),
    60: (20, (550,140,950,1001), "Thermodynamic process matching table"),
    61: (21, (326,730,485,820), "Substituted benzene structure shown in Statement I"),
    63: (21, (550,620,968,1014), "Reagents/reaction-name matching table"),
    66: (22, (558,570,964,857), "Four organic compound structures"),
    67: (23, (110,340,510,480), "Four substrate structures for SN1 comparison"),
    75: (24, (555,685,800,770), "Standard Gibbs-energy data table"),
}

SOLUTION_BLOCKS = {
    18: (6, (525,35,965,510), "Printed solution block for Q18"),
    27: (9, (45,850,500,1235), "Printed solution block for Q27, including scattering diagram"),
    # Shortened to avoid the beginning of Q33 while preserving Q32's final answer line.
    32: (11, (525,35,965,460), "Printed solution block for Q32"),
    38: (13, (520,35,965,755), "Printed solution block for Q38"),
    # Extended to include the printed 'Correct Ans. (2)' line, before Q46 begins.
    45: (15, (520,55,965,620), "Printed solution block for Q45"),
    # Extended to include the complete final result '= 7 kJ', before Q61 begins.
    60: (21, (45,35,500,635), "Printed solution block for Q60"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crop(root: Path, page_no: int, box: tuple[int, int, int, int], dest: Path) -> dict:
    src = root / "images" / "pages" / f"page_{page_no:02d}.jpg"
    if not src.is_file():
        raise SystemExit(f"Missing original source-page image: {src}")
    with Image.open(src) as opened:
        im = opened.convert("RGB")
    sx, sy = im.width / PREVIEW_WIDTH, im.height / PREVIEW_HEIGHT
    x1, y1, x2, y2 = box
    pad = 4
    px1 = max(0, int((x1 - pad) * sx))
    py1 = max(0, int((y1 - pad) * sy))
    px2 = min(im.width, int((x2 + pad) * sx))
    py2 = min(im.height, int((y2 + pad) * sy))
    if px2 - px1 < 30 or py2 - py1 < 30:
        raise SystemExit(f"Implausibly small crop requested: {dest}")
    result = im.crop((px1, py1, px2, py2))
    dest.parent.mkdir(parents=True, exist_ok=True)
    result.save(dest, "JPEG", quality=95, optimize=True, progressive=True)
    return {
        "source_page": f"images/pages/page_{page_no:02d}.jpg",
        "source_bbox_preview": [round(px1 / sx, 2), round(py1 / sy, 2), round(px2 / sx, 2), round(py2 / sy, 2)],
        "native_bbox": [px1, py1, px2, py2],
        "width": result.width,
        "height": result.height,
        "bytes": dest.stat().st_size,
        "sha256": sha256(dest),
    }


def contact_sheet(entries: Iterable[tuple[Path, str]], destination: Path, *, columns: int, cell_width: int, image_height: int, label_height: int) -> None:
    entries = list(entries)
    if not entries:
        raise SystemExit(f"No images to put in contact sheet: {destination.name}")
    rows = math.ceil(len(entries) / columns)
    tile_height = image_height + label_height
    sheet = Image.new("RGB", (columns * cell_width, rows * tile_height), (248, 248, 248))
    draw = ImageDraw.Draw(sheet)
    for index, (image_path, label) in enumerate(entries):
        col, row = index % columns, index // columns
        left, top = col * cell_width, row * tile_height
        with Image.open(image_path) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (cell_width - 12, image_height - 12))
        sheet.paste(thumb, (left + (cell_width - thumb.width) // 2, top + (image_height - thumb.height) // 2))
        draw.rectangle((left, top, left + cell_width - 1, top + image_height - 1), outline=(160, 160, 160), width=1)
        draw.text((left + 6, top + image_height + 4), label[:44], fill=(10, 10, 10))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "JPEG", quality=88, optimize=True, progressive=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Directory containing images/pages and the 75-question JSON")
    parser.add_argument("--source-pdf", required=False, help="Optional exact original PDF; if omitted, verifies pinned dataset metadata and all source-page image hashes.")
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    source_pdf = Path(args.source_pdf).resolve() if args.source_pdf else None
    source_pdf_bytes_verified = False
    if source_pdf is not None:
        if not source_pdf.is_file() or sha256(source_pdf) != SOURCE_SHA:
            raise SystemExit("Source PDF missing or SHA-256 mismatch; refusing to alter image paths.")
        source_pdf_bytes_verified = True

    json_path = root / "jee_main_2026_01_22_shift1_FINAL_75Q.json"
    if not json_path.is_file():
        raise SystemExit(f"Missing dataset JSON: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if data.get("paper", {}).get("source_sha256") != SOURCE_SHA:
        raise SystemExit("Dataset source SHA-256 metadata mismatch; refusing to alter image paths.")
    prior_asset_manifest_path = root / "asset-manifest.json"
    prior_asset_manifest = json.loads(prior_asset_manifest_path.read_text(encoding="utf-8")) if prior_asset_manifest_path.is_file() else {}
    if not source_pdf_bytes_verified:
        if prior_asset_manifest.get("source_pdf_sha256") != SOURCE_SHA:
            raise SystemExit("Without PDF bytes, a matching pinned source SHA must exist in asset-manifest.json.")
        expected_page_assets = {a.get("path"): a.get("sha256") for a in prior_asset_manifest.get("assets", []) if str(a.get("path", "")).startswith("images/pages/")}
        expected_page_paths = {f"images/pages/page_{i:02d}.jpg" for i in range(1, 25)}
        if set(expected_page_assets) != expected_page_paths:
            raise SystemExit("Without PDF bytes, asset manifest must pin all 24 source-page image hashes.")
        for rel, digest in expected_page_assets.items():
            path = root / rel
            if not path.is_file() or sha256(path) != digest:
                raise SystemExit(f"Source page image hash mismatch: {rel}")
    questions = data.get("questions", [])
    if len(questions) != 75 or {q.get("question_number") for q in questions} != set(range(1, 76)):
        raise SystemExit("Expected exactly 75 unique question records numbered 1..75.")
    q39 = next(q for q in questions if q["question_number"] == 39)
    if q39.get("correct_answer") is not None or q39.get("correct_answer_status") != "dropped_in_source" or "Dropped" not in str(q39.get("source", {}).get("printed_answer_label", "")):
        raise SystemExit("Q39 no longer matches the printed Dropped state; refusing to alter image paths.")

    crop_manifest = {
        "schema_version": 2,
        "source_pdf": SOURCE_PDF,
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "verification_mode": ("actual source PDF bytes SHA-256 verified in this run" if source_pdf_bytes_verified else "pinned source metadata and all 24 source-page image hashes verified; actual PDF bytes not available to this invocation"),
        "coordinate_note": "Crop regions were estimated manually in 1024x1450 preview coordinates and scaled to the original page JPEGs. Contact sheets are generated for human visual inspection. QA status remains REVIEW_REQUIRED; crops are not claimed to be perfectly verified.",
        "question_figures": [],
        "solution_crops": [],
        "quality_status": "REVIEW_REQUIRED",
        "production_import": "NOT_PERFORMED",
    }
    question_paths = {39: "images/questions/q039_question.jpg"}
    solution_paths: dict[int, str] = {}
    for number, (page, box, description) in QUESTION_FIGURES.items():
        name = f"q{number:03d}_figure.jpg"
        relative = f"images/questions/{name}"
        meta = crop(root, page, box, root / relative)
        crop_manifest["question_figures"].append({"question_number": number, "path": relative, "description": description, **meta})
        question_paths[number] = relative
    for number, (page, box, description) in SOLUTION_BLOCKS.items():
        name = f"q{number:03d}_solution.jpg"
        relative = f"images/solutions/{name}"
        meta = crop(root, page, box, root / relative)
        crop_manifest["solution_crops"].append({"question_number": number, "path": relative, "description": description, **meta})
        solution_paths[number] = relative

    for question in questions:
        number = question["question_number"]
        question["question_image_path"] = question_paths.get(number)
        question["solution_image_path"] = solution_paths.get(number)
        if not question.get("source_page_image_path"):
            raise SystemExit(f"Question {number} is missing source_page_image_path.")
    data["image_path_convention"] = "Paths are relative to this dataset directory. question_image_path is null unless a question includes a relevant figure/table/graph; such paths target question-specific crops. Q39 remains in source order, is visibly marked Dropped in the source, and has no invented answer. solution_image_path is null unless a separate readable solution crop is needed. source_page_image_path always preserves the full-page source for provenance."
    data.setdefault("database_notes", {})["import_gate"] = "NOT PRODUCTION READY: verify OCR/transcription and every generated crop against the exact source PDF. The builder checks source SHA-256 and preserves Q39 Dropped. No Worker/D1 import or deployment is performed."
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    crop_manifest_path = root / "image-crop-manifest.json"
    crop_manifest_path.write_text(json.dumps(crop_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    question_entries = [(root / "images/questions" / f"q{n:03d}_figure.jpg", f"Q{n:02d} - {description}") for n, (_, _, description) in QUESTION_FIGURES.items()]
    question_entries.insert(0, (root / question_paths[39], "Q39 - DROPPED source question"))
    solution_entries = [(root / "images/solutions" / f"q{n:03d}_solution.jpg", f"Q{n:02d} printed solution") for n, (_, _, _) in SOLUTION_BLOCKS.items()]
    contact_sheet(question_entries, root / "question-crops-contact-sheet.jpg", columns=4, cell_width=280, image_height=200, label_height=34)
    contact_sheet(solution_entries, root / "solution-crops-contact-sheet.jpg", columns=3, cell_width=340, image_height=360, label_height=34)

    image_root = root / "images"
    watermarked_root = image_root / "watermarked"
    # Watermarked review derivatives mirror source assets under images/watermarked/.
    # Exclude them from the source-asset inventory so reruns do not double-count them.
    image_files = sorted(p for p in image_root.rglob("*.jpg") if watermarked_root not in p.parents)
    assets = []
    for path in image_files:
        rel = path.relative_to(root).as_posix()
        assets.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path), "mime_type": "image/jpeg"})
    full_question_crops = [a for a in assets if a["path"].startswith("images/questions/q") and a["path"].endswith("_full_question.jpg")]
    if len(full_question_crops) not in (0, 75):
        raise SystemExit(f"Expected either zero or 75 full-question crops, found {len(full_question_crops)}.")
    expected_asset_count = 50 + len(full_question_crops)
    if len(assets) != expected_asset_count:
        raise SystemExit(f"Expected {expected_asset_count} assets (50 base + {len(full_question_crops)} full-question crops), found {len(assets)}.")

    asset_manifest = {
        "manifest_version": "1.2.0",
        "paper_id": "jee-main-2026-01-22-s1",
        "dataset_json": json_path.name,
        "dataset_sha256": sha256(json_path),
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "full_question_crop_manifest": "full-question-crop-manifest.json" if len(full_question_crops) == 75 and (root / "full-question-crop-manifest.json").is_file() else None,
        "asset_count": len(assets),
        "assets_total_bytes": sum(asset["bytes"] for asset in assets),
        "assets": assets,
        "crop_manifest": crop_manifest_path.name,
        "review_contact_sheets": ["question-crops-contact-sheet.jpg", "solution-crops-contact-sheet.jpg"],
        "status": "QUESTION_SPECIFIC_CROPS_GENERATED_REVIEW_REQUIRED",
        "production_import": "NOT_PERFORMED",
    }
    (root / "asset-manifest.json").write_text(json.dumps(asset_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    available = {path.relative_to(root).as_posix() for path in (root / "images").rglob("*.jpg")}
    missing = []
    for question in questions:
        for key in ("question_image_path", "solution_image_path", "source_page_image_path"):
            if question.get(key) and question[key] not in available:
                missing.append((question["question_number"], key, question[key]))
    if missing:
        raise SystemExit("Missing image references: " + repr(missing))
    if q39.get("question_image_path") != "images/questions/q039_question.jpg" or q39.get("correct_answer") is not None:
        raise SystemExit("Q39 Dropped/source image contract failed.")

    readme = f"""# JEE Main 2026 — 22 January Shift 1 (Quarantined Dataset)

## Build result
- Pinned source PDF SHA-256 metadata: `{SOURCE_SHA}`.
- Actual PDF bytes SHA-256 verified in this run: `{source_pdf_bytes_verified}`.
- 75 question records kept in source order (Q1–Q75); Q39 remains visibly marked Dropped and has no invented answer.
- 24 original full-page source images retained under `images/pages/`.
- 19 figure/table crops and the existing Q39 question crop under `images/questions/`.
- Six printed-solution crops under `images/solutions/`.
- `question_image_path` and `solution_image_path` now point only to specific relevant crops or null; `source_page_image_path` keeps the original full page.
- All {len(assets)} original (non-watermarked) JPEG image assets are listed with SHA-256 values in `asset-manifest.json`; watermarked derivatives are tracked separately.
- Review contact sheets: `question-crops-contact-sheet.jpg` and `solution-crops-contact-sheet.jpg`.

## Mandatory review gate
The crop coordinates were estimated from page previews. Inspect both contact sheets and every individual crop for cut-off labels, stray text, and correct association. OCR text, options, answers, solutions, chapter labels and topic labels still require independent source review. This export remains `REVIEW_REQUIRED` and must stay under `data/quarantine/` until human review is complete.

No Cloudflare Worker/D1 import, production database change, or website deployment was performed.
"""
    (root / "README.txt").write_text(readme, encoding="utf-8")
    (root / "README.md").write_text(readme, encoding="utf-8")

    answer_count = sum(1 for q in questions if q["question_number"] != 39 and q.get("correct_answer"))
    report = {
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "verification_mode": ("actual PDF bytes hash verified" if source_pdf_bytes_verified else "dataset source SHA metadata and 24 page-image hashes verified; PDF bytes not rechecked in this run"),
        "question_records": len(questions),
        "questions_with_printed_answers": answer_count,
        "question_figure_crops": len(QUESTION_FIGURES),
        "solution_crops": len(SOLUTION_BLOCKS),
        "image_assets": len(assets),
        "image_references": "PASSED",
        "q39_status": q39.get("correct_answer_status"),
        "q39_correct_answer": q39.get("correct_answer"),
        "review_status": "REVIEW_REQUIRED",
        "production_import": "NOT_PERFORMED",
        "contact_sheets": ["question-crops-contact-sheet.jpg", "solution-crops-contact-sheet.jpg"],
    }
    (root / "crop-build-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())