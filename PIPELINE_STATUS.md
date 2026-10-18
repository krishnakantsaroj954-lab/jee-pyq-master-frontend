# Pipeline status — 16 October 2026

## Fixed and merged to `main`

- Removed the fake 75-record generator that had fabricated question text, generic options, guessed answers, and placeholder solutions instead of reading the source PDF.
- Restored source-grounded PDF parsing with page geometry, two-column layout handling, OCR fallback, source answer/solution marker splitting, subject-aware question keys, source-specific question-type ranges, and bounded question/solution crop association.
- Added strict checks for paper scope/count, duplicate IDs and question keys, malformed options, missing/ambiguous answers, absent source solutions, invalid source lineage/bounds, notation damage, placeholder content, and required images.
- Added a per-question source-review manifest bound to the source PDF SHA-256, paper identity, and extracted-record fingerprint.
- The automatic parser now remains `REVIEW_REQUIRED` even when structural checks pass. `IMPORT_READY.json` requires a complete review approval; uncertain data stays quarantined.
- Kept source-marked dropped-question records with `Dropped` status rather than silently removing them.
- Replaced the old CI workflow's false claim that a fixed synthetic 75-question run was green with a test-only workflow. CI makes no production writes, deploys nothing, and uploads no large artifacts.

## Automated verification

- Pull request #13 was merged on 16 October 2026.
- GitHub Actions run **190** completed successfully. The parser/source-validation/review-gate/watermark test step passed; the run executed 61 tests.
- This proves the tested code paths and fixtures pass. It does **not** prove any real paper's question text, answers, solutions, or image crops are correct.

## What remains unverified

**The real-paper extraction is not certified complete.** The exact intended 16 MB PDF has not been re-run and visually reviewed here with the repaired parser. Before a paper can be marked ready, confirm the exact PDF's identity and SHA-256, run a dry extraction, inspect the validation report and question count/scope, compare every question/options/answer/solution/image against the same source PDF, and complete its content-bound review manifest. Do not substitute a different date or shift. Missing or uncertain items must remain quarantined.

The user-facing website/API/database also require separate verification; this is only the source/PDF pipeline.

## Production boundary

No Cloudflare Worker code, D1 database/table, secret, production import, or deployment was changed. Do not treat this pipeline repair or green unit tests as a completed website or as a production-ready PYQ corpus.
