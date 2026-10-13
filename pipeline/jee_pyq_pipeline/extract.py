from __future__ import annotations
import csv
import hashlib
import io
import re
import subprocess
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_START = re.compile(r'^(?:Q(?:uestion)?\.?\s*)?(\d{1,3})\s*[.):,](?:\s|$)', re.I)
OPTION_LABEL = re.compile(r'(?:\(\s*([A-D]|[1-4])\s*\)|(?<![\w.])([A-D]|[1-4])\s*[.)](?=\s|$))', re.I)
ANSWER_MARKER = re.compile(r'^\s*[\]\[|!.,;:_\-]*\s*(?:(?:[Il]|\d{1,2})\s+(?=ans(?:wer)?\s*\.?\s*(?:[:\-]|\([^)]{1,12}\)|[-+]?\d))\s*)?(?:answer|ans\s*\.?|correct\s+answer)\s*[:\-]?\s*', re.I)
SOLUTION_MARKER = re.compile(r'^\s*(?:solution|sol\s*[.,;])(?=\s|[:\-]|$)\s*[:\-]?\s*', re.I)
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


def _has_center_divider(page) -> bool:
    """Detect a long, dark vertical separator near the midpoint of a scanned page."""
    try:
        pix = page.get_pixmap(dpi=72, alpha=False)
    except Exception:
        return False
    width, height, channels = int(pix.width), int(pix.height), int(pix.n)
    if width < 100 or height < 100 or channels < 3:
        return False
    samples = pix.samples
    midpoint = width // 2
    radius = max(3, int(width * 0.006))
    y0, y1 = int(height * 0.12), int(height * 0.95)
    if y1 <= y0:
        return False
    required_fraction = 0.35
    required_run = int(height * 0.25)
    for x in range(max(0, midpoint - radius), min(width, midpoint + radius + 1)):
        dark_count = 0
        longest_run = run = gap = 0
        for y in range(y0, y1):
            offset = (y * width + x) * channels
            is_dark = (samples[offset] + samples[offset + 1] + samples[offset + 2]) / 3 < 170
            if is_dark:
                dark_count += 1
                run += 1
                gap = 0
                longest_run = max(longest_run, run)
            else:
                gap += 1
                if gap > 2:
                    run = 0
                    gap = 0
        if dark_count / (y1 - y0) >= required_fraction and longest_run >= required_run:
            return True
    return False


def _join_word_tokens(words: list[tuple]) -> str:
    """Join OCR tokens without breaking punctuation-only question/option markers."""
    value = ""
    for word in words:
        token = str(word[4]).strip()
        if not token:
            continue
        if not value:
            value = token
        elif token[0] in ".,;:!?%)]}»’”" or value[-1] in "([{":
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

    # Prefer the true page midpoint when both halves independently contain
    # printed question headers and very few text boxes cross the central gutter.
    # This avoids selecting a large accidental whitespace gap inside a column.
    midpoint = width * 0.5
    left_mid = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 < midpoint]
    right_mid = [w for w in words if (float(w[0]) + float(w[2])) / 2.0 >= midpoint]
    left_header_count = sum(
        1 for row in _word_rows(left_mid)
        if _question_start(_join_word_tokens(row).strip())[1] is not None
    )
    right_header_count = sum(
        1 for row in _word_rows(right_mid)
        if _question_start(_join_word_tokens(row).strip())[1] is not None
    )
    central_crossings = sum(
        1 for w in body
        if float(w[0]) < midpoint + width * 0.006
        and float(w[2]) > midpoint - width * 0.006
        # Tiny OCR boxes are often fragments of the scanned divider, not prose
        # crossing the gutter. Count only substantial text boxes as crossings.
        and float(w[2]) - float(w[0]) > max(12.0, width * 0.006)
    )
    if (
        left_header_count and right_header_count
        and central_crossings <= max(6, len(body) * 0.04)
    ):
        return midpoint

    # Some scanned equations destroy the printed header token boundaries even when
    # the page clearly has two columns. As a second, geometry-only fallback, require
    # dense text on both sides, a genuinely wide center gutter, and few boxes crossing
    # the gutter. Do not split balanced full-width prose when the center gap is narrow.
    left_body = [w for w in body if (float(w[0]) + float(w[2])) / 2.0 < midpoint]
    right_body = [w for w in body if (float(w[0]) + float(w[2])) / 2.0 >= midpoint]
    left_extent = max((float(w[2]) for w in left_body), default=midpoint)
    right_extent = min((float(w[0]) for w in right_body), default=midpoint)
    gutter_width = right_extent - left_extent
    word_balance = min(len(left_body), len(right_body)) / max(len(left_body), len(right_body), 1)
    if (
        len(left_body) >= 8 and len(right_body) >= 8
        and word_balance >= 0.20
        and gutter_width >= width * 0.015
        and central_crossings <= max(6, len(body) * 0.04)
    ):
        return midpoint

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

