# Drive sample validation — 0.4.0

Release 0.4.0 was tested directly against the Google Drive sample folder
`ACFRS / Representative_ACFR_Sample_120` (account docs@cocotax.org), in
its `Development_90` and `Validation_30_HOLDOUT` subfolders. Earlier releases
were developed on 22 uploaded copies only.

## What could be tested

The Drive connector available to this development session returns a file only if
it is smaller than about 6.2 MB. The session's network policy blocked Google's
direct download hosts. As a result **48 of the 120 PDFs were tested**:

| Folder | In Drive | Downloaded and tested | Not tested (too large) |
|---|---:|---:|---:|
| Development_90 | 90 | 36 | 54 |
| Validation_30_HOLDOUT | 30 | 12 | 18 |
| **Total** | **120** | **48** | **72** |

The untested 72 skew toward large documents: states, large cities and counties,
big pension systems and transit agencies, 6–50 MB each. Their results are
unknown. Each downloaded file's byte size was checked against Drive. The PDFs were
read only; nothing in the Drive sample was modified.

The 48 tested reports cover 9,226 pages. They include cities, counties and two
states (Hawaii, Missouri), plus school districts, colleges and universities, fire
districts, housing authorities, airports, a library district and a transit
authority. One
report (Oak Park) is FY2024. Freehold Regional High School District is scanned
and requires OCR.

## Method

1. Ran release 0.3.0 unchanged on the 36 development PDFs. Every failure was
   inspected against the PDF and classified, and a general rule was fixed.
   No filename-specific rules or reference answers are used by the extractor.
2. Before any tuning on them, ran the fixed code on the 12 holdout PDFs and saved
   that result (frozen measurement below).
3. Investigated the holdout failures, fixed their general causes, and re-ran
   everything. From this point the 12 holdout reports are regression samples, not
   untouched validation data.
4. Audited every run in four ways:
   - title checks on each statement's first page;
   - a search for untitled numeric pages directly after each statement (missed
     continuations);
   - a search of every "absent" statement type for a matching titled page;
   - a comparison with the previous reviewed reference (`combined_reference.json`,
     which covers 17 of the 48 reports).

## Results

| Measure | 0.3.0 | 0.4.0 |
|---|---:|---:|
| Reports with any unresolved ("unknown") statement | 9 / 48 | **0 / 48** |
| Unresolved statements (of 432 report × type cells) | 29 | **0** |
| Reference statement checks, exact pages + status (17 reports) | 144 / 153 | **153 / 153** |
| Reference caption pages, precision / recall (2 pages, 87 rows) | 87/87, 87/87 | **87/87, 87/87** |
| Report × type cells whose status or pages changed vs 0.3.0 | — | 53 |
| CPU time, 4 workers, all 48 | not measured cleanly (see note) | **8.0 min (6.7 min wall)** |
| Automated tests | 33 | **48** |

The 53 changed cells break down as follows:

