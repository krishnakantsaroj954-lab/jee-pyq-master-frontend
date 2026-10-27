# Legacy workspace archive — do not deploy or import

This is the old source/PDF extraction workspace. It is not the future website frontend, admin panel, API, or deployment target. The next ZIP/code uploaded by the owner is the source of truth for future frontend/admin work.

## Moved out of active paths

- `legacy-imports/jee_main_2026_04_08_shift_2_all_75_questions.json` — old April Shift 2 export.
- `legacy-pdfs/cEDaK5Wn5ILe4nOdotd6.pdf` — old pipeline test PDF.
- `legacy-workflows/d1-import-75q.yml` and `legacy-workflows/import_jee_json_to_d1.py` — old workflow/script that could write an old dataset to the existing D1 database.
- `legacy-workflows/d1-schema-audit.yml` — old production schema/data audit workflow.
- `legacy-workflows/unpack-jan22-image-bundle.yml` and `legacy-workflows/build_jan22_question_image_crops.py` — old paper-specific image-bundle workflow and crop script.

The files above are preserved for recovery/reference, but the workflow copies under this folder are no longer active GitHub Actions workflows.

## Existing quarantined bundle

`data/quarantine/2026-01-22-shift1/` remains in its already separate quarantine location. It contains an old Jan 22 Shift 1 JSON and associated page/crop images/manifests. It is explicitly **NOT PRODUCTION READY** and must not be served, published, or imported into D1.

## Boundaries

The remaining pipeline source and test-only CI are kept as historical/reference code. No Cloudflare Worker, API source, D1 table, database record, secret, or deployment was changed by this cleanup. Do not deploy this repository or run an old import workflow for future frontend work.
