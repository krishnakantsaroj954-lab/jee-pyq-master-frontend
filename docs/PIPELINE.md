# JEE PYQ image-first pipeline

The pipeline is source-image based.

For every question:
1. Locate the question boundary using PDF geometry/text only.
2. Render that original PDF region to PNG.
3. Store no OCR-reconstructed question text.
4. Store only literal option labels A/B/C/D.
5. Locate the matching source solution block and render it to PNG.
6. Preserve page, bounds, render DPI, object key and SHA-256.

The PDF is the source of truth. OCR, when necessary, is a locator only; it never becomes the stored question, option or solution content.

Fail-closed behavior:
- wrong question count => quarantine;
- wrong source numbering => quarantine;
- missing subject heading => fail;
- missing question image => quarantine;
- missing solution image => quarantine;
- synthetic/placeholder content => quarantine.

The pipeline never imports to D1/API and never modifies the live website.
