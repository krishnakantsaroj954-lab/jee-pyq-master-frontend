from __future__ import annotations
import hashlib, re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_START = re.compile(r'^(?:Q(?:uestion)?\.?\s*)?(\d{1,3})(?:[.)])(?:\s|$)', re.I)
OPTION_LABEL = re.compile(r'(?<!\w)(?:\(([A-D])\)|([A-D])[.)])(?=\s|$)')
FIGURE = re.compile(r'\b(fig(?:ure)?|diagram|graph|circuit|plot|schematic)\b|\b(shown|following)\s+(?:below|above|is|are)\b', re.I)

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError('PyMuPDF is required for layout-aware extraction; refusing text-only fallback') from error

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    """Reconstruct visual rows/columns from word geometry without plain-text PDF order."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w[0])
    gaps = [(ordered[i + 1][0] - ordered[i][2], i) for i in range(len(ordered) - 1)]
    split_gap, split_i = max(gaps, default=(0.0, 0))
    columns = [ordered]
    if split_gap > width * 0.12 and 0 < split_i < len(ordered) - 1:
        left = ordered[:split_i + 1]
        right = ordered[split_i + 1:]
        if (
            max(w[2] for w in left) - min(w[0] for w in left) > width * 0.20
            and max(w[2] for w in right) - min(w[0] for w in right) > width * 0.20
        ):
            columns = [left, right]

    result: list[list[tuple]] = []
    for col in columns:
        col = sorted(col, key=lambda w: (w[1], w[0]))
        rows: list[list[tuple]] = []
        for w in col:
            if not rows or abs(w[1] - rows[-1][0][1]) > 4.0:
                rows.append([w])
            else:
                rows[-1].append(w)
        for row in rows:
            result.append(sorted(row, key=lambda w: w[0]))
    return result

def _assets(page, page_no: int, asset_dir: Path, source_hash: str) -> list[Asset]:
    found: list[Asset] = []
    for n, item in enumerate(page.get_images(full=True)):
        xref = item[0]
        payload = page.parent.extract_image(xref)
        if not payload:
            continue
        data = payload['image']
        digest = hashlib.sha256(data).hexdigest()
        ext = payload.get('ext', 'bin')
        object_key = f'{source_hash[:16]}/page-{page_no}/image-{n}-{digest[:16]}.{ext}'
        file = asset_dir / object_key
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        for rect in page.get_image_rects(xref):
            bounds = [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]
            found.append(Asset(object_key, page_no, bounds, digest, str(file.relative_to(asset_dir.parent))))
    return found

def _intersects(a: list[float], b: list[float], padding: float = 2.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0-padding or bx1 < ax0-padding or ay1 < by0-padding or by1 < ay0-padding)

def _split_options(rows: list[tuple[int, str, list[float]]]) -> tuple[str, dict[str, str]]:
    body: list[str] = []
    options: dict[str, str] = {}
    current: str | None = None

    for _page, text, _bounds in rows:
        matches = list(OPTION_LABEL.finditer(text))
        if not matches:
            if current:
                options[current] = safe_normalize(f'{options[current]} {text}')
            else:
                body.append(text)
            continue

        prefix = text[:matches[0].start()].strip()
        if prefix:
            if current:
                options[current] = safe_normalize(f'{options[current]} {prefix}')
            else:
                body.append(prefix)

        for idx, match in enumerate(matches):
            label = match.group(1) or match.group(2)
            current = label
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            options[label] = safe_normalize(text[match.end():end].strip())

    return safe_normalize(' '.join(body)), options

def extract(config, asset_dir: Path) -> tuple[list[Question], list[Asset], list[Issue], int]:
    fitz = _fitz()
    doc = fitz.open(config.source_pdf)
    page_count = len(doc)
    all_assets: list[Asset] = []
    raw: list[tuple[int, str, list[float], list[Asset]]] = []
    source_hash = sha256_file(config.source_pdf)
    expected = set(config.expected_question_numbers)
    try:
        for page_no in range(config.page_range[0], config.page_range[1] + 1):
            if page_no > page_count:
                return [], [], [Issue('PAGE_RANGE_OUT_OF_BOUNDS', f'Configured page {page_no} does not exist')], page_count
            page = doc[page_no - 1]
            page_assets = _assets(page, page_no, asset_dir, source_hash)
            all_assets.extend(page_assets)
            for row in _lines(page.get_text('words'), page.rect.width):
                text = ' '.join(w[4] for w in row).strip()
                if not text:
                    continue
                bounds = [min(w[0] for w in row), min(w[1] for w in row), max(w[2] for w in row), max(w[3] for w in row)]
                raw.append((page_no, text, bounds, page_assets))
    finally:
        doc.close()

    blocks = []
    current = None
    for page, text, bounds, assets in raw:
        match = QUESTION_START.match(text)
        number = int(match.group(1)) if match else None
        if number in expected:
            if current:
                blocks.append(current)
            current = {'number': number, 'rows': [(page, text[match.end():].strip(), bounds)], 'assets': assets}
        elif current:
            current['rows'].append((page, text, bounds))
    if current:
        blocks.append(current)

    questions: list[Question] = []
    for block in blocks:
        text, options = _split_options(block['rows'])
        pages = sorted({r[0] for r in block['rows']})
        bounds = [
            min(r[2][0] for r in block['rows']),
            min(r[2][1] for r in block['rows']),
            max(r[2][2] for r in block['rows']),
            max(r[2][3] for r in block['rows']),
        ]
        qid = f'{source_hash[:16]}-q-{block["number"]:03d}'
        requires = bool(FIGURE.search(text))
        qassets = [
            asset for asset in block['assets']
            if asset.page in pages and asset.bounds and _intersects(asset.bounds, bounds)
        ]
        questions.append(
            Question(
                qid,
                block['number'],
                text,
                options,
                None,
                pages,
                bounds,
                {
                    'source_sha256': source_hash,
                    'source_document': config.source_pdf.name,
                    'source_release': config.release,
                },
                qassets,
                None,
                requires,
            )
        )
    return questions, all_assets, [], page_count
