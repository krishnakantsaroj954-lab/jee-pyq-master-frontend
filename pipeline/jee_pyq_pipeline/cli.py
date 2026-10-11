from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path

from .config import load
from .extract import extract
from .util import sha256_file, write_json
from .validate import validate

VERSION = "1.0.0"

def _build_batch(config, output_dir: Path):
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(config.source_pdf)
    questions, assets, extraction_issues, page_count = extract(config, assets_dir)
    issues = extraction_issues + validate(config, questions, page_count)
    status = "VALIDATED" if not any(i.blocking for i in issues) else "QUARANTINED"

    for q in questions:
        q.status = "VALIDATED" if status == "VALIDATED" else "QUARANTINED"
        q.issues.extend([i for i in issues if i.question_id == q.id])
        for asset in q.assets + q.solution_assets:
            p = Path(asset["path"])
            if p.is_absolute():
                asset["path"] = str(p.resolve().relative_to(output_dir.resolve())).replace("\\", "/")
            else:
                asset["path"] = str(p).replace("\\", "/")

    records = {
        "validated": [q.json() for q in questions if q.status == "VALIDATED"],
        "quarantined": [q.json() for q in questions if q.status == "QUARANTINED"],
        "rejected": [],
    }
    checksums = {
        name: write_json(output_dir / f"{name}.json", values)
        for name, values in records.items()
    }

    checksums["source_answers"] = write_json(
        output_dir / "source-answers.json",
        {
            "source_document": config.source_pdf.name,
            "source_sha256": source_hash,
            "answers": {
                f"{q.subject}:{q.source_question_number}": q.answer
                for q in questions if q.answer is not None
            },
        },
    )
    checksums["source_solutions"] = write_json(
        output_dir / "source-solutions.json",
        {
            "source_document": config.source_pdf.name,
            "source_sha256": source_hash,
            "mode": "source_pdf_image",
            "solutions": {
                f"{q.subject}:{q.source_question_number}": (q.solution or {}).get("assets", [])
                for q in questions
            },
        },
    )

    write_json(output_dir / "source-intake.json", {
        "pipeline_version": VERSION,
        "release": config.release,
        "source_pdf": config.source_pdf.name,
        "source_pdf_sha256": source_hash,
        "pdf_page_count": page_count,
        "selected_page_range": list(config.page_range),
        "identity": {
            "exam": config.exam,
            "year": config.year,
            "session": config.session,
            "paper": config.paper,
            "subject": config.subject,
        },
        "image_mode": {
            "question": "rendered PDF regions",
            "options": ["A","B","C","D"],
            "solution": "rendered PDF regions",
        },
    })

    report = {
        "validator_version": VERSION,
        "status": status,
        "counts": {k: len(v) for k, v in records.items()},
        "question_type_counts": {
            kind: sum(1 for q in questions if q.question_type == kind)
            for kind in ("MCQ","NUMERICAL","UNKNOWN")
        },
        "subject_counts": {
            s: sum(1 for q in questions if q.subject == s)
            for s in ("Physics","Chemistry","Mathematics")
        },
        "answer_count": sum(1 for q in questions if q.answer is not None),
        "asset_count": len(assets),
        "blocking_issue_count": sum(1 for i in issues if i.blocking),
        "issues": [i.__dict__ for i in issues],
    }
    write_json(output_dir / "validation-report.json", report)

    manifest = {
        "format": "jee-pyq-image-first/v1",
        "run_id": output_dir.name,
        "status": status,
        "validator_version": VERSION,
        "source_intake": "source-intake.json",
        "records": checksums,
        "asset_count": len(assets),
        "import_boundary": "No D1/API writes. IMPORT_READY is emitted only after a fully validated source-image batch.",
    }
    checksums["manifest"] = write_json(output_dir / "batch-manifest.json", manifest)

    if status == "VALIDATED":
        write_json(output_dir / "IMPORT_READY.json", {
            "status": "VALIDATED",
            "run_id": output_dir.name,
            "manifest_sha256": checksums["manifest"],
            "validated_json_sha256": checksums["validated"],
            "source_answers_sha256": checksums["source_answers"],
            "source_solutions_sha256": checksums["source_solutions"],
            "image_contract": {
                "question": "source PDF render only",
                "options": ["A","B","C","D"],
                "solution": "source PDF render only",
            },
            "instruction": "Import exactly this batch and reverify checksums. Do not OCR-rewrite source content.",
        })
    return status

def run(config_path: Path, output_root: Path, max_pages: int, force_reextract: bool) -> int:
    config = load(config_path)
    if config.page_range[1] - config.page_range[0] + 1 > max_pages:
        raise ValueError(f"Configured scope exceeds max-pages={max_pages}")
    if not config.source_pdf.is_file():
        raise FileNotFoundError(f"Source PDF is missing: {config.source_pdf}")

    source_hash = sha256_file(config.source_pdf)
    run_id = f"{source_hash[:16]}-{config.page_range[0]}-{config.page_range[1]}"
    final_dir = output_root / run_id
    if final_dir.exists() and not force_reextract:
        raise FileExistsError(f"Batch already exists at {final_dir}; use --force-reextract explicitly")

    tmp = output_root / f".{run_id}.partial"
    if tmp.exists():
        shutil.rmtree(tmp)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    tmp.mkdir(parents=True)

    try:
        status = _build_batch(config, tmp)
        tmp.replace(final_dir)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    print(final_dir)
    return 0 if status == "VALIDATED" else 2

def main(argv=None):
    p = argparse.ArgumentParser(description="JEE PYQ image-first fail-closed source PDF pipeline")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output", default=Path("pipeline-output"), type=Path)
    p.add_argument("--max-pages", type=int, default=150)
    p.add_argument("--force-reextract", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.max_pages < 1:
            raise ValueError("max-pages must be positive")
        return run(args.config, args.output, args.max_pages, args.force_reextract)
    except Exception as exc:
        print(f"EARLY FAIL: {exc}")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
