from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_START = re.compile(r'^(?:Q(?:uestion)?\.?\s*)?(\d{1,3})\s*[.):](?:\s|$)', re.I)
OPTION_LABEL = re.compile(r'(?<![\w.])(?:\(\s*([A-D]|[1-4])\s*\)|([A-D]|[1-4])\s*[.)])(?=\s|$)', re.I)
ANSWER_MARKER = re.compile(r'^\s*(?:answer|ans\s*\.?|correct\s+answer)\s*[:\-]?\s*', re.I)
SOLUTION_MARKER = re.compile(r'^\s*(?:solution|sol\s*\.)(?=\s|[:\-]|$)\s*[:\-]?\s*', re.I)
FIGURE = re.compile(r'\b(fig(?:ure)?|diagram|graph|circuit|plot|schematic)\b|\b(shown|following)\s+(?:below|above|is|are)\b', re.I)
SUBJECTS = {
    'PHYSICS':'Physics',
    'CHEMISTRY':'Chemistry',
    'MATHEMATICS':'Mathematics',
    'MATHS':'Mathematics',
}

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError('PyMuPDF is required for layout-aware extraction; refusing text-only fallback') from error


def _page_image_info(page) -> list[dict]:
    """Return only image placements actually painted on this page."""
    try:
        return page.get_image_info(xrefs=True)
    except (AttributeError, TypeError):
        return []


def _ocr_dpi(page, image_info: list[dict] | None = None) -> int:
    """Choose OCR DPI from the actual embedded full-page scan, without decoding unused XObjects."""
    if image_info is None:
        image_info = _page_image_info(page)
    page_width, page_height = float(page.rect.width), float(page.rect.height)
    estimates = []
    for image in image_info:
        bbox = image.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(v) for v in bbox)
        placed_width, placed_height = x1 - x0, y1 - y0
        if (
            placed_width < page_width * 0.85
            or placed_height < page_height * 0.80
        ):
            continue
        image_width = float(image.get("width") or 0)
        image_height = float(image.get("height") or 0)
        if image_width <= 0 or image_height <= 0:
            continue
        estimates.append(72.0 * min(
            image_width / max(placed_width, 1.0),
            image_height / max(placed_height, 1.0),
        ))
    if not estimates:
        return 200
    return int(max(72, min(250, min(estimates))))


def _clean_ocr_words(words: list[tuple], width: float, height: float) -> list[tuple]:
    """Remove long scan rules and border artefacts that can break column detection."""
    cleaned = []
    rule_tokens = {"|", "¦", "‖", "_", "—", "/", "\\", "]", "["}
    for word in words:
        if len(word) < 5:
            continue
        x0, y0, x1, y1, raw_text = word[:5]
        token = str(raw_text).strip()
        box_width = max(0.0, float(x1) - float(x0))
        box_height = max(0.0, float(y1) - float(y0))
        at_edge = (
            float(x0) <= width * 0.012 or float(x1) >= width * 0.988
            or float(y0) <= height * 0.008 or float(y1) >= height * 0.992
        )
        center_x = (float(x0) + float(x1)) / 2.0
        tall_narrow_rule = (
            box_width <= max(12.0, width * 0.006)
            and box_height >= height * 0.20
            and token in rule_tokens | {"I", "l", "!", "1"}
            and (at_edge or width * 0.35 <= center_x <= width * 0.65)
        )
        if tall_narrow_rule:
            continue
        if box_width >= width * 0.80 and len(token) <= 5:
            continue
        if token in rule_tokens and box_width <= 12.0 and box_height >= height * 0.30:
            continue
        if token in {"I", "l", "!", '"', "'", "~"} and at_edge and box_height > 20:
            continue
        cleaned.append(word)
    return cleaned


def _join_word_tokens(words: list[tuple]) -> str:
    """Join OCR tokens without breaking punctuation-only question/option markers."""
    value = ""
    for word in words:
        token = str(word[4]).strip()
        if not token:
            continue
        if not value:
            value = token
        elif token[0] in ".,;:!?%)]}»’”\\"'" or value[-1] in "([{\\\"'‘“":
            value += token
        else:
            value += " " + token
    return value


