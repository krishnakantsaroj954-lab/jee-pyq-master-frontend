# Image-first PDF pipeline v2

This directory is intentionally independent from the existing pipeline.

## Fixed behavior

- Source: `../cEDaK5Wn5ILe4nOdotd6.pdf` is the only PDF processed.
- Question content: exact rendered PDF page image(s).
- Options: exactly `A`, `B`, `C`, `D`; no option text is extracted.
- Solution content: exact rendered PDF page image(s).
- Stored question/solution text: none.
- Missing or ambiguous question/solution boundaries: fail closed.
- Writes to API/D1/Cloudflare/live site: none.
- Output is an Actions artifact for review; nothing is imported automatically.

The renderer uses full source pages rather than per-question crops. When multiple questions share a PDF page, each question references the same exact page image. This avoids accidental clipping or reconstruction.

The pipeline accepts both common 75-question numbering layouts:
1. global `1..75`
2. three subject runs of `1..25`

Solutions may be numbered in the same way or may be unnumbered, but there must be exactly 75 solution starts.

## Local command

```bash
python pipeline/image_first_pdf_v2/pipeline.py --self-test
python pipeline/image_first_pdf_v2/pipeline.py --pdf cEDaK5Wn5ILe4nOdotd6.pdf --output image-first-output
```

The GitHub Actions workflow runs the self-test and then validates the real PDF. It is scoped to the `image-first-pdf-v2` branch so the old `pipeline-ci.yml` is not changed or invoked by this pipeline's pushes.
