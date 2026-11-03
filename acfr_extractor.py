"""Offline ACFR caption extraction. Python 3.12; no remote document APIs.

Coordinates are PDF points from top-left; PDF page numbers are one based.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import itertools
import multiprocessing
import multiprocessing.connection
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
import unicodedata
import pymupdf
from legacy_clean_amount import clean_amount

VERSION = '0.6.1'
TYPES = {
 'GW_NET_POSITION':'Government-wide Statement of Net Position',
 'GW_ACTIVITIES':'Government-wide Statement of Activities',
 'GF_BALANCE_SHEET':'Governmental Funds Balance Sheet',
 'GF_OPERATING':'Governmental Funds Revenues Expenditures and Changes in Fund Balances',
 'PF_NET_POSITION':'Proprietary Funds Statement of Net Position',
 'PF_OPERATING':'Proprietary Funds Revenues Expenses and Changes in Net Position',
 'PF_CASH_FLOWS':'Proprietary Funds Statement of Cash Flows',
 'FF_NET_POSITION':'Statement of Fiduciary Net Position',
 'FF_CHANGES':'Statement of Changes in Fiduciary Net Position',
}
CONFIG = Path(__file__).with_name('normalization.json')
NUMERIC = re.compile(r'^[($€£+−–—\-]*\d[\d, .()%$€£+−–—\-]*$')
SECTION = re.compile(r'^(assets(?: and deferred outflows of resources)?|liabilities(?: and deferred inflows of resources)?|deferred (?:outflows|inflows) of resources|net position(?: \(deficit\))?|fund balances?(?: \(deficits?\))?|revenues|expenditures|expenses|additions|deductions|operating revenues|operating expenses|nonoperating revenues.*|cash flows (?:from|for).*)[: ]*$', re.I)
REJECT = re.compile(r'combining|reconciliation|condensed|management.{0,5}s discussion|notes to (?:the )?(?:basic )?financial|budget.{0,12}actual|statistical section',re.I)

SUBHEADING = re.compile(r'^(?:(?:current|noncurrent|non current|capital|restricted|temporarily restricted) assets|(?:current|noncurrent|non current) liabilities|primary government|governmental activities|business.type activities|general revenues|nonspendable|restricted(?: for)?|committed(?: to)?|assigned(?: to)?|due within one year|due in more than one year)[: ]*$', re.I)

def normalized(s):
 s=unicodedata.normalize('NFKC',s).casefold().replace('&',' and ')
 return re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',s)).strip()

def standardize(s, rules):
 s=normalized(s)
 return rules.get('aliases',{}).get(s,s)

def caption_key(caption,section,parent,rules):
 c=standardize(caption,rules)
 if c in rules.get('ambiguous_captions',[]):
  return ' | '.join(dict.fromkeys(x for x in [standardize(section,rules),standardize(parent,rules),c] if x))
 return c

def amount(s):
 s=s.strip()
 if s in {'-','–','—','_','$','(',')','%'}:return True
 if not NUMERIC.fullmatch(s):return False
 # Adapted from legacy date_classifier: require mostly numeric glyphs;
 # retain the existing clean_amount routine as a secondary numeric check.
 return bool(re.search(r'\d',str(clean_amount(s))))

DASHES='-‐‑‒–—―−'
DASH=f'[{DASHES}]'

def label_number(s):
 s=s.strip().strip(' ()'+DASHES)
 s=re.sub(rf'\s*{DASH}\s*','-',s)
 return s if re.fullmatch(r'(?:[IVXLC]+-)?\d{1,4}|[ivxlc]+',s) else ''

def printed_label(rows,height):
 for r in reversed(rows):
  if r['y0']<height*.70:continue
  m=re.match(r'^(\d{1,4})\s*[|:]\s*Financial',r['text'],re.I)
  if m:return m[1]
  v=label_number(r['text'])
  if v:return v
  m=re.search(r'(?:financial(?: section)?\s*[|:]?|annual comprehensive financial report(?: 20\d\d)?)\s*(\d{1,4})\s*$',r['text'],re.I)
  if m:return m[1]
  # Running footers that pair the page number with the government or report
  # name: "16 City of Boston, Massachusetts" / "County of X, Texas 17".
  if r['y0']>height*.88:
   entity=r'(?:city|county|state|commonwealth|district|authority|town|village|township|borough|parish|university|college|board|commission|system|agency|government|report|acfr)'
   m=re.match(rf'^(\d{{1,4}})\s+([A-Z][^\d$]{{3,90}})$',r['text'])
   if m and re.search(rf'\b{entity}\b',m[2],re.I):return m[1]
   m=re.match(rf'^([A-Z][^\d$]{{3,90}}?)\s+(\d{{1,4}})$',r['text'])
   if m and re.search(rf'\b{entity}\b',m[1],re.I) and not re.match(r'(?:total|net|less|add)\b',m[1],re.I):return m[2]
  # Some reports print the page label on the same baseline as a notes footer.
  if r['y0']>height*.70 and re.search(r'notes.*(?:financial statements|integral part)',r['text'],re.I):
   m=re.search(rf'((?:[IVX]+\s*{DASH}\s*)?\d{{1,4}})\s*$',r['text'])
   if m:return label_number(m[1])
 for r in rows:
  if r['y0']>height*.10:continue
  m=re.search(r'(?:financial\s*(?:section)?\s*[|:]?\s*)(\d{1,4})\s*$',r['text'],re.I)
  if m:return m[1]
  m=re.match(r'^(\d{1,4})\s+(?:financial(?: section)?|annual comprehensive)',r['text'],re.I)
  if m:return m[1]
  # A standalone header page number such as "-19-" or "Page 19".
  m=re.search(rf'(?:^|\s)(?:{DASH}\s*(\d{{1,4}})\s*{DASH}|page\s+(\d{{1,4}}))\s*$',r['text'],re.I)
  if m:return m[1] or m[2]
 return ''

def group_words(words):
 """Legacy same-row geometry idea, without its all-pairs NetworkX graph."""
 rows=[]
 for w in sorted(words,key=lambda v:((v[1]+v[3])/2,v[0])):
  x0,y0,x1,y1,text=w[:5]
  if not str(text).strip():continue
  cy=(y0+y1)/2
  if rows and abs(cy-rows[-1]['cy']) <= max(2.1,min(y1-y0,rows[-1]['h'])*.32):
   row=rows[-1];row['words'].append((x0,y0,x1,y1,str(text)))
   row['y0']=min(row['y0'],y0);row['y1']=max(row['y1'],y1)
  else:rows.append({'cy':cy,'h':y1-y0,'y0':y0,'y1':y1,'words':[(x0,y0,x1,y1,str(text))]})
 for row in rows:
  row['words'].sort(key=lambda w:w[0]);row['text']=' '.join(w[4] for w in row['words'])
 return rows

def frame_matrix(page,rotation):
 """Matrix from unrotated PDF space to the page displayed at `rotation` degrees."""
 w,h=page.mediabox.width,page.mediabox.height
 return {0:pymupdf.Matrix(1,0,0,1,0,0),90:pymupdf.Matrix(0,1,-1,0,h,0),180:pymupdf.Matrix(-1,0,0,-1,w,h),270:pymupdf.Matrix(0,-1,1,0,0,w)}[rotation%360],(h,w) if rotation%180 else (w,h)

def native_frame(page):
 """Word rows in the upright reading frame, with that frame's width/height and
 the extra clockwise rotation applied beyond the PDF /Rotate value.

 PDF words use unrotated coordinates, while page.rect and rendering reflect
 /Rotate. Normally the displayed page is the reading frame. Some reports store
 landscape statements with a /Rotate that leaves every line vertical on screen;
 the orientation in which most lines read left to right is then used. Vertical
 decorative sidebars are omitted.
 """
 textpage=page.get_textpage(flags=pymupdf.TEXTFLAGS_WORDS)
 raw={}
 for block in page.get_text('dict',textpage=textpage)['blocks']:
  for j,line in enumerate(block.get('lines',[])):raw[(block['number'],j)]=line['dir']
 def horizontal(matrix):
  a=pymupdf.Point(0,0)*matrix
  return {k:(lambda b:(b.x-a.x,b.y-a.y))(pymupdf.Point(*d)*matrix) for k,d in raw.items()}
 rotation=page.rotation%360
 best=(rotation,)+frame_matrix(page,rotation)
 dirs=horizontal(best[1])
 count=lambda ds:sum(dx>.7 and abs(dy)<=.3 for dx,dy in ds.values())
 current=count(dirs)
 if len(raw)>=20 and current<len(raw)*.4:
  for r in (0,90,180,270):
   if r==rotation:continue
   m,size=frame_matrix(page,r);d=horizontal(m)
   if count(d)>max(current*1.5,len(raw)*.6):best=(r,m,size);dirs=d;current=count(d)
 r,matrix,(width,height)=best
 words=[]
 for word in page.get_text('words',textpage=textpage):
  dx,dy=dirs.get((word[5],word[6]),(1,0))
  if abs(dy)>.3:continue
  box=pymupdf.Rect(word[:4])*matrix
  words.append((*box,word[4]))
 return group_words(words),width,height,(r-rotation)%360

def native_rows(page):
 return native_frame(page)[0]

TOC_LINE=re.compile(rf'[A-Za-z].*?(?:\s|\.)(?:[A-Z]{{1,3}}\s*{DASH}\s*)?(?:\d{{1,3}}|[ivxlc]{{1,6}})(?:\s*(?:{DASH}|and|to)\s*(?:[A-Z]{{1,3}}\s*{DASH}\s*)?\d{{1,3}})?\s*$',re.I)

NUMBER_FIRST=re.compile(rf'^((?:[A-Z]{{1,3}}\s*{DASH}\s*)?\d{{1,4}}(?:\s*{DASH}\s*\d{{1,4}})?)\s+([A-Z].*)$')

def number_first(lines):
 """Rewrite "36 Statement of Net Position" TOC lines as "Statement of Net
 Position 36" when the page uses page-number-first entries."""
 # "A-1 Statement of Net Position 26" is an exhibit code plus a trailing page
 # number, not a number-first entry; only lines without a trailing page number
 # are rewritten.
 trailing=re.compile(rf'\d{{1,4}}(?:\s*{DASH}\s*\d{{1,4}})?\s*$')
 first=lambda v:(lambda m:m if m and not trailing.search(m[2]) else None)(NUMBER_FIRST.match(v))
 if sum(bool(first(v)) for v in lines)<3:return lines
 return [(lambda m:f'{m[2]} {m[1]}' if m else v)(first(v)) for v in lines]

