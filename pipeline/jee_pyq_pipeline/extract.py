from __future__ import annotations
import hashlib, re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

Q = re.compile(r'^(\d{1,3})[.)]$')
OPT = re.compile(r'^\(?([A-D])\)[.:]?$')
FIGURE = re.compile(r'\b(fig(?:ure)?|diagram|graph|circuit|shown|following)\b', re.I)

def _fitz():
    try:
        import fitz
        return fitz
    except ImportError as error:
        raise RuntimeError('PyMuPDF is required for layout-aware extraction; refusing text-only fallback') from error

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    """Reconstruct reading order from geometric word boxes, never PDF text concatenation."""
    # Split persistent two-column pages before grouping rows; narrow pages remain one column.
    columns = [[], []]
    for word in words:
        columns[1 if word[0] >= width * .55 else 0].append(word)
    active = [c for c in columns if c]
    if len(active) == 2 and min(map(len, active)) < 5: active = [words]
    result=[]
    for col in active:
        col.sort(key=lambda w: (round(w[1] / 3), w[0]))
        rows=[]
        for w in col:
            if not rows or abs(w[1] - rows[-1][0][1]) > 4.0:
                rows.append([w])
            else: rows[-1].append(w)
        for row in rows:
            row.sort(key=lambda w:w[0]); result.append(row)
    return result

def _assets(page, page_no: int, asset_dir: Path, source_hash: str) -> list[Asset]:
    found=[]
    for n, item in enumerate(page.get_images(full=True)):
        xref=item[0]; payload=page.parent.extract_image(xref)
        if not payload: continue
        data=payload['image']; digest=hashlib.sha256(data).hexdigest(); ext=payload.get('ext','bin')
        object_key=f'{source_hash[:16]}/page-{page_no}/image-{n}-{digest[:16]}.{ext}'
        file=asset_dir / object_key; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(data)
        rects=page.get_image_rects(xref)
        for rect in rects or [None]:
            bounds=[] if rect is None else [round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
            found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found

def extract(config, asset_dir: Path) -> tuple[list[Question], list[Asset], list[Issue], int]:
    fitz=_fitz(); doc=fitz.open(config.source_pdf); all_assets=[]; raw=[]; source_hash=sha256_file(config.source_pdf)
    try:
      for page_no in range(config.page_range[0], config.page_range[1]+1):
        if page_no > len(doc): return [], [], [Issue('PAGE_RANGE_OUT_OF_BOUNDS', f'Configured page {page_no} does not exist')], len(doc)
        page=doc[page_no-1]; page_assets=_assets(page,page_no,asset_dir,source_hash); all_assets.extend(page_assets)
        words=page.get_text('words')
        for row in _lines(words, page.rect.width):
            text=' '.join(w[4] for w in row)
            x0=min(w[0] for w in row); y0=min(w[1] for w in row); x1=max(w[2] for w in row); y1=max(w[3] for w in row)
            raw.append((page_no,text,[x0,y0,x1,y1],page_assets))
    finally: doc.close()
    blocks=[]; current=None
    for page,text,bounds,assets in raw:
        tokens=text.split()
        match=Q.match(tokens[0]) if tokens else None
        if match:
            if current: blocks.append(current)
            current={'number':int(match.group(1)), 'rows':[(page,' '.join(tokens[1:]),bounds)], 'assets':assets}
        elif current: current['rows'].append((page,text,bounds))
    if current: blocks.append(current)
    questions=[]
    for b in blocks:
        body=[]; options={}; current_option=None
        for page,text,bounds in b['rows']:
            tokens=text.split(); label=OPT.match(tokens[0]) if tokens else None
            if label:
                current_option=label.group(1); options[current_option]=safe_normalize(' '.join(tokens[1:])); continue
            if current_option: options[current_option]=safe_normalize(options[current_option]+' '+text)
            else: body.append(text)
        pages=sorted({r[0] for r in b['rows']}); bounds=[min(r[2][0] for r in b['rows']),min(r[2][1] for r in b['rows']),max(r[2][2] for r in b['rows']),max(r[2][3] for r in b['rows'])]
        qid=f'{source_hash[:16]}-q-{b["number"]:03d}'
        text=safe_normalize(' '.join(body)); requires=bool(FIGURE.search(text))
        qassets=[a for a in b['assets'] if a.page in pages and (not a.bounds or True)]
        questions.append(Question(qid,b['number'],text,options,None,pages,bounds,{'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release},qassets,None,requires))
    return questions, all_assets, [], len(doc)
