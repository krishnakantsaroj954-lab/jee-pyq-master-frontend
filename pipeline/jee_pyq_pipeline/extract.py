"""Conservative, source-grounded JEE PDF extraction.

This module never creates synthetic question text, options, answers, or solutions.
Unrecognized layouts remain missing/quarantined and are reported by validation.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

SUBJECTS = {
    "PHYSICS": "Physics",
    "CHEMISTRY": "Chemistry",
    "MATHEMATICS": "Mathematics",
    "MATHS": "Mathematics",
}
_SUBJECT_LINE = re.compile(
    r"^\s*(?:SECTION\s+[A-Z]\s*[-:–]?\s*)?"
    r"(PHYSICS|CHEMISTRY|MATHEMATICS|MATHS)"
    r"(?:\s+(?:SECTION|QUESTIONS?|PAPER)\b.*)?\s*$",
    re.I,
)
_QUESTION_PATTERNS = (
    re.compile(r"^\s*Question\s*(?:No\.?\s*)?#?\s*(\d{1,2})\b\s*[:.)\-]?\s*(.*?)\s*$", re.I),
    re.compile(r"^\s*Q\.?\s*#?\s*(\d{1,2})\b\s*[:.)\-]?\s*(.*?)\s*$", re.I),
    re.compile(r"^\s*(\d{1,2})\s*[.)]\s+(.+?)\s*$", re.I),
)
_OPTION_MARKER = re.compile(
    r"(?<![A-Za-z0-9])(?:\(([A-Da-d1-4])\)|([A-Da-d1-4])[.)])(?=\s|$)"
)
_ANSWER_LINE = re.compile(
    r"^\s*(?:correct\s+(?:answer|option)|answer|ans\.?)\s*(?::|[-–])?\s*(.*?)\s*$",
    re.I,
)
_SOLUTION_LINE = re.compile(
    r"^\s*(?:detailed\s+)?(?:solution|soln?\.?|explanation)\s*(?::|[-–])?\s*(.*?)\s*$",
    re.I,
)
_FIGURE_HINT = re.compile(
    r"\b(?:figure|diagram|graph|circuit|shown\s+below|shown\s+in\s+the\s+figure|"
    r"given\s+in\s+the\s+figure|following\s+figure)\b",
    re.I,
)


def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError("PyMuPDF is required") from error


def _page_words(page):
    """Return PyMuPDF word tuples, using OCR only when the page has no text layer."""
    words = page.get_text("words")
    if words:
        return words, False
    text_page = page.get_textpage_ocr(language="eng", dpi=250, full=True)
    words = page.get_text("words", textpage=text_page)
    return words, True


def _question_start(text: str):
    """Return (start offset, source number, header remainder), or None."""
    for pattern in _QUESTION_PATTERNS:
        match = pattern.match(text or "")
        if match:
            number = int(match.group(1))
            remainder = (match.group(2) or "").strip()
            return match.start(), number, remainder
    return None


def _parse_answer(text: str) -> str | None:
    """Parse only the value printed after a source answer marker; never infer it."""
    raw = safe_normalize(text or "").strip()
    raw = raw.strip("()[]{} ")
    if not raw:
        return None
    match = re.match(r"^([A-Da-d]|-?\d+(?:\.\d+)?(?:/\d+)?)", raw)
    if not match:
        # Fractions/decimals may be followed by units or punctuation.
        match = re.match(r"^(-?\d+(?:\.\d+)?(?:/\d+)?)", raw)
    if not match:
        return None
    value = match.group(1)
    return value.upper() if value.isalpha() else value


def _row_text(row: Any) -> str:
    if isinstance(row, str):
        return row
    if isinstance(row, (tuple, list)) and len(row) >= 2 and isinstance(row[1], str):
        return row[1]
    return ""


def _split_options(rows) -> tuple[str, dict[str, str]]:
    """Split clearly-labelled A-D or 1-4 options; otherwise retain the raw stem."""
    texts = [_row_text(row) for row in rows] if not isinstance(rows, str) else [rows]
    raw = "\n".join(text for text in texts if text.strip())
    matches = list(_OPTION_MARKER.finditer(raw))
    if len(matches) < 4:
        return safe_normalize(raw), {}

    # Find one unambiguous sequence, not an arbitrary four numeral/letter matches.
    found = None
    for start in range(0, len(matches) - 3):
        group = matches[start:start + 4]
        labels = [(m.group(1) or m.group(2)).upper() for m in group]
        if labels in (["A", "B", "C", "D"], ["1", "2", "3", "4"]):
            found = group
            break
    if not found:
        return safe_normalize(raw), {}

    question_stem = safe_normalize(raw[:found[0].start()])
    options: dict[str, str] = {}
    for index, match in enumerate(found):
        end = found[index + 1].start() if index < 3 else len(raw)
        value = safe_normalize(raw[match.end():end])
        label = (match.group(1) or match.group(2)).upper()
        if not value:
            return safe_normalize(raw), {}
        options[label] = value
    if len(options) != 4:
        return safe_normalize(raw), {}
    return question_stem, options


def _split_source_sections(rows):
    """Split question/options, source answer, and source solution from line records.

    Each row is (page_number, line_text, [x0, y0, x1, y1]). The returned error
    is a diagnostic string only; callers must not fill missing fields by guessing.
    """
    qrows = []
    srows = []
    answer = None
    mode = "question"
    for row in rows:
        line = _row_text(row).strip()
        answer_match = _ANSWER_LINE.match(line)
        solution_match = _SOLUTION_LINE.match(line)
        if mode == "question" and answer_match:
            answer = _parse_answer(answer_match.group(1))
            mode = "after_answer"
            continue
        if solution_match:
            mode = "solution"
            remainder = solution_match.group(1).strip()
            if remainder:
                page = row[0] if isinstance(row, (tuple, list)) and len(row) > 0 else 1
                bounds = row[2] if isinstance(row, (tuple, list)) and len(row) > 2 else [0, 0, 0, 0]
                srows.append((page, remainder, bounds))
            continue
        if mode == "solution":
            srows.append(row)
        elif mode == "question":
            qrows.append(row)
        # Lines after an answer marker but before a solution marker belong to
        # the answer-key section, not to the question statement.

    qtext, options = _split_options(qrows)
    qtext = safe_normalize(qtext)
    solution_text = safe_normalize("\n".join(_row_text(row) for row in srows))
    error = None
    if not qtext:
        error = "empty_question_text"
    return qtext, options, answer, solution_text or None, qrows, srows, error


def _line_records(page, page_number: int):
    """Group word geometry into text lines and restore sensible two-column order."""
    words, used_ocr = _page_words(page)
    grouped = defaultdict(list)
    for word in words:
        if len(word) < 8:
            continue
        grouped[(int(word[5]), int(word[6]))].append(word)

    records = []
    for key, group in grouped.items():
        group.sort(key=lambda item: (float(item[0]), int(item[7])))
        text = safe_normalize(" ".join(str(item[4]) for item in group))
        if not text:
            continue
        x0 = min(float(item[0]) for item in group)
        y0 = min(float(item[1]) for item in group)
        x1 = max(float(item[2]) for item in group)
        y1 = max(float(item[3]) for item in group)
        records.append({
            "page": page_number, "text": text, "bounds": [x0, y0, x1, y1],
            "ocr": used_ocr, "block": key[0], "line": key[1],
        })

    midpoint = float(page.rect.width) / 2.0
    left = [r for r in records if (r["bounds"][0] + r["bounds"][2]) / 2.0 < midpoint]
    right = [r for r in records if r not in left]
    narrow_left = sum(1 for r in left if r["bounds"][2] - r["bounds"][0] < midpoint * 0.95)
    narrow_right = sum(1 for r in right if r["bounds"][2] - r["bounds"][0] < midpoint * 0.95)
    two_columns = len(left) >= 3 and len(right) >= 3 and narrow_left >= 3 and narrow_right >= 3
    if two_columns:
        records = sorted(left, key=lambda r: (r["bounds"][1], r["bounds"][0])) + \
                  sorted(right, key=lambda r: (r["bounds"][1], r["bounds"][0]))
    else:
        records.sort(key=lambda r: (r["bounds"][1], r["bounds"][0]))
    return records


def _is_subject_heading(text: str) -> str | None:
    match = _SUBJECT_LINE.match(safe_normalize(text or ""))
    if not match:
        return None
    return SUBJECTS[match.group(1).upper()]


def _bounds_for_rows(rows):
    valid = [row[2] for row in rows if isinstance(row, (tuple, list)) and len(row) > 2 and len(row[2]) == 4]
    if not valid:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(min(b[0] for b in valid), 2),
        round(min(b[1] for b in valid), 2),
        round(max(b[2] for b in valid), 2),
        round(max(b[3] for b in valid), 2),
    ]


def extract(config, asset_dir: Path) -> tuple[list[Question], list[Asset], list[Issue], int]:
    """Extract only statements and answer/solution evidence actually found in the PDF."""
    fitz = _fitz()
    asset_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(config.source_pdf)
    page_count = len(doc)
    source_hash = sha256_file(config.source_pdf)
    issues: list[Issue] = []
    all_assets: list[Asset] = []
    page_records: dict[int, list[dict[str, Any]]] = {}
    page_sizes: dict[int, tuple[float, float]] = {}

    start_page, end_page = config.page_range
    if start_page < 1 or end_page > page_count or start_page > end_page:
        doc.close()
        return [], [], [Issue("INVALID_PAGE_RANGE", f"Configured page range {config.page_range} is outside a {page_count}-page PDF")], page_count

    # Extract actual embedded image objects with checksums and placement geometry.
    image_records = []
    for page_no in range(start_page, end_page + 1):
        page = doc[page_no - 1]
        page_sizes[page_no] = (float(page.rect.width), float(page.rect.height))
        for image_no, item in enumerate(page.get_images(full=True)):
            xref = item[0]
            try:
                payload = doc.extract_image(xref)
                if not payload or not payload.get("image"):
                    continue
                data = payload["image"]
                digest = hashlib.sha256(data).hexdigest()
                ext = payload.get("ext", "png")
                key = f"{source_hash[:16]}/page-{page_no}/img-{image_no}-{digest[:12]}.{ext}"
                destination = asset_dir / key
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                for rect in page.get_image_rects(xref):
                    bounds = [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]
                    asset = Asset(key, page_no, bounds, digest, str(destination.relative_to(asset_dir.parent)))
                    all_assets.append(asset)
                    page_area = max(1.0, float(page.rect.width * page.rect.height))
                    rect_area = max(0.0, float(rect.width * rect.height))
                    # A full-page scan is source evidence, not a question-specific figure.
                    if rect_area / page_area < 0.65:
                        image_records.append({
                            "page": page_no, "rect": rect, "bounds": bounds,
                            "digest": digest, "ext": ext, "raw_path": destination,
                            "area_ratio": rect_area / page_area,
                        })
            except Exception as error:
                issues.append(Issue("IMAGE_EXTRACTION_FAILED", f"Page {page_no}, image {image_no}: {error}"))

        page_records[page_no] = _line_records(page, page_no)

    # Build subject-aware question occurrences. Unknown subject labels are not guessed.
    default_subject = config.subject if config.subject in set(SUBJECTS.values()) else None
    current_subject = default_subject
    occurrences = []
    current = None

    def flush():
        nonlocal current
        if current is not None:
            occurrences.append(current)
            current = None

    for page_no in range(start_page, end_page + 1):
        for line in page_records[page_no]:
            text = line["text"]
            detected_subject = _is_subject_heading(text)
            if detected_subject:
                flush()
                current_subject = detected_subject
                continue

            header = _question_start(text)
            if not header:
                if current is not None:
                    current["rows"].append((page_no, text, line["bounds"]))
                continue

            flush()
            _, number, remainder = header
            key_subject = current_subject
            row_text = remainder
            header_row = (page_no, row_text, line["bounds"])
            current = {
                "subject": key_subject,
                "number": number,
                "rows": [header_row],
                "header_page": page_no,
                "header_bounds": line["bounds"],
                "header_text": text,
                "ocr_used": line["ocr"],
            }
    flush()
    doc.close()

    if not occurrences:
        issues.append(Issue(
            "NO_QUESTION_HEADERS",
            "No source question headers were recognized. The PDF layout needs inspection; no placeholder questions were created.",
        ))
        return [], all_assets, issues, page_count

    expected_keys = set(getattr(config, "expected_question_numbers", ()) or ())
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        subject = occurrence["subject"]
        number = occurrence["number"]
        if subject is None:
            issues.append(Issue(
                "AMBIGUOUS_SUBJECT",
                f"Question {number} was found without a source subject heading; its subject was not inferred.",
            ))
            continue
        grouped[f"{subject}:{number}"].append(occurrence)

    questions: list[Question] = []
    first_regions: dict[str, dict[str, Any]] = {}
    for key, candidates in grouped.items():
        parsed = []
        for candidate in candidates:
            qtext, options, answer, solution_text, qrows, srows, error = _split_source_sections(candidate["rows"])
            parsed.append({
                "candidate": candidate, "text": qtext, "options": options, "answer": answer,
                "solution_text": solution_text, "qrows": qrows, "srows": srows, "error": error,
            })

        # Prefer the source occurrence with actual statement/options; obtain answer/solution
        # only from another occurrence when the question occurrence has no such evidence.
        statement = max(parsed, key=lambda item: (bool(item["text"]), len(item["text"]), len(item["options"])))
        answer_item = next((item for item in parsed if item["answer"] is not None), None)
        solution_item = max(
            (item for item in parsed if item["solution_text"]),
            key=lambda item: len(item["solution_text"]),
            default=None,
        )
        candidate = statement["candidate"]
        qrows = statement["qrows"]
        question_pages = sorted({row[0] for row in qrows if isinstance(row, (tuple, list)) and row})
        if not question_pages:
            question_pages = [candidate["header_page"]]
        bounds = _bounds_for_rows(qrows)
        answer = answer_item["answer"] if answer_item else None
        solution = None
        if solution_item:
            solution_pages = sorted({
                row[0] for row in solution_item["srows"]
                if isinstance(row, (tuple, list)) and row
            })
            solution = {"text": solution_item["solution_text"], "pages": solution_pages}

        options = statement["options"]
        if options:
            question_type = "MCQ"
        elif answer is not None and not re.fullmatch(r"[A-Da-d]", answer):
            question_type = "NUMERICAL"
        else:
            question_type = "UNKNOWN"

        question_id = f"{source_hash[:16]}-{candidate['subject'].lower()}-q-{candidate['number']:03d}"
        source_row_records = candidate["rows"]
        requires_figure = bool(_FIGURE_HINT.search(statement["text"]))
        question = Question(
            question_id, candidate["number"], statement["text"], options, answer,
            question_pages, bounds,
            {
                "source_sha256": source_hash,
                "source_document": Path(config.source_pdf).name,
                "extraction_method": "pymupdf-word-geometry",
                "source_header": candidate["header_text"],
                "source_pages": question_pages,
                "ocr_used": any(row_candidate["candidate"]["ocr_used"] for row_candidate in parsed),
            },
            [], solution, requires_figure, "VALIDATED", [], candidate["subject"], None, question_type, [],
        )
        questions.append(question)
        first_regions[key] = {
            "candidate": candidate,
            "rows": source_row_records,
            "question": question,
        }

    # Attach a rendered figure crop only when a non-page-sized source image falls
    # within the actual question text's page/column region. Full-page scans are excluded.
    figure_doc = fitz.open(config.source_pdf)
    for image_record in image_records:
        page_no = image_record["page"]
        rect = image_record["rect"]
        center_x = (rect.x0 + rect.x1) / 2
        center_y = (rect.y0 + rect.y1) / 2
        page_width, page_height = page_sizes[page_no]
        same_page = []
        for key, info in first_regions.items():
            candidate = info["candidate"]
            if candidate["header_page"] != page_no:
                continue
            header_bounds = candidate["header_bounds"]
            header_center_x = (header_bounds[0] + header_bounds[2]) / 2
            if abs(header_center_x - center_x) > page_width * 0.48:
                continue
            qrows = info["rows"]
            question_rows = []
            for row in qrows:
                if len(row) < 3 or row[0] != page_no:
                    continue
                if _ANSWER_LINE.match(str(row[1])) or _SOLUTION_LINE.match(str(row[1])):
                    break
                question_rows.append(row)
            if not question_rows:
                continue
            y0 = min(row[2][1] for row in question_rows)
            y1 = max(row[2][3] for row in question_rows)
            x0 = min(row[2][0] for row in question_rows)
            x1 = max(row[2][2] for row in question_rows)
            if y0 - 20 <= center_y <= y1 + 20 and x0 - page_width * 0.18 <= center_x <= x1 + page_width * 0.18:
                same_page.append((abs(center_y - (y0 + y1) / 2), key, info))
        if not same_page:
            continue
        _, key, info = min(same_page, key=lambda item: item[0])
        try:
            page = figure_doc[page_no - 1]
            pad = 4
            crop = fitz.Rect(
                max(0, rect.x0 - pad), max(0, rect.y0 - pad),
                min(page_width, rect.x1 + pad), min(page_height, rect.y1 + pad),
            )
            pix = page.get_pixmap(clip=crop, alpha=False)
            crop_key = f"question-crops/{info['question'].id}-figure-{len(info['question'].assets) + 1}.png"
            crop_path = asset_dir / crop_key
            crop_path.parent.mkdir(parents=True, exist_ok=True)
            pix.save(crop_path)
            crop_bytes = crop_path.read_bytes()
            crop_hash = hashlib.sha256(crop_bytes).hexdigest()
            info["question"].assets.append(Asset(
                crop_key, page_no,
                [round(crop.x0, 2), round(crop.y0, 2), round(crop.x1, 2), round(crop.y1, 2)],
                crop_hash, str(crop_path.relative_to(asset_dir.parent)),
            ))
            if _FIGURE_HINT.search(info["question"].text):
                info["question"].requires_figure = True
        except Exception as error:
            issues.append(Issue("FIGURE_CROP_FAILED", f"Could not crop source figure on page {page_no}: {error}"))

    figure_doc.close()
    return questions, all_assets, issues, page_count
