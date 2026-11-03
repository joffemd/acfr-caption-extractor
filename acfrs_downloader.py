"""Download fiscal-year ACFRs from acfrs.reason.org for the caption extractor.

Credentials come only from the ACFRS_USERNAME and ACFRS_PASSWORD environment
variables. They are sent to the site's login form and are never written to the
manifest, the log or the console.

The site is organised as states -> categories -> years -> reports. The
downloader walks every state and every category with reports, opens the
requested year's listing and collects each report's download link. Each PDF is
saved as "ST Entity 2025.pdf" (state, entity, fiscal year, separated by spaces),
the name form acfr_extractor.py reads.

Rerunning the same command resumes: finished files are skipped and failed ones
are retried. Files are written to a ".part" file first and renamed when
complete, so an interrupted run never leaves a truncated PDF under its final
name.

Stdlib only; runs on Windows 11 with Python 3.12.
"""
import argparse
import concurrent.futures
import csv
import datetime
import html
import http.cookiejar
import logging
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'https://acfrs.reason.org'
LOGIN_PATH = '/accounts/login/'
USER_AGENT = 'acfr-caption-extractor-downloader/1.0'
MAX_WORKERS = 8
MANIFEST_FIELDS = ['state', 'category', 'entity', 'entity_id', 'fiscal_year', 'source_url',
                   'filename', 'size_bytes', 'status', 'attempts', 'error', 'updated_at']
# Leaves room for a long Windows output directory within the 260-character path limit.
MAX_ENTITY_CHARS = 120
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}

log = logging.getLogger('acfrs_downloader')


class LoginError(RuntimeError):
    pass


class PermanentError(RuntimeError):
    """A download failure that retrying will not fix (for example HTTP 404)."""


# ---------------------------------------------------------------------------
# Site access

