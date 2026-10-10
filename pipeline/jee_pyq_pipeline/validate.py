from __future__ import annotations
import re
from .models import Issue, Question

NOTATION = re.compile(r'[□�]')
PLACEHOLDER = re.compile(
    r'validated source statement with mathematical precision|step-by-step mathematical proof',
    re.I,
)

def _expected_key(question: Question) -> str:
    return f'{question.subject or "UNKNOWN"}:{question.source_question_number}'

def _expected_set(config) -> set[str]:
    return {str(item) for item in getattr(config, 'expected_question_numbers', ())}

def _option_labels_valid(options: dict[str, str]) -> bool:
    if set(options) not in (set('ABCD'), set('1234')):
        return False
    return all(isinstance(options.get(k), str) and options[k].strip() for k in options)

def validate(config, questions: list[Question], page_count: int) -> list[Issue]:
    issues: list[Issue] = []
    expected = _expected_set(config)
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()

    for q in questions:
        local: list[Issue] = []
        key = _expected_key(q)
        is_dropped = q.status == 'Dropped'

        if not q.id or q.id in seen_ids:
            local.append(Issue('DUPLICATE_OR_MISSING_ID', 'Question ID is missing or duplicated', question_id=q.id))
        seen_ids.add(q.id)
        if key in seen_keys:
            local.append(Issue('DUPLICATE_SOURCE_NUMBER', f'Duplicate subject/question key: {key}', question_id=q.id))
        seen_keys.add(key)

        if not q.subject or q.subject not in {'Physics', 'Chemistry', 'Mathematics'}:
            local.append(Issue('MISSING_SUBJECT', 'Question subject could not be resolved from the source', question_id=q.id))
        if not q.pages or any(p < config.page_range[0] or p > config.page_range[1] or p > page_count for p in q.pages):
            local.append(Issue('INVALID_PROVENANCE', 'Invalid source pages', question_id=q.id))
        if not isinstance(q.text, str) or len(q.text.strip()) < 12:
            local.append(Issue('TRUNCATED_CONTENT', 'Question content is missing or suspiciously short', question_id=q.id))
        if PLACEHOLDER.search(q.text or '') or PLACEHOLDER.search(' '.join((q.solution or {}).get('text', '').split())):
            local.append(Issue('PLACEHOLDER_CONTENT', 'Placeholder text is not accepted as source evidence', question_id=q.id))
        if NOTATION.search((q.text or '') + ' '.join((q.options or {}).values())):
            local.append(Issue('UNPRESERVED_NOTATION', 'Unsafe/unpreserved notation detected', question_id=q.id))

        if not is_dropped:
            if q.question_type == 'MCQ':
                if not _option_labels_valid(q.options or {}):
                    local.append(Issue('MALFORMED_OPTIONS', 'MCQ must have four non-empty source-labelled options', question_id=q.id))
                answer = str(q.answer).strip() if q.answer is not None else ''
                if answer not in (q.options or {}):
                    local.append(Issue('MISSING_OR_AMBIGUOUS_ANSWER', 'MCQ source answer is absent or does not match a source option label', question_id=q.id))
            elif q.question_type == 'NUMERICAL':
                if q.options:
                    local.append(Issue('NUMERICAL_HAS_OPTIONS', 'Numerical question unexpectedly contains options', question_id=q.id))
                answer = str(q.answer).strip() if q.answer is not None else ''
                if not answer or not re.fullmatch(r'-?\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?', answer):
                    local.append(Issue('MISSING_OR_AMBIGUOUS_ANSWER', 'Numerical source answer is absent or invalid', question_id=q.id))
            else:
                local.append(Issue('UNKNOWN_QUESTION_TYPE', 'Could not safely classify source question as MCQ or numerical', question_id=q.id))

            if getattr(config, 'source_has_solutions', False):
                solution = q.solution or {}
                if not str(solution.get('text', '')).strip() or not solution.get('pages'):
                    local.append(Issue('MISSING_SOURCE_SOLUTION', 'Source solutions were declared but no source solution text/page reference exists', question_id=q.id))

        if q.requires_figure and not q.assets:
            local.append(Issue('MISSING_REQUIRED_IMAGE', 'Question needs a figure but no bounded source image crop was associated', question_id=q.id))

        if local:
            if not is_dropped:
                q.status = 'QUARANTINED'
            q.issues.extend(local)
        issues.extend(local)

    actual = {_expected_key(q) for q in questions}
    if len(questions) != config.expected_question_count:
        issues.append(Issue('COUNT_MISMATCH', f'Expected {config.expected_question_count}; extracted {len(questions)}'))
    if actual != expected:
        issues.append(Issue('QUESTION_SCOPE_MISMATCH', f'Source scope mismatch; missing={sorted(expected-actual)[:12]} extra={sorted(actual-expected)[:12]}'))

    if issues:
        for q in questions:
            if q.status == 'VALIDATED':
                q.status = 'QUARANTINED'
    return issues
