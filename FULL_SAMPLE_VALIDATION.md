# Drive sample validation — 0.5.0 (all 120 reports)

Release 0.5.0 was tested on **all 120 PDFs** of the Google Drive folder
`ACFRS / Representative_ACFR_Sample_120` (Development_90 and
Validation_30_HOLDOUT; account docs@cocotax.org). Each file was downloaded
read-only and checked byte-for-byte against its Drive size. Nothing in Drive
was modified. Drive file IDs are carried into every output
(`validation/all120/drive_metadata_120.json`).

The first 48 reports were the files small enough for the Drive connector; that
stage is documented further below. After the cloud environment's network policy
was widened, the remaining 72 (larger: states, big cities and counties, pension
systems, transit and utility agencies) were downloaded directly.

## Frozen measurement on the 72 new reports

Before any change for them, 0.4.0 was run unchanged on all 120:

| | 0.4.0 frozen | 0.5.0 |
|---|---:|---:|
| Reports fully resolved, all 120 | 102 / 120 | **119 / 120** |
| Reports fully resolved, 72 new | 54 / 72 | **71 / 72** |
| Reports fully resolved, 48 earlier | 48 / 48 | 48 / 48 (no statement changed) |
| Unresolved statement slots (of 1,080) | 80 | **5** (all St. Louis) |
| Crashes | 0 | 0 |
| Reference statement checks, exact pages + status (22 reports) | not run | **198 / 198** |
| Reference caption pages, precision and recall (5 pages, 191 rows) | not run | **191/191, 191/191** |
| Wall time, 4 workers, cold | 18.5 min | **17.4 min** (see note) |
| Automated tests | 48 | **59** |

The 17.4-minute cold run used the rule set before the final two continuation
fixes, which add no OCR. The release run itself was resumed after a container
restart, so its own timing is not meaningful.

"Resolved" means every one of the nine statement types was either located with
its page range or established as absent. It is not a manual verification of
every page.

Relative to the frozen run, 99 of 1,080 cells changed:

- 59 unknown → present;
- 16 unknown → absent;
- 17 page ranges corrected (missed continuation pages or spread halves);
- 7 wrong "absent" → present. These are Poudre River Library's and MWRD's combined
  government-wide/fund statements and Miami's statements drawn as vector outlines.

The remaining failure is **St. Louis**. Its PDF is scrambled at the source: the
rendered page itself shows titles in the middle of tables and labels detached
from amounts. Five of its statements are left unresolved for human review rather
than guessed.

## Final 0.5.0 inventory (120 reports, 27,153 pages)

| Statement | Present | Absent | Unresolved |
|---|---:|---:|---:|
| Government-wide net position | 96 | 24 | 0 |
| Government-wide activities | 96 | 24 | 0 |
| Governmental funds balance sheet | 96 | 24 | 0 |
| Governmental funds revenues/expenditures | 96 | 24 | 0 |
| Proprietary net position | 105 | 14 | 1 |
| Proprietary revenues/expenses | 105 | 14 | 1 |
| Proprietary cash flows | 105 | 14 | 1 |
| Fiduciary net position | 87 | 32 | 1 |
| Changes in fiduciary net position | 87 | 32 | 1 |

40,645 caption/heading rows were extracted (33,212 captions, 7,433 headings);
1,553 come from OCR and are flagged for review. 63 reports needed some OCR
(1,132 pages). The median report took 3.5 seconds; the slowest, a scanned
196-page report, took 7 minutes.

Review warnings in `statement_inventory.csv`:

| Warning | Statements |
|---|---:|
| amount_only_continuation | 68 |
| titleless_continuation | 65 |
| toc_page_mapping_ignored | 18 |
| absence_inferred_from_statement_section | 12 |
| combined_statement | 8 |
| shared_page | 2 |
| title_from_toc / ocr_title_from_toc / untitled_spread_first_page | 1 each |

All 12 inferred absences belong to DC Water and Truckee Donner, two enterprise
utilities without a readable TOC. A full-text search confirmed that neither
report contains any fiduciary statement.

## Audits on all 120

1. **Titles:** every flagged first page was reviewed. They are OCR reports with an
   unreadable native layer (Alaska, Freehold, Miami, Carmel, Canaveral), Boise's
   irregular title, New York's 8-page cash flows, and the Livonia and UNC layouts.
2. **Missed continuations:** an untitled numeric page directly after a statement.
   Four real misses were found and fixed (Tarrant, Deschutes, and MWRD twice).
   Two more changed as side effects (Phoenix, Idaho) and were checked. The
   remaining flags are St. Louis, Carmel's unreadable pages, Boise's next
   statement, and Livonia's spread.
