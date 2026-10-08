# Bulk Source Verification — Final Gate

Status: BLOCKED_FOR_PRODUCTION_IMPORT

## Source checked
Samkarya/online-exam-questions

The JEE Main JSON files have the required question/option/answer/explanation structure, including 75-question paper files.

## Blocking issue
The repository declares an "ExamOven Non-Commercial Open Source License". Its README states that commercial use is reserved for ExamOven. This conflicts with a production JEE PYQ Master deployment that may use advertising/commercial distribution.

The repository README also identifies its content as an open-source question bank for ExamOven. The data provenance therefore cannot be treated as commercially cleared for our production database.

## Current decision
Do not copy these question records, solutions, images, or source data into the production dataset.
Do not import them into the existing D1.
Do not mark them IMPORT_READY.

## Validation code
pipeline/jee_pyq_pipeline/bulk_source.py remains the fail-closed structural validator/normalizer. It validates source records but intentionally does not create tables, change D1, call the API, or deploy a Worker.

## Required next source
A 10k+ JEE Main/Advanced dataset whose redistribution and commercial use are explicitly permitted, with source provenance that covers the underlying question/solution/image content.

Once such a source is available, the existing validator can produce the import-ready JSON without changing the existing Worker/D1 architecture.
