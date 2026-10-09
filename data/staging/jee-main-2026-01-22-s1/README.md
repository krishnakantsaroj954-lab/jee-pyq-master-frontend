# JEE Main 2026 — 22 January Shift 1 (STAGING ONLY)

This branch preserves the current 75-record JSON export. It is deliberately isolated from `main`.

## Safety status

- **Production import: BLOCKED.**
- No Cloudflare Worker, D1 binding, production database, or deployment was changed by this commit.
- The uploaded source PDF cover identifies this paper as **22 January 2026 Shift 1**.
- All 75 question numbers are retained in order. Q39 is retained with `answer_text: "Dropped"`, `correct_answer: null`, and `correct_answer_status: "dropped_in_source"`; no answer is guessed.
- Structural counts do not establish that every transcription, answer, or solution is accurate. OCR/notation flags require review.
- The companion image ZIP is **not yet present in this Git branch**. JSON image paths are relative to the ZIP root, so the images must be copied into the repository or hosted and the paths remapped before production.

## Files

- `jee_main_2026_01_22_shift1_FINAL_75Q.json` — exact staged JSON export.
- `JEE_Main_2026_01_22_Shift1_EXTRACTION_STATUS.md` — extraction status note.
- `DATABASE_SCHEMA_REFERENCE.sql` — reference only; do not execute against production D1 automatically.

## Structural counts

- Question records: 75
- Non-empty question text: 75
- Options present: 60
- Correct answer values present: 74
- Non-empty solution text: 68
- Question + source-page image paths present: 75

These counts are not a content validation pass. Do not connect an automatic production import to this folder until images are present, records are reviewed, and the import dry-run passes.