def _word_rows(words: list[tuple]) -> list[list[tuple]]:
    """Group word boxes into horizontal text lines using adaptive vertical tolerance."""
    if not words:
        return []
    heights = sorted(
        max(1.0, float(w[3]) - float(w[1]))
        for w in words if len(w) >= 4 and float(w[3]) > float(w[1])
    )
    median_height = heights[len(heights) // 2] if heights else 8.0
    tolerance = max(4.0, min(14.0, median_height * 0.25))
    ordered = sorted(words, key=lambda w: (float(w[1]), float(w[0])))
    rows = []
    for word in ordered:
        if not rows:
            rows.append([word])
            continue
        anchor_values = sorted(float(item[1]) for item in rows[-1])
        anchor = anchor_values[len(anchor_values) // 2]
        if abs(float(word[1]) - anchor) > tolerance:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: float(w[0])) for row in rows]


def _column_split_x(words: list[tuple], width: float) -> float | None:
    """Find a two-column gutter efficiently; examine only the strongest central gaps."""
    if not words or width <= 0:
        return None
    page_height = max(float(w[3]) for w in words)
    body = [
        w for w in words
        if float(w[1]) >= page_height * 0.12
        and float(w[3]) <= page_height * 0.96
        and float(w[2]) - float(w[0]) < width * 0.80
    ]
    ordered = sorted(body, key=lambda w: float(w[0]))
    gaps = []
    for idx in range(len(ordered) - 1):
        gap = float(ordered[idx + 1][0]) - float(ordered[idx][2])
        cut = (float(ordered[idx][2]) + float(ordered[idx + 1][0])) / 2.0
        # This source uses a near-centre gutter. A narrow range also avoids cutting
        # through long formula lines or wide question stems within either column.
        if gap >= width * 0.015 and width * 0.40 < cut < width * 0.60:
            gaps.append((gap, cut))
    # Testing every central token gap by re-grouping all page words is quadratic on
    # scan-heavy pages. A small shortlist captures the actual gutter without that cost.
    shortlist = sorted(gaps, key=lambda item: item[0], reverse=True)[:6]
    candidates = []
    for gap, cut in shortlist:
        crossing = sum(1 for w in body if float(w[0]) < cut < float(w[2]))
        if crossing > max(3, len(body) * 0.03):
            continue
        left = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 < cut]
        right = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 >= cut]
        if len(left) < 8 or len(right) < 8:
            continue
        left_headers = sum(
            1 for row in _word_rows(left)
            if _question_start(_join_word_tokens(row).strip())[1] is not None
        )
        right_headers = sum(
            1 for row in _word_rows(right)
            if _question_start(_join_word_tokens(row).strip())[1] is not None
        )
        headers_on_both_sides = bool(left_headers and right_headers)
        left_count, right_count = len(left), len(right)
        balance = min(left_count, right_count) / max(left_count, right_count, 1)
        # OCR can miss a printed question number. A strong central gutter plus
        # substantial text on both sides is still better evidence than allowing
        # same-height rows from two columns to merge into one question.
        if not headers_on_both_sides and (gap < width * 0.025 or balance < 0.20):
            continue
        score = gap - crossing * 5.0 - abs(cut - width * 0.5) * 0.02
        if headers_on_both_sides:
            score += width * 0.01
        candidates.append((score, cut))
    return max(candidates, default=(0.0, None), key=lambda item: item[0])[1]

def _page_words(page, page_no: int = 1, image_info: list[dict] | None = None):
    """Return word coordinates, applying source-resolution OCR when the page is scanned."""
    words = page.get_text("words")
    if words:
        return words, False
    try:
        textpage = page.get_textpage_ocr(language="eng", dpi=_ocr_dpi(page, image_info), full=True)
        words = page.get_text("words", textpage=textpage)
    except Exception as error:
        raise RuntimeError(
            f"OCR required on source page {page_no} but unavailable; refusing placeholder output"
        ) from error
    if not words:
        raise RuntimeError(
            f"OCR produced no words on source page {page_no}; refusing empty/placeholder output"
        )
    return _clean_ocr_words(words, float(page.rect.width), float(page.rect.height)), True


def _question_start(text: str):
    """Return (regex_match, integer question number) for supported printed headers."""
    match = QUESTION_START.match(text)
    return match, (int(match.group(1)) if match else None)


def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    """Group text rows and return complete left column before complete right column."""
    if not words:
        return []
    split_x = _column_split_x(words, width)
    if split_x is None:
        return _word_rows(words)
    left = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 < split_x]
    right = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 >= split_x]
    # Column order is deliberate: processing each entire column prevents Q1 and Q3,
    # printed at the same y coordinate, from being fused into one question.
    return _word_rows(left) + _word_rows(right)

