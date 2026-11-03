"""Find fiscal-year special district single audits on the Federal Audit Clearinghouse.

Pulls every report in the FAC API "general" table with entity_type "local" and a
fiscal year ending in the requested year (filtered on fy_end_date, not
audit_year), classifies each auditee as Special District, General Purpose,
School District or something else, and writes a review CSV. Nothing is
downloaded: review the CSV first.

Classification, in order:
  1. Housing authorities are always included (name rule).
  2. State-level finance agencies are excluded (name rule).
  3. The auditee's state + normalized name is looked up in the acfrs.reason.org
     Special District / General Purpose / School District entity lists (crawled
     once and cached), then optionally in the Census of Governments 2022 list.
     A match in exactly one category decides; anything ambiguous or where the
     sources disagree goes to review.
  4. Leftovers are classified by name rules ("City of", "Department",
     "Enterprise Fund", "Inc", "School District", "Water District", ...). Weak
     or missing signals go to review.

Rows are de-duplicated by FAC report ID, and auditees already downloaded from
acfrs.reason.org (state + name found in the downloader's manifest.csv with
status downloaded or already_present) are dropped.

Credentials come only from environment variables: FAC_API_KEY (api.data.gov
key) and ACFRS_USERNAME / ACFRS_PASSWORD. They are never written to the
output files, the log or the console.

Stdlib only, except openpyxl when --census is used. Runs on Windows 11 with
Python 3.12-3.14.
"""
import argparse
import collections
import concurrent.futures
import csv
import datetime
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import acfrs_downloader as acfrs

FAC_BASE = 'https://api.fac.gov'
FAC_FIELDS = ['report_id', 'auditee_uei', 'auditee_ein', 'auditee_name', 'auditee_city',
              'auditee_state', 'fy_start_date', 'fy_end_date', 'audit_year', 'entity_type',
              'fac_accepted_date']
FAC_PAGE_SIZE = 10000          # the FAC API returns at most 20,000 rows per request
FAC_SUMMARY_URL = 'https://app.fac.gov/dissemination/summary/{}'
USER_AGENT = 'acfr-caption-extractor-fac/1.0'
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}

CENSUS_URL = 'https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP'
CENSUS_SHEETS = {'General Purpose': 'General Purpose', 'Special District': 'Special District',
                 'School District': 'School District', 'DEP School Dist': 'School District'}

SD, GP, SCHOOL = 'Special District', 'General Purpose', 'School District'
REFERENCE_CATEGORIES = (SD, GP, SCHOOL)
DEPT, NONPROFIT, STATE_AGENCY = 'Department or Fund', 'Non-profit or Corporation', 'State Agency'
CHARTER, HIGHER_ED, UNKNOWN = 'Charter School', 'Higher Education', 'Unknown'
INCLUDE, EXCLUDE, REVIEW = 'include', 'exclude', 'review'
DOWNLOADED_STATUSES = {'downloaded', 'already_present'}

REVIEW_FIELDS = ['name', 'state', 'uei', 'report_id', 'fiscal_year_end', 'proposed_category',
                 'match_method', 'why', 'action', 'city', 'ein', 'fiscal_year_start', 'audit_year',
                 'fac_accepted_date', 'reference_match', 'reports_for_uei', 'fac_summary_url']
REFERENCE_FIELDS = ['source', 'state', 'category', 'entity', 'entity_id']

log = logging.getLogger('fac_special_districts')


# ---------------------------------------------------------------------------
# Name normalization

STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'DC': 'District of Columbia',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois',
    'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana',
    'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
    'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon',
    'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota',
    'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia',
    'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'PR': 'Puerto Rico', 'GU': 'Guam', 'VI': 'Virgin Islands', 'AS': 'American Samoa',
    'MP': 'Northern Mariana Islands',
}
_STATE_TOKENS = {code: name.casefold().split() for code, name in STATE_NAMES.items()}

ABBREVIATIONS = {
    'twp': 'township', 'twsp': 'township', 'dist': 'district', 'dists': 'districts',
    'auth': 'authority', 'hsg': 'housing', 'util': 'utility', 'utils': 'utilities',
    'co': 'county', 'cnty': 'county', 'mun': 'municipal', 'muni': 'municipal',
    'sch': 'school', 'schs': 'schools', 'dept': 'department', 'assn': 'association',
    'assoc': 'association', 'svc': 'service', 'svcs': 'services', 'saint': 'st',
    'ft': 'fort', 'mt': 'mount', 'number': 'no', 'num': 'no', 'nbr': 'no',
    'wtr': 'water', 'swr': 'sewer', 'metro': 'metropolitan', 'pub': 'public',
    'ctr': 'center', 'hosp': 'hospital', 'imp': 'improvement', 'impr': 'improvement',
    'jt': 'joint', 'jnt': 'joint', 'cmty': 'community', 'comm': 'commission',
    'corp': 'corporation', 'incorporated': 'inc', 'regl': 'regional', 'rgnl': 'regional',
}
FILLER = {'of', 'the', 'and', 'for', 'in'}
LOCAL_GOV_WORDS = {'city', 'town', 'village', 'county', 'borough', 'township', 'parish'}
SPECIAL_WORDS = {'authority', 'district', 'commission', 'board', 'agency', 'utility', 'utilities',
                 'port', 'transit', 'sanitary', 'conservancy', 'levee', 'drainage', 'irrigation',
                 'reclamation', 'housing', 'hospital', 'library', 'park', 'cemetery', 'airport'}


