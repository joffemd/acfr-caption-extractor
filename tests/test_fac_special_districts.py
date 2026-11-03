"""Offline tests for fac_special_districts.py (fake FAC API, no network)."""
import csv
import http.server
import io
import json
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
import fac_special_districts as f


def index(source, entries):
    idx = f.NameIndex(source)
    for state, name, cat in entries:
        idx.add(state, name, cat)
    return idx


def fac_row(rid, name, state, uei='UEI1', end='2025-06-30', start='2024-07-01', year='2025'):
    return {'report_id': rid, 'auditee_uei': uei, 'auditee_ein': '123', 'auditee_name': name,
            'auditee_city': 'Town', 'auditee_state': state, 'fy_start_date': start, 'fy_end_date': end,
            'audit_year': year, 'entity_type': 'local', 'fac_accepted_date': '2026-01-15'}


class NormalizeTests(unittest.TestCase):
    def test_punctuation_case_accents_and_abbreviations(self):
        self.assertEqual(f.normalize('St. Mary’s Water Dist. #2'), 'st marys water district 2')
        self.assertEqual(f.normalize('Cañon City Hsg. Auth.'), 'canon city housing authority')
        self.assertEqual(f.normalize('Fire District No. 1'), f.normalize('Fire District 1'))
        self.assertEqual(f.normalize('The Port of Tacoma'), 'port of tacoma')

    def test_trailing_state_removed_only_for_own_state(self):
        self.assertEqual(f.normalize('City of Austin, Texas', 'TX'), 'city of austin')
        self.assertEqual(f.normalize('City of Austin, State of Texas', 'TX'), 'city of austin')
        self.assertEqual(f.normalize('Kansas City, MO', 'MO'), 'kansas city')
        self.assertEqual(f.normalize('City of Nevada', 'MO'), 'city of nevada')
        self.assertEqual(f.normalize('Indiana', 'IN'), 'indiana')

    def test_word_order_key(self):
        self.assertEqual(f.token_key(f.normalize('COUNTY OF AUTAUGA')), f.token_key(f.normalize('Autauga County')))
        self.assertNotEqual(f.token_key(f.normalize('Town of X')), f.token_key(f.normalize('X Township')))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.acfrs = index('acfrs', [('TX', 'Austin', f.GP), ('AL', 'Autauga County', f.GP),
                                     ('TX', 'Harris County Flood Control District', f.SD),
                                     ('TX', 'Austin Independent School District', f.SCHOOL),
                                     ('WA', 'Seattle Housing Authority', f.SD),
                                     ('CA', 'Springfield', f.GP), ('CA', 'Springfield', f.SD)])

    def test_reordered_and_place_name(self):
        self.assertEqual(self.acfrs.lookup('AL', 'COUNTY OF AUTAUGA')[0], 'reordered')
        method, refs = self.acfrs.lookup('TX', 'City of Austin, Texas')
        self.assertEqual((method, refs[0]['category']), ('place name', f.GP))

    def test_state_must_match(self):
        self.assertEqual(self.acfrs.lookup('OK', 'Austin Independent School District'), (None, []))

    def test_place_name_not_used_for_special_district_names(self):
        self.assertEqual(self.acfrs.lookup('TX', 'Austin Water Utility')[1], [])

    def test_classified_from_reference(self):
        v = f.classify('Harris County Flood Control District', 'TX', [self.acfrs])
        self.assertEqual((v['action'], v['proposed_category'], v['match_method']), ('include', f.SD, 'acfrs exact'))
        v = f.classify('AUSTIN INDEPENDENT SCHOOL DISTRICT', 'TX', [self.acfrs])
        self.assertEqual((v['action'], v['proposed_category']), ('exclude', f.SCHOOL))
        v = f.classify('City of Austin', 'TX', [self.acfrs])
        self.assertEqual((v['action'], v['proposed_category']), ('exclude', f.GP))

    def test_ambiguous_reference_goes_to_review(self):
        v = f.classify('Springfield', 'CA', [self.acfrs])
        self.assertEqual(v['action'], 'review')
        self.assertIn('several categories', v['why'])

    def test_sources_disagree_goes_to_review(self):
        census = index('census', [('TX', 'HARRIS COUNTY FLOOD CONTROL DISTRICT', f.GP)])
        v = f.classify('Harris County Flood Control District', 'TX', [self.acfrs, census])
        self.assertEqual(v['action'], 'review')
        self.assertIn('census says General Purpose', v['why'])

    def test_sources_agree(self):
        census = index('census', [('TX', 'HARRIS COUNTY FLOOD CONTROL DISTRICT', f.SD)])
        v = f.classify('Harris County Flood Control District', 'TX', [self.acfrs, census])
        self.assertEqual((v['action'], v['match_method']), ('include', 'acfrs exact + census'))

    def test_census_only(self):
        census = index('census', [('AL', 'PRATTVILLE WATER WORKS BOARD', f.SD)])
        v = f.classify('Prattville Water Works Board', 'AL', [self.acfrs, census])
        self.assertEqual((v['action'], v['match_method']), ('include', 'census exact'))

    def test_city_department_listed_as_special_district_is_excluded(self):
        acfrs = index('acfrs', [('OH', 'City of Dayton Water Department', f.SD),
                                ('AL', 'City of Huntsville Electric, Natural Gas, and Water Systems', f.SD)])
        for name, st in (('City of Dayton Water Department', 'OH'),
                         ('City of Huntsville Electric, Natural Gas, and Water Systems', 'AL')):
            v = f.classify(name, st, [acfrs])
            self.assertEqual((v['action'], v['proposed_category']), ('exclude', f.DEPT))
            self.assertIn('reference lists it as Special District', v['why'])

    def test_misfiled_reference_entry_is_reviewed(self):
        acfrs = index('acfrs', [('WA', 'Tukwila School District 406', f.SD),
                                ('CO', 'Estes Park Sanitation District', f.SCHOOL)])
        v = f.classify('Tukwila School District No. 406', 'WA', [acfrs])
        self.assertEqual(v['action'], 'review')
        self.assertIn('name looks like a School District', v['why'])
        self.assertEqual(f.classify('Estes Park Sanitation District', 'CO', [acfrs])['action'], 'review')

    def test_state_finance_agency_listed_as_special_district_is_reviewed(self):
        acfrs = index('acfrs', [('AR', 'Arkansas Development Finance Authority', f.SD)])
        v = f.classify('Arkansas Development Finance Authority', 'AR', [acfrs])
        self.assertEqual((v['action'], v['proposed_category']), ('review', f.STATE_AGENCY))


