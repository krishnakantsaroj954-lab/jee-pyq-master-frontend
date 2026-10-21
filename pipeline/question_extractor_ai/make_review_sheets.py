#!/usr/bin/env python3
"""Create compact contact sheets and a reviewer summary from candidate crops."""
import argparse
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps


def make_sheet(entries, destination, columns, cell_width, image_height, label_height):
    if not entries:
        raise RuntimeError("No images found for " + destination.name)
    tile_height = image_height + label_height
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * tile_height), (246, 246, 246))
    draw = ImageDraw.Draw(sheet)
    for i, (image_path, label) in enumerate(entries):
        col, row = i % columns, i // columns
        left, top = col * cell_width, row * tile_height
        with Image.open(image_path) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (cell_width - 12, image_height - 12))
        sheet.paste(thumb, (left + (cell_width - thumb.width) // 2, top + (image_height - thumb.height) // 2))
        draw.rectangle((left, top, left + cell_width - 1, top + image_height - 1), outline=(170, 170, 170), width=1)
        draw.text((left + 6, top + image_height + 4), label[:38], fill=(20, 20, 20))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "JPEG", quality=62, optimize=True, progressive=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="question-extractor-output")
    parser.add_argument("--review-dir", default="question-extractor-output/review")
    args = parser.parse_args()
    root = Path(args.input_dir).resolve()
    review = Path(args.review_dir).resolve()
    source_manifest = root / "manifest.json"
    if not source_manifest.is_file():
        raise SystemExit("Missing extraction manifest: " + str(source_manifest))
    data = json.loads(source_manifest.read_text(encoding="utf-8"))

    pages, crops, compact_pages, quality_flags = [], [], [], []
    for page in data.get("pages", []):
        number = int(page["page"])
        overlay = root / "previews" / ("page_%03d_boxes.jpg" % number)
        if overlay.is_file():
            pages.append((overlay, "Page %02d | %d regions" % (number, int(page.get("count", 0)))))
        compact_crop_list = []
        page_size = page.get("pageSize") or {}
        page_width = int(page_size.get("width", 0) or 0)
        page_height = int(page_size.get("height", 0) or 0)
        for crop in page.get("crops", []):
            bbox = crop.get("bbox") or {}
            compact_crop_list.append({"indexOnPage": crop.get("indexOnPage"), "bbox": bbox})
            if page_width > 0 and page_height > 0:
                box_width = int(bbox.get("width", 0) or 0)
                box_height = int(bbox.get("height", 0) or 0)
                if box_height >= 0.85 * page_height and box_width >= 0.25 * page_width:
                    quality_flags.append("Page %02d candidate %02d spans nearly the full page height and a substantial column width; likely a page/column merge." % (number, int(crop.get("indexOnPage", 0))))
                elif box_width >= 0.90 * page_width and box_height >= 0.55 * page_height:
                    quality_flags.append("Page %02d candidate %02d covers most of the page; likely merged." % (number, int(crop.get("indexOnPage", 0))))
                elif box_height <= 0.012 * page_height:
                    quality_flags.append("Page %02d candidate %02d is extremely thin; likely a line/footer fragment." % (number, int(crop.get("indexOnPage", 0))))
            candidate = root / crop.get("path", "")
            if candidate.is_file():
                crops.append((candidate, "Page %02d | candidate %02d" % (number, int(crop["indexOnPage"]))))
        entry = {"page": number, "pageSize": page_size or None, "count": int(page.get("count", 0)), "crops": compact_crop_list}
        if page.get("error"):
            entry["error"] = page["error"]
        compact_pages.append(entry)

    if int(data.get("totalCrops", 0)) > 120:
        quality_flags.append("The detector returned %s regions, above the 120-region sanity limit for this 75-question source paper; likely over-segmented." % int(data.get("totalCrops", 0)))

    review.mkdir(parents=True, exist_ok=True)
    make_sheet(pages, review / "page_overview.jpg", 4, 300, 350, 28)
    make_sheet(crops, review / "candidate_crop_overview.jpg", 4, 240, 150, 25)
    compact = {
        "schemaVersion": "question-extractor-ai-review/v1",
        "createdAt": data.get("createdAt"),
        "sourcePdf": data.get("sourcePdf"),
        "extractor": data.get("extractor"),
        "parameters": data.get("parameters"),
        "warning": "Geometry-only candidates, not verified questions; no OCR, answers, solutions, subjects, chapters, or topics.",
        "totalPages": len(compact_pages),
        "totalCrops": int(data.get("totalCrops", 0)),
        "pagesWithErrors": int(data.get("pagesWithErrors", 0)),
        "qualityStatus": "REJECTED" if quality_flags else "REVIEW_REQUIRED",
        "qualityFlags": quality_flags,
        "pages": compact_pages,
        "contactSheets": ["page_overview.jpg", "candidate_crop_overview.jpg"],
    }
    (review / "manifest.json").write_text(json.dumps(compact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Experimental QuestionExtractorAI crop review", "",
        "- Source PDF: " + str(data.get("sourcePdf")),
        "- Pages processed: " + str(len(compact_pages)),
        "- Candidate regions detected: " + str(compact.get("totalCrops")),
        "- Pages with errors: " + str(compact.get("pagesWithErrors")),
        "- Suspect geometry regions: " + str(len(quality_flags)),
        "- QA status: " + str(compact.get("qualityStatus")),
        "- Automatic import: BLOCKED (geometry-only candidates are never import-ready).",
        "- Layout type: " + str((data.get("parameters") or {}).get("paperType")),
        "- Kernel: " + str((data.get("parameters") or {}).get("kernel")), "",
        "## Important interpretation", "",
        "These are geometry-based candidate regions, not verified questions. The upstream tool does not OCR text or extract answers, solutions, subjects, chapters, or topics. Do not import these candidates into the live website.", "",
        "## Contact sheets", "",
        "- page_overview.jpg: page overlays showing detected regions.",
        "- candidate_crop_overview.jpg: candidate regions labelled by source page and detector index.", "",
        "## Per-page counts", "",
        "| Page | Regions | Status |", "|---:|---:|---|",
    ]
    for page in data.get("pages", []):
        lines.append("| %s | %s | %s |" % (page.get("page"), page.get("count", 0), page.get("error", "processed")))
    if quality_flags:
        lines.extend(["", "## Geometry warnings", ""])
        lines.extend("- " + warning for warning in quality_flags)
    else:
        lines.extend(["", "No obvious page-sized or extremely thin regions were detected by this basic geometry check. Visual review is still mandatory."])
    lines.extend(["", "Full-resolution crop and diagnostic files are temporary CI output. Only compact review sheets and the compact manifest are saved to the test branch, avoiding Actions artifact-storage quota use.", ""])
    (review / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("Review bundle created.")
    print("Pages=%s candidates=%s page_errors=%s" % (compact["totalPages"], compact["totalCrops"], compact["pagesWithErrors"]))
    for path in sorted(review.iterdir()):
        print("%s bytes: %s" % (path.stat().st_size, path.name))


if __name__ == "__main__":
    main()