3. **Absences:** every absence with a page bearing a matching title was reviewed.
   Each is the same net position statement correctly assigned to the other
   reporting model (enterprise-only districts, colleges, pension systems), a
   component-unit or foundation statement, or a TOC page.
4. **Reference:** all 22 reports of `combined_reference.json` are now in the sample
   and match exactly, including Alaska (OCR), Auburn and the
   Minnesota TRA pension report.
5. **Caption spot checks:** Pennsylvania's sideways Statement of Activities and
   Boston's cash flows were compared row by row with the page text.

## Failures found on the 72 new reports and fixed

| Cause | Example reports |
|---|---|
| TOC page numbers that recur (Single Audit section or statistical tables numbered from 1) | Ohio, Pennsylvania, Boston, Tarrant |
| Footer "16 City of Boston, Massachusetts"; header "SUSSEX COUNTY, DELAWARE -19-" | Boston, Sussex |
| Number-first TOC lines ("36 Statement of …"), garbled TOC title | Phoenix, UNC Chapel Hill |
| Landscape pages stored with /Rotate so every displayed line is vertical | Pennsylvania |
| Fiduciary word in header-area body text retyped net position as fiduciary | Cincinnati |
| Two statements on one page | UNC Chapel Hill |
| Combined government-wide/fund statements | Poudre River Library, MWRD |
| Prior-year statement "for comparative information purposes" | MTC |
| "ACTIVITES" typo; fiduciary component units; irregular "Schedule of …" title | Olmsted, MWAA, Boise |
| Symbol-soup text from broken fonts; statements drawn as vector outlines | Carmel, Miami |
| Statement pages first located by an OCR-recovered TOC were never OCR'd | Miami |
| Rotated scans without a TOC link | Carmel |
| Amount-only right-hand spread pages; header text taken as a new title | Ohio, Tarrant, Deschutes, MWRD |
| Enterprise-only reports with no readable TOC | DC Water, Truckee Donner |
| One slow scanned report held up a whole batch of workers | Throughput |

Two regressions were introduced and caught during this work, and both are fixed.
Exhibit codes ("A-1 Statement of Net Position 26") were briefly misread as
number-first TOC lines (Freehold). Absence inference briefly applied to OCR'd
sections and is now restricted to native text.

## Per-report results (all 120)

"0.4.0 unresolved" is from the frozen run. "Changed" counts statement types whose
status or page set differs from it. St. Louis's 5 unresolved types are neither
present nor absent.