def _assets(page, page_no:int, asset_dir:Path, source_hash:str,
            image_info:list[dict]|None=None)->list[Asset]:
    """Extract only genuinely placed, bounded images; skip full-page scans before decoding."""
    found=[]
    if image_info is None:
        image_info=_page_image_info(page)
    for n,item in enumerate(image_info):
        bbox=item.get('bbox')
        if not bbox or len(bbox)!=4:
            continue
        rect=[float(v) for v in bbox]
        width=rect[2]-rect[0]
        height=rect[3]-rect[1]
        # A full-page raster is original-page context, not a question figure. Reject it
        # before extract_image(): scans can contain many unplaced XObject references.
        if width >= float(page.rect.width)*0.85 and height >= float(page.rect.height)*0.80:
            continue
        xref=int(item.get('xref') or 0)
        if xref <= 0:
            continue
        payload=page.parent.extract_image(xref)
        if not payload:
            continue
        data=payload['image']
        digest=hashlib.sha256(data).hexdigest()
        ext=payload.get('ext','bin')
        object_key=f'{source_hash[:16]}/page-{page_no}/image-{n}-{digest[:16]}.{ext}'
        file=asset_dir/object_key
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(data)
        bounds=[round(v,2) for v in rect]
        found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found


def _rect_union(rects: list[list[float]]) -> list[float] | None:
    if not rects:
        return None
    return [
        min(r[0] for r in rects), min(r[1] for r in rects),
        max(r[2] for r in rects), max(r[3] for r in rects),
    ]

def _x_overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    denom = max(1e-6, min(a[2] - a[0], b[2] - b[0]))
    return overlap / denom

def _crop_question_figures(config, block: dict, qrows: list[tuple[int, str, list[float]]],
                           blocks: list[dict], block_index: int, asset_dir: Path,
                           source_hash: str) -> list[Asset]:
    """Render only bounded, nearby figure/diagram regions; never attach a full PDF page."""
    fitz = _fitz()
    cropped: list[Asset] = []
    doc = fitz.open(config.source_pdf)
    try:
        for page_no in sorted({r[0] for r in qrows}):
            if page_no < 1 or page_no > len(doc):
                continue
            page = doc[page_no - 1]
            page_rows = [r[2] for r in qrows if r[0] == page_no]
            own = _rect_union(page_rows)
            if own is None:
                continue

            own_cx = (own[0] + own[2]) / 2.0
            prev_bottom = 0.0
            next_top = float(page.rect.y1)
            # Limit candidate graphics to the same column and this question's vertical band.
            for other_index, other in enumerate(blocks):
                if other_index == block_index or page_no not in other.get("pages", set()):
                    continue
                obox = _rect_union([r[2] for r in other["rows"] if r[0] == page_no])
                if obox is None:
                    continue
                ocx = (obox[0] + obox[2]) / 2.0
                same_column = (
                    _x_overlap_ratio(own, obox) >= 0.08
                    or abs(own_cx - ocx) <= float(page.rect.width) * 0.30
                )
                if not same_column:
                    continue
                if obox[3] <= own[1] and obox[3] > prev_bottom:
                    prev_bottom = obox[3]
                if obox[1] >= own[3] and obox[1] < next_top:
                    next_top = obox[1]

            band_top = max(0.0, own[1] - 55.0, prev_bottom + 3.0 if prev_bottom else 0.0)
            band_bottom = min(float(page.rect.y1), next_top - 3.0, own[3] + 125.0)
            if band_bottom <= band_top:
                continue

            graphics: list[list[float]] = []
            page_dict = page.get_text("dict")
            for item in page_dict.get("blocks", []):
                if item.get("type") != 1 or "bbox" not in item:
                    continue
                b = [float(v) for v in item["bbox"]]
                graphics.append(b)

            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if rect is None:
                    continue
                b = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
                if b[2] - b[0] >= 2.0 and b[3] - b[1] >= 2.0:
                    graphics.append(b)

            candidates = []
            for g in graphics:
                width, height = g[2] - g[0], g[3] - g[1]
                if width <= 0 or height <= 0:
                    continue
                # Never allow a whole-page screenshot/scan to become a question image.
                if width >= float(page.rect.width) * 0.85 and height >= float(page.rect.height) * 0.80:
                    continue
                cy = (g[1] + g[3]) / 2.0
                if not (band_top <= cy <= band_bottom):
                    continue
                gcx = (g[0] + g[2]) / 2.0
                if abs(gcx - own_cx) > float(page.rect.width) * 0.34 and _x_overlap_ratio(g, own) < 0.05:
                    continue
                if width * height < 18.0 and max(width, height) < 14.0:
                    continue
                candidates.append(g)

            figure_bounds = _rect_union(candidates)
            if figure_bounds is None:
                continue
            pad = 4.0
            crop_rect = fitz.Rect(
                figure_bounds[0] - pad, figure_bounds[1] - pad,
                figure_bounds[2] + pad, figure_bounds[3] + pad,
            ) & page.rect
            if crop_rect.is_empty or crop_rect.width <= 0 or crop_rect.height <= 0:
                continue
            if crop_rect.width >= float(page.rect.width) * 0.85 and crop_rect.height >= float(page.rect.height) * 0.80:
                continue

            pix = page.get_pixmap(clip=crop_rect, dpi=240, alpha=False)
            payload = pix.tobytes("png")
            digest = hashlib.sha256(payload).hexdigest()
            slug = re.sub(r"[^a-z0-9-]+", "-", str(block["subject"]).lower()).strip("-")
            object_key = (
                f"{source_hash[:16]}/page-{page_no}/"
                f"q-{slug}-{int(block['number']):03d}-figure-{digest[:12]}.png"
            )
            file_path = asset_dir / object_key
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not file_path.exists():
                file_path.write_bytes(payload)
            bounds = [round(crop_rect.x0, 2), round(crop_rect.y0, 2),
                      round(crop_rect.x1, 2), round(crop_rect.y1, 2)]
            cropped.append(Asset(
                object_key, page_no, bounds, digest,
                str(file_path.relative_to(asset_dir.parent)),
            ))
    finally:
        doc.close()
    return cropped


