"""Write human-readable reference transcribed from page renderings and source TOCs.
Not derived from extractor output. Includes headings and repeated caption occurrences.
"""
import json
from pathlib import Path
J='ACFR001__AK_City_and_Borough_of_Juneau_2025.pdf'
A='ACFR002__AK_State_of_Alaska_2025.pdf'
B='ACFR003__AL_Auburn_2025.pdf'
types=['GW_NET_POSITION','GW_ACTIVITIES','GF_BALANCE_SHEET','GF_OPERATING','PF_NET_POSITION','PF_OPERATING','PF_CASH_FLOWS','FF_NET_POSITION','FF_CHANGES']
reference={'method':'Assistant manually transcribed caption labels and headings from rendered PDF pages; statement membership checked against source TOCs and page titles. Not an external accountant audit. Auburn held out from modern rule tuning, though legacy baseline saw all reports.','statements':{
 J:dict(zip(types,[[34],[35,36],[37,38],[41,42],[45,46,47,48],[49,50],[51,52,53,54],[],[]])),
 A:dict(zip(types,[[26,27],[28,29],[30],[32],[34,35],[37],[38,39],[40],[41]])),
 B:dict(zip(types,[[83,84],[85],[86],[87],[91],[92],[93],[94],[95]]))},'caption_pages':[]}
for name,page,text in [
(J,34,'''ASSETS:
Equity in central treasury
Receivables (net of allowance for credit losses)
Due from other governments
Internal balances
Inventories
Prepaid items
Other assets
Temporarily restricted assets:
Equity in central treasury
Receivables (net of allowance for credit losses)
Intergovernmental receivables
Leases receivable, long-term
Net OPEB asset
Capital assets:
Lease assets, net of amortization
Subscription assets, net of amortization
Land
Plant and equipment, net of depreciation
Infrastructure, net of depreciation
Construction and infrastructure in progress
Total assets
DEFERRED OUTFLOWS OF RESOURCES
Total assets and deferred outflows of resources
LIABILITIES:
Accounts payable
Accrued liabilities
Accrued interest payable
Unearned revenue
Liabilities payable from restricted assets
Noncurrent liabilities:
Due within one year:
Bonds, loans, and contracts
Compensated absences
Leases payable
Subscription payable
Due in more than one year:
Bonds, loans, and contracts
Compensated absences
Leases payable
Subscription payable
Net pension liability
Total liabilities
DEFERRED INFLOWS OF RESOURCES
Total liabilities and deferred inflows of resources
NET POSITION (DEFICIT):
Net investment in capital assets
Restricted - expendable:
Capital projects
Debt service
Net OPEB asset
Permanent fund
Other purposes
Restricted - nonexpendable - Jensen-Olson Arboretum
Unrestricted
Total net position (deficit)'''),
(A,26,'''ASSETS
Cash and Investments
Accounts Receivable - Net
Interest and Dividends Receivable
Internal Balances
Due from Primary Government
Due from Component Units
Due from Other Governments
Loans, Notes, Bonds, and Leases Receivable
Inventories
Repossessed Property
Restricted Assets
Securities Lending Collateral
Net Pension Asset
Net OPEB Asset
Other Assets
Capital Assets
Equipment, Net of Depreciation
Buildings, Net of Depreciation
Library Books, Net of Depreciation
Infrastructure, Net of Depreciation
Intangibles, Net of Amortization
Museum Collections
Land / Right-of-Way
Construction in Progress
Total Assets
DEFERRED OUTFLOWS OF RESOURCES
Total Deferred Outflows of Resources
LIABILITIES
Accounts Payable and Accrued Liabilities
Obligations Under Securities Lending
Due to Primary Government
Due to Component Units
Due to Other Governments
Interest Payable
Derivative Instruments
Other Current Liabilities'''),
(B,83,'''ASSETS
Current assets:
Cash and cash equivalents
Investments
Certificates of deposit
Receivables, net
Accrued interest receivable
Due from component units
Inventories
Current portion of mortgages and notes receivable
Current portion of leases receivable
Current portion of notes receivable
Property tax receivable
Interest receivable
Due from other governments
Due from primary government
Other current assets
Restricted cash
Total current assets
Noncurrent assets:
Restricted assets
Cash and cash equivalents
Leases receivable, net of current portion
Mortgages and notes receivable, net of current portion
Investments
Notes receivable, net of current portion
Advances to other agencies
Property for resale
Capital assets not being depreciated
Capital assets net of accumulated depreciation
Total noncurrent assets
Total assets
DEFERRED OUTFLOWS OF RESOURCES
Deferred amount on refunding
Pension related
OPEB related
Total deferred outflows of resources''')]:
 reference['caption_pages'].append({'pdf_filename':name,'statement_type':'GW_NET_POSITION','pdf_page':page,'captions':text.splitlines()})
Path(__file__).with_name('verified_reference.json').write_text(json.dumps(reference,indent=2))
