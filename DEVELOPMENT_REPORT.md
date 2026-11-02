# ACFR caption extraction development report — release 0.2.1

## Outcome

Implemented and executed an offline Python 3.12 development release on the three
uploaded FY2025 reports. It supports all nine requested statement classes and
produces the six requested CSVs. The final sample run found 25 statements, marked
Juneau's two fiduciary statements absent, and produced 1,523 caption/heading rows
and 951 frequency rows across statement types and row kinds.

The software has not been established as production-ready for 25,000 ACFRs. Final
results are regression results on known sample documents, not an independent
population accuracy estimate. Windows and the optional Colab/Drive workflow have
not been executed in this Linux session.

## Actual sample inventory

| Uploaded PDF | Pages | Development role | Statements found |
|---|---:|---|---:|
| ACFR001__AK_City_and_Borough_of_Juneau_2025.pdf | 270 | Development | 7 |
| ACFR002__AK_State_of_Alaska_2025.pdf | 614 | Development | 9 |
| ACFR003__AL_Auburn_2025.pdf | 238 | Initial holdout; later regression | 9 |

All 1,122 pages were scanned for native text/title evidence. Alaska's basic
financial statement pages have a badly encoded text layer; local Tesseract OCR
recovered captions and statement titles. Its actual statement pages are 26–41;
reconciliation and intentionally blank pages within that interval are excluded.
Juneau's statements occupy pages 34–54 with gaps between statements. Auburn's
actual basic statements start on PDF page 83, after Single Audit and lengthy MD&A
material; condensed/illustrative statements in earlier pages must be excluded.

Original PDFs and original ZIP attachments were not edited. They are not included
in the release. sample_inventory.csv records source sizes and SHA-256 hashes.
Only one 2021 code archive was uploaded, despite one earlier prompt referring to
two. The second uploaded ZIP contains the three PDFs, not another code archive.
Original Google Drive file IDs were unavailable and remain empty, never fabricated.
Government names and fiscal years are supplied explicitly in sample_metadata.json.

## Legacy inspection and baseline

Inspected the uploaded Python source before execution. Original code was run with
modern dependencies in an isolated temporary output directory. It failed with:

```text
AttributeError: 'DataFrame' object has no attribute 'append'
```

The original pins include numpy 1.19.5, pandas 1.1.5 and pdfminer.six 20201018, which
are unsuitable as a modern Python 3.12 environment. The legacy finder also:

- stops at PDF page 60;
- excludes fiduciary headings;
- searches titles without adequate basic-statement/condensed-statement separation;
- repeats PDF text parsing and constructs all-pairs geometry graphs;
- uses fragile filename offsets and old ExcelWriter APIs;
- counts rows instead of distinct statement identities in frequency aggregation;
- does not provide robust OCR/resume paths.

The baseline saw all three reports, including Auburn; its detected candidate page
numbers were not used to tune the modern extractor. It found no Alaska statement
candidates in its native-text search. No valid complete legacy caption/frequency
baseline was produced, so no fabricated legacy accuracy or runtime comparison is
reported.

Reuse: retained and called utils/clean_amount.py as legacy_clean_amount.py for
numeric-token checks, with one raw-string correction. Adapted the legacy
same-row/bounding-box and indentation/category ideas, replacing its quadratic
NetworkX/Pandas table pipeline with sorted word geometry and ordinary Python.
Reused the statement-title vocabulary, expanded to nine classes. Replaced the
legacy digit-stripping caption cleanup, row-count aggregation, obsolete export
APIs and fixed-offset filename parsing. Full original source remains unchanged
in the user's uploaded archive; reused source attribution is retained.

## Implemented behavior

- Native word geometry, table-of-contents/printed-page/bookmark hints, reporting
  model context, header exclusions and continuation grouping.
- Statement search throughout the PDF; no first-60-page assumption.
- Government-wide and proprietary net-position distinction, including native and
  scanned enterprise-only cases exercised by synthetic tests.
- Original/OCR wording, source identity, fiscal year, statement identity, section,
  parent, one-based PDF page, recognizable printed page and location box.
- Conservative normalization with editable exact aliases and ambiguous-caption
  context keys; headings remain distinguishable from numeric line-item captions.
- Distinct statement/report/government frequencies, with extracted-statement
  denominators; repeated rows within a statement do not inflate frequency.
- Local optional OCR, cached by content hash and page; no paid/LLM document APIs.
- Recursive directories, process workers, per-report SQLite commits, atomic CSV
  replacement, hash/config-aware resume, retries for document-level failures.
- Read-only input processing; password/malformed cases are logged and other PDFs
  continue. Missing statements use absent/unknown rather than fabricated rows.
- Windows installation and operations instructions; a separate optional Colab
  notebook for user-authorized Drive mounting and saving.

## Measured validation and chronology