| Report | Set | Pages | 0.4.0 unresolved | 0.5.0 present | 0.5.0 absent | Changed vs 0.4.0 | Caption rows |
|---|---|---:|---:|---:|---:|---:|---:|
| ACFR001  AK City and Borough of Juneau | dev | 270 | 0 | 7 | 2 | 0 | 660 |
| ACFR002  AK State of Alaska | dev | 614 | 0 | 9 | 0 | 0 | 478 |
| ACFR003  AL Auburn | dev | 238 | 0 | 9 | 0 | 0 | 415 |
| ACFR004  AL Jefferson County | holdout | 216 | 0 | 9 | 0 | 0 | 429 |
| ACFR005  AZ Chandler | dev | 225 | 0 | 7 | 2 | 0 | 322 |
| ACFR006  AZ Phoenix | dev | 366 | 1 | 9 | 0 | 1 | 460 |
| ACFR007  CA Carlsbad | holdout | 238 | 0 | 9 | 0 | 0 | 320 |
| ACFR008  CA Palo Alto | dev | 210 | 0 | 9 | 0 | 0 | 414 |
| ACFR009  CO City and County of Denver | dev | 296 | 0 | 9 | 0 | 0 | 473 |
| ACFR010  CO Golden | dev | 151 | 0 | 9 | 0 | 0 | 392 |
| ACFR011  CT Darien | holdout | 176 | 0 | 9 | 0 | 0 | 252 |
| ACFR012  CT Hartford | dev | 207 | 0 | 9 | 0 | 0 | 359 |
| ACFR013  DE State of Delaware | dev | 386 | 0 | 9 | 0 | 0 | 387 |
| ACFR014  DE Sussex County | holdout | 147 | 9 | 9 | 0 | 9 | 361 |
| ACFR015  FL Miami | holdout | 268 | 3 | 6 | 3 | 6 | 247 |
| ACFR016  FL Winter Park | dev | 175 | 0 | 9 | 0 | 0 | 373 |
| ACFR017  GA Dunwoody | holdout | 120 | 0 | 7 | 2 | 0 | 236 |
| ACFR018  GA Hall County | dev | 260 | 0 | 9 | 0 | 0 | 395 |
| ACFR019  HI City and County of Honolulu | holdout | 362 | 0 | 9 | 0 | 0 | 404 |
| ACFR020  HI State of Hawaii | dev | 195 | 0 | 9 | 0 | 0 | 491 |
| ACFR021  IA Cedar Rapids | dev | 174 | 0 | 9 | 0 | 0 | 458 |
| ACFR022  IA Scott County | dev | 191 | 0 | 9 | 0 | 0 | 363 |
| ACFR023  ID Boise | dev | 159 | 1 | 7 | 2 | 1 | 599 |
| ACFR024  ID State of Idaho | dev | 224 | 0 | 9 | 0 | 2 | 395 |
| ACFR025  IL Evanston | dev | 223 | 0 | 9 | 0 | 0 | 408 |
| ACFR026  IL Hoffman Estates | dev | 266 | 0 | 9 | 0 | 0 | 377 |
| ACFR027  IN Carmel | holdout | 159 | 6 | 9 | 0 | 9 | 379 |
| ACFR028  IN Fort Wayne | dev | 268 | 0 | 9 | 0 | 0 | 366 |
| ACFR029  KS Lawrence | dev | 182 | 0 | 7 | 2 | 0 | 388 |
| ACFR030  KS Lenexa | dev | 223 | 0 | 9 | 0 | 0 | 341 |
| ACFR031  KY Commonwealth of Kentucky | dev | 505 | 0 | 9 | 0 | 0 | 433 |
| ACFR032  KY Louisville-Jefferson County Metro Government | dev | 242 | 0 | 9 | 0 | 0 | 392 |
| ACFR033  LA Baton Rouge | dev | 349 | 0 | 9 | 0 | 0 | 410 |
| ACFR034  LA State of Louisiana | dev | 541 | 0 | 9 | 0 | 0 | 629 |
| ACFR035  MA Boston | dev | 229 | 9 | 9 | 0 | 9 | 283 |
| ACFR036  MA Nantucket | dev | 163 | 0 | 9 | 0 | 0 | 356 |
| ACFR037  MD Montgomery County | dev | 289 | 0 | 9 | 0 | 0 | 495 |
| ACFR038  MD Rockville | holdout | 123 | 0 | 9 | 0 | 0 | 358 |
| ACFR039  ME Kennebunkport | holdout | 139 | 0 | 7 | 2 | 0 | 267 |
| ACFR040  ME South Portland | dev | 185 | 0 | 9 | 0 | 0 | 290 |
| ACFR041  MI Kalamazoo | dev | 292 | 0 | 9 | 0 | 0 | 408 |
| ACFR042  MI Livonia | holdout | 117 | 0 | 9 | 0 | 0 | 385 |
| ACFR043  MN Duluth | holdout | 219 | 0 | 9 | 0 | 0 | 609 |
| ACFR044  MN Olmsted County | dev | 210 | 1 | 9 | 0 | 1 | 431 |
| ACFR045  MO St. Louis | dev | 290 | 6 | 4 | 0 | 1 | 172 |
| ACFR046  MO State of Missouri | holdout | 273 | 0 | 9 | 0 | 0 | 418 |
| ACFR047  MT Billings | dev | 293 | 0 | 9 | 0 | 0 | 371 |
| ACFR048  MT State of Montana | dev | 324 | 0 | 9 | 0 | 1 | 474 |
| ACFR049  NC Brunswick County | dev | 254 | 0 | 9 | 0 | 0 | 292 |
| ACFR050  NC Cary | holdout | 280 | 0 | 7 | 2 | 0 | 352 |
| ACFR051  NC Chapel Hill | dev | 216 | 0 | 9 | 0 | 0 | 511 |
| ACFR052  ND Fargo | dev | 238 | 0 | 9 | 0 | 0 | 434 |
| ACFR053  ND State of North Dakota | dev | 255 | 0 | 9 | 0 | 0 | 635 |
| ACFR054  NE Lincoln | dev | 229 | 0 | 9 | 0 | 0 | 511 |
| ACFR055  NE Omaha | dev | 270 | 0 | 9 | 0 | 0 | 355 |
| ACFR056  NH Manchester | dev | 303 | 0 | 9 | 0 | 0 | 392 |
| ACFR057  NH State of New Hampshire | holdout | 370 | 0 | 9 | 0 | 0 | 462 |
| ACFR058  NJ State of New Jersey | holdout | 529 | 0 | 9 | 0 | 0 | 332 |
| ACFR059  NM Albuquerque | dev | 315 | 0 | 9 | 0 | 0 | 373 |
| ACFR060  NM Santa Fe County | dev | 336 | 0 | 9 | 0 | 1 | 314 |
| ACFR061  NV Clark County | dev | 218 | 0 | 9 | 0 | 0 | 484 |
| ACFR062  NV Las Vegas | dev | 283 | 0 | 9 | 0 | 0 | 462 |
| ACFR063  NY New York | dev | 260 | 0 | 9 | 0 | 0 | 1197 |
| ACFR064  NY White Plains | dev | 191 | 0 | 9 | 0 | 0 | 293 |
| ACFR065  OH Cincinnati | dev | 336 | 1 | 9 | 0 | 2 | 534 |
| ACFR066  OH State of Ohio | dev | 449 | 9 | 9 | 0 | 9 | 458 |
| ACFR067  OK Edmond | holdout | 223 | 0 | 9 | 0 | 0 | 406 |
| ACFR068  OK Tulsa | dev | 217 | 0 | 9 | 0 | 0 | 415 |
| ACFR069  OR Deschutes County | holdout | 252 | 0 | 9 | 0 | 1 | 351 |
| ACFR070  OR Portland | dev | 454 | 0 | 9 | 0 | 0 | 578 |
| ACFR071  OR State of Oregon | holdout | 456 | 0 | 9 | 0 | 0 | 623 |
| ACFR072  PA Commonwealth of Pennsylvania | dev | 406 | 9 | 9 | 0 | 9 | 593 |
| ACFR073  PA Philadelphia | dev | 230 | 0 | 9 | 0 | 0 | 434 |
| ACFR074  PA Pittsburgh | holdout | 256 | 0 | 6 | 3 | 0 | 284 |
| ACFR075  RI Providence | dev | 200 | 0 | 9 | 0 | 0 | 402 |
| ACFR076  RI State of Rhode Island | dev | 464 | 0 | 9 | 0 | 0 | 429 |
| ACFR077  SC Charleston | dev | 172 | 0 | 9 | 0 | 0 | 377 |
| ACFR078  SC Greenville County | dev | 202 | 0 | 9 | 0 | 0 | 369 |
| ACFR079  TX Flower Mound | dev | 167 | 0 | 7 | 2 | 0 | 323 |
| ACFR080  TX Tarrant County | dev | 237 | 3 | 9 | 0 | 3 | 226 |
| ACFR081  AZ Arizona State University | dev | 101 | 0 | 3 | 6 | 0 | 155 |
| ACFR082  AZ Fry Fire District | dev | 100 | 0 | 4 | 5 | 0 | 137 |
| ACFR083  AZ J O Combs Unified School District | dev | 119 | 0 | 4 | 5 | 0 | 152 |
| ACFR084  CA Eastern Municipal Water District | dev | 137 | 0 | 5 | 4 | 0 | 231 |
| ACFR085  CA Los Altos School District | dev | 128 | 0 | 4 | 5 | 0 | 127 |
| ACFR086  CA Metropolitan Transportation Commission | dev | 170 | 2 | 9 | 0 | 6 | 432 |
| ACFR088  CA Santa Clara Valley Transportation Authority | dev | 182 | 0 | 9 | 0 | 0 | 384 |
| ACFR089  CA Tiburon Fire Protection District | holdout | 108 | 0 | 4 | 5 | 0 | 117 |
| ACFR090  CO Colorado Public Employees Retirement Association | dev | 262 | 2 | 2 | 7 | 2 | 198 |
| ACFR091  CO Frederick Firestone Fire Protection District | dev | 88 | 0 | 4 | 5 | 0 | 114 |
| ACFR092  CO Poudre River Public Library District | dev | 68 | 0 | 4 | 5 | 2 | 162 |
| ACFR093  DC District of Columbia Water and Sewer Authority | dev | 126 | 6 | 3 | 6 | 6 | 126 |
| ACFR094  FL Canaveral Port Authority | dev | 101 | 0 | 3 | 6 | 0 | 159 |
| ACFR095  GA Housing Authority of the City of Atlanta | dev | 110 | 0 | 3 | 6 | 0 | 117 |
| ACFR096  IL Arlington Heights School District 25 | dev | 145 | 0 | 4 | 5 | 0 | 172 |
| ACFR097  IL Carl Sandburg College | dev | 170 | 0 | 3 | 6 | 0 | 138 |
| ACFR098  IL Heartland Community College | dev | 170 | 0 | 3 | 6 | 0 | 145 |
| ACFR099  IL Metropolitan Water Reclamation District of Greater Chicago | dev | 209 | 0 | 6 | 3 | 4 | 285 |
| ACFR100  IL Oakton College | dev | 146 | 0 | 3 | 6 | 0 | 156 |
| ACFR101  IL Park District of Oak Park (FY2024) | dev | 141 | 0 | 7 | 2 | 0 | 149 |
| ACFR102  IN Fort Wayne Allen County Airport Authority | holdout | 106 | 0 | 3 | 6 | 0 | 155 |
| ACFR103  IN Indianapolis Marion County Public Library | dev | 123 | 0 | 9 | 0 | 0 | 216 |
| ACFR104  MN Minnesota State Retirement System | dev | 212 | 0 | 2 | 7 | 0 | 75 |
| ACFR105  MN Minnesota Teachers Retirement Association | holdout | 132 | 0 | 2 | 7 | 0 | 70 |
| ACFR106  NC University of North Carolina at Chapel Hill | holdout | 142 | 5 | 5 | 4 | 5 | 179 |
| ACFR107  NJ Freehold Regional High School District | holdout | 196 | 0 | 7 | 2 | 0 | 290 |
| ACFR108  NV Las Vegas Clark County Library District | holdout | 176 | 0 | 4 | 5 | 0 | 133 |
| ACFR109  NY Albany County Airport Authority | dev | 132 | 0 | 5 | 4 | 0 | 189 |
| ACFR110  NY New York City Housing Authority | dev | 157 | 0 | 3 | 6 | 0 | 171 |
| ACFR111  OH Lakewood Local School District | dev | 216 | 0 | 7 | 2 | 0 | 276 |
| ACFR112  CA Truckee Donner Public Utility District | dev | 100 | 6 | 3 | 6 | 6 | 153 |
| ACFR113  OR Oregon Public Employees Retirement System | holdout | 198 | 0 | 5 | 4 | 0 | 161 |
| ACFR114  SC Coastal Carolina University | holdout | 129 | 0 | 3 | 6 | 0 | 157 |
| ACFR115  TX Fort Worth Independent School District | dev | 232 | 0 | 9 | 0 | 2 | 314 |
| ACFR116  TX Panola College | dev | 114 | 0 | 3 | 6 | 0 | 151 |
| ACFR117  VA Metropolitan Washington Airports Authority | dev | 217 | 1 | 5 | 4 | 1 | 225 |
| ACFR118  VA Richmond Metropolitan Transportation Authority | holdout | 92 | 0 | 5 | 4 | 0 | 144 |
| ACFR119  WA Port of Seattle | dev | 129 | 0 | 5 | 4 | 0 | 227 |
| ACFR120  WA Seattle Housing Authority | dev | 157 | 0 | 3 | 6 | 0 | 168 |
| BART FY2025 original secured.pdf | holdout | 172 | 0 | 5 | 4 | 0 | 211 |

