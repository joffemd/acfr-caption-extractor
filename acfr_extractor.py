"""Offline ACFR caption extraction. Python 3.12; no remote document APIs.

Coordinates are PDF points from top-left; PDF page numbers are one based.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
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

VERSION = '0.3.0'
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

def label_number(s):
 s=s.strip().strip(' ()-–—')
 s=re.sub(r'\s*[-–—]\s*','-',s)
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
  # Some reports print the page label on the same baseline as a notes footer.
  if r['y0']>height*.70 and re.search(r'notes.*(?:financial statements|integral part)',r['text'],re.I):
   m=re.search(r'((?:[IVX]+\s*[-–—]\s*)?\d{1,4})\s*$',r['text'])
   if m:return label_number(m[1])
 for r in rows:
  if r['y0']>height*.10:continue
  m=re.search(r'(?:financial\s*(?:section)?\s*[|:]?\s*)(\d{1,4})\s*$',r['text'],re.I)
  if m:return m[1]
  m=re.match(r'^(\d{1,4})\s+(?:financial(?: section)?|annual comprehensive)',r['text'],re.I)
  if m:return m[1]
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

def native_rows(page):
 # PDF words use unrotated coordinates, while page.rect and rendering reflect /Rotate.
 # Normalize to the displayed page and omit vertical decorative sidebars.
 matrix=page.rotation_matrix
 directions={}
 textpage=page.get_textpage(flags=pymupdf.TEXTFLAGS_WORDS)
 for block in page.get_text('dict',textpage=textpage)['blocks']:
  for j,line in enumerate(block.get('lines',[])):
   dx,dy=line['dir'];a=pymupdf.Point(0,0)*matrix;b=pymupdf.Point(dx,dy)*matrix
   directions[(block['number'],j)]=(b.x-a.x,b.y-a.y)
 words=[]
 for word in page.get_text('words',textpage=textpage):
  dx,dy=directions.get((word[5],word[6]),(1,0))
  if abs(dy)>.3:continue
  box=pymupdf.Rect(word[:4])*matrix
  words.append((*box,word[4]))
 return group_words(words)

def is_toc(text):
 for line in text.splitlines()[:12]:
  n=normalized(line)
  if len(line)<160 and re.sub(r'[^a-z]','',n).startswith('tableofcontent'):return True
  if re.fullmatch(r'(?:table of )?contents?(?: continued)?',n):return True
 head=' '.join(text.splitlines()[:12])
 return bool(re.search(r'\btable\b',head,re.I) and re.search(r'\bcontents?\b',head,re.I) and len(re.findall(r'\d+\s*$',text,re.M))>=5)

def native_text(page,rows):
 text='\n'.join(r['text'] for r in rows)
 # A legitimate TOC title can itself be vertical. Preserve that document-level
 # signal from logical text without admitting vertical sidebars as captions.
 if not is_toc(text) and is_toc(page.get_text()):text='TABLE OF CONTENTS\n'+text
 return text

def title_scope(header):
 # Stop before dates/body; rejecting a reconciliation inside a cash-flow body
 # would otherwise discard a legitimate cash-flow continuation.
 return re.split(r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b|\bfor (?:the )?(?:fiscal )?years?\b',header,flags=re.I)[0]

def numeric_rows(rows,width,height):
 return sum(any(amount(w[4]) and re.search(r'\d',w[4]) and w[0]>width*.30 for w in r['words']) for r in rows if height*.1<r['y0']<height*.94)


def bad_text(text):
 if len(text.strip())<60:return True
 words=re.findall(r'[A-Za-z]{2,}',text.lower())
 common={'the','of','and','for','in','assets','liabilities','net','total','cash','fund','funds','government','statement','revenues','expenses','year','ended','position','june','september','securities','intentionally','blank'}
 return text.count('\ufffd')>max(3,len(text)*.02) or (len(words)>25 and sum(w in common for w in words)/len(words)<.035)

def identify(header, context='', enterprise=False, allow_basic_combining=False):
 n=normalized(header);scope=title_scope(header);sn=normalized(scope);c=normalized(context)
 if allow_basic_combining:scope=re.sub(r'\bcombining\b','',scope,flags=re.I)
 if REJECT.search(scope) and not ('cash flows' in sn and scope.lower().find('reconciliation')>scope.lower().find('cash flows')):return None
 if re.search(r'discretely presented|nongovernmental component|affiliated organization|component unit.*(?:foundation|educational)',sn) and 'primary government' not in n:return None
 if re.search(r'statements? of changes? in fiduciary net position',n):return 'FF_CHANGES'
 if re.search(r'statements? of fiduciary net position',n):return 'FF_NET_POSITION'
 if re.search(r'statements? of cash flows?',n):return 'PF_CASH_FLOWS'
 if re.search(r'statements? of (?:revenues?|income).*expenses?.*changes? in (?:fund )?net position',n):return 'PF_OPERATING'
 if re.search(r'statements? of revenues?.*expenditures?.*changes? in fund balances?',n):return 'GF_OPERATING'
 if re.search(r'\bbalance sheets?\b',n):
  return 'GF_BALANCE_SHEET' if 'governmental' in n or 'governmental' in c else None
 if re.search(r'statements? of activities',n):return 'GW_ACTIVITIES'
 if re.search(r'statements? of (?:fund )?net position',n):
  if 'fiduciary' in n or 'fiduciary' in c:return 'FF_NET_POSITION'
  if any(v in sn for v in ['proprietary','enterprise funds','enterprise fund']) or 'proprietary' in c:return 'PF_NET_POSITION'
  if 'government wide' in sn or 'governmental activities' in n or 'government wide' in c:return 'GW_NET_POSITION'
  if enterprise:return 'PF_NET_POSITION'
  if 'primary government' in n:return 'GW_NET_POSITION'
 return None

def toc_entries(summaries):
 entries=[];context='';closed=False
 for summary in summaries:
  if not is_toc(summary['text']):continue
  lines=[re.sub(r'(?:[.·…]\s*){3,}',' ',v).strip() for v in summary['text'].splitlines() if v.strip()]
  consumed=set()
  for i,line in enumerate(lines):
   if i in consumed:continue
   n=normalized(line)
   if re.search(r'notes to (?:the )?(?:basic )?financial statements',n):
    # Notes are a range barrier, not a statement. No subsequent supplementary
    # statement can replace a basic statement in the inventory.
    m=re.search(r'(?P<start>\d{1,4})(?:\s*[-–—]\s*\d{1,4})?\s*$',line)
    if m:entries.append({'type':'EXCLUDED','label':m['start'],'end_label':'','title':line,'basic':False})
    closed=True;continue
   if closed:continue
   if 'government wide' in n or 'district wide' in n:context='government wide'
   if re.fullmatch(r'(?:major )?governmental funds?',n):context='governmental funds'
   if re.fullmatch(r'(?:major )?(?:proprietary|propriety|enterprise) funds?',n):context='proprietary funds'
   if re.fullmatch(r'fiduciary funds?',n):context='fiduciary funds'
   if (re.match(r'^(?:discretely presented |nongovernmental )?component units?\b',n) or re.fullmatch(r'affiliated organization',n)) and not re.search(r'statements? of',n):context='excluded'
   stripped=re.sub(r'^(?:(?:exhibit )?[A-Z]-?\d+[A-Za-z]?\s+)', '',line,flags=re.I)
   stripped=re.sub(r'^comparative\s+','',stripped,flags=re.I)
   if not re.match(r'(?:statements? of|balance sheets?|reconciliation)',stripped,re.I):continue
   combined=stripped
   # Page ranges in a TOC denote the START and END, not only the last number.
   ref=r'(?:(?P<prefix>[IVXLC]+)\s*[-–—]\s*)?(?P<start>\d{1,4})(?:\s*[-–—]\s*(?P<end>\d{1,4}))?\s*$'
   for j,nxt in enumerate(lines[i+1:i+4],i+1):
    if re.search(ref,combined):break
    combined+=' '+nxt;consumed.add(j)
   m=re.search(ref,combined)
   if not m:continue
   if REJECT.search(combined) or context=='excluded' or re.search(r'affiliated organization|nongovernmental component',combined,re.I):typ='EXCLUDED'
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
   result=subprocess.run(['tesseract',str(image),'stdout','-l','eng','--psm','3','tsv'],capture_output=True,text=True,timeout=120,check=True)
   words=[]
   for r in csv.DictReader(io.StringIO(result.stdout),delimiter='\t',quoting=csv.QUOTE_NONE):
    text=r.get('text','') or ''
    if not text.strip():continue
    x,y,w,h=(float(r[k])*72/dpi for k in ['left','top','width','height']);words.append((x,y,x+w,y+h,text))
   rows=group_words(words)
   for row in rows:row.update(ocr_rotation=angle,ocr_width=pix.width*72/dpi,ocr_height=pix.height*72/dpi,ocr_version=2)
   return rows
  rows=recognize(0);text='\n'.join(r['text'] for r in rows)
  if force and len(text.strip())>20 and bad_text(text):
   osd=subprocess.run(['tesseract',str(image),'stdout','--psm','0'],capture_output=True,text=True,timeout=60)
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
 return ' '.join(r['text'] for r in rows if r['y0']<min(220,height*.29))

def extract_rows(rows,width,height):
 """Use left-of-number text; preserve headings, indentation and joined wraps."""
 numeric=[]
 for r in rows:
  ws=r['words']
  # Ignore years and note numbers in label column when estimating amount columns.
  ns=[w for w in ws if amount(w[4]) and re.search(r'\d',w[4]) and w[0]>width*.32 and r['y0']>height*.12 and r['y0']<height*.94]
  if ns:numeric.append((r,ns))
 if len(numeric)<3:return []
 # The typical first value-column left edge, rather than the leftmost stray note.
 lefts=sorted(min(w[0] for w in ns) for r,ns in numeric)
 column=lefts[len(lefts)//5]
 candidates=[]
 for r in rows:
  if r['y0']<height*.10 or r['y0']>height*.94:continue
  ws=r['words'];nums=[w for w in ws if amount(w[4]) and w[0]>=column-18]
  end=min((w[0] for w in nums),default=column-4)
  left=[w for w in ws if w[0]<end-2 and not (amount(w[4]) and w[0]>column-30)]
  text=re.sub(r'(?:[.·…]\s*){3,}',' ',' '.join(w[4] for w in left)).strip().strip('$ ')
  if not re.search('[A-Za-z]',text) or not left:continue
  if len(text)>210:continue
  if re.search(r'see accompanying|notes (?:are|to)|this statement|continued|statement of|balance sheet|for the (?:year|fiscal)|year ended|june \d|september \d|december \d|in thousands|stated in|exhibit |statement \d',text,re.I):continue
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
   if nxt and nxt['numeric'] and nxt['y0']-c['y1']<6 and abs(nxt['x0']-c['x0'])<=4 and not c['text'].endswith(':'):
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

def sha256_file(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def document_identity(path,meta):
 name=path.stem
 m=re.match(r'ACFR\d+__([A-Z]{2})_(.+)_(20\d\d)$',name)
 return {'government_name':meta.get('government_name') or (m[2].replace('_',' ') if m else re.sub(r'[_-]',' ',name)), 'fiscal_year':meta.get('fiscal_year') or (m[3] if m else ''),'drive_file_id':meta.get('drive_file_id','')}

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
    rows=native_rows(page);text=native_text(page,rows)
    numeric_panel=numeric_rows(rows,page.rect.width,page.rect.height)>=3 and not re.search(r'[A-Za-z]{2,}',text)
    blank=not text.strip() and not page.get_images() and not page.get_drawings()
    summaries.append({'page':i,'text':text,'label':printed_label(rows,page.rect.height),'bad':bad_text(text) and not numeric_panel,'blank':blank,'header':page_header(rows,page.rect.height),'method':'native','width':page.rect.width,'height':page.rect.height,'ocr_rotation':0})
   except Exception as e:
    summaries.append({'page':i,'text':'','label':'','bad':True,'blank':False,'header':'','method':'native','width':page.rect.width,'height':page.rect.height,'ocr_rotation':0});errors.append(f'page {i+1}: {type(e).__name__}: {e}')

  def map_contents(entries):
   labels=defaultdict(list)
   for summary in summaries:
    if summary['label'] and not is_toc(summary['text']):labels[summary['label']].append(summary['page'])
   mapped=[]
   for entry in entries:
    candidates=labels[entry['label']]
    if not candidates:continue
    start=min(candidates);end_candidates=[i for i in labels[entry.get('end_label','')] if i>=start]
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
   items=extract_rows(rows,width,height) if n_numeric>=3 else []
   recovered=False
   if typ is None and i in hints and s['method']=='ocr' and n_numeric>=3 and items:
    t=normalized(s['text']);expected=hints[i]
    markers={'GW_NET_POSITION':['assets','liabilities','net position'],'GW_ACTIVITIES':['expenses','activities','program revenues'],'GF_BALANCE_SHEET':['assets','liabilities','fund balances'],'GF_OPERATING':['revenues','expenditures','fund balances'],'PF_NET_POSITION':['assets','liabilities','net position'],'PF_OPERATING':['operating revenues','operating expenses','net position'],'PF_CASH_FLOWS':['cash flows','operating activities','cash'],'FF_NET_POSITION':['assets','net position'],'FF_CHANGES':['additions','deductions','net position']}
    if sum(v in t for v in markers[expected])>=2 and not REJECT.search(title_scope(s['header'])):
     typ=expected;recovered=True
   if typ and n_numeric>=3 and items:
    detected.append({'type':typ,'page':i,'items':items,'method':s['method'],'label':s['label'],'warning':'ocr_title_from_toc' if recovered else ''});continue
   if not detected or detected[-1]['page']!=i-1:continue
   previous=detected[-1];previous_type=previous['type']
   in_range=any(lo<=i<=hi for lo,hi in windows[previous_type])
   # Reject an explicit different title, notes, budgets or reconciliations before
   # allowing a title-less numeric panel to extend a statement.
   title_text=title_scope(s['header'])
   blocked=bool(REJECT.search(title_text) or re.search(r'reconciliation of',s['header'],re.I)) and previous_type!='PF_CASH_FLOWS'
   different_title=bool(re.search(r'statements? of|balance sheets?',s['header'],re.I)) and typ!=previous_type
   continuation='continued' in s['header'].lower() or 'continues on the next page' in summaries[i-1]['text'].lower()
   # Explicit accounting-section evidence permits a title-less second page when
   # a TOC lists only the start and the next statement provides the boundary.
   accounting=any(SECTION.match(r['text'].strip().rstrip(':')) or SUBHEADING.match(r['text'].strip().rstrip(':')) for r in rows[:18])
   if n_numeric>=3 and not blocked and not different_title and (in_range or continuation) and (items or in_range or accounting):
    detected.append({'type':previous_type,'page':i,'items':items,'method':s['method'],'label':s['label'],'warning':'amount_only_continuation' if not items else 'titleless_continuation'})

  bytype=defaultdict(list)
  for d in detected:bytype[d['type']].append(d)
  # A complete readable basic TOC ending at Notes supplies absence evidence even
  # for three-statement enterprise or two-statement pension reporting models.
  toc_complete=any(is_toc(s['text']) and re.search(r'notes to (?:the )?(?:basic )?financial statements',normalized(s['text'])) for s in summaries) and len(toc_types)>=2
  for typ in TYPES:
   pages=bytype[typ]
   if windows[typ]:pages=[p for p in pages if any(lo<=p['page']<=hi for lo,hi in windows[typ])]
   typed_hints=[i for i,t in hints.items() if t==typ]
   groups=[]
   for d in pages:
    if not groups or d['page']>groups[-1][-1]['page']+1:groups.append([d])
    else:groups[-1].append(d)
   chosen=groups[0] if len(groups)==1 else [];warnings=[]
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
 write_csv(out/'caption_occurrences.csv',OCC_FIELDS,occurrences())
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
 db.commit()


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
  tasks.append((str(p),str(root),str(out),options,metadata))
 # Scope checkpoint to this input tree and current file membership.
 for rel, in db.execute('SELECT source_path FROM results').fetchall():
  if rel not in seen:db.execute('DELETE FROM results WHERE source_path=?',(rel,))
 db.commit()
 def save(result):
  rel=result['base']['source_path']
  db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',(rel,result['base']['document_id'],config_id,json.dumps(result)));db.commit()
  print(f"{result['logs'][0]['status'].upper()} {rel}: {len(result['occurrences'])} rows",flush=True)
 try:
  if args.workers==1:
   for task in tasks:save(process_pdf(task))
  else:
   # map chunksize=1; reports stay in workers, only small result structures return.
   # Bounded chunks avoid submitting all 25,000 tasks to an unbounded queue.
   with ProcessPoolExecutor(max_workers=args.workers) as pool:
    for start in range(0,len(tasks),args.workers*2):
     for result in pool.map(process_pdf,tasks[start:start+args.workers*2],chunksize=1):save(result)
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
 args=parser.parse_args()
 if args.workers<1:parser.error('--workers must be positive')
 try:return run(args)
 except (ValueError,OSError,sqlite3.Error) as e:parser.exit(2,f'{type(e).__name__}: {e}\n')

if __name__=='__main__':raise SystemExit(main())
