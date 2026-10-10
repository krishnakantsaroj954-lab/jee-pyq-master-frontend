# 8 April 2026 Shift 2 — source sample QC

**Result: FAIL / QUARANTINED SAMPLE. Do not treat this as a green 75-question paper.**

## Sources and scope

- Target: JEE Main 2026, 8 April Shift 2, Paper 1 (B.E./B.Tech.).
- Official NTA PDF: https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/04/20260409932754345.pdf
- The official PDF text layer identifies “B Tech 8th Apr 2026 Shift 2”, 300 marks, and 31 pages.
- Secondary text reference used for a limited content spot-check (not treated as an official answer key): https://static.zollege.in/public/image/JEE_Mains_2026_April_8_shift_2_Question_Paper_with_Solution_06659e1bde1dd3627fc13b72752d185b.pdf
- Dataset checked: `full_jee_dataset_v2.json` on `main`, 75 records, SHA is recorded by GitHub's current blob history.

## One-record observation

The 26th array item (zero-based index 25), record ID `mnsik5l1`, corresponds by its question concept/options to the first Mathematics question in the reference paper.

- **Question text:** key mathematical information is missing from `question.text`. The finite set is rendered without its members and the defining inequality is absent. This makes the statement incomplete and unsuitable for students.
- **Options:** four option labels and option text are present in the JSON record.
- **Answer encoding:** `correct_answer` is a nested API-response-shaped object (including `corrects: [0]`) rather than a normalized answer field. It needs explicit mapping and source-key verification before import.
- **Image association:** not verified in this sample.
- **Visual review:** not completed. The source PDF was accessible to the web text parser, but its screenshot could not be fetched by the inspection tool in this run.
- **Source checksum:** not obtained in this runtime because the PDF binary could not be downloaded. No SHA-256 is guessed.

## Decision

This spot-check is **not passed**. It is concrete evidence that JSON parseability and having four options do not prove mathematical-text fidelity. The 8 April Shift 2 dataset must remain unapproved until all 75 questions have complete notation, normalized answer mapping, accurate solutions, correct subject/question identity, and question-specific image references checked against the source.

## Pipeline boundary

The repair branch's automatic batch status is now `REVIEW_REQUIRED` unless a complete per-question review manifest is provided and its fingerprints match the exact source PDF and extracted records. The synthetic-PDF CI tests do not claim the real 8 April paper is verified. No production Worker, D1, API, or deployment is changed.
