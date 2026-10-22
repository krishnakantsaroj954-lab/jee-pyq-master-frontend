#!/usr/bin/env python3
"""Experimental adapter for TaroAndMulan/QuestionExtractorAI.

The upstream project detects bounding boxes, but its PDF entrypoint currently
saves page overlays rather than individual crops. This adapter saves both.
It does not OCR question text or identify answers/solutions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="PDF path inside the checked-out repository")
    parser.add_argument("--extractor-dir", required=True, help="Path to a checked-out QuestionExtractorAI repository")
    parser.add_argument("--output-dir", default="question-extractor-output")
    parser.add_argument("--type", type=int, choices=(1, 2, 3), default=1, dest="paper_type")
    parser.add_argument("--kernel", type=int, nargs=2, default=(15, 5), metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--top", type=int, default=0, help="Ignore this percentage at the top of each page")
    parser.add_argument("--bottom", type=int, default=0, help="Ignore this percentage at the bottom of each page")
    parser.add_argument("--dpi", type=int, default=160, help="PDF rasterization DPI (default: 160)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path.cwd().resolve()
    pdf_path = Path(args.pdf).resolve()
    extractor_dir = Path(args.extractor_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not pdf_path.is_file():
        print(f"ERROR: PDF does not exist: {pdf_path}", file=sys.stderr)
        return 2
    if not pdf_path.is_relative_to(workspace):
        print("ERROR: For safety, --pdf must point to a file inside the checked-out repository.", file=sys.stderr)
        return 2
    if not extractor_dir.is_dir():
        print(f"ERROR: QuestionExtractorAI checkout was not found: {extractor_dir}", file=sys.stderr)
        return 2
    if args.dpi < 72 or args.dpi > 300:
        print("ERROR: --dpi must be between 72 and 300.", file=sys.stderr)
        return 2
    if not 0 <= args.top < 100 or not 0 <= args.bottom < 100 or args.top + args.bottom >= 100:
        print("ERROR: --top and --bottom must be percentages that leave some page content.", file=sys.stderr)
        return 2

    # Import the upstream code only after adding its checkout to sys.path.
    sys.path.insert(0, str(extractor_dir))
    try:
        import cv2
        import numpy as np
        from PIL import Image
        from pdf2image import convert_from_path
        from tools.helper import boundingBox
    except Exception as exc:
        print(f"ERROR: Required extraction dependencies/imports failed: {exc}", file=sys.stderr)
        return 2

    # Upstream mergeRelatedBoundingBoxes calls max() on an empty list. Guard
    # that edge case so a sparse page can still produce a manifest and preview.
    original_merge = boundingBox.mergeRelatedBoundingBoxes

    def safe_merge_related(boxes, page_width, offset):
        if not boxes:
            return []
        return original_merge(boxes, page_width, offset)

    boundingBox.mergeRelatedBoundingBoxes = safe_merge_related

    try:
        from tools.helper import analyze
    except Exception as exc:
        print(f"ERROR: Could not import upstream analyzer: {exc}", file=sys.stderr)
        return 2

    crop_dir = output_dir / "crops"
    preview_dir = output_dir / "previews"
    diagnostic_dir = output_dir / "diagnostics"
    crop_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_dir.mkdir(parents=True, exist_ok=True)

    print(f"PDF: {pdf_path.relative_to(workspace)}")
    print(f"Paper type: {args.paper_type}; kernel: {args.kernel}; DPI: {args.dpi}")
    try:
        pages = convert_from_path(str(pdf_path), dpi=args.dpi)
    except Exception as exc:
        print(f"ERROR: PDF could not be rasterized. Check Poppler/PDF integrity: {exc}", file=sys.stderr)
        return 2

    manifest = {
        "schemaVersion": "question-extractor-ai-crops/v1",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "sourcePdf": str(pdf_path.relative_to(workspace)),
        "extractor": {
            "repository": "https://github.com/TaroAndMulan/QuestionExtractorAI",
            "commit": "6206db58972bb4a06cf7d8e1294a89cd6c2fd729",
        },
        "parameters": {
            "paperType": args.paper_type,
            "kernel": list(args.kernel),
            "topPercent": args.top,
            "bottomPercent": args.bottom,
            "dpi": args.dpi,
        },
        "warning": "Experimental geometry-only crops. No OCR, correct answers, solutions, or chapter labels are extracted. Review every crop before use.",
        "pages": [],
        "totalCrops": 0,
    }

    total_crops = 0
    page_errors = 0
    for page_number, pil_page in enumerate(pages, start=1):
        page_stem = f"page_{page_number:03d}"
        page_record = {"page": page_number, "crops": [], "count": 0}
        page_rgb = np.asarray(pil_page.convert("RGB"))
        height, width = page_rgb.shape[:2]
        min_area = 0.001 * height * width
        page_bgr = cv2.cvtColor(page_rgb, cv2.COLOR_RGB2BGR)
        page_record["pageSize"] = {"width": int(width), "height": int(height)}

        try:
            original, threshold, dilated, overlay, boxes = analyze.analyzeImage(
                page_bgr.copy(),
                min_area,
                args.paper_type,
                tuple(args.kernel),
                args.top,
                args.bottom,
            )

            Image.fromarray(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)).save(preview_dir / f"{page_stem}_boxes.jpg", quality=90)
            Image.fromarray(threshold).save(diagnostic_dir / f"{page_stem}_threshold.png")
            Image.fromarray(dilated).save(diagnostic_dir / f"{page_stem}_dilated.png")

            original_height, original_width = original.shape[:2]
            for question_index, box in enumerate(boxes, start=1):
                x, y, box_width, box_height = [int(value) for value in box]
                x0 = max(0, x)
                y0 = max(0, y)
                x1 = min(original_width, x + box_width)
                y1 = min(original_height, y + box_height)
                if x1 <= x0 or y1 <= y0:
                    continue

                crop = original[y0:y1, x0:x1]
                crop_name = f"{page_stem}_q_{question_index:03d}.jpg"
                crop_path = crop_dir / crop_name
                Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).save(crop_path, quality=95)
                page_record["crops"].append({
                    "indexOnPage": question_index,
                    "path": str(crop_path.relative_to(output_dir)),
                    "bbox": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
                })

            page_record["count"] = len(page_record["crops"])
            total_crops += page_record["count"]
            print(f"Page {page_number}/{len(pages)}: {page_record['count']} candidate crop(s)")
        except Exception as exc:
            page_errors += 1
            page_record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"WARNING: page {page_number} failed: {page_record['error']}", file=sys.stderr)

        manifest["pages"].append(page_record)

    manifest["totalCrops"] = total_crops
    manifest["pagesWithErrors"] = page_errors
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Finished: {total_crops} candidate crops from {len(pages)} page(s).")
    print(f"Manifest: {manifest_path}")
    if total_crops == 0:
        print("No candidates were detected. Adjust layout type/kernel or use a different extraction method.", file=sys.stderr)
        return 2
    if page_errors:
        print(f"Completed with {page_errors} page error(s); inspect manifest.json.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
