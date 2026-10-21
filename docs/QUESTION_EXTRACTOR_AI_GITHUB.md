# QuestionExtractorAI: GitHub-hosted crop experiment

This isolated experiment uses the existing source PDF in this private repository. It runs on a GitHub-hosted Ubuntu runner, so OpenCV does not need to be installed on Android/Termux.

## Run it

1. Open this repository on GitHub.
2. Go to **Actions** → **Experimental QuestionExtractorAI PDF crops**.
3. Select branch **test/question-extractor-ai-github-runner** and choose **Run workflow**.
4. Keep the default PDF path and use layout type 2 (two-column) with top/bottom 0 for this PDF.
5. When complete, inspect the folder **qa-artifacts/question-extractor-ai-review/** on the same test branch. The workflow commits only compact review images, a compact manifest, and a summary, rather than uploading a large Actions artifact.

## Review files

- **page_overview.jpg**: source-page overlays with detected bounding regions.
- **candidate_crop_overview.jpg**: thumbnails of candidate regions, labelled by page and detector index.
- **manifest.json**: source identity, extraction settings, per-page counts, and candidate bounding boxes.
- **summary.md**: quick count/status report and limitations.

Full-resolution crops, threshold maps, and dilation maps are temporary CI files.

The first type-1 run was not visually acceptable: it produced page-sized regions and thin footer fragments across much of this PDF. The workflow now defaults to type 2 because the source pages use a two-column layout. The review output still requires a human visual check; page-spanning and extremely thin candidate regions are called out as warnings, and geometry crops are never import-ready.

## Important limitations

The upstream **TaroAndMulan/QuestionExtractorAI** repository labels itself **Work in progress**. This is contour/geometry-based detection, not a validated question-understanding model. It does not OCR question text and does not extract correct answers, solutions, subjects, chapters, or topics. Candidate boxes may combine several questions or split one question into multiple regions. A high crop count is not evidence of correct extraction.

**Do not import these candidate regions into the live website.** They are only a visual diagnostic. The existing fail-closed source-grounded JEE data pipeline remains separate; no Worker, D1, API, production deployment, or live data is changed by this experiment. The external source is pinned to commit 6206db58972bb4a06cf7d8e1294a89cd6c2fd729.
