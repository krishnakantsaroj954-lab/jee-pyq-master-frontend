from __future__ import annotations
import re
from .models import Issue, Question
from .util import sha256_file

NOTATION=re.compile(r'[□�]')

def _expected_key(question:Question)->str:
    subject=question.subject or 'UNKNOWN'
    return f'{subject}:{question.source_question_number}'

def _expected_set(config):
    raw=getattr(config,'expected_question_numbers',())
    subject=getattr(config,'subject','UNKNOWN')
    out=set()
    for item in raw:
        if isinstance(item,int):
            out.add(f'{subject}:{item}')
        else:
            out.add(str(item))
    return out

def _answer_key_token(answer):
    return str(answer).strip() if answer is not None else ''

def validate(config, questions:list[Question], page_count:int)->list[Issue]:
    issues=[]
    expected=_expected_set(config)
    seen_ids=set()
    seen_keys=set()

    for q in questions:
        local=[]
        key=_expected_key(q)
        if q.id in seen_ids:
            local.append(Issue('DUPLICATE_ID','Duplicate stable question ID',question_id=q.id))
        seen_ids.add(q.id)
        if key in seen_keys:
            local.append(Issue('DUPLICATE_SOURCE_NUMBER',f'Duplicate subject/question key: {key}',question_id=q.id))
        seen_keys.add(key)

        if not q.subject or q.subject not in {'Physics','Chemistry','Mathematics'}:
            local.append(Issue('MISSING_SUBJECT','Question subject could not be resolved from the source',question_id=q.id))
        if not q.pages or any(p<config.page_range[0] or p>config.page_range[1] or p>page_count for p in q.pages):
            local.append(Issue('INVALID_PROVENANCE','Invalid source pages',question_id=q.id))
        if len(q.text)<12:
            local.append(Issue('TRUNCATED_CONTENT','Question content is suspiciously short',question_id=q.id))
        if NOTATION.search(q.text+' '.join(q.options.values())):
            local.append(Issue('UNPRESERVED_NOTATION','Unsafe/unpreserved notation detected',question_id=q.id))

        if q.question_type=='MCQ':
            if set(q.options) not in (set('ABCD'),set('1234')) or any(not q.options.get(x,'').strip() for x in q.options):
                local.append(Issue('MALFORMED_OPTIONS','MCQ must contain exactly four non-empty source-labelled options',question_id=q.id))
            answer=_answer_key_token(q.answer)
            if answer not in q.options:
                local.append(Issue('MISSING_OR_AMBIGUOUS_ANSWER','MCQ source answer is absent or does not match an option label',question_id=q.id))
        elif q.question_type=='NUMERICAL':
            if q.options:
                local.append(Issue('NUMERICAL_HAS_OPTIONS','Numerical question unexpectedly contains options',question_id=q.id))
            if not _answer_key_token(q.answer):
                local.append(Issue('MISSING_OR_AMBIGUOUS_ANSWER','Numerical source answer is absent or ambiguous',question_id=q.id))
        else:
            local.append(Issue('UNKNOWN_QUESTION_TYPE','Could not classify question as MCQ or NUMERICAL from the source',question_id=q.id))

        if getattr(config,'source_has_solutions',False):
            if not q.solution or not q.solution.get('text') or not q.solution.get('pages'):
                local.append(Issue('MISSING_SOURCE_SOLUTION','Source solutions declared but no preserved solution text/reference exists',question_id=q.id))

        if q.requires_figure and not q.assets:
            local.append(Issue('MISSING_REQUIRED_IMAGE','Question appears to require a figure but no geometrically associated source asset is present',question_id=q.id))

        q.issues.extend(local)
        if local:
            q.status='QUARANTINED'
        issues.extend(local)

    actual={_expected_key(q) for q in questions}
    if len(questions)!=config.expected_question_count:
        issues.append(Issue('COUNT_MISMATCH',f'Expected {config.expected_question_count}; extracted {len(questions)}'))
    if actual!=expected:
        missing=sorted(expected-actual)
        extra=sorted(actual-expected)
        issues.append(Issue('QUESTION_SCOPE_MISMATCH',f'Source question scope mismatch; missing={missing[:12]} extra={extra[:12]}'))

    if issues:
        for q in questions:
            if q.status=='VALIDATED':
                q.status='QUARANTINED'
    return issues