class NameRuleTests(unittest.TestCase):
    def check(self, name, action, category, state='TX'):
        v = f.classify(name, state, [])
        self.assertEqual((v['action'], v['proposed_category']), (action, category), f'{name}: {v}')

    def test_housing_authorities_always_included(self):
        self.check('Housing Authority of the City of Fort Worth', 'include', f.SD)
        self.check('Detroit Housing Commission', 'include', f.SD, 'MI')
        self.check('Housing Authority of the County of Kern, Inc.', 'include', f.SD, 'CA')
        self.check('Minneapolis Public Housing Agency', 'include', f.SD, 'MN')
        # even when a reference list puts it elsewhere
        gp = index('acfrs', [('WA', 'Seattle Housing Authority', f.GP)])
        v = f.classify('Seattle Housing Authority', 'WA', [gp])
        self.assertEqual(v['action'], 'include')
        self.assertIn('reference lists it as General Purpose', v['why'])

    def test_departments_and_enterprise_funds_excluded(self):
        self.check('Riverside County Department of Public Social Services', 'exclude', f.DEPT, 'CA')
        self.check('City of Lubbock Enterprise Fund', 'exclude', f.DEPT)
        self.check('City of Ames Electric Utility', 'exclude', f.DEPT, 'IA')
        self.check('Town of Wallingford Water and Sewer System', 'exclude', f.DEPT, 'CT')
        self.check('Cuyahoga County Sheriff', 'exclude', f.DEPT, 'OH')
        # a district or commission named after a town is not a town department
        self.check('Tri Water District Township', 'include', f.SD, 'OH')
        self.check('City of Lakeland Utilities Commission', 'review', f.SD, 'FL')

    def test_general_purpose_names(self):
        self.check('City of El Paso', 'exclude', f.GP)
        self.check('Village of Oak Park', 'exclude', f.GP, 'IL')
        self.check('Harris County', 'exclude', f.GP)
        self.check('Charter Township of Canton', 'exclude', f.GP, 'MI')
        self.check('Jefferson County Fiscal Court', 'exclude', f.GP, 'KY')
        self.check('District of Columbia', 'exclude', f.GP, 'DC')

    def test_school_districts(self):
        self.check('Austin ISD', 'exclude', f.SCHOOL)
        self.check('Board of Education of Montgomery County', 'exclude', f.SCHOOL, 'MD')
        self.check('Springfield Public Schools', 'exclude', f.SCHOOL, 'MA')

    def test_state_finance_agencies_excluded(self):
        self.check('Iowa Finance Authority', 'exclude', f.STATE_AGENCY, 'IA')
        self.check('State of Ohio Treasurer', 'exclude', f.STATE_AGENCY, 'OH')
        self.check('State of Alaska', 'exclude', f.STATE_AGENCY, 'AK')
        self.check('Commonwealth of Kentucky', 'exclude', f.STATE_AGENCY, 'KY')
        # a county agency is not state-level
        self.check('Washington County Housing Finance Authority', 'include', f.SD, 'OR')
        # housing + state finance conflict
        self.check('Colorado Housing and Finance Authority', 'review', f.SD, 'CO')

    def test_inc_and_corporations(self):
        self.check('Helping Hands Inc.', 'exclude', f.NONPROFIT)
        self.check('ABC Water Supply Corporation', 'review', f.SD)

    # Fixes from the live FAC fiscal-2025 sample (names as FAC lists them).
    def test_nonprofit_category_is_a_label(self):
        v = f.classify('Central Peninsula General Hospital Inc', 'AK', [])
        self.assertEqual((v['action'], v['proposed_category']), ('exclude', 'Non-profit or Corporation'))

    def test_corporation_named_after_a_parish_is_not_a_government(self):
        self.check("CORPORATION OF ST. PATRICK'S PARISH", 'exclude', f.NONPROFIT, 'AK')
        self.check('St. Tammany Parish', 'exclude', f.GP, 'LA')

    def test_delaware_levy_court_is_a_county_government(self):
        self.check('Kent County Levy Court', 'exclude', f.GP, 'DE')

    def test_charter_schools_without_the_word_school(self):
        self.check('Aspira of Delaware Charter', 'exclude', f.CHARTER, 'DE')
        self.check('Avon Grove Charter', 'exclude', f.CHARTER, 'PA')
        self.check('CHESTER CHARTER SCHOLARS ACADEMY', 'exclude', f.CHARTER, 'PA')
        self.check('West Philadelphia Achievement Charter Elementary School', 'exclude', f.CHARTER, 'PA')
        self.check('Charter Township of Canton', 'exclude', f.GP, 'MI')

    def test_nj_boards_of_education_and_vocational_schools(self):
        self.check('Red Bank BOE', 'exclude', f.SCHOOL, 'NJ')
        self.check('Ocean County Vocational Technical', 'exclude', f.SCHOOL, 'NJ')

    def test_school_name_settles_a_school_vs_district_listing_conflict(self):
        listed = index('acfrs', [('NJ', 'Lyndhurst Board of Education', f.SCHOOL),
                                 ('NJ', 'Lyndhurst Boe', f.SD), ('CA', 'Springfield', f.GP),
                                 ('CA', 'Springfield', f.SD)])
        v = f.classify('LYNDHURST BOARD OF EDUCATION', 'NJ', [listed])
        self.assertEqual((v['action'], v['proposed_category']), ('exclude', f.SCHOOL))
        self.assertEqual(f.classify('Springfield', 'CA', [listed])['action'], 'review')

    def test_commonwealth_finance_agency(self):
        self.check('COMMONWEALTH FINANCING AUTHORITY', 'exclude', f.STATE_AGENCY, 'PA')
        listed = index('acfrs', [('PA', 'Commonwealth Financing Authority', f.SD)])
        v = f.classify('COMMONWEALTH FINANCING AUTHORITY', 'PA', [listed])
        self.assertEqual((v['action'], v['proposed_category']), ('review', f.STATE_AGENCY))
        # local entities that start with "Commonwealth" but are not finance agencies are unaffected
        self.check('Commonwealth Transit Authority', 'include', f.SD, 'VA')

    def test_state_student_aid_agency(self):
        self.check('Kentucky Higher Education Assistance Authority', 'exclude', f.STATE_AGENCY, 'KY')

    def test_authority_named_after_its_city_is_not_a_city_department(self):
        census = index('census', [('PA', 'HAZLETON CITY AUTHORITY WATER DEPARTMENT', f.SD)])
        v = f.classify('HAZLETON CITY AUTHORITY WATER DEPARTMENT', 'PA', [census])
        self.assertEqual((v['action'], v['proposed_category']), ('review', f.SD))
        self.assertEqual(f.classify('HAZLETON CITY AUTHORITY WATER DEPARTMENT', 'PA', [])['action'], 'review')
        # real city departments stay excluded
        self.check('City of San Bernardino Municipal Water Department', 'exclude', f.DEPT, 'CA')
        self.check('City of Springfield Water District Department', 'exclude', f.DEPT, 'MO')

    def test_special_district_names(self):
        self.check('Orange County Water District', 'include', f.SD, 'CA')
        self.check('Port of Seattle', 'include', f.SD, 'WA')
        self.check('Metropolitan Transit Authority', 'include', f.SD)

    def test_uncertain_goes_to_review(self):
        self.check('Metro Council', 'review', f.SD, 'MN')
        self.check('Airport Authority, a component unit of the City of X', 'review', f.SD)
        self.check('Smith Memorial', 'review', f.UNKNOWN)
        self.check('Third Judicial District Court', 'review', f.SD)


