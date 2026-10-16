# Pipeline status — 16 October 2026

## Fixed in the source-grounded parser branch

- Removed the placeholder-question generation path from the extraction code being proposed for `main`.
- Restored layout-aware PDF parsing with OCR fallback, source-page and geometry provenance, answer/solution marker handling, subject-aware question keys, explicit paper-specific question-type bands, and question/solution crop association.
- Added fail-closed checks for question count/scope, duplicates, missing or malformed options, absent/ambiguous answers, missing source solutions, invalid bounds/lineage, replacement glyphs, placeholder content, and required images.
- Added a per-question source-review manifest bound to the PDF SHA-256, paper identity, and extracted-record fingerprint.
- Changed the release boundary so automatic extraction remains `REVIEW_REQUIRED`; `IMPORT_READY.json` requires complete structural validation and explicit review approval.
- Preserved source-marked dropped-question records instead of silently omitting them.
- Replaced the old CI workflow's claim that a fixed 75-question run was automatically green with a lightweight test-only workflow. It does not generate question data, import to production, deploy, or upload large artifacts.

## What is not yet proven

**The real-paper extraction is not certified complete.** Tests against generated PDFs and helper fixtures prove only the tested parser behaviours. They do not prove the exact 16 MB source paper has correct question boundaries, answers, solutions, or image crops.

Before any paper can be marked ready, run the pipeline on the exact intended PDF, confirm the PDF header/identity and SHA-256, inspect the extraction report, visually compare every question/options/answer/solution and image association against the source, and finish the content-bound review manifest. Any missing or uncertain item must remain quarantined.

## Production boundary

No Cloudflare Worker code, D1 database/table, secret, deployment, or live import was changed by this branch. The website/API/database still require separate verification; this branch only addresses the source/PDF extraction pipeline. Do not treat these commits as a completed website or as a production-ready PYQ corpus.
