# QuestionExtractorAI: GitHub-hosted test

This is an **experimental, isolated crop test** for the PDF in this private repository. It runs on a GitHub-hosted Ubuntu runner, so it does not require OpenCV to be installed in Termux.

## Run it

1. Open the repository on GitHub.
2. Go to **Actions** → **Experimental QuestionExtractorAI PDF crops** → **Run workflow**.
3. Keep `cEDaK5Wn5ILe4nOdotd6.pdf` as the PDF path for the first test.
4. Start with layout type `1`, top `0`, bottom `0`.
5. Open the completed run and download the `question-extractor-ai-output` artifact.

The artifact contains:
- `crops/`: candidate question-region images, intended to keep options/figures in the same crop where the detector groups them;
- `previews/`: page images with detected boxes drawn;
- `diagnostics/`: threshold and dilation images for troubleshooting;
- `manifest.json`: page number, crop file path, and bounding-box coordinates.

## Important limitations

The upstream repository labels itself **Work in progress**. It uses layout/contour heuristics; despite its project name, the current code does not provide a finished neural-network model and it does not OCR text. These crops are not automatically verified questions, and this workflow does not extract correct answers, solutions, subjects, chapters, or topics. Some crops may be merged incorrectly or split incorrectly. Check the previews and every crop manually.

This job only saves an artifact. It does **not** import anything into D1, modify website data, publish question records, or change production files. The external source is pinned to commit `6206db58972bb4a06cf7d8e1294a89cd6c2fd729` so a future upstream change cannot silently alter this test.

For a different PDF already committed to the repository, change the `pdf_path` input to its repository-relative path when running the workflow.