class PipelineTests(unittest.TestCase):
    def test_dedupe_and_manifest_drop(self):
        rows = [fac_row('R1', 'Seattle Housing Authority', 'WA', 'U1'),
                fac_row('R1', 'Seattle Housing Authority', 'WA', 'U1'),
                fac_row('R2', 'City of Austin', 'TX', 'U2'),
                fac_row('R3', 'City of Austin - Housing Authority', 'TX', 'U3'),
                fac_row('R4', 'Port of Seattle', 'WA', 'U4'),
                fac_row('R5', 'Port of Seattle', 'WA', 'U4', end='2025-12-31', start='2025-01-01')]
        manifest = [{'state': 'TX', 'entity': 'City of Austin', 'category': f.GP, 'status': 'downloaded'},
                    {'state': 'WA', 'entity': 'Port of Seattle', 'category': f.SD, 'status': 'failed'}]
        review, dupes, dropped = f.build_review(rows, [], f.downloaded_index(manifest))
        self.assertEqual(dupes, 1)
        self.assertEqual([d[0]['report_id'] for d in dropped], ['R2'])
        by_id = {r['report_id']: r for r in review}
        self.assertEqual(sorted(by_id), ['R1', 'R3', 'R4', 'R5'])   # failed downloads are kept
        self.assertEqual(by_id['R3']['action'], 'include')
        self.assertEqual(by_id['R4']['reports_for_uei'], 2)
        self.assertEqual(review[0]['action'], 'include')

    def test_audit_year_summary(self):
        rows = [fac_row('A', 'x', 'TX', year='2025'), fac_row('B', 'x', 'TX', year='2024'),
                fac_row('C', 'x', 'TX', year='2023')]
        self.assertEqual(f.audit_year_summary(rows),
                         {'= fy_end_date year': 1, '= fy_start_date year': 1, 'other': 1})


