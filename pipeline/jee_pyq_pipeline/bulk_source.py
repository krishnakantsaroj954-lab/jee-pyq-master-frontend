from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

OPTION_KEYS = ("A", "B", "C", "D")


def _nonempty(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load either a JSON array or JSONL without modifying record content."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line_no, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_no} is not an object")
            rows.append(value)
        return rows

    value = json.loads(raw)
    if isinstance(value, list):
        if not all(isinstance(row, dict) for row in value):
            raise ValueError("JSON array must contain only objects")
        return value
    if isinstance(value, dict) and isinstance(value.get("questions"), list):
        rows = value["questions"]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("questions must contain only objects")
        return rows
    raise ValueError("Expected a JSON array, JSONL file, or an object with a questions array")


def _options(record: dict[str, Any]) -> dict[str, str]:
    if isinstance(record.get("options"), dict):
        source = record["options"]
        mapped: dict[str, str] = {}
        for key, value in source.items():
            if isinstance(key, str) and isinstance(value, str) and value.strip():
                mapped[key.upper()] = value
        return mapped

    mapped = {}
    for index, key in enumerate(("option_1", "option_2", "option_3", "option_4")):
        value = _nonempty(record.get(key))
        if value:
            mapped[OPTION_KEYS[index]] = value
    return mapped


def _answer(record: dict[str, Any], options: dict[str, str]) -> str | None:
    value = record.get("correct_answer")
    if isinstance(value, str) and value.strip():
        return value.strip().upper()

    value = record.get("correct_option")
    if isinstance(value, int) and 1 <= value <= 4:
        return OPTION_KEYS[value - 1]

    value = record.get("numerical_answer")
    if isinstance(value, (str, int, float)) and str(value).strip():
        return str(value).strip()

    # Some sources use answer as their primary field.
    value = record.get("answer")
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _question_type(record: dict[str, Any], options: dict[str, str]) -> str:
    raw = record.get("question_type")
    if isinstance(raw, str) and raw.strip():
        value = raw.strip().upper()
        if value in {"SINGLE_CORRECT", "MCQ"}:
            return "MCQ"
        if value in {"NUMERICAL", "INTEGER"}:
            return "NUMERICAL"
        return value

    if record.get("numerical_answer") not in (None, ""):
        return "NUMERICAL"
    if len(options) == 4:
        return "MCQ"
    return "UNKNOWN"


def normalize(record: dict[str, Any], source_name: str, row_number: int) -> dict[str, Any]:
    question_id = (
        _nonempty(record.get("question_id"))
        or _nonempty(record.get("id"))
        or f"{Path(source_name).name}:{row_number}"
    )
    text = record.get("question")
    if not isinstance(text, str):
        text = record.get("question_text", "")
    if not isinstance(text, str):
        text = ""

    options = _options(record)
    return {
        "id": question_id,
        "text": text,
        "options": options,
        "answer": _answer(record, options),
        "question_type": _question_type(record, options),
        "subject": _nonempty(record.get("subject")),
        "topic": _nonempty(record.get("topic")),
        "subtopic": _nonempty(record.get("subtopic")),
        "difficulty": _nonempty(record.get("difficulty")),
        "exam": _nonempty(record.get("exam")),
        "source_paper": _nonempty(record.get("source_paper")),
        "question_images": list(record.get("question_images") or []),
        "solution": record.get("solution") if isinstance(record.get("solution"), str) else "",
        "solution_images": list(record.get("solution_images") or []),
        "provenance": {
            "source_file": source_name,
            "source_row": row_number,
        },
    }


def validate_record(row: dict[str, Any], require_solution: bool) -> list[str]:
    issues: list[str] = []
    if not row["text"].strip():
        issues.append("MISSING_QUESTION_TEXT")

    kind = row["question_type"]
    if kind == "MCQ" and tuple(sorted(row["options"])) != OPTION_KEYS:
        issues.append("MCQ_REQUIRES_A_B_C_D")

    if not row["answer"]:
        issues.append("MISSING_ANSWER")

    if row["answer"] in OPTION_KEYS and row["answer"] not in row["options"]:
        issues.append("ANSWER_NOT_IN_OPTIONS")

    if "[IMAGE]" in row["text"] and not row["question_images"]:
        issues.append("QUESTION_IMAGE_MARKER_WITHOUT_ASSET")

    if require_solution and not row["solution"].strip() and not row["solution_images"]:
        issues.append("MISSING_SOLUTION")

    if not row["source_paper"]:
        issues.append("MISSING_SOURCE_PAPER")

    return issues


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(input_path: Path, output_dir: Path, min_count: int, require_solution: bool) -> int:
    rows = load_records(input_path)
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row_number, record in enumerate(rows, 1):
        row = normalize(record, str(input_path), row_number)
        issues = []
        if row["id"] in seen:
            issues.append("DUPLICATE_ID")
        else:
            seen.add(row["id"])
        issues.extend(validate_record(row, require_solution))

        if issues:
            rejected.append({"row": row, "issues": issues})
        else:
            normalized.append(row)

    blocking: list[str] = []
    if len(normalized) < min_count:
        blocking.append(f"VALIDATED_COUNT_BELOW_MINIMUM:{len(normalized)}<{min_count}")
    if not normalized:
        blocking.append("NO_VALIDATED_RECORDS")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validated.json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "rejected.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    subject_counts = {}
    for row in normalized:
        subject_counts[row["subject"] or "UNKNOWN"] = subject_counts.get(row["subject"] or "UNKNOWN", 0) + 1

    report = {
        "format": "jee-pyq-bulk-validation/v1",
        "status": "VALIDATED" if not blocking else "QUARANTINED",
        "source_file": str(input_path),
        "source_sha256": sha256_file(input_path),
        "input_count": len(rows),
        "validated_count": len(normalized),
        "rejected_count": len(rejected),
        "subject_counts": subject_counts,
        "blocking_issues": blocking,
        "require_solution": require_solution,
        "import_boundary": "This command validates and normalizes source data only. It never creates tables, changes D1, calls the API, or deploys a Worker.",
    }
    (output_dir / "validation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not blocking:
        manifest = {
            "format": "jee-pyq-bulk-import-ready/v1",
            "status": "VALIDATED",
            "validated_sha256": sha256_file(output_dir / "validated.json"),
            "rejected_sha256": sha256_file(output_dir / "rejected.json"),
            "report_sha256": sha256_file(output_dir / "validation-report.json"),
        }
        (output_dir / "IMPORT_READY.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(report, indent=2))
    return 0 if not blocking else 2


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed bulk JEE JSON/JSONL validator")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=Path("bulk-output"), type=Path)
    parser.add_argument("--min-count", type=int, default=10000)
    parser.add_argument("--require-solution", action="store_true")
    args = parser.parse_args(argv)
    if args.min_count < 1:
        parser.error("--min-count must be positive")
    return run(args.input, args.output, args.min_count, args.require_solution)


if __name__ == "__main__":
    raise SystemExit(main())
