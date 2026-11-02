# Results for all 22 supplied ACFRs

ACFR22_results.xlsx contains all six complete result tables in one workbook.
The individual UTF-8 CSVs contain the same tabular data:

- caption_occurrences.csv — 5,671 caption/heading occurrences
- caption_frequencies.csv — 3,030 frequency rows
- statement_inventory.csv — 198 statement type/report combinations (124 present)
- caption_mapping.csv — original/standardized/context mappings
- processing_log.csv — all 22 reports completed; review per-row OCR/permission warnings
- validation_report.csv — 198 inventory checks and 191 checked captions/headings match

The extractor was rerun on all 22 PDFs. The five extraction/validation data CSVs
match the previously published data byte-for-byte; the processing log records the
latest run's timings. The workbook was checked against every CSV's row count and
contains no formulas, macros, or external connections.

On GitHub, open a CSV to preview it. For the Excel workbook, open ACFR22_results.xlsx
and choose Download raw file. Store permanent copies in the project's Google Drive.
These are regression results for the provided sample, not a population-wide accuracy
claim. Original PDFs are unchanged and are not included in this folder.