def normalize(name, state=None):
    """Lowercase, accent- and punctuation-free form of an entity name.

    Common abbreviations are expanded, a leading "the", "no" before a number and
    a trailing name or code of the entity's own state are dropped."""
    s = unicodedata.normalize('NFKD', name or '')
    s = ''.join(c for c in s if not unicodedata.combining(c)).casefold()
    s = s.replace('&', ' and ').replace('#', ' no ')
    s = re.sub(r"['’`]", '', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    toks = [ABBREVIATIONS.get(t, t) for t in s.split()]
    toks = [t for i, t in enumerate(toks)
            if not (t == 'no' and i + 1 < len(toks) and toks[i + 1][:1].isdigit())]
    while toks and toks[0] == 'the':
        toks = toks[1:]
    if state:
        st = _STATE_TOKENS.get(state.upper())
        for tail in ([state.casefold()], st) if st else ([state.casefold()],):
            if len(toks) > len(tail) and toks[-len(tail):] == tail:
                toks = toks[:-len(tail)]
                if toks and toks[-1] in ('of', 'state'):
                    toks = toks[:-1]
                    if toks and toks[-1] == 'state':
                        toks = toks[:-1]
                break
    return ' '.join(toks)


def token_key(norm):
    """Word-order-free key: "city of austin" and "austin city" give the same key."""
    return ' '.join(sorted(set(norm.split()) - FILLER))


def loose_key(norm):
    """Token key without city/county/town words, for names with a special-district word.

    Matches "Housing Authority of the City of X" to "X Housing Authority". Only
    used for classification, never to drop rows as already downloaded."""
    toks = set(norm.split()) - FILLER
    if not toks & SPECIAL_WORDS:
        return ''
    rest = toks - LOCAL_GOV_WORDS
    return ' '.join(sorted(rest)) if len(rest) >= 2 and rest != toks else ''


def bare_key(norm):
    """Place name without city/county/town words: "City of Hughes" -> "hughes"."""
    return ' '.join(sorted(set(norm.split()) - FILLER - LOCAL_GOV_WORDS))


def name_keys(name, state, loose=True):
    """(method, kind, key) lookups for a name, strongest first."""
    variants = [('', name)]
    stripped = re.sub(r'\([^)]*\)', ' ', name or '')
    stripped = re.sub(r',?\s*(a|an|the)\s+(blended |discretely presented )?component units?\b.*$', '',
                      stripped, flags=re.I)
    if stripped.strip() and stripped != name:
        variants.append((' (qualifier removed)', stripped))
    out, seen = [], set()
    for suffix, text in variants:
        norm = normalize(text, state)
        cands = [('exact' + suffix, 'exact', norm), ('reordered' + suffix, 'tokens', token_key(norm))]
        if loose:
            cands.append(('loose' + suffix, 'loose', loose_key(norm)))
        for method, kind, key in cands:
            if key and (kind, key) not in seen:
                seen.add((kind, key))
                out.append((method, kind, key))
    return out


class NameIndex:
    """(state, normalized name) -> reference entities, for one source."""

    def __init__(self, source):
        self.source = source
        self._idx = collections.defaultdict(list)
        self.size = 0

    def add(self, state, name, category, entity_id=''):
        state = (state or '').upper()
        ref = {'name': name, 'category': category, 'entity_id': entity_id}
        norm = normalize(name, state)
        if not norm:
            return
        self.size += 1
        for kind, key in (('exact', norm), ('tokens', token_key(norm)), ('loose', loose_key(norm)),
                          ('bare', bare_key(norm))):
            if key:
                self._idx[(state, kind, key)].append(ref)

    def lookup(self, state, name, loose=True):
        """(method, refs) for the strongest key that matches, or (None, [])."""
        state = (state or '').upper()
        for method, kind, key in name_keys(name, state, loose):
            refs = self._idx.get((state, kind, key))
            if refs:
                return method, refs
        # acfrs.reason.org often lists a general-purpose government by its bare place name
        # ("Hughes" for "City of Hughes"). Tried only for names shaped like a city/county/town.
        if loose and name_flags(name)['gp']:
            refs = self._idx.get((state, 'bare', bare_key(normalize(name, state))))
            if refs:
                return 'place name', refs
        return None, []


# ---------------------------------------------------------------------------
# Name rules (for leftovers and the two overrides)

def _rx(pattern):
    return re.compile(pattern)


HOUSING_AUTHORITY = _rx(r'\bhousing (?:\w+ ){0,3}(?:authority|commission)\b|\bpublic housing agency\b'
                        r'|\bhousing agency\b|\bhousing (?:and \w+ )?redevelopment\b')
STATE_FINANCE = _rx(r'\b(?:finance|financing|bond bank|mortgage|treasurer|treasury|infrastructure bank'
                    r'|student loan|lottery|housing development authority|housing and finance)\b')
DEPARTMENT = _rx(r'\b(?:department|enterprise fund|enterprise funds|fund|funds|division|office of'
                 r'|district attorney|sheriff|clerk of court|clerk of the circuit court'
                 r'|county attorney|public defender|county treasurer|county auditor)\b')
COMPONENT_UNIT = _rx(r'\bcomponent unit\b')
NONPROFIT = _rx(r'\b(?:inc|llc|foundation|nonprofit|non profit|corporation|association|ltd)\b')
CHARTER_SCHOOL = _rx(r'\bcharter (?:school|schools|academy)\b')
HIGHER_EDUCATION = _rx(r'\b(?:college|university|community college)\b')
SCHOOL_DISTRICT = _rx(
    r'\b(?:school district|school districts|schools|school system|school department|board of education'
    r'|isd|cisd|usd|cusd|csd|ufsd|unified school|school corporation|school unit|school administrative'
    r'|union school|union high school|union free school|school committee|community unit'
    r'|educational service|education service|boces|intermediate unit|regional school'
    r'|school board|parish school|county school|city school|public school)\b')
GP_PREFIX = _rx(r'^(?:city and county|city and borough|town and county|unified government|'
                r'consolidated government|metropolitan government|charter township|city|town|village|'
                r'county|borough|township|parish|municipality|plantation) of (.+)$')
GP_SUFFIX = _rx(r'^(.+?) (?:city|town|village|county|borough|township|charter township|parish|'
                r'county fiscal court|fiscal court|parish police jury|police jury|county commission'
                r'|board of county commissioners|county board of supervisors|county board of commissioners'
                r'|county government|city government|town government|consolidated government'
                r'|unified government|metropolitan government|municipality)$')
SD_STRONG = _rx(r'\b(?:district|districts|authority|joint powers|water supply|sanitary|sanitation'
                r'|conservancy|levee|drainage|irrigation|reclamation|mosquito abatement|transit'
                r'|port of|public power|water control|water users)\b')
SD_WEAK = _rx(r'\b(?:commission|board|agency|council|consortium|cooperative|coop|utilities|utility'
              r'|regional|planning|workforce|joint|service area|trust|center|hospital|library'
              r'|water|sewer|system|alliance|compact|airport|transportation|cemetery|park|parks'
              r'|court|jail|detention|health)\b')
# Weak words that still stop "<place> City" / "Town of <place>" being read as a general-purpose
# government. Place-like words (park, center, health, ...) are left out: "Village of Oak Park".
GP_BLOCK = _rx(r'\b(?:commission|board|agency|council|consortium|cooperative|coop|utilities|utility'
               r'|planning|workforce|service area|hospital|library|sewer|system|alliance|compact'
               r'|airport|transportation|cemetery|jail|detention)\b')
NOT_SD_DISTRICT = _rx(r'\bdistrict (?:court|attorney|judge|clerk)\b|\bjudicial district\b')
# Words that make "City of X ..." an enterprise fund or department. Kept to words that
# rarely appear in place names ("Oak Park", "Light", "Fire Island" stay place names).
SERVICE_WORDS = _rx(r'\b(?:water|waterworks|sewer|sewerage|wastewater|electric|utility|utilities|system'
                    r'|systems|airport|hospital|enterprise|transit|sanitation|solid waste|stormwater'
                    r'|landfill|parking|nursing home|medical center|light and power|power and light'
                    r'|light plant|gas|parks and recreation|recreation|ambulance|ems|golf course)\b')


def starts_with_state(norm):
    """State code whose full name (or "state of <name>") starts the normalized name."""
    toks = norm.split()
    if toks[:2] in (['state', 'of'], ['commonwealth', 'of']):
        toks = toks[2:]
    for code, st in _STATE_TOKENS.items():
        if toks[:len(st)] == st:
            return code
    return None


def name_flags(name):
    norm = normalize(name)
    toks = set(norm.split())
    flags = {
        'housing_authority': bool(HOUSING_AUTHORITY.search(norm)),
        'department_or_fund': bool(DEPARTMENT.search(norm)),
        'component_unit': bool(COMPONENT_UNIT.search(norm)),
        'nonprofit': bool(NONPROFIT.search(norm)),
        'charter': bool(CHARTER_SCHOOL.search(norm)),
        'higher_ed': bool(HIGHER_EDUCATION.search(norm)),
        'school': bool(SCHOOL_DISTRICT.search(norm)),
        'sd_strong': bool(SD_STRONG.search(norm)) and not NOT_SD_DISTRICT.search(norm),
        'sd_weak': bool(SD_WEAK.search(norm)),
        'state_finance': False, 'state_government': False, 'gp': False, 'gp_service': False,
    }
    if norm == 'district of columbia':
        flags['sd_strong'] = False   # a general-purpose government (set below)
    code = starts_with_state(norm)
    if code and norm in (f'state of {STATE_NAMES[code].casefold()}', f'commonwealth of {STATE_NAMES[code].casefold()}'):
        flags['state_government'] = True
    # A state-level finance agency starts with a state name and has no local-government word
    # ("Iowa Finance Authority", but not "Washington County Housing Finance Authority").
    if code and STATE_FINANCE.search(norm) and not toks & LOCAL_GOV_WORDS:
        flags['state_finance'] = True
    m = GP_PREFIX.match(norm) or GP_SUFFIX.match(norm)
    if m:
        rest = m.group(1)
        if SERVICE_WORDS.search(rest) and not SD_STRONG.search(rest) and not re.search(r'\b(?:commission|board)\b', rest):
            flags['gp_service'] = True   # "City of X Water and Sewer System": a city enterprise
        elif not (SD_STRONG.search(rest) or GP_BLOCK.search(rest) or SCHOOL_DISTRICT.search(rest)):
            flags['gp'] = True
    if norm == 'district of columbia':
        flags['gp'] = True
    # A department, office or fund of a city/county/town (or "City of X Water System"): excluded
    # even when a reference list files it as a Special District.
    flags['local_department'] = flags['gp_service'] or (flags['department_or_fund'] and bool(toks & LOCAL_GOV_WORDS))
    return flags


# ---------------------------------------------------------------------------
# Classification

def _describe(source, method, refs):
    shown = '; '.join(f"{r['category']} '{r['name']}'" + (f" (id {r['entity_id']})" if r['entity_id'] else '')
                      for r in refs[:3])
    more = f' and {len(refs) - 3} more' if len(refs) > 3 else ''
    return f'{source} {method}: {shown}{more}'


def _verdict(category, method, why, ref='', certain=True):
    action = (INCLUDE if category == SD else EXCLUDE) if certain else REVIEW
    return {'proposed_category': category, 'action': action, 'match_method': method,
            'why': why, 'reference_match': ref}


def classify(name, state, indexes):
    """Proposed category, action and explanation for one FAC auditee.

    indexes is a list of NameIndex, most trusted first (acfrs, then Census)."""
    flags = name_flags(name)
    hits = []
    for idx in indexes:
        method, refs = idx.lookup(state, name)
        if refs:
            hits.append((idx.source, method, refs, {r['category'] for r in refs}))
    ref_text = ' | '.join(_describe(s, m, r) for s, m, r, _ in hits)

    if flags['housing_authority']:
        if flags['state_finance']:
            return _verdict(SD, 'name rule: housing authority',
                            'name looks like a housing authority and like a state-level finance agency',
                            ref_text, certain=False)
        why = 'housing authorities are always included'
        others = sorted({c for *_, cats in hits for c in cats} - {SD})
        if others:
            why += f'; reference lists it as {", ".join(others)}'
        return _verdict(SD, 'name rule: housing authority', why, ref_text)

    if flags['local_department']:
        why = 'city/county departments, offices and enterprise funds are excluded'
        listed = sorted({c for *_, cats in hits for c in cats})
        if listed:
            why += f'; reference lists it as {", ".join(listed)}'
        return _verdict(DEPT, 'name rule: department or fund', why, ref_text)

    if flags['state_government']:
        return _verdict(STATE_AGENCY, 'name rule: state government', 'name is a state government', ref_text)

    if flags['state_finance']:
        if any(SD in cats for *_, cats in hits):
            return _verdict(STATE_AGENCY, 'name rule: state finance agency',
                            'name looks like a state-level finance agency but a reference lists it as a '
                            'Special District', ref_text, certain=False)
        return _verdict(STATE_AGENCY, 'name rule: state finance agency',
                        'starts with a state name and names a finance/bond/treasury function', ref_text)

    if hits:
        source, method, refs, cats = hits[0]
        how = f'{source} {method}'
        if len(cats) > 1:
            return _verdict(SD if SD in cats else sorted(cats)[0], how,
                            f'{source} lists this name under several categories: {", ".join(sorted(cats))}',
                            ref_text, certain=False)
        cat = next(iter(cats))
        for other_source, _, _, other_cats in hits[1:]:
            if other_cats != cats:
                return _verdict(cat, how, f'{source} says {cat} but {other_source} says '
                                f'{", ".join(sorted(other_cats))}', ref_text, certain=False)
        agree = [s for s, *_ in hits[1:]]
        if cat == SD and (flags['department_or_fund'] or flags['gp_service']):
            return _verdict(SD, how, f'{source} lists it as a Special District but the name looks like a '
                            'city/county department or enterprise fund', ref_text, certain=False)
        # The reference lists contain some misfiled entities ("Tukwila School District 406" under
        # Special District, sanitation districts under School District): a contradicting name is reviewed.
        named = SCHOOL if flags['school'] else GP if flags['gp'] else SD if flags['sd_strong'] else None
        if named and named != cat and not (cat == GP and named == SD and flags['school']):
            return _verdict(cat, how, f'{source} lists it as {cat} but the name looks like a {named}',
                            ref_text, certain=False)
        why = f'{source} lists it as {cat}' + (f'; {", ".join(agree)} agrees' if agree else '')
        if method.startswith('loose') or (method == 'place name' and cat != GP):
            # Matching without the city/county words may pair different governments' entities.
            return _verdict(cat, how, why + ' (matched without city/county words; check the entity)',
                            ref_text, certain=False)
        return _verdict(cat, how + (' + ' + ' + '.join(agree) if agree else ''), why, ref_text)

    rule = 'name rule'
    if flags['component_unit']:
        return _verdict(SD if flags['sd_strong'] else UNKNOWN, rule,
                        'no reference match; name says it is a component unit of another government',
                        certain=False)
    if flags['department_or_fund']:
        if flags['sd_strong'] and not GP_PREFIX.match(normalize(name)):
            return _verdict(DEPT, rule, 'no reference match; name has both a department/fund word and a '
                            'special-district word', certain=False)
        return _verdict(DEPT, rule, 'no reference match; name looks like a department or fund of a government')
    if flags['gp_service']:
        return _verdict(DEPT, rule, 'no reference match; name is a city/county/town followed by a service '
                        '(an enterprise fund or department)')
    if flags['charter']:
        return _verdict(CHARTER, rule, 'no reference match; name says charter school')
    if flags['school']:
        return _verdict(SCHOOL, rule, 'no reference match; name looks like a school district')
    if flags['higher_ed']:
        return _verdict(HIGHER_ED, rule, 'no reference match; name looks like a college or university',
                        certain=not flags['sd_strong'])
    if flags['gp']:
        return _verdict(GP, rule, 'no reference match; name is a city/county/town/township/village name')
    if flags['nonprofit']:
        if flags['sd_strong']:
            return _verdict(SD, rule, 'no reference match; special-district word but also Inc/Corporation/'
                            'Association', certain=False)
        return _verdict(NONPROFIT, rule, 'no reference match; name has Inc/LLC/Corporation/Foundation/'
                        'Association')
    if flags['sd_strong']:
        return _verdict(SD, rule, 'no reference match; name has a special-district word '
                        '(district, authority, sanitary, levee, ...)')
    if flags['sd_weak']:
        return _verdict(SD, rule, 'no reference match; name has only a weak special-district word '
                        '(commission, board, utility, ...)', certain=False)
    return _verdict(UNKNOWN, 'none', 'no reference match and no name rule applies', certain=False)


# ---------------------------------------------------------------------------
# FAC API

class FacError(RuntimeError):
    pass


class FacClient:
    def __init__(self, api_key, base=FAC_BASE, timeout=120, retries=5):
        self.base = base.rstrip('/')
        self.timeout = timeout
        self.retries = retries
        self._key = api_key

    def get(self, table, params):
        """Rows from one API request. params is a list of (name, value) pairs."""
        url = f'{self.base}/{table}?' + urllib.parse.urlencode(params, safe='.,()')
        req = urllib.request.Request(url, headers={'X-Api-Key': self._key, 'User-Agent': USER_AGENT,
                                                   'Accept': 'application/json'})
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    log.debug('GET %s -> %s (rate limit remaining %s)', url, r.status,
                              r.headers.get('X-RateLimit-Remaining'))
                    return json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', 'replace')[:500]
                retry_after = e.headers.get('Retry-After')
                e.close()
                if e.code not in RETRYABLE_HTTP or attempt == self.retries:
                    if e.code == 403 or 'API_KEY' in body:
                        raise FacError(f'FAC API refused the request (HTTP {e.code}): {body}. '
                                       'Check FAC_API_KEY.') from None
                    raise FacError(f'FAC API HTTP {e.code} for {table}: {body}') from None
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                log.warning('FAC API HTTP %s; retry %d/%d in %ds', e.code, attempt, self.retries - 1, wait)
                time.sleep(min(wait, 300))
            except (urllib.error.URLError, OSError, ValueError) as e:
                if attempt == self.retries:
                    raise FacError(f'FAC API request failed: {e}') from None
                log.warning('FAC API request failed (%s); retry %d/%d', e, attempt, self.retries - 1)
                time.sleep(2 ** attempt)

    def fetch_general(self, fy_end_year, states=None, limit=None, page_size=FAC_PAGE_SIZE):
        """All local-government general rows whose fiscal year ends in fy_end_year."""
        base = [('select', ','.join(FAC_FIELDS)), ('entity_type', 'eq.local'),
                ('fy_end_date', f'gte.{fy_end_year}-01-01'), ('fy_end_date', f'lte.{fy_end_year}-12-31')]
        if states:
            base.append(('auditee_state', f'in.({",".join(sorted(states))})'))
        base.append(('order', 'report_id.asc'))
        rows, offset = [], 0
        while True:
            size = page_size if limit is None else min(page_size, limit - len(rows))
            if size <= 0:
                break
            page = self.get('general', base + [('limit', str(size)), ('offset', str(offset))])
            if not isinstance(page, list):
                raise FacError(f'unexpected FAC API response: {str(page)[:300]}')
            rows += page
            offset += len(page)
            log.info('FAC: %d rows so far', len(rows))
            if len(page) < size:
                break
        return rows


def audit_year_summary(rows):
    """How audit_year relates to the fiscal-year dates across rows."""
    c = collections.Counter()
    for r in rows:
        ay = str(r.get('audit_year') or '')
        end, start = str(r.get('fy_end_date') or '')[:4], str(r.get('fy_start_date') or '')[:4]
        c['= fy_end_date year' if ay == end else '= fy_start_date year' if ay == start else 'other'] += 1
    return dict(c)


def check_audit_year(client, year):
    """Print audit_year next to the fiscal-year dates for a few reports of each year-end."""
    print(f'{"report_id":<28} {"fy_start":<11} {"fy_end":<11} {"audit_year":<10} auditee')
    rows = []
    for end in (f'{year}-06-30', f'{year}-09-30', f'{year}-12-31', f'{year - 1}-12-31', f'{year + 1}-06-30'):
        rows += client.get('general', [('select', ','.join(FAC_FIELDS)), ('entity_type', 'eq.local'),
                                       ('fy_end_date', f'eq.{end}'), ('order', 'report_id.asc'),
                                       ('limit', '3')])
    for r in rows:
        print(f"{r.get('report_id')!s:<28} {r.get('fy_start_date')!s:<11} {r.get('fy_end_date')!s:<11} "
              f"{r.get('audit_year')!s:<10} {r.get('auditee_name')}")
    print('audit_year matches:', audit_year_summary(rows))


# ---------------------------------------------------------------------------
# Reference lists

def crawl_reference(site, categories=REFERENCE_CATEGORIES, states=None, workers=4):
    """Every entity listed on acfrs.reason.org in the categories, across all years."""
    all_states = acfrs.parse_states(site.get('/external/states/'))
    if not all_states:
        raise RuntimeError('no states found on acfrs.reason.org /external/states/ (site layout changed?)')
    wanted = [s for s in all_states if not states or s in states]
    cat_filter = {c.casefold() for c in categories}

    def listing_pages(state):
        pages = []
        for cat, count in acfrs.parse_state_categories(site.get(f'/external/state/{state}/'), state):
            if count and cat.casefold() in cat_filter:
                years = acfrs.parse_year_links(site.get(f'/external/state_category/{state}/{cat}/'))
                pages += [(state, cat, y) for y in sorted(years)]
        return pages

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pages = [p for ps in pool.map(listing_pages, wanted) for p in ps]
        log.info('acfrs.reason.org: reading %d listing pages in %d states', len(pages), len(wanted))

        def one(page):
            state, cat, year = page
            return state, cat, acfrs.parse_reports(
                site.get(f'/external/state_category_year/{state}/{cat}/{year}/'), site.base)

        entities = {}
        for i, (state, cat, reports) in enumerate(pool.map(one, pages), 1):
            for r in reports:
                key = (r['state'] or state, cat, r['entity_id'] or r['entity'])
                entities.setdefault(key, {'source': 'acfrs', 'state': r['state'] or state, 'category': cat,
                                          'entity': r['entity'], 'entity_id': r['entity_id']})
            if i % 200 == 0:
                log.info('acfrs.reason.org: %d/%d listing pages, %d entities', i, len(pages), len(entities))
    log.info('acfrs.reason.org: %d entities in %s', len(entities), ', '.join(categories))
    return sorted(entities.values(), key=lambda e: (e['state'], e['category'], e['entity'].casefold()))


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def load_census(path):
    """Census of Governments 2022 government units (the .ZIP or the .xlsx inside it)."""
    import openpyxl  # only needed for this optional source
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            member = next((n for n in z.namelist() if n.lower().endswith('.xlsx')), None)
            if not member:
                raise RuntimeError(f'{path} has no .xlsx file')
            data = io.BytesIO(z.read(member))
    else:
        data = path
    wb = openpyxl.load_workbook(data, read_only=True, data_only=True)
    out = []
    try:
        for sheet, cat in CENSUS_SHEETS.items():
            if sheet not in wb.sheetnames:
                log.warning('Census file has no "%s" sheet', sheet)
                continue
            rows = wb[sheet].iter_rows(values_only=True)
            header = [str(h or '').strip() for h in next(rows)]
            col = {h: i for i, h in enumerate(header)}
            if 'UNIT_NAME' not in col or 'STATE' not in col:
                raise RuntimeError(f'Census sheet "{sheet}" has no UNIT_NAME/STATE columns')
            for r in rows:
                name, state = r[col['UNIT_NAME']], r[col['STATE']]
                if name and state:
                    pid = r[col['CENSUS_ID_PID6']] if 'CENSUS_ID_PID6' in col else ''
                    out.append({'source': 'census', 'state': str(state).strip().upper(), 'category': cat,
                                'entity': str(name).strip(), 'entity_id': str(pid or '')})
    finally:
        wb.close()
    log.info('Census of Governments: %d units', len(out))
    return out


def download_file(url, dest, timeout=300):
    part = dest.with_name(dest.name + '.part')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, 'wb') as f:
        while chunk := r.read(1024 * 1024):
            f.write(chunk)
    os.replace(part, dest)


