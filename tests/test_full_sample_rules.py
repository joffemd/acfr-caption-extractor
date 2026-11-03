"""Regression tests for layouts found while running the 48-report Drive sample (0.4.0)."""
import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import acfr_extractor as a


class TocRules(unittest.TestCase):
 def entries(self,text):
  return [(e['type'],e['label'],e['end_label']) for e in a.toc_entries([{'text':text}])]
 def test_figure_dash_and_and_ranges(self):
  # Hawaii prints U+2012 figure dashes; Greenville prints "16 and 17".
  text='TABLE OF CONTENTS\nStatement of Net Position ..... 30‒31\nStatement of Activities ..... 32 and 33\nNotes to Basic Financial Statements ..... 52‒120'
  self.assertEqual(self.entries(text)[:2],[('GW_NET_POSITION','30','31'),('GW_ACTIVITIES','32','33')])
 def test_component_unit_and_fasb_entries_are_boundaries(self):
  text='TABLE OF CONTENTS\nStatement of Net Position 28\nStatement of Financial Position - Component Units 29\nStatement of Revenues, Expenses, and Changes in Net Position 30\nStatement of Activities - Component Units 31\nStatement of Cash Flows 32\nNotes to Financial Statements 33'
  types=[t for t,_,_ in self.entries(text)]
  self.assertEqual([t for t in types if t in a.TYPES],['PF_NET_POSITION','PF_OPERATING','PF_CASH_FLOWS'])
  self.assertEqual(types.count('EXCLUDED'),3)
 def test_unlabelled_fasb_pair(self):
  # Oakton: the foundation statements carry no "component unit" label in the TOC.
  text='TABLE OF CONTENTS\nStatements of Net Position 38-39\nStatements of Revenues, Expenses and Changes in Net Position 40\nStatements of Cash Flows 41-42\nStatements of Financial Position 43\nStatements of Activities 44\nNotes to Financial Statements 45-88'
  self.assertEqual([t for t,_,_ in self.entries(text) if t in a.TYPES],['PF_NET_POSITION','PF_OPERATING','PF_CASH_FLOWS'])
 def test_bare_exhibit_letter(self):
  text='TABLE OF CONTENTS\nC Balance Sheet — Governmental Funds ..... 50–51\nE Statement of Revenues, Expenditures, and Changes in Fund Balances — Governmental Funds ..... 53\nNotes to the Basic Financial Statements ..... 75–129'
  self.assertEqual(self.entries(text)[:2],[('GF_BALANCE_SHEET','50','51'),('GF_OPERATING','53','')])
 def test_back_link_is_not_a_toc(self):
  # Duluth prints a "Table of Contents" link on every page.
  statement='Table of Contents\nCITY OF DULUTH, MINNESOTA\nSTATEMENT OF NET POSITION\nDECEMBER 31, 2025\nCash and cash equivalents $ 183,016,746 $ 61,000\nReceivables 12,345 678\nCapital assets 9,876,543 210\nTotal assets 1,234,567 89'
  self.assertFalse(a.is_toc(statement))
  self.assertTrue(a.is_toc('Table of Contents\nStatement of Net Position 22\nStatement of Activities 23\nBalance Sheet 25'))
 def test_label_gaps_are_inferred_only_with_consistent_offset(self):
  s=[{'page':i,'text':'','label':l} for i,l in enumerate(['33','','35','','37','40'])]
  self.assertEqual(a.infer_labels(s),{0:'33',1:'34',2:'35',3:'36',4:'37',5:'40'})
  s=[{'page':0,'text':'','label':'10'},{'page':1,'text':'','label':''},{'page':2,'text':'','label':'15'}]
  self.assertNotIn(1,a.infer_labels(s))