def _crop_scan_regions(doc, block:dict, rows:list[tuple[int,str,list[float]]],
                       blocks:list[dict], block_index:int, asset_dir:Path,
                       source_hash:str, kind:str, dpi_by_page:dict[int,int])->list[Asset]:
    """Render bounded question/source-solution crops; keep column continuations separate."""
    fitz = _fitz()
    cropped = []
    for page_no in sorted({row[0] for row in rows}):
        if page_no < 1 or page_no > len(doc):
            continue
        page = doc[page_no - 1]
        page_width, page_height = float(page.rect.width), float(page.rect.height)
        midpoint = page_width * 0.5
        page_rows = [row for row in rows if row[0] == page_no]
        answer_rows = [
            row for row in block.get("rows", [])
            if row[0] == page_no and ANSWER_MARKER.match(row[1])
        ]

        def side_of(row):
            center = (float(row[2][0]) + float(row[2][2])) / 2.0
            return "left" if center < midpoint else "right"

        sides = {side_of(row) for row in page_rows}
        for side in sorted(sides):
            own_rows = [row for row in page_rows if side_of(row) == side]
            answer_side = [row for row in answer_rows if side_of(row) == side]
            region_rows = list(own_rows)
            if kind == "solution":
                region_rows.extend(answer_side)
            region_box = _rect_union([row[2] for row in region_rows])
            if region_box is None:
                continue
            center_x = (region_box[0] + region_box[2]) / 2.0

            # Compute horizontal extent from rows on this side only. A solution can
            # continue from the bottom of the left column to the top of the right;
            # joining both extents would create an almost-full-width screenshot.
            column_rows = []
            for other in blocks:
                other_rows = [
                    row for row in other.get("rows", [])
                    if row[0] == page_no and side_of(row) == side
                ]
                other_box = _rect_union([row[2] for row in other_rows])
                if other_box is not None:
                    column_rows.extend(other_rows)
            column_box = _rect_union([row[2] for row in column_rows]) or region_box
            x0 = max(0.0, column_box[0] - 12.0)
            x1 = min(page_width, column_box[2] + 12.0)
            y0 = max(0.0, min(row[2][1] for row in region_rows) - 8.0)
            y1 = min(page_height, max(row[2][3] for row in region_rows) + 8.0)

            if kind == "question" and answer_side:
                answer_top = min(row[2][1] for row in answer_side)
                if answer_top > y0:
                    y1 = min(page_height, max(y1, answer_top - 6.0))
            elif kind == "solution":
                region_bottom = max(row[2][3] for row in region_rows)
                next_top = None
                for other_index, other in enumerate(blocks):
                    if other_index <= block_index:
                        continue
                    other_rows = [
                        row for row in other.get("rows", [])
                        if row[0] == page_no and side_of(row) == side
                    ]
                    other_box = _rect_union([row[2] for row in other_rows])
                    if other_box is None:
                        continue
                    other_top = min(row[2][1] for row in other_rows)
                    if other_top > region_bottom:
                        next_top = other_top if next_top is None else min(next_top, other_top)
                if next_top is not None:
                    y1 = min(page_height, next_top - 6.0)

            if x1 <= x0 or y1 <= y0:
                continue
            crop_rect = fitz.Rect(x0, y0, x1, y1) & page.rect
            if crop_rect.is_empty or crop_rect.width <= 0 or crop_rect.height <= 0:
                continue
            if crop_rect.width >= page_width * 0.85 and crop_rect.height >= page_height * 0.80:
                continue
            dpi = max(72, min(150, int(dpi_by_page.get(page_no, 72))))
            payload = page.get_pixmap(clip=crop_rect, dpi=dpi, alpha=False).tobytes("png")
            digest = hashlib.sha256(payload).hexdigest()
            slug = re.sub(r"[^a-z0-9-]+", "-", str(block["subject"]).lower()).strip("-")
            key = (
                f"{source_hash[:16]}/page-{page_no}/"
                f"q-{slug}-{int(block['number']):03d}-{kind}-{side}-{digest[:12]}.png"
            )
            path = asset_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(payload)
            bounds = [round(crop_rect.x0, 2), round(crop_rect.y0, 2),
                      round(crop_rect.x1, 2), round(crop_rect.y1, 2)]
            cropped.append(Asset(
                key, page_no, bounds, digest, str(path.relative_to(asset_dir.parent))
            ))
    return cropped


