# Representative-paper pipeline

## Safety contract
The runner processes exactly the configured paper. It uses PyMuPDF word geometry and source-page image assets, has no network access, no database code, no Worker code, and cannot import. A batch receives IMPORT_READY.json only when every validation gate is green.

## Input contract
Supply an authorized source PDF and exact identity metadata. The source PDF may contain both questions and solutions. Answers and solutions are extracted from that same source PDF; they are not generated or manually guessed. For a combined JEE Main paper, expected question keys use `Subject:Number` (for example `Physics:1`, `Chemistry:1`, `Mathematics:1`).

## Run
```bash
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config ./representative-config.json --output ./pipeline-output --max-pages 150 --timeout-seconds 1200
```

## Stages
1. Intake records PDF/ZIP checksums, identity and page count.
2. Layout-aware extraction reconstructs rows/columns and identifies subject/question boundaries.
3. Question text/options are separated from source Answer/Solution sections.
4. Images are extracted with page, bounds, stable object keys and checksums; question and solution assets are kept separately.
5. Validation checks count, subject/question scope, provenance, MCQ/numerical type, answers, required figures, notation and source solutions.
6. The batch is atomic. Any blocking failure quarantines the whole run. A green batch emits source-answers.json, source-solutions.json, validated.json and IMPORT_READY.json.

## Reuse rule
A successful validated batch is keyed by source PDF SHA-256 and selected page range. If IMPORT_READY.json and the manifest checksum still match, rerunning reuses the existing batch and does not extract the PDF again. Explicit --force-reextract is required to replace it.

## Boundaries
This pipeline never touches D1/API/live website and never invents missing content. Ambiguous or truncated content is quarantined.