# ---------------------------------------------------------------------------
# Pipeline

def dedupe_reports(rows):
    seen, out = set(), []
    for r in rows:
        rid = r.get('report_id')
        if rid and rid not in seen:
            seen.add(rid)
            out.append(r)
    return out, len(rows) - len(out)


def downloaded_index(manifest_rows):
    idx = NameIndex('manifest')
    for r in manifest_rows:
        if (r.get('status') or '').strip() in DOWNLOADED_STATUSES:
            idx.add(r.get('state'), r.get('entity'), r.get('category') or '', r.get('entity_id') or '')
    return idx


def build_review(fac_rows, indexes, downloaded=None):
    """Review rows plus counts of what was dropped."""
    rows, dupes = dedupe_reports(fac_rows)
    per_uei = collections.Counter(r.get('auditee_uei') for r in rows if r.get('auditee_uei'))
    out, dropped = [], []
    for r in rows:
        name, state = (r.get('auditee_name') or '').strip(), (r.get('auditee_state') or '').strip().upper()
        if downloaded is not None:
            method, refs = downloaded.lookup(state, name, loose=False)
            if refs:
                dropped.append((r, method, refs))
                continue
        v = classify(name, state, indexes)
        uei = r.get('auditee_uei') or ''
        out.append({'name': name, 'state': state, 'uei': uei, 'report_id': r.get('report_id'),
                    'fiscal_year_end': r.get('fy_end_date'), 'fiscal_year_start': r.get('fy_start_date'),
                    'audit_year': r.get('audit_year'), 'city': r.get('auditee_city') or '',
                    'ein': r.get('auditee_ein') or '', 'fac_accepted_date': r.get('fac_accepted_date') or '',
                    'reports_for_uei': per_uei.get(uei, 0) if uei else '',
                    'fac_summary_url': FAC_SUMMARY_URL.format(r.get('report_id')), **v})
    order = {INCLUDE: 0, REVIEW: 1, EXCLUDE: 2}
    out.sort(key=lambda x: (order[x['action']], x['state'], x['name'].casefold(), x['report_id']))
    return out, dupes, dropped


