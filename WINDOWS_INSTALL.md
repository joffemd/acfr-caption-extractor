# Windows 11 installation

1. Install 64-bit Python 3.12 from python.org. Confirm `py -3.12 --version`.
2. Extract the release into a writable directory. Open PowerShell there.
3. Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

You do not need to change PowerShell execution policy or activate the environment.
Use the explicit Python executable above for all commands.

4. Optional OCR: install a Windows Tesseract build with English language data.
   The Tesseract project documentation links Windows builds; review the source and
   installer. Add the installation directory to PATH for the current terminal and
   verify `tesseract --version` and `tesseract --list-langs` (must include eng).
5. Optional inspection tools: install Poppler for Windows from a trusted build and
   put its bin directory on PATH. Verify `pdftotext -v`. Git is optional for running
   the ZIP release; install Git for Windows if version control is desired.
6. Test and run (replace example paths with directories you choose):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe acfr_extractor.py --input "C:\ACFR-working\pdfs" --output "C:\ACFR-working\results" --workers 2 --ocr auto --resume
```

## Downloading the fiscal-year 2025 reports from acfrs.reason.org

`acfrs_downloader.py` logs in to acfrs.reason.org, walks every state and
category folder, and saves each fiscal-year 2025 report as `ST Entity 2025.pdf`
(for example `AK Aleutians East Borough 2025.pdf`), the naming the extractor
reads. It uses only the Python standard library, so the `requirements.txt`
install above is enough.

Set the credentials for the current PowerShell window only (nothing is saved to
disk), then run:

```powershell
$env:ACFRS_USERNAME = Read-Host "acfrs.reason.org username"
$env:ACFRS_PASSWORD = [System.Net.NetworkCredential]::new("", (Read-Host "acfrs.reason.org password" -AsSecureString)).Password
.\.venv\Scripts\python.exe acfrs_downloader.py --output "D:\ACFR\pdfs" --workers 4
```

- The script reads the credentials only from those two environment variables and
  never writes them to the manifest, the log or the screen.
- Try a small batch first: `--states AK --limit 10`. Use `--list-only` to crawl
  and write the manifest without downloading. `--categories` limits the run to
  some categories (for example `"General Purpose,School District"`).
- `--workers` sets parallel downloads (default 4, maximum 8).
- Resuming: rerun the same command. Files already in the output folder are
  skipped. Failed files are tried again. Each download is written to a `.part`
  file and renamed only when complete, so an interrupted run (Ctrl+C, sleep,
  network loss) never leaves a truncated PDF.
- Failures: network errors, timeouts and HTTP 429/5xx are retried with back-off
  (`--retries`, default 5). A missing file (HTTP 403/404) or a response that is
  not a PDF is logged once and marked `failed`. The exit code is 1 if any report
  failed.
- Output folder contents: the PDFs, plus `manifest.csv` with one row per report
  (state, category, entity, entity_id, fiscal_year, source_url, filename,
  size_bytes, status (`downloaded`, `already_present` or `failed`), attempts,
  error, updated_at) and `download_log.txt`. The manifest opens in Excel.
- In November 2026 the site listed 18,852 fiscal-year 2025 reports across all
  categories, including charter schools, non-profits and unclassified entities.
  A crawl takes about a minute.
- File names: characters Windows forbids (`<>:"/\|?*`) become `-`, for example
  `Delta/Greely School District` becomes `Delta-Greely School District`. If two
  reports in a state would get the same name (Windows names ignore case), each
  gets its site entity id, for example `TX Lake ISD (id1234) 2025.pdf`. File names
  are at most about 130 characters, so keep the output folder path under about
  120 characters.
- Then point the extractor at the same folder:
  `--input "D:\ACFR\pdfs"`. The manifest and log are not PDFs and are ignored.

## Large runs (for example 25,000 reports on a 12-core, 64 GB PC)

```powershell
.\.venv\Scripts\python.exe acfr_extractor.py --input "D:\ACFR\pdfs" --output "D:\ACFR\results" --workers 10 --ocr auto --occurrences sqlite --timeout 1800 --metadata "D:\ACFR\metadata.json" --resume
```

- `--workers 10` leaves two cores for Windows and Tesseract. Peak memory was
  under 0.6 GB per worker on the sample, so 64 GB is ample.
- Estimated time: the 120-report sample used about 20 CPU-seconds per report,
  so about 14 hours for 25,000 reports with 10 workers. Scanned reports
  dominate. Measure on a pilot of about 1,000 reports first.
- Put input and output on a local SSD, not a cloud-synced folder. Keep the
  machine from sleeping. If the run stops for any reason, rerun the same
  command; `--resume` skips finished reports.
- Results: open `caption_frequencies.xlsx` in Excel. Per-caption detail is in
  `caption_occurrences.sqlite`. Review `processing_log.csv` (failed and timed-out
  PDFs) and the `unknown` rows of `statement_inventory.csv`.
- Without `--metadata`, government name and fiscal year are read from file
  names of the form `CA Alameda County 2025.pdf` (state, entity, fiscal year,
  separated by spaces), giving government "Alameda County, CA" and fiscal year
  2025. The sample naming `ACFR001__AK_Name_2025.pdf` is also recognized. Other
  names are used as the government name, with a blank fiscal year. The state is
  kept in the name so that same-named governments in different states (for
  example Washington County) are counted separately.

The program does not require access to the developer's computer. These are user-run
installation examples. For a downloaded production universe, no Google services
are required. For this project, keep authoritative inputs and permanent results in
Drive. If using Drive for desktop, keep the output/checkpoint on a local temporary
working disk while processing, then copy completed CSVs and releases to Drive;
syncing an actively written SQLite database is unsafe. Do not run multiple extractor
instances against the same output directory.

Windows execution has not been tested in this Linux session. Paths, process entry
point, subprocess argument lists and multiprocessing are designed for Windows;
verification on your Windows machine remains necessary.