def toc_structure(text):
 """True when the page reads like a contents listing, not a statement.

 Some reports print a "Table of Contents" back-link at the top of every page;
 a title alone must not make a statement page a TOC page.
 """
 lines=number_first([v.strip() for v in text.splitlines() if v.strip()])
 money=lambda v:bool(re.search(r'\d,\d{3}|\$',v))
 amount_line=lambda v:money(v) or (not TOC_LINE.fullmatch(v) and len(re.findall(r'(?<![\w,.])\(?\d[\d,.]*\)?(?![\w,.])',v))>=2)
 entries=sum(bool(TOC_LINE.fullmatch(v)) and not money(v) for v in lines)
 amounts=sum(amount_line(v) for v in lines)
 return entries>=2 and entries>=amounts

def is_toc(text):
 titled=False
 for line in text.splitlines()[:12]:
  n=normalized(line)
  if len(line)<160 and re.sub(r'[^a-z]','',n).startswith('tableofcontent'):titled=True;break
  if re.fullmatch(r'(?:table of )?contents?(?: continued)?',n):titled=True;break
 if not titled:
  # A contents page whose title is garbled but whose lines are "47 Statement of ...".
  lines=[v.strip() for v in text.splitlines() if v.strip()]
  titled=sum(bool(NUMBER_FIRST.match(v)) and bool(re.match(r'\S+\s+(?:statements? of|balance sheets?|notes to)',v,re.I)) for v in lines)>=4
 if not titled:
  head=' '.join(text.splitlines()[:12])
  titled=bool(re.search(r'\btable\b',head,re.I) and re.search(r'\bcontents?\b',head,re.I) and len(re.findall(r'\d+\s*$',text,re.M))>=5)
 return titled and toc_structure(text)

def native_text(page,rows):
 text='\n'.join(r['text'] for r in rows)
 # A legitimate TOC title can itself be vertical. Preserve that document-level
 # signal from logical text without admitting vertical sidebars as captions.
 if not is_toc(text) and is_toc(page.get_text()):text='TABLE OF CONTENTS\n'+text
 return text