def _ocr_clip_words(page, page_no: int, clip, dpi: int) -> list[tuple]:
    """OCR one source-page region, retrying a contaminated TSV block in sparse-column mode."""
    fitz = _fitz()
    rect = fitz.Rect(clip)
    pix = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
    sx = rect.width / max(float(pix.width), 1.0)
    sy = rect.height / max(float(pix.height), 1.0)
    png = pix.tobytes("png")

    def run_tesseract(psm: str) -> bytes:
        try:
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", psm, "tsv"],
                input=png,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=120,
            )
        except Exception as error:
            raise RuntimeError(
                f"Tesseract region OCR failed on source page {page_no} (PSM {psm})"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
            raise RuntimeError(
                f"Tesseract region OCR failed on source page {page_no} (PSM {psm}): {detail}"
            )
        return result.stdout

    def parse_tsv(payload: bytes) -> tuple[list[tuple], bool]:
        words = []
        contaminated = False
        reader = csv.DictReader(
            io.StringIO(payload.decode("utf-8", errors="replace")),
            delimiter="\t",
        )
        for row in reader:
            try:
                if int(row.get("level", "0")) != 5:
                    continue
                token = (row.get("text") or "").strip()
                if not token:
                    continue
                # Tesseract 5.5 can occasionally emit a whole run of TSV records
                # inside one quoted word's text field on equation-heavy scan pages.
                # Treat that as corrupted output, not as question text.
                if any(char in token for char in ("\t", "\n", "\r")):
                    contaminated = True
                    continue
                left, top = int(row["left"]), int(row["top"])
                width, height = int(row["width"]), int(row["height"])
                if width <= 0 or height <= 0:
                    continue
                words.append((
                    rect.x0 + left * sx, rect.y0 + top * sy,
                    rect.x0 + (left + width) * sx, rect.y0 + (top + height) * sy,
                    token, int(row.get("block_num", 0)), int(row.get("line_num", 0)),
                    int(row.get("word_num", 0)),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return words, contaminated

    # PSM 6 is the normal column mode; PSM 4 is the first fallback. The
    # page-19 source diagnostic showed both modes returning a contaminated TSV
    # field for the left column, while PSM 11 returned clean word rows. Retry
    # in sparse-text mode before failing closed; never salvage contaminated text.
    words, contaminated = parse_tsv(run_tesseract("6"))
    if contaminated or not words:
        words, contaminated = parse_tsv(run_tesseract("4"))
    if contaminated or not words:
        words, contaminated = parse_tsv(run_tesseract("11"))
    if contaminated:
        raise RuntimeError(
            f"Tesseract returned corrupted TSV in PSM 6, 4, and 11 on source page {page_no}; refusing contaminated text"
        )
    if not words:
        raise RuntimeError(f"Tesseract produced no word boxes on source page {page_no}")
    return words


def _page_words(page, page_no: int = 1, image_info: list[dict] | None = None):
    """Return source-grounded word coordinates; isolate scanned columns before OCR."""
    words = page.get_text("words")
    if words:
        return words, False
    try:
        dpi = _ocr_dpi(page, image_info)
        if _has_center_divider(page):
            # This source uses two side-by-side question/solution columns. Full-page
            # OCR merges their baselines and frequently loses option labels/Ans.
            # OCR each side as an independent text block; preserve original PDF boxes.
            width = float(page.rect.width)
            height = float(page.rect.height)
            midpoint = float(page.rect.x0) + width * 0.5
            margin = max(2.0, width * 0.006)
            left_clip = (float(page.rect.x0), float(page.rect.y0), midpoint - margin, float(page.rect.y1))
            right_clip = (midpoint + margin, float(page.rect.y0), float(page.rect.x1), float(page.rect.y1))
            words = (
                _ocr_clip_words(page, page_no, left_clip, dpi)
                + _ocr_clip_words(page, page_no, right_clip, dpi)
            )
        else:
            textpage = page.get_textpage_ocr(language="eng", dpi=dpi, full=True)
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


def _lines(words: list[tuple], width: float, force_midpoint: bool = False) -> list[list[tuple]]:
    """Group rows, respecting a source-verified center divider when present."""
    if not words:
        return []
    split_x = width * 0.5 if force_midpoint else _column_split_x(words, width)
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
            # This source uses two columns separated at the page midpoint. Clip each
            # crop to its own side so overlapping vertical bands cannot include a
            # neighboring question or a full-page border in the wrong question asset.
            column_margin = min(36.0, page_width * 0.03)
            if side == "left":
                x0 = max(x0, column_margin)
                x1 = min(x1, midpoint - 6.0)
            else:
                x0 = max(x0, midpoint + 6.0)
                x1 = min(x1, page_width - column_margin)
            y0 = max(0.0, min(row[2][1] for row in region_rows) - 8.0)
            y1 = min(page_height, max(row[2][3] for row in region_rows) + 8.0)

            if kind == "question" and answer_side:
                answer_top = min(row[2][1] for row in answer_side)
                if answer_top > y0:
                    # Never allow the question crop to extend into the printed answer row.
                    # min() is essential here: max() can retain an overlapping crop when
                    # OCR has accidentally included the answer row in question-region rows.
                    y1 = min(y1, answer_top - 6.0)
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


def _expected_subject_by_number(expected: set[str]) -> dict[int, str]:
    """Map printed question numbers to subjects only when the config makes them unique."""
    candidates: dict[int, set[str]] = {}
    for key in expected:
        if ':' not in key:
            continue
        subject_name, number_text = key.rsplit(':', 1)
        if number_text.isdigit() and subject_name.strip():
            candidates.setdefault(int(number_text), set()).add(subject_name.strip())
    return {
        number: next(iter(subject_names))
        for number, subject_names in candidates.items()
        if len(subject_names) == 1
    }




def _sequence_header_gap(
    expected_numbers: list[int], next_expected_index: int, observed_number: int
) -> tuple[int, list[int]] | None:
    """Find a forward header position and explicitly expose any missing numbers.

    A return value of None means the observation is unknown or backwards and
    must not advance the source sequence.
    """
    try:
        observed_index = expected_numbers.index(int(observed_number))
    except (ValueError, TypeError):
        return None
    if observed_index < next_expected_index:
        return None
    return observed_index, expected_numbers[next_expected_index:observed_index]


def _question_type_from_ranges(number: int, ranges) -> str | None:
    """Return an explicitly configured source-paper question type, if covered exactly once."""
    matches = [kind for start, end, kind in ranges if int(start) <= number <= int(end)]
    return matches[0] if len(matches) == 1 else None


_NUMBERED_SECTION_LABEL = re.compile(
    r'^\s*(?:ans(?:wer)?\s*[.:,;]|sol(?:ution)?\s*[.:,;])(?=\s|$|[\(\[])',
    re.I,
)


def _question_header_candidate(text: str, bounds: list[float], page_width: float, expected_number: int | None = None):
    """Recognize printed question numbers, while excluding numbered Answer/Solution rows."""
    x0 = float(bounds[0])
    midpoint = float(page_width) * 0.5
    in_number_gutter = (
        x0 <= float(page_width) * 0.105
        or midpoint - float(page_width) * 0.008 <= x0 <= midpoint + float(page_width) * 0.105
    )
    if not in_number_gutter:
        return None, None

    direct_match, direct_number = _question_start(text)
    if direct_match is not None and _NUMBERED_SECTION_LABEL.match(text[direct_match.end():]):
        # Some pages print the question number again beside its answer, e.g.
        # "10. Ans. ()". That is not a new question boundary: the actual stem
        # may be at the top of the next column/page.
        return None, None
    if direct_number is not None and (expected_number is None or direct_number == expected_number):
        return direct_match, direct_number

    # On equation/figure pages, OCR can omit the punctuation immediately after
    # a printed question number (source Q67 becomes "67 —K QY x"). Only accept
    # this form when it exactly matches the next expected number and the start of
    # the row is already inside the printed question-number gutter.
    if expected_number is not None:
        expected_prefix = re.match(rf'^\s*({re.escape(str(expected_number))})\b', text)
        if expected_prefix and not _NUMBERED_SECTION_LABEL.match(text[expected_prefix.end():]):
            return expected_prefix, expected_number

    # Examples from the source scan include "1 2. The value...", "I 46. ...",
    # "| 50. ..." and "| 75. ...". Search only the first 40 characters and allow
    # only short OCR debris / one stray digit before the expected printed number.
    marker = re.compile(r'(?<!\d)(\d{1,3})\s*[.):,](?=\s|$)')
    for match in marker.finditer(text[:40]):
        if _NUMBERED_SECTION_LABEL.match(text[match.end():]):
            return None, None
        number = int(match.group(1))
        if expected_number is not None and number != expected_number:
            continue
        prefix = text[:match.start()].strip()
        debris = not prefix or bool(re.fullmatch(r'[|Iil!.,;:-]+', prefix)) or bool(re.fullmatch(r'\d{1,3}', prefix))
        if len(prefix) <= 6 and debris:
            return match, number
    return None, None


def _layout_answer_marker(text: str) -> bool:
    """Tolerantly recognize answer labels for layout inference only, not final answer parsing."""
    value = str(text).strip()
    # OCR sometimes merges a short mathematical token from the same baseline
    # before the printed label (the source scan has the exact form "1 Ans. (1)").
    value = re.sub(
        r'^\s*\d{1,2}\s+(?=(?:answer|ans|correct\s+answer)\b)',
        '',
        value,
        count=1,
        flags=re.I,
    )
    return bool(ANSWER_MARKER.match(value))


def _layout_solution_marker(text: str) -> bool:
    """Tolerantly recognize noisy Sol labels for layout inference only."""
    value = str(text).strip()
    # On the source scan OCR reads the printed "Sol." label as "Sol,".
    value = re.sub(
        r'^\s*(solution|sol)\s*[,;](?=\s|$)',
        r'\1.',
        value,
        count=1,
        flags=re.I,
    )
    return bool(SOLUTION_MARKER.match(value))


def _infer_missing_top_question_header(raw, row_index: int, expected_number: int, page_dimensions: dict[int, tuple[float, float]], expected_subject_by_number: dict[int, str]) -> bool:
    """Infer a completely OCR-missed number only at a column top with answer/solution markers and the next numbered question in the same column."""
    if expected_number + 1 not in expected_subject_by_number:
        return False
    page_no, text, bounds, _subject = raw[row_index]
    dimensions = page_dimensions.get(page_no)
    if not dimensions:
        return False
    width, height = dimensions
    if float(bounds[1]) > height * 0.12:
        return False
    # Ignore OCR'd scan borders at the very top; they can otherwise inherit the
    # following question merely because its answer/solution markers are nearby.
    if float(bounds[1]) <= height * 0.015:
        return False
    x0 = float(bounds[0])
    midpoint = width * 0.5
    # OCR can lose only the printed number while keeping the mathematical stem
    # farther to the right (for example, an opening trigonometric expression).
    # A top-of-column row is inferred only when a later numbered question in the
    # same column is preceded by this block's own Answer and Solution markers.
    # Those source-order checks are stronger evidence than the x-position of the
    # first legible token, so do not require that token to lie in the number gutter.
    if len(text.strip()) < 12:
        return False
    if _layout_answer_marker(text) or _layout_solution_marker(text) or text.lstrip().startswith(("=", "∴", "⇒", "→")):
        return False

    same_column_left = x0 < midpoint
    saw_answer = False
    saw_solution = False
    for future_index in range(row_index + 1, len(raw)):
        future_page, future_text, future_bounds, _future_subject = raw[future_index]
        if future_page != page_no:
            break
        future_x0 = float(future_bounds[0])
        if (future_x0 < midpoint) != same_column_left:
            break
        answer_row = _layout_answer_marker(future_text)
        solution_label = _layout_solution_marker(future_text)
        if answer_row:
            saw_answer = True
        if solution_label:
            saw_solution = True
        next_match, next_number = _question_header_candidate(
            future_text, future_bounds, width, expected_number + 1
        )
        if next_number is not None:
            return saw_answer and saw_solution
        other_match, other_number = _question_header_candidate(future_text, future_bounds, width, None)
        if other_number is not None and other_number >= expected_number:
            # Do not infer from a continuation row before an already visible
            # expected question, or skip ahead across an unexpected number.
            return False
        # OCR sometimes misses the literal "Sol." prefix on scanned math working.
        # After a source Answer row, non-empty non-question text in the same
        # column is source-solution evidence; never count a later question header.
        if saw_answer and future_text.strip() and not answer_row and not solution_label:
            saw_solution = True
    return False


def _source_row_key(page: int, bounds: list[float] | tuple[float, ...]):
    """Stable key connecting a rendered text row to its original word-level boxes."""
    return int(page), tuple(round(float(value), 2) for value in bounds)


def _split_options_geometry(rows, word_rows_by_page_bounds):
    """Rebuild four options from their original word boxes when a 2-D grid is present.

    Some scanned papers put options 1/2 on one visual row and 3/4 on the next,
    while each fraction's numerator, bar and denominator occupy separate OCR rows.
    A flattened text row cannot preserve that layout, so allocate tokens to the
    nearest labelled option using both x and y coordinates. Ambiguous layouts fall
    back to the existing parser and still face normal validation.
    """
    if not word_rows_by_page_bounds:
        return None

    word_rows = []
    label_records = []
    for page, text, bounds in rows:
        tokens = word_rows_by_page_bounds.get(_source_row_key(page, bounds))
        if tokens is None:
            return None
        word_rows.append((page, text, bounds, tokens))
        for token in tokens:
            if len(token) < 5:
                continue
            token_text = str(token[4]).strip()
            match = OPTION_LABEL.fullmatch(token_text)
            if not match:
                continue
            label = (match.group(1) or match.group(2) or "").upper()
            if label:
                label_records.append((
                    label, float(token[0]), float(token[1]),
                    float(token[2]), float(token[3])
                ))

    labels_present = {item[0] for item in label_records}
    if set("ABCD").issubset(labels_present):
        expected_labels = set("ABCD")
    elif set("1234").issubset(labels_present):
        expected_labels = set("1234")
    else:
        return None

    selected = [item for item in label_records if item[0] in expected_labels]
    centers = {}
    for label in expected_labels:
        entries = sorted(
            ((item[1] + item[3]) / 2.0, (item[2] + item[4]) / 2.0)
            for item in selected if item[0] == label
        )
        if not entries:
            return None
        # Median coordinates protect against a stray duplicate label in a stem.
        xs = sorted(item[0] for item in entries)
        ys = sorted(item[1] for item in entries)
        centers[label] = (xs[len(xs) // 2], ys[len(ys) // 2])

    # This coordinate strategy is for multi-column option grids. A single vertical
    # option list is better handled by the line-oriented parser below.
    unique_x = sorted({round(value[0] / 20.0) for value in centers.values()})
    x_values = [value[0] for value in centers.values()]
    if len(unique_x) < 2 or max(x_values) - min(x_values) < 80:
        return None

    first_label_top = min(item[2] for item in selected)
    option_window_start = first_label_top - 60.0
    first_anchor_x = min(value[0] for value in centers.values())
    body_parts = []
    option_tokens = {label: [] for label in expected_labels}

    for page, text, bounds, tokens in word_rows:
        row_top = float(bounds[1])
        if row_top < option_window_start:
            if text.strip():
                body_parts.append(text.strip())
            continue

        # Keep any prompt prefix from a row that begins immediately before its
        # option labels (e.g. "Select the correct value: (1) ...").
        text_matches = list(OPTION_LABEL.finditer(text))
        if text_matches:
            prefix = text[:text_matches[0].start()].strip()
            if prefix:
                body_parts.append(prefix)

        for token in tokens:
            if len(token) < 5:
                continue
            token_text = str(token[4]).strip()
            if not token_text:
                continue
            label_match = OPTION_LABEL.fullmatch(token_text)
            if label_match:
                label = (label_match.group(1) or label_match.group(2) or "").upper()
                if label in expected_labels:
                    continue

            y0, y1 = float(token[1]), float(token[3])
            if y1 < option_window_start:
                continue
            center_x = (float(token[0]) + float(token[2])) / 2.0
            center_y = (y0 + y1) / 2.0

            # Narrow page-edge OCR artefacts are outside the option cells; don't
            # let them contaminate the leftmost option.
            if center_x < first_anchor_x - 45.0:
                continue

            label = min(
                expected_labels,
                key=lambda candidate: (
                    abs(center_x - centers[candidate][0])
                    + 0.9 * abs(center_y - centers[candidate][1])
                ),
            )
            option_tokens[label].append(token)

    options = {}
    for label, tokens in option_tokens.items():
        tokens.sort(key=lambda token: (float(token[1]), float(token[0])))
        value = safe_normalize(_join_word_tokens(tokens))
        if value:
            options[label] = value

    if set(options) != expected_labels:
        return None
    return safe_normalize(" ".join(part for part in body_parts if part)), options


def _split_mixed_terminal_option_group(rows: list[tuple[int, str, list[float]]]):
    """Prefer a complete option group after an explicit choose/select cue.

    OCR stems may contain earlier enumerated statements or reaction steps that
    reuse the same (1)-(4) labels as the actual choices. When the source prompt
    identifies where the choices begin, anchor parsing there instead of taking
    the first complete label group in the stem. Geometry remains the fallback
    for two-column grids whose OCR reading order is not sequential.
    """
    flat = safe_normalize(" ".join(str(text or "") for _page, text, _bounds in rows))
    matches = []
    for match in OPTION_LABEL.finditer(flat):
        raw_label = (match.group(1) or match.group(2) or "").upper()
        family = "letters" if raw_label in set("ABCD") else "numbers" if raw_label in set("1234") else None
        if family:
            matches.append((match.start(), match.end(), raw_label, family))
    if len(matches) < 4:
        return None

    cue = re.compile(
        r"\b(?:choose|select)\s+(?:the\s+)?correct(?:\s+(?:option|answer))?(?:\s+from\s+the\s+option)?\b",
        re.I,
    )
    cue_match = cue.search(flat)

    def make_result(group, family):
        options = {}
        for index, item in enumerate(group):
            stop = group[index + 1][0] if index + 1 < len(group) else len(flat)
            options[item[2]] = safe_normalize(flat[item[1]:stop])
        expected = set("ABCD") if family == "letters" else set("1234")
        if set(options) != expected or any(not value for value in options.values()):
            return None
        return safe_normalize(flat[:group[0][0]]), options

    # Source prompt first: select a complete label group after the cue even if
    # an earlier statement/reaction group uses the same label family.
    if cue_match:
        complete_after = []
        for start_index, (start, _end, _label, family) in enumerate(matches):
            if start < cue_match.end():
                continue
            expected = set("ABCD") if family == "letters" else set("1234")
            group = []
            seen = set()
            for item in matches[start_index:]:
                if item[3] != family or item[2] in seen:
                    break
                group.append(item)
                seen.add(item[2])
                if seen == expected:
                    complete_after.append((start_index, family, group))
                    break
        if complete_after:
            start_index, family, group = min(complete_after, key=lambda item: item[0])
            result = make_result(group, family)
            if result is not None:
                return result

    # Fallback for scans where the prompt cue was lost by OCR but the stem
    # contains a complete label group from a different family.
    if len(matches) < 8:
        return None
    complete = []
    for start_index, (start, end, label, family) in enumerate(matches):
        expected = set("ABCD") if family == "letters" else set("1234")
        group = []
        seen = set()
        for item in matches[start_index:]:
            if item[3] != family or item[2] in seen:
                break
            group.append(item)
            seen.add(item[2])
            if seen == expected:
                cue_after = bool(cue.search(flat[group[-1][1]:]))
                complete.append({
                    "start_index": start_index,
                    "family": family,
                    "group": group,
                    "cue_after": cue_after,
                })
                break
    if not complete:
        return None
    usable = [item for item in complete if not item["cue_after"]]
    if not usable:
        return None
    terminal = max(usable, key=lambda item: item["start_index"])
    mixed_prefix = any(
        item["family"] != terminal["family"]
        and item["start_index"] < terminal["start_index"]
        for item in complete
    )
    if not mixed_prefix:
        return None
    return make_result(terminal["group"], terminal["family"])


def _split_options(rows: list[tuple[int, str, list[float]]],
                   word_rows_by_page_bounds=None) -> tuple[str, dict[str, str]]:
    mixed_terminal_result = _split_mixed_terminal_option_group(rows)
    if mixed_terminal_result is not None:
        return mixed_terminal_result

    geometry_result = _split_options_geometry(rows, word_rows_by_page_bounds)
    if geometry_result is not None:
        return geometry_result

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
    # If the option labels are incomplete or OCR has detached math glyphs from
    # their labels, preserve the source row text once and fail structural
    # validation. Do not duplicate the question stem/options in the text field.
    all_text=safe_normalize(' '.join(t for _,t,_ in rows if t))
    return all_text,{}

def _parse_answer(text:str)->str|None:
    # Match a complete numerical token before single-digit MCQ labels, otherwise 42
    # would be incorrectly read as 4.
    token=re.match(r'\s*[\(\[]?\s*(-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?|[A-D])\s*[\)\]]?',text,re.I)
    return token.group(1) if token else None

def _split_source_sections(rows:list[tuple[int,str,list[float]]], word_rows_by_page_bounds=None):
    qrows=[]
    srows=[]
    answer=None
    answer_count=0
    answer_seen=False
    solution_seen=False
    for page,text,bounds in rows:
        am=ANSWER_MARKER.match(text) if not answer_seen else None
        sm=SOLUTION_MARKER.match(text)
        answer_token = None
        if am:
            answer_token = _parse_answer(text[am.end():])
            # OCR can wrap the last word of a prompt ("... choose the correct
            # answer") onto a separate row containing only "answer". Treat a
            # bare marker as an answer section only when it has a value or an
            # explicit separator; otherwise keep it in the question region.
            explicit_empty_marker = bool(re.search(
                r"(?:answer|ans\\s*\\.?|correct\\s+answer)\\s*[:\\-]\\s*$",
                text,
                re.I,
            ))
            if answer_token is None and not explicit_empty_marker:
                am = None
        if am:
            if answer_token:
                answer=answer_token
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
    q_text,q_opts=_split_options(qrows, word_rows_by_page_bounds)
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
    source_word_rows_by_page_bounds={}
    page_dimensions={}
    scan_only_pages=set()
    scan_dpi_by_page={}
    source_hash=sha256_file(config.source_pdf)
    expected=set(config.expected_question_numbers)
    # Only override headings when config explicitly provides a unique subject for
    # a printed number; ambiguous per-subject numbering remains heading-led.
    expected_subject_by_number = _expected_subject_by_number(expected)
    current_subject=None
    try:
        for page_no in range(config.page_range[0],config.page_range[1]+1):
            if page_no>page_count:
                return [],[],[Issue('PAGE_RANGE_OUT_OF_BOUNDS',f'Configured page {page_no} does not exist')],page_count
            page=doc[page_no-1]
            page_dimensions[page_no]=(float(page.rect.width),float(page.rect.height))
            page_image_info=_page_image_info(page)
            pa=_assets(page,page_no,asset_dir,source_hash,page_image_info)
            page_assets[page_no]=pa
            all_assets.extend(pa)
            words, used_ocr = _page_words(page,page_no,page_image_info)
            if used_ocr:
                scan_only_pages.add(page_no)
                scan_dpi_by_page[page_no]=_ocr_dpi(page)
            page_rows=[]
            force_midpoint = used_ocr and _has_center_divider(page)
            for row in _lines(words, page.rect.width, force_midpoint=force_midpoint):
                text=_join_word_tokens(row).strip()
                if not text:
                    continue
                subject=_subject_line(text)
                bounds=[min(w[0] for w in row),min(w[1] for w in row),max(w[2] for w in row),max(w[3] for w in row)]
                source_word_rows_by_page_bounds[_source_row_key(page_no,bounds)] = row
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

    expected_number_sequence = sorted(expected_subject_by_number)
    strict_sequential_numbering = (
        len(expected_number_sequence) == config.expected_question_count
        and bool(expected_number_sequence)
        and expected_number_sequence == list(range(
            expected_number_sequence[0],
            expected_number_sequence[0] + len(expected_number_sequence),
        ))
    )
    next_expected_index = 0
    header_issues: list[Issue] = []
    blocks=[]
    current=None
    for raw_index,(page,text,bounds,subject) in enumerate(raw):
        expected_next = (
            expected_number_sequence[next_expected_index]
            if strict_sequential_numbering and next_expected_index < len(expected_number_sequence)
            else None
        )
        page_width = page_dimensions.get(page, (0.0, 0.0))[0]
        match, number = _question_header_candidate(text, bounds, page_width, expected_next)
        if number is None and strict_sequential_numbering and expected_next is not None:
            if _infer_missing_top_question_header(raw,raw_index,expected_next,page_dimensions,expected_subject_by_number):
                # The source has a distinct top-of-column stem, then its own Answer
                # and Solution markers, followed by the next numbered question. The
                # printed number itself was missed by OCR; keep the stem text intact.
                match = re.match(r"", text)
                number = expected_next

        # If an expected number was not legible, still recognize later numbered
        # headers so the rest of the paper is not swallowed into the previous
        # question's solution. The gap is an explicit blocking issue; no missing
        # question text is fabricated and the batch remains non-importable.
        if number is None and strict_sequential_numbering and expected_next is not None:
            later_match, later_number = _question_header_candidate(
                text, bounds, page_width, None
            )
            if (
                later_number is not None
                and later_number in expected_subject_by_number
                and later_number > expected_next
            ):
                match, number = later_match, later_number

        if number is not None and strict_sequential_numbering:
            position = _sequence_header_gap(
                expected_number_sequence, next_expected_index, number
            )
            if position is None:
                match, number = None, None
            else:
                observed_index, missing_numbers = position
                if missing_numbers:
                    missing_text = ", ".join(str(value) for value in missing_numbers)
                    header_issues.append(Issue(
                        "MISSING_EXPECTED_QUESTION_HEADER",
                        f"Could not confidently detect printed question header(s) {missing_text} before source header {number}; missing content was not invented.",
                    ))
                next_expected_index = observed_index + 1
                subject = expected_subject_by_number[number]
        elif number is not None and number in expected_subject_by_number:
            subject = expected_subject_by_number[number]
        if number is not None and subject is None:
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
    issues=list(header_issues)
    crop_doc = fitz.open(config.source_pdf) if scan_only_pages else None
    source_placed_assets = tuple(all_assets)

    for block_index, block in enumerate(blocks):
        q_text,q_opts,answer,solution_text,qrows,srows,split_error=_split_source_sections(block['rows'],source_word_rows_by_page_bounds)
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
        for asset in source_placed_assets:
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
        # Explicit section bands in the source-paper config outrank OCR heuristics.
        # Incomplete options/answers still fail structural validation below.
        configured_type = _question_type_from_ranges(
            int(block['number']), getattr(config, 'question_type_ranges', ())
        )
        if configured_type is not None:
            question_type = configured_type
        # Otherwise retain content-based classification, without inventing missing fields.
        elif len(q_opts)==4 and set(q_opts) in (set('ABCD'),set('1234')):
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