def _subject_line(text:str)->str|None:
    t=safe_normalize(text).strip().upper()
    t=re.sub(r'\s+(SECTION|PAPER|SUBJECT)$','',t)
    return SUBJECTS.get(t)


def _split_options(rows:list[tuple[int,str,list[float]]])->tuple[str,dict[str,str]]:
    body=[]
    candidates={}
    current=None
    for _page,text,_bounds in rows:
        matches=list(OPTION_LABEL.finditer(text))
        if not matches:
            if current:
                candidates[current]=safe_normalize(f'{candidates[current]} {text}')
            else:
                body.append(text)
            continue
        prefix=text[:matches[0].start()].strip()
        if prefix:
            if current:
                candidates[current]=safe_normalize(f'{candidates[current]} {prefix}')
            else:
                body.append(prefix)
        for idx,match in enumerate(matches):
            label=match.group(1) or match.group(2)
            current=label
            end=matches[idx+1].start() if idx+1<len(matches) else len(text)
            candidates[label]=safe_normalize(text[match.end():end].strip())
    if set(candidates)==set('ABCD') or set(candidates)==set('1234'):
        return safe_normalize(' '.join(body)),{k:v for k,v in candidates.items() if v.strip()}
    all_text=safe_normalize(' '.join(body+[safe_normalize(t) for _,t,_ in rows if t]))
    return all_text,{}

def _parse_answer(text:str)->str|None:
    # Match a complete numerical token before single-digit MCQ labels, otherwise 42
    # would be incorrectly read as 4.
    token=re.match(r'\s*[\(\[]?\s*(-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?|[A-D])\s*[\)\]]?',text,re.I)
    return token.group(1) if token else None

def _split_source_sections(rows:list[tuple[int,str,list[float]]]):
    qrows=[]
    srows=[]
    answer=None
    answer_count=0
    answer_seen=False
    solution_seen=False
    for page,text,bounds in rows:
        am=ANSWER_MARKER.match(text) if not answer_seen else None
        sm=SOLUTION_MARKER.match(text)
        if am:
            token=_parse_answer(text[am.end():])
            if token:
                answer=token
            answer_count+=1
            answer_seen=True
            if sm:
                solution_seen=True
                suffix=text[sm.end():].strip()
                if suffix:
                    srows.append((page,suffix,bounds))
            continue
        if sm and not solution_seen:
            solution_seen=True
            suffix=text[sm.end():].strip()
            if suffix:
                srows.append((page,suffix,bounds))
            continue
        if solution_seen or answer_seen:
            srows.append((page,text,bounds))
        else:
            qrows.append((page,text,bounds))
    solution_text=safe_normalize(' '.join(t for _,t,_ in srows if t))
    q_text,q_opts=_split_options(qrows)
    if answer_count>1:
        return q_text,q_opts,None,solution_text,qrows,srows,'MULTIPLE_ANSWER_MARKERS'
    return q_text,q_opts,answer,solution_text,qrows,srows,None

