# Pipeline status

## Implemented

- A one-paper, configuration-selected intake/extraction/validation/review-batch pipeline.
- Source and optional ZIP checksums; deterministic batch paths and JSON; per-asset object keys, source page/bounds and checksums.
- Geometric word extraction, question-number boundaries, A–D options, source-derived answer-key mapping, quarantine, and a non-importing atomic-import hand-off marker.
- Unit tests cover fail-closed validation gates using in-memory parser records only; no PYQ content is stored as application data.

## Verified

- Validator behavior is automated by the included test suite.
- No authorized source PDF, answer key, 03 Oct 2026 Blueprint file, Worker, D1 details, or import endpoint is in this repository; no source run can be verified yet.

## Run representative paper

`PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config /secure/config/representative-paper.json --output ./pipeline-output --max-pages 50 --timeout-seconds 1200`

A nonzero (2) status means quarantine/early failure. Review `validation-report.json`; never use the batch for import without `status: VALIDATED` and `IMPORT_READY.json`.

## Exact next step

Provide the authorized representative PDF, its reviewed source answer-key JSON, source-solution map when the source includes solutions, exact expected source question numbers, unambiguous source metadata, and the actual Blueprint; run the command once and manually review the generated package before any separately authorized atomic-import integration work.
