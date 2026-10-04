from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .models import Asset, Issue, Question
from .util import safe_normalize, sha256_file

QUESTION_START = re.compile(r'^(?:Q(?:uestion)?\.?\s*)?(\d{1,3})(?:[.)])(?:\s|$)', re.I)
OPTION_LABEL = re.compile(r'(?<![\w.])(?:\(([A-D]|[1-4])\)|([A-D]|[1-4])[.)])(?=\s|$)')
ANSWER_MARKER = re.compile(r'(?:^|\s)(?:answer|ans\.?|correct\s+answer)\s*[:\-]\s*', re.I)
SOLUTION_MARKER = re.compile(r'(?:^|\s)(?:solution|sol\.?)(?:\s*\([^)]*\))?\s*[:\-]?\s*', re.I)
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
            bounds=[round(rect.x0,2),round(rect.y0,2),round(rect.x1,2),round(rect.y1,2)]
            found.append(Asset(object_key,page_no,bounds,digest,str(file.relative_to(asset_dir.parent))))
    return found

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
    token=re.match(r'\s*([A-D]|[1-4]|-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?)\b',text,re.I)
    return token.group(1) if token else None

def _split_source_sections(rows:list[tuple[int,str,list[float]]]):
    qrows=[]
    srows=[]
    answer=None
    answer_count=0
    solution_seen=False
    for page,text,bounds in rows:
        am=ANSWER_MARKER.search(text) if not solution_seen else None
        sm=SOLUTION_MARKER.search(text)
        if not solution_seen and am:
            prefix=text[:am.start()].strip()
            if prefix:
                qrows.append((page,prefix,bounds))
            token=_parse_answer(text[am.end():])
            if token:
                answer=token
            answer_count+=1
            solution_seen=True if sm else False
            if sm:
                srows.append((page,text[sm.end():].strip(),bounds))
            continue
        if not solution_seen and sm:
            prefix=text[:sm.start()].strip()
            if prefix:
                qrows.append((page,prefix,bounds))
            solution_seen=True
            suffix=text[sm.end():].strip()
            if suffix:
                srows.append((page,suffix,bounds))
            continue
        if solution_seen:
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
            for row in _lines(page.get_text('words'),page.rect.width):
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
        match=QUESTION_START.match(text)
        number=int(match.group(1)) if match else None
        if number is not None and current is None and subject is None:
            continue
        if number is not None and subject is not None:
            key=f'{subject}:{number}'
            if key in expected:
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
    for block in blocks:
        q_text,q_opts,answer,solution_text,qrows,srows,split_error=_split_source_sections(block['rows'])
        if split_error:
            issues.append(Issue('MULTIPLE_ANSWER_MARKERS',f'Question {block["subject"]}:{block["number"]} has multiple answer markers'))
        qpages=sorted({r[0] for r in qrows})
        spages=sorted({r[0] for r in srows})
        if not qpages:
            qpages=sorted(block['pages'])
        q_bounds=[
            min(r[2][0] for r in qrows),min(r[2][1] for r in qrows),
            max(r[2][2] for r in qrows),max(r[2][3] for r in qrows),
        ]
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
        questions.append(Question(
            qid,block['number'],q_text,q_opts,answer,qpages,q_bounds,
            {'source_sha256':source_hash,'source_document':config.source_pdf.name,'source_release':config.release},
            qassets,solution,bool(FIGURE.search(q_text)),'VALIDATED',[],block['subject'],None,question_type,sassets
        ))
    return questions,all_assets,issues,page_count
