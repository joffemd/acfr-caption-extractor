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
- Without `--metadata`, government name and fiscal year are read from
  filenames like `ACFR001__AK_City_and_Borough_of_Juneau_2025.pdf`; otherwise
  the file name is used as the government name and the fiscal year is blank.

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
