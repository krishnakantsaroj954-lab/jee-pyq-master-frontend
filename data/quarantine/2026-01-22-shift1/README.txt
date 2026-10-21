# JEE Main 2026 — 22 January Shift 1 (Quarantined source dataset)

## Dataset and image assets
- 75 question records are retained in printed source order.
- Q39 remains marked `Dropped`; the source dropped label is preserved and no correct answer has been invented.
- Original full-page source images are preserved under `images/pages/`.
- 75 full-question image crops are generated under `images/questions/`; they preserve the printed question material, options and diagrams in source reading order and normally stop before the printed `Ans.` row.
- The previous 19 question figure/table crops are retained and linked through `question_figure_image_path`; the six solution crops remain under `images/solutions/`.
- The JSON retains original OCR/transcription/answer/solution fields; this crop script does not rewrite their text values.
- `asset-manifest.json` and `full-question-crop-manifest.json` contain hashes, dimensions, source locations and crop metadata.

## Mandatory review status
**REVIEW_REQUIRED — NOT production-ready.** OCR-based start/answer boundaries and all 75 visual crops require human comparison against the source page images. Three source question-number headers (Q1, Q7 and Q51) use explicit source-checked anchors because OCR missed or misjoined the printed number; these are marked in the manifest. Review all question text, options, answers, solution text/image, and question-to-image associations before any website import.

This pipeline does not write to Cloudflare D1, does not publish question records, and does not deploy or alter a production Worker. No production import was performed.
