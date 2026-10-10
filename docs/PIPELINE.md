# Representative-paper source pipeline

## Safety contract
The runner processes only the configured source PDF. It uses PyMuPDF word geometry and OCR only when a page has no text layer. It does not connect to a database, Cloudflare Worker, API, or production import path.

A structurally clean extraction is **not** considered source-verified. The runner emits `IMPORT_READY.json` only when structural validation passes and a per-question review manifest approves every extracted record against the exact source hash and content fingerprint.

## Input contract
Supply an authorized source PDF and exact identity metadata. The source PDF may contain questions and solutions. This parser extracts answers/solutions only from visible source Answer/Solution sections; it does not generate missing answers or explanations. An answer-key PDF or external worked-solution source is not automatically reconciled by this parser. For a combined JEE Main paper, expected question keys use `Subject:Number` (for example `Physics:1`, `Chemistry:1`, `Mathematics:1`).

## Run
```bash
PYTHONPATH=pipeline python -m jee_pyq_pipeline.cli --config ./representative-config.json --output ./pipeline-output --max-pages 150 --timeout-seconds 1200
```

## Stages
1. Intake records the PDF/optional ZIP checksums, identity and page count.
2. Layout-aware extraction uses word coordinates to segment rows, columns, subjects and question boundaries.
3. Question text/options are separated from source Answer/Solution sections. OCR is used only when a page has no text layer, and empty OCR output fails closed.
4. Image extraction preserves page, bounds, stable object key and checksum. Full-page embedded scans are excluded from question image attachments; bounded figure crops may be created for text-detected diagrams. Question and solution assets remain distinct.
5. Structural validation checks count/scope, SHA-256 source lineage, bounding boxes, MCQ/numerical type, options, answers, notation, required figures, and source solution references.
6. If structure passes but no valid review manifest exists, the batch status is `REVIEW_REQUIRED` and `review-manifest-template.json` is emitted. The template binds each review to a question content hash.
7. A full review manifest must cover every question exactly once, match the paper identity/source checksum/content fingerprint, record reviewer and timestamp, and mark every applicable check true. Only then can the batch be `VALIDATED` and include `IMPORT_READY.json`.
8. Any blocking structural issue quarantines the batch. Dropped questions remain represented with status `Dropped`; they are never silently removed from the paper.

## Review manifest
Copy the generated `review-manifest-template.json`, compare each required field and figure association against the original source, and fill every listed check only after visual confirmation. Set each `review_status` to `verified`, and record `reviewer` and `reviewed_at`. Set `review_manifest` in the config to that completed file and run using a new output directory. If the extraction changes, the fingerprint changes and the previous approval is rejected.

## Reuse and evidence preservation
A source PDF hash plus page range identifies a batch. Existing batch output is never deleted by `--force-reextract`; use a new output directory for a fresh run and preserve prior review evidence.

## Verification boundary
The tests use a generated synthetic PDF to exercise parsing and the review gate. They are not proof that any external paper has been extracted accurately. Do not call a real paper verified until its exact source PDF is available, its header/checksum are recorded, and its question records and crops are actually reviewed.

This pipeline never touches production D1/API/website and never invents missing content.
