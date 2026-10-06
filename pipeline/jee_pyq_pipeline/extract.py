from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_STRONG = re.compile(
    r'^\s*(?:question|q)\s*(?:no\.?|number|#)?\s*(\d{1,3})(?:\s*[\[\]():.\-]\s*|\s+|$)',
    re.I,
)
QUESTION_PLAIN = re.compile(
    r'^\s*(\d{1,2})\s*[\[\]():.\-]\s+(?=[A-Za-z0-9(])',
    re.I,
)

OPTION_LABEL = re.compile(r'(?<![\w.])(?:\(([A-D]|[1-4])\)|([A-D]|[1-4])[.)])(?=\s|$)')
ANSWER_MARKER = re.compile(r'^\s*(?:answer|ans\.?|correct\s+answer)\s*[:\-]?\s*', re.I)
SOLUTION_MARKER = re.compile(r'^\s*(?:solution|sol\.?)(?:\s*\([^)]*\))?\s*[:\-]?\s*', re.I)
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

def _page_words(page):
    try:
        words = page.get_text('words', sort=True)
    except TypeError:
        words = page.get_text('words')
    if words:
        return words, False
    try:
        textpage = page.get_textpage_ocr(language='eng', dpi=300, full=True)
        try:
            words = page.get_text('words', textpage=textpage, sort=True)
        except TypeError:
            words = page.get_text('words', textpage=textpage)
    except Exception as error:
        raise RuntimeError(
            'OCR was required because the page has no text layer, but OCR failed. '
            'Install Tesseract-OCR and keep the batch quarantined.'
        ) from error
    return words, True

def _question_start(text:str):
    match=QUESTION_STRONG.match(text)
    if match:
        return match, int(match.group(1))
    match=QUESTION_PLAIN.match(text)
    if match:
        return match, int(match.group(1))
    return None, None

def _lines(words: list[tuple], width: float) -> list[list[tuple]]:
    if not words:
        return []

    # The supplied scan has a stable vertical divider near the page midpoint.
    # Split words into physical columns before rebuilding visual rows; OCR
    # block/line IDs can merge the two columns on image-only pages.
    midpoint = width / 2.0
    margin = max(6.0, width * 0.002)

    left_words = []
    right_words = []
    for w in words:
        x0, x1 = float(w[0]), float(w[2])
        if x1 <= midpoint - margin:
            left_words.append(w)
        elif x0 >= midpoint + margin:
            right_words.append(w)

    def rows_for_column(column_words):
        ordered = sorted(column_words, key=lambda w: (w[1], w[0]))
        rows = []
        for w in ordered:
            if not rows or abs(w[1] - rows[-1][0][1]) > 9.0:
                rows.append([w])
            else:
                rows[-1].append(w)
        return [sorted(row, key=lambda w: w[0]) for row in rows]

    return rows_for_column(left_words) + rows_for_column(right_words)

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
            bounds=[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
            found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found

def _subject_line(text:str)->str|None:
    t=safe_normalize(text).strip().upper()
    compact=re.sub(r'[^A-Z]+',' ',t).strip()
    return SUBJECTS.get(compact)

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
    token=re.match(
        r'\s*[\(\[]?\s*(-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?|[A-D])'
        r'\s*[\)\]\.,:;]?',
        text,
        re.I,
    )
    return token.group(1).strip() if token else None

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
    raw=[]
    extraction_issues=[]
    ocr_pages=set()
    source_hash=sha256_file(config.source_pdf)
    current_subject=None
    try:
        for page_no in range(config.page_range[0],config.page_range[1]+1):
            if page_no>page_count:
                return [],[],[Issue('PAGE_RANGE_OUT_OF_BOUNDS',f'Configured page {page_no} does not exist')],page_count
            page=doc[page_no-1]
            pa=_assets(page,page_no,asset_dir,source_hash)
            all_assets.extend(pa)
            try:
                words,used_ocr=_page_words(page)
            except RuntimeError as error:
                extraction_issues.append(Issue('OCR_FAILED',f'Page {page_no}: {error}'))
                continue
            if used_ocr:
                ocr_pages.add(page_no)
            for row in _lines(words,page.rect.width):
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

    expected_keys = set(getattr(config, 'expected_question_numbers', ()))
    expected_by_number = {}
    for key in expected_keys:
        subject_name, number_text = str(key).rsplit(':', 1)
        if number_text.isdigit():
            expected_by_number[int(number_text)] = str(key)

    blocks=[]
    current=None
    next_number=1

    for page,text,bounds,subject in raw:
        if subject and text.strip().upper() in SUBJECTS:
            if current and current['subject'] != subject:
                blocks.append(current)
                current=None
            current_subject=subject
            continue

        match,number=_question_start(text)
        if number is not None:
            candidate_subject=subject or (current['subject'] if current else current_subject)
            if candidate_subject is None:
                continue

            key=f'{candidate_subject}:{number}'
            # Source questions are globally sequential in visual reading order.
            # Require the next exact configured key so numbered solution steps
            # cannot become fake question boundaries.
            if number != next_number or expected_by_number.get(number) != key:
                continue

            if current:
                blocks.append(current)

            current={
                'number':number,
                'subject':candidate_subject,
                'rows':[(page,text[match.end():].strip(),bounds)],
                'pages':{page},
                'strong_header':bool(QUESTION_STRONG.match(text)),
            }
            next_number += 1
            continue

        if current:
            current['rows'].append((page,text,bounds))
            current['pages'].add(page)

    if current:
        blocks.append(current)
    questions=[]
    issues=extraction_issues
    for block in blocks:
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
            q_bounds=[0.0,0.0,0.0,0.0]
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
                pad=90.0
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
        question_type='MCQ' if len(q_opts)==4 else 'NUMERICAL' if not q_opts else 'UNKNOWN'
        qid=f'{source_hash[:16]}-{block["subject"].lower()}-q-{block["number"]:03d}'
        solution=None
        if solution_text:
            solution={'text':solution_text,'pages':spages,'source_reference':{
                'source_document':config.source_pdf.name,
                'source_sha256':source_hash,
            }}
        extraction_method='ocr' if any(page in ocr_pages for page in block['pages']) else 'text'
        questions.append(Question(
            qid,block['number'],q_text,q_opts,answer,qpages,q_bounds,
            {'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release,'extraction_method':extraction_method},
            qassets,solution,bool(FIGURE.search(q_text)),'VALIDATED',[],block['subject'],None,question_type,sassets
        ))
    if not raw and not extraction_issues:
        issues.append(Issue('NO_TEXT_EXTRACTED','No source text could be extracted, including OCR fallback'))
    if len(ocr_pages) > 0:
        issues.append(Issue('OCR_USED','One or more pages required OCR; content still must pass all source validators',blocking=False))
    return questions,all_assets,issues,page_count
