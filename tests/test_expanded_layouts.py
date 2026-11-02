"""Regression fixtures for layouts found in the 19-report expansion."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import acfr_extractor as a

class ExpandedRulesTests(unittest.TestCase):
 def test_toc_ranges_use_start_and_end(self):
  text='TABLE OF CONTENTS\nBasic Financial Statements\nGovernment-wide Financial Statements\nStatement of Net Position 15-16\nStatement of Activities 17-18\nNotes to Basic Financial Statements 32-94'
  entries=a.toc_entries([{'text':text}]);self.assertEqual([(x['label'],x['end_label']) for x in entries[:2]],[('15','16'),('17','18')])
 def test_comparative_and_plural_fiduciary(self):
  text='TABLE OF CONTENTS\nFinancial Statements\nComparative Statements of Net Position 28-29\nComparative Statements of Revenues, Expenses and Changes in Net Position 30\nComparative Statements of Cash Flows 31\nComparative Statements of Fiduciary Net Position 32\nComparative Statements of Changes in Fiduciary Net Position 33\nNotes to Financial Statements 35-60'
  self.assertEqual([x['type'] for x in a.toc_entries([{'text':text}]) if x['type'] in a.TYPES],['PF_NET_POSITION','PF_OPERATING','PF_CASH_FLOWS','FF_NET_POSITION','FF_CHANGES'])
 def test_component_unit_does_not_change_college_model(self):
  text='TABLE OF CONTENTS\nBasic Financial Statements\nStatements of Net Position 38-39\nStatements of Revenues, Expenses and Changes in Net Position 40\nStatements of Cash Flows 41-42\nComponent Unit:\nStatements of Financial Position 43\nStatements of Activities 44\nNotes to Financial Statements 45-88'
  entries=a.toc_entries([{'text':text}]);types={x['type'] for x in entries}
  self.assertIn('PF_NET_POSITION',types);self.assertNotIn('GW_ACTIVITIES',types)
 def test_inline_affiliated_organization_does_not_exclude_next_statement(self):
  text='TABLE OF CONTENTS\nStatements of Net Position (Exhibit 1) 19\nStatements of Financial Position - Affiliated Organization (Exhibit 1-A) 20\nStatements of Revenues, Expenses, and Changes in Net Position (Exhibit 2) 21\nStatements of Activities - Affiliated Organization (Exhibit 2-A) 22\nStatements of Cash Flows (Exhibit 3) 23-24\nNotes to Financial Statements 25'
  entries=a.toc_entries([{'text':text}]);self.assertEqual([x['type'] for x in entries if x['type'] in a.TYPES],['PF_NET_POSITION','PF_OPERATING','PF_CASH_FLOWS'])
 def test_reconciliation_wrap_is_consumed(self):
  text='TABLE OF CONTENTS\nGovernment-wide Financial Statements\nA-2 Statement of Activities 27\nB-3 Reconciliation of Governmental Fund Changes to\nStatement of Activities 32\nNotes to Financial Statements 37'
  entries=a.toc_entries([{'text':text}]);self.assertEqual([e['label'] for e in entries if e['type']=='GW_ACTIVITIES'],['27'])
 def test_enterprise_primary_government_columns(self):
  self.assertEqual(a.identify('Statement of Net Position December 31, 2025 Primary Government Component Units',enterprise=True),'PF_NET_POSITION')
 def test_combining_allowed_only_with_basic_evidence(self):
  header='Combining Statement of Net Position Proprietary Funds June 30, 2025'
  self.assertIsNone(a.identify(header));self.assertEqual(a.identify(header,allow_basic_combining=True),'PF_NET_POSITION')
 def test_dotted_leaders_are_not_captions(self):
  words=[]
  for i,label in enumerate(['ADDITIONS','Employee ....................','Employer ......................','Total additions ...................']):
   y=130+i*20;words.append((40,y,250,y+10,label))
   if i:words.append((400,y,460,y+10,'503,821'))
  items=a.extract_rows(a.group_words(words),612,792)
  self.assertIn('Employee',[i['text'] for i in items]);self.assertFalse(any('...' in i['text'] for i in items))
 def test_indented_child_is_not_joined_to_parent_heading(self):
  words=[]
  for y,x,label,value in [(120,40,'ASSETS',None),(140,50,'Restricted current assets',None),(155,62,'Cash','100'),(180,50,'Other assets','100'),(200,50,'Total assets','200')]:
   words.append((x,y,250,y+13,label))
   if value:words.append((350,y,400,y+13,value))
  items=a.extract_rows(a.group_words(words),612,792);labels=[r['text'] for r in items]
  self.assertIn('Restricted current assets',labels);self.assertIn('Cash',labels);self.assertNotIn('Restricted current assets Cash',labels)
 def test_image_blocks_do_not_shift_text_direction_indices(self):
  d=pymupdf.open();p=d.new_page()
  p.insert_image(pymupdf.Rect(500,600,520,620),stream=b'P6\n2 2\n255\n'+b'\xff'*12)
  p.insert_text((500,500),'SIDEBAR',rotate=90)
  p.insert_text((40,60),'Statement of Net Position')
  text=' '.join(r['text'] for r in a.native_rows(p))
  self.assertIn('Statement of Net Position',text);self.assertNotIn('SIDEBAR',text);d.close()
 def test_vertical_toc_title_remains_document_evidence(self):
  d=pymupdf.open();p=d.new_page();p.insert_text((500,500),'TABLE OF CONTENT',rotate=90)
  p.insert_text((40,100),'Statement of Cash Flows 31');p.insert_text((40,120),'Notes to Financial Statements 39')
  rows=a.native_rows(p)
  self.assertTrue(a.is_toc(a.native_text(p,rows)));self.assertNotIn('TABLE OF CONTENT',' '.join(r['text'] for r in rows));d.close()
 def test_rotated_pdf_coordinates_are_normalized(self):
  d=pymupdf.open();p=d.new_page();p.insert_text((100,700),'Statement of Cash Flows',rotate=90);p.set_rotation(90)
  rows=a.native_rows(p);self.assertIn('Statement of Cash Flows',' '.join(r['text'] for r in rows))
  for row in rows:
   for x0,y0,x1,y1,_ in row['words']:
    self.assertGreaterEqual(x0,0);self.assertGreaterEqual(y0,0);self.assertLessEqual(x1,p.rect.width);self.assertLessEqual(y1,p.rect.height)
  d.close()
 def test_singular_content_heading_and_running_labels(self):
  text='TABLE OF CONTENT\nStatement of Cash Flows 31\nNotes to Financial Statements 39'
  self.assertTrue(a.is_toc(text));self.assertFalse(a.is_toc('Independent auditor report\nThe statements are listed in the table of contents.'))
  self.assertEqual(a.printed_label([{'y0':750,'text':'24 | Financial'}],792),'24')
  self.assertEqual(a.label_number('(25)'),'25')

class ExpandedPipelineTests(unittest.TestCase):
 def test_numeric_only_panel_is_in_inventory(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);inp=root/'input';inp.mkdir();out=root/'out';d=pymupdf.open()
   p=d.new_page()
   for i,text in enumerate(['TABLE OF CONTENTS','Basic Financial Statements','Statement of Net Position 1-2','Statement of Cash Flows 3','Notes to Financial Statements 4']):p.insert_text((40,40+i*20),text)
   for page_number in [1,2,3,4]:
    p=d.new_page();p.insert_text((300,770),str(page_number))
    if page_number==4:p.insert_text((40,40),'Notes to Financial Statements');continue
    if page_number!=2:
     p.insert_text((40,40),'Statement of Net Position' if page_number==1 else 'Statement of Cash Flows')
     for j,text in enumerate(['ASSETS','Cash','Receivables','Total assets']):p.insert_text((40,140+j*20),text)
    for j in range(1,4):p.insert_text((350,140+j*20),'123,456')
   d.save(inp/'panels.pdf');d.close()
   r=subprocess.run([sys.executable,a.__file__,'--input',str(inp),'--output',str(out)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   with (out/'statement_inventory.csv').open(encoding='utf-8-sig') as f:inv=list(csv.DictReader(f))
   row=next(r for r in inv if r['statement_type']=='PF_NET_POSITION');self.assertEqual(row['pdf_pages'],'2;3');self.assertIn('amount_only_continuation',row['warning'])

if __name__=='__main__':unittest.main()
