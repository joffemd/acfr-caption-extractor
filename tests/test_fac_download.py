"""Offline tests for fac_download.py (fake FAC server, no network)."""
import csv
import http.server
import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fac_download as d

PDF = b'%PDF-1.4\n%fake\n' + b'x' * 2000


def review_row(rid, name, state='TX', action='include', end='2025-06-30'):
    return {'name': name, 'state': state, 'uei': 'U' + rid[-4:], 'report_id': rid, 'fiscal_year_end': end,
            'proposed_category': 'Special District', 'action': action}


class FakeFac(http.server.BaseHTTPRequestHandler):
    hits = {}
    fail_first = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path
        FakeFac.hits[path] = FakeFac.hits.get(path, 0) + 1
        if path.startswith('/pdf/'):
            rid = path.rsplit('/', 1)[1]
            if FakeFac.fail_first.get(rid):
                FakeFac.fail_first[rid] -= 1
                return self._send(503, b'busy')
            if rid.endswith('0404'):
                return self._send(404, b'not found')
            self.send_response(302)
            self.send_header('Location', f'/s3/{rid}.pdf')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path.startswith('/s3/'):
            body = b'<html>error</html>' if 'GSAFAC-0000000500' in path else PDF
            return self._send(200, body, 'application/pdf')
        self._send(404, b'')

    def _send(self, code, body, ctype='text/plain'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SelectAndNameTests(unittest.TestCase):
    def test_selects_action_dedupes_and_skips_bad_ids(self):
        rows = [review_row('2025-06-GSAFAC-0000000001', 'Port of X'),
                review_row('2025-06-GSAFAC-0000000001', 'Port of X'),
                review_row('2025-06-GSAFAC-0000000002', 'City of Y', action='exclude'),
                review_row('2025-06-GSAFAC-0000000003', 'Z Board', action='review'),
                review_row('not-an-id', 'Bad')]
        with self.assertLogs(d.log, 'WARNING'):
            reports, skipped = d.select_reports(rows, {'include'})
        self.assertEqual([r['report_id'] for r in reports], ['2025-06-GSAFAC-0000000001'])
        self.assertEqual(skipped, 1)
        self.assertEqual(reports[0]['source_url'],
                         'https://app.fac.gov/dissemination/report/pdf/2025-06-GSAFAC-0000000001')
        with self.assertLogs(d.log, 'WARNING'):
            both, _ = d.select_reports(rows, {'include', 'review'})
        self.assertEqual(len(both), 2)
        self.assertEqual(d.select_reports(rows, {'include'}, states={'CA'})[0], [])

    def test_file_names_match_the_extractor_and_never_collide(self):
        rows = [review_row('2025-06-GSAFAC-0000000001', 'ST ANNE UNIT DISTRICT 24', 'IL'),
                review_row('2025-06-GSAFAC-0000000002', 'St Anne Unit District 24', 'IL'),
                review_row('2025-12-GSAFAC-0000000003', 'Authority: "A/B" Water*', 'TX', end='2025-12-31'),
                review_row('2025-06-GSAFAC-0000000004', 'Port of X.', 'WA')]
        reports = d.assign_filenames(d.select_reports(rows, {'include'})[0])
        names = [r['filename'] for r in reports]
        self.assertEqual(names, ['IL ST ANNE UNIT DISTRICT 24 (2025-06-GSAFAC-0000000001) 2025.pdf',
                                 'IL St Anne Unit District 24 (2025-06-GSAFAC-0000000002) 2025.pdf',
                                 'TX Authority- -A-B- Water- 2025.pdf',
                                 'WA Port of X 2025.pdf'])
        self.assertEqual(len({n.casefold() for n in names}), len(names))
        long = d.assign_filenames(d.select_reports([review_row('2025-06-GSAFAC-0000000009', 'A' * 300)],
                                                   {'include'})[0])
        self.assertLessEqual(len(long[0]['filename']), 3 + d.MAX_ENTITY_CHARS + 9)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeFac)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}/pdf/{{}}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        d.log.handlers[:] = [logging.NullHandler()]
        d.log.propagate = False
        d.log.setLevel(logging.INFO)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = self.dir / 'review.csv'
        rows = [review_row('2025-06-GSAFAC-0000000001', 'Port of X', 'WA'),
                review_row('2025-06-GSAFAC-0000000002', 'Y Transit Authority', 'TX'),
                review_row('2025-06-GSAFAC-0000000404', 'Missing District', 'TX'),
                review_row('2025-06-GSAFAC-0000000500', 'Not A Pdf Authority', 'TX'),
                review_row('2025-06-GSAFAC-0000000007', 'City of Z', 'TX', action='exclude')]
        with open(self.csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        FakeFac.hits.clear()
        FakeFac.fail_first = {'2025-06-GSAFAC-0000000002': 1}

    def tearDown(self):
        for h in list(d.log.handlers):
            d.log.removeHandler(h)
            h.close()
        self.tmp.cleanup()

    def run_main(self, *extra):
        out = self.dir / 'out'
        # Keep test output quiet: no console or log-file handlers.
        with mock.patch.object(d, 'setup_logging', lambda *a: None):
            code = d.main([str(self.csv), '--output', str(out), '--pdf-url', self.url, '--workers', '2',
                           '--retries', '3', *extra])
        manifest = {r['report_id']: r for r in d.read_csv(out / 'manifest.csv')}
        return code, out, manifest

    def test_download_retry_failures_and_resume(self):
        code, out, m = self.run_main()
        self.assertEqual(code, 1)   # two permanent failures
        self.assertEqual(sorted(m), ['2025-06-GSAFAC-0000000001', '2025-06-GSAFAC-0000000002',
                                     '2025-06-GSAFAC-0000000404', '2025-06-GSAFAC-0000000500'])
        self.assertEqual(m['2025-06-GSAFAC-0000000001']['status'], 'downloaded')
        self.assertEqual(m['2025-06-GSAFAC-0000000002']['status'], 'downloaded')   # after one 503
        self.assertEqual(m['2025-06-GSAFAC-0000000002']['attempts'], '2')
        self.assertIn('HTTP 404', m['2025-06-GSAFAC-0000000404']['error'])
        self.assertEqual(m['2025-06-GSAFAC-0000000500']['error'], 'response is not a PDF')
        self.assertEqual((out / 'WA Port of X 2025.pdf').read_bytes(), PDF)
        self.assertEqual(sorted(p.name for p in out.glob('*.pdf')),
                         ['TX Y Transit Authority 2025.pdf', 'WA Port of X 2025.pdf'])
        self.assertEqual(list(out.glob('*.part')), [])

        FakeFac.hits.clear()
        code, out, m = self.run_main()
        self.assertEqual(m['2025-06-GSAFAC-0000000001']['status'], 'already_present')
        self.assertNotIn('/pdf/2025-06-GSAFAC-0000000001', FakeFac.hits)   # not fetched again
        self.assertIn('/pdf/2025-06-GSAFAC-0000000404', FakeFac.hits)      # failures retried

    def test_list_only_and_limit(self):
        code, out, m = self.run_main('--list-only')
        self.assertEqual(code, 0)
        self.assertEqual(len(m), 4)
        self.assertEqual({r['status'] for r in m.values()}, {'pending'})
        self.assertEqual(list(out.glob('*.pdf')), [])
        self.assertEqual(FakeFac.hits, {})
        code, out, m = self.run_main('--limit', '1')
        self.assertEqual(code, 0)
        self.assertEqual(len(list(out.glob('*.pdf'))), 1)

    def test_missing_csv(self):
        with mock.patch('sys.stderr'):
            self.assertEqual(d.main([str(self.dir / 'nope.csv'), '--output', str(self.dir / 'o')]), 2)


if __name__ == '__main__':
    unittest.main()