# Navigation tab bars such as "INTRODUCTORY SECTION FINANCIAL SECTION STATISTICAL
# SECTION" repeat on every page and must not reject a statement as statistical.
NAV_TABS=re.compile(r'(?:\b(?:introductory|financial|statistical|supplementary|other supplementary information|compliance|single audit)\b\s*(?:section\b\s*)?){2,}',re.I)
TITLE_START=re.compile(r'\bstatements? of\b|\bbalance sheets?\b',re.I)
DATE_CUT=re.compile(r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}\b|\bfor (?:the )?(?:fiscal )?(?:years?|period)\b|\bas of\b|\b(?:fiscal )?years? ended\b|\(?\b(?:amounts )?(?:expressed )?in thousands\b|\(?\bin millions\b',re.I)
TYPOS=[(re.compile(r'\bpos(?:iton|tion|itoin|ision|iiton)\b',re.I),'Position'),(re.compile(r'\bactivit(?:es|ties|iess)\b',re.I),'Activities'),(re.compile(r'\bfiduciay\b',re.I),'Fiduciary'),(re.compile(r'\bstatment\b',re.I),'Statement')]

def clean_header(header):
 header=NAV_TABS.sub(' ',header)
 for pattern,word in TYPOS:header=pattern.sub(word,header)
 return header

def title_scope(header):
 """The statement title and a short preceding qualifier, without dates/body.

 Running headers ("Annual Comprehensive Financial Report for the Year Ended")
 often precede the real title, so cutting at the first date would lose it.
 Stop before dates/body; rejecting a reconciliation inside a cash-flow body
 would otherwise discard a legitimate cash-flow continuation.
 """
 header=clean_header(header)
 lines=[v.strip() for v in header.split('\n') if v.strip()]
 def prose(line):
  return len(line)>100 and len(re.findall(r'(?:^|\s)[a-z][a-z]+',line))>=8
 for k,line in enumerate(lines[:8]):
  if prose(line):break
  m=TITLE_START.search(line)
  if not m:continue
  before=line[:m.start()]
  # A title begins a short line; "The statement of net position provides..."
  # and note/MD&A prose mentioning a statement are not titles.
  joiner=r'\b(?:the|a|an|in|on|of|to|and|our|its|this|see|for|from|with|by)\s*$'
  # "The Statement of Fund Net Position" is a title when the rest of the line is
  # Title Case; "The Statement of Net Position provides ..." is prose.
  titled_the=before.strip()=='The' and not re.search(r'\b(?!(?:of|and|in|the|for|to|on|by|net)\b)[a-z][a-z]+',line[m.start():])
  if len(before)>60 or (re.search(joiner,before,re.I) and not titled_the) or not m.group()[0].isupper():continue
  if not before and k and re.search(joiner,lines[k-1],re.I):continue
  # Keep preceding non-prose header lines after the last date: they carry
  # qualifiers such as "Component Unit", "Combining" or a foundation's name.
  # Dates are removed rather than used as a cut, so an MD&A or notes heading
  # printed above a date line still rejects the page.
  prev=re.sub(r'\s+',' ',DATE_CUT.sub(' ',' '.join(lines[:k]))).strip()[-200:]
  scope=line
  for nxt in lines[k+1:k+3]:
   if DATE_CUT.search(scope) or prose(nxt):break
   scope+=' '+nxt
  title=DATE_CUT.split(scope[len(before):])[0]
  return ' '.join(v for v in [prev,DATE_CUT.split(before)[-1].strip(),title.strip()] if v)[:260]
 # No qualifying title line. Keep the top non-prose lines (they still carry
 # reconciliation/budget wording used to reject pages) but drop statement names
 # that failed the title tests, so prose mentions cannot identify a page.
 top=[]
 for line in lines[:8]:
  if prose(line):break
  top.append(line)
 return TITLE_START.sub(' ',DATE_CUT.split(' '.join(top))[0])

ZERO_DASHES={'-','–','—','‒','−'}

def amount_panel_rows(rows,height):
 """Rows that begin with an amount: the right-hand half of a facing-page spread
 has no label column, so its amounts start at the left margin."""
 return sum(bool(r['words']) and amount(r['words'][0][4]) and any(re.search(r'\d',w[4]) for w in r['words']) for r in rows if height*.1<r['y0']<height*.94)

def numeric_rows(rows,width,height,dashes=False):
 """Rows with an amount right of the label column.

 dashes=True also counts nil amounts printed as a dash. It is used only for
 pages that already carry a recognized statement title: small custodial or
 pension statements can have only one or two non-zero lines.
 """
 return sum(any((amount(w[4]) and re.search(r'\d',w[4]) or (dashes and w[4] in ZERO_DASHES)) and w[0]>width*.30 for w in r['words']) for r in rows if height*.1<r['y0']<height*.94)


def bad_text(text):
 if len(text.strip())<60:return True
 words=re.findall(r'[A-Za-z]{2,}',text.lower())
 common={'the','of','and','for','in','assets','liabilities','net','total','cash','fund','funds','government','statement','revenues','expenses','year','ended','position','june','september','securities','intentionally','blank'}
 if text.count('\ufffd')>max(3,len(text)*.02) or (len(words)>25 and sum(w in common for w in words)/len(words)<.035):return True
 # Badly encoded fonts can yield symbol soup with almost no real words
 # ("K D`D[ O U 12 - GE . 4 4 !#$ [D"), which the ratio above does not catch.
 tokens=[t for t in text.split() if not amount(t)]
 real=sum(bool(re.fullmatch(r'[(\[]?(?:[A-Z][a-z]{2,}|[a-z]{3,}|[A-Z]{3,})[),.:;]*',t)) for t in tokens)
 return len(tokens)>=40 and real<len(tokens)*.15 and sum(w in common for w in words)<3

COMBINED=[('GW_NET_POSITION','GF_BALANCE_SHEET',re.compile(r'statements? of net position.*balance sheets?|balance sheets?.*statements? of net position',re.I)),
 ('GW_ACTIVITIES','GF_OPERATING',re.compile(r'statements? of activities.*expenditures|expenditures.*statements? of activities',re.I))]

def combined_pair(scope,typ):
 """Single-program governments may combine the government-wide and governmental
 fund statements ("Statement of Net Position and Governmental Funds Balance
 Sheet"); return the other statement type such a page also serves."""
 if REJECT.search(scope):return None
 for a,b,pattern in COMBINED:
  if typ in (a,b) and pattern.search(scope):return b if typ==a else a
 return None

COMPONENT_TITLE=re.compile(r'discretely presented|\bcomponent units?\b|\bfoundations?\b|affiliated organization|statements? of financial position',re.I)

def identify(header, context='', enterprise=False, allow_basic_combining=False):
 header=clean_header(header);n=normalized(header);scope=title_scope(header);sn=normalized(scope);c=normalized(context)
 if allow_basic_combining:scope=re.sub(r'\bcombining\b','',scope,flags=re.I)
 # A statement title must appear as a title line, not only inside prose.
 if not TITLE_START.search(scope):return None
 # Prior-year statements reprinted "for comparative information purposes".
 if re.search(r'for comparative (?:information )?purposes|comparative information only',n):return None
 if REJECT.search(scope) and not ('cash flows' in sn and scope.lower().find('reconciliation')>scope.lower().find('cash flows')):return None
 if re.search(r'discretely presented|nongovernmental component|affiliated organization|component unit.*(?:foundation|educational)',sn) and 'primary government' not in n:return None
 # "Statement of Net Position - Component Units" / "Component Units Statement of
 # Activities" are separate presentations, not the primary government's statements.
 # Column headings such as "Component Units" fall outside the title scope.
 # Fiduciary component units (pension trusts) are reported as the primary
 # government's fiduciary funds.
 if re.search(r'\bcomponent units?\b|\bfoundations?\b|\bstatements? of financial position\b',sn) and 'primary government' not in sn and 'fiduciary' not in sn:return None
 if re.search(r'statements? of (?:changes? in fiduciary|(?:additions|revenues).{0,60}changes? in fiduciary) net position|statements? of changes? in (?:plan |fiduciary )?net position (?:held in trust|restricted for|available for)',n):return 'FF_CHANGES'
 # "Statement of Changes in Net Position - Fiduciary Funds" names the fund type
 # only in its qualifier.
 if re.search(r'statements? of changes? in (?:fund |plan )?net position',sn) and re.search(r'fiduciary|pension|trust|custodial',sn+' '+c):return 'FF_CHANGES'
 if re.search(r'statements? of fiduciary net position',n):return 'FF_NET_POSITION'
 if re.search(r'statements? of cash flows?',n):return 'PF_CASH_FLOWS'
 if re.search(r'statements? of (?:revenues?|income).*expenses?.*changes? in (?:fund )?net position',n):return 'PF_OPERATING'
 if re.search(r'statements? of revenues?.*expenditures?.*changes? in fund balances?',n):return 'GF_OPERATING'
 if re.search(r'\bbalance sheets?\b',n):
  return 'GF_BALANCE_SHEET' if 'governmental' in n or 'governmental' in c else None
 if re.search(r'statements? of activities',n):return 'GW_ACTIVITIES'
 if re.search(r'statements? of (?:fund )?net position',n):
  # The fund type must come from the title, not body text in the header area
  # (Cincinnati's government-wide page mentions fiduciary activity).
  if 'fiduciary' in sn or 'fiduciary' in c:return 'FF_NET_POSITION'
  if any(v in sn for v in ['proprietary','enterprise funds','enterprise fund']) or 'proprietary' in c:return 'PF_NET_POSITION'
  if 'government wide' in sn or 'governmental activities' in n or 'government wide' in c:return 'GW_NET_POSITION'
  if enterprise:return 'PF_NET_POSITION'
  if 'primary government' in n:return 'GW_NET_POSITION'
 return None

def toc_entries(summaries):
 entries=[];context='';closed=False;fasb_next=False
 for summary in summaries:
  if not is_toc(summary['text']):continue
  lines=number_first([re.sub(r'(?:[.·…]\s*){3,}',' ',v).strip() for v in summary['text'].splitlines() if v.strip()])
  consumed=set()
  for i,line in enumerate(lines):
   if i in consumed:continue
   n=normalized(line)
   if re.search(r'notes to (?:the )?(?:basic )?financial statements',n):
    # Notes are a range barrier, not a statement. No subsequent supplementary
    # statement can replace a basic statement in the inventory.
    m=re.search(rf'(?P<start>\d{{1,4}})(?:\s*{DASH}\s*\d{{1,4}})?\s*$',line)
    if m:entries.append({'type':'EXCLUDED','label':m['start'],'end_label':'','title':line,'basic':False})
    closed=True;continue
   if closed:continue
   if 'government wide' in n or 'district wide' in n:context='government wide'
   if re.fullmatch(r'(?:major )?governmental funds?(?: financial statements)?',n):context='governmental funds'
   if re.fullmatch(r'(?:major )?(?:proprietary|propriety|enterprise) funds?(?: financial statements)?',n):context='proprietary funds'
   if re.fullmatch(r'fiduciary funds?(?: financial statements)?',n):context='fiduciary funds'
   if (re.match(r'^(?:discretely presented |nongovernmental )?component units?\b',n) or re.fullmatch(r'affiliated organization',n)) and not re.search(r'statements? of',n):context='excluded'
   # Exhibit markers: "A-1", "Exhibit 3", a bare letter ("C Balance Sheet") or roman numeral.
   stripped=re.sub(r'^(?:(?:exhibit|statement|schedule)\s+)?(?:[A-Z]-?\d+[A-Za-z]?|[A-Z]{1,2}|[IVX]{1,4}|\d{1,2})[.):]?\s+(?=statements?\b|balance\b|reconciliation\b|comparative\b)', '',line,flags=re.I)
   stripped=re.sub(r'^(?:(?:exhibit )?[A-Z]-?\d+[A-Za-z]?\s+)', '',stripped,flags=re.I)
   stripped=re.sub(r'^comparative\s+','',stripped,flags=re.I)
   if not re.match(r'(?:statements? of|balance sheets?|reconciliation)',stripped,re.I):continue
   combined=stripped
   # Page ranges in a TOC denote the START and END, not only the last number.
   ref=rf'(?:(?P<prefix>[IVXLC]+)\s*{DASH}\s*)?(?P<start>\d{{1,4}})(?:\s*(?:{DASH}|\bto\b|\bthrough\b|\band\b|&)\s*(?P<end>\d{{1,4}}))?\s*$'
   for j,nxt in enumerate(lines[i+1:i+4],i+1):
    if re.search(ref,combined):break
    combined+=' '+nxt;consumed.add(j)
   m=re.search(ref,combined)
   if not m:continue
   # A FASB foundation's Statement of Activities follows its Statement of
   # Financial Position; neither belongs to the primary government.
   fasb_pair=fasb_next and re.search(r'statements? of activities',combined,re.I) and not re.search(r'primary government',combined,re.I)
   fasb_next=bool(re.search(r'statements? of financial position',combined,re.I))
   if fasb_pair or REJECT.search(combined) or context=='excluded' or re.search(r'affiliated organization|nongovernmental component|\bcomponent units?\b|\bfoundations?\b|statements? of financial position',combined,re.I):typ='EXCLUDED'
   else:
    typ=identify(combined,context)
    if not typ and re.search(r'statements? of (?:fund )?net position',normalized(combined)):typ='NET_POSITION'
   if not typ:continue
   prefix=(m['prefix']+'-') if m['prefix'] else ''
   entries.append({'type':typ,'label':prefix+m['start'],'end_label':prefix+m['end'] if m['end'] else '', 'title':combined,'basic':typ!='EXCLUDED'})
 known={e['type'] for e in entries}
 model='GW_NET_POSITION' if known & {'GF_BALANCE_SHEET','GW_ACTIVITIES'} else 'PF_NET_POSITION' if known & {'PF_CASH_FLOWS','PF_OPERATING'} else None
 for e in entries:
  if e['type']=='NET_POSITION' and model:e['type']=model
 return list({(e['type'],e['label']):e for e in entries if e['type']!='NET_POSITION'}.values())


# Parallelism comes from worker processes; Tesseract's own OpenMP threads would
# oversubscribe the CPU and cause timeouts on busy machines.
OCR_ENV={**os.environ,'OMP_THREAD_LIMIT':'1'}

def tesseract(args,timeouts=(120,360),check=True):
 """Run Tesseract, retrying once with a longer timeout on a slow page."""
 for n,limit in enumerate(timeouts):
  try:return subprocess.run(['tesseract',*args],capture_output=True,text=True,timeout=limit,check=check,env=OCR_ENV)
  except subprocess.TimeoutExpired:
   if n==len(timeouts)-1:raise

def ocr_rows(page,cache,force=False):
 """Tesseract TSV with a bounded local orientation retry for unreadable OCR."""
 if cache.exists() and not force:
  cached=json.loads(cache.read_text())
  return cached
 dpi=220
 def quality(rows):
  text=' '.join(r['text'] for r in rows).lower();words=re.findall(r'[a-z]{2,}',text)
  vocab={'the','of','and','for','assets','liabilities','net','total','cash','fund','funds','statement','revenues','expenses','position','activities','expenditures','year','ended','governmental','program','services','additions','deductions'}
  return sum(w in vocab for w in words)/max(1,len(words)) + (.3 if re.search(r'statements? of|balance sheet',text) else 0)
 with tempfile.TemporaryDirectory(prefix='acfr-ocr-') as tmp:
  image=Path(tmp)/'page.png'
  def recognize(angle):
   pix=page.get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72).prerotate(angle));pix.save(image)
   result=tesseract([str(image),'stdout','-l','eng','--psm','3','tsv'])
   words=[]
   for r in csv.DictReader(io.StringIO(result.stdout),delimiter='\t',quoting=csv.QUOTE_NONE):
    text=r.get('text','') or ''
    if not text.strip():continue
    x,y,w,h=(float(r[k])*72/dpi for k in ['left','top','width','height']);words.append((x,y,x+w,y+h,text))
   rows=group_words(words)
   for row in rows:row.update(ocr_rotation=angle,ocr_width=pix.width*72/dpi,ocr_height=pix.height*72/dpi,ocr_version=2)
   return rows
  rows=recognize(0);text='\n'.join(r['text'] for r in rows)
  # Rotated scans come back as long unreadable text; retry orientation for them
  # even without a TOC link (Carmel's landscape statements).
  if ((force and len(text.strip())>20) or len(text.strip())>200) and bad_text(text):
   try:osd=tesseract([str(image),'stdout','--psm','0'],timeouts=(60,),check=False)
   except subprocess.TimeoutExpired:osd=subprocess.CompletedProcess([],1,'','')
   m=re.search(r'Rotate:\s*(90|180|270)',osd.stdout);preferred=int(m[1]) if m else 90
   best_score=quality(rows)
   for angle in dict.fromkeys([preferred,90,180,270]):
    candidate=recognize(angle);score=quality(candidate)
    if score>best_score:rows=candidate;best_score=score
    if score>.35:break
 cache.parent.mkdir(parents=True,exist_ok=True)
 tmp=cache.with_suffix('.tmp');tmp.write_text(json.dumps(rows));os.replace(tmp,cache)
 return rows

