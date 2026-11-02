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

## 0.3.0 — 19-report expansion and original-three regression

Normalize rotated geometry and align word/dictionary extraction flags; preserve
vertical TOC evidence while excluding decorative sidebars. Parse range endpoints,
comparative/plural titles, consumed wrapped entries, component-unit boundaries and
inline affiliated-organization exclusions. Classify primary-government enterprise
columns using reporting-model context. Include title-less and amounts-only panels,
with warnings, and exclude reconciliation pages repeating the preceding title.

Interpret scanned TOCs after OCR, retry unreadable mapped statement orientations,
and recover damaged titles only with TOC plus accounting structure. Preserve
indented headings and remove dotted leaders. Record page_rotation and ocr_rotation.

All 22 reports processed; 198 inventory checks and 191 checked caption/heading
occurrences match the reviewed regression reference. Original caption token streams
are preserved on all 40 original statement pages. 33 automated tests pass. Baseline,
final CSVs, references, hashes and limitations are published with the release.
