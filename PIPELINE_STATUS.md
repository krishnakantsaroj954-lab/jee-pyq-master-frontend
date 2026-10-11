# Pipeline status

The old OCR/text-first extractor has been replaced on the image-first branch.

Per question:
- question content = rendered image from the original PDF region;
- stored question text = empty;
- options = exactly A, B, C, D labels;
- solution content = rendered image from the original PDF solution region;
- no AI/generated/synthetic question or solution content.

OCR/PDF text is used only to locate boundaries. The original rendered pixels are what become the assets.

The batch never writes to D1/API. IMPORT_READY.json is created only when all image and provenance checks pass.
