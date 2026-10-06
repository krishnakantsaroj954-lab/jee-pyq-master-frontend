# Image-first PDF pipeline v2

This is a completely isolated pipeline. It does not modify or call the existing
pipeline or its workflow.

## Exact source

The workflow pins the requested file `cEDaK5Wn5ILe4nOdotd6.pdf` to its known Git
blob and verifies the PDF has exactly 24 pages and zero searchable text
characters. The source is therefore treated as a scanned/image-only PDF.

## Output contract

For each of the 75 questions:

- `question_text` is `null`.
- `solution_text` is `null`.
- `options` are exactly A, B, C, D.
- `question.image_refs` points to the exact rendered source-PDF page image.
- `solution.image_refs` points to the exact rendered source-PDF page image.
- No question or solution content is invented, paraphrased, or OCR-reconstructed.

The 75-question page map is explicitly checked in
`question-page-map.json` and comes from visual verification of this exact
source PDF.

## Safety boundary

This pipeline only prepares a review artifact. It never writes to the API,
D1, Cloudflare, or the live website. `IMPORT_READY.json` is only a review
marker and requires independent checksum/source verification before any future
import implementation.

## Files

`pipeline/image_first_pdf_v2/pipeline.py` — isolated renderer/validator.

`.github/workflows/image-first-pdf-v2.yml` — isolated GitHub Actions workflow.

The existing `pipeline/jee_pyq_pipeline/*` and
`.github/workflows/pipeline-ci.yml` are not part of this pipeline.
