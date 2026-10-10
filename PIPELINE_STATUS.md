# Pipeline status

## Repairs applied on this branch

- Restored the parser helpers that the existing tests attempted to import.
- Made OCR fallback a single testable path; an OCR page that yields no words fails rather than producing empty placeholder records.
- Filtered full-page embedded scan images out of question-level image attachments. A full page is source context, not a question crop.
- Added a safe fallback for a detected question whose question-text region is empty; it records a blocking issue instead of crashing during bounding-box calculation.
- Strengthened validation of source SHA-256, source-document lineage, finite positive-area question bounds, placeholder text, duplicate IDs, and solution source references.
- Added a per-question source-review manifest bound to the source PDF hash, paper identity, and extracted-record fingerprint.
- Changed the batch contract: a clean automatic parse is `REVIEW_REQUIRED`, not `VALIDATED`. `IMPORT_READY.json` is emitted only after every applicable field/image check is explicitly reviewed.
- Prevented `--force-reextract` from deleting an existing batch's review evidence.
- Removed the stale CI workflow's hard-coded January paper claim. CI now runs parser/validator/crop/review-gate tests instead of incorrectly asserting that an unverified source is a green paper.

## Real-paper proof status

**Not complete.** The repository contains `full_jee_dataset_v2.json` labelled JEE Main 2026, 8 April Evening Shift, but that is a JSON dataset—not the exact source PDF needed to prove PDF extraction. The source PDF currently present under another filename has not been verified as 8 April Shift 2; it must not be used as a substitute for that paper.

The official 8 April Shift 2 source PDF was identified in the source manifest, but it could not be downloaded into this runtime during this repair. No claim is made that the target paper has been extracted, that its question figures were visually matched, or that its complete JSON is production-ready.

## Required proof for the target paper

A real proof must include the exact source PDF header and SHA-256, extraction counts/scope, source-page and question bounds, distinct question-level figure crops (no full-page question images), and a visual comparison of question text, all options, answer, solution and image links. The pipeline must remain `REVIEW_REQUIRED` until that per-question review is completed.

No production Worker, D1, or deployment was changed.
