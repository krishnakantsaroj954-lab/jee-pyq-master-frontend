# Pipeline status — 22 October 2026

## Repair in progress: Jan 22 Shift 1 source and OCR dry run

The previous dry-run config was wrong for this source and could not safely run:
- Repository-root `cEDaK5Wn5ILe4nOdotd6.pdf` is **28 January 2026 Shift 1**, not the requested 22 January paper.
- The source audit and the checked-in Jan 22 manifest identify the correct original as `BPD4dLYdvGj7xm8cDL66.pdf`, SHA-256 `7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3`.
- The exact original PDF is present in the conversation Library and its bytes were checked against that SHA-256; its cover explicitly says **22 January 2026 Shift 1**.
- The correct original PDF is not present in the GitHub repository. The repo does, however, contain 24 full source-page JPEGs plus `asset-manifest.json`, whose page-by-page byte sizes and hashes were created for that original PDF.
- The initial SHA guard correctly stopped extraction instead of reading the wrong Jan 28 paper.

## Fix on branch `fix/jan22-scan-ocr-dry-run-20261022`

The branch now:
1. Does not use or rename the wrong repository-root PDF.
2. Verifies all 24 Jan 22 source-page JPEGs against their pinned SHA-256 values and confirms the manifest's original PDF SHA-256.
3. Reconstructs a temporary **OCR derivative PDF** from those verified page images. This generated PDF is expressly not treated as byte-identical to the original PDF.
4. Points the representative config to that derivative, with 24 pages, 75 global question numbers in source order (Mathematics 1–25, Physics 26–50, Chemistry 51–75), and source section type bands (MCQ 1–20 etc.).
5. Runs parser tests plus a real-paper OCR dry run, preserves previous batch/review evidence, and writes no data to Cloudflare/D1.
6. Keeps the whole dataset read-only/unapproved until every question, option, answer, solution, dropped status and image association is verified against the source.

## Original source identity

- Original file recorded by the Jan 22 bundle: `BPD4dLYdvGj7xm8cDL66.pdf`
- Original SHA-256: `7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3`
- Source-page count: 24
- Page-image verification: must pass all 24 pinned hashes before the OCR step starts.

## Verification boundary

Passing the source-page checksum gate proves that the expected bundle page files are unchanged relative to the checked-in asset manifest; the manifest records the original PDF hash. OCR text, math notation, options, answer/solution association and figures are still untrusted until human review. The pipeline must remain `REVIEW_REQUIRED` / `QUARANTINED` until source review is complete and a content-bound review manifest is approved.

No production import, D1 write, Worker code change, or verified-data promotion is part of this repair.
