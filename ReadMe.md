# ACFR Caption Extractor 0.4.0

An offline, deterministic Python 3.12 development release for financial-statement
caption research. No LLM, paid processing API, Google account, or network connection
is required during extraction. Accuracy is heuristic; see DEVELOPMENT_REPORT.md
and validation_report.csv for measured results and limits. This is not a certified
25,000-report production system.

## Quick start

Create a Python 3.12 virtual environment and install requirements.txt. For OCR,
install Tesseract with English language data and put `tesseract` on PATH. PyMuPDF
handles native PDF text and rendering; Poppler remains available as an independent
inspection tool but is not a runtime dependency of this implementation.

```text
python acfr_extractor.py --input "PDF directory" --output "results directory" --workers 2 --ocr auto --resume
```

Use `--metadata sample_metadata.json` for government/fiscal year/Drive ID overrides.
Never invent Drive IDs from filenames. The sample IDs are blank because attachments
do not carry original Google Drive file IDs. Input PDFs are opened read-only and
never renamed, moved, or overwritten. Output must be a separate writable directory.

## Package contents

- acfr_extractor.py: nine statement types, geometry extraction, OCR, SQLite resume,
  CSV exports and reference evaluation.
- legacy_clean_amount.py: reused legacy numeric-cleaning component, attributed
  to the supplied 2021 caption-extraction-master archive; one raw-string fix.
- normalization.json: editable exact aliases and context-sensitive caption keys.
- tests/: executable functional and regression tests (standard unittest).
- verified_reference.json and build_reference.py: manually transcribed reference.
- sample_split.json and rule_freeze.json: development/holdout designation and hash.
- sample_metadata.json: explicit source identities, unknown Drive IDs left blank.
- WINDOWS_INSTALL.md, OPERATING_MANUAL.md, DEVELOPMENT_REPORT.md.
- Sample results and validation artifacts; original input PDFs are not redistributed.

## Validation

```text
python -m unittest discover -s tests -v
python acfr_extractor.py --input "sample PDFs" --output "sample results" --ocr auto --workers 2 --metadata sample_metadata.json --gold verified_reference.json --resume
```

The OCR test is skipped if Tesseract is unavailable. No reference file means
validation_report.csv explicitly says not_measured. A heuristic confidence label
is not a calibrated probability. The reference includes section headings and
caption occurrences (duplicates retained), not numeric values.

## Storage policy

Google Drive is the permanent project home. During this development session only
uploaded temporary copies were accessible. This software and result package must
be downloaded and uploaded by the user to Drive; no Drive folder was modified.
Suggested destination: ACFRS / ACFR Extraction Software / Releases. Keep PDFs in
their existing collection. Source Code, Development Results, and Validation Results
can be populated from the corresponding package files. No Drive connector or token
is embedded in this software.

## Third-party licensing

Review upstream licenses before distribution. PyMuPDF 1.26.7 is available under
AGPL/commercial licensing; use must comply with the selected license. Tesseract
uses Apache 2.0. The uploaded legacy archive did not include a license file; this
package does not invent distribution rights for its reused component. Reuse is
for the user's supplied project; resolve rights before broader redistribution.

## Drive sample validation (0.4.0)

Tested on the 48 PDFs of the Google Drive `Representative_ACFR_Sample_120`
folder that could be downloaded in the development session (36 development,
12 holdout; the 72 largest PDFs could not be transferred and are untested).
0.3.0 left 23 statements unresolved in 8 of those reports. 0.4.0 resolves all
432 report × statement-type cells (332 present, 100 absent) and matches all
153 available reference checks. 48 automated tests pass. See
[FULL_SAMPLE_VALIDATION.md](FULL_SAMPLE_VALIDATION.md) for method, the frozen
holdout measurement, per-report results and limitations. The final CSVs are
in validation/full_sample. Release ZIP: releases/acfr-caption-extractor-0.4.0.zip.

## Expanded validation (0.3.0)

Tested the original three reports plus 19 additional uploaded reports (22 PDFs,
4,266 pages). See [EXPANDED_VALIDATION.md](EXPANDED_VALIDATION.md) and
[validation/expanded/final/validation_report.csv](validation/expanded/final/validation_report.csv).
All 198 statement type/status/page-membership checks and 191 checked caption/heading
occurrences match the reviewed regression reference. 33 automated tests pass.
The original three retain their caption text across all 40 statement pages;
merged headings are now separate rows. These are regression measurements, not a
claim of accuracy on an unseen production universe.

```text
python acfr_extractor.py --input "all 22 sample PDFs" --output "results" --ocr auto --workers 2 --metadata validation/expanded/sample_metadata.json --gold validation/expanded/combined_reference.json --resume
```

The six combined CSV outputs are in validation/expanded/final. The preserved
0.2.1 baseline results for the 19 new reports are in validation/expanded/baseline_*.
PDFs, OCR images/caches, and checkpoints are not committed. For the complete
updated release, use releases/acfr-caption-extractor-0.3.0.zip.