class Site:
    """Logged-in session for the listing pages. Thread-safe for reads."""

    def __init__(self, username, password, base=BASE, timeout=60):
        self.base = base.rstrip('/')
        self.timeout = timeout
        self._username, self._password = username, password
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._opener.addheaders = [('User-Agent', USER_AGENT)]
        self._login_lock = threading.Lock()

    def _open(self, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        with self._opener.open(req, timeout=self.timeout) as r:
            return r.geturl(), r.read().decode('utf-8', 'replace')

    def login(self):
        with self._login_lock:
            _, page = self._open(LOGIN_PATH)
            m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
            if not m:
                raise LoginError('login page has no CSRF token')
            body = urllib.parse.urlencode({'csrfmiddlewaretoken': m[1], 'username': self._username,
                                           'password': self._password, 'next': '/'}).encode()
            url, page = self._open(LOGIN_PATH, body, {'Referer': self.base + LOGIN_PATH,
                                                      'Content-Type': 'application/x-www-form-urlencoded'})
            if LOGIN_PATH in urllib.parse.urlparse(url).path or 'name="password"' in page:
                raise LoginError('login rejected: check ACFRS_USERNAME and ACFRS_PASSWORD')
            log.info('Logged in to %s', self.base)

    def get(self, path, retries=4):
        """Fetch a listing page, logging in again if the session has expired."""
        quoted = urllib.parse.quote(path, safe='/')
        for attempt in range(1, retries + 1):
            try:
                url, page = self._open(quoted)
                if LOGIN_PATH in urllib.parse.urlparse(url).path:
                    log.info('Session expired; logging in again')
                    self.login()
                    url, page = self._open(quoted)
                    if LOGIN_PATH in urllib.parse.urlparse(url).path:
                        raise LoginError('still redirected to login after logging in again')
                return page
            except LoginError:
                raise
            except (urllib.error.URLError, OSError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    e.close()
                code = getattr(e, 'code', None)
                if code is not None and code not in RETRYABLE_HTTP or attempt == retries:
                    raise
                wait = 2 ** attempt
                log.warning('GET %s failed (%s); retry %d/%d in %ds', path, e, attempt, retries - 1, wait)
                time.sleep(wait)


# ---------------------------------------------------------------------------
# Parsing

def parse_states(page):
    return sorted(set(re.findall(r'href="/external/state/([A-Z]{2})/"', page)))


def parse_state_categories(page, state):
    """(category, entity count) pairs on a state page."""
    pat = rf'href="/external/state_category/{state}/([^"/]+)/"[^>]*>.*?</a>\s*</td>\s*<td>\s*([\d,]+)'
    return [(html.unescape(c), int(n.replace(',', ''))) for c, n in re.findall(pat, page, re.S)]


def parse_year_links(page):
    """{year: report count} on a state/category page."""
    pat = r'href="/external/state_category_year/[^"]*/((?:19|20)\d\d)/"[^>]*>.*?</a>\s*</td>\s*<td>\s*([\d,]+)'
    return {int(y): int(n.replace(',', '')) for y, n in re.findall(pat, page, re.S)}


ROW = re.compile(r'<tr>(.*?)</tr>', re.S)
CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S)


def _text(fragment):
    return html.unescape(re.sub(r'<[^>]+>', '', fragment)).strip()


def parse_reports(page, base=BASE):
    """Report rows on a year listing page."""
    reports = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        if len(cells) < 5:
            continue
        link = re.search(r'href="([^"]+)"', cells[4])
        ent = re.search(r'href="/external/entity/(\d+)/"', cells[1])
        if not link:
            continue
        year = _text(cells[2])
        reports.append({
            'state': _text(cells[0]),
            'entity': re.sub(r'\s+', ' ', _text(cells[1])),
            'entity_id': ent[1] if ent else '',
            'fiscal_year': int(year) if year.isdigit() else None,
            'category': _text(cells[3]),
            'source_url': urllib.parse.urljoin(base + '/', html.unescape(link[1])),
        })
    return reports


# ---------------------------------------------------------------------------
# File names

WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_entity(name):
    """Entity name safe for a Windows file name and for the extractor's parser.

    Characters Windows forbids become "-" (the extractor turns "_" into spaces),
    and whitespace collapses."""
    name = unicodedata.normalize('NFC', name)
    name = WINDOWS_ILLEGAL.sub('-', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > MAX_ENTITY_CHARS:
        name = name[:MAX_ENTITY_CHARS].rstrip()
    return name or 'Unnamed'


def assign_filenames(reports):
    """Give every report a unique "ST Entity YYYY.pdf" name.

    Windows file names are case-insensitive, so names that differ only in case
    collide. Colliding reports get " (id<entity id>)" after the entity name, plus
    a counter if one entity has several reports that year. Assignment depends
    only on the set of reports, not on crawl order, so reruns give the same names.
    """
    groups = {}
    for r in reports:
        base = f"{r['state']} {clean_entity(r['entity'])} {r['fiscal_year']}"
        groups.setdefault(base.casefold(), []).append((base, r))
    for members in groups.values():
        if len(members) == 1:
            base, r = members[0]
            r['filename'] = base + '.pdf'
            continue
        members.sort(key=lambda m: (int(m[1]['entity_id'] or 0), m[1]['source_url']))
        seen = {}
        for base, r in members:
            tag = f"id{r['entity_id']}" if r['entity_id'] else 'dup'
            seen[tag] = seen.get(tag, 0) + 1
            if seen[tag] > 1:
                tag += f'-{seen[tag]}'
            state, year = r['state'], r['fiscal_year']
            r['filename'] = f"{state} {clean_entity(r['entity'])} ({tag}) {year}.pdf"
    return reports


# ---------------------------------------------------------------------------
# Crawl

def crawl(site, year, states=None, categories=None, workers=4):
    """Walk every state and category folder and return the year's reports."""
    all_states = parse_states(site.get('/external/states/'))
    if not all_states:
        raise RuntimeError('no states found on /external/states/ (site layout changed?)')
    wanted = [s for s in all_states if not states or s in states]
    log.info('Crawling %d states for fiscal year %d', len(wanted), year)
    cat_filter = {c.casefold() for c in categories} if categories else None

    def one_state(state):
        found, expected = [], 0
        for cat, count in parse_state_categories(site.get(f'/external/state/{state}/'), state):
            if count == 0 or cat_filter and cat.casefold() not in cat_filter:
                continue
            years = parse_year_links(site.get(f'/external/state_category/{state}/{cat}/'))
            if year not in years:
                continue
            expected += years[year]
            rows = parse_reports(site.get(f'/external/state_category_year/{state}/{cat}/{year}/'), site.base)
            rows = [r for r in rows if r['fiscal_year'] == year]
            if len(rows) != years[year]:
                log.warning('%s / %s / %d: listing shows %d reports, folder count says %d',
                            state, cat, year, len(rows), years[year])
            found += rows
        log.info('%s: %d reports', state, len(found))
        return found, expected

    reports, expected = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for found, exp in pool.map(one_state, wanted):
            reports += found
            expected += exp
    unique = {}
    for r in reports:
        unique.setdefault(r['source_url'], r)
    if len(unique) != len(reports):
        log.info('%d duplicate listings of the same file removed', len(reports) - len(unique))
    log.info('Found %d reports (folder counts total %d)', len(unique), expected)
    return sorted(assign_filenames(list(unique.values())), key=lambda r: r['filename'].casefold())


# ---------------------------------------------------------------------------
# Download

_local = threading.local()


def _download_opener():
    # The PDFs are public S3 objects; a plain opener keeps site cookies off those requests.
    if not hasattr(_local, 'opener'):
        _local.opener = urllib.request.build_opener()
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
        with _download_opener().open(urllib.request.Request(url), timeout=timeout) as r:
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
        e.close()  # release the error response's connection; only code and reason are used
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


def write_manifest(path, reports):
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(reports)
    os.replace(tmp, path)


def run_downloads(reports, out_dir, manifest, workers, retries, timeout):
    stop = threading.Event()
    done = 0
    counts = {}

    def task(r):
        res = download_one(r, out_dir, retries, timeout, stop)
        res['updated_at'] = datetime.datetime.now().isoformat(timespec='seconds')
        return r, res

    def record(r, res):
        # Called only from the main thread, so no lock is needed.
        nonlocal done
        r.update(res)
        done += 1
        counts[res['status']] = counts.get(res['status'], 0) + 1
        if res['status'] == 'downloaded':
            log.info('[%d/%d] %s (%s bytes)', done, len(reports), r['filename'], res['size_bytes'])
        if done % 100 == 0:
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
            r.setdefault('status', 'pending')
        write_manifest(manifest, reports)
    return counts


# ---------------------------------------------------------------------------
# CLI

def setup_logging(log_file, verbose):
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Entity names can include characters a Windows console code page cannot show.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(fmt)
    log.addHandler(fh)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--output', default='acfrs_2025', help='directory for PDFs, manifest and log (default: acfrs_2025)')
    p.add_argument('--year', type=int, default=2025, help='fiscal year to download (default: 2025)')
    p.add_argument('--workers', type=int, default=4, help=f'parallel downloads, 1-{MAX_WORKERS} (default: 4)')
    p.add_argument('--retries', type=int, default=5, help='attempts per file before it is logged as failed (default: 5)')
    p.add_argument('--timeout', type=int, default=300, help='seconds per network read (default: 300)')
    p.add_argument('--states', help='comma-separated state codes to limit the run, e.g. AK,CA')
    p.add_argument('--categories', help='comma-separated categories to limit the run, e.g. "General Purpose,School District"')
    p.add_argument('--limit', type=int, help='download at most this many reports (for a test batch)')
    p.add_argument('--list-only', action='store_true', help='crawl and write the manifest without downloading')
    p.add_argument('--verbose', action='store_true')
    a = p.parse_args(argv)
    if not 1 <= a.workers <= MAX_WORKERS:
        p.error(f'--workers must be between 1 and {MAX_WORKERS}')
    if a.retries < 1:
        p.error('--retries must be at least 1')
    return a


def main(argv=None):
    args = parse_args(argv)
    username, password = os.environ.get('ACFRS_USERNAME'), os.environ.get('ACFRS_PASSWORD')
    if not username or not password:
        print('Set the ACFRS_USERNAME and ACFRS_PASSWORD environment variables first.', file=sys.stderr)
        return 2
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir / 'download_log.txt', args.verbose)
    manifest = out_dir / 'manifest.csv'

    site = Site(username, password)
    try:
        site.login()
    except LoginError as e:
        log.error('%s', e)
        return 2
    states = {s.strip().upper() for s in args.states.split(',')} if args.states else None
    cats = [c.strip() for c in args.categories.split(',')] if args.categories else None
    reports = crawl(site, args.year, states, cats, workers=min(args.workers, 4))
    if args.limit is not None:
        reports = reports[:args.limit]
    if args.list_only:
        for r in reports:
            r['status'] = 'listed'
        write_manifest(manifest, reports)
        log.info('Listed %d reports in %s', len(reports), manifest)
        return 0

    log.info('Downloading %d reports to %s with %d workers', len(reports), out_dir.resolve(), args.workers)
    try:
        counts = run_downloads(reports, out_dir, manifest, args.workers, args.retries, args.timeout)
    except KeyboardInterrupt:
        return 130
    log.info('Done: %s. Manifest: %s', counts, manifest)
    if counts.get('failed'):
        log.warning('%d reports failed; rerun the same command to retry them.', counts['failed'])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
