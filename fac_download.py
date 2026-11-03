"""Download the FAC single audit PDFs listed in a fac_special_districts.py review CSV.

Reads fac_fy2025_special_district_review.csv (or a copy you edited), keeps the
rows whose action is "include" (--action changes this), and downloads each
report's PDF from the Federal Audit Clearinghouse:

    https://app.fac.gov/dissemination/report/pdf/<report_id>

That address redirects to the file; it needs no API key or login. Each PDF is
saved as "ST Entity 2025.pdf" (state, auditee name, fiscal-year-end year), the
name form acfr_extractor.py reads. Names that would collide (Windows ignores
case) get the report ID added: "ST Entity (2025-06-GSAFAC-0000012345) 2025.pdf".

A manifest.csv in the output folder records every report and its status.
Rerunning the same command resumes: finished files are skipped and failed ones
are retried. Files are written to a ".part" file first and renamed when
complete, so an interrupted run never leaves a truncated PDF under its final
name.

Standalone: standard library only, imports nothing else from this repository,
so it can be copied to any folder. Runs on Windows 11 with Python 3.12-3.14.
"""
import argparse
import concurrent.futures
import csv
import datetime
import logging
import os
import re
import sys
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PDF_URL = 'https://app.fac.gov/dissemination/report/pdf/{}'
USER_AGENT = 'acfr-caption-extractor-fac-download/1.0'
MAX_WORKERS = 8
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
MAX_ENTITY_CHARS = 120   # room for a long Windows output folder within the 260-character path limit
REPORT_ID = re.compile(r'^\d{4}-\d{2}-[A-Z]+-\d{10}$')
WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MANIFEST_FIELDS = ['state', 'category', 'entity', 'report_id', 'uei', 'fiscal_year', 'fiscal_year_end',
                   'source_url', 'filename', 'size_bytes', 'status', 'attempts', 'error', 'updated_at']

log = logging.getLogger('fac_download')


class PermanentError(RuntimeError):
    """A failure that retrying will not fix (for example HTTP 404)."""


# ---------------------------------------------------------------------------
# Review CSV -> report list

def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def select_reports(rows, actions, states=None, pdf_url=PDF_URL):
    """Reports to download, one per report ID, in the CSV's order.

    Returns (reports, skipped) where skipped counts rows without a usable report ID."""
    reports, seen, skipped = [], set(), 0
    for r in rows:
        if (r.get('action') or '').strip().casefold() not in actions:
            continue
        state = (r.get('state') or '').strip().upper()
        if states and state not in states:
            continue
        rid = (r.get('report_id') or '').strip()
        if not REPORT_ID.match(rid):
            skipped += 1
            log.warning('Skipping row without a valid report_id: %r', r.get('name'))
            continue
        if rid in seen:
            continue
        seen.add(rid)
        end = (r.get('fiscal_year_end') or '').strip()
        reports.append({'state': state, 'category': r.get('proposed_category') or '',
                        'entity': (r.get('name') or '').strip(), 'report_id': rid,
                        'uei': r.get('uei') or '', 'fiscal_year_end': end,
                        'fiscal_year': end[:4] if re.match(r'^\d{4}', end) else rid[:4],
                        'source_url': pdf_url.format(urllib.parse.quote(rid))})
    return reports, skipped


def clean_entity(name):
    """Entity name safe for a Windows file name and for the extractor's file-name parser."""
    name = unicodedata.normalize('NFC', name)
    name = WINDOWS_ILLEGAL.sub('-', name)
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    if len(name) > MAX_ENTITY_CHARS:
        name = name[:MAX_ENTITY_CHARS].rstrip(' .')
    return name or 'Unnamed'


def assign_filenames(reports):
    """Give every report a unique "ST Entity YYYY.pdf" name (case-insensitive, like Windows).

    Colliding reports all get their report ID after the entity name. Assignment
    depends only on the set of reports, so reruns give the same names."""
    groups = {}
    for r in reports:
        base = f"{r['state'] or 'XX'} {clean_entity(r['entity'])}"
        groups.setdefault(f"{base} {r['fiscal_year']}".casefold(), []).append((base, r))
    for members in groups.values():
        for base, r in members:
            r['filename'] = (f"{base} {r['fiscal_year']}.pdf" if len(members) == 1
                             else f"{base} ({r['report_id']}) {r['fiscal_year']}.pdf")
    return reports


