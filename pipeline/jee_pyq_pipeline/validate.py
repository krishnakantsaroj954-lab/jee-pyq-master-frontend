from __future__ import annotations
import json, re
from .models import Issue, Question

NOTATION = re.compile(r'[□�]')

def answers(path):
    raw=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict) or not raw.get('source_document') or not isinstance(raw.get('answers'), dict):
        raise ValueError('Answer key must contain source_document and answers map')
    return raw

def validate(config, questions: list[Question], page_count: int) -> list[Issue]:
    issues=[]
    solutions=None

    if config.source_has_solutions:
        try:
            solutions=json.loads(config.source_solutions.read_text(encoding='utf-8'))
            if solutions.get('source_document') != config.source_pdf.name or not isinstance(solutions.get('solutions'), dict):
                raise ValueError('Solution map must match source_document and contain solutions')
        except (OSError, ValueError, json.JSONDecodeError) as e:
            issues.append(Issue('INVALID_SOURCE_SOLUTIONS',str(e)))

    try:
        key=answers(config.answer_key)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        key=None
        issues.append(Issue('INVALID_ANSWER_KEY',str(e)))

    expected_numbers=set(config.expected_question_numbers)
    if key and key['source_document'] != config.source_pdf.name:
        issues.append(Issue('ANSWER_KEY_SOURCE_MISMATCH','Answer key provenance does not match source PDF'))
    if key and set(key['answers']) != {str(n) for n in expected_numbers}:
        issues.append(Issue('ANSWER_KEY_SCOPE_MISMATCH','Answer key question-number scope does not exactly match configured source scope'))

    if solutions is not None and set(solutions['solutions']) != {str(n) for n in expected_numbers}:
        issues.append(Issue('SOURCE_SOLUTION_SCOPE_MISMATCH','Source solution scope does not exactly match configured source scope'))

    ids=set()
    nums=set()
    for q in questions:
        local=[]
        if q.id in ids:
            local.append(Issue('DUPLICATE_ID','Duplicate stable question ID',question_id=q.id))
        ids.add(q.id)

        if q.source_question_number in nums:
            local.append(Issue('DUPLICATE_SOURCE_NUMBER','Duplicate source question number',question_id=q.id))
        nums.add(q.source_question_number)

        if not q.pages or any(p < config.page_range[0] or p > config.page_range[1] or p > page_count for p in q.pages):
            local.append(Issue('INVALID_PROVENANCE','Invalid source pages',question_id=q.id))
        if len(q.text) < 12:
            local.append(Issue('TRUNCATED_CONTENT','Question content is suspiciously short',question_id=q.id))
        if set(q.options) != set('ABCD') or any(not q.options.get(x,'').strip() for x in 'ABCD'):
            local.append(Issue('MALFORMED_OPTIONS','Representative pipeline requires exactly four non-empty A/B/C/D options',question_id=q.id))
        if NOTATION.search(q.text+' '.join(q.options.values())):
            local.append(Issue('UNPRESERVED_NOTATION','Unsafe/unpreserved notation detected',question_id=q.id))
        if q.requires_figure and not q.assets:
            local.append(Issue('MISSING_REQUIRED_IMAGE','Question appears to require a figure but no geometrically associated source asset is present',question_id=q.id))

        if solutions is not None:
            solution=solutions['solutions'].get(str(q.source_question_number))
            if not solution:
                local.append(Issue('MISSING_SOURCE_SOLUTION','Source solutions declared but no preserved solution reference exists',question_id=q.id))
            else:
                q.solution={'source_reference': solution}

        if key:
            answer=key['answers'].get(str(q.source_question_number))
            q.answer=answer
            if answer not in q.options:
                local.append(Issue('MISSING_OR_AMBIGUOUS_ANSWER','Source answer absent or not mapped to an option',question_id=q.id))

        q.issues.extend(local)
        if local:
            q.status='QUARANTINED'
        issues.extend(local)

    if len(questions) != config.expected_question_count:
        issues.append(Issue('COUNT_MISMATCH',f'Expected {config.expected_question_count}; extracted {len(questions)}'))
    if {q.source_question_number for q in questions} != expected_numbers:
        issues.append(Issue('QUESTION_NUMBERING_MISMATCH','Extracted source question numbers do not match configured source scope'))

    if issues:
        for q in questions:
            if q.status == 'VALIDATED':
                q.status='QUARANTINED'
    return issues
