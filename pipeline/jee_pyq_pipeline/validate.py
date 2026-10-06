"""
Strict Green-Batch Validator for JEE Main PYQ Pipelines
Ensures 100% compliance with ExamSide & MathonGo schemas.
"""
from __future__ import annotations
from .models import Issue, Question

def validate(config, questions: list[Question], page_count: int) -> list[Issue]:
    issues = []
    expected_count = getattr(config, 'expected_question_count', 75)

    if len(questions) != expected_count:
        issues.append(Issue('COUNT_MISMATCH', f'Expected {expected_count}; extracted {len(questions)}'))

    math_count = sum(1 for q in questions if q.subject == 'Mathematics')
    phys_count = sum(1 for q in questions if q.subject == 'Physics')
    chem_count = sum(1 for q in questions if q.subject == 'Chemistry')

    if (math_count, phys_count, chem_count) != (25, 25, 25):
        issues.append(Issue('SUBJECT_DISTRIBUTION_MISMATCH', f'Math: {math_count}, Phys: {phys_count}, Chem: {chem_count}'))

    mcq_count = sum(1 for q in questions if q.question_type == 'MCQ')
    num_count = sum(1 for q in questions if q.question_type == 'NUMERICAL')

    if mcq_count != 60 or num_count != 15:
        issues.append(Issue('QUESTION_TYPE_MISMATCH', f'Expected 60 MCQ, 15 NUMERICAL; got {mcq_count} MCQ, {num_count} NUMERICAL'))

    for q in questions:
        if not q.answer:
            issues.append(Issue('MISSING_ANSWER', f'Question {q.subject}:{q.source_question_number} is missing answer'))
        if not q.solution or not q.solution.get('text'):
            issues.append(Issue('MISSING_SOLUTION', f'Question {q.subject}:{q.source_question_number} is missing solution text'))

    return issues
