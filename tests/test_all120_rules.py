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


if __name__=='__main__':unittest.main()