## Limitations

- 120 reports is a sample. The 25,000-report universe will contain layouts not
  seen here; review `unknown` rows and the warnings above.
- Caption accuracy is verified on 5 reference pages (191 rows) and two spot-check
  pages, not on all 40,645 rows. Known caption defect: a caption ending in a note
  number or date can be truncated where its digits are taken as amounts
  ("Transfers—Note 4" → "Transfers—Note"; "Net Position (Deficit) June 30, 2024"
  → "Net Position (Deficit) June").
- Continuation and inferred-absence rules trade some risk for coverage; their rows
  carry warnings.
- OCR results are review-grade; heavily scanned reports take minutes each.
- St. Louis-type corrupted PDFs need manual handling.
- Windows was not tested in this session.

## Outputs

`validation/all120/`:

- `final/`: the six 0.5.0 CSVs for all 120 reports.
- `frozen_0.4.0/`: inventory, log and validation report from the unchanged 0.4.0
  run.
- `drive_metadata_120.json`: Drive file IDs.
- `reference_available_120.json`: the reference used.

---

# Earlier stage: 0.4.0 on the first 48 reports

Release 0.4.0 was tested directly against the Google Drive sample folder
`ACFRS / Representative_ACFR_Sample_120` (account docs@cocotax.org), in
its `Development_90` and `Validation_30_HOLDOUT` subfolders. Earlier releases
were developed on 22 uploaded copies only.

### What could be tested

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

### Method

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

### Results

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

### Failures found and fixed

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

### Reference correction

The previous reference listed Lakewood's government-wide net position, activities
and governmental-fund operating statements as single pages. Visual review shows
that each continues onto the following page. The TOC gives printed pages 16 and
18; PDF page 43 is printed page 17 and carries deferred inflows and net position.
The three entries were corrected and the reason is recorded under `corrections` in
`validation/expanded/combined_reference.json`.

### Per-report results

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

### Limitations

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

### Reproducing

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
