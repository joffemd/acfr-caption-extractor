# Operating manual

## Statement codes

GW_NET_POSITION, GW_ACTIVITIES: government-wide.
GF_BALANCE_SHEET, GF_OPERATING: governmental funds.
PF_NET_POSITION, PF_OPERATING, PF_CASH_FLOWS: proprietary funds.
FF_NET_POSITION, FF_CHANGES: fiduciary funds.

The table of contents, printed footer labels and PDF bookmarks provide candidate
locations. Every native page is scanned; there is no first-60-page cutoff.
Actual page headers and numeric table rows must corroborate a statement.
Government-wide versus proprietary net position uses reporting-model evidence:
governmental/primary-government columns, fund headings, TOC context, and the
presence of enterprise operating/cash-flow statements without governmental ones.
Unresolved net-position titles are not automatically labeled government-wide.
Combining, reconciliation, condensed, budget comparisons and notes are excluded;
cash-flow reconciliation pages within the cash-flow statement remain included.

Continuation pages with repeated statement titles are grouped. Untitled pages need
an explicit continued marker and adjacent numeric table evidence. Multiple separated
candidate groups are unknown, not arbitrarily merged. TOC-linked continuation
search currently covers 12 pages per start; longer statements require review.
An extraction status of extracted means the heuristic produced table rows, not that
all captions or every page has been verified by a person.

## OCR modes

- off (default): native text only; malformed text can cause unknown statements.
- auto: OCR suspect TOC/bookmark-linked statement pages and nearby continuations.
  Without usable TOC hints, OCR suspect pages across the document. For badly encoded
  documents this can be expensive. Pages outside a usable TOC-guided range are not
  all OCR-checked; absence and completeness need review.
- all: scan native text throughout and OCR every suspect page. Healthy text is still
  used natively; this is not forced OCR of every page.

Tesseract OCR is local, English, 220 dpi, with a 120-second subprocess timeout per
page. JSON OCR caches are temporary working data under output/ocr_cache. OCR labels
are marked review. Amounts in OCR are not validated or exported as financial data.
A printed label is recorded when the footer is a recognized standalone label;
otherwise the field is empty. PDF pages and location boxes remain available.

## Outputs

- caption_occurrences.csv: source SHA-256 document ID, government, year, filename,
  relative source path, optional original Drive ID, statement ID/type, wording,
  standardized caption, context key, section/parent, one-based PDF page, printed
  page, PDF-point box (top-left origin), heading/caption kind, native/OCR, warning.
- caption_frequencies.csv: distinct statement, report and government counts per
  statement type and context key. Rows are separated by heading/caption kind.
  Repeated labels within one statement are counted once. Denominators contain only
  distinct statements marked present/extracted, excluding absent/unknown/failed.
- statement_inventory.csv: nine rows per PDF with present/absent/unknown,
  extraction status, exact page membership and range, TOC candidate pages, warnings.
  Absent is inferred only when a readable mapped basic TOC contains at least four
  statement types and omits the type. This is evidence-based but still heuristic;
  an incomplete TOC can invalidate absence. Unknown means review is necessary.
- caption_mapping.csv: original/standardized/context mappings, headings and captions.
- processing_log.csv: per-document outcome, pages, row counts, OCR pages, runtime,
  errors. A report-level processed status is not a claim of perfect accuracy.
- validation_report.csv: reference measurements if --gold is supplied; otherwise
  explicitly not_measured. Precision/recall use normalized caption multisets, so
  duplicate occurrences and headings count. Reference evaluation does not measure
  section/parent correctness, numerical values or unreferenced pages.
- progress.sqlite: durable per-PDF results and cache fingerprints. Not a deliverable
  to edit manually. Keep it with results for resume; export CSVs are reproducible.

Original wording is the PDF text layer or OCR transcription; OCR can differ from
the visual source. Boxes are unions of caption words across wrapped lines. Full
numeric table data is not retained; PDF source and row coordinates permit later
numeric extraction. Complete numeric extraction is outside this release.

## Normalization and identities

