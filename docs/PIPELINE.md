# Representative-paper pipeline

## Safety contract

The runner processes exactly the one paper named by `--config`. It uses PyMuPDF word geometry (not a plain-text extraction fallback), has no network access, no database code, no Worker code, and cannot import. A batch may produce `IMPORT_READY.json` only when every validation gate is green. That marker is a hand-off artifact, not an importer.

`75 questions` is only an expected dataset-count check; it does not mean 75 mock papers.

## Input contract

Supply an authorized PDF and a source-derived answer-key JSON outside version control. The configuration must include resolved, unambiguous `release`, `exam`, `year`, `session`, `paper`, `subject`, `page_range`, `expected_question_count`, exact `expected_question_numbers`, and `source_has_solutions`; absent/unknown/ambiguous identity stops early. When source solutions exist, a source-derived `source_solutions` JSON map is mandatory. Optional `source_zip` is checksummed.

The answer/solution maps are provenance inputs, not generated guesses. A source map must be reviewed against the source document before it can make a batch import-ready.

## Run

```bash
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config /secure/config/representative-paper.json --output ./pipeline-output --max-pages 50 --timeout-seconds 1200
```

Install the pinned runtime dependency first: `python -m pip install -e .`.

## Stages and outputs

1. Intake checks paths and records source ZIP/PDF checksums, release, identity and PDF page count in `source-intake.json`.
2. The selected page range is extracted with word positions. Column/row geometric ordering and option-label evidence form question boundaries. Images are extracted with page, bounds (when exposed by PDF), stable object key, and checksum.
3. Only whitespace/line-join normalization is performed. Source wording is retained.
4. Validation produces `validated.json`, `quarantined.json`, `rejected.json`, `validation-report.json`, `batch-manifest.json`, and assets. Any blocking failure makes the whole batch `QUARANTINED`.
5. A reviewer inspects the source pages, assets, records and report. Only a green batch receives `IMPORT_READY.json`.

## Reuse rule

A successful validated batch is keyed by the source PDF SHA-256 and selected page range. If `IMPORT_READY.json` and its manifest checksum still match, rerunning the command **reuses the existing batch and does not extract the PDF again**. The exact validated batch directory/artifact is the input to the later importer.

The only way to intentionally replace an existing batch is the explicit `--force-reextract` flag.

## Boundaries and limitations

Processing is one bounded PDF/page range per invocation: serial (concurrency 1), default 50 selected pages maximum, with a 1,200-second hard process alarm. No corpus loop or retries exists. The runner fails early on missing files and missing PyMuPDF. Complex tables, formulas, figures, answer keys and solutions remain fail-closed: ambiguous or truncated output is quarantined rather than silently repaired. This repository still has no frontend, Worker, D1 client, or importer.
