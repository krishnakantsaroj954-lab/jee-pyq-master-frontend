# JEE Main 2026 — 22 January Shift 1 (Quarantined Dataset)

## Current status
- 75 question records remain in source order; Q39 remains present and marked Dropped without an invented answer.
- 24 original full-page source images are retained under images/pages/.
- Question-specific crops: 19 figure/table/graph crops plus the pre-existing Q39 question crop.
- Six printed-solution crops were created for questions whose solution text is missing/unreadable in the JSON.
- question_image_path and solution_image_path now point only to specific crops or null; source_page_image_path preserves the full-page source.
- All 50 JPEG assets are listed with SHA-256 values in asset-manifest.json; crop coordinates/metadata are in image-crop-manifest.json.

## Important review gate
The crop boxes were estimated from source-page previews and are not claimed to be perfect. Review each crop for cut-off labels, stray text, and correct question association, then review all OCR/transcription, options, answers, and solution text against the original PDF. Several dataset records remain incomplete or OCR-only. This is not production-ready and must stay under data/quarantine/.

No Cloudflare Worker/D1 import, production database change, or website deployment was performed. The repository still needs a separate reviewed frontend integration change.
