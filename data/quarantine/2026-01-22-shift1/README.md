# JEE Main 2026 — 22 January Shift 1 (Quarantined JSON)

## Status: NOT PRODUCTION READY

This folder preserves the generated 75-record JSON export from the source PDF. It is intentionally stored under `data/quarantine/`; do not import it into Cloudflare D1 or serve it as production question data yet.

## Source identity

- Exam: JEE Main 2026, Session 1
- Date / shift: 22 January 2026, Shift 1
- Paper: Paper 1 (B.E./B.Tech)
- Source PDF filename: `BPD4dLYdvGj7xm8cDL66.pdf`
- Source PDF SHA-256: `7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3`
- Source PDF pages: 24

## Dataset check

- Question records: 75, retained in source order
- Q39: retained in position 39; `question_status = "Dropped"`; `answer_text = "Dropped"`; no invented correct answer
- Records with a correct-answer value: 74
- Records with options: 60
- Records with solution text: 68
- Some transcription, notation, options, answer, and solution fields still need visual review against source pages.

## Image bundle and path warning

The source export's image paths are relative paths intended to resolve beside the JSON within its companion ZIP bundle. The ZIP contains 24 full-page JPEGs and the Q39 question crop (`images/questions/q039_question.jpg`); its SHA-256 is:

`b1c2358ef30469ed3ab16995f303e2d72cdfb78c26af58500b7229f805f40783`

**Important:** that ZIP has not been committed/extracted into this repository by this commit. Therefore the JSON's image paths are not yet resolvable from the repository checkout. Do not treat the JSON-only commit as a complete image-backed website dataset.

## Release gate

Before any Cloudflare production import or deployment:
1. Add the companion images beside this JSON, preserving the relative paths.
2. Visually compare every question, option, answer, and solution against the source page images; confirm the source and rights to reproduce the material.
3. Run schema, path-existence, completeness, answer/solution, duplicate, and question-number checks.
4. Keep the batch blocked until review is complete. Do not change the existing Worker, D1 binding, or production database as part of this quarantine commit.