Edit normalization.json aliases to approve exact equivalences. Rules perform NFKC,
lowercase, punctuation-to-spaces and whitespace collapse; they do not stem or
remove digits. Context is included for listed ambiguous labels. Normalization
changes re-export on --resume without reprocessing PDFs. Grouping governments uses
case-insensitive supplied names, not an authoritative entity registry; provide
consistent names in --metadata to avoid merging/splitting governments incorrectly.
Same-content PDF duplicates share the SHA-256 statement identity and do not inflate
frequencies. Different fiscal years are distinct reports; a statement identity is
content hash plus statement type. Drive IDs must be supplied via --metadata.

## Batch and resume

Start with 1-2 workers; measure memory before increasing. Native text and geometry
are read a page at a time. Text summaries remain per-document; rendered images are
created only for OCR pages and deleted. Each finished PDF is committed atomically
in SQLite; CSV exports are replaced atomically on normal completion/interruption
handled by Python. A hard kill may leave older CSVs but committed PDFs are reused
on --resume. Re-running exports reconstructs the CSVs. Failed PDFs are retried.
Changed file content, extraction code, OCR mode, or metadata invalidates resume
cache. Removed inputs are removed from the checkpoint on the next run. Use separate
output directories per input collection. OCR caches are keyed by content hash/page.
Do not edit the cache or run concurrently into one output directory.

Exit 0: no document-level failures (unknown statements can still exist).
Exit 1: one or more failed PDFs; other PDFs and inventory are still exported.
Exit 2: invalid configuration/input or startup failure. Review processing_log.csv
and every unknown or review row. Password-required PDFs are logged, not unlocked.
Permission-restricted PDFs carry a warning. No credentials are read or saved.

## Reference validation

verified_reference.json contains exact page membership for all nine statement
classes in each uploaded PDF, and three visually checked net-position pages.
Use --gold to reproduce metrics only against those exact source PDFs. For further
validation, reserve new reports before tuning, annotate page membership and complete
caption lists independently, and extend the reference. Do not equate the small
sample's metrics with generalization to 25,000 PDFs. Include actual enterprise-only
and scanned government reports in the next validation set; current edge tests for
those reporting models are synthetic.

## Changes in 0.3.0

Rotated PDF geometry is normalized to the displayed page before grouping words;
vertical decorative sidebars are omitted. Logical text still identifies a vertical
TOC title. Image-block indices cannot shift the text-direction lookup.

Coordinates are PDF points in the upright extraction frame. page_rotation records
the PDF /Rotate value. ocr_rotation records any additional clockwise image rotation
used for OCR. Native/OCR frame transforms must be inverted before mapping boxes to
raw PDF content. An OCR rotation of 90 or 270 swaps frame width and height.

TOC page ranges use both endpoints. Range barriers include reconciliations, component
units and notes. The next contents entry can bound an untitled continuation, including
an amounts-only right panel; such pages remain in the inventory without invented
caption rows. Title-only See Following Page placeholders are omitted. Fallback
bookmark windows and auto-OCR candidate ranges are limited to 12 pages; unusual
long or undocumented continuations still need review.

A combining title is admitted only when mapped evidence locates it in the basic
statement section, as in Freehold's B-4 proprietary statement. Supplementary
combining statements, college foundations, affiliated organizations and grant
program statements do not determine the primary reporting model. Readable complete
TOCs can establish absence for two-statement pension and three-statement enterprise
models, not only governments reporting four or more classes. PDF permission warnings
are retained even when openable text and a readable TOC establish the inventory.

Local OCR first scans suspect pages, then interprets recovered TOCs. Unreadable
TOC-linked statement starts can retry orientation using Tesseract OSD plus candidate
rotations scored by English/accounting vocabulary. No new Python dependency is needed.
A severely damaged OCR title may use a mapped basic TOC start plus corroborating
accounting structure, with warning ocr_title_from_toc. Unknowns still require review.
Scans without a usable TOC can require extensive OCR and manual orientation review.

Dotted leaders are removed as layout furniture. A label is not wrapped into the next
row when the next row is materially more indented; this preserves parent headings.
Normalization equivalence rules themselves are unchanged.

The original verified_reference.json remains unchanged. The expanded combined
reference is validation/expanded/combined_reference.json, with exact inventory for
22 reports and five checked caption pages. See EXPANDED_VALIDATION.md for scope and
limitations. A zero-error processing log still does not certify caption completeness.