def merge_manifest(reports, manifest_rows):
    """Carry status from an earlier run's manifest (same report ID and file name)."""
    old = {m.get('report_id'): m for m in manifest_rows}
    for r in reports:
        m = old.get(r['report_id'])
        if m and m.get('filename') == r['filename']:
            for k in ('size_bytes', 'status', 'attempts', 'error', 'updated_at'):
                r[k] = m.get(k, '')
    return reports


def write_manifest(path, reports):
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(reports)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Download

_local = threading.local()


def _opener():
    if not hasattr(_local, 'opener'):
        _local.opener = urllib.request.build_opener()   # follows the redirect to the file
        _local.opener.addheaders = [('User-Agent', USER_AGENT)]
    return _local.opener


def is_pdf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(1024).lstrip().startswith(b'%PDF')
    except OSError:
        return False


def fetch(url, dest, timeout=300):
    """Download url to dest atomically and return its size."""
    part = dest.with_name(dest.name + '.part')
    try:
        with _opener().open(urllib.request.Request(url), timeout=timeout) as r:
            expected = r.headers.get('Content-Length')
            with open(part, 'wb') as f:
                while chunk := r.read(1024 * 1024):
                    f.write(chunk)
        size = part.stat().st_size
        if expected is not None and size != int(expected):
            raise OSError(f'incomplete download: {size} of {expected} bytes')
        if not is_pdf(part):
            raise PermanentError('response is not a PDF')
        os.replace(part, dest)
        return size
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in RETRYABLE_HTTP:
            raise
        raise PermanentError(f'HTTP {e.code} {e.reason}') from None
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def download_one(report, out_dir, retries, timeout, stop):
    dest = out_dir / report['filename']
    if dest.exists() and dest.stat().st_size > 0 and is_pdf(dest):
        return {'status': 'already_present', 'size_bytes': dest.stat().st_size, 'attempts': 0, 'error': ''}
    error = ''
    for attempt in range(1, retries + 1):
        if stop.is_set():
            return {'status': 'failed', 'size_bytes': '', 'attempts': attempt - 1, 'error': 'interrupted'}
        try:
            size = fetch(report['source_url'], dest, timeout)
            return {'status': 'downloaded', 'size_bytes': size, 'attempts': attempt, 'error': ''}
        except PermanentError as e:
            log.error('FAILED %s: %s (%s)', report['filename'], e, report['source_url'])
            return {'status': 'failed', 'size_bytes': '', 'attempts': attempt, 'error': str(e)}
        except (urllib.error.URLError, OSError, ValueError) as e:
            error = str(getattr(e, 'reason', None) or e)
            if attempt < retries:
                wait = min(2 ** attempt, 60)
                log.warning('Retry %d/%d for %s in %ds: %s', attempt, retries - 1, report['filename'], wait, error)
                stop.wait(wait)
    log.error('FAILED %s after %d attempts: %s (%s)', report['filename'], retries, error, report['source_url'])
    return {'status': 'failed', 'size_bytes': '', 'attempts': retries, 'error': error}