def page_header(rows,height):
 # Rows are kept on separate lines so a title can be told apart from prose.
 return '\n'.join(r['text'] for r in rows if r['y0']<min(220,height*.29))

def extract_rows(rows,width,height,dashes=False):
 """Use left-of-number text; preserve headings, indentation and joined wraps."""
 numeric=[]
 for r in rows:
  ws=r['words']
  # Ignore years and note numbers in label column when estimating amount columns.
  ns=[w for w in ws if amount(w[4]) and (re.search(r'\d',w[4]) or (dashes and w[4] in ZERO_DASHES)) and w[0]>width*.32 and r['y0']>height*.12 and r['y0']<height*.94]
  if ns:numeric.append((r,ns))
 if len(numeric)<3 or not any(re.search(r'\d',w[4]) for r,ns in numeric for w in ns):return []
 # The typical first value-column left edge, rather than the leftmost stray note.
 lefts=sorted(min(w[0] for w in ns) for r,ns in numeric)
 column=lefts[len(lefts)//5]
 candidates=[]
 for r in rows:
  if r['y0']<height*.10 or r['y0']>height*.94:continue
  ws=r['words']
  # Numbers inside a label ("Transfers—Note 5 ....", "June 30, 2024, as
  # previously reported") sit left of the label's last word or dot leader;
  # only numbers after that point and before the first real amount are amounts.
  big=[w[0] for w in ws if re.search(r'\d,\d{3}|\(\d|\$|\d{5}',w[4])]
  first_big=min(big,default=float('inf'))
  # Without a real amount on the row, words right of the amount column are
  # column headings, not label text.
  limit=first_big if first_big<float('inf') else column-18
  # Dot leaders run from a label toward its amounts; underline rules belong to
  # amount columns and do not extend a label.
  label_end=max((w[0] for w in ws if w[0]<limit and (re.search('[A-Za-z]',w[4]) or re.fullmatch(r'[.·…]{3,}',w[4]))),default=-1)
  nums=[w for w in ws if amount(w[4]) and w[0]>=column-18 and w[0]>label_end]
  end=min((w[0] for w in nums),default=max(column-4,label_end+1))
  left=[w for w in ws if w[0]<end-2 and (w[0]<=label_end or not (amount(w[4]) and w[0]>column-30))]
  # Dotted leaders and underline rules are layout furniture, not caption text.
  text=re.sub(r'\s+',' ',re.sub(r'(?:[.·…]\s*){3,}|_{3,}',' ',' '.join(w[4] for w in left))).strip().strip('$ ')
  # Leftover leader dots (". .") and a nil-amount em dash left of the column.
  text=re.sub(r'(?:\s*[.·]){2,}$|(?:\s+—)+$','',text).strip()
  if not re.search('[A-Za-z]',text) or not left:continue
  if len(text)>210:continue
  if re.search(r'see accompanying|notes (?:are|to)|this statement|continued|statement of|balance sheet|in thousands|stated in|exhibit |statement \d',text,re.I):continue
  # Date header lines ("June 30, 2025", "For the year ended ...") are not captions,
  # but closing-balance captions such as "Fund balances - June 30, 2025" are.
  if re.match(r'(?:for the (?:year|fiscal|period)|(?:fiscal )?years? ended|as of\b|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d)',text,re.I):continue
  if len(text.split())>26:continue
  candidates.append({'text':text,'x0':min(w[0] for w in left),'x1':max(w[2] for w in left),'y0':r['y0'],'y1':r['y1'],'numeric':bool(nums),'all':r['text']})
 if not candidates:return []
 first=next((i for i,c in enumerate(candidates) if c['numeric']),len(candidates))
 # Start at an accounting section heading before the first numeric row.
 starts=[i for i,c in enumerate(candidates[:first+1]) if SECTION.match(c['text']) or SUBHEADING.match(c['text'])]
 start=starts[0] if starts else first
 candidates=candidates[start:]
 # Header-only labels between column headings and first data often have no numbers.
 items=[];section='';parents=[];pending=[]
 for i,c in enumerate(candidates):
  text=c['text'].strip().rstrip(':');heading=bool(SECTION.match(text) or SUBHEADING.match(text))
  nxt=candidates[i+1] if i+1<len(candidates) else None
  if not c['numeric'] and not heading:
   # Wrapped caption: close vertical adjacency and matching/continuation indentation.
   # A hanging-indent continuation starts in lowercase or ")" ("as previously" /
   # "reported"), or the first line ends mid-phrase ("Revenues Over (Under)").
   unfinished=bool(re.search(r'(?:\b(?:of|and|to|for|in|from|over|under|on|by|the|as|or|with|less|before|after|between|previously|adjusted)|\((?:under|over)\)|[,(&]|(?<=\w)[-–])$',c['text'].strip(),re.I))
   hanging=nxt is not None and bool(re.match(r'[a-z(\)]',nxt['text'])) and nxt['x0']>=c['x0']-4
   if nxt and nxt['numeric'] and nxt['y0']-c['y1']<6 and (abs(nxt['x0']-c['x0'])<=4 or hanging or (unfinished and nxt['x0']>=c['x0']-4)) and not c['text'].endswith(':'):
    pending.append(c);continue
   if pending:
    # An unmatched fragment is retained as a heading instead of silently lost.
    for p in pending:items.append({**p,'section':section,'parent_heading':parents[-1][1] if parents else '', 'row_kind':'heading','warning':'unresolved_wrap'})
    pending=[]
  if pending:
   c={**c,'text':' '.join([p['text'] for p in pending]+[text]),'y0':pending[0]['y0'],'x0':min(p['x0'] for p in pending+[c]),'x1':max(p['x1'] for p in pending+[c])};text=c['text'];pending=[]
  if SECTION.match(text):
   section=text;parents=[]
  else:
   while parents and c['x0']<=parents[-1][0]+2:parents.pop()
  if text.lower().startswith('total '):parents=[]
  parent=parents[-1][1] if parents else section
  items.append({**c,'section':section,'parent_heading':parent,'row_kind':'caption' if c['numeric'] else 'heading','warning':''})
  if not c['numeric'] and not SECTION.match(text):parents.append((c['x0'],text))
 return items

def infer_labels(summaries,gap=3):
 """Printed labels by PDF page, filling short unlabeled gaps.

 Many reports print a page number only on odd pages, or omit it on landscape
 statement pages. A gap is filled only when the labeled pages on both sides
 agree on the same printed-minus-PDF offset, so a TOC entry pointing at an
 unlabeled page can still be located. Inferred labels are used for mapping
 only; printed_page output keeps the observed label.
 """
 labels={s['page']:s['label'] for s in summaries if s['label'] and not is_toc(s['text'])}
 numeric=sorted((p,int(v)) for p,v in labels.items() if v.isdigit())
 for (p0,v0),(p1,v1) in zip(numeric,numeric[1:]):
  if 1<p1-p0<=gap+1 and v1-p1==v0-p0:
   for p in range(p0+1,p1):labels.setdefault(p,str(v0+p-p0))
 return labels

def sha256_file(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

FILENAME_PATTERNS=[
 # Production naming: "CA Alameda County 2025.pdf" (state, entity, fiscal year).
 re.compile(r'^([A-Z]{2})\s+(.+?)\s+((?:19|20)\d\d)$'),
 # Sample naming: "ACFR001__AK_City_and_Borough_of_Juneau_2025.pdf".
 re.compile(r'^ACFR\d+__([A-Z]{2})_(.+)_((?:19|20)\d\d)$'),
]

def document_identity(path,meta):
 """Government name ("Entity, ST") and fiscal year from --metadata, else from
 the file name. The state is kept in the name so same-named governments in
 different states are counted separately."""
 name=re.sub(r'\s+',' ',path.stem.strip())
 m=next((m for m in (p.match(name) for p in FILENAME_PATTERNS) if m),None)
 parsed=f"{m[2].replace('_',' ').strip()}, {m[1]}" if m else re.sub(r'[_-]',' ',name)
 return {'government_name':meta.get('government_name') or parsed,'fiscal_year':meta.get('fiscal_year') or (m[3] if m else ''),'drive_file_id':meta.get('drive_file_id','')}

def process_pdf(task):
 path,root,out,options,metadata=task;path=Path(path);root=Path(root);out=Path(out)
 started=time.monotonic();file_id=sha256_file(path);relative=path.relative_to(root).as_posix()
 identity=document_identity(path,metadata.get(relative,metadata.get(path.name,{})))
 base={'document_id':file_id,'source_path':relative,'pdf_filename':path.name,**identity}
 logs=[];inventory=[];occ=[];errors=[];ocr_pages=[]
 try:
  doc=pymupdf.open(path)
  if doc.needs_pass:raise ValueError('password_required: encrypted PDF cannot be opened without a password')
  permission_warning=not bool(doc.permissions & pymupdf.PDF_PERM_COPY)
  summaries=[]
  for i,page in enumerate(doc):
   try:
    rows,fw,fh,extra=native_frame(page);text=native_text(page,rows)
    numeric_panel=numeric_rows(rows,fw,fh)>=3 and not re.search(r'[A-Za-z]{2,}',text)
    blank=not text.strip() and not page.get_images() and not page.get_drawings()
    # A statement drawn as vector paths or an image, with only a footer as
    # text (Miami), needs OCR even though its little text is readable.
    graphic=len(text.strip())<250 and not blank and (bool(page.get_images()) or len(page.get_drawings())>50)
    summaries.append({'page':i,'text':text,'label':printed_label(rows,fh),'bad':(bad_text(text) and not numeric_panel) or graphic,'blank':blank,'header':page_header(rows,fh),'method':'native','width':fw,'height':fh,'ocr_rotation':extra})
   except Exception as e:
    summaries.append({'page':i,'text':'','label':'','bad':True,'blank':False,'header':'','method':'native','width':page.rect.width,'height':page.rect.height,'ocr_rotation':0});errors.append(f'page {i+1}: {type(e).__name__}: {e}')

  def map_contents(entries):
   # Recomputed on each call because OCR can supply labels for scanned pages.
   labels=defaultdict(list)
   for page,label in sorted(infer_labels(summaries).items()):labels[label].append(page)
   # A printed number can recur (a Single Audit section or statistical tables
   # numbered from 1 again). Prefer the occurrence whose page carries a
   # statement title; place other entries at the dominant printed-to-PDF offset.
   def titled(page):
    scope=title_scope(summaries[page]['header'])
    return bool(TITLE_START.search(scope)) and not re.search(r'notes? to|schedule of expenditures of federal',scope,re.I)
   chosen={}
   for k,entry in enumerate(entries):
    candidates=labels[entry['label']]
    if len(candidates)>1 and entry['type'] in TYPES:
     good=[c for c in candidates if titled(c)]
     if good:chosen[k]=min(good)
   offsets=Counter(chosen[k]-int(entries[k]['label']) for k in chosen if entries[k]['label'].isdigit())
   offset=offsets.most_common(1)[0][0] if offsets else None
   mapped=[]
   for k,entry in enumerate(entries):
    candidates=labels[entry['label']]
    if not candidates:continue
    if k in chosen:start=chosen[k]
    elif len(candidates)>1 and offset is not None and entry['label'].isdigit() and int(entry['label'])+offset in candidates:start=int(entry['label'])+offset
    else:start=min(candidates)
    end_candidates=[i for i in labels[entry.get('end_label','')] if i>=start]
    mapped.append({**entry,'start':start,'end':min(end_candidates) if end_candidates else None})
   return mapped

  entries=toc_entries(summaries);mapped=map_contents(entries)
  ocr_targets=set()
  starts=sorted(set(e['start'] for e in mapped))
  for j,i in enumerate(starts):
   if not any(e['start']==i and e['type'] in TYPES for e in mapped):continue
   stop=starts[j+1] if j+1<len(starts) else min(len(doc),i+4)
   ocr_targets.update(range(i,min(stop,i+12)))
  if options['ocr']=='all' or (options['ocr']=='auto' and not any(e['type'] in TYPES for e in mapped)):
   ocr_targets={s['page'] for s in summaries if s['bad'] and not s['blank']}
  if options['ocr']!='off':
   for s in summaries:
    i=s['page']
    if not s['bad'] or s['blank'] or i not in ocr_targets:continue
    if is_toc(s['text']) and len(toc_entries([s]))>=2:continue
    try:
     page=doc[i];rows=ocr_rows(page,out/'ocr_cache'/file_id/f'{i+1}.json');ocr_pages.append(i+1)
     width=rows[0].get('ocr_width',page.rect.width) if rows else page.rect.width; height=rows[0].get('ocr_height',page.rect.height) if rows else page.rect.height
     s.update(text='\n'.join(r['text'] for r in rows),header=page_header(rows,height),label=printed_label(rows,height) or s['label'],method='ocr',width=width,height=height,ocr_rotation=rows[0].get('ocr_rotation',0) if rows else 0)
     s['bad']=bad_text(s['text'])
    except Exception as e:errors.append(f'OCR page {i+1}: {type(e).__name__}: {e}')

  # Scanned TOCs must be interpreted AFTER OCR, not only during native scanning.
  entries=toc_entries(summaries);mapped=map_contents(entries)
  if options['ocr']!='off':
   # A TOC recovered by OCR can point at statement pages that were not in the
   # first OCR target set; OCR those unreadable pages too.
   later=set()
   starts=sorted(set(e['start'] for e in mapped))
   for j,i in enumerate(starts):
    if not any(e['start']==i and e['type'] in TYPES for e in mapped):continue
    stop=starts[j+1] if j+1<len(starts) else min(len(doc),i+4)
    later.update(range(i,min(stop,i+12)))
   for i in sorted(later-set(p-1 for p in ocr_pages)):
    s=summaries[i]
    if not s['bad'] or s['blank']:continue
    try:
     page=doc[i];rows=ocr_rows(page,out/'ocr_cache'/file_id/f'{i+1}.json');ocr_pages.append(i+1)
     width=rows[0].get('ocr_width',page.rect.width) if rows else page.rect.width; height=rows[0].get('ocr_height',page.rect.height) if rows else page.rect.height
     s.update(text='\n'.join(r['text'] for r in rows),header=page_header(rows,height),label=printed_label(rows,height) or s['label'],method='ocr',width=width,height=height,ocr_rotation=rows[0].get('ocr_rotation',0) if rows else 0)
     s['bad']=bad_text(s['text'])
    except Exception as e:errors.append(f'OCR page {i+1}: {type(e).__name__}: {e}')
   entries=toc_entries(summaries);mapped=map_contents(entries)
  # Retry orientation only on unreadable, contents-linked statement starts. A
  # 200-page scan's statistical tables must not trigger four OCR passes apiece.
  for e in mapped:
   if e['type'] not in TYPES:continue
   summary=summaries[e['start']]
   if summary['method']!='ocr' or not summary['bad']:continue
   try:
    page=doc[e['start']];rows=ocr_rows(page,out/'ocr_cache'/file_id/f"{e['start']+1}.json",force=True)
    width=rows[0].get('ocr_width',page.rect.width) if rows else page.rect.width;height=rows[0].get('ocr_height',page.rect.height) if rows else page.rect.height
    summary.update(text='\n'.join(r['text'] for r in rows),header=page_header(rows,height),label=printed_label(rows,height) or summary['label'],width=width,height=height,ocr_rotation=rows[0].get('ocr_rotation',0) if rows else 0)
    summary['bad']=bad_text(summary['text'])
   except Exception as error:errors.append(f"OCR orientation page {e['start']+1}: {error}")
  entries=toc_entries(summaries);mapped=map_contents(entries)
  toc_types={e['type'] for e in entries if e['type'] in TYPES}
  hints={e['start']:e['type'] for e in mapped if e['type'] in TYPES}
  boundary_starts=sorted(set(e['start'] for e in mapped))
  windows=defaultdict(list)
  for e in mapped:
   if e['type'] not in TYPES:continue
   following=[i for i in boundary_starts if i>e['start']]
   end=min(following)-1 if following else min(len(doc)-1,e['start']+11)
   if e['end'] is not None:end=min(end,e['end'])
   windows[e['type']].append((e['start'],end))
  # Bookmarks can locate statements even when footer labels are not usable.
  for _,title,pageno in doc.get_toc():
   typ=identify(title)
   if typ and 1<=pageno<=len(doc) and pageno-1 not in hints and typ not in windows:
    hints[pageno-1]=typ
  notes_candidates=[e['start'] for e in mapped if e['type']=='EXCLUDED' and re.search(r'notes to',e['title'],re.I)]
  for _,title,pageno in doc.get_toc():
   if 1<=pageno<=len(doc) and re.search(r'notes to (?:the )?(?:basic )?financial statements',title,re.I):notes_candidates.append(pageno-1)
  for summary in summaries:
   if not is_toc(summary['text']) and not re.search(r'discussion|analysis',summary['header'][:250],re.I) and any(re.match(r'^notes to (?:the )?(?:basic )?financial statements',r.strip(),re.I) for r in summary['text'].splitlines()[:7]):notes_candidates.append(summary['page'])
  first_hint=min(hints) if hints else 0
  notes_candidates=[v for v in notes_candidates if v>first_hint]
  notes_start=min(notes_candidates) if notes_candidates else len(doc)
  all_boundaries=sorted(set(boundary_starts+list(hints)+[notes_start]))
  for start,typ in hints.items():
   if any(lo==start for lo,hi in windows[typ]):continue
   following=[v for v in all_boundaries if v>start]
   end=min(following)-1 if following else min(len(doc)-1,start+11)
   windows[typ].append((start,min(end,start+11)))
  model_types=toc_types | {identify(s['header']) for s in summaries if not s['bad'] and s['page']<notes_start and not is_toc(s['text'])}
  government_model=bool({'GF_BALANCE_SHEET','GW_ACTIVITIES'} & model_types)
  enterprise=bool({'PF_CASH_FLOWS','PF_OPERATING'} & model_types) and not government_model
  # Enterprise primary-government columns do not turn a housing/airport authority
  # into a government-wide reporting model.
  detected=[]
  def get_rows(s):
   return ocr_rows(doc[s['page']],out/'ocr_cache'/file_id/f"{s['page']+1}.json") if s['method']=='ocr' else native_rows(doc[s['page']])
  for s in summaries:
   i=s['page'];page=doc[i]
   if s['bad'] or s['blank'] or i>=notes_start or is_toc(s['text']):continue
   context=TYPES[hints[i]] if i in hints else ('government wide' if government_model else '')
   authoritative=any(lo<=i<=hi for lo,hi in windows.get(hints.get(i,''),[])) or any(lo<=i<=hi for ranges in windows.values() for lo,hi in ranges)
   typ=identify(s['header'],context,enterprise,allow_basic_combining=authoritative)
   # A reconciliation sometimes repeats the preceding GF statement title.
   if typ not in (None,'PF_CASH_FLOWS') and re.search(r'reconciliation of',s['header'],re.I):typ=None
   rows=get_rows(s);width=s.get('width',page.rect.width);height=s.get('height',page.rect.height);n_numeric=numeric_rows(rows,width,height)
   sparse=bool(typ) and n_numeric<3
   if sparse:n_numeric=numeric_rows(rows,width,height,dashes=True)
   items=extract_rows(rows,width,height,dashes=sparse) if n_numeric>=3 else []
   if typ and not items and not sparse and n_numeric>=3:items=extract_rows(rows,width,height,dashes=True)
   recovered=False
   # Facing-page spreads sometimes print the title only on the right-hand page.
   # A TOC-linked, untitled numeric start page joins the statement titled on the
   # next page.
   if typ is None and i in hints and i+1<len(summaries) and n_numeric>=3 and items and not TITLE_START.search(title_scope(s['header'])):
    nxt=summaries[i+1]
    if not nxt['bad'] and identify(nxt['header'],TYPES[hints[i]],enterprise)==hints[i]:typ=hints[i];recovered='untitled_spread_first_page'
   # A TOC-linked page whose own title is irregular ("Schedule of Revenues,
   # Expenditures, and Changes in Fund Balances - Proprietary Funds") takes the
   # TOC type when its accounting structure matches; flagged for review.
   if typ is None and i in hints and s['method']!='ocr' and n_numeric>=3 and items:
    scope=title_scope(s['header'])
    if re.search(r'\b(?:statements?|schedules?) of\b|balance sheet',scope,re.I) and not REJECT.search(scope) and not COMPONENT_TITLE.search(scope):
     t=normalized(s['text']);expected=hints[i]
     markers={'GW_NET_POSITION':['assets','liabilities','net position'],'GW_ACTIVITIES':['expenses','program revenues','net position'],'GF_BALANCE_SHEET':['assets','liabilities','fund balance'],'GF_OPERATING':['revenues','expenditures','fund balance'],'PF_NET_POSITION':['assets','liabilities','net position'],'PF_OPERATING':['operating revenues','operating expenses','net position'],'PF_CASH_FLOWS':['cash flows','operating activities','cash equivalents'],'FF_NET_POSITION':['assets','liabilities','net position'],'FF_CHANGES':['additions','deductions','net position']}
     if all(v in t for v in markers[expected]):typ=expected;recovered='title_from_toc'
   if typ is None and i in hints and s['method']=='ocr' and n_numeric>=3 and items:
    t=normalized(s['text']);expected=hints[i]
    markers={'GW_NET_POSITION':['assets','liabilities','net position'],'GW_ACTIVITIES':['expenses','activities','program revenues'],'GF_BALANCE_SHEET':['assets','liabilities','fund balances'],'GF_OPERATING':['revenues','expenditures','fund balances'],'PF_NET_POSITION':['assets','liabilities','net position'],'PF_OPERATING':['operating revenues','operating expenses','net position'],'PF_CASH_FLOWS':['cash flows','operating activities','cash'],'FF_NET_POSITION':['assets','net position'],'FF_CHANGES':['additions','deductions','net position']}
    scope=title_scope(s['header'])
    if sum(v in t for v in markers[expected])>=2 and not REJECT.search(scope) and not COMPONENT_TITLE.search(scope):
     typ=expected;recovered=True
   if typ and n_numeric>=3 and items:
    # Two short statements can share a page (UNC prints fiduciary net position
    # and changes in fiduciary net position together). A second title lower on
    # the page starts the other statement; captions below it move there.
    second=None
    for row in rows:
     if row['y0']<height*.3 or row['y0']>height*.85 or len(row['text'])>120:continue
     if not TITLE_START.match(row['text'].strip()):continue
     other=identify(row['text'],TYPES.get(typ,''),enterprise)
     if other and other!=typ and not REJECT.search(row['text']):second=(row['y0'],other);break
    if second:
     upper=[x for x in items if x['y0']<second[0]];lower=[x for x in items if x['y0']>second[0]]
     detected.append({'type':typ,'page':i,'items':upper,'method':s['method'],'label':s['label'],'warning':'shared_page'})
     detected.append({'type':second[1],'page':i,'items':lower,'method':s['method'],'label':s['label'],'warning':'shared_page'})
     continue
    entry={'type':typ,'page':i,'items':items,'method':s['method'],'label':s['label'],'warning':recovered if isinstance(recovered,str) else 'ocr_title_from_toc' if recovered else ''}
    pair=combined_pair(title_scope(s['header']),typ)
    if pair:entry.update(pair=pair,warning='combined_statement')
    detected.append(entry)
    if pair:detected.append({**entry,'type':pair,'pair':typ})
    continue
   if not detected or detected[-1]['page']!=i-1:continue
   previous=detected[-1];previous_type=previous['type']
   in_range=any(lo<=i<=hi for t in (previous_type,previous.get('pair')) if t for lo,hi in windows[t])
   # Reject an explicit different title, notes, budgets or reconciliations before
   # allowing a title-less numeric panel to extend a statement.
   title_text=title_scope(s['header'])
   blocked=bool(REJECT.search(title_text) or re.search(r'reconciliation of',s['header'],re.I)) and previous_type!='PF_CASH_FLOWS'
   # Only an actual title line counts; "statement of" in header-area text does not.
   different_title=bool(TITLE_START.search(title_scope(s['header']))) and typ!=previous_type
   continuation='continued' in s['header'].lower() or 'continues on the next page' in summaries[i-1]['text'].lower()
   # Explicit accounting-section evidence permits a title-less second page when
   # a TOC lists only the start and the next statement provides the boundary.
   accounting=any(SECTION.match(r['text'].strip().rstrip(':')) or SUBHEADING.match(r['text'].strip().rstrip(':')) for r in rows[:18])
   # An untitled numeric page directly after a statement page (the second half
   # of a spread, or a page whose title is printed only on the first page) is a
   # continuation when it shows accounting structure, even without a TOC range.
   untitled=not re.search(r'statements? of|balance sheets?|schedule of|notes? to|discussion',s['header'],re.I)
   if untitled and n_numeric<3 and amount_panel_rows(rows,height)>=5:n_numeric=amount_panel_rows(rows,height)
   # The amounts-only right half of a spread has neither captions nor section
   # headings; directly after a statement page it continues that statement.
   amounts_only=untitled and not items and n_numeric>=5
   if n_numeric>=3 and not blocked and not different_title and (in_range or continuation or (untitled and (items or accounting)) or amounts_only) and (items or in_range or accounting or amounts_only):
    cont={'type':previous_type,'page':i,'items':items,'method':s['method'],'label':s['label'],'warning':'amount_only_continuation' if not items else 'titleless_continuation'}
    if previous.get('pair'):
     # A combined statement continues under both of its statement types.
     detected.append({**cont,'type':previous['pair'],'pair':previous_type})
    detected.append({**cont,'pair':previous.get('pair')} if previous.get('pair') else cont)

  if os.environ.get('ACFR_DEBUG'):print('DEBUG',path.name,[(d['type'],d['page']+1,d['warning']) for d in detected],dict(windows),flush=True)
  bytype=defaultdict(list)
  for d in detected:bytype[d['type']].append(d)
  # A complete readable basic TOC ending at Notes supplies absence evidence even
  # for three-statement enterprise or two-statement pension reporting models.
  toc_complete=any(is_toc(s['text']) and re.search(r'notes to (?:the )?(?:basic )?financial statements',normalized(s['text'])) for s in summaries) and len(toc_types)>=2
  first_statement=min((d['page'] for d in detected),default=None)
  present_types={d['type'] for d in detected}
  section_readable=(first_statement is not None and notes_start<len(doc) and len(present_types)>=3
   and all((not summaries[i]['bad'] or summaries[i]['blank']) and summaries[i]['method']=='native' for i in range(first_statement,notes_start)))
  for typ in TYPES:
   pages=bytype[typ]
   toc_mismatch=False
   if windows[typ]:
    inside=[p for p in pages if any(lo<=p['page']<=hi for lo,hi in windows[typ])]
    # A TOC range holding none of the titled statement pages points at a
    # different numbering sequence; trust contiguous titled pages instead.
    if inside or not pages or len({d['page'] for d in pages})!=pages[-1]['page']-pages[0]['page']+1:pages=inside
    else:toc_mismatch=True
   typed_hints=[i for i,t in hints.items() if t==typ]
   groups=[]
   for d in pages:
    if not groups or d['page']>groups[-1][-1]['page']+1:groups.append([d])
    else:groups[-1].append(d)
   chosen=groups[0] if len(groups)==1 else [];warnings=['toc_page_mapping_ignored'] if toc_mismatch and chosen else []
   if len(groups)>1:warnings.append('multiple_candidate_statement_ranges')
   if chosen:
    status='present';extraction_status='extracted';sid=f'{file_id}:{typ}';section='';parent=''
    for p in chosen:
     if p['warning']:warnings.append(p['warning'])
     for item in p['items']:
      if item['section']:section=item['section']
      if item['parent_heading']:parent=item['parent_heading']
      occ.append({**base,'statement_id':sid,'statement_type':typ,'original_caption':item['text'],'section':section,'parent_heading':parent,'pdf_page':p['page']+1,'printed_page':p['label'],'page_rotation':doc[p['page']].rotation,'ocr_rotation':summaries[p['page']].get('ocr_rotation',0),'x0':round(item['x0'],2),'y0':round(item['y0'],2),'x1':round(item['x1'],2),'y1':round(item['y1'],2),'row_kind':item['row_kind'],'method':p['method'],'confidence':'review' if p['method']=='ocr' or item['warning'] else 'heuristic','warning':item['warning'] or ('ocr_requires_review' if p['method']=='ocr' else '')})
    if any(p['method']=='ocr' for p in chosen):warnings.append('ocr_requires_review')
   else:
    absence_supported=toc_complete and typ not in toc_types and not groups and not errors
    # Without a usable TOC, a fully readable basic-statement section that runs up
    # to the notes and holds no page titled as this statement is weaker absence
    # evidence; it is flagged for review.
    inferred=not absence_supported and section_readable and typ not in toc_types and not groups and not typed_hints and not errors
    if inferred:absence_supported=True;warnings.append('absence_inferred_from_statement_section')
    status='absent' if absence_supported else 'unknown';extraction_status='not_applicable' if status=='absent' else 'unresolved'
    if typ in toc_types:warnings.append('toc_statement_not_extracted')
   if permission_warning:warnings.append('pdf_copy_permission_restricted')
   inventory.append({**base,'statement_id':f'{file_id}:{typ}','statement_type':typ,'statement_name':TYPES[typ],'status':status,'extraction_status':extraction_status,'pdf_start_page':chosen[0]['page']+1 if chosen else '', 'pdf_end_page':chosen[-1]['page']+1 if chosen else '', 'pdf_pages':';'.join(str(p['page']+1) for p in chosen),'toc_start_pages':';'.join(str(i+1) for i in typed_hints),'warning':';'.join(dict.fromkeys(warnings))})
  logs.append({**base,'status':'warning' if errors or any(v['status']=='unknown' for v in inventory) else 'processed','page_count':len(doc),'captions':len(occ),'statements_extracted':sum(v['status']=='present' for v in inventory),'ocr_pages':';'.join(map(str,ocr_pages)),'seconds':round(time.monotonic()-started,3),'message':'; '.join(errors) or ('Drive ID not supplied; government/year from metadata or filename, verify identity' if not identity['drive_file_id'] else '')})
 except Exception as e:
  logs.append({**base,'status':'failed','page_count':'','captions':0,'statements_extracted':0,'ocr_pages':'','seconds':round(time.monotonic()-started,3),'message':f'{type(e).__name__}: {e}'})
  inventory=[{**base,'statement_id':f'{file_id}:{typ}','statement_type':typ,'statement_name':name,'status':'unknown','extraction_status':'failed','pdf_start_page':'','pdf_end_page':'','pdf_pages':'','toc_start_pages':'','warning':'document_processing_failed'} for typ,name in TYPES.items()]
 return {'base':base,'occurrences':occ,'inventory':inventory,'logs':logs}

OCC_FIELDS=['document_id','government_name','fiscal_year','pdf_filename','source_path','drive_file_id','statement_id','statement_type','original_caption','standardized_caption','frequency_key','section','parent_heading','pdf_page','printed_page','page_rotation','ocr_rotation','x0','y0','x1','y1','row_kind','method','confidence','warning']
INV_FIELDS=['document_id','government_name','fiscal_year','pdf_filename','source_path','drive_file_id','statement_id','statement_type','statement_name','status','extraction_status','pdf_start_page','pdf_end_page','pdf_pages','toc_start_pages','warning']
LOG_FIELDS=['document_id','government_name','fiscal_year','pdf_filename','source_path','drive_file_id','status','page_count','captions','statements_extracted','ocr_pages','seconds','message']

def write_csv(path,fields,rows):
 path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
 with tmp.open('w',newline='',encoding='utf-8-sig') as f:
  writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
 os.replace(tmp,path)

def export_results(db,out,rules):
 """Streaming occurrence exports and SQLite distinct aggregates; bounded by one report."""
 def records(kind):
  for payload, in db.execute('SELECT payload FROM results ORDER BY source_path'):
   for row in json.loads(payload)[kind]:
    if kind=='occurrences':
     row['standardized_caption']=standardize(row['original_caption'],rules)
     row['frequency_key']=caption_key(row['original_caption'],row['section'],row['parent_heading'],rules)
    yield row
 db.executescript('DROP TABLE IF EXISTS captions; DROP TABLE IF EXISTS statements; CREATE TABLE captions (statement_type, frequency_key, standardized_caption, statement_id, document_id, government_name, original_caption, section, parent_heading, row_kind); CREATE TABLE statements (statement_type,statement_id,status);')
 def occurrences():
  for row in records('occurrences'):
   db.execute('INSERT INTO captions VALUES (?,?,?,?,?,?,?,?,?,?)',tuple(row[k] for k in ['statement_type','frequency_key','standardized_caption','statement_id','document_id','government_name','original_caption','section','parent_heading','row_kind']))
   yield row
 fmt=getattr(export_results,'occurrences_format','csv')
 if fmt in ('csv','both'):write_csv(out/'caption_occurrences.csv',OCC_FIELDS,occurrences())
 if fmt in ('sqlite','both'):write_occurrence_db(out/'caption_occurrences.sqlite',occurrences() if fmt=='sqlite' else records('occurrences'))
 def inventory():
  for r in records('inventory'):
   db.execute('INSERT INTO statements VALUES (?,?,?)',(r['statement_type'],r['statement_id'],r['status']));yield r
 write_csv(out/'statement_inventory.csv',INV_FIELDS,inventory())
 write_csv(out/'processing_log.csv',LOG_FIELDS,records('logs'))
 denom=dict(db.execute("SELECT statement_type,count(DISTINCT statement_id) FROM statements WHERE status='present' GROUP BY statement_type"))
 freq=[]
 for typ,key,caption,kind,ns,nd,ng in db.execute('SELECT statement_type,frequency_key,min(standardized_caption),row_kind,count(DISTINCT statement_id),count(DISTINCT document_id),count(DISTINCT lower(government_name)) FROM captions GROUP BY statement_type,frequency_key,row_kind ORDER BY statement_type,count(DISTINCT statement_id) DESC,frequency_key'):
  freq.append({'statement_type':typ,'frequency_key':key,'standardized_caption':caption,'row_kind':kind,'statement_count':ns,'acfr_count':nd,'government_count':ng,'successful_statement_denominator':denom[typ],'frequency_percent':round(100*ns/denom[typ],4)})
 write_csv(out/'caption_frequencies.csv',['statement_type','frequency_key','standardized_caption','row_kind','statement_count','acfr_count','government_count','successful_statement_denominator','frequency_percent'],freq)
 fields=['original_caption','standardized_caption','frequency_key','section','parent_heading','row_kind']
 mapping=(dict(zip(fields,r)) for r in db.execute('SELECT DISTINCT original_caption,standardized_caption,frequency_key,section,parent_heading,row_kind FROM captions ORDER BY standardized_caption,original_caption'))
 write_csv(out/'caption_mapping.csv',fields,mapping)
 summary=db.execute("SELECT statement_type,sum(status='present'),sum(status='absent'),sum(status='unknown') FROM statements GROUP BY statement_type").fetchall()
 write_workbook(out/'caption_frequencies.xlsx',freq,summary)
 db.commit()

def write_occurrence_db(path,rows):
 """All caption occurrences in one SQLite table, for queries at a scale where
 a CSV is unwieldy (about 8 million rows for 25,000 reports)."""
 path=Path(path);tmp=path.with_suffix('.sqlite.tmp')
 if tmp.exists():tmp.unlink()
 con=sqlite3.connect(tmp);cols=', '.join(OCC_FIELDS)
 con.execute(f'CREATE TABLE occurrences ({cols})')
 con.executemany(f"INSERT INTO occurrences VALUES ({','.join('?'*len(OCC_FIELDS))})",(tuple(r.get(k,'') for k in OCC_FIELDS) for r in rows))
 con.execute('CREATE INDEX occurrences_caption ON occurrences(statement_type, frequency_key)')
 con.commit();con.close();os.replace(tmp,path)

XLSX_MAX_ROWS=1_048_575

def write_workbook(path,freq,summary):
 """Excel summary: unique captions, statement names and counts only. Caption
 occurrence detail stays in caption_occurrences.csv / .sqlite."""
 from openpyxl import Workbook
 from openpyxl.styles import Font
 wb=Workbook(write_only=True)
 headers=['Statement type','Financial statement','Standardized caption','Context key','Row kind','Statements containing caption','ACFRs containing caption','Governments containing caption','Statements extracted (denominator)','Percent of statements']
 def sheet(title,head,widths):
  ws=wb.create_sheet(title);ws.freeze_panes='A2'
  for i,w in enumerate(widths):ws.column_dimensions[chr(65+i)].width=w
  bold=[];
  from openpyxl.cell import WriteOnlyCell
  for h in head:c=WriteOnlyCell(ws,value=h);c.font=Font(bold=True);bold.append(c)
  ws.append(bold);return ws
 widths=[18,48,48,48,10,14,14,14,16,12]
 part=1;ws=sheet('Caption frequencies',headers,widths);n=0
 for r in freq:
  if n==XLSX_MAX_ROWS:
   part+=1;ws=sheet(f'Caption frequencies ({part})',headers,widths);n=0
  ws.append([r['statement_type'],TYPES[r['statement_type']],r['standardized_caption'],r['frequency_key'],r['row_kind'],r['statement_count'],r['acfr_count'],r['government_count'],r['successful_statement_denominator'],r['frequency_percent']])
  n+=1
 ws=sheet('Statements',['Statement type','Financial statement','Present','Absent','Unresolved'],[18,60,10,10,12])
 by={t:(p,a,u) for t,p,a,u in summary}
 for t,name in TYPES.items():
  p,a,u=by.get(t,(0,0,0));ws.append([t,name,p or 0,a or 0,u or 0])
 ws=wb.create_sheet('About')
 for line in [f'ACFR caption extractor {VERSION}',
  'Caption frequencies: one row per standardized caption (and context key for ambiguous captions) per statement type.',
  'Statements containing caption counts each statement once even if the caption repeats in it.',
  'Percent of statements = statements containing caption / statements of that type extracted (present). Absent and unresolved statements are excluded from the denominator.',
  'Row kind "heading" rows are section headings without amounts; "caption" rows carry amounts.',
  'Caption occurrence detail (page, location, original wording) is in caption_occurrences.csv or caption_occurrences.sqlite, not in this workbook.',
  'Edit normalization.json to approve additional equivalences, then rerun with --resume to re-export without reprocessing PDFs.']:ws.append([line])
 tmp=Path(str(path)+'.tmp');wb.save(tmp);os.replace(tmp,path)


def validate(out,gold,rules):
 metrics=[]
 if not gold:
  metrics=[{'scope':'all','metric':'validation','numerator':'','denominator':'','value':'','status':'not_measured','details':'No verified reference supplied. Heuristic confidence is not measured accuracy.'}]
 else:
  with (out/'statement_inventory.csv').open(encoding='utf-8-sig') as f:inv=list(csv.DictReader(f))
  with (out/'caption_occurrences.csv').open(encoding='utf-8-sig') as f:occ=list(csv.DictReader(f))
  ref=json.loads(Path(gold).read_text());true=0;total=0
  for name,statements in ref.get('statements',{}).items():
   for typ,expected in statements.items():
    found=next((r for r in inv if r['pdf_filename']==name and r['statement_type']==typ),None)
    actual=[int(x) for x in found['pdf_pages'].split(';') if x] if found else []
    ok=actual==expected and (found['status']=='present' if expected else found['status']=='absent')
    true+=ok;total+=1
    metrics.append({'scope':f'{name}:{typ}','metric':'statement_exact_pages','numerator':int(ok),'denominator':1,'value':int(ok),'status':'measured','details':f'expected={expected}; actual={actual}; status={found["status"] if found else "missing"}'})
  if total:metrics.append({'scope':'reference_statements','metric':'statement_identification_accuracy','numerator':true,'denominator':total,'value':true/total,'status':'measured','details':'Exact PDF page membership and absent/present status'})
  for sample in ref.get('caption_pages',[]):
   name,typ,page=sample['pdf_filename'],sample['statement_type'],sample['pdf_page']
   expected=Counter(standardize(x,rules) for x in sample['captions'])
   actual=Counter(standardize(r['original_caption'],rules) for r in occ if r['pdf_filename']==name and r['statement_type']==typ and int(r['pdf_page'])==page)
   tp=sum((expected & actual).values());fp=sum((actual-expected).values());fn=sum((expected-actual).values())
   for metric,num,den in [('caption_precision',tp,tp+fp),('caption_recall',tp,tp+fn)]:
    metrics.append({'scope':f'{name}:{typ}:page{page}','metric':metric,'numerator':num,'denominator':den,'value':num/den if den else '', 'status':'measured' if den else 'undefined','details':json.dumps({'missing':list((expected-actual).elements()),'extra':list((actual-expected).elements())})})
 write_csv(out/'validation_report.csv',['scope','metric','numerator','denominator','value','status','details'],metrics)
 return metrics


def failed_result(task,message):
 """A processing-log/inventory record for a report that timed out or crashed."""
 path,root,out,options,metadata=task;path=Path(path)
 relative=path.relative_to(Path(root)).as_posix()
 identity=document_identity(path,metadata.get(relative,metadata.get(path.name,{})))
 base={'document_id':sha256_file(path),'source_path':relative,'pdf_filename':path.name,**identity}
 log={**base,'status':'failed','page_count':'','captions':0,'statements_extracted':0,'ocr_pages':'','seconds':'','message':message}
 inventory=[{**base,'statement_id':f"{base['document_id']}:{typ}",'statement_type':typ,'statement_name':name,'status':'unknown','extraction_status':'failed','pdf_start_page':'','pdf_end_page':'','pdf_pages':'','toc_start_pages':'','warning':'document_processing_failed'} for typ,name in TYPES.items()]
 return {'base':base,'occurrences':[],'inventory':inventory,'logs':[log]}

def _isolated_worker(task,conn):
 # Test hook: ACFR_TEST_HANG=<filename> makes that PDF hang (time limit test).
 if os.environ.get('ACFR_TEST_HANG') and Path(task[0]).name==os.environ['ACFR_TEST_HANG']:time.sleep(3600)
 try:conn.send(process_pdf(task))
 except BaseException as e:conn.send({'error':f'{type(e).__name__}: {e}'})
 finally:conn.close()

def run_isolated(tasks,workers,timeout,save):
 """Run each report in its own process so a hung or crashing PDF can be
 stopped without losing the run. A report exceeding `timeout` seconds is
 killed and logged as failed; --resume retries failed reports."""
 queue=iter(tasks);running={}
 def launch():
  task=next(queue,None)
  if task is None:return False
  recv,send=multiprocessing.Pipe(duplex=False)
  proc=multiprocessing.Process(target=_isolated_worker,args=(task,send),daemon=True);proc.start();send.close()
  running[recv]=(proc,task,time.monotonic());return True
 try:
  while len(running)<workers and launch():pass
  while running:
   ready=multiprocessing.connection.wait(list(running),timeout=1.0)
   now=time.monotonic()
   for conn in list(running):
    proc,task,started=running[conn];result=None
    if conn in ready:
     try:result=conn.recv()
     except EOFError:result={'error':f'worker exited with code {proc.exitcode} (crash or out of memory)'}
    elif timeout>0 and now-started>timeout:
     proc.kill();result={'error':f'timed out after {timeout} seconds; worker stopped'}
    elif not proc.is_alive() and not conn.poll():
     result={'error':f'worker exited with code {proc.exitcode} (crash or out of memory)'}
    if result is None:continue
    del running[conn];conn.close();proc.join(5)
    if 'error' in result:result=failed_result(task,result['error'])
    save(result)
    launch()
 finally:
  for conn,(proc,_,_) in running.items():proc.kill()

def run(args):
 root=Path(args.input).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
 if not root.is_dir():raise ValueError('Input must be a directory containing PDFs')
 rules=json.loads(Path(args.rules).read_text());metadata=json.loads(Path(args.metadata).read_text()) if args.metadata else {}
 options={'ocr':args.ocr}
 config_id=hashlib.sha256((Path(__file__).read_text()+Path(__file__).with_name('legacy_clean_amount.py').read_text()+json.dumps(options,sort_keys=True)+json.dumps(metadata,sort_keys=True)).encode()).hexdigest()
 db=sqlite3.connect(out/'progress.sqlite');db.execute('CREATE TABLE IF NOT EXISTS results(source_path TEXT PRIMARY KEY,fingerprint TEXT,config_id TEXT,payload TEXT)')
 files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower()=='.pdf' and not p.is_relative_to(out))
 if not files:raise ValueError('No PDF inputs found')
 seen=[];tasks=[]
 for p in files:
  rel=p.relative_to(root).as_posix();seen.append(rel);fingerprint=sha256_file(p)
  old=db.execute('SELECT fingerprint,config_id,payload FROM results WHERE source_path=?',(rel,)).fetchone()
  if args.resume and old and old[:2]==(fingerprint,config_id) and json.loads(old[2])['logs'][0]['status']!='failed':
   print(f'RESUME {rel}',flush=True);continue
  # Send each worker only its own metadata entry, not the whole mapping.
  entry={k:metadata[k] for k in (rel,p.name) if k in metadata}
  tasks.append((str(p),str(root),str(out),options,entry))
 # Scope checkpoint to this input tree and current file membership.
 for rel, in db.execute('SELECT source_path FROM results').fetchall():
  if rel not in seen:db.execute('DELETE FROM results WHERE source_path=?',(rel,))
 db.commit()
 def save(result):
  rel=result['base']['source_path']
  db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',(rel,result['base']['document_id'],config_id,json.dumps(result)));db.commit()
  print(f"{result['logs'][0]['status'].upper()} {rel}: {len(result['occurrences'])} rows",flush=True)
 try:
  if args.timeout<=0 and args.workers==1:
   for task in tasks:save(process_pdf(task))
  else:
   run_isolated(tasks,args.workers,args.timeout,save)
 finally:
  export_results(db,out,rules);validate(out,args.gold,rules)
 failures=sum(json.loads(p[0])['logs'][0]['status']=='failed' for p in db.execute('SELECT payload FROM results'))
 db.close();return 1 if failures else 0


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--input',required=True,help='Recursive PDF directory')
 parser.add_argument('--output',required=True,help='Results and resumable checkpoint directory')
 parser.add_argument('--workers',type=int,default=1)
 parser.add_argument('--ocr',choices=['off','auto','all'],default='off',help='auto OCRs suspect TOC-linked statement pages; all OCRs suspect pages throughout')
 parser.add_argument('--resume',action='store_true')
 parser.add_argument('--metadata',help='JSON keyed by relative PDF path: government_name, fiscal_year, drive_file_id')
 parser.add_argument('--rules',default=str(CONFIG))
 parser.add_argument('--gold',help='Verified reference JSON for accuracy measurement')
 parser.add_argument('--occurrences',choices=['csv','sqlite','both'],default='csv',help='Format for per-caption detail: csv (caption_occurrences.csv), sqlite (caption_occurrences.sqlite, recommended for large runs) or both')
 parser.add_argument('--timeout',type=int,default=1800,help='Seconds allowed per PDF before its worker is stopped and the PDF is logged as failed (0 = no limit)')
 args=parser.parse_args()
 if args.workers<1:parser.error('--workers must be positive')
 export_results.occurrences_format=args.occurrences
 try:return run(args)
 except (ValueError,OSError,sqlite3.Error) as e:parser.exit(2,f'{type(e).__name__}: {e}\n')

if __name__=='__main__':raise SystemExit(main())
