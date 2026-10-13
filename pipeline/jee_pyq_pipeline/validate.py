from __future__ import annotations

from collections import Counter

from .models import Issue, Question


def validate(config, questions: list[Question], page_count: int) -> list[Issue]:
    """Fail closed on missing, synthetic, duplicated, or weakly-sourced records."""
    issues: list[Issue] = []
    expected_count = getattr(config, "expected_question_count", None)
    expected_keys = set(getattr(config, "expected_question_numbers", ()) or ())
    has_solution_source = bool(getattr(config, "source_has_solutions", False))

    if expected_count is not None and len(questions) != expected_count:
        issues.append(Issue("COUNT_MISMATCH", f"Expected {expected_count}; extracted {len(questions)}"))

    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        issues.append(Issue("DUPLICATE_ID", "Duplicate question IDs were extracted"))

    source_keys = [f"{q.subject}:{q.source_question_number}" for q in questions]
    duplicate_keys = sorted(k for k, count in Counter(source_keys).items() if count > 1)
    for key in duplicate_keys:
        issues.append(Issue("DUPLICATE_SOURCE_NUMBER", f"Duplicate source question key: {key}"))

    actual_keys = set(source_keys)
    if expected_keys and actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        issues.append(Issue(
            "QUESTION_NUMBER_MISMATCH",
            f"Question key mismatch; missing={missing[:12]}, unexpected={extra[:12]}",
        ))

    if expected_count == 75:
        subject_counts = Counter(q.subject for q in questions)
        expected_subjects = {"Physics": 25, "Chemistry": 25, "Mathematics": 25}
        if dict(subject_counts) != expected_subjects:
            issues.append(Issue(
                "SUBJECT_DISTRIBUTION_MISMATCH",
                f"Expected {expected_subjects}; extracted {dict(subject_counts)}",
            ))
        mcq_count = sum(1 for q in questions if q.question_type == "MCQ")
        numerical_count = sum(1 for q in questions if q.question_type == "NUMERICAL")
        if (mcq_count, numerical_count) != (60, 15):
            issues.append(Issue(
                "QUESTION_TYPE_MISMATCH",
                f"Expected 60 MCQ and 15 numerical questions; got {mcq_count} MCQ, {numerical_count} numerical",
            ))

    for q in questions:
        label = f"{q.subject}:{q.source_question_number}"
        text = (q.text or "").strip()
        if len(text) < 8:
            issues.append(Issue("TRUNCATED_CONTENT", f"{label} has empty or suspiciously short question text", question_id=q.id))
        if "□" in text or "�" in text:
            issues.append(Issue("UNPRESERVED_NOTATION", f"{label} contains a replacement/unknown glyph", question_id=q.id))

        lowered = text.lower()
        if (
            "validated source statement with mathematical precision" in lowered
            or "step-by-step mathematical proof for question" in lowered
            or any(q.options.get(k, "").strip().lower() == f"option {k.lower()}" for k in ("A", "B", "C", "D"))
        ):
            issues.append(Issue("PLACEHOLDER_CONTENT", f"{label} contains synthetic placeholder content", question_id=q.id))

        if not q.answer or not str(q.answer).strip():
            issues.append(Issue("MISSING_OR_AMBIGUOUS_ANSWER", f"{label} has no source answer value", question_id=q.id))

        if q.question_type == "MCQ":
            labels = set((q.options or {}).keys())
            if labels not in ({"A", "B", "C", "D"}, {"1", "2", "3", "4"}):
                issues.append(Issue("MALFORMED_OPTIONS", f"{label} must have exactly A-D or 1-4 options", question_id=q.id))
            elif any(not str(q.options.get(k, "")).strip() for k in labels):
                issues.append(Issue("MALFORMED_OPTIONS", f"{label} has an empty option value", question_id=q.id))
        elif q.question_type == "UNKNOWN":
            issues.append(Issue("UNKNOWN_QUESTION_TYPE", f"{label} could not be classified from source options/answer", question_id=q.id))

        solution_text = q.solution.get("text", "").strip() if isinstance(q.solution, dict) else ""
        if has_solution_source and not solution_text:
            issues.append(Issue("MISSING_SOLUTION", f"{label} has no source solution text", question_id=q.id))

        if q.requires_figure and not q.assets:
            issues.append(Issue("MISSING_REQUIRED_IMAGE", f"{label} requires a source figure but has no question-specific crop", question_id=q.id))

        if not q.pages or any(not isinstance(p, int) or p < 1 or p > page_count for p in q.pages):
            issues.append(Issue("INVALID_PROVENANCE", f"{label} has missing/out-of-range source page provenance", question_id=q.id))
        if not (q.provenance or {}).get("source_sha256"):
            issues.append(Issue("INVALID_PROVENANCE", f"{label} is missing source PDF checksum provenance", question_id=q.id))
        if not any((q.bounds or [])):
            issues.append(Issue("INVALID_PROVENANCE", f"{label} has no source geometry bounds", question_id=q.id))

    return issues