def extract(config, asset_dir:Path)->tuple[list[Question],list[Asset],list[Issue],int]:
    fitz=_fitz()
    doc=fitz.open(config.source_pdf)
    page_count=len(doc)
    all_assets=[]
    page_assets={}
    raw=[]
    scan_only_pages=set()
    scan_dpi_by_page={}
    source_hash=sha256_file(config.source_pdf)
    expected=set(config.expected_question_numbers)
    subject_candidates={}
    for key in expected:
        if ':' not in key:
            continue
        subject_name, number_text = key.rsplit(':', 1)
        if number_text.isdigit() and subject_name.strip():
            subject_candidates.setdefault(int(number_text), set()).add(subject_name.strip())
    # An explicitly configured, unique printed-number-to-subject mapping handles
    # source PDFs that number a whole paper consecutively. Ambiguous repeated local
    # numbers (e.g. 1-25 in each subject) are deliberately not mapped.
    expected_subject_by_number={
        number: next(iter(subject_names))
        for number, subject_names in subject_candidates.items()
        if len(subject_names)==1
    }
    current_subject=None
    try:
        for page_no in range(config.page_range[0],config.page_range[1]+1):
            if page_no>page_count:
                return [],[],[Issue('PAGE_RANGE_OUT_OF_BOUNDS',f'Configured page {page_no} does not exist')],page_count
            page=doc[page_no-1]
            page_image_info=_page_image_info(page)
            pa=_assets(page,page_no,asset_dir,source_hash,page_image_info)
            page_assets[page_no]=pa
            all_assets.extend(pa)
            words, used_ocr = _page_words(page,page_no,page_image_info)
            if used_ocr:
                scan_only_pages.add(page_no)
                scan_dpi_by_page[page_no]=_ocr_dpi(page)
            page_rows=[]
            for row in _lines(words, page.rect.width):
                text=_join_word_tokens(row).strip()
                if not text:
                    continue
                subject=_subject_line(text)
                bounds=[min(w[0] for w in row),min(w[1] for w in row),max(w[2] for w in row),max(w[3] for w in row)]
                page_rows.append((text,bounds,subject))
            question_y = [
                bounds[1] for text,bounds,_subject in page_rows
                if _question_start(text)[1] is not None
            ]
            headings = sorted(
                [(bounds[1],subject) for _text,bounds,subject in page_rows if subject],
                key=lambda item:item[0]
            )
            # Subject names may be centered in the right column. Apply a heading
            # above the first question to the entire page before reading either column.
            if headings and (not question_y or headings[0][0] <= min(question_y)):
                current_subject=headings[0][1]
            for text,bounds,subject in page_rows:
                if subject:
                    current_subject=subject
                raw.append((page_no,text,bounds,current_subject))
    finally:
        doc.close()

    blocks=[]
    current=None
    for page,text,bounds,subject in raw:
        match, number = _question_start(text)
        if number is not None and number in expected_subject_by_number:
            subject = expected_subject_by_number[number]
        if number is not None and current is None and subject is None:
            continue
        if number is not None and subject is not None:
            if current:
                blocks.append(current)
            current={'number':number,'subject':subject,'rows':[(page,text[match.end():].strip(),bounds)],'pages':{page}}
            continue
        if current:
            current['rows'].append((page,text,bounds))
            current['pages'].add(page)
    if current:
        blocks.append(current)

    questions=[]
    issues=[]
    crop_doc = fitz.open(config.source_pdf) if scan_only_pages else None
    for block_index, block in enumerate(blocks):
        q_text,q_opts,answer,solution_text,qrows,srows,split_error=_split_source_sections(block['rows'])
        if split_error:
            issues.append(Issue('MULTIPLE_ANSWER_MARKERS',f'Question {block["subject"]}:{block["number"]} has multiple answer markers'))
        qpages=sorted({r[0] for r in qrows})
        spages=sorted({r[0] for r in srows})
        if not qpages:
            qpages=sorted(block['pages'])
        if qrows:
            q_bounds=[
                min(r[2][0] for r in qrows),min(r[2][1] for r in qrows),
                max(r[2][2] for r in qrows),max(r[2][3] for r in qrows),
            ]
        else:
            issues.append(Issue(
                'EMPTY_QUESTION_TEXT',
                f'Question {block["subject"]}:{block["number"]} has no question-region text before the answer/solution section',
            ))
            fallback_bounds = _rect_union([r[2] for r in block['rows']])
            q_bounds = fallback_bounds or [0.0, 0.0, 1.0, 1.0]
        s_bounds=None
        if srows:
            s_bounds=[
                min(r[2][0] for r in srows),min(r[2][1] for r in srows),
                max(r[2][2] for r in srows),max(r[2][3] for r in srows),
            ]
        qassets=[]
        sassets=[]
        for asset in all_assets:
            if asset.page in qpages:
                ax=asset.bounds
                bx=q_bounds
                pad=16.0
                test=[bx[0]-pad,bx[1]-pad,bx[2]+pad,bx[3]+pad]
                if not (ax[2]<test[0] or ax[0]>test[2] or ax[3]<test[1] or ax[1]>test[3]):
                    qassets.append(asset)
            if s_bounds and asset.page in spages:
                pad=40.0
                test=[s_bounds[0]-pad,s_bounds[1]-pad,s_bounds[2]+pad,s_bounds[3]+pad]
                ax=asset.bounds
                if not (ax[2]<test[0] or ax[0]>test[2] or ax[3]<test[1] or ax[1]>test[3]):
                    sassets.append(asset)
        qassets={ (a.object_key,tuple(a.bounds)):a for a in qassets }.values()
        sassets={ (a.object_key,tuple(a.bounds)):a for a in sassets }.values()
        qassets=list(qassets)
        sassets=list(sassets)
        requires_figure=bool(FIGURE.search(q_text))
        if requires_figure and not any(page_no in scan_only_pages for page_no in qpages):
            figure_crops=_crop_question_figures(config,block,qrows,blocks,block_index,asset_dir,source_hash)
            if figure_crops:
                qassets=figure_crops
                all_assets.extend(figure_crops)
        if crop_doc is not None:
            # A source scan is context, not a question image. Give every record a
            # bounded question crop and a distinct source-solution crop when present.
            question_crops=_crop_scan_regions(
                crop_doc,block,qrows,blocks,block_index,asset_dir,source_hash,
                "question",scan_dpi_by_page
            )
            solution_crops=_crop_scan_regions(
                crop_doc,block,srows,blocks,block_index,asset_dir,source_hash,
                "solution",scan_dpi_by_page
            ) if srows else []
            if question_crops:
                qassets.extend(question_crops)
                all_assets.extend(question_crops)
            if solution_crops:
                sassets.extend(solution_crops)
                all_assets.extend(solution_crops)
        # MCQ must have four parsed choices; an absent answer is not guessed.
        if len(q_opts)==4 and set(q_opts) in (set('ABCD'),set('1234')):
            question_type='MCQ'
        elif not q_opts and answer is not None and re.fullmatch(r'-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?',str(answer).strip()):
            question_type='NUMERICAL'
        else:
            question_type='UNKNOWN'
        dropped=bool(re.search(r'\b(?:question\s+(?:has\s+been\s+)?dropped|dropped\s+(?:question|by\s+NTA|from\s+evaluation)|question\s+is\s+dropped)\b',q_text+' '+solution_text,re.I))
        qid=f'{source_hash[:16]}-{block["subject"].lower()}-q-{block["number"]:03d}'
        solution=None
        if solution_text:
            solution={'text':solution_text,'pages':spages,'source_reference':{
                'source_document':config.source_pdf.name,
                'source_sha256':source_hash,
            }}
        questions.append(Question(
            qid,block['number'],q_text,q_opts,answer,qpages,q_bounds,
            {'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release},
            qassets,solution,requires_figure,'Dropped' if dropped else 'VALIDATED',[],block['subject'],None,question_type,sassets
        ))
    if crop_doc is not None:
        crop_doc.close()
    return questions,all_assets,issues,page_count