def load_fac(args, out_dir):
    """FAC rows, from the cache in the output folder when it matches the request."""
    cache = out_dir / f'fac_general_fy{args.fy_end_year}.json'
    want = {'fy_end_year': args.fy_end_year, 'states': sorted(args.states or []), 'limit': args.limit,
            'fields': FAC_FIELDS}
    if cache.exists() and not args.refresh_fac:
        try:
            data = json.loads(cache.read_text(encoding='utf-8'))
            if data.get('request') == want:
                log.info('FAC: using %d cached rows from %s (fetched %s; --refresh-fac to fetch again)',
                         len(data['rows']), cache, data.get('fetched_at'))
                return data['rows']
        except (ValueError, KeyError):
            pass
    key = os.environ.get('FAC_API_KEY')
    if not key:
        raise FacError('Set the FAC_API_KEY environment variable (an api.data.gov key) first.')
    rows = FacClient(key, base=args.fac_base).fetch_general(args.fy_end_year, args.states, args.limit)
    tmp = cache.with_name(cache.name + '.tmp')
    tmp.write_text(json.dumps({'request': want, 'fetched_at': datetime.datetime.now().isoformat(timespec='seconds'),
                               'rows': rows}), encoding='utf-8')
    os.replace(tmp, cache)
    return rows