- 29 unknown → resolved;
- 19 page ranges corrected (missing continuation pages or spread halves);
- 3 absent → present (Scott County, Pittsburgh, ASU);
- 2 present → absent (ASU's false government-wide net position and activities).

The 0.3.0 column is a single combined run of all 48. Run as two separate sets,
0.3.0 had 23 unresolved statements in 8 reports. The extra report in the combined
run is Freehold, whose TOC page hit the OCR timeout under four parallel workers,
the intermittent defect fixed in 0.4.0. The 0.3.0 timing was interrupted by a
container restart and resumed, so it is not reported. The OCR threading change
alone was measured on 0.4.0 code just before it was applied, with the same 48
inputs: 28.7 CPU minutes and 10.0 wall minutes fell to 8.0 and 6.7.

**Holdout, frozen before any tuning on it** (12 reports, 108 cells):

| | 0.3.0 | Development-tuned code, frozen |
|---|---:|---:|
| Reports with an unresolved statement | 4 / 12 | 2 / 12 |
| Unresolved statements | 13 | 11 |

The two remaining holdout failures were Duluth and Cary:

- Duluth prints a "Table of Contents" back-link on every page, so all 9 of its
  statements were unresolved.
- Cary's TOC uses bare exhibit letters, so its fiduciary statements were not
  marked absent.

A third error was silent: Pittsburgh's "Statement of Changes in Net Position –
Fiduciary Funds" was marked absent. All three are fixed in 0.4.0. These are
honest out-of-sample failure rates for the development-only rules.

Final 0.4.0 inventory for the 48 reports: 332 statements present, 100 absent,
0 unknown. 15,836 caption/heading rows were extracted (12,884 captions,
2,952 headings), 290 of them flagged for OCR review. 19 reports needed some OCR
(268 pages), usually for cover or image pages.

| Statement | Present | Absent |
|---|---:|---:|
| Government-wide net position | 38 | 10 |
| Government-wide activities | 38 | 10 |
| Governmental funds balance sheet | 38 | 10 |
| Governmental funds revenues/expenditures | 38 | 10 |
| Proprietary net position | 42 | 6 |
| Proprietary revenues/expenses | 42 | 6 |
| Proprietary cash flows | 42 | 6 |
| Fiduciary net position | 27 | 21 |
| Changes in fiduciary net position | 27 | 21 |

The 10 government-wide absences are the enterprise-only reporting models: colleges,
universities, housing and airport authorities, and a transit authority. Every
absence flagged by the audit search was reviewed. Each is either the same net
position statement correctly assigned to the other reporting model, or a
component-unit or foundation statement.

## Failures found and fixed

| Cause | Example reports | Effect in 0.3.0 |
|---|---|---|
| TOC range written with a figure dash (U+2012) or "16 and 17" | Hawaii, Greenville, Charleston | Start page read as the end page; first page or half of a spread lost |
| "Statement of … – Component Units" treated as primary statement | Hawaii, ASU, Louisville | Competing ranges → unknown; ASU flipped to government-wide |
| FASB foundation statements without "component unit" label | Oakton College | Government-wide statements reported for a college |
| Navigation tabs "… STATISTICAL SECTION" in every header | Louisville | Statements rejected as statistical tables |
| Page numbers printed on odd pages only | Louisville | TOC entries on even pages unmapped |
| Running header "Annual … Report for the Year Ended …" above the title | Portland | Proprietary net position classified government-wide |
| "Table of Contents" back-link on every page | Duluth | Every page treated as a TOC: 0 of 9 statements |
| Bare exhibit letters in TOC ("C Balance Sheet") | Cary | TOC unreadable → fiduciary absence unknown |
| "Statement of Additions, Deductions and Changes in Fiduciary Net Position" | Scott County | Wrongly marked absent |
| "Statement of Changes in Net Position – Fiduciary Funds" | Pittsburgh | Wrongly marked absent |
| Title typo "NET POSITON"; custodial statement with dash amounts | White Plains | Unknown |
| "The Statement of Fund Net Position" (leading "The") | Cedar Rapids | Handled by 0.3.0; regression caught during 0.4.0 work |
| Untitled continuation pages / untitled left page of a spread | Cedar Rapids, Lakewood, Livonia | Statement truncated to one page |
| Tesseract multi-threading under parallel workers | Freehold | OCR timeout on the TOC page → statements unresolvable (intermittent) |
| Hanging-indent wrapped captions | Duluth and most others | One caption split into a heading plus a fragment ("reported") |
| Captions containing a date ("Fund Balances - December 31, 2025") | 14 reports, 62 rows | Closing-balance captions dropped |
| Underline rules / leader fragments in captions | New York City | "Total assets  ___________" |

Prose mentions of statements in MD&A and notes ("The statement of net position
provides …") are no longer read as titles. This was a risk introduced by the new
title search, caught on Lakewood and Frederick-Firestone.

## Reference correction

The previous reference listed Lakewood's government-wide net position, activities
and governmental-fund operating statements as single pages. Visual review shows
that each continues onto the following page. The TOC gives printed pages 16 and
18; PDF page 43 is printed page 17 and carries deferred inflows and net position.
The three entries were corrected and the reason is recorded under `corrections` in
`validation/expanded/combined_reference.json`.

## Per-report results

"Changed" counts statement types whose status or page set differs from 0.3.0.

| Report | Set | Pages | 0.3.0 unresolved | 0.4.0 present | 0.4.0 absent | Changed vs 0.3.0 | Caption rows |
|---|---|---:|---:|---:|---:|---:|---:|
| ACFR001  AK City and Borough of Juneau | dev | 270 | 0 | 7 | 2 | 0 | 660 |
| ACFR005  AZ Chandler | dev | 225 | 0 | 7 | 2 | 0 | 322 |
| ACFR011  CT Darien | holdout | 176 | 0 | 9 | 0 | 0 | 252 |
| ACFR016  FL Winter Park | dev | 175 | 0 | 9 | 0 | 0 | 373 |
| ACFR017  GA Dunwoody | holdout | 120 | 0 | 7 | 2 | 1 | 236 |
| ACFR020  HI State of Hawaii | dev | 195 | 2 | 9 | 0 | 4 | 491 |
| ACFR021  IA Cedar Rapids | dev | 174 | 0 | 9 | 0 | 2 | 458 |
| ACFR022  IA Scott County | dev | 191 | 0 | 9 | 0 | 1 | 363 |
| ACFR025  IL Evanston | dev | 223 | 0 | 9 | 0 | 0 | 408 |
| ACFR026  IL Hoffman Estates | dev | 266 | 0 | 9 | 0 | 0 | 377 |
| ACFR028  IN Fort Wayne | dev | 268 | 0 | 9 | 0 | 0 | 366 |
| ACFR029  KS Lawrence | dev | 182 | 0 | 7 | 2 | 0 | 388 |
| ACFR030  KS Lenexa | dev | 223 | 0 | 9 | 0 | 0 | 341 |
| ACFR032  KY Louisville-Jefferson County Metro Government | dev | 242 | 5 | 9 | 0 | 6 | 392 |
| ACFR041  MI Kalamazoo | dev | 292 | 0 | 9 | 0 | 0 | 408 |
| ACFR042  MI Livonia | holdout | 117 | 0 | 9 | 0 | 1 | 385 |
| ACFR043  MN Duluth | holdout | 219 | 9 | 9 | 0 | 9 | 609 |
| ACFR046  MO State of Missouri | holdout | 273 | 1 | 9 | 0 | 1 | 418 |
| ACFR050  NC Cary | holdout | 280 | 2 | 7 | 2 | 2 | 352 |
| ACFR051  NC Chapel Hill | dev | 216 | 0 | 9 | 0 | 0 | 511 |
| ACFR052  ND Fargo | dev | 238 | 0 | 9 | 0 | 0 | 434 |
| ACFR055  NE Omaha | dev | 270 | 0 | 9 | 0 | 0 | 355 |
| ACFR061  NV Clark County | dev | 218 | 0 | 9 | 0 | 0 | 484 |
| ACFR063  NY New York | dev | 260 | 0 | 9 | 0 | 0 | 1197 |
| ACFR064  NY White Plains | dev | 191 | 2 | 9 | 0 | 2 | 293 |
| ACFR070  OR Portland | dev | 454 | 1 | 9 | 0 | 2 | 578 |
| ACFR074  PA Pittsburgh | holdout | 256 | 1 | 6 | 3 | 2 | 284 |
| ACFR075  RI Providence | dev | 200 | 0 | 9 | 0 | 0 | 402 |
| ACFR077  SC Charleston | dev | 172 | 0 | 9 | 0 | 4 | 377 |
| ACFR078  SC Greenville County | dev | 202 | 0 | 9 | 0 | 4 | 369 |
| ACFR081  AZ Arizona State University | dev | 101 | 0 | 3 | 6 | 3 | 155 |
| ACFR082  AZ Fry Fire District | dev | 100 | 0 | 4 | 5 | 0 | 137 |
| ACFR083  AZ J O Combs Unified School District | dev | 119 | 0 | 4 | 5 | 0 | 152 |
| ACFR091  CO Frederick Firestone Fire Protection District | dev | 88 | 0 | 4 | 5 | 0 | 114 |
| ACFR095  GA Housing Authority of the City of Atlanta | dev | 110 | 0 | 3 | 6 | 0 | 117 |
| ACFR096  IL Arlington Heights School District 25 | dev | 145 | 0 | 4 | 5 | 0 | 172 |
| ACFR097  IL Carl Sandburg College | dev | 170 | 0 | 3 | 6 | 0 | 138 |
| ACFR100  IL Oakton College | dev | 146 | 0 | 3 | 6 | 0 | 156 |
| ACFR101  IL Park District of Oak Park (FY2024) | dev | 141 | 0 | 7 | 2 | 0 | 149 |
| ACFR102  IN Fort Wayne Allen County Airport Authority | holdout | 106 | 0 | 3 | 6 | 0 | 155 |
| ACFR107  NJ Freehold Regional High School District | holdout | 196 | 6 | 7 | 2 | 6 | 290 |
| ACFR108  NV Las Vegas Clark County Library District | holdout | 176 | 0 | 4 | 5 | 0 | 133 |
| ACFR109  NY Albany County Airport Authority | dev | 132 | 0 | 5 | 4 | 0 | 189 |
| ACFR111  OH Lakewood Local School District | dev | 216 | 0 | 7 | 2 | 3 | 276 |
| ACFR114  SC Coastal Carolina University | holdout | 129 | 0 | 3 | 6 | 0 | 157 |
| ACFR116  TX Panola College | dev | 114 | 0 | 3 | 6 | 0 | 151 |
| ACFR118  VA Richmond Metropolitan Transportation Authority | holdout | 92 | 0 | 5 | 4 | 0 | 144 |
| ACFR120  WA Seattle Housing Authority | dev | 157 | 0 | 3 | 6 | 0 | 168 |

## Limitations

- **72 of the 120 sample reports, the largest ones, have not been run.** States,
  big cities and pension systems have longer and more varied statements.
  New failure types are likely there.
- Caption accuracy is measured on only two reference pages (87 rows). The 15,836
  extracted rows have not been individually verified. Caption changes in 0.4.0
  were reviewed by diffing every changed row between runs, not against an
  independent transcription.
- The new continuation rule includes an untitled numeric page after a statement
  when it shows accounting structure. An untitled schedule placed directly after a
  statement could be absorbed. Rows carry `titleless_continuation` or
  `amount_only_continuation` warnings for review.
- OCR results (Freehold) remain review-grade.
- Windows was not tested in this session.

## Reproducing

```text
python acfr_extractor.py --input "<folder with the PDFs>" --output results --workers 4 --ocr auto --gold validation/expanded/combined_reference.json
```

The reference covers 22 reports. A report missing from the input is scored as a
failure, so filter the reference to the reports you have before measuring.
Outputs are in `validation/full_sample/`:

- `final/`: the six 0.4.0 CSVs, with Drive file IDs from `drive_metadata_48.json`.
- `baseline_0.3.0/`: the 0.3.0 inventory, log and validation report.
- `holdout_frozen/`: the frozen holdout measurement.
- `sample_inventory_120.json`: all 120 sample files and which were tested.
- `reference_available.json`: the reference filtered to the 48 reports.
