from __future__ import annotations
import hashlib, re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

Q = re.compile(r'^(\d{1,3})(?:[.)])?$')
OPT = re.compile(r'^(?:\(([A-D])\)|([A-D])[.)])[:.]?
FIGURE = re.compile(r'\b(fig(?:ure)?|diagram|graph|circuit)\b|\b(shown|following)\s+(?:below|above|is|are)\b', re.I)

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError('PyMuPDF is required for layout-aware extraction; refusing text-only fallback') from error

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    """Reconstruct reading order from geometric word boxes, never PDF text concatenation."""
    if not words:
        return []

    # Detect two-column layouts using the largest horizontal gap rather than a fixed x=.55 split.
    ordered = sorted(words, key=lambda w: w[0])
    gaps = [(ordered[i + 1][0] - ordered[i][2], i) for i in range(len(ordered) - 1)]
    split = max(gaps, default=(0, 0))
    columns = [ordered]
    if split[0] > width * 0.08:
        left = ordered[:split[1] + 1]
        right = ordered[split[1] + 1:]
        if left and right:
            columns = [left, right]

    result = []
    for col in columns:
        col.sort(key=lambda w: (w[1], w[0]))
        rows = []
        for w in col:
            if not rows or abs(w[1] - rows[-1][0][1]) > 4.0:
                rows.append([w])
            else:
                rows[-1].append(w)
        for row in rows:
            row.sort(key=lambda w: w[0])
            result.append(row)
    return result

def _assets(page, page_no: int, asset_dir: Path, source_hash: str) -> list[Asset]:
    found=[]
    for n, item in enumerate(page.get_images(full=True)):
        xref=item[0]
        payload=page.parent.extract_image(xref)
        if not payload:
            continue
        data=payload['image']
        digest=hashlib.sha256(data).hexdigest()
        ext=payload.get('ext','bin')
        object_key=f'{source_hash[:16]}/page-{page_no}/image-{n}-{digest[:16]}.{ext}'
        file=asset_dir / object_key
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        for rect in page.get_image_rects(xref):
            bounds=[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
            found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found

def _intersects(a: list[float], b: list[float], padding: float = 2.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0-padding or bx1 < ax0-padding or ay1 < by0-padding or by1 < ay0-padding)

def extract(config, asset_dir: Path) -> tuple[list[Question], list[Asset], list[Issue], int]:
    fitz=_fitz()
    doc=fitz.open(config.source_pdf)
    page_count=len(doc)
    all_assets=[]
    raw=[]
    source_hash=sha256_file(config.source_pdf)
    try:
        for page_no in range(config.page_range[0], config.page_range[1]+1):
            if page_no > page_count:
                return [], [], [Issue('PAGE_RANGE_OUT_OF_BOUNDS', f'Configured page {page_no} does not exist')], page_count
            page=doc[page_no-1]
            page_assets=_assets(page,page_no,asset_dir,source_hash)
            all_assets.extend(page_assets)
            words=page.get_text('words')
            for row in _lines(words, page.rect.width):
                text=' '.join(w[4] for w in row)
                x0=min(w[0] for w in row); y0=min(w[1] for w in row)
                x1=max(w[2] for w in row); y1=max(w[3] for w in row)
                raw.append((page_no,text,[x0,y0,x1,y1],page_assets))
    finally:
        doc.close()

    blocks=[]
    current=None
    for page,text,bounds,assets in raw:
        tokens=text.split()
        match=Q.match(tokens[0]) if tokens else None
        if match and int(match.group(1)) in set(config.expected_question_numbers):
            if current:
                blocks.append(current)
            current={'number':int(match.group(1)), 'rows':[(page,' '.join(tokens[1:]),bounds)], 'assets':assets}
        elif current:
            current['rows'].append((page,text,bounds))

    if current:
        blocks.append(current)

    questions=[]
    for b in blocks:
        body=[]
        options={}
        current_option=None
        for page,text,bounds in b['rows']:
            tokens=text.split()
            label=OPT.match(tokens[0]) if tokens else None
            if label and tokens[0].strip('().:') in set('ABCD'):
                current_option=label.group(1) or label.group(2)
                remainder=' '.join(tokens[1:])
                options[current_option]=safe_normalize(remainder)
                continue
            if current_option:
                options[current_option]=safe_normalize(options[current_option]+' '+text)
            else:
                body.append(text)

        pages=sorted({r[0] for r in b['rows']})
        bounds=[min(r[2][0] for r in b['rows']),min(r[2][1] for r in b['rows']),
                max(r[2][2] for r in b['rows']),max(r[2][3] for r in b['rows'])]
        qid=f'{source_hash[:16]}-q-{b["number"]:03d}'
        text=safe_normalize(' '.join(body))
        requires=bool(FIGURE.search(text))
        qassets=[]
        for asset in b['assets']:
            if asset.page in pages and asset.bounds and _intersects(asset.bounds,bounds):
                qassets.append(asset)
        questions.append(
            Question(
                qid,b['number'],text,options,None,pages,bounds,
                {'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release},
                qassets,None,requires
            )
        )
    return questions, all_assets, [], page_count
)
FIGURE = re.compile(r'\b(fig(?:ure)?|diagram|graph|circuit)\b|\b(shown|following)\s+(?:below|above|is|are)\b', re.I)

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError('PyMuPDF is required for layout-aware extraction; refusing text-only fallback') from error

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    """Reconstruct reading order from geometric word boxes, never PDF text concatenation."""
    if not words:
        return []

    # Detect two-column layouts using the largest horizontal gap rather than a fixed x=.55 split.
    ordered = sorted(words, key=lambda w: w[0])
    gaps = [(ordered[i + 1][0] - ordered[i][2], i) for i in range(len(ordered) - 1)]
    split = max(gaps, default=(0, 0))
    columns = [ordered]
    if split[0] > width * 0.08:
        left = ordered[:split[1] + 1]
        right = ordered[split[1] + 1:]
        if left and right:
            columns = [left, right]

    result = []
    for col in columns:
        col.sort(key=lambda w: (w[1], w[0]))
        rows = []
        for w in col:
            if not rows or abs(w[1] - rows[-1][0][1]) > 4.0:
                rows.append([w])
            else:
                rows[-1].append(w)
        for row in rows:
            row.sort(key=lambda w: w[0])
            result.append(row)
    return result

def _assets(page, page_no: int, asset_dir: Path, source_hash: str) -> list[Asset]:
    found=[]
    for n, item in enumerate(page.get_images(full=True)):
        xref=item[0]
        payload=page.parent.extract_image(xref)
        if not payload:
            continue
        data=payload['image']
        digest=hashlib.sha256(data).hexdigest()
        ext=payload.get('ext','bin')
        object_key=f'{source_hash[:16]}/page-{page_no}/image-{n}-{digest[:16]}.{ext}'
        file=asset_dir / object_key
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        for rect in page.get_image_rects(xref):
            bounds=[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
            found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found

def _intersects(a: list[float], b: list[float], padding: float = 2.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0-padding or bx1 < ax0-padding or ay1 < by0-padding or by1 < ay0-padding)

def extract(config, asset_dir: Path) -> tuple[list[Question], list[Asset], list[Issue], int]:
    fitz=_fitz()
    doc=fitz.open(config.source_pdf)
    page_count=len(doc)
    all_assets=[]
    raw=[]
    source_hash=sha256_file(config.source_pdf)
    try:
        for page_no in range(config.page_range[0], config.page_range[1]+1):
            if page_no > page_count:
                return [], [], [Issue('PAGE_RANGE_OUT_OF_BOUNDS', f'Configured page {page_no} does not exist')], page_count
            page=doc[page_no-1]
            page_assets=_assets(page,page_no,asset_dir,source_hash)
            all_assets.extend(page_assets)
            words=page.get_text('words')
            for row in _lines(words, page.rect.width):
                text=' '.join(w[4] for w in row)
                x0=min(w[0] for w in row); y0=min(w[1] for w in row)
                x1=max(w[2] for w in row); y1=max(w[3] for w in row)
                raw.append((page_no,text,[x0,y0,x1,y1],page_assets))
    finally:
        doc.close()

    blocks=[]
    current=None
    for page,text,bounds,assets in raw:
        tokens=text.split()
        match=Q.match(tokens[0]) if tokens else None
        if match and int(match.group(1)) in set(config.expected_question_numbers):
            if current:
                blocks.append(current)
            current={'number':int(match.group(1)), 'rows':[(page,' '.join(tokens[1:]),bounds)], 'assets':assets}
        elif current:
            current['rows'].append((page,text,bounds))

    if current:
        blocks.append(current)

    questions=[]
    for b in blocks:
        body=[]
        options={}
        current_option=None
        for page,text,bounds in b['rows']:
            tokens=text.split()
            label=OPT.match(tokens[0]) if tokens else None
            if label and tokens[0].strip('().:') in set('ABCD'):
                current_option=label.group(1) or label.group(2)
                remainder=' '.join(tokens[1:])
                options[current_option]=safe_normalize(remainder)
                continue
            if current_option:
                options[current_option]=safe_normalize(options[current_option]+' '+text)
            else:
                body.append(text)

        pages=sorted({r[0] for r in b['rows']})
        bounds=[min(r[2][0] for r in b['rows']),min(r[2][1] for r in b['rows']),
                max(r[2][2] for r in b['rows']),max(r[2][3] for r in b['rows'])]
        qid=f'{source_hash[:16]}-q-{b["number"]:03d}'
        text=safe_normalize(' '.join(body))
        requires=bool(FIGURE.search(text))
        qassets=[]
        for asset in b['assets']:
            if asset.page in pages and asset.bounds and _intersects(asset.bounds,bounds):
                qassets.append(asset)
        questions.append(
            Question(
                qid,b['number'],text,options,None,pages,bounds,
                {'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release},
                qassets,None,requires
            )
        )
    return questions, all_assets, [], page_count
