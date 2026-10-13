# Pipeline status

## Implemented

- One-paper, configuration-selected intake/extraction/validation/review-batch pipeline.
- Source and optional ZIP checksums; deterministic batch identity; per-asset page/bounds/checksums.
- Layout-aware extraction with side-by-side option support and subject-aware question keys.
- Combined JEE Main papers can use `Physics:1` ... `Chemistry:25` ... `Mathematics:25`, so repeated per-subject numbering is not treated as a duplicate.
- Source PDFs that contain questions + solutions are split at source Answer/Solution markers. The answer and solution evidence is emitted from the same PDF; no guessed/manual answer map is required.
- MCQ and numerical (Section B style) questions are both validated. Source option labels may remain A-D or 1-4; numerical questions are not forced into a four-option shape.
- Required source figures are associated from page geometry with bounded padding; solution assets are kept separately.
- Validated batch hand-off through `IMPORT_READY.json`; **no D1/API import code exists in this repository**.
- Successful batches are reusable by source PDF hash + page range; the runner refuses silent re-extraction.

## Representative dry-run wiring

The repository now contains CI wiring that, when the uploaded `cEDaK5Wn5ILe4nOdotd6.pdf` is present, verifies that the PDF identifies itself as JEE Main 2026 / Jan 28 / Shift 1, creates the exact 75-question PCM scope, runs the strict pipeline, and uploads the review batch as a workflow artifact. The dry-run never touches D1/API/live website.

## Verification boundary

The source PDF binary is stored in GitHub, but the connected GitHub file API available to this session cannot stream that binary into the local runtime, so the actual 28 Jan Shift 1 extraction result cannot honestly be marked green from this interface alone. The repository workflow is the execution gate for the real source file.

A green representative run must contain:
- `status: VALIDATED`
- 75 validated records
- 25 Physics + 25 Chemistry + 25 Mathematics
- MCQ/numerical type counts consistent with the source
- source answer and source solution evidence for every question
- no blocking validation issues
- `IMPORT_READY.json`

No live import should occur until that gate is green and the batch artifact is reviewed.


## Controlled verification

The representative workflow is dispatched manually or from pull requests and has a hard source-presence and green-batch gate; a missing source PDF can no longer skip extraction.