def load_acfrs_reference(args, out_dir):
    suffix = '_' + '-'.join(sorted(args.states)) if args.states else ''
    cache = Path(args.reference_cache) if args.reference_cache else out_dir / f'acfrs_reference_entities{suffix}.csv'
    if cache.exists() and not args.refresh_reference:
        rows = read_csv(cache)
        log.info('acfrs.reason.org: using %d cached entities from %s (--refresh-reference to crawl again)',
                 len(rows), cache)
        return rows
    username, password = os.environ.get('ACFRS_USERNAME'), os.environ.get('ACFRS_PASSWORD')
    if not username or not password:
        raise acfrs.LoginError('Set the ACFRS_USERNAME and ACFRS_PASSWORD environment variables first.')
    site = acfrs.Site(username, password)
    site.login()
    rows = crawl_reference(site, REFERENCE_CATEGORIES, args.states, workers=args.workers)
    write_csv(cache, REFERENCE_FIELDS, rows)
    return rows


def load_census_reference(args, out_dir):
    if not args.census:
        return []
    path = Path(args.census)
    if args.census.lower() == 'download':
        path = out_dir / 'govt_units_2022.zip'
        if not path.exists():
            log.info('Downloading the Census of Governments 2022 list from %s', CENSUS_URL)
            download_file(CENSUS_URL, path)
    if not path.exists():
        raise FileNotFoundError(f'Census file not found: {path}')
    return load_census(path)


