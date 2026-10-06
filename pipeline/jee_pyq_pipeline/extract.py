"""Image-first extraction: PDF regions become the question and solution content."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Any

from .models import Issue, Question
from .util import normalize_line, safe_name, sha256_file

QUESTION_RE = re.compile(
    r"^(?:question\s*(?:no\.?|number|#)?\s*|q\.?\s*)?([0-9]{1,2})\s*(?:[:.)\-]\s*|$)",
    re.I,
)
SUBJECT_RE = re.compile(r"^(Physics|Chemistry|Mathematics|Maths)$", re.I)
SOLUTION_SECTION_RE = re.compile(
    r"^(?:detailed\s+)?(?:solutions?|answers?\s+and\s+solutions?|answer\s+key)\b", re.I
)
SOLUTION_Q_RE = re.compile(
    r"^(?:solution\s*(?:for|of)?\s*)?(?:question\s*|ques\.?\s*|q\.?\s*)([0-9]{1,2})\b"
    r"|^solution\s*[:#\-]?\s*([0-9]{1,2})\b",
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

def _line_records(page):
    words = page.get_text("words")
    if not words:
        try:
            tp = page.get_textpage_ocr(language="eng", dpi=250, full=True)
            words = page.get_text("words", textpage=tp)
        except Exception as exc:
            raise RuntimeError(f"Cannot read page {page.number + 1}: {exc}") from exc
    if not words:
        return []

    words = sorted(words, key=lambda w: (float(w[1]), float(w[0])))
    lines = []
    current = []
    current_y = None
    for word in words:
        y = float(word[1])
        if current and abs(y - current_y) > 3.5:
            lines.append(_make_line(current))
            current = []
        current.append(word)
        current_y = y
    if current:
        lines.append(_make_line(current))
    return lines

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
    left_lines = [l for l in lines if l["x0"] < width * 0.48]
    right_lines = [l for l in lines if l["x0"] > width * 0.52]
    if not left_lines or not right_lines:
        return [(0.0, width)]
    left_max = max(l["x1"] for l in left_lines)
    right_min = min(l["x0"] for l in right_lines)
    if right_min - left_max < width * 0.08:
        return [(0.0, width)]
    mid = (left_max + right_min) / 2.0
    return [(0.0, mid), (mid, width)]

def _question_starts(page_data):
    starts = []
    for page_no, data in enumerate(page_data, 1):
        columns = data["columns"]
        for line in data["lines"]:
            if SOLUTION_SECTION_RE.match(line["text"]):
                break
            m = QUESTION_RE.match(line["text"])
            if not m:
                continue
            number = int(m.group(1))
            if not 1 <= number <= 25:
                continue
            column = 0
            if len(columns) == 2 and line["x0"] >= columns[1][0]:
                column = 1
            starts.append({"page": page_no, "number": number, "column": column, **line})
    starts.sort(key=lambda x: (x["page"], x["column"], x["y0"], x["x0"]))
    return starts

def _solution_starts(page_data):
    found = []
    solution_seen = False
    for page_no, data in enumerate(page_data, 1):
        for line in data["lines"]:
            if SOLUTION_SECTION_RE.match(line["text"]):
                solution_seen = True
                continue
            if not solution_seen:
                continue
            m = SOLUTION_Q_RE.match(line["text"])
            if not m:
                continue
            number = next((int(g) for g in m.groups() if g), None)
            if not number or not 1 <= number <= 25:
                continue
            column = 0
            if len(data["columns"]) == 2 and line["x0"] >= data["columns"][1][0]:
                column = 1
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
