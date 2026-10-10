from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_START = re.compile(r'^(?:Q(?:uestion)?\.?\s*)?(\d{1,3})(?:[.):])(?:\s|$)', re.I)
OPTION_LABEL = re.compile(r'(?<![\w.])(?:\(([A-D]|[1-4])\)|([A-D]|[1-4])[.)])(?=\s|$)')
ANSWER_MARKER = re.compile(r'^\s*(?:answer|ans\.?|correct\s+answer)\s*[:\-]?\s*', re.I)
SOLUTION_MARKER = re.compile(r'^\s*(?:solution|sol\.?)(?:\s*\([^)]*\))?\s*[:\-]\s*', re.I)
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


def _page_words(page, page_no: int = 1):
    """Return geometry-bearing words, using OCR only when the PDF page has no text layer."""
    words = page.get_text('words')
    if words:
        return words, False
    try:
        textpage = page.get_textpage_ocr(language='eng', dpi=250, full=True)
        words = page.get_text('words', textpage=textpage)
    except Exception as error:
        raise RuntimeError(
            f'OCR required on source page {page_no} but unavailable; refusing placeholder output'
        ) from error
    if not words:
        raise RuntimeError(
            f'OCR produced no words on source page {page_no}; refusing empty/placeholder output'
        )
    return words, True


def _question_start(text: str):
    """Return (regex_match, integer question number) for supported printed headers."""
    match = QUESTION_START.match(text)
    return match, (int(match.group(1)) if match else None)

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    if not words:
        return []
    ordered=sorted(words,key=lambda w:w[0])
    gaps=[(ordered[i+1][0]-ordered[i][2],i) for i in range(len(ordered)-1)]
    split_gap,split_i=max(gaps,default=(0.0,0))
    columns=[ordered]
    if split_gap>width*0.12 and 0<split_i<len(ordered)-1:
        left,right=ordered[:split_i+1],ordered[split_i+1:]
        if (
            max(w[2] for w in left)-min(w[0] for w in left)>width*0.20
            and max(w[2] for w in right)-min(w[0] for w in right)>width*0.20
        ):
            columns=[left,right]
    result=[]
    for col in columns:
        col=sorted(col,key=lambda w:(w[1],w[0]))
        rows=[]
        for w in col:
            if not rows or abs(w[1]-rows[-1][0][1])>4.0:
                rows.append([w])
            else:
                rows[-1].append(w)
        result.extend(sorted((sorted(row,key=lambda w:w[0]) for row in rows),key=lambda row:row[0][1]))
    return result

def _assets(page, page_no:int, asset_dir:Path, source_hash:str)->list[Asset]:
    found=[]
    for n,item in enumerate(page.get_images(full=True)):
        xref=item[0]
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
        for rect in page.get_image_rects(xref):
            # Full-page scans are source context, not question images. Never attach them
            # to every question; individual question crops must be created from geometry.
            if rect.width >= float(page.rect.width) * 0.85 and rect.height >= float(page.rect.height) * 0.80:
                continue
            bounds=[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
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
    token=re.match(r'\s*[\(\[]?\s*([A-D]|[1-4]|-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?)\s*[\)\]]?',text,re.I)
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
    source_hash=sha256_file(config.source_pdf)
    expected=set(config.expected_question_numbers)
    current_subject=None
    try:
        for page_no in range(config.page_range[0],config.page_range[1]+1):
            if page_no>page_count:
                return [],[],[Issue('PAGE_RANGE_OUT_OF_BOUNDS',f'Configured page {page_no} does not exist')],page_count
            page=doc[page_no-1]
            pa=_assets(page,page_no,asset_dir,source_hash)
            page_assets[page_no]=pa
            all_assets.extend(pa)
            words, _used_ocr = _page_words(page, page_no)
            for row in _lines(words, page.rect.width):
                text=' '.join(w[4] for w in row).strip()
                if not text:
                    continue
                subject=_subject_line(text)
                if subject:
                    current_subject=subject
                bounds=[min(w[0] for w in row),min(w[1] for w in row),max(w[2] for w in row),max(w[3] for w in row)]
                raw.append((page_no,text,bounds,current_subject))
    finally:
        doc.close()

    blocks=[]
    current=None
    for page,text,bounds,subject in raw:
        match, number = _question_start(text)
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
        if requires_figure:
            figure_crops=_crop_question_figures(config,block,qrows,blocks,block_index,asset_dir,source_hash)
            if figure_crops:
                qassets=figure_crops
                all_assets.extend(figure_crops)
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
    return questions,all_assets,issues,page_count
