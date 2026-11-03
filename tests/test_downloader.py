"""Offline tests for acfrs_downloader.py against a local fake site."""
import csv
import http.server
import io
import logging
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acfrs_downloader as d

PDF = b'%PDF-1.4\n' + b'x' * 5000 + b'\n%%EOF\n'


def row(state, entity_id, entity, year, cat, url):
    return (f'<tr><td><a href="/external/state/{state}/">{state}</a></td>'
            f'<td><a href="/external/entity/{entity_id}/">{entity}</a></td><td>{year}</td>'
            f'<td><a href="/external/category/{cat}/">{cat}</td>'
            f'<td><a href="{url}" target="_blank">Download</a></td></tr>')


class FakeSite(http.server.BaseHTTPRequestHandler):
    """Minimal imitation of the site's login, folder pages and file store."""
    pages = {}
    files = {}
    flaky = {}          # path -> number of 503s before success
    truncated = set()   # paths that send fewer bytes than Content-Length
    hits = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body=b'', ctype='text/html', length=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def _logged_in(self):
        return 'sessionid=ok' in self.headers.get('Cookie', '')

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split('?')[0])
        FakeSite.hits[path] = FakeSite.hits.get(path, 0) + 1
        if path.startswith('/files/'):
            if FakeSite.flaky.get(path, 0) > 0:
                FakeSite.flaky[path] -= 1
                return self._send(503, b'busy')
            if path not in FakeSite.files:
                return self._send(404, b'missing')
            body = FakeSite.files[path]
            if path in FakeSite.truncated:
                self.send_response(200)
                self.send_header('Content-Length', str(len(body) + 100))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._send(200, body, 'application/pdf')
        if path == d.LOGIN_PATH:
            return self._send(200, b'<form><input type="hidden" name="csrfmiddlewaretoken" value="tok">'
                                   b'<input name="password"></form>')
        if not self._logged_in():
            self.send_response(302)
            self.send_header('Location', d.LOGIN_PATH + '?next=' + self.path)
            self.end_headers()
            return
        if path in FakeSite.pages:
            return self._send(200, FakeSite.pages[path].encode())
        self._send(404, b'no page')

    def do_POST(self):
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
        if form.get('username') == ['user'] and form.get('password') == ['secret'] and form.get('csrfmiddlewaretoken') == ['tok']:
            self.send_response(302)
            self.send_header('Set-Cookie', 'sessionid=ok; Path=/')
            self.send_header('Location', '/')
            self.end_headers()
        else:
            self._send(200, b'<form><input name="password"></form>')


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These tests fail downloads on purpose; keep their log lines out of the test output.
        d.log.addHandler(logging.NullHandler())
        d.log.propagate = False
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeSite)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        b = self.base
        FakeSite.files = {'/files/a.pdf': PDF, '/files/b.pdf': PDF + b'b', '/files/c.pdf': PDF + b'cc',
                          '/files/flaky.pdf': PDF, '/files/html.pdf': b'<html>error</html>',
                          '/files/short.pdf': PDF}
        FakeSite.flaky, FakeSite.truncated, FakeSite.hits = {}, set(), {}
        FakeSite.pages = {
            '/': 'home',
            '/external/states/': '<a href="/external/state/AK/">Alaska</a><a href="/external/state/CA/">California</a>',
            '/external/state/AK/': ('<td><a href="/external/state_category/AK/General Purpose/">General Purpose</a></td><td>2</td>'
                                    '<td><a href="/external/state_category/AK/Charter School/">Charter School</a></td><td>0</td>'),
            '/external/state/CA/': '<td><a href="/external/state_category/CA/School District/">School District</a></td><td>1,234</td>',
            '/external/state_category/AK/General Purpose/': (
                '<td><a href="/external/state_category_year/AK/General Purpose/2025/">2025</a></td><td>2</td>'
                '<td><a href="/external/state_category_year/AK/General Purpose/2024/">2024</a></td><td>3</td>'),
            '/external/state_category/CA/School District/':
                '<td><a href="/external/state_category_year/CA/School District/2024/">2024</a></td><td>1</td>',
            '/external/state_category_year/AK/General Purpose/2025/': '<table>' + row('AK', 1, 'Juneau &amp; Borough', 2025, 'General Purpose', b + '/files/a.pdf')
                + row('AK', 2, 'Delta/Greely', 2025, 'General Purpose', b + '/files/b.pdf') + '</table>',
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def site(self, password='secret'):
        s = d.Site('user', password, base=self.base, timeout=10)
        s.login()
        return s

    def report(self, path, name='AK Test 2025.pdf'):
        return {'state': 'AK', 'category': 'General Purpose', 'entity': 'Test', 'entity_id': '9',
                'fiscal_year': 2025, 'source_url': self.base + path, 'filename': name}

    # --- names ---
    def test_clean_entity_is_windows_safe(self):
        self.assertEqual(d.clean_entity('Delta/Greely: "A" <b>|c?*'), 'Delta-Greely- -A- -b--c--')
        self.assertEqual(d.clean_entity('  College   Options, Inc.  '), 'College Options, Inc.')
        self.assertEqual(len(d.clean_entity('x' * 300)), d.MAX_ENTITY_CHARS)

    def test_filenames_follow_extractor_pattern(self):
        r = d.assign_filenames([{'state': 'CA', 'entity': 'Alameda County', 'entity_id': '1', 'fiscal_year': 2025,
                                 'source_url': 'u'}])[0]
        self.assertEqual(r['filename'], 'CA Alameda County 2025.pdf')
        stem = r['filename'][:-4]
        sys.modules.setdefault('pymupdf', mock.MagicMock())
        import acfr_extractor
        m = acfr_extractor.FILENAME_PATTERNS[0].match(stem)
        self.assertEqual((m[1], m[2], m[3]), ('CA', 'Alameda County', '2025'))

    def test_case_insensitive_collisions_get_entity_ids(self):
        rs = [{'state': 'TX', 'entity': 'Lake ISD', 'entity_id': '20', 'fiscal_year': 2025, 'source_url': 'b'},
              {'state': 'TX', 'entity': 'lake isd', 'entity_id': '10', 'fiscal_year': 2025, 'source_url': 'a'},
              {'state': 'TX', 'entity': 'Lake ISD', 'entity_id': '10', 'fiscal_year': 2025, 'source_url': 'c'},
              {'state': 'OK', 'entity': 'Lake ISD', 'entity_id': '30', 'fiscal_year': 2025, 'source_url': 'd'}]
        names = {r['source_url']: r['filename'] for r in d.assign_filenames(rs)}
        self.assertEqual(names, {'a': 'TX lake isd (id10) 2025.pdf', 'c': 'TX Lake ISD (id10-2) 2025.pdf',
                                 'b': 'TX Lake ISD (id20) 2025.pdf', 'd': 'OK Lake ISD 2025.pdf'})
        self.assertEqual(len({n.casefold() for n in names.values()}), 4)

    # --- login and crawl ---
    def test_bad_password_is_rejected_without_echoing_it(self):
        with self.assertRaises(d.LoginError) as cm:
            self.site(password='wrong-pass')
        self.assertNotIn('wrong-pass', str(cm.exception))

    def test_crawl_walks_states_categories_and_year(self):
        reports = d.crawl(self.site(), 2025, workers=2)
        self.assertEqual([r['filename'] for r in reports], ['AK Delta-Greely 2025.pdf', 'AK Juneau & Borough 2025.pdf'])
        self.assertEqual(reports[1]['entity'], 'Juneau & Borough')
        self.assertEqual(reports[1]['entity_id'], '1')
        self.assertNotIn('/external/state_category/AK/Charter School/', FakeSite.hits)  # empty folder skipped
        self.assertEqual(d.crawl(self.site(), 2025, states={'CA'}), [])

    def test_crawl_logs_in_again_when_session_expires(self):
        s = self.site()
        s._jar.clear()
        self.assertEqual(len(d.crawl(s, 2025, states={'AK'})), 2)

    # --- downloads ---
    def test_download_resume_and_failures(self):
        reports = [self.report('/files/a.pdf', 'AK A 2025.pdf'), self.report('/files/missing.pdf', 'AK Missing 2025.pdf'),
                   self.report('/files/html.pdf', 'AK Html 2025.pdf')]
        manifest = self.out / 'manifest.csv'
        counts = d.run_downloads(reports, self.out, manifest, workers=2, retries=3, timeout=10)
        self.assertEqual(counts, {'downloaded': 1, 'failed': 2})
        self.assertEqual((self.out / 'AK A 2025.pdf').read_bytes(), PDF)
        self.assertFalse(any(p.suffix == '.part' for p in self.out.iterdir()))
        with open(manifest, encoding='utf-8-sig') as f:
            rows = {r['filename']: r for r in csv.DictReader(f)}
        self.assertEqual(list(rows['AK A 2025.pdf'])[:len(d.MANIFEST_FIELDS)], d.MANIFEST_FIELDS)
        self.assertEqual(rows['AK A 2025.pdf']['size_bytes'], str(len(PDF)))
        self.assertEqual(rows['AK A 2025.pdf']['source_url'], self.base + '/files/a.pdf')
        self.assertEqual(rows['AK Missing 2025.pdf']['status'], 'failed')
        self.assertIn('404', rows['AK Missing 2025.pdf']['error'])
        self.assertEqual(rows['AK Missing 2025.pdf']['attempts'], '1')  # 404 is not retried
        self.assertIn('not a PDF', rows['AK Html 2025.pdf']['error'])
        # Second run: finished file skipped without a request, failure retried.
        FakeSite.files['/files/missing.pdf'] = PDF
        before = FakeSite.hits.get('/files/a.pdf')
        counts = d.run_downloads([dict(r, status=None) for r in reports[:2]], self.out, manifest, 2, 3, 10)
        self.assertEqual(counts, {'already_present': 1, 'downloaded': 1})
        self.assertEqual(FakeSite.hits.get('/files/a.pdf'), before)

    def test_transient_errors_are_retried(self):
        FakeSite.flaky['/files/flaky.pdf'] = 2
        with mock.patch.object(threading.Event, 'wait'):
            res = d.download_one(self.report('/files/flaky.pdf'), self.out, 5, 10, threading.Event())
        self.assertEqual((res['status'], res['attempts']), ('downloaded', 3))

    def test_truncated_download_is_not_kept(self):
        FakeSite.truncated.add('/files/short.pdf')
        with mock.patch.object(threading.Event, 'wait'):
            res = d.download_one(self.report('/files/short.pdf'), self.out, 2, 10, threading.Event())
        self.assertEqual(res['status'], 'failed')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_missing_credentials_exit_cleanly(self):
        with mock.patch.dict(os.environ, {'ACFRS_USERNAME': '', 'ACFRS_PASSWORD': ''}):
            with mock.patch('sys.stderr', io.StringIO()) as err:
                self.assertEqual(d.main(['--output', str(self.out)]), 2)
        self.assertIn('ACFRS_USERNAME', err.getvalue())


if __name__ == '__main__':
    unittest.main()