class FakeFac(http.server.BaseHTTPRequestHandler):
    rows = []
    requests = []
    fail_first = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeFac.requests.append((self.path, self.headers.get('X-Api-Key')))
        if self.headers.get('X-Api-Key') != 'k':
            return self._send(403, {'error': {'code': 'API_KEY_INVALID'}})
        if FakeFac.fail_first:
            FakeFac.fail_first -= 1
            return self._send(429, {'error': {'code': 'OVER_RATE_LIMIT'}}, {'Retry-After': '0'})
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get('select', [''])[0] == 'bogus':
            return self._send(400, {'message': 'column general.bogus does not exist'})
        rows = [r for r in FakeFac.rows
                if all(op(r, v) for op, v in [(self._cmp, x) for x in q.get('fy_end_date', [])])]
        off, lim = int(q['offset'][0]), int(q['limit'][0])
        self._send(200, rows[off:off + lim])

    @staticmethod
    def _cmp(r, cond):
        op, val = cond.split('.', 1)
        return {'gte': r['fy_end_date'] >= val, 'lte': r['fy_end_date'] <= val, 'eq': r['fy_end_date'] == val}[op]

    def _send(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


class FacApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeFac)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeFac.rows = [fac_row(f'2025-06-GSAFAC-{i:010d}', f'Water District {i}', 'TX', f'U{i}')
                        for i in range(25)]
        FakeFac.rows.append(fac_row('2024-12-GSAFAC-0000000099', 'Old District', 'TX', end='2024-12-31'))
        FakeFac.requests = []
        FakeFac.fail_first = 0
        logging.getLogger('fac_special_districts').setLevel(logging.CRITICAL)

    def test_pagination_filters_and_key_header(self):
        rows = f.FacClient('k', self.base).fetch_general(2025, page_size=10)
        self.assertEqual(len(rows), 25)
        self.assertEqual(len(FakeFac.requests), 3)
        path, key = FakeFac.requests[0]
        self.assertEqual(key, 'k')
        self.assertNotIn('k', urllib.parse.parse_qs(urllib.parse.urlparse(path).query).get('api_key', []))
        self.assertIn('entity_type=eq.local', path)
        self.assertIn('fy_end_date=gte.2025-01-01', path)
        self.assertIn('fy_end_date=lte.2025-12-31', path)
        self.assertIn('order=report_id.asc', path)

    def test_limit(self):
        self.assertEqual(len(f.FacClient('k', self.base).fetch_general(2025, limit=7, page_size=5)), 7)

    def test_rate_limit_retry(self):
        FakeFac.fail_first = 2
        with mock.patch.object(f.time, 'sleep'):
            rows = f.FacClient('k', self.base).fetch_general(2025)
        self.assertEqual(len(rows), 25)

    def test_bad_key_message_does_not_contain_key(self):
        with self.assertRaises(f.FacError) as cm:
            f.FacClient('secret-key-123', self.base).fetch_general(2025)
        self.assertIn('FAC_API_KEY', str(cm.exception))
        self.assertNotIn('secret-key-123', str(cm.exception))

    def test_end_to_end_review_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = tmp / 'out'
            out.mkdir()
            ref = out / 'acfrs_reference_entities.csv'
            f.write_csv(ref, f.REFERENCE_FIELDS, [
                {'source': 'acfrs', 'state': 'TX', 'category': f.SD, 'entity': 'Water District 1', 'entity_id': '9'},
                {'source': 'acfrs', 'state': 'TX', 'category': f.GP, 'entity': 'Water District 2', 'entity_id': '8'}])
            manifest = tmp / 'manifest.csv'
            with open(manifest, 'w', newline='', encoding='utf-8-sig') as fh:
                w = csv.DictWriter(fh, fieldnames=['state', 'category', 'entity', 'status'])
                w.writeheader()
                w.writerow({'state': 'TX', 'category': f.SD, 'entity': 'Water District 3', 'status': 'downloaded'})
            env = {'FAC_API_KEY': 'k', 'ACFRS_USERNAME': '', 'ACFRS_PASSWORD': ''}
            with mock.patch.dict(os.environ, env), mock.patch.object(f.sys, 'stdout', io.StringIO()):
                code = f.main(['--output', str(out), '--manifest', str(manifest), '--fac-base', self.base])
                self.assertEqual(code, 0)
                n_requests = len(FakeFac.requests)
                self.assertEqual(f.main(['--output', str(out), '--manifest', str(manifest),
                                         '--fac-base', self.base]), 0)
                self.assertEqual(len(FakeFac.requests), n_requests)   # second run uses the cache
            for h in list(f.log.handlers) + list(f.acfrs.log.handlers):
                h.close()
            f.log.handlers.clear()
            f.acfrs.log.handlers.clear()
            rows = f.read_csv(out / 'fac_fy2025_special_district_review.csv')
            self.assertEqual(list(rows[0])[:8], ['name', 'state', 'uei', 'report_id', 'fiscal_year_end',
                                                  'proposed_category', 'match_method', 'why'])
            self.assertEqual(len(rows), 24)   # 25 FY2025 rows, one already downloaded
            by_name = {r['name']: r for r in rows}
            self.assertEqual(by_name['Water District 1']['match_method'], 'acfrs exact')
            self.assertEqual(by_name['Water District 2']['proposed_category'], f.GP)
            self.assertEqual(by_name['Water District 4']['match_method'], 'name rule')
            self.assertNotIn('Water District 3', by_name)
            self.assertNotIn('Old District', by_name)
            text = (out / 'fac_log.txt').read_text(encoding='utf-8')
            self.assertNotIn('X-Api-Key', text)
            self.assertIn('Nothing was downloaded', text)

    def test_missing_manifest_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(f.sys, 'stdout', io.StringIO()):
                code = f.main(['--output', tmp, '--manifest', str(Path(tmp) / 'nope.csv')])
            for h in list(f.log.handlers) + list(f.acfrs.log.handlers):
                h.close()
            f.log.handlers.clear()
            f.acfrs.log.handlers.clear()
            self.assertEqual(code, 2)