def run_downloads(reports, out_dir, manifest, workers, retries, timeout):
    stop = threading.Event()
    done, counts = 0, {}

    def task(r):
        res = download_one(r, out_dir, retries, timeout, stop)
        res['updated_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        return r, res

    def record(r, res):   # main thread only
        nonlocal done
        r.update(res)
        done += 1
        counts[res['status']] = counts.get(res['status'], 0) + 1
        if res['status'] == 'downloaded':
            log.info('[%d/%d] %s (%s bytes)', done, len(reports), r['filename'], res['size_bytes'])
        if done % 50 == 0:
            write_manifest(manifest, reports)
            log.info('Progress %d/%d: %s', done, len(reports), counts)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        pending = {pool.submit(task, r) for r in reports}
        while pending:
            # A timed wait keeps Ctrl+C responsive on Windows.
            finished, pending = concurrent.futures.wait(pending, timeout=1,
                                                        return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in finished:
                record(*fut.result())
    except KeyboardInterrupt:
        log.warning('Interrupted; finishing current files and writing the manifest. Rerun to resume.')
        stop.set()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        for r in reports:
            if not r.get('status') or r['status'] == 'pending':
                r['status'] = 'pending'
        write_manifest(manifest, reports)
    return counts


# ---------------------------------------------------------------------------
# CLI

def setup_logging(log_file, verbose):
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')   # names a Windows console code page cannot show
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    log.propagate = False
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('review_csv', help='review CSV written by fac_special_districts.py')
    p.add_argument('--output', default='fac_pdfs_2025', help='folder for PDFs, manifest and log (default: fac_pdfs_2025)')
    p.add_argument('--action', default='include',
                   help='comma-separated actions to download (default: include), e.g. include,review')
    p.add_argument('--states', help='comma-separated state codes to limit the run, e.g. AK,CA')
    p.add_argument('--limit', type=int, help='download at most this many reports (for a test batch)')
    p.add_argument('--workers', type=int, default=4, help=f'parallel downloads, 1-{MAX_WORKERS} (default: 4)')
    p.add_argument('--retries', type=int, default=5, help='attempts per file before it is logged as failed (default: 5)')
    p.add_argument('--timeout', type=int, default=300, help='seconds per network read (default: 300)')
    p.add_argument('--list-only', action='store_true', help='write the manifest with file names, download nothing')
    p.add_argument('--verbose', action='store_true')
    p.add_argument('--pdf-url', default=PDF_URL, help=argparse.SUPPRESS)   # for tests
    a = p.parse_args(argv)
    if not 1 <= a.workers <= MAX_WORKERS:
        p.error(f'--workers must be between 1 and {MAX_WORKERS}')
    if a.retries < 1:
        p.error('--retries must be at least 1')
    if a.limit is not None and a.limit < 1:
        p.error('--limit must be at least 1')
    a.actions = {s.strip().casefold() for s in a.action.split(',') if s.strip()}
    if not a.actions:
        p.error('--action needs at least one action')
    a.states = {s.strip().upper() for s in a.states.split(',') if s.strip()} if a.states else None
    return a


def main(argv=None):
    args = parse_args(argv)
    src = Path(args.review_csv)
    if not src.is_file():
        print(f'Review CSV not found: {src}', file=sys.stderr)
        return 2
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir / 'download_log.txt', args.verbose)

    rows = read_csv(src)
    if rows and 'report_id' not in rows[0]:
        log.error('%s has no report_id column; is it a fac_special_districts.py review CSV?', src)
        return 2
    reports, skipped = select_reports(rows, args.actions, args.states, args.pdf_url)
    assign_filenames(reports)
    if args.limit:
        reports = reports[:args.limit]
    manifest = out_dir / 'manifest.csv'
    if manifest.exists():
        merge_manifest(reports, read_csv(manifest))
    log.info('%d reports with action %s in %s (%d rows skipped without a report ID)',
             len(reports), '/'.join(sorted(args.actions)), src, skipped)
    if args.list_only:
        for r in reports:
            r.setdefault('status', 'pending')
        write_manifest(manifest, reports)
        log.info('List only: wrote %s. Nothing was downloaded.', manifest)
        return 0
    try:
        counts = run_downloads(reports, out_dir, manifest, args.workers, args.retries, args.timeout)
    except KeyboardInterrupt:
        return 130
    total = sum(int(r['size_bytes']) for r in reports if str(r.get('size_bytes') or '').isdigit())
    log.info('Done: %s. %.1f GB in %s. Manifest: %s', counts, total / 1e9, out_dir, manifest)
    if counts.get('failed'):
        log.info('Rerun the same command to retry the %d failed reports.', counts['failed'])
    return 1 if counts.get('failed') else 0


if __name__ == '__main__':
    sys.exit(main())
