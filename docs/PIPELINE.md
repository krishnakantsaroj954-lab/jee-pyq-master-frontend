# Representative-paper pipeline

## Safety contract

The runner processes exactly the one paper named by `--config`. It uses PyMuPDF word geometry (not a plain-text extraction fallback), has no network access, no database code, no Worker code, and cannot import. A batch may produce `IMPORT_READY.json` only when every validation gate is green. That marker is a hand-off artifact, **not** an importer.

`75 questions` is only an expected dataset-count check; it does not mean 75 mock papers.

## Input contract

Supply an authorized PDF and a source-derived answer-key JSON outside version control. The configuration must include resolved, unambiguous `release`, `exam`, `year`, `session`, `paper`, `subject`, `page_range`, and `expected_question_count`, exact `expected_question_numbers`, and `source_has_solutions`; absent/unknown/ambiguous identity stops early. When source solutions exist, a source-derived `source_solutions` JSON map is mandatory. Optional `source_zip` is checksummed. The answer key has this shape:

```json
{"source_document":"authorized-paper.pdf","answers":{"1":"A"}}
```

The answer key itself must be reviewed against its source before use. This is an interface example, not question data.

## Run

```bash
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config /secure/config/representative-paper.json --output ./pipeline-output --max-pages 50 --timeout-seconds 1200
```

Install the pinned runtime dependency first: `python -m pip install -e .`.

## Stages and outputs

1. Intake checks paths and records source ZIP/PDF checksums, release, identity and PDF page count in `source-intake.json`.
2. The selected page range is extracted with word positions. Column/row geometric ordering, number evidence, and option labels form question boundaries. Images are extracted with page, bounds (when exposed by PDF), stable object key, and checksum.
3. Only whitespace/line-join normalization is performed. Source wording is retained.
4. Validation produces `validated.json`, `quarantined.json`, `rejected.json`, `validation-report.json`, checksummed `batch-manifest.json`, and assets. Any blocking failure makes the whole batch `QUARANTINED`.
5. A reviewer inspects source pages, assets, records and report. Only a green batch receives `IMPORT_READY.json`; a separately authorized external atomic importer must reverify it.

## Boundaries and limitations

Processing is one bounded PDF/page range per invocation: it is serial (concurrency 1), defaults to 50 selected pages maximum, and has a 1,200-second hard process alarm. No corpus loop or retries exists. The runner fails early on missing files and missing PyMuPDF. Complex table, formula, figure and answer-key fidelity must be reviewer-approved: ambiguous/truncated output is quarantined rather than repaired. A source PDF and the Blueprint itself are not present in this repository, so no representative paper has been executed or verified.