class TitleRules(unittest.TestCase):
 def test_navigation_tabs_do_not_reject(self):
  h='INTRODUCTORY SECTION FINANCIAL SECTION STATISTICAL SECTION\nSTATEMENT OF NET POSITION\nJune 30, 2025\nPrimary Government'
  self.assertEqual(a.identify(h,'government wide'),'GW_NET_POSITION')
 def test_running_header_before_title(self):
  h='Annual Comprehensive Financial Report for the Year Ended June 30, 2025\nCity of Portland Oregon\nStatement of Net Position\nProprietary Funds\nJune 30, 2025'
  self.assertEqual(a.identify(h,'government wide'),'PF_NET_POSITION')
 def test_prose_mentions_are_not_titles(self):
  for h in ['LAKEWOOD LOCAL SCHOOL DISTRICT\nManagement’s Discussion and Analysis\nThe Statement of Net Position provides a perspective of the District as a whole and is very long text here.',
            'LAKEWOOD LOCAL SCHOOL DISTRICT\nTotal Governmental Fund Balances $ 20,774,668\nAmounts reported for governmental activities in the\nstatement of net position are different because']:
   self.assertIsNone(a.identify(h,'government wide'))
 def test_component_unit_titles(self):
  self.assertIsNone(a.identify('State of Hawaii\nComponent Units\nStatement of Net Position\nJune 30, 2025'))
  self.assertIsNone(a.identify('OAKTON COLLEGE\nCOMPONENT UNIT\nOAKTON COLLEGE EDUCATIONAL FOUNDATION\nDES PLAINES, ILLINOIS\nSTATEMENTS OF ACTIVITIES\nFor the Years Ended June 30, 2025'))
  # Column headings after the date do not exclude the primary government statement.
  self.assertEqual(a.identify('State of Hawaii\nStatement of Net Position\nJune 30, 2025\nPrimary Government Component Units','government wide'),'GW_NET_POSITION')
 def test_fiduciary_variants_and_typo(self):
  self.assertEqual(a.identify('STATEMENT OF FIDUCIARY NET POSITON\nFIDUCIARY FUND'),'FF_NET_POSITION')
  self.assertEqual(a.identify('Statement of Additions, Deductions and Changes in Fiduciary Net Position'),'FF_CHANGES')
  self.assertEqual(a.identify('CITY OF PITTSBURGH\nSTATEMENT OF CHANGES IN NET POSITION\nFIDUCIARY FUNDS\nYEAR ENDED DECEMBER 31, 2025'),'FF_CHANGES')
  self.assertEqual(a.identify('Statement of Revenues, Expenses, and Changes in Net Position\nProprietary Funds'),'PF_OPERATING')
 def test_leading_the_in_title(self):
  # Cedar Rapids: "The Statement of Fund Net Position / Proprietary Funds".
  self.assertEqual(a.identify('City of Cedar Rapids, Iowa\nThe Statement of Fund Net Position\nProprietary Funds\nJune 30, 2025'),'PF_NET_POSITION')
  self.assertIsNone(a.identify('CITY\nThe Statement of Net Position provides a view','government wide'))


class SparseStatement(unittest.TestCase):
 def test_dash_amounts_count_only_when_requested(self):
  rows=a.group_words([(40,180,120,190,'ADDITIONS'),(40,200,200,210,'Taxes'),(400,200,460,210,'237,315,820'),(40,220,200,230,'Payments'),(400,220,460,230,'237,315,820'),(40,240,200,250,'Change'),(450,240,460,250,'-'),(40,260,200,270,'Beginning'),(450,260,460,270,'-')])
  self.assertEqual(a.numeric_rows(rows,612,792),2)
  self.assertEqual(a.numeric_rows(rows,612,792,dashes=True),4)
  self.assertEqual(a.extract_rows(rows,612,792),[])
  self.assertIn('Taxes',[x['text'] for x in a.extract_rows(rows,612,792,dashes=True)])


class CaptionRules(unittest.TestCase):
 def rows(self,spec):
  words=[]
  for y,x,label,amt in spec:
   xx=x
   for t in label.split():words.append((xx,y,xx+5*len(t),y+9,t));xx+=5*len(t)+3
   if amt:words.append((420,y,470,y+9,amt))
  return a.group_words(words)
 def test_hanging_wrap_dates_and_spaced_dash_heading(self):
  rows=self.rows([(150,40,'REVENUES',''),(165,48,'Taxes','1,000'),(180,48,'Charges for services','2,000'),(195,40,'Fund Balances - January 1, 2025, as previously',''),(205,52,'reported','3,000'),
                  (220,40,'Excess (Deficiency) of Revenues Over (Under)',''),(230,52,'Expenditures','400'),(245,40,'Payable from restricted assets -',''),(260,48,'Accounts payable','50'),
                  (275,40,'Fund Balances - December 31, 2025','3,400'),(60,40,'June 30, 2025','')])
  got=[(x['row_kind'],x['text']) for x in a.extract_rows(rows,612,792)]
  self.assertIn(('caption','Fund Balances - January 1, 2025, as previously reported'),got)
  self.assertIn(('caption','Excess (Deficiency) of Revenues Over (Under) Expenditures'),got)
  self.assertIn(('heading','Payable from restricted assets -'),got)
  self.assertIn(('caption','Accounts payable'),got)
  self.assertIn(('caption','Fund Balances - December 31, 2025'),got)
  self.assertNotIn('June 30, 2025',[t for _,t in got])


