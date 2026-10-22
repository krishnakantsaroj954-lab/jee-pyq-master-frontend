# Pipeline status — 22 October 2026

## Repair in progress: exact Jan 22 source dry run

The existing dry-run script was not correctly targeted to the paper the user asked to extract:
- It searched for selectable-text markers for **28 January 2026**, so a scanned/image-only PDF could be rejected before the OCR fallback ever ran.
- It wrote/remade a generic config using the wrong paper identity and assumed subject-local question numbering, while the currently staged 75-question paper follows global question numbering: Mathematics 1–25, Physics 26–50, Chemistry 51–75.
- It used `rm -rf pipeline-output`, which could erase prior review evidence.
- It treated the expected review-required CLI exit as an early shell failure and looked for output manifests at the wrong directory level.

The repair on branch `fix/jan22-scan-ocr-dry-run-20261022`:
- Pins the run to `cEDaK5Wn5ILe4nOdotd6.pdf` and the 22 January 2026 Shift 1 identity.
- Uses the known 24-page paper scope and explicit global question-number/MCQ/numerical ranges.
- Checks the PDF's SHA-256 against the existing Jan 22 bundle metadata before OCR; a mismatch blocks extraction instead of silently using a different paper.
- Allows OCR for scanned pages rather than requiring selectable text.
- Preserves old pipeline output and reports `VALIDATED`, `REVIEW_REQUIRED`, or `QUARANTINED` results without importing to Cloudflare/D1.
- Adds a GitHub Actions real-PDF dry-run job, with no large artifact upload.

## Source gate

Expected PDF SHA-256, recorded in the existing Jan 22 bundle metadata:

`7d633fea3bf16857bc4c477d80b2a3eb2535603b54f665c3d683b777f02f52f3`

The real OCR extraction may only run if the checked-in PDF bytes match this value and the 24-page/configuration checks pass. If the root PDF does not match, the pipeline must stop; do not rename the file or change the expected hash to force a pass. The actual hash and exact mismatch will be reported by CI.

## Verification boundary

Unit-test success proves code paths/fixtures, not the accuracy of a real paper. Even after a successful OCR run, every question, option, answer, solution, dropped label, page/source association, and crop must be checked against the original PDF. The parser's output should remain `REVIEW_REQUIRED` or `QUARANTINED` until the content-bound per-question source review is complete.

No production import, D1 write, Worker code change, or data deployment is part of this repair.
