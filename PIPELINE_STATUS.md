# Pipeline status

## Implemented

- One-paper, configuration-selected intake/extraction/validation/review-batch pipeline.
- Source and optional ZIP checksums; deterministic batch identity; per-asset page/bounds/checksums.
- Layout-aware extraction with side-by-side option support and subject-aware question keys.
- This representative JEE Main 2026 source uses global source numbering: Mathematics 1–25, Physics 26–50, Chemistry 51–75; stable keys preserve that exact scope.
- Source PDFs that contain questions + solutions are split at source Answer/Solution markers. The answer and solution evidence is emitted from the same PDF; no guessed/manual answer map is required.
- MCQ and numerical (Section B style) questions are both validated. Source option labels may remain A-D or 1-4; numerical questions are not forced into a four-option shape.
- Required source figures are associated from page geometry with bounded padding; solution assets are kept separately.
- Validated batch hand-off through `IMPORT_READY.json`; **no D1/API import code exists in this repository**.
- Successful batches are reusable by source PDF hash + page range; the runner refuses silent re-extraction.

## Representative dry-run wiring

The repository CI verifies the pinned `cEDaK5Wn5ILe4nOdotd6.pdf` as JEE Main 2026 / Jan 28 / Shift 1, uses the exact source-global 1–75 scope, runs the strict pipeline, and uploads the review batch as a workflow artifact. It never touches D1/API/live website.

## Verification boundary

The source PDF binary is stored in GitHub, but the connected GitHub file API available to this session cannot stream that binary into the local runtime, so the actual 28 Jan Shift 1 extraction result cannot honestly be marked green from this interface alone. The repository workflow is the execution gate for the real source file.

A green representative run must contain:
- `status: VALIDATED`
- 75 validated records
- 25 Physics + 25 Chemistry + 25 Mathematics
- 60 MCQ + 15 numerical records, matching the source's 20 + 5 structure per subject
- source answer and source solution evidence for every question
- no blocking validation issues
- `IMPORT_READY.json`

No live import should occur until that gate is green and the batch artifact is reviewed.
