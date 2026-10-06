"""Image-first extraction: PDF regions become the question and solution content."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any

from .models import Issue, Question
from .util import normalize_line, safe_name, sha256_file

QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:question|ques|q)\.?\s*(?:no\.?|number|num\.?|#)?\s*([0-9]{1,2}|[IL])"
    r"\s*(?=$|[:.)\-]|\s)",
    re.I,
)
QUESTION_BARE_RE = re.compile(r"^\s*([0-9]{1,2})\s*(?=[:.)\-]|\s|$)")
QUESTION_NOISE_RE = re.compile(
    r"^\s*[0-9]{1,2}\s*(?:[:.)\-]\s*)?(?:ans(?:wer)?|sol(?:ution)?|figure|number)\b",
    re.I,
)
SUBJECT_RE = re.compile(r"^(Physics|Chemistry|Mathematics|Maths)$", re.I)
SOLUTION_SECTION_RE = re.compile(
    r"^(?:detailed\s+)?(?:solutions?|answers?\s+and\s+solutions?|answer\s+key)\b", re.I
)
SOLUTION_Q_RE = re.compile(
    r"^\s*(?:solution|sol\.?|answer|ans\.?)\s*(?:for|of)?\s*"
    r"(?:question|ques\.?|q\.?)?\s*(?:no\.?|number|num\.?|#)?\s*([0-9]{1,2}|[IL])"
    r"\s*(?=$|[:.)\-]|\s)",
    re.I,
)
ANSWER_RE = re.compile(
    r"\b(?:correct\s+answer|answer|ans\.?|key)\s*[:\-]?\s*"
    r"(?:\(([A-D])\)|([A-D])|([1-4])|(-?[0-9]+(?:\.[0-9]+)?))\b", re.I
)
OPTION_RE = re.compile(r"(?:^|\s)(?:\(([A-D]|[1-4])\)|([A-D]|[1-4])[.)])\s", re.I)

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required") from exc

def _words_to_lines(words):
    if not words:
        return []
    lines = []
    for group in _split_word_columns(words):
        group = sorted(group, key=lambda w: (float(w[1]), float(w[0])))
        current, current_y = [], None
        for word in group:
            y = float(word[1])
            if current and abs(y - current_y) > 3.5:
                lines.append(_make_line(current))
                current = []
            current.append(word)
            current_y = y
        if current:
            lines.append(_make_line(current))
    return sorted(lines, key=lambda l: (l["y0"], l["x0"]))


def _split_word_columns(words, width=None):
    width = float(width) if width is not None else max((float(w[2]) for w in words), default=0.0)
    words = sorted(words, key=lambda w: (float(w[0]), float(w[1])))
    xs = sorted(float(w[0]) for w in words)
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    gap, idx = max(gaps, default=(0.0, 0))
    groups = [words]
    if width > 0 and gap >= width * 0.10:
        split_x = (xs[idx] + xs[idx + 1]) / 2.0
        left = [w for w in words if float(w[0]) < split_x]
        right = [w for w in words if float(w[0]) >= split_x]
        if len(left) >= 8 and len(right) >= 8:
            groups = [left, right]
    return groups


def _question_number(text):
    text = normalize_line(text)
    m = QUESTION_PREFIX_RE.match(text)
    if m:
        raw = m.group(1).upper()
        if raw in {"I", "L"}:
            raw = "1"
        return int(raw)
    m = QUESTION_BARE_RE.match(text)
    return int(m.group(1)) if m else None


def _header_signal(lines):
    q = sum(1 for l in lines if _question_number(l["text"]) is not None)
    sol = sum(1 for l in lines if SOLUTION_SECTION_RE.match(l["text"]) or SOLUTION_Q_RE.match(l["text"]))
    subj = sum(1 for l in lines if SUBJECT_RE.fullmatch(l["text"]))
    return q * 10 + sol * 4 + subj * 6


def _line_records(page):
    """Build text lines without merging visual columns; use OCR when it exposes more structural markers."""
    native_words = page.get_text("words")
    native_lines = _words_to_lines(native_words)

    ocr_lines = []
    try:
        tp = page.get_textpage_ocr(language="eng", dpi=250, full=True)
        ocr_words = page.get_text("words", textpage=tp)
        ocr_lines = _words_to_lines(ocr_words)
    except Exception:
        ocr_lines = []

    if not native_lines:
        if not ocr_lines:
            raise RuntimeError(f"Cannot read page {page.number + 1} as native text or OCR")
        return ocr_lines

    if ocr_lines and _header_signal(ocr_lines) > _header_signal(native_lines):
        return ocr_lines
    return native_lines

def _make_line(words):
    return {
        "text": normalize_line(" ".join(str(w[4]) for w in sorted(words, key=lambda w: float(w[0])))),
        "x0": min(float(w[0]) for w in words),
        "y0": min(float(w[1]) for w in words),
        "x1": max(float(w[2]) for w in words),
        "y1": max(float(w[3]) for w in words),
    }

def _page_columns(page, lines):
    width = float(page.rect.width)
    if not lines:
        return [(0.0, width)]

    # Detect visual columns from line start positions (x0), not line extents.
    # Long equations/figures can span across the page and would otherwise make
    # a genuine two-column page look like a single column.
    x0s = sorted(float(l["x0"]) for l in lines)
    gaps = [(x0s[i + 1] - x0s[i], i) for i in range(len(x0s) - 1)]
    gap, idx = max(gaps, default=(0.0, -1))
    if idx >= 0 and gap >= width * 0.12:
        left_count = idx + 1
        right_count = len(x0s) - left_count
        if left_count >= 8 and right_count >= 8:
            split_x = (x0s[idx] + x0s[idx + 1]) / 2.0
            return [(0.0, split_x), (split_x, width)]

    return [(0.0, width)]

def _line_column(data, line):
    columns = data["columns"]
    if len(columns) == 2 and line["x0"] >= columns[1][0]:
        return 1
    return 0


def _is_question_candidate(data, column, line):
    text = normalize_line(line["text"])
    if QUESTION_NOISE_RE.match(text):
        return False

    number = _question_number(text)
    if number is None or not 1 <= number <= 25:
        return False

    if QUESTION_PREFIX_RE.match(text):
        return True

    # Bare numeric headers are accepted only near the column's reading margin
    # and when enough alphabetic content remains to resemble a question line.
    x0, x1 = data["columns"][column]
    margin_limit = x0 + max(48.0, (x1 - x0) * 0.08)
    alpha_count = len(re.findall(r"[A-Za-z]", text))
    return float(line["x0"]) <= margin_limit and alpha_count >= 3


def _question_starts(page_data):
    starts = []
    for page_no, data in enumerate(page_data, 1):
        for column in range(len(data["columns"])):
            blocked = False
            column_lines = [
                line for line in data["lines"]
                if _line_column(data, line) == column
            ]
            for line in sorted(column_lines, key=lambda l: (l["y0"], l["x0"])):
                if SOLUTION_SECTION_RE.match(line["text"]):
                    blocked = True
                    continue
                if blocked:
                    continue
                if not _is_question_candidate(data, column, line):
                    continue
                number = _question_number(line["text"])
                starts.append({"page": page_no, "number": number, "column": column, **line})
    starts.sort(key=lambda x: (x["page"], x["column"], x["y0"], x["x0"]))
    return starts

def _solution_starts(page_data):
    found = []
    for page_no, data in enumerate(page_data, 1):
        for column in range(len(data["columns"])):
            solution_seen = False
            column_lines = [
                line for line in data["lines"]
                if _line_column(data, line) == column
            ]
            for line in sorted(column_lines, key=lambda l: (l["y0"], l["x0"])):
                # Numbered solution headers must be tested before the generic section heading,
                # because "Solution 1" also matches the word "Solution".
                m = SOLUTION_Q_RE.match(line["text"])
                if solution_seen and m:
                    raw = next((g for g in m.groups() if g), None)
                    if raw:
                        raw = raw.upper()
                        number = int("1" if raw in {"I", "L"} else raw)
                        if 1 <= number <= 25:
                            found.append({"page": page_no, "number": number, "column": column, **line})
                    continue

                if SOLUTION_SECTION_RE.match(line["text"]):
                    solution_seen = True
                    continue

                if not solution_seen:
                    continue

                # Some sources repeat a bare "Question N" marker inside the solution block.
                number = _question_number(line["text"])
                if number is not None and 1 <= number <= 25:
                    found.append({"page": page_no, "number": number, "column": column, **line})

    found.sort(key=lambda x: (x["page"], x["column"], x["y0"], x["x0"]))
    return found

def _segments_for_item(item, next_item, page_data, page_count):
    segments = []
    start_page = item["page"]
    start_y = item["y0"]
    start_col = item["column"]

    same_column_next = (
        next_item is not None
        and next_item["page"] == start_page
        and next_item["column"] == start_col
    )
    if same_column_next:
        end_page = start_page
        end_y = next_item["y0"]
    elif next_item is not None and next_item["page"] > start_page and next_item["column"] == start_col:
        end_page = next_item["page"]
        end_y = next_item["y0"]
    else:
        end_page = start_page
        end_y = float(page_data[start_page - 1]["page"].rect.height)

    for page_no in range(start_page, end_page + 1):
        data = page_data[page_no - 1]
        columns = data["columns"]
        x0, x1 = columns[start_col] if start_col < len(columns) else (0.0, float(data["page"].rect.width))
        pad = 8.0
        y0 = start_y if page_no == start_page else 0.0
        y1 = end_y if page_no == end_page and end_y > y0 else float(data["page"].rect.height)
        rect = [
            max(0.0, x0 - pad),
            max(0.0, y0 - pad),
            min(float(data["page"].rect.width), x1 + pad),
            min(float(data["page"].rect.height), y1 + pad),
        ]
        if rect[2] > rect[0] + 2 and rect[3] > rect[1] + 2:
            segments.append({"page": page_no, "bounds": rect})
    return segments

def _render_segments(doc, segments, asset_dir: Path, prefix: str, dpi: int):
    fitz = _fitz()
    scale = dpi / 72.0
    assets = []
    for idx, segment in enumerate(segments, 1):
        rect = fitz.Rect(*segment["bounds"])
        pix = doc[segment["page"] - 1].get_pixmap(
            matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False
        )
        data = pix.tobytes("png")
        digest = hashlib.sha256(data).hexdigest()
        rel = Path(prefix) / f"page-{segment['page']:03d}-{idx:02d}-{digest[:12]}.png"
        path = asset_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        assets.append({
            "kind": prefix.split("/")[0],
            "page": segment["page"],
            "bounds": [round(v, 2) for v in segment["bounds"]],
            "render_dpi": dpi,
            "mime_type": "image/png",
            "object_key": str(rel).replace("\\", "/"),
            "path": str(path),
            "sha256": digest,
            "width_px": pix.width,
            "height_px": pix.height,
        })
    return assets

def _segment_text(doc, segments):
    fitz = _fitz()
    return "\n".join(
        doc[s["page"] - 1].get_text("text", clip=fitz.Rect(*s["bounds"])) or ""
        for s in segments
    )

def _classify_question(text):
    return "MCQ" if len(OPTION_RE.findall(text)) >= 4 else "NUMERICAL"

def _answer_from_text(text):
    m = ANSWER_RE.search(text)
    if not m:
        return None
    raw = next((g for g in m.groups() if g), None)
    if raw is None:
        return None
    raw = raw.upper()
    return {"1": "A", "2": "B", "3": "C", "4": "D"}.get(raw, raw)

def _subject_headings(page_data):
    found = []
    for page_no, data in enumerate(page_data, 1):
        for line in data["lines"]:
            m = SUBJECT_RE.fullmatch(line["text"])
            if m:
                value = m.group(1).title()
                if value == "Maths":
                    value = "Mathematics"
                found.append((page_no, value))
    return found

def extract(config, asset_dir: Path):
    fitz = _fitz()
    doc = fitz.open(config.source_pdf)
    page_count = len(doc)
    start, end = config.page_range
    if start < 1 or end > page_count:
        doc.close()
        raise ValueError(f"Configured page_range {config.page_range} is outside PDF page count {page_count}")

    page_data = []
    for page_no in range(start, end + 1):
        page = doc[page_no - 1]
        lines = _line_records(page)
        page_data.append({"page": page, "lines": lines, "columns": _page_columns(page, lines)})

    expected = list(config.expected_question_numbers)
    starts = _question_starts(page_data)
    if len(starts) != len(expected):
        diagnostic = [
            {
                "page": item["page"],
                "column": item["column"],
                "number": item["number"],
                "x0": round(item["x0"], 2),
                "y0": round(item["y0"], 2),
                "text": item["text"],
            }
            for item in starts
        ]
        print("QUESTION_HEADER_DIAGNOSTIC=" + repr(diagnostic))
        doc.close()
        raise ValueError(f"Question header count mismatch: expected {len(expected)}, found {len(starts)}")

    headings = [s for _, s in _subject_headings(page_data)]
    for subject in config.subject_order:
        if subject not in headings:
            doc.close()
            raise ValueError(f"Missing source subject heading: {subject}")

    solution_starts = _solution_starts(page_data) if config.source_has_solutions else []
    if config.source_has_solutions and len(solution_starts) != len(expected):
        doc.close()
        raise ValueError(f"Solution header count mismatch: expected {len(expected)}, found {len(solution_starts)}")

    source_hash = sha256_file(config.source_pdf)
    questions = []
    assets = []
    extraction_issues = []

    for idx, expected_key in enumerate(expected):
        subject, number_text = expected_key.split(":", 1)
        expected_number = int(number_text)
        q_start = starts[idx]
        if q_start["number"] != expected_number:
            extraction_issues.append(
                Issue("SOURCE_QUESTION_NUMBER_MISMATCH",
                      f"Expected source number {expected_number}, found {q_start['number']} at position {idx + 1}")
            )

        q_next = starts[idx + 1] if idx + 1 < len(starts) else None
        q_segments = _segments_for_item(q_start, q_next, page_data, page_count)
        q_assets = _render_segments(
            doc, q_segments, asset_dir,
            f"question/{subject.lower()}/q-{expected_number:02d}", config.render_dpi
        )
        assets.extend(q_assets)

        sol_assets = []
        answer = None
        sol_start_page = None
        if config.source_has_solutions:
            s_start = solution_starts[idx]
            s_next = solution_starts[idx + 1] if idx + 1 < len(solution_starts) else None
            s_segments = _segments_for_item(s_start, s_next, page_data, page_count)
            sol_assets = _render_segments(
                doc, s_segments, asset_dir,
                f"solution/{subject.lower()}/q-{expected_number:02d}", config.render_dpi
            )
            assets.extend(sol_assets)
            answer = _answer_from_text(_segment_text(doc, s_segments))
            sol_start_page = s_start["page"]

        region_text = _segment_text(doc, q_segments)
        q_pages = sorted({a["page"] for a in q_assets})
        q_bounds = q_assets[0]["bounds"] if q_assets else [0.0, 0.0, 0.0, 0.0]
        qid = f"{source_hash[:16]}-{safe_name(subject)}-q-{expected_number:02d}"

        questions.append(Question(
            id=qid,
            source_question_number=expected_number,
            text="",
            options={"A":"A","B":"B","C":"C","D":"D"},
            answer=answer,
            pages=q_pages,
            bounds=q_bounds,
            provenance={
                "source_sha256": source_hash,
                "source_document": config.source_pdf.name,
                "mode": "source_pdf_render",
                "question_assets": q_assets,
                "source_question_header_page": q_start["page"],
            },
            assets=q_assets,
            solution={
                "mode": "source_pdf_image",
                "assets": sol_assets,
                "pages": sorted({a["page"] for a in sol_assets}),
                "source_solution_header_page": sol_start_page,
            } if config.source_has_solutions else None,
            subject=subject,
            question_type=_classify_question(region_text),
            solution_assets=sol_assets,
        ))

    doc.close()
    return questions, assets, extraction_issues, page_count
