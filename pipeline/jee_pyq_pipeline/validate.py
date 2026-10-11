from __future__ import annotations
from pathlib import Path
from .models import Issue, Question

OPTION_LABELS = ("A", "B", "C", "D")

def _key(q: Question) -> str:
    return f"{q.subject}:{q.source_question_number}"

def validate(config, questions: list[Question], page_count: int) -> list[Issue]:
    issues: list[Issue] = []
    expected = set(getattr(config, "expected_question_numbers", ()))
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()

    if len(questions) != config.expected_question_count:
        issues.append(Issue("COUNT_MISMATCH", f"Expected {config.expected_question_count}; extracted {len(questions)}"))

    for q in questions:
        key = _key(q)
        if q.id in seen_ids:
            issues.append(Issue("DUPLICATE_ID", f"Duplicate question ID: {q.id}", question_id=q.id))
        seen_ids.add(q.id)
        if key in seen_keys:
            issues.append(Issue("DUPLICATE_SOURCE_NUMBER", f"Duplicate subject/question key: {key}", question_id=q.id))
        seen_keys.add(key)

        if key not in expected:
            issues.append(Issue("QUESTION_SCOPE_MISMATCH", f"Unexpected question key: {key}", question_id=q.id))
        if not q.subject or q.subject not in {"Physics", "Chemistry", "Mathematics"}:
            issues.append(Issue("MISSING_SUBJECT", "Question subject is not resolved", question_id=q.id))
        if not q.pages or any(p < config.page_range[0] or p > config.page_range[1] or p > page_count for p in q.pages):
            issues.append(Issue("INVALID_PROVENANCE", "Question image points outside the configured source PDF", question_id=q.id))

        if q.text:
            issues.append(Issue("QUESTION_TEXT_NOT_EMPTY", "Image-first mode must not synthesize/store question text", question_id=q.id))

        if q.options != {k: k for k in OPTION_LABELS}:
            issues.append(Issue("INVALID_LABEL_ONLY_OPTIONS", "Options must be exactly A/B/C/D labels", question_id=q.id))

        if not q.assets:
            issues.append(Issue("MISSING_QUESTION_IMAGE", "No source-PDF question image was produced", question_id=q.id))
        for asset in q.assets:
            path = Path(asset.get("path", ""))
            if not path.is_file() or path.stat().st_size < 100:
                issues.append(Issue("QUESTION_IMAGE_FILE_MISSING", f"Missing/empty question image: {path}", question_id=q.id))

        if not q.solution or q.solution.get("mode") != "source_pdf_image" or not q.solution.get("assets"):
            issues.append(Issue("MISSING_SOLUTION_IMAGE", "No source-PDF solution image was produced", question_id=q.id))
        for asset in (q.solution or {}).get("assets", []):
            path = Path(asset.get("path", ""))
            if not path.is_file() or path.stat().st_size < 100:
                issues.append(Issue("SOLUTION_IMAGE_FILE_MISSING", f"Missing/empty solution image: {path}", question_id=q.id))

        if config.require_answers and not q.answer:
            issues.append(Issue("MISSING_SOURCE_ANSWER", "Source answer was not explicitly recovered", question_id=q.id))

        if q.question_type == "UNKNOWN":
            issues.append(Issue("UNKNOWN_QUESTION_TYPE", "Question type could not be classified from the source image region", question_id=q.id))

        if any(token in str(q.provenance).lower() for token in ("placeholder", "sample option", "step-by-step", "generated")):
            issues.append(Issue("SYNTHETIC_CONTENT_MARKER", "Synthetic/demo content marker detected", question_id=q.id))

    actual = {_key(q) for q in questions}
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        issues.append(Issue("QUESTION_SCOPE_MISMATCH", f"Missing={sorted(missing)} Extra={sorted(extra)}"))
    return issues
