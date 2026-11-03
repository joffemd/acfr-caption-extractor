import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import acfr_extractor as a

RULES=json.loads(a.CONFIG.read_text(encoding='utf-8'))

class RulesTests(unittest.TestCase):
 def test_all_nine_titles(self):
  examples={
   'GW_NET_POSITION':('Statement of Net Position Government-wide',''),
   'GW_ACTIVITIES':('Statement of Activities',''),
   'GF_BALANCE_SHEET':('Governmental Funds Balance Sheet',''),
   'GF_OPERATING':('Statement of Revenues, Expenditures, and Changes in Fund Balances',''),
   'PF_NET_POSITION':('Statement of Net Position','Proprietary Funds'),
   'PF_OPERATING':('Statement of Revenues, Expenses, and Changes in Fund Net Position',''),
   'PF_CASH_FLOWS':('Statement of Cash Flows',''),
   'FF_NET_POSITION':('Statement of Fiduciary Net Position',''),
   'FF_CHANGES':('Statement of Changes in Fiduciary Net Position','')}
  for expected,(title,context) in examples.items():
   with self.subTest(expected=expected):self.assertEqual(a.identify(title,context),expected)
 def test_exclusions(self):
  for title in ['Combining Balance Sheet Governmental Funds','Reconciliation of Balance Sheet to Statement of Net Position','Condensed Statement of Net Position Government-wide','Notes to Basic Financial Statements Statement of Activities','Statement of Net Position Component Units']:
   with self.subTest(title=title):self.assertIsNone(a.identify(title))
 def test_cash_flow_reconciliation_is_part_of_statement(self):
  self.assertEqual(a.identify('Statement of Cash Flows Proprietary Funds '+(' '*190)+'Reconciliation of operating income'),'PF_CASH_FLOWS')
 def test_ambiguous_net_position(self):self.assertIsNone(a.identify('Statement of Net Position'))
 def test_enterprise_only(self):self.assertEqual(a.identify('Statement of Net Position',enterprise=True),'PF_NET_POSITION')
 def test_normalization_conservative(self):
  self.assertEqual(a.standardize('  Cash, AND  Cash Equivalents! ',RULES),'cash and cash equivalents')
  self.assertNotEqual(a.standardize('Due within 1 year',RULES),a.standardize('Due within 2 years',RULES))
 def test_context_keys(self):
  self.assertNotEqual(a.caption_key('Other','Assets','Current',RULES),a.caption_key('Other','Liabilities','Current',RULES))
 def test_numeric_filter(self):
  for x in ['1,234','(2,300)','$','—','12.50']:self.assertTrue(a.amount(x),x)
  for x in ['Accounts payable','GASB 87','2025 Bonds']:self.assertFalse(a.amount(x),x)
 def test_printed_numbers(self):
  self.assertEqual(a.label_number('I – 18'),'I-18')
  self.assertEqual(a.label_number('- 17 -'),'17')
  self.assertEqual(a.label_number('Page with narrative'),'')
 def test_page_number_on_notes_footer_baseline(self):
  rows=[{'y0':755,'text':'The notes to the financial statements are an integral part of this statement. 69'}]
  self.assertEqual(a.printed_label(rows,792),'69')
 def test_bad_text(self):
  self.assertTrue(a.bad_text('$>+>/7/8> 90  /> "9=3>398 '+ '3D7 @AF 8;@3@5;3> '*30))
  self.assertFalse(a.bad_text('Statement of Net Position Government-wide Assets cash and investments Total assets '+ 'Cash and investments '*20))
 def test_toc_wrapped_and_reconciliation(self):
  text='TABLE OF CONTENTS\nBasic Financial Statements\nGovernmental Funds\nStatement of Revenues, Expenditures, and\nChanges in Fund Balances ..... I – 24\nReconciliation of the Change in Fund Balances to\nthe Statement of Activities ..... I – 25'
  self.assertEqual([e['type'] for e in a.toc_entries([{'text':text}]) if e['type'] in a.TYPES],['GF_OPERATING'])
  self.assertEqual([e['label'] for e in a.toc_entries([{'text':text}]) if e['type']=='EXCLUDED'],['I-25'])
 def test_wrapped_caption_and_heading(self):
  words=[]
  for y,label,value in [(100,'ASSETS:',None),(120,'Restricted investments:',None),(140,'Loans and notes','100'),(170,'Total assets','100'),(195,'Total liabilities','50')]:
   words.append((40,y,210,y+9,label))
   if value:words.append((350,y,390,y+9,value))
  words += [(40,130,200,139,'Long term'),(40,160,200,169,'(net of allowances)')]
  rows=a.extract_rows(a.group_words(words),612,792)
  labels=[r['text'] for r in rows]
  self.assertIn('Restricted investments:',labels)
  self.assertIn('Long term Loans and notes',labels)


