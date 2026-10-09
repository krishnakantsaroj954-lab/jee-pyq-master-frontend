# JEE Main 2026 — 22 January Shift 1 (Quarantined Dataset)

## Status

- Image assets: `ASSETS_EXTRACTED_AND_HASH_VERIFIED`
- Production readiness: `NOT PRODUCTION READY`
- GitHub Actions verification run: https://github.com/krishnakantsaroj954-lab/jee-pyq-master-frontend/actions/runs/37977318124

This dataset remains under `data/quarantine/`. It must not be imported into Cloudflare D1 or served as production question data yet.

## Source identity

- Exam: JEE Main 2026, Session 1
- Date / shift: 22 January 2026, Shift 1
- Paper: Paper 1 (B.E./B.Tech)
- Source PDF filename: `BPD4dLYdvGj7xm8cDL66.pdf`
- Source PDF SHA-256: `7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3`
- Source PDF pages: 24

## Dataset checks

- Question records: 75, retained in source order
- Q39: retained in position 39; `question_status = "Dropped"`; `answer_text = "Dropped"`; no invented correct answer
- Records with a correct-answer value: 74
- Records with options: 60
- Records with solution text: 68
- Some transcription, notation, options, answer, and solution fields still need visual review against the source pages.

## Image assets — restored and verified

- Bundle SHA-256: `b1c2358ef30469ed3ab16995f303e2d72cdfb78c26af58500b7229f805f40783`
- Bundle integrity: passed
- JSON records checked: 75
- Referenced image paths checked: 25
- JPEG assets extracted and committed: 25 (24 full-page images + `images/questions/q039_question.jpg`)
- Asset hashes: recorded in `asset-manifest.json`

The JSON's relative image paths now resolve from this directory in the repository. The bundle has the expected source identity and Q39 remains marked as dropped. The verification run completed successfully.

## Release gate

Before any Cloudflare production import or deployment:

1. Visually compare every question, option, answer, and solution against the source page images; confirm source identity and rights to reproduce the material.
2. Run schema, path-existence, completeness, answer/solution, duplicate, and question-number checks after visual review.
3. Keep the batch blocked until all review checks pass.
4. Do not change the existing Worker, D1 binding, or production database as part of this quarantine dataset step.

## Website integration boundary

The repository currently contains the source/PDF pipeline, not the frontend application code. Restoring the JSON and matching image assets does not publish them on the live website. The website frontend still needs to be connected to this dataset in a separate, reviewed change. No Cloudflare Worker/D1 import or website deployment was performed by this workflow.