def build_index(source, rows):
    idx = NameIndex(source)
    for r in rows:
        idx.add(r['state'], r['entity'], r['category'], r.get('entity_id', ''))
    return idx


def setup_logging(log_file, verbose):
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    acfrs.log.setLevel(logging.INFO)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    handlers = [console]
    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(fmt)
        handlers.append(fh)
    for lg in (log, acfrs.log):
        for h in list(lg.handlers):   # a second main() in one process must not log twice
            lg.removeHandler(h)
            h.close()
        lg.propagate = False
        for h in handlers:
            lg.addHandler(h)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--output', default='fac_2025', help='folder for the review CSV, caches and log (default: fac_2025)')
    p.add_argument('--fy-end-year', type=int, default=2025, help='fiscal years ending in this year (default: 2025)')
    p.add_argument('--manifest', default=str(Path('acfrs_2025') / 'manifest.csv'),
                   help='acfrs_downloader.py manifest; its downloaded entities are dropped (default: acfrs_2025\\manifest.csv)')
    p.add_argument('--no-manifest', action='store_true', help='do not drop already-downloaded entities')
    p.add_argument('--census', help='Census of Governments 2022 file (govt_units_2022.ZIP or its .xlsx), '
                                    'or "download" to fetch it from census.gov')
    p.add_argument('--states', help='comma-separated state codes to limit the run, e.g. AK,CA')
    p.add_argument('--limit', type=int, help='fetch at most this many FAC reports (for a test run)')
    p.add_argument('--reference-cache', help='acfrs entity list CSV (default: in the output folder)')
    p.add_argument('--refresh-reference', action='store_true', help='crawl acfrs.reason.org again')
    p.add_argument('--refresh-fac', action='store_true', help='query the FAC API again instead of using the cache')
    p.add_argument('--workers', type=int, default=4, help='parallel acfrs.reason.org page requests, 1-8 (default: 4)')
    p.add_argument('--check-audit-year', action='store_true',
                   help='print audit_year next to fiscal-year dates for a few FAC reports and exit')
    p.add_argument('--verbose', action='store_true')
    p.add_argument('--fac-base', default=FAC_BASE, help=argparse.SUPPRESS)  # for tests
    a = p.parse_args(argv)
    if not 1 <= a.workers <= 8:
        p.error('--workers must be between 1 and 8')
    if a.limit is not None and a.limit < 1:
        p.error('--limit must be at least 1')
    a.states = {s.strip().upper() for s in a.states.split(',') if s.strip()} if a.states else None
    return a