def make_report(path,start=0):
 d=pymupdf.open()
 for _ in range(start):d.new_page()
 for title,rows in [('Statement of Net Position',['ASSETS','Cash and cash equivalents','Accounts receivable','Total assets']),('Statement of Cash Flows',['Cash flows from operating activities','Receipts from customers','Payments to suppliers','Net cash provided'])]:
  p=d.new_page();p.insert_text((40,45),'TEST WATER DISTRICT');p.insert_text((40,65),title)
  for j,text in enumerate(rows):
   p.insert_text((40,140+j*20),text)
   if j:p.insert_text((350,140+j*20),str(1000*j))
 d.save(path);d.close()

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.inputs=self.root/'inputs';self.inputs.mkdir();self.output=self.root/'out'
 def tearDown(self):self.tmp.cleanup()
 def invoke(self,*extra):
  return subprocess.run([sys.executable,str(Path(a.__file__)),'--input',str(self.inputs),'--output',str(self.output),*extra],capture_output=True,text=True)
 def read(self,name):
  with (self.output/name).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
 def test_windows_code_page_and_unicode_names(self):
  # Windows reads files and writes redirected output with a legacy code page
  # (cp1252), not UTF-8. Every file access must name its encoding, and a name
  # cp1252 cannot show (from acfrs.reason.org) must not crash progress output.
  name='HI Kanu o ka \u02bb\u0100ina School 2025.pdf';make_report(self.inputs/name)
  env=dict(os.environ,PYTHONIOENCODING='cp1252',PYTHONWARNDEFAULTENCODING='1')
  r=subprocess.run([sys.executable,str(Path(a.__file__)),'--input',str(self.inputs),'--output',str(self.output)],capture_output=True,encoding='cp1252',errors='replace',env=env)
  self.assertEqual(r.returncode,0,r.stderr)
  # openpyxl's own warning (a temp file it only names, never writes) is not ours.
  self.assertEqual([l for l in r.stderr.splitlines() if 'EncodingWarning' in l and 'openpyxl' not in l],[])
  self.assertIn('Found 1 PDFs',r.stdout);self.assertIn('1 PDFs to process, 0 already done',r.stdout)
  self.assertIn(' HI Kanu o ka \\u02bb\\u0100ina School 2025.pdf',r.stdout)
  self.assertEqual({x['government_name'] for x in self.read('statement_inventory.csv')},{'Kanu o ka \u02bb\u0100ina School, HI'})
 def test_after_page60_enterprise_and_resume(self):
  pdf=self.inputs/'district.pdf';make_report(pdf,70)
  r=self.invoke('--workers','2');self.assertEqual(r.returncode,0,r.stderr)
  inv=self.read('statement_inventory.csv')
  np=next(x for x in inv if x['statement_type']=='PF_NET_POSITION')
  self.assertEqual(np['pdf_pages'],'71');self.assertEqual(np['status'],'present')
  self.assertEqual(next(x for x in inv if x['statement_type']=='GW_NET_POSITION')['status'],'unknown')
  before=(self.output/'caption_occurrences.csv').read_bytes()
  r=self.invoke('--resume');self.assertEqual(r.returncode,0,r.stderr);self.assertIn('RESUME',r.stdout)
  self.assertEqual(before,(self.output/'caption_occurrences.csv').read_bytes())
  # A normalization change re-exports without rerunning extraction.
  rules=self.root/'rules.json';rr=dict(RULES);rr['aliases']={'cash and cash equivalents':'cash equivalents'};rules.write_text(json.dumps(rr),encoding='utf-8')
  r=self.invoke('--resume','--rules',str(rules));self.assertIn('RESUME',r.stdout)
  self.assertIn('cash equivalents',[x['standardized_caption'] for x in self.read('caption_occurrences.csv')])
 def test_malformed_and_password_pdf(self):
  (self.inputs/'bad.pdf').write_bytes(b'not a PDF')
  d=pymupdf.open();d.new_page();d.save(self.inputs/'locked.pdf',encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='password');d.close()
  r=self.invoke();self.assertEqual(r.returncode,1)
  logs=self.read('processing_log.csv');self.assertEqual(len(logs),2);self.assertTrue(all(x['status']=='failed' for x in logs))
  self.assertEqual(len(self.read('statement_inventory.csv')),18)
  self.assertTrue(any('password_required' in x['message'] for x in logs))
 def test_distinct_statement_frequency_and_denominator(self):
  out=self.root/'freq';out.mkdir();db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.execute('CREATE TABLE results(source_path,payload)')
  for i in range(2):
   base={'statement_type':'GW_NET_POSITION','document_id':f'd{i}','government_name':'Same government','statement_id':f's{i}','original_caption':'Cash','section':'Assets','parent_heading':'Assets','row_kind':'caption'}
   payload={'occurrences':[base,base],'inventory':[{'statement_type':'GW_NET_POSITION','statement_id':f's{i}','status':'present'},{'statement_type':'PF_NET_POSITION','statement_id':f'p{i}','status':'absent'}],'logs':[]}
   db.execute('INSERT INTO results VALUES (?,?)',(str(i),json.dumps(payload)))
  a.export_results(db,out,RULES)
  with (out/'caption_frequencies.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
  self.assertEqual(len(rows),1);r=rows[0]
  self.assertEqual((r['statement_count'],r['acfr_count'],r['government_count'],r['successful_statement_denominator']),('2','2','1','2'))
  self.assertEqual(r['frequency_percent'],'100.0')
 def test_ocr_scanned_page(self):
  try:subprocess.run(['tesseract','--version'],capture_output=True,check=True)
  except (FileNotFoundError,subprocess.CalledProcessError):self.skipTest('Tesseract unavailable')
  vector=self.root/'vector.pdf';make_report(vector)
  source=pymupdf.open(vector);dest=pymupdf.open()
  for page in source:
   pix=page.get_pixmap(dpi=180);p=dest.new_page(width=612,height=792);p.insert_image(p.rect,stream=pix.tobytes('png'))
  dest.save(self.inputs/'scan.pdf');source.close();dest.close()
  r=self.invoke('--ocr','all');self.assertEqual(r.returncode,0,r.stderr)
  occ=self.read('caption_occurrences.csv');self.assertGreater(len(occ),0);self.assertTrue(all(x['method']=='ocr' for x in occ))
  inv=self.read('statement_inventory.csv')
  self.assertEqual(next(x for x in inv if x['statement_type']=='PF_NET_POSITION')['status'],'present')
 def test_ambiguous_candidates_never_absent(self):
  d=pymupdf.open();p=d.new_page()
  p.insert_text((40,40),'TABLE OF CONTENTS')
  for i,text in enumerate(['Governmental Funds','Statement of Activities ..... 10','Balance Sheet Governmental Funds ..... 11','Statement of Revenues Expenditures and Changes in Fund Balances ..... 12','Statement of Cash Flows ..... 13']):p.insert_text((40,70+i*20),text)
  for i in range(3):
   p=d.new_page()
   if i==1:continue
   p.insert_text((40,45),'Statement of Net Position Primary Government')
   for j,text in enumerate(['ASSETS','Cash','Receivables','Total assets']):
    p.insert_text((40,140+j*20),text)
    if j:p.insert_text((350,140+j*20),'1000')
  d.save(self.inputs/'ambiguous.pdf');d.close()
  r=self.invoke();self.assertEqual(r.returncode,0,r.stderr)
  inv=self.read('statement_inventory.csv')
  self.assertEqual(next(x for x in inv if x['statement_type']=='GW_NET_POSITION')['status'],'unknown')
 def test_empty_input_is_error(self):self.assertEqual(self.invoke().returncode,2)

if __name__=='__main__':unittest.main()
