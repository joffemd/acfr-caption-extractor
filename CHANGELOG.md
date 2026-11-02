# Change log

## 0.1.0 — frozen initial validation baseline

Nine statement classes, native/OCR extraction, normalization, frequencies, CSVs and
SQLite resume. Initial holdout detected 8/9 Auburn statement types/ranges. Evidence
and initial extraction-code hashes are retained separately.

## 0.2.0 — regression fixes

Recognize printed labels sharing a baseline with notes footers. Preserve TOC
statement declarations independently of label mapping. Multiple ambiguous candidate
ranges cannot be classified absent.

## 0.2.1 — final development release

Retain relevant pre-table headings. Revisit ambiguous scanned enterprise-only net
position after OCR recovers corroborating cash-flow/operating statements. 19 tests
pass, including OCR, and all three sample reports have correct reference statement
membership. Added Windows guide, operating manual, optional Colab notebook and
measured development report. This is a development release, not production approval.
