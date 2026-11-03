"""Regression tests for layouts found on the 72 larger Drive sample reports (0.5.0)."""
from pathlib import Path
import sys
import unittest
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import acfr_extractor as a


class Labels(unittest.TestCase):
 def test_footer_with_entity_name(self):
  # Boston: "16 City of Boston, Massachusetts"; mirrored on facing pages.
  self.assertEqual(a.printed_label([{'y0':750,'text':'16 City of Boston, Massachusetts'}],792),'16')
  self.assertEqual(a.printed_label([{'y0':750,'text':'City of Boston, Massachusetts 17'}],792),'17')
  # A statement total near the bottom is not a page number.
  self.assertEqual(a.printed_label([{'y0':720,'text':'Total net position 523'}],792),'')
 def test_dash_wrapped_header_number(self):
  # Sussex: "SUSSEX COUNTY, DELAWARE -19-" on the first header line.
  self.assertEqual(a.printed_label([{'y0':22,'text':'SUSSEX COUNTY, DELAWARE -19-'}],792),'19')
  self.assertEqual(a.printed_label([{'y0':22,'text':'Page 21'}],792),'21')


class Toc(unittest.TestCase):
 def test_number_first_entries(self):
  # Phoenix/UNC put the page number before the title.
  text='PHOENIX\nTable of\nContents\nEnterprise Fund Financial Statements\n36 Statement of Net Position (Exhibit B-9)\n38 Statement of Revenues, Expenses and Changes in Net Position (Exhibit B-10)\n40 Statement of Cash Flows (Exhibit B-11)\n47 Notes to the Financial Statements'
  self.assertTrue(a.is_toc(text))
  got=[(e['type'],e['label']) for e in a.toc_entries([{'text':text}]) if e['type'] in a.TYPES]
  self.assertEqual(got,[('PF_NET_POSITION','36'),('PF_OPERATING','38'),('PF_CASH_FLOWS','40')])
 def test_garbled_title_number_first_toc(self):
  text="Financial Statements\n,I'aI1Ie ,>f ( : , >11 l e11 l s\n44 Statement of Net Position - Proprietary Fund\n45 Statement of Revenues, Expenses, and Changes in Net Position - Proprietary Fund\n46 Statement of Cash Flows - Proprietary Funds\n47 Statement of Fiduciary Net Position - Custodial Funds\n50 Notes to the Financial Statements"
  self.assertTrue(a.is_toc(text))


class Titles(unittest.TestCase):
 def test_fiduciary_word_in_body_does_not_retype(self):
  # Cincinnati: header-area body text mentions fiduciary activity.
  h='City of Cincinnati, Ohio\nStatement of Net Position\nJune 30, 2025\nGovernmental Business-Type\nEquity in City Treasury held for fiduciary purposes 12,345'
  self.assertEqual(a.identify(h,'government wide'),'GW_NET_POSITION')
 def test_typo_and_fiduciary_component_units(self):
  self.assertEqual(a.identify('OLMSTED COUNTY\nSTATEMENT OF ACTIVITES\nFOR THE YEAR ENDED DECEMBER 31, 2025'),'GW_ACTIVITIES')
  self.assertEqual(a.identify('Metropolitan Washington Airports Authority\nFiduciary Component Units\nBasic Financial Statements\nStatement of Fiduciary Net Position\nAs of December 31, 2025'),'FF_NET_POSITION')
  self.assertIsNone(a.identify('City of Miami, Florida\nStatement of Net Position\nDiscretely Presented Component Units\nSeptember 30, 2025'))
 def test_comparative_prior_year_excluded(self):
  self.assertIsNone(a.identify('Metropolitan Transportation Commission\nBalance Sheet - Governmental Funds\nJune 30, 2024\n(For comparative information purposes)'))


class Combined(unittest.TestCase):
 def test_combined_government_wide_and_fund_statements(self):
  # Poudre River Library / MWRD single-program presentations.
  for h,a1,b1 in [('Poudre River Public Library District\nStatement of Net Position and Governmental Funds Balance Sheet\nDecember 31, 2025','GF_BALANCE_SHEET','GW_NET_POSITION'),
                  ('Exhibit A-2\nStatements of Governmental Fund Revenues, Expenditures and Changes in Fund Balances/Statement of Activities\nYear Ended December 31, 2025','GF_OPERATING','GW_ACTIVITIES')]:
   # Either type may be identified first; the page must serve both.
   t=a.identify(h,'government wide');self.assertEqual({t,a.combined_pair(a.title_scope(h),t)},{a1,b1})
  h='Reconciliation of the Balance Sheet to the Statement of Net Position'
  self.assertIsNone(a.combined_pair(a.title_scope(h),'GF_BALANCE_SHEET'))


class Text(unittest.TestCase):
 def test_symbol_soup_is_bad_but_amount_panel_is_not(self):
  soup=' '.join(["K D`D[ O U 12 - GE . 4 4 !#$ [D /$ +\"+: 8 _GKZ ZG[ , 8 < = KKD - > 491 KM ./ 4 0 1 12"]*4)
  self.assertTrue(a.bad_text(soup))
  panel='NONMAJOR\nPROPRIETARY\nFUNDS TOTAL\n'+'\n'.join(f'$ {i},962 $ {i}5,806,635' for i in range(10,40))
  self.assertFalse(a.bad_text(panel))
 def test_amount_panel_rows(self):
  rows=a.group_words([(60,150+i*12,110,158+i*12,f'{i},962') for i in range(6)]+[(300,150+i*12,360,158+i*12,f'{i}5,806') for i in range(6)])
  self.assertEqual(a.amount_panel_rows(rows,792),6)


