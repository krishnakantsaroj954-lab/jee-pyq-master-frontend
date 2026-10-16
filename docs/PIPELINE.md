# JEE PYQ source/PDF pipeline

## Purpose and safety boundary

This repository is the source-grounded extraction and review pipeline, not the deployed website or API. The runner processes one explicitly configured PDF at a time. It does not call network services, write to Cloudflare D1, edit Workers, deploy, or import data.

**A structurally clean extraction is not proof that the content is correct.** Automatic output must remain `REVIEW_REQUIRED` until each extracted record has been compared against the exact source PDF and the content-bound review manifest has been fully approved. Missing, ambiguous, malformed, synthetic, or weakly sourced data must be quarantined rather than guessed.

## Input configuration

The JSON config identifies the exact PDF and paper: `source_pdf`, `release`, `exam`, `year`, `session`, `paper`, `subject`, `page_range`, `expected_question_count`, and `expected_question_numbers`. For a combined paper, use explicit keys such as `Physics:1`, `Chemistry:1`, and `Mathematics:1`.

Optional `question_type_ranges` must come from the actual paper's printed section rules; the parser does not assume that a universal question-number range is numerical. Configure `source_has_solutions: true` only when the same supplied source PDF visibly contains the solution section.

## Run

```bash
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config ./representative-config.json --output ./pipeline-output --max-pages 150 --timeout-seconds 1200
```

The command emits a deterministic batch directory keyed by source PDF checksum and selected page range. It records source provenance, per-question boundaries, answers/solutions found in the PDF, image/crop assets, validation issues, and a review-manifest template.

## Required gates

1. Confirm the source PDF bytes and its identity; do not substitute a similarly named or different shift's paper.
2. Extract text and page geometry, using OCR only when needed. Ambiguous question boundaries or contaminated OCR must fail closed.
3. Keep each question, its options, answer, solution, page/bounds provenance, and question/solution image crops linked to the correct record.
4. Validate exact question scope and count, subject/question keys, question type, source answers, source solutions, notation, non-empty options, crop requirements, unique IDs, and source checksums.
5. Compare every item against the original PDF. Approve only checks actually verified in the review manifest. The approval is tied to source SHA-256, paper identity, and extracted-record fingerprint.
6. Consume only the exact checksummed batch marked by `IMPORT_READY.json`, and only after human review. This repository itself never imports the batch.

Dropped questions must remain represented with a `Dropped` status when that status is present in the source; they must not silently disappear from the paper count. A dropped question must not be given an invented answer or solution.

## Existing output safety

Source assets are preserved. Watermarking utilities operate on review/output copies and must not mutate the original PDF or the source asset. Never overwrite earlier review evidence to force a re-extraction; use a new output location when a clean rerun is required.

## Verification limitations

Unit tests exercise parser logic and validation rules on controlled fixtures. They do **not** establish that any real examination paper has been extracted accurately. A real-paper pass requires a dry run on the exact source PDF, inspection of its identity and SHA-256, a source-page/asset comparison for every question, complete solution/answer checks, and approval of the per-question review manifest. No production import, Worker edit, D1 write, or deployment is part of CI.
