# Expanded ACFR validation — 0.3.0

The 0.2.1 extractor missed rotated statements, misclassified enterprise net position,
included some foundation/grant statements, and omitted continuation panels. Release
0.3.0 corrects these behaviors using PDF geometry, basic-statement contents entries,
reporting-model evidence and local OCR. No filename-specific statement overrides or
reference answers are used by extraction. Reference files are evaluation inputs only.

## Results

| Check | Preserved 0.2.1 baseline | Final 0.3.0 |
|---|---:|---:|
| New 19 PDFs: exact class/status/page membership | 68/171 (39.8%) | 171/171 |
| Original 3 PDFs: exact class/status/page membership | 27/27 | 27/27 |
| Original three: checked caption/heading occurrences | 130/130 | 130/130 |
| Additional checked captions/headings | 0/61 recalled on the two selected pages | 61/61 |
| Original statement-page caption token streams preserved | — | 40/40 |
| Automated tests | 19 | 33, no skips |

The full run processed 22 PDFs, 4,266 pages and 124 basic statements. The remaining
74 class/report combinations are absent according to the reviewed source inventories.
It generated 5,671 caption/heading rows. Counts include repeated labels on multiple
pages and headings, not just unique accounting concepts. All reports completed;
OCR and PDF-permission warnings remain visible in inventories/occurrences.

The original three now produce 1,575 rows rather than 1,523 because merged headings
are separated. Their normalized caption text in reading order is unchanged across
all 40 statement pages. This check is stronger than testing only the three original
net-position reference pages, but it does not independently prove every original
caption or parent assignment was correct.

## Source review and measurement limits

The 19 additional uploaded PDFs were kept unchanged. Actual filenames, sizes and
SHA-256 hashes are in validation/expanded/sample_inventory.json. They include one
FY2024 park district report; the other supplied filenames identify FY2025. Source
TOCs, page titles and financial tables were reviewed to establish all nine class
statuses and exact data-page membership per PDF. Original Drive IDs were unavailable
and remain blank in metadata; no credentials or original PDFs are committed.

The reference is assistant-reviewed, not an external accountant's adjudication.
The original reference remains unchanged. New caption lists were transcribed from
rendered Minnesota Teachers Retirement Association page 29 (30 occurrences) and
Coastal Carolina University page 34 (31 occurrences), including visible headings.
Together with the original 130, final exact normalized multiset precision and recall
are 191/191 on five selected pages. Other caption pages and hierarchy assignments
have not been comprehensively measured.

Freehold is a fully scanned 196-page report. Source title review corrected an initial
reference pagination assumption: printed page 26 is PDF page 34, not 33. Its basic
B-4 proprietary statement is titled Combining Statement of Net Position; its basic
TOC corroborates inclusion. Reconciliation-only pages and See Following Page
placeholders are excluded, while data-only right panels are included. This is
recorded in the reference method notes. Baseline and final scores use the same
corrected reference.

All 19 new reports were used to diagnose and fix issues, so the final results are
regression measurements, not an untouched holdout or a production-wide accuracy
claim. The baseline used the unchanged 0.2.1 extractor from commit 9a3bd98 with
--ocr auto and two workers; its extracted results were preserved before code edits.
The final run used the same source PDFs and local OCR caches where valid. Timings
in final logs include cached OCR and must not be extrapolated to cold throughput.

## Main corrections

- **Rotation and image blocks:** word coordinates now reflect PDF rotation. Native
  word/dictionary queries share a text page, so image blocks cannot shift the
  direction lookup. Vertical sidebars do not become captions, but logical text
  still preserves a vertically placed TOC title.
- **Contents evidence:** read range starts/ends, comparative and plural titles,
  wrapped exhibit-prefixed entries and single-content headings. Reconciliation,
  foundation and notes entries bound the basic statement ranges.
- **Reporting models:** primary-government columns in a housing/airport authority
  do not make an enterprise statement government-wide. College foundations and
  affiliated organizations cannot change the primary model. Complete small-model
  TOCs support legitimate absence rather than six/seven unexplained unknowns.
- **Continuations:** include data-only panels without inventing captions, and
  recognize title-less adjacent accounting pages within mapped ranges. Reject
  reconciliation-only pages even when they repeat a financial statement title.
- **OCR:** recover the TOC after OCR; retry unreadable mapped statement starts at
  candidate orientations. Damaged titles require TOC plus accounting-structure
  corroboration and carry a review warning. Orientation retries are restricted to
  candidate statements, not every statistical page.
- **Captions:** remove dotted leader furniture and preserve an indented heading
  separately from the child row beneath it. Normalization aliases are unchanged.

## Reproduce

Install requirements.txt and Tesseract English/OSD data, then run:

```text
python -m unittest discover -s tests -v
python acfr_extractor.py --input "22 sample PDFs" --output "results" --ocr auto --workers 2 --metadata validation/expanded/sample_metadata.json --gold validation/expanded/combined_reference.json --resume
```

Original source PDFs must be supplied separately. For just the new 19, use
validation/expanded/reference.json. The combined reference contains the original
three too; evaluating it against a subset would correctly report missing inputs.
The final six combined CSVs are in validation/expanded/final. The preserved baseline
inventory, processing log and measurements are the baseline_* files. See
original_caption_comparison.csv for original-page token preservation and
verification.json for hashes, counts and resume verification.

## Remaining limits

Windows execution, Google Drive/Colab authentication and 25,000-report unattended
scale remain untested. No new Drive writes were attempted; delivery is through the
authorized GitHub repository. Scanned reports without a usable TOC may need costly
OCR and manual orientation review. Rare layouts, long undocumented continuations,
malformed native parsers, incorrect/incomplete TOCs and OCR errors can still produce
unknown/partial/incorrect extraction. Worker crash isolation and hard native-PDF
per-document timeouts remain future work. The new tests guard the specific generic
failure modes found here; they do not certify arbitrary ACFRs.

Review unknown/review warnings before using corpus frequencies. Denominators use
heuristic extracted-statement status, not externally audited completeness. New
section/parent assignments and all 5,671 rows have not been manually verified.
Third-party licensing considerations in the README still apply.