def main(argv=None):
    args = parse_args(argv)
    if args.check_audit_year:
        setup_logging(None, args.verbose)
        key = os.environ.get('FAC_API_KEY')
        if not key:
            print('Set the FAC_API_KEY environment variable (an api.data.gov key) first.', file=sys.stderr)
            return 2
        try:
            check_audit_year(FacClient(key, base=args.fac_base), args.fy_end_year)
        except FacError as e:
            log.error('%s', e)
            return 2
        return 0

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir / 'fac_log.txt', args.verbose)
    manifest = None if args.no_manifest else Path(args.manifest)
    if manifest is not None and not manifest.exists():
        log.error('Manifest %s not found. Pass --manifest with the acfrs_downloader.py manifest.csv, '
                  'or --no-manifest to keep entities already downloaded.', manifest)
        return 2
    try:
        fac_rows = load_fac(args, out_dir)
        log.info('FAC: %d local-government reports with fiscal year ending in %d', len(fac_rows), args.fy_end_year)
        log.info('FAC audit_year vs fiscal-year dates: %s', audit_year_summary(fac_rows))
        indexes = [build_index('acfrs', load_acfrs_reference(args, out_dir))]
        census = load_census_reference(args, out_dir)
        if census:
            indexes.append(build_index('census', census))
    except (FacError, acfrs.LoginError, RuntimeError, OSError) as e:
        log.error('%s', e)
        return 2
    downloaded = downloaded_index(read_csv(manifest)) if manifest else None
    if downloaded is not None:
        log.info('Manifest: %d downloaded entities in %s', downloaded.size, manifest)

    review, dupes, dropped = build_review(fac_rows, indexes, downloaded)
    out = out_dir / f'fac_fy{args.fy_end_year}_special_district_review.csv'
    write_csv(out, REVIEW_FIELDS, review)
    log.info('Removed %d duplicate report IDs; dropped %d reports of entities already downloaded', dupes, len(dropped))
    for action in (INCLUDE, REVIEW, EXCLUDE):
        cats = collections.Counter(r['proposed_category'] for r in review if r['action'] == action)
        log.info('%-7s %5d  %s', action, sum(cats.values()), dict(cats.most_common()))
    methods = collections.Counter(r['match_method'] for r in review)
    log.info('Match methods: %s', dict(methods.most_common()))
    log.info('Review CSV: %s (%d rows). Nothing was downloaded.', out, len(review))
    return 0


if __name__ == '__main__':
    sys.exit(main())
