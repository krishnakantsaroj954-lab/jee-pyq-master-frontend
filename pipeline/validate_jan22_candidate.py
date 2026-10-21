#!/usr/bin/env python3
"""Offline structural consistency audit for the Jan 22 2026 candidate.

This script checks relationships among the already-extracted candidate fields and
watermarked files. It does not certify source-PDF bytes, answer correctness against
an independent source, publication rights, or OCR solution accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

EXPECTED_ANSWERS = {1: "A", 2: "B", 3: "C", 4: "D"}
EXPECTED_MANUAL_TEXT = set(range(5, 39)) | set(range(40, 76))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data/quarantine/2026-01-22-shift1", type=Path)
    args = ap.parse_args()
    root = args.data_dir.resolve()
    errors: list[str] = []
    notes: list[str] = []

    candidate_path = root / "IMPORT_CANDIDATE.json"
    blocked_path = root / "IMPORT_BLOCKED_REPORT.json"
    manifest_path = root / "watermark-manifest.json"
    if not all(p.is_file() for p in (candidate_path, blocked_path, manifest_path)):
        missing = [str(p) for p in (candidate_path, blocked_path, manifest_path) if not p.is_file()]
        raise SystemExit("Required candidate QA input missing: " + ", ".join(missing))

    candidate = read_json(candidate_path)
    blocked = read_json(blocked_path)
    watermark = read_json(manifest_path)
    questions = candidate.get("questions")
    if not isinstance(questions, list):
        raise SystemExit("Candidate questions field is not a list")

    numbers = [q.get("question_number") for q in questions]
    ids = [q.get("question_id") for q in questions]
    if len(questions) != 75 or sorted(numbers) != list(range(1, 76)):
        errors.append("Candidate must contain question numbers exactly 1..75.")
    if len(set(ids)) != len(ids):
        errors.append("Duplicate question_id values found.")

    missing_text = [q.get("question_number") for q in questions if not str(q.get("question_text") or "").strip()]
    if missing_text:
        errors.append(f"Blank question_text records: {missing_text}")

    manual_numbers = {
        int(q["question_number"])
        for q in questions
        if q.get("question_text_review_status") == "MANUALLY_TRANSCRIBED_FROM_QUESTION_CROP"
    }
    if manual_numbers != EXPECTED_MANUAL_TEXT:
        errors.append(
            "Manual-transcription coverage mismatch: "
            f"missing={sorted(EXPECTED_MANUAL_TEXT - manual_numbers)}, "
            f"unexpected={sorted(manual_numbers - EXPECTED_MANUAL_TEXT)}"
        )

    q_images = [q.get("question_image_path") for q in questions]
    if len(set(q_images)) != 75 or any(not p for p in q_images):
        errors.append("Question image references must be non-empty and unique for all 75 records.")

    referenced_paths: set[str] = set()
    for q in questions:
        for field in (
            "question_image_path",
            "question_figure_image_path",
            "solution_image_path",
            "source_page_image_path",
            "question_source_crop_path",
        ):
            value = q.get(field)
            if value:
                referenced_paths.add(str(value))
    for rel in sorted(referenced_paths):
        path = root / rel
        if not path.is_file():
            errors.append(f"Candidate image reference missing on disk: {rel}")

    mcq_count = numeric_count = answer_checked = 0
    answer_mismatches: list[dict] = []
    option_mismatches: list[int] = []
    no_solution: list[int] = []
    flagged_solution_numbers: list[int] = []
    for q in questions:
        n = int(q.get("question_number", -1))
        dropped = q.get("question_status") == "Dropped" or q.get("correct_answer_status") == "dropped_in_source"
        flags = q.get("quality_flags") or []
        if "solution_math_ocr_requires_review" in flags or "math_ocr_requires_review" in flags:
            flagged_solution_numbers.append(n)
        if dropped:
            if n != 39 or q.get("correct_answer") is not None or q.get("correct_answer_raw_from_pdf") != "(Dropped)":
                errors.append(f"Dropped-source record contract violated at Q{n}.")
            continue

        raw = str(q.get("correct_answer_raw_from_pdf") or "")
        match = re.search(r"\(\s*([0-9]+)\s*\)", raw)
        if not match:
            answer_mismatches.append({"question": n, "raw_answer": raw, "stored": q.get("correct_answer"), "reason": "cannot parse printed answer"})
        else:
            printed = match.group(1)
            if q.get("question_type") == "single_correct_mcq":
                mcq_count += 1
                expected = EXPECTED_ANSWERS.get(int(printed)) if int(printed) in EXPECTED_ANSWERS else None
                if expected != q.get("correct_answer"):
                    answer_mismatches.append({"question": n, "raw_answer": raw, "stored": q.get("correct_answer"), "expected": expected})
                options = q.get("options")
                if not isinstance(options, dict) or not all(str(options.get(k) or "").strip() for k in ("A", "B", "C", "D")):
                    option_mismatches.append(n)
                elif str(q.get("answer_text") or "").strip() != str(options.get(q.get("correct_answer")) or "").strip():
                    option_mismatches.append(n)
            elif q.get("question_type") == "numerical_value":
                numeric_count += 1
                if str(q.get("correct_answer")) != printed:
                    answer_mismatches.append({"question": n, "raw_answer": raw, "stored": q.get("correct_answer"), "expected": printed})
            else:
                errors.append(f"Unexpected question_type at Q{n}: {q.get('question_type')!r}")
            answer_checked += 1

        if not (str(q.get("solution_text") or "").strip() or q.get("solution_image_path")):
            no_solution.append(n)

    if answer_mismatches:
        errors.append("Printed answer marker/stored answer consistency mismatches found.")
    if option_mismatches:
        errors.append(f"MCQ options/answer_text consistency failures: {sorted(set(option_mismatches))}")
    if no_solution:
        errors.append(f"Non-dropped questions with neither solution text nor solution image: {no_solution}")

    q39 = next((q for q in questions if q.get("question_number") == 39), {})
    if q39.get("question_status") != "Dropped" or q39.get("correct_answer") is not None or q39.get("answer_text") != "Dropped":
        errors.append("Q39 must remain Dropped without an invented answer.")

    watermarked = watermark.get("outputs", [])
    watermark_checks = []
    if watermark.get("source_image_count") != 125 or len(watermarked) != 125:
        errors.append("Watermark manifest must describe exactly 125 watermarked derivatives.")
    for item in watermarked:
        rel = str(item.get("output_path") or "")
        file_path = Path(rel)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.is_file():
            errors.append(f"Watermark output missing: {rel}")
            continue
        digest = sha256(file_path)
        ok = digest == item.get("output_sha256") and digest != item.get("source_sha256")
        watermark_checks.append(ok)
        if not ok:
            errors.append(f"Watermark output checksum/change check failed: {rel}")
    if len(watermark_checks) != 125 or not all(watermark_checks):
        errors.append("Not all 125 watermark derivatives passed checksum/change validation.")

    # The import gate must remain closed while independent review is pending.
    if blocked.get("status") != "BLOCKED_REVIEW_REQUIRED":
        errors.append("Blocked report unexpectedly does not say BLOCKED_REVIEW_REQUIRED.")
    if blocked.get("production_import") != "NOT_PERFORMED":
        errors.append("Blocked report unexpectedly claims a production import was performed.")
    if blocked.get("source_pdf_bytes_verified_by_GitHub_runner") is not False:
        errors.append("This run must not claim source PDF bytes are verified.")
    if (root / "IMPORT_READY.json").exists():
        errors.append("IMPORT_READY.json exists despite unresolved review gates.")

    report = {
        "schema_version": "1.0.0",
        "paper_id": candidate.get("paper", {}).get("paper_id"),
        "status": "STRUCTURAL_CONSISTENCY_PASSED_REVIEW_STILL_REQUIRED" if not errors else "STRUCTURAL_CONSISTENCY_FAILED",
        "question_count": len(questions),
        "manual_question_text_transcriptions": len(manual_numbers),
        "mcq_records_checked": mcq_count,
        "numerical_records_checked": numeric_count,
        "non_dropped_printed_answer_consistency_checked": answer_checked,
        "printed_answer_mismatch_count": len(answer_mismatches),
        "mcq_option_answer_text_mismatch_count": len(set(option_mismatches)),
        "unique_question_image_paths": len(set(q_images)),
        "referenced_image_paths_checked": len(referenced_paths),
        "watermarked_derivatives_checksum_checked": len(watermark_checks),
        "solution_math_ocr_review_required": len(flagged_solution_numbers),
        "q39": {"status": q39.get("question_status"), "correct_answer": q39.get("correct_answer")},
        "source_pdf_bytes_verified": False,
        "publication_rights_verified": False,
        "production_import": "NOT_PERFORMED",
        "errors": errors,
        "limitations": [
            "Answer consistency is checked against the answer marker stored in the same extracted candidate; it is not an independent solution of the question.",
            "Manual question-text transcription does not verify OCR solution text, chapter/topic tags, original PDF bytes, source provenance, or publication rights.",
            "This audit is not approval to import into production."
        ]
    }
    out = root / "candidate-internal-qa.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
