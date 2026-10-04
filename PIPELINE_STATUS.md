# Pipeline status

## Implemented

- One-paper, configuration-selected intake/extraction/validation/review-batch pipeline.
- Source and optional ZIP checksums; deterministic batch identity; per-asset object keys, source page/bounds and checksums.
- Layout-aware question extraction with stricter question-start parsing and support for multiple option labels in one visual row.
- Fail-closed validation for count, numbering, provenance, four-option structure, suspiciously short content, unsafe notation, required figures, answer-key provenance/scope, and source-solution scope.
- Validated batch hand-off through `IMPORT_READY.json`; **no D1/API import code exists in this repository**.
- Successful batches are reusable by source hash + page range; the runner refuses silent re-extraction.

## Verified locally

- Python compilation succeeds after repairing the broken `extract.py`.
- Validator test suite: **13/13 passed**.
- No live D1/API/website data is touched by this pipeline.

## Representative paper status

The uploaded repository PDF is now present, but a live representative extraction has **not** been claimed yet because the pipeline input contract still requires reviewed source answer-key/solution maps and exact page scope. Those must be prepared from the same source PDF before the first extraction is accepted.

## Run

`PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config /secure/config/representative-paper.json --output ./pipeline-output --max-pages 50 --timeout-seconds 1200`

A nonzero (2) status means quarantine/early failure. A green run must contain both `status: VALIDATED` and `IMPORT_READY.json`.