class Rotation(unittest.TestCase):
 def test_sideways_landscape_page_is_read_upright(self):
  # Pennsylvania stores landscape statements with /Rotate 90, which leaves all
  # displayed lines vertical; the upright reading frame must be recovered.
  d=pymupdf.open();p=d.new_page(width=792,height=612)
  p.insert_text((40,40),'Commonwealth of Pennsylvania');p.insert_text((40,60),'Statement of Activities')
  for j in range(25):p.insert_text((40,90+j*18),f'Program line {j}');p.insert_text((600,90+j*18),f'{(j+1)*1000:,}')
  p.set_rotation(90)
  rows,width,height,extra=a.native_frame(p)
  self.assertEqual((width,height),(792,612));self.assertEqual(extra,270)
  self.assertIn('Statement of Activities',a.page_header(rows,height))
  self.assertGreaterEqual(a.numeric_rows(rows,width,height),20)
  d.close()


class CaptionNumbers(unittest.TestCase):
 def rows(self,spec):
  words=[]
  for y,tokens in spec:
   for x,t in tokens:words.append((x,y,x+5*len(t),y+9,t))
  return a.group_words(words)
 def test_note_numbers_dates_and_hyphens_stay_in_captions(self):
  rows=self.rows([(150,[(60,'Revenues')]),
   (170,[(60,'Transfers—Note'),(110,'5'),(118,'............'),(400,'(807,773)'),(470,'807,773')]),
   (190,[(60,'Net'),(75,'Position'),(110,'June'),(130,'30,'),(145,'2024,'),(170,'as'),(185,'restated'),(400,'33,345,694'),(470,'1,260,702')]),
   (210,[(60,'Sales'),(85,'taxes'),(110,'-'),(120,'Restricted'),(400,'1,234'),(470,'5,678')]),
   (230,[(60,'Interest'),(100,'received'),(250,'____________'),(300,'583'),(340,'____'),(400,'2,030'),(470,'114')])])
  got=[x['text'] for x in a.extract_rows(rows,612,792)]
  self.assertIn('Transfers—Note 5',got)
  self.assertIn('Net Position June 30, 2024, as restated',got)
  self.assertIn('Sales taxes - Restricted',got)
  self.assertIn('Interest received',got)


class Workbook(unittest.TestCase):
 def test_workbook_holds_only_frequencies(self):
  import subprocess,tempfile
  from openpyxl import load_workbook
  sys.path.insert(0,str(Path(__file__).resolve().parent))
  from test_extractor import make_report
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'in').mkdir();make_report(root/'in'/'district.pdf')
   r=subprocess.run([sys.executable,str(Path(a.__file__)),'--input',str(root/'in'),'--output',str(root/'out'),'--occurrences','sqlite'],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
   self.assertFalse((root/'out'/'caption_occurrences.csv').exists())
   self.assertTrue((root/'out'/'caption_occurrences.sqlite').exists())
   # A read-only workbook keeps the file open until close(); Windows cannot
   # delete the temporary directory while it is open.
   wb=load_workbook(root/'out'/'caption_frequencies.xlsx',read_only=True)
   try:
    self.assertEqual(wb.sheetnames,['Caption frequencies','Statements','About'])
    head=next(wb['Caption frequencies'].iter_rows(values_only=True))
    self.assertIn('Standardized caption',head);self.assertNotIn('pdf_page',head);self.assertNotIn('Original caption',head)
    self.assertGreater(sum(1 for _ in wb['Caption frequencies'].iter_rows()),1)
   finally:wb.close()


class FileNames(unittest.TestCase):
 def test_state_entity_year_names(self):
  ident=lambda n:a.document_identity(Path(n),{})
  got=ident('CA Alameda County 2025.pdf');self.assertEqual((got['government_name'],got['fiscal_year']),('Alameda County, CA','2025'))
  self.assertEqual(ident('TX  Fort Worth Independent School District  2024.pdf')['government_name'],'Fort Worth Independent School District, TX')
  self.assertEqual(ident('ACFR001__AK_City_and_Borough_of_Juneau_2025.pdf')['government_name'],'City and Borough of Juneau, AK')
  self.assertNotEqual(ident('WA Washington County 2025.pdf')['government_name'],ident('OR Washington County 2025.pdf')['government_name'])
  self.assertEqual(ident('Some Report.pdf')['fiscal_year'],'')
  self.assertEqual(a.document_identity(Path('CA Alameda County 2025.pdf'),{'government_name':'County of Alameda, CA'})['government_name'],'County of Alameda, CA')


class Isolation(unittest.TestCase):
 def test_hung_report_is_stopped_and_others_finish(self):
  import csv,os,subprocess,tempfile
  sys.path.insert(0,str(Path(__file__).resolve().parent))
  from test_extractor import make_report
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);inputs=root/'in';inputs.mkdir()
   make_report(inputs/'good.pdf');make_report(inputs/'hang.pdf')
   env={**os.environ,'ACFR_TEST_HANG':'hang.pdf'}
   r=subprocess.run([sys.executable,str(Path(a.__file__)),'--input',str(inputs),'--output',str(root/'out'),'--workers','2','--timeout','3'],capture_output=True,text=True,env=env,timeout=120)
   self.assertEqual(r.returncode,1,r.stderr)
   with (root/'out'/'processing_log.csv').open(encoding='utf-8-sig') as f:log={x['pdf_filename']:x for x in csv.DictReader(f)}
   self.assertEqual(log['hang.pdf']['status'],'failed');self.assertIn('timed out',log['hang.pdf']['message'])
   self.assertNotEqual(log['good.pdf']['status'],'failed')


if __name__=='__main__':unittest.main()
