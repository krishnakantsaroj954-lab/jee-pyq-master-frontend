#!/usr/bin/env python3
"""Build per-question source-PDF image crops for 22 Jan 2026 JEE Main Shift 1.

Uses OCR word/line geometry on the original bundled source-page scans to locate
printed question headers and the corresponding printed Ans. boundary. Preserves
all visible question material, including options/figures, and stops before the
printed answer except for the source-dropped Q39 label. Outputs remain quarantined
and REVIEW_REQUIRED; this script never imports into D1 or a production site.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

SOURCE_PDF = "BPD4dLYdvGj7xm8cDL66.pdf"
SOURCE_SHA = "7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3"
EXPECTED_PAPER_ID = "jee-main-2026-01-22-s1"
EXPECTED_DATE = "2026-01-22"
EXPECTED_SHIFT = 1
PAGE_COUNT = 24
QUESTION_COUNT = 75
# Manually verified source-page positions used only when OCR completely misses
# the printed question number. The source stem text and Ans. boundary are still
# verified by the sequence/marker gate below.
MANUAL_HEADER_ANCHORS = {
    1: {"page": 2, "side": "L", "y": 445.8, "review_reason": "OCR misses printed question number; stem begins 'Let AB = ...'"},
    7: {"page": 3, "side": "R", "y": 184.7, "review_reason": "OCR misses printed question number; stem begins 'If a random variable...'"},
    51: {"page": 18, "side": "L", "y": 445.8, "review_reason": "Hosted Tesseract 5.3 fails to join the printed Q51 number to its stem; source header visually checked on page 18 left column."},
}

# Leading OCR debris is tolerated only before an exact expected number and only
# in the narrow printed-number gutter. All question starts must form 1..75.
HEADER_PREFIX = re.compile(r"^[\s|!:/\\IlHhi\d\[\]{}()'\"‘’`]*$")
ANSWER_RE = re.compile(r"^\s*['\"‘’`|!:/\\IlHhi\d\[\]{}]*\s*Ans\.?\b", re.I)
CORRECT_ANSWER_RE = re.compile(r"^\s*Correct\s+Ans\b", re.I)
SOLUTION_RE = re.compile(r"^\s*['\"‘’`|!:/\\IlHhi\d\[\]{}]*\s*Sol\.?\b", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordered_key(row: dict[str, Any]) -> tuple:
    return (int(row["page"]), 0 if row["side"] == "L" else 1, float(row["y0"]), float(row["x0"]))


def is_answer_row(row: dict[str, Any]) -> bool:
    text = str(row.get("text") or "")
    if CORRECT_ANSWER_RE.match(text):
        return False
    return bool(ANSWER_RE.match(text))


def is_solution_row(row: dict[str, Any]) -> bool:
    return bool(SOLUTION_RE.match(str(row.get("text") or "")))


def header_candidate(row: dict[str, Any], number: int, page_width: int) -> bool:
    text = str(row.get("text") or "")[:40]
    if is_answer_row(row) or is_solution_row(row) or CORRECT_ANSWER_RE.match(text):
        return False
    midpoint = page_width / 2.0
    x0 = float(row["x0"])
    gutter = x0 <= page_width * 0.105 or midpoint - page_width * 0.008 <= x0 <= midpoint + page_width * 0.105
    if not gutter:
        return False
    marker = re.compile(r"(?<!\d)(" + str(number) + r")\s*[.,:)]\s+")
    for match in marker.finditer(text):
        prefix = text[:match.start()]
        if len(prefix) <= 7 and HEADER_PREFIX.fullmatch(prefix):
            return True
    return False


def load_ocr_rows(root: Path, cache_dir: Path | None, pages: dict[int, Image.Image]) -> list[dict[str, Any]]:
    if cache_dir is not None:
        manifest_path = cache_dir / "ocr-cache-manifest.json"
        if not manifest_path.is_file():
            raise SystemExit(f"Pinned OCR cache manifest missing: {manifest_path}")
        try:
            cache_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"OCR cache manifest is unreadable: {exc}") from exc
        if cache_manifest.get("paper_id") != EXPECTED_PAPER_ID or cache_manifest.get("source_pdf_sha256") != SOURCE_SHA:
            raise SystemExit("OCR cache is not bound to the expected paper/source PDF SHA-256")
        if cache_manifest.get("pages_covered") != list(range(2, PAGE_COUNT + 1)):
            raise SystemExit("OCR cache manifest must cover every question page 2..24 exactly")
        expected_page_hashes = cache_manifest.get("source_page_image_hashes")
        if not isinstance(expected_page_hashes, dict) or set(expected_page_hashes) != {f"images/pages/page_{i:02d}.jpg" for i in range(1, PAGE_COUNT + 1)}:
            raise SystemExit("OCR cache manifest must pin hashes for all 24 source-page images")
        for rel, digest in expected_page_hashes.items():
            source_page = root / rel
            if not source_page.is_file() or sha256(source_page) != digest:
                raise SystemExit(f"OCR cache source-page image hash mismatch: {rel}")

        listed_files = cache_manifest.get("files")
        if not isinstance(listed_files, list) or not listed_files:
            raise SystemExit("OCR cache manifest has no file checksum list")
        listed_by_name = {entry.get("path"): entry for entry in listed_files if isinstance(entry, dict)}
        files = sorted(cache_dir.glob("ocr_lines_*.json"))
        if {path.name for path in files} != set(listed_by_name):
            raise SystemExit("OCR cache file set differs from its pinned manifest")
        rows: list[dict[str, Any]] = []
        for path in files:
            entry = listed_by_name[path.name]
            if sha256(path) != entry.get("sha256"):
                raise SystemExit(f"OCR cache checksum mismatch: {path.name}")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise SystemExit(f"Unreadable OCR cache {path}: {exc}") from exc
            if not isinstance(value, list) or len(value) != int(entry.get("row_count", -1)):
                raise SystemExit(f"OCR cache row count mismatch: {path.name}")
            represented_in_file = sorted({int(row.get("page", 0)) for row in value})
            if represented_in_file != entry.get("pages"):
                raise SystemExit(f"OCR cache page list mismatch: {path.name}")
            rows.extend(value)
        represented = {int(row.get("page", 0)) for row in rows}
        needed = set(range(2, PAGE_COUNT + 1))
        if represented != needed:
            raise SystemExit(f"OCR cache source page coverage mismatch: missing={sorted(needed - represented)}, extra={sorted(represented - needed)}")
        return sorted(rows, key=ordered_key)

    try:
        import pytesseract
        from pytesseract import Output
    except Exception as exc:
        raise SystemExit("pytesseract is required when --ocr-cache-dir is not supplied") from exc

    rows = []
    for page_no in range(2, PAGE_COUNT + 1):
        page_path = root / "images" / "pages" / f"page_{page_no:02d}.jpg"
        if not page_path.is_file():
            raise SystemExit(f"Missing source page image: {page_path}")
        with Image.open(page_path) as im:
            page = im.convert("RGB")
        width, height = page.size
        midpoint = width // 2
        for side, xoff, region in (
            ("L", 0, page.crop((0, 0, midpoint, height))),
            ("R", midpoint, page.crop((midpoint, 0, width, height))),
        ):
            scale = 0.72
            resized = region.resize((round(region.width * scale), round(region.height * scale)))
            data = pytesseract.image_to_data(resized, config="--psm 6", output_type=Output.DICT)
            grouped: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
            boxes: dict[tuple, list[tuple[float, float, float, float]]] = defaultdict(list)
            for i, token in enumerate(data.get("text", [])):
                token = str(token or "").strip()
                if not token:
                    continue
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                left = float(data["left"][i]) / scale + xoff
                top = float(data["top"][i]) / scale
                right = (float(data["left"][i]) + float(data["width"][i])) / scale + xoff
                bottom = (float(data["top"][i]) + float(data["height"][i])) / scale
                boxes[key].append((left, top, right, bottom))
                grouped[key].append((left, token))
            for key, entries in grouped.items():
                coords = boxes[key]
                rows.append({
                    "page": page_no,
                    "side": side,
                    "x0": min(box[0] for box in coords),
                    "y0": min(box[1] for box in coords),
                    "x1": max(box[2] for box in coords),
                    "y1": max(box[3] for box in coords),
                    "text": " ".join(text for _, text in sorted(entries)),
                })
        print(f"OCR page {page_no}/{PAGE_COUNT}: {sum(1 for row in rows if row['page'] == page_no)} lines")
    return sorted(rows, key=ordered_key)




def meaningful_source_row(row: dict[str, Any], page_width: int, page_height: int) -> bool:
    """Ignore OCR artefacts from the decorative page border, not printed question text."""
    text = str(row.get("text") or "").strip()
    if not text:
        return False
    # Long horizontal page-border strokes are frequently OCR'd as a run of glyphs.
    border_ratio = sum(1 for char in text if char in "-—_=|") / max(1, len(text))
    if ((float(row["y0"]) < 60 or float(row["y1"]) > page_height - 60)
            and len(text) >= 18 and border_ratio >= 0.38
            and re.search(r"(?:[-—_=|]){4,}", text)):
        return False
    # The decorative side borders often yield repeated isolated 1/I/! tokens.
    if len(text) <= 12 and (float(row["x0"]) < 32 or float(row["x1"]) > page_width - 32):
        if re.fullmatch(r"[\s|!:/\\IlHhi\d\[\]{}()'\"‘’`.,;:_—-]+", text):
            return False
        if re.fullmatch(r"(?:a\s*){3,}", text, re.I):
            return False
    if len(text) <= 3 and re.fullmatch(r"[\s|!:/\\IlHhi\d\[\]{}()'\"‘’`.,;:_—-]+", text):
        return False
    return True

def locate_question_headers(rows: list[dict[str, Any]], page_sizes: dict[int, tuple[int, int]]) -> tuple[dict[int, dict[str, Any]], dict[int, int]]:
    index_by_object = {id(row): i for i, row in enumerate(rows)}
    headers: dict[int, dict[str, Any]] = {}
    row_indices: dict[int, int] = {}
    for number, anchor in MANUAL_HEADER_ANCHORS.items():
        candidates = [row for row in rows if int(row["page"]) == anchor["page"] and row["side"] == anchor["side"]]
        if not candidates:
            raise SystemExit(f"Manual source anchor row missing for Q{number}")
        row = min(candidates, key=lambda r: abs(float(r["y0"]) - float(anchor["y"])))
        if abs(float(row["y0"]) - float(anchor["y"])) > 24:
            raise SystemExit(f"Manual source anchor drifted too far for Q{number}: {row}")
        headers[number] = {
            **row,
            "question_number": number,
            "manual_header_fallback": True,
            "manual_review_reason": anchor["review_reason"],
            # Pad above the OCR row to retain the printed number beside the first stem line.
            "crop_start_y": max(0.0, float(row["y0"]) - 26.0),
        }
        row_indices[number] = index_by_object[id(row)]

    for number in range(1, QUESTION_COUNT + 1):
        if number in headers:
            continue
        candidates = [row for row in rows if header_candidate(row, number, page_sizes[int(row["page"])][0])]
        if not candidates:
            raise SystemExit(f"Could not locate source header for Q{number}; refusing partial crop output")
        # Pick the first source-order candidate not already claimed by another number.
        selected = next((row for row in candidates if id(row) not in {id(h) for h in headers.values()}), None)
        if selected is None:
            raise SystemExit(f"Conflicting OCR header candidates for Q{number}")
        headers[number] = {
            **selected,
            "question_number": number,
            "manual_header_fallback": False,
            "crop_start_y": max(0.0, float(selected["y0"]) - 12.0),
        }
        row_indices[number] = index_by_object[id(selected)]

    expected_order = list(range(1, QUESTION_COUNT + 1))
    ordered_numbers = [h["question_number"] for h in sorted(headers.values(), key=ordered_key)]
    if ordered_numbers != expected_order:
        raise SystemExit(f"Question headers are not in exact 1..75 source order: {ordered_numbers}")
    indices = [row_indices[n] for n in expected_order]
    if indices != sorted(indices) or len(indices) != len(set(indices)):
        raise SystemExit("Question header row indices are not unique and ordered")
    return headers, row_indices


def locate_answers(rows: list[dict[str, Any]], header_indices: dict[int, int]) -> dict[int, tuple[int, dict[str, Any]]]:
    answers = [(idx, row) for idx, row in enumerate(rows) if is_answer_row(row)]
    if len(answers) != QUESTION_COUNT:
        raise SystemExit(f"Expected exactly 75 printed Ans. labels, found {len(answers)}")
    mapped = {}
    for number in range(1, QUESTION_COUNT + 1):
        start = header_indices[number]
        stop = header_indices[number + 1] if number < QUESTION_COUNT else len(rows)
        matches = [(idx, row) for idx, row in answers if start < idx < stop]
        if len(matches) != 1:
            detail = [(r["page"], r["side"], round(r["y0"], 1), r["text"]) for _, r in matches]
            raise SystemExit(f"Q{number}: expected one source Ans. boundary before the next numbered header; got {detail}")
        mapped[number] = matches[0]
    return mapped


def safe_crop_segments(root: Path, pages: dict[int, Image.Image], rows: list[dict[str, Any]], start_idx: int,
                       answer_idx: int, header: dict[str, Any], q_number: int, answer_row: dict[str, Any]) -> tuple[Image.Image, list[dict[str, Any]]]:
    row_slice = rows[start_idx:answer_idx + 1]
    grouped: list[dict[str, Any]] = []
    # Preserve source reading stream order. A question that wraps to the next column
    # gets one vertical strip per column, stacked in reading order.
    for idx, row in enumerate(row_slice, start=start_idx):
        key = (int(row["page"]), str(row["side"]))
        if not grouped or grouped[-1]["key"] != key:
            grouped.append({"key": key, "row_start_index": idx, "row_end_index": idx, "rows": [row]})
        else:
            grouped[-1]["row_end_index"] = idx
            grouped[-1]["rows"].append(row)

    strips = []
    source_meta = []
    for segment_index, segment in enumerate(grouped):
        page_no, side = segment["key"]
        image = pages[page_no]
        width, height = image.size
        midpoint = width // 2
        x0, x1 = (22, midpoint - 12) if side == "L" else (midpoint + 12, width - 22)
        first_segment = segment_index == 0
        last_segment = segment_index == len(grouped) - 1
        if first_segment:
            y0 = max(0, int(math.floor(float(header["crop_start_y"]))))
        else:
            useful_rows = [r for r in segment["rows"] if meaningful_source_row(r, width, height)]
            if not useful_rows:
                raise SystemExit(f"Q{q_number}: continuation segment contains only border/empty OCR rows")
            # Printed questions on this paper begin below the decorative top border.
            # Clamp continuation crops to y>=80 native pixels so a column wrap at the
            # top of a page never embeds the page's dashed header border in the question.
            y0 = max(80, int(math.floor(min(float(r["y0"]) for r in useful_rows) - 20.0)))
        if last_segment:
            if q_number == 39:
                y1 = min(height - 20, int(math.ceil(float(answer_row["y1"]) + 12.0)))
            else:
                # Stop just above the printed Ans. label while retaining the previous
                # option row; the OCR row gap is sometimes only a few pixels.
                y1 = max(0, int(math.floor(float(answer_row["y0"]) - 2.0)))
        else:
            # Only extend a wrapped-column segment a little beyond its last meaningful
            # line. Do not include decorative border tokens or the page-bottom stripe.
            useful_rows = [r for r in segment["rows"] if meaningful_source_row(r, width, height)]
            if not useful_rows:
                raise SystemExit(f"Q{q_number}: intermediate segment contains only border/empty OCR rows")
            y1 = min(height - 60, int(math.ceil(max(float(r["y1"]) for r in useful_rows) + 95.0)))
        if y1 <= y0 + 18:
            raise SystemExit(f"Q{q_number}: degenerate crop segment page={page_no} side={side} y0={y0} y1={y1}")
        strip = image.crop((x0, y0, x1, y1)).convert("RGB")
        strips.append(strip)
        source_meta.append({
            "source_page_image_path": f"images/pages/page_{page_no:02d}.jpg",
            "page": page_no,
            "side": side,
            "native_bbox": [x0, y0, x1, y1],
            "ocr_row_index_range": [segment["row_start_index"], segment["row_end_index"]],
            "is_manual_start_anchor": bool(first_segment and header.get("manual_header_fallback")),
            "stops_before_answer": bool(last_segment and q_number != 39),
            "includes_source_dropped_label": bool(last_segment and q_number == 39),
        })

    output_width = max(strip.width for strip in strips)
    spacer = 26
    output_height = sum(strip.height for strip in strips) + spacer * max(0, len(strips) - 1)
    if output_height < 120 or output_width < 300:
        raise SystemExit(f"Q{q_number}: implausibly small combined crop {output_width}x{output_height}")
    canvas = Image.new("RGB", (output_width, output_height), "white")
    current_y = 0
    for strip in strips:
        canvas.paste(strip, (0, current_y))
        current_y += strip.height + spacer
    return canvas, source_meta


def make_contact_sheet(entries: list[tuple[Path, str]], dest: Path, *, columns: int = 5, cell_width: int = 280,
                       image_height: int = 285, label_height: int = 32) -> None:
    if not entries:
        raise SystemExit(f"No entries to make contact sheet: {dest}")
    rows = math.ceil(len(entries) / columns)
    tile_h = image_height + label_height
    sheet = Image.new("RGB", (columns * cell_width, rows * tile_h), (248, 248, 248))
    draw = ImageDraw.Draw(sheet)
    for i, (path, label) in enumerate(entries):
        col, row = i % columns, i // columns
        x, y = col * cell_width, row * tile_h
        with Image.open(path) as opened:
            thumb = ImageOps.contain(opened.convert("RGB"), (cell_width - 10, image_height - 10))
        sheet.paste(thumb, (x + (cell_width - thumb.width) // 2, y + (image_height - thumb.height) // 2))
        draw.rectangle((x, y, x + cell_width - 1, y + image_height - 1), outline=(175, 175, 175), width=1)
        draw.text((x + 6, y + image_height + 5), label[:40], fill=(20, 20, 20))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=83, optimize=True, progressive=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--source-pdf", type=Path, default=None,
                    help="Optional actual PDF bytes to SHA-256 check; CI bundle flow can omit this only after pinned bundle/source metadata checks.")
    ap.add_argument("--ocr-cache-dir", type=Path, default=None,
                    help="Optional folder with cached ocr_lines_*.json files; otherwise run Tesseract OCR over the page images.")
    args = ap.parse_args()
    root = args.data_dir.resolve()
    json_path = root / "jee_main_2026_01_22_shift1_FINAL_75Q.json"
    if not json_path.is_file():
        raise SystemExit(f"Dataset JSON missing: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    paper = data.get("paper") or {}
    if paper.get("paper_id") != EXPECTED_PAPER_ID or paper.get("exam_date") != EXPECTED_DATE or paper.get("shift") != EXPECTED_SHIFT:
        raise SystemExit("Source paper identity mismatch; refusing to generate crops")
    if paper.get("source_sha256") != SOURCE_SHA:
        raise SystemExit("Dataset source PDF SHA-256 metadata mismatch")
    questions = data.get("questions")
    if not isinstance(questions, list) or len(questions) != QUESTION_COUNT:
        raise SystemExit(f"Expected exactly {QUESTION_COUNT} question records")
    by_number = {q.get("question_number"): q for q in questions}
    if set(by_number) != set(range(1, QUESTION_COUNT + 1)):
        raise SystemExit("Question numbers must be exactly 1..75")
    q39 = by_number[39]
    if q39.get("question_status") != "Dropped" or q39.get("correct_answer") is not None or q39.get("answer_text") != "Dropped":
        raise SystemExit("Q39 dropped-source record contract failed; no crops will be written")

    source_pdf_bytes_verified = False
    if args.source_pdf:
        if not args.source_pdf.is_file():
            raise SystemExit(f"Source PDF not found: {args.source_pdf}")
        actual_sha = sha256(args.source_pdf)
        if actual_sha != SOURCE_SHA:
            raise SystemExit(f"Source PDF SHA-256 mismatch: {actual_sha}")
        source_pdf_bytes_verified = True

    page_sizes = {}
    page_images = {}
    expected_page_hashes = {}
    asset_manifest_path = root / "asset-manifest.json"
    prior_manifest = {}
    if asset_manifest_path.is_file():
        prior_manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8"))
        expected_page_hashes = {a.get("path"): a.get("sha256") for a in prior_manifest.get("assets", []) if str(a.get("path", "")).startswith("images/pages/")}
    if not source_pdf_bytes_verified:
        if prior_manifest.get("source_pdf_sha256") != SOURCE_SHA:
            raise SystemExit("Without PDF bytes, asset-manifest.json must contain the pinned source PDF SHA-256 metadata.")
        expected_paths = {f"images/pages/page_{i:02d}.jpg" for i in range(1, PAGE_COUNT + 1)}
        if set(expected_page_hashes) != expected_paths:
            raise SystemExit("Without PDF bytes, the asset manifest must pin exactly 24 source-page image hashes.")
        for rel, digest in expected_page_hashes.items():
            path = root / rel
            if not path.is_file() or sha256(path) != digest:
                raise SystemExit(f"Pinned source page-image SHA-256 mismatch: {rel}")
    for page_no in range(1, PAGE_COUNT + 1):
        path = root / "images" / "pages" / f"page_{page_no:02d}.jpg"
        if not path.is_file():
            raise SystemExit(f"Missing original page image: {path}")
        if path.relative_to(root).as_posix() in expected_page_hashes and sha256(path) != expected_page_hashes[path.relative_to(root).as_posix()]:
            raise SystemExit(f"Source page image hash mismatch: {path}")
        im = Image.open(path).convert("RGB")
        page_images[page_no] = im
        page_sizes[page_no] = im.size
    if any(size[0] < 1000 or size[1] < 1500 for size in page_sizes.values()):
        raise SystemExit("Unexpected source page image dimensions; refusing low-resolution crops")

    cache_path = args.ocr_cache_dir.resolve() if args.ocr_cache_dir else None
    rows = load_ocr_rows(root, cache_path, page_images)
    if cache_path is not None:
        cache_meta = json.loads((cache_path / "ocr-cache-manifest.json").read_text(encoding="utf-8"))
        ocr_provenance = {
            "mode": "pinned_precomputed_ocr_rows",
            "engine": cache_meta.get("ocr_engine"),
            "config": cache_meta.get("ocr_config"),
            "scale": cache_meta.get("scale"),
            "cache_manifest_sha256": sha256(cache_path / "ocr-cache-manifest.json"),
            "cache_file_count": len(cache_meta.get("files", [])),
            "row_count": len(rows),
        }
    else:
        try:
            import pytesseract
            engine_version = str(pytesseract.get_tesseract_version()).splitlines()[0]
        except Exception as exc:
            raise SystemExit("Tesseract/pytesseract is required when --ocr-cache-dir is not supplied") from exc
        ocr_provenance = {
            "mode": "ocr_run_from_verified_source_page_images",
            "engine": engine_version,
            "config": "--psm 6",
            "scale": 0.72,
            "row_count": len(rows),
            "source_page_image_hashes_verified": not source_pdf_bytes_verified,
        }
    headers, header_indices = locate_question_headers(rows, page_sizes)
    answer_mappings = locate_answers(rows, header_indices)

    # All source mapping checks complete before changing the dataset or overwriting any image path.
    all_questions_dir = root / "images" / "questions"
    all_questions_dir.mkdir(parents=True, exist_ok=True)
    crop_records = []
    for number in range(1, QUESTION_COUNT + 1):
        answer_idx, answer_row = answer_mappings[number]
        crop, source_segments = safe_crop_segments(
            root, page_images, rows, header_indices[number], answer_idx,
            headers[number], number, answer_row,
        )
        dest = all_questions_dir / f"q{number:03d}_full_question.jpg"
        crop.save(dest, "JPEG", quality=91, optimize=True, progressive=True)
        crop_records.append({
            "question_number": number,
            "question_id": by_number[number].get("question_id"),
            "path": f"images/questions/{dest.name}",
            "width": crop.width,
            "height": crop.height,
            "bytes": dest.stat().st_size,
            "sha256": sha256(dest),
            "start_header": {
                "page": headers[number]["page"],
                "side": headers[number]["side"],
                "y": round(float(headers[number]["crop_start_y"]), 2),
                "manual_fallback": bool(headers[number].get("manual_header_fallback")),
                "manual_review_reason": headers[number].get("manual_review_reason"),
                "ocr_line": headers[number].get("text"),
            },
            "answer_boundary": {
                "page": answer_row["page"],
                "side": answer_row["side"],
                "y0": round(float(answer_row["y0"]), 2),
                "y1": round(float(answer_row["y1"]), 2),
                "printed_label_ocr": answer_row.get("text"),
            },
            "source_segments": source_segments,
            "review_status": "REVIEW_REQUIRED",
            "source_dropped_label_included": number == 39,
        })

    if len(crop_records) != QUESTION_COUNT or {r["question_number"] for r in crop_records} != set(range(1,76)):
        raise SystemExit("Full question crop set is incomplete")
    missing_paths = [r["path"] for r in crop_records if not (root / r["path"]).is_file()]
    if missing_paths:
        raise SystemExit(f"Generated question crop files are missing: {missing_paths[:8]}")

    for q in questions:
        n = int(q["question_number"])
        old_path = q.get("question_image_path")
        if old_path and old_path != f"images/questions/q{n:03d}_full_question.jpg":
            if old_path.endswith("_figure.jpg"):
                q["question_figure_image_path"] = old_path
            elif n == 39:
                q["question_source_crop_path"] = old_path
            else:
                q["previous_question_image_path"] = old_path
        q["question_image_path"] = f"images/questions/q{n:03d}_full_question.jpg"
        q["question_image_source"] = "source-page crop; question/options retained in visual order"
        q["question_image_review_status"] = "REVIEW_REQUIRED"
        # Keep source lineage and all OCR/answer/solution fields untouched.

    full_manifest = {
        "schema_version": "1.0.0",
        "paper_id": EXPECTED_PAPER_ID,
        "source_pdf": SOURCE_PDF,
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "verification_mode": (
            "actual PDF bytes SHA-256 verified in this run"
            if source_pdf_bytes_verified else
            "source SHA is pinned in dataset metadata and source page-image hashes are verified; actual PDF bytes were not available to this invocation"
        ),
        "source_page_count": PAGE_COUNT,
        "ocr_provenance": ocr_provenance,
        "question_count": QUESTION_COUNT,
        "source_stream_order": "PDF page ascending; each page left column top-to-bottom, then right column top-to-bottom",
        "answer_boundary_rule": "Question crop stops before its own printed Ans. row; source-dropped Q39 includes its printed dropped label",
        "manual_header_fallbacks": [
            {"question_number": n, **entry} for n, entry in MANUAL_HEADER_ANCHORS.items()
        ],
        "quality_status": "REVIEW_REQUIRED",
        "production_import": "NOT_PERFORMED",
        "warning": "OCR-driven crop boundaries require human visual review. Full question crops preserve printed options/figures, and question/answer/solution text in the JSON was not modified by this crop script.",
        "question_crops": crop_records,
    }
    full_manifest_path = root / "full-question-crop-manifest.json"
    full_manifest_path.write_text(json.dumps(full_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    data["image_path_convention"] = (
        "question_image_path targets a full source-page crop that preserves question text, printed options and figures before the printed Ans. row; "
        "question_figure_image_path preserves any separate figure/table crop; solution_image_path targets a separate printed-solution crop when available; "
        "source_page_image_path always points to the original full-page source image. Q39 remains Dropped with no invented correct answer."
    )
    data["database_notes"]["import_gate"] = (
        "REVIEW_REQUIRED: visually compare all 75 full-question crops, question text, options, answers, solution images and source-page associations. "
        "Do not import into D1/production until the question-level review is complete. No import or deployment was performed by this script."
    )
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Rebuild hash-backed assets list without trusting stale asset-manifest contents.
    assets = []
    image_root = root / "images"
    watermarked_root = image_root / "watermarked"
    # The watermark step stores branded review copies below images/watermarked/.
    # They mirror the source images and must not enter the source asset count/hash list.
    for path in sorted(p for p in image_root.rglob("*.jpg") if watermarked_root not in p.parents):
        rel = path.relative_to(root).as_posix()
        with Image.open(path) as im:
            fmt = im.format or "JPEG"
        assets.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path), "mime_type": "image/jpeg"})
    expected_assets = PAGE_COUNT + 1 + len([p for p in assets if p["path"].startswith("images/questions/q") and p["path"].endswith("_figure.jpg")]) + len([p for p in assets if p["path"].startswith("images/solutions/")]) + QUESTION_COUNT
    if len(assets) != expected_assets or len([a for a in assets if a["path"].endswith("_full_question.jpg")]) != QUESTION_COUNT:
        raise SystemExit(f"Asset count/reference invariant failed: {len(assets)} assets")
    asset_manifest = {
        "manifest_version": "1.2.0",
        "paper_id": EXPECTED_PAPER_ID,
        "dataset_json": json_path.name,
        "dataset_sha256": sha256(json_path),
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "question_crop_manifest": "full-question-crop-manifest.json",
        "legacy_figure_solution_manifest": "image-crop-manifest.json",
        "asset_count": len(assets),
        "assets_total_bytes": sum(a["bytes"] for a in assets),
        "assets": assets,
        "status": "FULL_QUESTION_CROPS_GENERATED_REVIEW_REQUIRED",
        "production_import": "NOT_PERFORMED",
    }
    (root / "asset-manifest.json").write_text(json.dumps(asset_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    crop_entries = [(root / r["path"], f"Q{r['question_number']:02d} | {r['width']}x{r['height']}") for r in crop_records]
    make_contact_sheet(crop_entries, root / "full-question-crops-contact-sheet.jpg", columns=5, cell_width=280, image_height=285, label_height=32)
    for start in (1, 26, 51):
        stop = min(QUESTION_COUNT, start + 24)
        selected = [entry for entry, record in zip(crop_entries, crop_records) if start <= record["question_number"] <= stop]
        make_contact_sheet(selected, root / f"full-question-crops-q{start:02d}-q{stop:02d}.jpg", columns=5, cell_width=280, image_height=285, label_height=32)

    report = {
        "status": "REVIEW_REQUIRED",
        "paper_id": EXPECTED_PAPER_ID,
        "source_pdf_sha256": SOURCE_SHA,
        "source_pdf_bytes_verified_in_this_run": source_pdf_bytes_verified,
        "question_records": len(questions),
        "full_question_crops": len(crop_records),
        "legacy_figure_crops": len([a for a in assets if a["path"].endswith("_figure.jpg")]),
        "solution_crops": len([a for a in assets if a["path"].endswith("_solution.jpg")]),
        "source_page_images": PAGE_COUNT,
        "all_question_image_references_exist": all((root / q["question_image_path"]).is_file() for q in questions),
        "question_numbers_exactly_1_to_75": [q["question_number"] for q in questions] == list(range(1,76)),
        "q39_status": q39.get("question_status"),
        "q39_correct_answer": q39.get("correct_answer"),
        "q39_includes_dropped_source_label": next(r for r in crop_records if r["question_number"] == 39)["source_dropped_label_included"],
        "manual_header_fallback_count": len(MANUAL_HEADER_ANCHORS),
        "total_jpeg_assets": len(assets),
        "production_import": "NOT_PERFORMED",
        "review_gate": "Human visual review of every question crop and the text/options/answers/solutions is required; do not import automatically.",
        "contact_sheets": ["full-question-crops-contact-sheet.jpg", "full-question-crops-q01-q25.jpg", "full-question-crops-q26-q50.jpg", "full-question-crops-q51-q75.jpg"],
    }
    (root / "full-question-build-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readme = """# JEE Main 2026 — 22 January Shift 1 (Quarantined source dataset)

## Dataset and image assets
- 75 question records are retained in printed source order.
- Q39 remains marked `Dropped`; the source dropped label is preserved and no correct answer has been invented.
- Original full-page source images are preserved under `images/pages/`.
- 75 full-question image crops are generated under `images/questions/`; they preserve the printed question material, options and diagrams in source reading order and normally stop before the printed `Ans.` row.
- The previous 19 question figure/table crops are retained and linked through `question_figure_image_path`; the six solution crops remain under `images/solutions/`.
- The JSON retains original OCR/transcription/answer/solution fields; this crop script does not rewrite their text values.
- `asset-manifest.json` and `full-question-crop-manifest.json` contain hashes, dimensions, source locations and crop metadata.

## Mandatory review status
**REVIEW_REQUIRED — NOT production-ready.** OCR-based start/answer boundaries and all 75 visual crops require human comparison against the source page images. Three source question-number headers (Q1, Q7 and Q51) use explicit source-checked anchors because OCR missed or misjoined the printed number; these are marked in the manifest. Review all question text, options, answers, solution text/image, and question-to-image associations before any website import.

This pipeline does not write to Cloudflare D1, does not publish question records, and does not deploy or alter a production Worker. No production import was performed.
"""
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "README.txt").write_text(readme, encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())