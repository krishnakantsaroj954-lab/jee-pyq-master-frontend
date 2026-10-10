from __future__ import annotations
import math
import re
from pathlib import Path
from .models import Issue, Question

NOTATION = re.compile(r'[□�]')
# These phrases only identify known template/sample output patterns. They are
# deliberately checked across question, option, answer, and solution fields.
PLACEHOLDER = re.compile(
    r'validated source statement|step-by-step mathematical proof|'
    r'\bplaceholder\b|\blorem ipsum\b|\btodo\b|\btbd\b|'
    r'question content long enough|sample question with four source options|'
    r'\boption\s+[A-D]\b|\banswer\s+not available\b',
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

        if not q.id:
            local.append(Issue('MISSING_ID', 'Question ID is missing', question_id=q.id))
        elif q.id in seen_ids:
            local.append(Issue('DUPLICATE_ID', 'Question ID is duplicated', question_id=q.id))
        seen_ids.add(q.id)
        if key in seen_keys:
            local.append(Issue('DUPLICATE_SOURCE_NUMBER', f'Duplicate subject/question key: {key}', question_id=q.id))
        seen_keys.add(key)

        if not q.subject or q.subject not in {'Physics', 'Chemistry', 'Mathematics'}:
            local.append(Issue('MISSING_SUBJECT', 'Question subject could not be resolved from the source', question_id=q.id))
        if not q.pages or any(
            not isinstance(p, int) or p < config.page_range[0]
            or p > config.page_range[1] or p > page_count
            for p in q.pages
        ):
            local.append(Issue('INVALID_PROVENANCE', 'Invalid source pages', question_id=q.id))

        provenance = q.provenance if isinstance(q.provenance, dict) else {}
        source_sha = provenance.get('source_sha256')
        source_document = provenance.get('source_document')
        expected_document = Path(config.source_pdf).name
        if (
            not isinstance(source_sha, str)
            or not re.fullmatch(r'[0-9a-f]{64}', source_sha)
            or source_document != expected_document
        ):
            local.append(Issue(
                'INVALID_SOURCE_LINEAGE',
                'Source SHA-256 and matching source document name are required',
                question_id=q.id,
            ))

        bounds = q.bounds
        valid_bounds = (
            isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds)
            and bounds[2] > bounds[0] and bounds[3] > bounds[1]
        )
        if not valid_bounds:
            local.append(Issue(
                'INVALID_QUESTION_BOUNDS',
                'Question bounding box must contain finite, positive-area coordinates',
                question_id=q.id,
            ))

        if not isinstance(q.text, str) or len(q.text.strip()) < 12:
            local.append(Issue('TRUNCATED_CONTENT', 'Question content is missing or suspiciously short', question_id=q.id))
        source_text = ' '.join([
            q.text or '',
            ' '.join((q.options or {}).values()),
            str(q.answer or ''),
            ' '.join(((q.solution or {}).get('text', '') or '').split()),
        ])
        if PLACEHOLDER.search(source_text):
            local.append(Issue(
                'PLACEHOLDER_CONTENT',
                'Template/sample text is not accepted as source evidence',
                question_id=q.id,
            ))
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
                source_ref = solution.get('source_reference') if isinstance(solution, dict) else None
                if (
                    not str(solution.get('text', '')).strip()
                    or not solution.get('pages')
                    or not isinstance(source_ref, dict)
                    or source_ref.get('source_sha256') != source_sha
                    or source_ref.get('source_document') != source_document
                ):
                    local.append(Issue(
                        'MISSING_SOURCE_SOLUTION',
                        'Solution text, page lineage, and matching source reference are required',
                        question_id=q.id,
                    ))

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