Auburn was reserved before developing the modern rules (one of three reports is
the nearest nonempty holdout to approximately 25%). Code/rules were frozen in
rule_freeze.json before modern holdout evaluation. The reference was transcribed
by the assistant from rendered PDF pages and reviewed against source TOCs/titles.
It is not an independent accountant's review or an externally adjudicated gold set.

The initial held-out run exposed a real failure: Auburn government-wide net
position was incorrectly absent when its two actual pages and other candidate
pages produced multiple ranges. Its printed page numbers share a baseline with a
notes footer, so the TOC location was not linked. Initial evidence is preserved
unchanged in Validation Results/initial_holdout.

| Measurement | Initial frozen run | Final 0.2.1 regression |
|---|---:|---:|
| Exact statement type/status/page membership, development reports | 18/18 | 18/18 |
| Exact statement type/status/page membership, Auburn | 8/9 | 9/9 |
| Exact statement checks, all reports | 26/27 (96.3%) | 27/27 (100%) |
| Juneau page 34 caption precision / recall | 56/56 / 56/56 | 56/56 / 56/56 |
| Alaska page 26 caption precision / recall | 37/37 / 37/37 | 37/37 / 37/37 |
| Auburn page 83 caption recall | 0/37 | 37/37 |
| Auburn page 83 caption precision | Undefined: no extracted rows | 37/37 |

The final measured reference comprises 130 caption/heading occurrences on three
net-position pages, including duplicates. Final precision and recall on this
reference are both 130/130. This does not mean every one of the 1,523 extracted
rows is correct. Caption accuracy for the other statement types, all other pages,
and section/parent assignments has not been comprehensively measured.

The Auburn defect was corrected after viewing holdout results. Therefore Auburn
is now a regression sample, not an untouched validation set for release 0.2.1.
A new, larger independent set is required before production accuracy claims.

19 automated tests passed with no skips, including actual Tesseract OCR on a
synthetic raster PDF. Tests cover all nine title classes, exclusions, ambiguous
net position, enterprise-only reports, statements after page 60, wrapped captions,
context keys, distinct frequencies/denominators, malformed/password PDFs,
multiprocessing, resume, changed normalization and footer-page references.
Tests also passed in a fresh Python 3.12 environment containing only the declared
runtime dependency, PyMuPDF 1.26.7. Tesseract is an external system prerequisite for
OCR; Poppler and Git were already installed in the development environment.

An identical --resume run skipped all three PDFs and regenerated all six CSVs
byte-for-byte. release_verification.json records hashes. Sample processing logs
from the final run used cached OCR, so their seconds must not be extrapolated as
cold OCR throughput or projected production runtime.

## Remaining limitations and recommended next work

1. Test a new, stratified independent sample: real enterprise-only special-purpose
   governments, scanned-only reports, restricted/malformed documents, rotated
   pages, long statements, different states and small governments. Current real
   examples are two municipalities and one state, all FY2025.
2. TOC absence inference remains heuristic. An incomplete TOC can make absence
   unreliable. Ambiguous candidates now stay unknown. Human review is still needed
   for unknown/review rows and reporting models beyond the examples.
3. Continuation searches linked to each TOC start cover up to 12 pages. Untitled
   continuations require explicit continued evidence. Unusual split/rotated tables
   can be missed; this is not a complete generic document-layout engine.
4. OCR is English-only and flagged for review. Column assignment, punctuation,
   wrapped labels and hierarchy can still be wrong. Rendered numerical amounts
   are not being validated or exported.
5. Frequency denominators use heuristic extracted-statement status, not audited
   full-statement completeness. Review partial extractions before statistical use.
6. Native parsing lacks a hard per-document subprocess timeout. Worker crashes and
   pathological PDFs need additional isolation/watchdog testing before unattended
   25,000-report production. A Tesseract page subprocess timeout is implemented.
7. Memory-bounded worker windows and SQLite exports are implemented, but 25,000-PDF
   load, multi-day interruptions, disk exhaustion and Windows have not been tested.
8. The Colab notebook was checked as valid notebook JSON/Python syntax only;
   account authentication, mounted folder access and Drive writes are untested.
9. PyMuPDF's AGPL/commercial terms and the supplied legacy archive's missing license
   require review before broader redistribution. No new license for legacy code is
   invented by this release.

## Delivery and Google Drive

No Google Drive tools were available in this Codex session. No existing Drive
folder was read or modified, and no deliverable has been uploaded there. The
uploaded files were the actual development inputs, used as temporary copies.
The downloadable release is ready for the user to store under:

ACFRS / ACFR Extraction Software / Releases

The ZIP organizes Source Code, Development Results and Validation Results. Keep
original ACFR PDFs in place. Run_in_Colab.ipynb offers an optional route to read
from and save into Drive using the user's own authenticated Colab session. The
standalone production program remains independent of Google services.
