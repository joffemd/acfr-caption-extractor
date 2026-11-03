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

## 0.4.0 — Google Drive sample run (48 of 120 reports)

Tested against the Representative_ACFR_Sample_120 Drive folder. Only the 48 PDFs
small enough for the Drive connector (36 development, 12 holdout) could be
downloaded; the other 72 remain untested. See FULL_SAMPLE_VALIDATION.md.

Fixes, each found on a real report:

- TOC page ranges written with figure dashes (U+2012), "16 and 17", "to" or
  "through" now give both endpoints (Hawaii, Greenville, Charleston).
- TOC lines prefixed by a bare exhibit letter ("C Balance Sheet") are parsed (Cary).
- Missing printed page numbers (odd-page-only numbering) are inferred for TOC mapping
  when neighbouring pages agree on the offset (Louisville).
- A "Table of Contents" back-link printed on every page no longer makes every page a
  TOC page; a TOC page must also look like a contents listing (Duluth: 0 -> 9
  statements).
- Statement titles are found line by line below running headers ("Annual
  Comprehensive Financial Report for the Year Ended...") and navigation tab bars
  ("INTRODUCTORY SECTION FINANCIAL SECTION STATISTICAL SECTION"); prose mentions in
  MD&A and notes are not titles (Portland, Louisville, Lakewood, Frederick).
- Component-unit and FASB foundation statements ("Statement of Net Position -
  Component Units", "Statements of Financial Position/Activities") are excluded and
  bound TOC ranges, so they no longer flip a college or university to the
  government-wide model (Hawaii, ASU, Oakton, Louisville).
- Fiduciary title variants: "Statement of Additions, Deductions and Changes in
  Fiduciary Net Position", "Statement of Changes in Net Position - Fiduciary Funds",
  and the typo "NET POSITON" (Scott County, Pittsburgh, White Plains).
- "The Statement of Fund Net Position" (leading "The") is a title (Cedar Rapids).
- Small statements whose amounts are mostly dashes are extracted (White Plains).
- Untitled numeric continuation pages directly after a statement page, and untitled
  left-hand pages of spreads whose title is printed on the right, are included
  (Cedar Rapids, Lakewood, Livonia).
- Tesseract runs single-threaded (parallelism comes from workers) and retries a slow
  page once with a longer timeout; an OCR timeout on Freehold's TOC page had made
  its statements unresolvable.

Reference correction: three Lakewood page ranges in combined_reference.json omitted
continuation pages (recorded under "corrections" with the reason).

## 0.5.0 — all 120 Drive sample reports

After the environment's network policy was widened, the remaining 72 (larger)
sample PDFs were downloaded and size-checked. 0.4.0 run unchanged on all 120
(frozen measurement): 102/120 fully resolved; all 18 failures were among the
72 new reports (54/72 resolved), 80 unresolved statement slots. 0.5.0: 119/120
resolved; St. Louis has a scrambled text layer and is left for review.

Fixes, each found on a real report:

- TOC page numbers that recur (Single Audit sections numbered from 1, statistical
  tables) are resolved to the occurrence carrying a statement title, other entries
  follow the dominant page offset; a TOC range holding none of the titled pages is
  ignored with `toc_page_mapping_ignored` (Ohio, Pennsylvania, Boston, Tarrant).
- Page numbers in footers with the entity name ("16 City of Boston,
  Massachusetts") and dash-wrapped header numbers ("-19-") (Boston, Sussex).
- Number-first TOC lines ("36 Statement of Net Position"), including contents
  pages with a garbled title; exhibit codes ("A-1 ... 26") are not page numbers
  (Phoenix, UNC Chapel Hill, Freehold).
- "Enterprise Fund Financial Statements" style TOC section headings set context.
- Landscape pages stored with a /Rotate that leaves all text vertical are read in
  the orientation where text runs left to right; the extra rotation is reported
  in `ocr_rotation` (Pennsylvania).
- Two statements on one page are split at the second title (UNC).
- Prior-year statements "for comparative information purposes" are excluded (MTC).
- The fiduciary fund type is taken from the title, not header-area text
  (Cincinnati); fiduciary component units count as fiduciary funds (MWAA);
  "ACTIVITES" typo (Olmsted); TOC-linked pages with an irregular title such as
  "Schedule of Revenues, Expenditures, and Changes in Fund Balances - Proprietary
  Funds" take the TOC type when their structure matches (`title_from_toc`, Boise).
- Without a usable TOC, absence is inferred from a fully readable, native-text
  basic-statement section that ends at the notes
  (`absence_inferred_from_statement_section`; Truckee Donner, DC Water).
- Symbol-soup text layers from broken font encodings, and statements drawn as
  vector outlines with only a footer as text, are routed to OCR (Carmel, Miami).
- A second OCR pass covers statement pages first located by an OCR-recovered TOC;
  rotated scans retry orientation even without a TOC link; OCR title recovery
  never assigns a component-unit statement (Miami, Carmel).
- Amount-only right-hand spread pages are continuations; header-area text no
  longer counts as a different title (Ohio, Tarrant, Deschutes, MWRD).
- Workers are kept busy: a new report starts as soon as any finishes instead of
  waiting for a batch (full 120-report cold run: 31 -> 17 minutes).
- Optional `ACFR_DEBUG=1` prints detected pages and TOC windows per report.
