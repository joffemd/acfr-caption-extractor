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