class CensusTests(unittest.TestCase):
    def test_reads_sheets_from_xlsx_and_zip(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest('openpyxl not installed')
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'General Purpose'
            ws.append(['CENSUS_ID_PID6', 'UNIT_NAME', 'UNIT_TYPE', 'STATE'])
            ws.append(['1', 'COUNTY OF AUTAUGA', '1 - COUNTY', 'AL'])
            ws = wb.create_sheet('Special District')
            ws.append(['CENSUS_ID_PID6', 'UNIT_NAME', 'FUNCTION_NAME', 'STATE'])
            ws.append(['2', 'PRATTVILLE HOUSING AUTHORITY', '50 - HOUSING', 'AL'])
            ws = wb.create_sheet('DEP School Dist')
            ws.append(['CENSUS_ID_PID6', 'UNIT_NAME', 'STATE'])
            ws.append(['3', 'KASHUNAMIUT SCHOOL DISTRICT', 'AK'])
            xlsx = Path(tmp) / 'Govt_Units_2022_Final.xlsx'
            wb.save(xlsx)
            zpath = Path(tmp) / 'govt_units_2022.zip'
            with zipfile.ZipFile(zpath, 'w') as z:
                z.write(xlsx, 'Govt_Units_2022_Final.xlsx')
            logging.getLogger('fac_special_districts').setLevel(logging.CRITICAL)
            for path in (xlsx, zpath):
                rows = f.load_census(path)
                self.assertEqual([(r['state'], r['category']) for r in rows],
                                 [('AL', f.GP), ('AL', f.SD), ('AK', f.SCHOOL)])
            idx = f.build_index('census', rows)
            self.assertEqual(idx.lookup('AL', 'Autauga County')[1][0]['category'], f.GP)


if __name__ == '__main__':
    unittest.main()