def page(d,lines):
 p=d.new_page()
 for y,(x,text) in lines:p.insert_text((x,y),text,fontsize=9)
 return p

class Pipeline(unittest.TestCase):
 def test_back_link_running_header_and_untitled_continuation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);inputs=root/'in';inputs.mkdir();out=root/'out'
   d=pymupdf.open()
   page(d,[(40,(40,'Table of Contents')),(80,(40,'Statement of Net Position ..... 2-3')),(100,(40,'Statement of Activities ..... 4')),(120,(40,'Balance Sheet - Governmental Funds ..... 5')),(140,(40,'Notes to the Financial Statements ..... 6'))])
   body=[(170,(40,'ASSETS')),(190,(48,'Cash and cash equivalents')),(190,(400,'1,000,000')),(210,(48,'Receivables')),(210,(400,'200,000')),(230,(48,'Capital assets')),(230,(400,'3,000,000')),(250,(40,'Total assets')),(250,(400,'4,200,000'))]
   page(d,[(30,(40,'Table of Contents')),(50,(40,'Annual Comprehensive Financial Report for the Year Ended June 30, 2025')),(70,(40,'TEST CITY')),(90,(40,'STATEMENT OF NET POSITION')),(110,(40,'JUNE 30, 2025')),*body,(760,(300,'2'))])
   # Untitled second page: no title, deferred inflows and net position sections.
   page(d,[(30,(40,'Table of Contents')),(70,(40,'TEST CITY')),(170,(40,'LIABILITIES')),(190,(48,'Accounts payable')),(190,(400,'50,000')),(210,(48,'Long-term debt')),(210,(400,'900,000')),(230,(40,'NET POSITION')),(250,(48,'Unrestricted')),(250,(400,'3,250,000'))])
   page(d,[(30,(40,'Table of Contents')),(70,(40,'TEST CITY')),(90,(40,'STATEMENT OF ACTIVITIES')),(110,(40,'FOR THE YEAR ENDED JUNE 30, 2025')),(170,(40,'Functions/Programs')),(190,(48,'General government')),(190,(400,'(100,000)')),(210,(48,'Public safety')),(210,(400,'(200,000)')),(230,(40,'Total primary government')),(230,(400,'(300,000)')),(760,(300,'4'))])
   page(d,[(30,(40,'Table of Contents')),(70,(40,'TEST CITY')),(90,(40,'BALANCE SHEET')),(105,(40,'GOVERNMENTAL FUNDS')),(120,(40,'JUNE 30, 2025')),*body,(760,(300,'5'))])
   page(d,[(30,(40,'Table of Contents')),(70,(40,'TEST CITY')),(90,(40,'NOTES TO THE FINANCIAL STATEMENTS')),(120,(40,'Note 1. Summary of significant accounting policies.')),(760,(300,'6'))])
   d.save(inputs/'city.pdf');d.close()
   r=subprocess.run([sys.executable,str(Path(a.__file__)),'--input',str(inputs),'--output',str(out)],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
   with (out/'statement_inventory.csv').open(encoding='utf-8-sig') as f:inv={x['statement_type']:x for x in csv.DictReader(f)}
   self.assertEqual(inv['GW_NET_POSITION']['pdf_pages'],'2;3')
   self.assertEqual(inv['GW_ACTIVITIES']['pdf_pages'],'4')
   self.assertEqual(inv['GF_BALANCE_SHEET']['pdf_pages'],'5')


if __name__=='__main__':unittest.main()
