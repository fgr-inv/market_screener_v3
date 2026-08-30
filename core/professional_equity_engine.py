from __future__ import annotations

"""Professional equity research engine.

Industry/sub-industry classification, business-model-specific quality scoring,
valuation method selection, specialist KPI expectations and research framing.
The engine deliberately separates *what should be analysed* from *what the free
feeds actually provide*. Missing non-standard KPIs are disclosed, never inferred.
"""

from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd

from core.utils import clamp


def _present(v: Any) -> bool:
    if v is None: return False
    if isinstance(v, str): return bool(v.strip()) and v.strip().upper() not in {'N/D','N/A','NONE','UNAVAILABLE'}
    try: return bool(pd.notna(v))
    except Exception: return True


def _num(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else np.nan
    except Exception: return np.nan


def _score_growth(x, good=.08, great=.18):
    x=_num(x)
    if pd.isna(x): return np.nan
    return 92 if x>=great*1.5 else 84 if x>=great else 70 if x>=good else 56 if x>0 else 34 if x>-0.10 else 18


def _score_margin(x, good=.12, great=.25):
    x=_num(x)
    if pd.isna(x): return np.nan
    return 92 if x>=great*1.4 else 84 if x>=great else 70 if x>=good else 55 if x>0 else 22


def _score_roe(x):
    x=_num(x)
    if pd.isna(x): return np.nan
    return 92 if x>=.35 else 84 if x>=.25 else 72 if x>=.15 else 58 if x>=.08 else 38 if x>0 else 18


def _score_roic(x):
    x=_num(x)
    if pd.isna(x): return np.nan
    # FMP may expose decimal or percentage depending endpoint/version.
    if abs(x)>2: x=x/100
    return 92 if x>=.25 else 84 if x>=.18 else 72 if x>=.12 else 58 if x>=.07 else 35 if x>0 else 18


def _score_debt_equity(x, tolerant=False):
    x=_num(x)
    if pd.isna(x): return np.nan
    levels=(100,180,280,450) if tolerant else (50,100,180,300)
    return 88 if x<levels[0] else 74 if x<levels[1] else 58 if x<levels[2] else 38 if x<levels[3] else 18


def _score_fcf_yield(f):
    y=_num(f.get('FCF_Yield'))
    if pd.isna(y):
        fcf=_num(f.get('FCF')); mc=_num(f.get('Market_Cap'))
        if pd.notna(fcf) and pd.notna(mc) and mc: y=fcf/mc
    elif abs(y)>1.5: y=y/100
    if pd.isna(y): return np.nan
    return 92 if y>=.08 else 84 if y>=.055 else 72 if y>=.035 else 60 if y>=.02 else 45 if y>0 else 18


def _score_cash_conversion(f):
    fcf=_num(f.get('FCF')); ocf=_num(f.get('Operating_Cashflow'))
    if pd.isna(fcf) or pd.isna(ocf) or ocf==0: return np.nan
    r=fcf/abs(ocf)
    return 90 if r>=.8 else 80 if r>=.6 else 68 if r>=.4 else 52 if r>=.2 else 28 if r>=0 else 15


def _score_liquidity(f):
    cr=_num(f.get('Current_Ratio')); qr=_num(f.get('Quick_Ratio'))
    vals=[]
    if pd.notna(cr): vals.append(88 if cr>=1.8 else 76 if cr>=1.3 else 62 if cr>=1.0 else 38 if cr>=.7 else 20)
    if pd.notna(qr): vals.append(88 if qr>=1.4 else 74 if qr>=1.0 else 58 if qr>=.7 else 34)
    return np.mean(vals) if vals else np.nan


def _score_sbc(f):
    x=_num(f.get('SBC_to_Revenue'))
    if pd.isna(x): return np.nan
    return 90 if x<=.03 else 78 if x<=.06 else 62 if x<=.10 else 42 if x<=.18 else 20


def _score_inventory(f):
    x=_num(f.get('Inventory_to_Revenue'))
    if pd.isna(x): return np.nan
    # Generic sanity score only; trend is more valuable but unavailable from a single latest fact.
    return 82 if x<=.10 else 72 if x<=.20 else 58 if x<=.35 else 38 if x<=.55 else 22


def _weighted(values: dict[str,float], weights: dict[str,float]):
    used=[(k,_num(values.get(k)),w) for k,w in weights.items() if pd.notna(_num(values.get(k)))]
    if not used: return np.nan,0.0,[]
    sw=sum(w for _,_,w in used)
    score=sum(v*w for _,v,w in used)/sw
    return int(clamp(round(score))), round(100*sw/sum(weights.values()),1), [k for k,_,_ in used]


@dataclass(frozen=True)
class IndustryProfile:
    key: str
    label: str
    sector: str
    description: str
    kpis: tuple[str,...]
    valuation: tuple[str,...]
    catalysts: tuple[str,...]
    risks: tuple[str,...]
    peer_basis: str
    weights: dict[str,float]


# Quality pillar names: growth, earnings, margin, efficiency, fcf, balance, liquidity, sbc, inventory.
PROFILES: dict[str,IndustryProfile] = {
    'ai_accelerators': IndustryProfile('ai_accelerators','AI Accelerators / GPU','Technology','Compute platform economics: demand visibility, product cadence, ecosystem lock-in, supply and gross-margin durability.',('Data_Center_Growth','AI_Accelerator_Revenue','Gross_Margin','Product_Cadence','Supply_Commitments','Customer_Concentration'),('Forward P/E','EV/EBITDA','FCF yield','PEG / growth-adjusted multiple'),('AI capex','new architecture ramps','hyperscaler budgets','inference adoption'),('customer concentration','competition/custom silicon','export controls','cycle/valuation'), 'Semiconductor compute peers', {'growth':.22,'earnings':.14,'margin':.18,'efficiency':.12,'fcf':.17,'balance':.08,'inventory':.09}),
    'memory': IndustryProfile('memory','Memory Semiconductors','Technology','Highly cyclical memory economics: bits shipped, pricing, HBM mix, utilization, inventory and capex discipline.',('DRAM_Pricing','NAND_Pricing','HBM_Revenue','Bit_Shipments','Utilization','Inventory_Days','Capex'),('Mid-cycle P/E','EV/EBITDA','P/B','FCF yield'),('HBM ramps','memory pricing','supply cuts/additions','AI server demand'),('oversupply','pricing collapse','capex cycle','customer inventory'), 'Memory peers', {'growth':.13,'earnings':.14,'margin':.17,'efficiency':.10,'fcf':.17,'balance':.11,'inventory':.18}),
    'foundry': IndustryProfile('foundry','Semiconductor Foundry','Technology','Foundry model: node leadership, utilization, wafer pricing, capex intensity and customer concentration.',('Advanced_Node_Mix','Utilization','Wafer_Pricing','Capex','Yield','Customer_Concentration'),('Forward P/E','EV/EBITDA','FCF yield'),('node ramps','AI/HPC demand','utilization recovery'),('geopolitics','capex intensity','yield execution','customer concentration'), 'Foundry peers', {'growth':.14,'earnings':.12,'margin':.18,'efficiency':.15,'fcf':.15,'balance':.10,'inventory':.16}),
    'semi_equipment': IndustryProfile('semi_equipment','Semiconductor Equipment','Technology','Equipment economics: wafer-fab-equipment cycle, backlog, service mix, bookings and technology intensity.',('WFE_Growth','Bookings','Backlog','Service_Revenue','Gross_Margin','China_Exposure'),('Forward P/E','EV/EBITDA','FCF yield'),('fab capex','node transitions','memory recovery','advanced packaging'),('export restrictions','order pushouts','cycle peak','customer concentration'), 'Semi equipment peers', {'growth':.15,'earnings':.14,'margin':.16,'efficiency':.14,'fcf':.18,'balance':.10,'inventory':.13}),
    'analog_semis': IndustryProfile('analog_semis','Analog / Mixed Signal Semiconductors','Technology','Analog model: broad end-market demand, inventory normalization, pricing durability, utilization and capital returns.',('Industrial_Auto_Mix','Inventory_Days','Utilization','Pricing','Gross_Margin'),('Forward P/E','EV/EBITDA','FCF yield'),('industrial recovery','auto content growth','inventory normalization'),('long downcycle','China weakness','inventory correction'), 'Analog semiconductor peers', {'growth':.11,'earnings':.13,'margin':.18,'efficiency':.16,'fcf':.20,'balance':.10,'inventory':.12}),
    'connectivity_semis': IndustryProfile('connectivity_semis','Connectivity / Networking Semiconductors','Technology','Connectivity silicon: AI interconnect, switching/optical exposure, design wins, content growth and margins.',('AI_Networking_Revenue','Design_Wins','Content_per_System','Gross_Margin','Customer_Concentration','Capex'),('Forward P/E','EV/EBITDA','FCF yield'),('AI cluster buildout','800G/1.6T ramps','custom silicon'),('customer concentration','architecture shifts','valuation'), 'Connectivity semiconductor peers', {'growth':.19,'earnings':.15,'margin':.17,'efficiency':.13,'fcf':.18,'balance':.09,'inventory':.09}),
    'eda_ip': IndustryProfile('eda_ip','EDA / Semiconductor IP','Technology','Mission-critical design software/IP: recurring revenue, backlog/RPO, design activity and very high switching costs.',('ARR','RPO','Backlog','Renewal_Rate','SBC','FCF_Margin'),('Forward P/E','EV/Sales','EV/FCF','FCF yield'),('AI chip complexity','R&D intensity','new node/design starts'),('valuation','China/export risk','SBC dilution'), 'EDA/IP peers', {'growth':.19,'earnings':.13,'margin':.17,'efficiency':.13,'fcf':.18,'balance':.07,'sbc':.13}),
    'saas': IndustryProfile('saas','Software / SaaS','Technology','Recurring software economics: ARR/RPO, NRR, durable growth, gross margin, FCF margin and dilution.',('ARR','RPO','NRR','Billings_Growth','Gross_Margin','FCF_Margin','SBC'),('EV/Sales vs growth+margin','EV/FCF','FCF yield','Rule of 40'),('AI monetization','large-deal activity','seat expansion','margin inflection'),('growth deceleration','SBC dilution','competition','multiple compression'), 'Software/SaaS peers', {'growth':.22,'earnings':.08,'margin':.16,'efficiency':.10,'fcf':.19,'balance':.06,'liquidity':.06,'sbc':.13}),
    'cybersecurity': IndustryProfile('cybersecurity','Cybersecurity Software','Technology','Security platform economics: ARR/RPO, platform consolidation, NRR, billings, FCF and sales efficiency.',('ARR','RPO','NRR','Billings_Growth','Platform_Adoption','FCF_Margin','SBC'),('EV/Sales vs growth+FCF','EV/FCF','FCF yield'),('security spending','platform consolidation','AI security demand'),('competition','billings slowdown','SBC dilution','valuation'), 'Cybersecurity peers', {'growth':.23,'earnings':.07,'margin':.14,'efficiency':.10,'fcf':.20,'balance':.06,'liquidity':.06,'sbc':.14}),
    'it_services': IndustryProfile('it_services','IT Services / Consulting','Technology','Services model: bookings, utilization, headcount productivity, pricing, margin and FCF conversion.',('Bookings','Backlog','Utilization','Headcount_Growth','Pricing','FCF_Conversion'),('Forward P/E','EV/EBITDA','FCF yield'),('enterprise IT budgets','AI consulting demand','bookings'),('discretionary IT cuts','wage inflation','utilization'), 'IT services peers', {'growth':.14,'earnings':.15,'margin':.15,'efficiency':.14,'fcf':.20,'balance':.12,'liquidity':.10}),
    'hardware': IndustryProfile('hardware','Technology Hardware','Technology','Hardware economics: units, ASP/mix, installed base, channel inventory, services attach and cash returns.',('Units','ASP_Mix','Installed_Base','Channel_Inventory','Services_Mix','Gross_Margin'),('Forward P/E','EV/EBITDA','FCF yield'),('product cycle','replacement cycle','services mix'),('mature units','supply chain','China exposure','product concentration'), 'Hardware peers', {'growth':.12,'earnings':.14,'margin':.15,'efficiency':.16,'fcf':.21,'balance':.12,'inventory':.10}),

    'money_center_bank': IndustryProfile('money_center_bank','Money-Center Bank','Financials','Bank economics: NIM, deposit franchise, fees, credit quality, capital and ROTCE.',('NIM','Deposit_Growth','Deposit_Mix','NCO_Ratio','CET1','ROTCE','Tangible_Book_Value'),('P/TBV','P/E','ROTCE vs cost of equity'),('yield curve','loan growth','capital returns','fee growth'),('credit deterioration','deposit competition','regulation','duration risk'), 'Large-bank peers', {'earnings':.20,'efficiency':.25,'balance':.30,'growth':.10,'fcf':.15}),
    'regional_bank': IndustryProfile('regional_bank','Regional Bank','Financials','Regional-bank economics: deposits/beta, CRE exposure, NIM, losses, capital and tangible book.',('NIM','Deposit_Beta','Deposit_Growth','CRE_Exposure','NCO_Ratio','CET1','Tangible_Book_Value'),('P/TBV','P/E','ROTCE'),('deposit stabilization','curve steepening','loan growth'),('deposit flight','CRE losses','capital pressure','regulation'), 'Regional-bank peers', {'earnings':.18,'efficiency':.22,'balance':.34,'growth':.08,'fcf':.18}),
    'insurance': IndustryProfile('insurance','Insurance','Financials','Underwriting + investment economics: combined ratio, pricing, reserve adequacy, investment yield and book growth.',('Combined_Ratio','Premium_Growth','Reserve_Adequacy','Investment_Yield','Book_Value_Growth'),('P/B','P/E','ROE vs cost of equity'),('pricing cycle','higher reinvestment yields','cat-loss normalization'),('reserve charges','catastrophes','pricing reversal','asset losses'), 'Insurance peers', {'growth':.12,'earnings':.16,'margin':.10,'efficiency':.22,'fcf':.12,'balance':.28}),
    'asset_manager': IndustryProfile('asset_manager','Asset Management','Financials','AUM economics: net flows, fee rate, performance fees, operating leverage and capital returns.',('AUM','Net_Flows','Fee_Rate','Performance_Fees','Operating_Margin'),('P/E','EV/EBITDA','FCF yield'),('market appreciation','positive flows','alternatives growth'),('outflows','fee compression','market beta','key-person risk'), 'Asset-manager peers', {'growth':.15,'earnings':.15,'margin':.19,'efficiency':.15,'fcf':.21,'balance':.15}),
    'exchange': IndustryProfile('exchange','Exchange / Market Infrastructure','Financials','Market infrastructure: volumes, open interest/listings, data/services mix, pricing and high incremental margins.',('Trading_Volume','Open_Interest','Data_Revenue','Recurring_Revenue','Operating_Margin'),('Forward P/E','EV/EBITDA','FCF yield'),('volatility/volumes','new products','data growth'),('volume normalization','regulation','fee pressure'), 'Exchange peers', {'growth':.16,'earnings':.14,'margin':.20,'efficiency':.16,'fcf':.20,'balance':.14}),
    'payments': IndustryProfile('payments','Payments Network / Processor','Financials','Payments economics: TPV, transactions, cross-border, take rate, active credentials and incremental margins.',('TPV_Growth','Transactions_Growth','Cross_Border_Growth','Take_Rate','Operating_Margin'),('Forward P/E','EV/EBITDA','FCF yield'),('consumer spending','cross-border travel','digital penetration'),('regulation','pricing pressure','consumer slowdown','fintech competition'), 'Payments peers', {'growth':.18,'earnings':.15,'margin':.18,'efficiency':.16,'fcf':.20,'balance':.13}),
    'consumer_finance': IndustryProfile('consumer_finance','Consumer Finance','Financials','Lending economics: receivable growth, NIM/yield, delinquencies, charge-offs, funding and capital.',('Receivable_Growth','Net_Interest_Margin','Delinquency_Rate','Charge_Off_Rate','Funding_Cost'),('P/E','P/B','ROTCE'),('credit normalization','consumer strength','funding costs'),('charge-offs','funding stress','regulation'), 'Consumer-finance peers', {'growth':.11,'earnings':.16,'efficiency':.18,'balance':.32,'fcf':.23}),

    'data_center_reit': IndustryProfile('data_center_reit','Data Center REIT','Real Estate','Data-center real estate: bookings, power capacity, occupancy, same-store NOI, development yields and leverage.',('FFO','AFFO','Bookings','MW_Capacity','Occupancy','Same_Store_NOI','Development_Yield','Debt_Maturity_Profile'),('P/AFFO','EV/EBITDAre','NAV premium/discount','implied cap rate'),('AI/cloud demand','power delivery','pre-leasing'),('power constraints','capex funding','rates','customer concentration'), 'Data-center REIT peers', {'growth':.15,'earnings':.10,'margin':.10,'fcf':.22,'balance':.28,'efficiency':.15}),
    'industrial_reit': IndustryProfile('industrial_reit','Industrial / Logistics REIT','Real Estate','Logistics real estate: occupancy, rent spreads, same-store NOI, development pipeline and balance sheet.',('FFO','AFFO','Occupancy','Rent_Spreads','Same_Store_NOI','Development_Pipeline','Debt_Maturity_Profile'),('P/AFFO','NAV premium/discount','implied cap rate'),('rent resets','e-commerce/logistics demand','development leasing'),('supply wave','rates','tenant weakness'), 'Industrial REIT peers', {'growth':.13,'earnings':.10,'margin':.10,'fcf':.24,'balance':.28,'efficiency':.15}),
    'residential_reit': IndustryProfile('residential_reit','Residential REIT','Real Estate','Residential REIT: blended rent growth, occupancy, concessions, same-store NOI and supply by market.',('FFO','AFFO','Occupancy','Blended_Rent_Growth','Concessions','Same_Store_NOI','Debt_Maturity_Profile'),('P/AFFO','NAV premium/discount','implied cap rate'),('rent growth','supply moderation','household formation'),('new supply','rent controls','rates'), 'Residential REIT peers', {'growth':.12,'earnings':.10,'margin':.10,'fcf':.24,'balance':.29,'efficiency':.15}),
    'retail_reit': IndustryProfile('retail_reit','Retail REIT','Real Estate','Retail property economics: occupancy, leasing spreads, tenant sales, same-store NOI and redevelopment.',('FFO','AFFO','Occupancy','Leasing_Spreads','Tenant_Sales','Same_Store_NOI'),('P/AFFO','NAV premium/discount','implied cap rate'),('leasing spreads','tenant demand','redevelopment'),('tenant bankruptcies','consumer weakness','rates'), 'Retail REIT peers', {'growth':.10,'earnings':.11,'margin':.10,'fcf':.24,'balance':.30,'efficiency':.15}),
    'healthcare_reit': IndustryProfile('healthcare_reit','Healthcare REIT','Real Estate','Healthcare real estate: occupancy, operator coverage, reimbursement sensitivity, NOI and leverage.',('FFO','AFFO','Occupancy','Operator_Coverage','Same_Store_NOI','Debt_Maturity_Profile'),('P/AFFO','NAV premium/discount','implied cap rate'),('senior housing recovery','demographics','occupancy'),('operator distress','reimbursement','rates'), 'Healthcare REIT peers', {'growth':.11,'earnings':.10,'margin':.10,'fcf':.24,'balance':.30,'efficiency':.15}),
    'tower_reit': IndustryProfile('tower_reit','Tower REIT','Real Estate','Tower economics: organic tenant billings, churn, amendment activity, leasing and leverage.',('FFO','AFFO','Organic_Tenant_Billings','Churn','Leasing_Activity','Debt_Maturity_Profile'),('P/AFFO','EV/EBITDA','FCF yield'),('5G densification','carrier capex','international growth'),('carrier consolidation','rates','FX'), 'Tower REIT peers', {'growth':.13,'earnings':.10,'margin':.12,'fcf':.25,'balance':.27,'efficiency':.13}),
    'reit_general': IndustryProfile('reit_general','REIT','Real Estate','Property economics: FFO/AFFO, occupancy, same-store NOI, NAV/cap rate and debt maturities.',('FFO','AFFO','NAV','Occupancy','Same_Store_NOI','Debt_Maturity_Profile'),('P/AFFO','NAV premium/discount','implied cap rate'),('rent/NOI growth','leasing','rates'),('rates','refinancing','tenant/property cycle'), 'Property-type REIT peers', {'growth':.11,'earnings':.10,'margin':.10,'fcf':.24,'balance':.30,'efficiency':.15}),

    'ep': IndustryProfile('ep','Oil & Gas E&P','Energy','Upstream economics: production, reserves, realized price, unit costs, hedges, breakeven and returns.',('Production','Reserves','Realized_Price','Lifting_Cost','Hedge_Book','FCF_Breakeven'),('EV/EBITDA','FCF yield','EV/2P reserves','NAV'),('oil/gas price','production growth','capital returns'),('commodity downside','cost inflation','reserve replacement','policy'), 'E&P peers', {'growth':.08,'earnings':.10,'margin':.13,'efficiency':.14,'fcf':.24,'balance':.19,'inventory':.12}),
    'integrated_oil': IndustryProfile('integrated_oil','Integrated Oil & Gas','Energy','Integrated model: upstream price sensitivity plus refining/chemicals, production, capex and shareholder returns.',('Production','Reserves','Realized_Price','Refining_Margins','Chemicals_Margins','Capex','Shareholder_Returns'),('EV/EBITDA','FCF yield','P/E through cycle'),('commodity prices','refining margins','LNG/projects'),('commodity downturn','megaproject execution','policy'), 'Integrated-energy peers', {'growth':.07,'earnings':.10,'margin':.13,'efficiency':.15,'fcf':.25,'balance':.20,'inventory':.10}),
    'oil_services': IndustryProfile('oil_services','Oilfield Services','Energy','Services model: international/North America activity, pricing, backlog, utilization and FCF conversion.',('Backlog','Rig_or_Frack_Activity','Pricing','Utilization','International_Growth','FCF_Conversion'),('EV/EBITDA','FCF yield','P/E'),('E&P capex','international projects','pricing'),('capex cuts','pricing pressure','customer concentration'), 'Oil-services peers', {'growth':.14,'earnings':.15,'margin':.15,'efficiency':.14,'fcf':.20,'balance':.13,'inventory':.09}),
    'midstream': IndustryProfile('midstream','Midstream / Pipelines','Energy','Infrastructure cash-flow model: volumes, contract mix, distributable cash flow, leverage and project returns.',('Volumes','Take_or_Pay_Mix','DCF','Distribution_Coverage','Leverage','Growth_Capex'),('EV/EBITDA','DCF yield','FCF yield'),('volume growth','LNG exports','project starts'),('counterparty risk','project overruns','rates/regulation'), 'Midstream peers', {'growth':.09,'earnings':.10,'margin':.13,'efficiency':.13,'fcf':.25,'balance':.24,'liquidity':.06}),
    'refining': IndustryProfile('refining','Refining','Energy','Refining economics: crack spreads, utilization, throughput, capture rate and maintenance.',('Crack_Spread','Utilization','Throughput','Capture_Rate','Turnaround_Capex'),('Mid-cycle EV/EBITDA','FCF yield'),('crack spreads','product demand','turnaround completion'),('margin collapse','outages','RIN/regulatory costs'), 'Refiner peers', {'growth':.07,'earnings':.10,'margin':.16,'efficiency':.15,'fcf':.24,'balance':.18,'inventory':.10}),
    'lng': IndustryProfile('lng','LNG Infrastructure / Export','Energy','LNG economics: contracted capacity, utilization, project execution, spreads and funding.',('Contracted_Capacity','Utilization','Project_Capex','FID_Pipeline','Contract_Duration'),('EV/EBITDA','DCF/FCF yield','NAV'),('new trains','global LNG demand','contracting'),('project delays','gas basis','financing','regulation'), 'LNG peers', {'growth':.15,'earnings':.10,'margin':.13,'efficiency':.12,'fcf':.18,'balance':.25,'liquidity':.07}),

    'biotech': IndustryProfile('biotech','Biotechnology','Health Care','Pipeline valuation: clinical probability, TAM, differentiation, cash runway, dilution and risk-adjusted NPV.',('Pipeline','Trial_Phase','Probability_of_Success','TAM','Cash_Runway','Dilution_Risk','rNPV'),('rNPV / EV','cash-adjusted EV','EV vs pipeline'),('trial readouts','FDA decisions','partnering','launch data'),('clinical failure','dilution','safety','single-asset concentration'), 'Stage/mechanism biotech peers', {'growth':.08,'earnings':.03,'margin':.05,'efficiency':.08,'fcf':.05,'balance':.27,'liquidity':.28,'sbc':.16}),
    'pharma': IndustryProfile('pharma','Pharmaceuticals','Health Care','Portfolio model: product growth, patent cliffs, pipeline replacement, R&D productivity, margins and FCF.',('Product_Growth','Pipeline','Patent_Cliffs','Product_Concentration','R_and_D_Productivity'),('Forward P/E','EV/EBITDA','FCF yield','SOTP/rNPV'),('launches','label expansion','trial readouts','M&A'),('patent cliffs','pricing policy','pipeline failure','concentration'), 'Pharma peers', {'growth':.14,'earnings':.14,'margin':.17,'efficiency':.14,'fcf':.20,'balance':.12,'liquidity':.09}),
    'medtech': IndustryProfile('medtech','Medical Devices / MedTech','Health Care','MedTech economics: procedure growth, installed base, consumables, innovation cycle, gross margin and FCF.',('Procedure_Growth','Installed_Base','Consumables_Growth','Gross_Margin','R_and_D','FCF_Conversion'),('Forward P/E','EV/EBITDA','FCF yield'),('procedure recovery','new product cycles','robotics adoption'),('reimbursement','competition','hospital budgets','regulatory'), 'MedTech peers', {'growth':.17,'earnings':.14,'margin':.16,'efficiency':.15,'fcf':.18,'balance':.11,'liquidity':.09}),
    'managed_care': IndustryProfile('managed_care','Managed Care','Health Care','Insurer economics: membership, premium yield, medical cost ratio, utilization, Stars/Medicare and capital.',('Membership_Growth','Premium_Yield','Medical_Cost_Ratio','Utilization','Stars_Ratings'),('Forward P/E','FCF yield'),('rate updates','membership','cost trend normalization'),('medical-cost inflation','policy','reimbursement cuts'), 'Managed-care peers', {'growth':.13,'earnings':.16,'margin':.11,'efficiency':.17,'fcf':.18,'balance':.16,'liquidity':.09}),
    'hospital': IndustryProfile('hospital','Hospitals / Providers','Health Care','Provider economics: admissions, acuity, payer mix, labor cost, reimbursement and leverage.',('Admissions','Acuity','Payer_Mix','Labor_Cost','Revenue_per_Admission'),('EV/EBITDA','FCF yield','P/E'),('volume growth','labor normalization','pricing'),('labor inflation','payer pressure','bad debt','policy'), 'Provider peers', {'growth':.13,'earnings':.15,'margin':.15,'efficiency':.13,'fcf':.18,'balance':.17,'liquidity':.09}),
    'life_science_tools': IndustryProfile('life_science_tools','Life Science Tools','Health Care','Tools economics: biopharma funding, instrument placements, consumables, book-to-bill, China and margins.',('Organic_Growth','Book_to_Bill','Instrument_Placements','Consumables_Mix','China_Exposure'),('Forward P/E','EV/EBITDA','FCF yield'),('biopharma funding','instrument cycle','China recovery'),('funding slowdown','China weakness','destocking'), 'Life-science tools peers', {'growth':.15,'earnings':.14,'margin':.16,'efficiency':.15,'fcf':.18,'balance':.13,'inventory':.09}),

    'aerospace_defense': IndustryProfile('aerospace_defense','Aerospace & Defense','Industrials','Long-cycle industrial model: backlog, bookings, book-to-bill, program execution, margins and FCF.',('Backlog','Orders','Book_to_Bill','Program_Margins','FCF_Conversion'),('Forward P/E','EV/EBITDA','FCF yield'),('defense budgets','aircraft build rates','bookings'),('program charges','supply chain','fixed-price contracts','politics'), 'Aerospace/defense peers', {'growth':.14,'earnings':.14,'margin':.14,'efficiency':.14,'fcf':.20,'balance':.14,'inventory':.10}),
    'automation': IndustryProfile('automation','Automation / Robotics','Industrials','Automation economics: orders, backlog, book-to-bill, recurring software/service, margins and factory capex.',('Orders','Backlog','Book_to_Bill','Recurring_Revenue','Installed_Base','FCF_Conversion'),('Forward P/E','EV/EBITDA','FCF yield'),('reshoring','labor scarcity','AI/robotics capex'),('factory capex downturn','China weakness','execution'), 'Automation peers', {'growth':.17,'earnings':.14,'margin':.15,'efficiency':.14,'fcf':.19,'balance':.12,'inventory':.09}),
    'electrical': IndustryProfile('electrical','Electrical Equipment / Grid','Industrials','Grid/electrification model: orders, backlog, pricing, capacity expansion, data-center exposure and FCF.',('Orders','Backlog','Book_to_Bill','Data_Center_Exposure','Pricing','Capacity_Expansion'),('Forward P/E','EV/EBITDA','FCF yield'),('grid capex','data centers','electrification'),('capacity execution','copper/input costs','valuation'), 'Electrical-equipment peers', {'growth':.17,'earnings':.14,'margin':.15,'efficiency':.14,'fcf':.18,'balance':.12,'inventory':.10}),
    'machinery': IndustryProfile('machinery','Machinery','Industrials','Machinery cycle: orders, backlog, dealer inventory, pricing, aftermarket and incremental margins.',('Orders','Backlog','Dealer_Inventory','Pricing','Aftermarket_Mix'),('Forward P/E','EV/EBITDA','FCF yield'),('nonresidential capex','commodity capex','infrastructure'),('cycle downturn','dealer destock','input inflation'), 'Machinery peers', {'growth':.13,'earnings':.15,'margin':.14,'efficiency':.15,'fcf':.19,'balance':.13,'inventory':.11}),
    'construction': IndustryProfile('construction','Engineering & Construction','Industrials','Project economics: backlog, awards, book-to-bill, margin quality, working capital and project risk.',('Backlog','Awards','Book_to_Bill','Project_Margins','Working_Capital'),('Forward P/E','EV/EBITDA','FCF yield'),('infrastructure','data-center buildout','reshoring'),('project overruns','fixed-price risk','labor/material inflation'), 'E&C peers', {'growth':.15,'earnings':.14,'margin':.14,'efficiency':.13,'fcf':.18,'balance':.15,'liquidity':.11}),
    'transport': IndustryProfile('transport','Transportation / Logistics','Industrials','Transport economics: volumes, yield/pricing, utilization, fuel/labor costs and FCF through the cycle.',('Volumes','Yield_or_Pricing','Utilization','Fuel_Cost','Labor_Cost'),('Mid-cycle P/E','EV/EBITDA','FCF yield'),('freight cycle','pricing','capacity exits'),('recession','fuel/labor inflation','overcapacity'), 'Transport peers', {'growth':.11,'earnings':.13,'margin':.15,'efficiency':.14,'fcf':.20,'balance':.16,'liquidity':.11}),
    'airline': IndustryProfile('airline','Airlines','Industrials','Airline unit economics: RASM, CASM ex-fuel, capacity, load factor, premium mix and leverage.',('RASM','CASM','Load_Factor','Capacity','Fuel_Cost','Net_Debt'),('EV/EBITDAR','mid-cycle P/E','FCF yield'),('pricing','premium travel','capacity discipline'),('fuel','labor','overcapacity','recession','balance sheet'), 'Airline peers', {'growth':.10,'earnings':.12,'margin':.16,'efficiency':.11,'fcf':.17,'balance':.23,'liquidity':.11}),
    'waste': IndustryProfile('waste','Waste / Environmental Services','Industrials','Defensive route-density economics: price, volume, landfill assets, margins and FCF.',('Price_Growth','Volume_Growth','Landfill_Mix','EBITDA_Margin','FCF_Conversion'),('Forward P/E','EV/EBITDA','FCF yield'),('pricing','M&A','recycling recovery'),('valuation','fuel/labor','regulation'), 'Waste peers', {'growth':.12,'earnings':.13,'margin':.18,'efficiency':.16,'fcf':.21,'balance':.12,'liquidity':.08}),

    'copper_miner': IndustryProfile('copper_miner','Copper Mining','Materials','Copper miner: realized copper price, production, grade, cash cost/AISC, reserves, capex and jurisdiction.',('Copper_Production','Realized_Price','Grade','AISC','Reserves','Growth_Capex'),('P/NAV','EV/EBITDA','FCF yield','EV/reserves'),('copper price','mine expansions','grade/recovery'),('commodity downside','cost inflation','jurisdiction','project execution'), 'Copper-mining peers', {'growth':.08,'earnings':.10,'margin':.16,'efficiency':.13,'fcf':.22,'balance':.18,'inventory':.13}),
    'gold_miner': IndustryProfile('gold_miner','Gold Mining','Materials','Gold miner: realized gold price, production, AISC, reserve life, capex and jurisdiction.',('Gold_Production','Realized_Price','AISC','Reserves','Reserve_Life','Growth_Capex'),('P/NAV','EV/EBITDA','FCF yield','EV/reserves'),('gold price','grade','mine ramps'),('commodity downside','AISC inflation','jurisdiction'), 'Gold-mining peers', {'growth':.07,'earnings':.10,'margin':.16,'efficiency':.13,'fcf':.22,'balance':.19,'inventory':.13}),
    'steel': IndustryProfile('steel','Steel','Materials','Steel cycle: spreads, utilization, shipments, raw-material costs, capacity and capital returns.',('Steel_Spreads','Utilization','Shipments','Raw_Material_Cost','Capacity'),('Mid-cycle EV/EBITDA','P/B','FCF yield'),('steel prices','infrastructure','trade policy'),('overcapacity','recession','raw-material inflation'), 'Steel peers', {'growth':.08,'earnings':.10,'margin':.17,'efficiency':.14,'fcf':.21,'balance':.17,'inventory':.13}),
    'chemicals': IndustryProfile('chemicals','Chemicals','Materials','Chemical cycle: volumes, price/cost spread, utilization, feedstocks and capacity discipline.',('Volumes','Price_Cost','Utilization','Feedstock_Cost','Capacity'),('Mid-cycle EV/EBITDA','P/E','FCF yield'),('destocking end','housing/industrial recovery','capacity closures'),('overcapacity','feedstock inflation','China weakness'), 'Chemical peers', {'growth':.09,'earnings':.12,'margin':.16,'efficiency':.14,'fcf':.20,'balance':.16,'inventory':.13}),
    'materials_general': IndustryProfile('materials_general','Materials / Mining','Materials','Cyclical materials economics: price, volume, unit cost, capacity, capex and balance sheet.',('Realized_Price','Production','Unit_Cost','Capacity','Capex','Reserves'),('Mid-cycle EV/EBITDA','FCF yield','P/NAV where asset-based'),('commodity/price cycle','capacity','project ramps'),('commodity downside','cost inflation','project/jurisdiction'), 'Commodity-exposure peers', {'growth':.09,'earnings':.11,'margin':.16,'efficiency':.14,'fcf':.21,'balance':.17,'inventory':.12}),

    'retail': IndustryProfile('retail','Retail','Consumer Discretionary','Retail economics: comps, traffic/ticket, inventory, gross margin, store productivity and FCF.',('Comparable_Sales','Traffic','Ticket','Inventory_Turns','Store_Productivity','Gross_Margin'),('Forward P/E','EV/EBITDA','FCF yield'),('comps','traffic','inventory normalization'),('consumer slowdown','promotions','inventory','shrink'), 'Retail peers', {'growth':.14,'earnings':.14,'margin':.14,'efficiency':.14,'fcf':.19,'balance':.13,'inventory':.12}),
    'restaurant': IndustryProfile('restaurant','Restaurants','Consumer Discretionary','Restaurant economics: same-store sales, traffic, ticket, unit growth, restaurant margin and franchise mix.',('Comparable_Sales','Traffic','Ticket','Unit_Growth','Restaurant_Margin','Franchise_Mix'),('Forward P/E','EV/EBITDA','FCF yield'),('traffic','menu pricing','unit openings'),('consumer trade-down','labor/food inflation','valuation'), 'Restaurant peers', {'growth':.16,'earnings':.14,'margin':.14,'efficiency':.14,'fcf':.18,'balance':.13,'inventory':.11}),
    'auto': IndustryProfile('auto','Automobiles','Consumer Discretionary','Auto economics: units, ASP/mix, incentives, inventory, automotive margin, FCF and finance credit.',('Unit_Volume','Pricing_Mix','Incentives','Inventory','EBIT_Margin','Captive_Finance_Credit'),('EV/EBITDA','P/E','FCF yield'),('deliveries','new models','pricing/incentives'),('price war','inventory','rates','execution'), 'Auto OEM peers', {'growth':.14,'earnings':.13,'margin':.15,'efficiency':.13,'fcf':.18,'balance':.14,'inventory':.13}),
    'homebuilder': IndustryProfile('homebuilder','Homebuilders','Consumer Discretionary','Builder economics: orders, backlog, cancellations, community count, incentives, gross margin and land.',('Orders','Backlog','Cancellations','Community_Count','Incentives','Land_Position'),('P/E','P/B','FCF yield'),('mortgage rates','orders','community growth'),('rates','affordability','incentives','land impairment'), 'Homebuilder peers', {'growth':.13,'earnings':.14,'margin':.15,'efficiency':.15,'fcf':.17,'balance':.14,'inventory':.12}),
    'travel': IndustryProfile('travel','Travel / Lodging / Leisure','Consumer Discretionary','Travel economics: bookings, ADR/rates, occupancy, RevPAR or take rate, loyalty and FCF.',('Bookings','ADR','Occupancy','RevPAR','Take_Rate','Loyalty'),('EV/EBITDA','Forward P/E','FCF yield'),('travel demand','pricing','international mix'),('recession','capacity','fuel/geopolitics'), 'Travel/leisure peers', {'growth':.15,'earnings':.14,'margin':.15,'efficiency':.14,'fcf':.19,'balance':.14,'liquidity':.09}),
    'luxury_apparel': IndustryProfile('luxury_apparel','Apparel / Luxury','Consumer Discretionary','Brand economics: organic sales, regional mix, full-price sell-through, gross margin, inventory and brand heat.',('Organic_Sales','Regional_Mix','Full_Price_Sell_Through','Gross_Margin','Inventory_Turns'),('Forward P/E','EV/EBITDA','FCF yield'),('brand momentum','China/US demand','product cycle'),('fashion risk','promotions','China slowdown','FX'), 'Brand/apparel peers', {'growth':.15,'earnings':.14,'margin':.17,'efficiency':.15,'fcf':.18,'balance':.11,'inventory':.10}),
    'staples': IndustryProfile('staples','Consumer Staples','Consumer Staples','Defensive consumer model: organic volume/price mix, market share, gross margin, cash conversion and leverage.',('Organic_Sales','Volume','Price_Mix','Market_Share','Gross_Margin'),('Forward P/E','EV/EBITDA','FCF yield','dividend yield'),('pricing/volume','input deflation','market share'),('private label','volume elasticity','FX/input costs'), 'Staples peers', {'growth':.10,'earnings':.13,'margin':.16,'efficiency':.15,'fcf':.22,'balance':.14,'inventory':.10}),

    'telecom': IndustryProfile('telecom','Telecom','Communication Services','Telecom economics: subscribers/net adds, ARPU, churn, capex intensity, spectrum/debt and FCF.',('Subscribers','Net_Adds','ARPU','Churn','Capex_Intensity'),('EV/EBITDA','FCF yield','dividend yield'),('pricing','churn','capex normalization'),('competition','spectrum/debt','pricing regulation'), 'Telecom peers', {'growth':.09,'earnings':.11,'margin':.18,'efficiency':.14,'fcf':.23,'balance':.18,'liquidity':.07}),
    'streaming_media': IndustryProfile('streaming_media','Streaming / Media','Communication Services','Media economics: subscribers/users, ARPU, engagement, ad monetization, content spend and FCF.',('Subscribers_or_Users','ARPU','Engagement','Ad_Monetization','Content_Spend'),('Forward P/E','EV/EBITDA','FCF yield'),('ad tier','pricing','engagement','content slate'),('content costs','churn','competition','ad cycle'), 'Media/streaming peers', {'growth':.16,'earnings':.13,'margin':.16,'efficiency':.14,'fcf':.19,'balance':.12,'liquidity':.10}),
    'internet_platform': IndustryProfile('internet_platform','Internet / Digital Platform','Communication Services','Platform economics: users/engagement, monetization, ad pricing, cloud/AI capex and FCF.',('Users','Engagement','ARPU_or_Monetization','Ad_Pricing','AI_Capex','FCF'),('Forward P/E','EV/EBITDA','FCF yield'),('AI monetization','ad recovery','engagement'),('regulation','AI capex returns','competition'), 'Internet-platform peers', {'growth':.18,'earnings':.14,'margin':.17,'efficiency':.15,'fcf':.20,'balance':.09,'liquidity':.07}),

    'regulated_utility': IndustryProfile('regulated_utility','Regulated Utility','Utilities','Regulated model: rate-base growth, allowed ROE, jurisdiction, capex funding, leverage and dividend coverage.',('Rate_Base_Growth','Allowed_ROE','Regulatory_Jurisdiction','Capex_Funding','Dividend_Coverage'),('P/E vs growth','EV/EBITDA','dividend yield'),('rate cases','load/data-center growth','falling rates'),('rates','regulatory disallowance','capex financing','wildfire/weather'), 'Regulated-utility peers', {'growth':.09,'earnings':.15,'margin':.12,'efficiency':.12,'fcf':.12,'balance':.27,'liquidity':.13}),
    'renewable_utility': IndustryProfile('renewable_utility','Renewable / Power Developer','Utilities','Power-development model: contracted backlog, project returns, funding, generation growth and power prices.',('Project_Backlog','Contracted_Capacity','Project_IRR','Generation_Growth','Funding_Cost'),('EV/EBITDA','P/CF','NAV'),('power demand','data centers','project awards','rates'),('financing costs','project delays','merchant power prices'), 'Power-developer peers', {'growth':.15,'earnings':.11,'margin':.13,'efficiency':.12,'fcf':.12,'balance':.27,'liquidity':.10}),

    'generic': IndustryProfile('generic','General Equity','Other','General business analysis: durable growth, margins, cash generation, capital efficiency, balance sheet and valuation.',('Revenue_Growth','Earnings_Growth','Margins','ROIC','FCF','Balance_Sheet'),('Forward P/E','EV/EBITDA','FCF yield'),('earnings','product/market catalysts'),('competition','cycle','balance sheet','valuation'), 'Same-industry peers', {'growth':.15,'earnings':.15,'margin':.15,'efficiency':.15,'fcf':.20,'balance':.12,'liquidity':.08}),
}


def classify_equity_subindustry(sector: str='', industry: str='', ticker: str='') -> IndustryProfile:
    s=str(sector or '').lower(); i=str(industry or '').lower(); t=str(ticker or '').upper()
    text=f'{s} {i}'

    # Explicit ticker disambiguation for common business-model edge cases.
    ticker_map={
        'NVDA':'ai_accelerators','AMD':'ai_accelerators','MU':'memory','TSM':'foundry','ASML':'semi_equipment','AMAT':'semi_equipment','LRCX':'semi_equipment','KLAC':'semi_equipment',
        'AVGO':'connectivity_semis','MRVL':'connectivity_semis','SNPS':'eda_ip','CDNS':'eda_ip',
        'V':'payments','MA':'payments','AXP':'consumer_finance','COIN':'exchange','CME':'exchange','ICE':'exchange','NDAQ':'exchange',
        'EQIX':'data_center_reit','DLR':'data_center_reit','PLD':'industrial_reit','AMT':'tower_reit','CCI':'tower_reit',
        'XOM':'integrated_oil','CVX':'integrated_oil','COP':'ep','EOG':'ep','OXY':'ep','SLB':'oil_services','HAL':'oil_services','KMI':'midstream','WMB':'midstream','LNG':'lng',
        'LLY':'pharma','NVO':'pharma','PFE':'pharma','MRK':'pharma','ABBV':'pharma','ISRG':'medtech','UNH':'managed_care','HCA':'hospital','TMO':'life_science_tools','DHR':'life_science_tools',
        'LMT':'aerospace_defense','RTX':'aerospace_defense','NOC':'aerospace_defense','GD':'aerospace_defense','TER':'automation','ROK':'automation','ETN':'electrical','GEV':'electrical','CAT':'machinery','DE':'machinery','STRL':'construction','WM':'waste','RSG':'waste',
        'FCX':'copper_miner','SCCO':'copper_miner','NEM':'gold_miner','GOLD':'gold_miner',
        'TSLA':'auto','GM':'auto','F':'auto','PHM':'homebuilder','DHI':'homebuilder','LEN':'homebuilder','CAVA':'restaurant','MCD':'restaurant','SBUX':'restaurant',
        'META':'internet_platform','GOOGL':'internet_platform','GOOG':'internet_platform','NFLX':'streaming_media','TMUS':'telecom','T':'telecom','VZ':'telecom',
        'NEE':'renewable_utility','VST':'renewable_utility','CEG':'renewable_utility',
    }
    if t in ticker_map: return PROFILES[ticker_map[t]]

    rules=[
        (('semiconductor memory','memory'), 'memory'),
        (('semiconductor equipment','semiconductor equipment & materials'), 'semi_equipment'),
        (('semiconductor foundry','foundry'), 'foundry'),
        (('analog semiconductor','analog & mixed'), 'analog_semis'),
        (('semiconductor','semiconductors'), 'connectivity_semis'),
        (('electronic design automation','semiconductor ip'), 'eda_ip'),
        (('cybersecurity','security software'), 'cybersecurity'),
        (('software - application','software—infrastructure','software - infrastructure','software'), 'saas'),
        (('information technology services','it services','consulting services'), 'it_services'),
        (('computer hardware','consumer electronics','communication equipment'), 'hardware'),
        (('regional bank','banks - regional'), 'regional_bank'),
        (('banks - diversified','diversified banks'), 'money_center_bank'),
        (('insurance','reinsurance'), 'insurance'),
        (('asset management','capital markets'), 'asset_manager'),
        (('financial data','stock exchange','exchange'), 'exchange'),
        (('credit services','consumer finance'), 'consumer_finance'),
        (('payment','transaction & payment'), 'payments'),
        (('reit - data center','data center reit'), 'data_center_reit'),
        (('reit - industrial','industrial reit'), 'industrial_reit'),
        (('reit - residential','apartment reit','residential reit'), 'residential_reit'),
        (('reit - retail','retail reit','shopping center reit'), 'retail_reit'),
        (('reit - healthcare','healthcare reit'), 'healthcare_reit'),
        (('reit - specialty','tower reit'), 'tower_reit'),
        (('reit','real estate investment trust'), 'reit_general'),
        (('oil & gas e&p','exploration & production','oil and gas exploration'), 'ep'),
        (('oil & gas integrated','integrated oil'), 'integrated_oil'),
        (('oil & gas equipment','oilfield services','oil & gas services'), 'oil_services'),
        (('oil & gas midstream','midstream','pipeline'), 'midstream'),
        (('oil & gas refining','refining'), 'refining'),
        (('lng','liquefied natural gas'), 'lng'),
        (('biotechnology','biotech'), 'biotech'),
        (('drug manufacturers','pharmaceutical'), 'pharma'),
        (('medical devices','medical instruments','medtech'), 'medtech'),
        (('healthcare plans','managed care'), 'managed_care'),
        (('medical care facilities','hospital'), 'hospital'),
        (('diagnostics & research','life science tools'), 'life_science_tools'),
        (('aerospace & defense','aerospace and defense'), 'aerospace_defense'),
        (('specialty industrial machinery','automation','robotics'), 'automation'),
        (('electrical equipment','electrical & electronic'), 'electrical'),
        (('farm & heavy construction machinery','machinery'), 'machinery'),
        (('engineering & construction','construction'), 'construction'),
        (('trucking','railroads','integrated freight','logistics','transportation'), 'transport'),
        (('airlines','airline'), 'airline'),
        (('waste management','environmental services'), 'waste'),
        (('copper','copper mining'), 'copper_miner'),
        (('gold','gold mining'), 'gold_miner'),
        (('steel','steel producers'), 'steel'),
        (('chemicals','specialty chemicals'), 'chemicals'),
        (('mining','metals','materials'), 'materials_general'),
        (('restaurants','restaurant'), 'restaurant'),
        (('auto manufacturers','automobile','auto & truck'), 'auto'),
        (('residential construction','homebuilder'), 'homebuilder'),
        (('travel services','lodging','resorts','leisure'), 'travel'),
        (('apparel','luxury goods','footwear'), 'luxury_apparel'),
        (('retail','specialty retail','discount stores','department stores'), 'retail'),
        (('telecom','telecommunication'), 'telecom'),
        (('entertainment','broadcasting','media','streaming'), 'streaming_media'),
        (('internet content','internet retail','interactive media'), 'internet_platform'),
        (('regulated electric','utilities - regulated','regulated utility'), 'regulated_utility'),
        (('renewable','independent power','utilities - renewable'), 'renewable_utility'),
    ]
    for tokens,key in rules:
        if any(tok in text for tok in tokens): return PROFILES[key]
    if 'consumer staples' in s: return PROFILES['staples']
    return PROFILES['generic']


def professional_quality_score(f: dict, sector: str='', industry: str='', ticker: str='') -> dict:
    p=classify_equity_subindustry(sector,industry,ticker)
    vals={
        'growth':_score_growth(f.get('Revenue_Growth'), .08, .18),
        'earnings':_score_growth(f.get('Earnings_Growth'), .10, .22),
        'margin':_score_margin(f.get('Operating_Margin') if _present(f.get('Operating_Margin')) else f.get('Profit_Margin'), .10, .22),
        'efficiency':_score_roic(f.get('ROIC')) if _present(f.get('ROIC')) else _score_roe(f.get('ROE')),
        'fcf':_score_fcf_yield(f),
        'balance':_score_debt_equity(f.get('Debt_Equity'), tolerant=p.sector in {'Utilities','Real Estate'}),
        'liquidity':_score_liquidity(f),
        'sbc':_score_sbc(f),
        'inventory':_score_inventory(f),
    }
    score,cov,used=_weighted(vals,p.weights)
    return {
        'Quality_Score':score,
        'Fundamental_Coverage_%':cov,
        'Quality_Pillars':vals,
        'Quality_Pillars_Used':used,
        'Equity_Model_Key':p.key,
        'Equity_Model':p.label,
        'Peer_Group':p.peer_basis,
        'Professional_Framework':p.description,
        'Critical_KPIs':list(p.kpis),
        'Preferred_Valuation_Methods':list(p.valuation),
        'Key_Catalysts':list(p.catalysts),
        'Key_Risks':list(p.risks),
    }


def _valuation_metric_scores(f:dict, profile:IndustryProfile):
    pe=_num(f.get('Forward_PE')); ev=_num(f.get('EV_EBITDA')); pb=_num(f.get('Price_to_Book')); ps=_num(f.get('Price_to_Sales')); evs=_num(f.get('EV_Revenue'))
    fy=_num(f.get('FCF_Yield'))
    if pd.isna(fy):
        fcf=_num(f.get('FCF')); mc=_num(f.get('Market_Cap')); fy=fcf/mc if pd.notna(fcf) and pd.notna(mc) and mc else np.nan
    elif abs(fy)>1.5: fy/=100
    growth=max(_num(f.get('Revenue_Growth')) if pd.notna(_num(f.get('Revenue_Growth'))) else 0, _num(f.get('Earnings_Growth')) if pd.notna(_num(f.get('Earnings_Growth'))) else 0)
    def pe_score(x):
        if pd.isna(x) or x<=0:return np.nan
        return 88 if x<=15 else 80 if x<=20 else 68 if x<=28 else 55 if x<=38 else 40 if x<=55 else 24
    def ev_score(x):
        if pd.isna(x) or x<=0:return np.nan
        return 88 if x<=9 else 78 if x<=13 else 66 if x<=18 else 52 if x<=25 else 34
    def pb_score(x):
        if pd.isna(x) or x<=0:return np.nan
        return 88 if x<=1.2 else 80 if x<=1.8 else 68 if x<=2.8 else 52 if x<=4.5 else 32
    def sales_score(x):
        if pd.isna(x) or x<=0:return np.nan
        # Growth businesses can rationally support higher sales multiples.
        adj=1.4 if growth>=.25 else 1.2 if growth>=.15 else 1.0
        x=x/adj
        return 86 if x<=3 else 76 if x<=5 else 63 if x<=8 else 48 if x<=12 else 30
    vals={'Forward_PE':pe_score(pe),'EV_EBITDA':ev_score(ev),'Price_to_Book':pb_score(pb),'Price_to_Sales':sales_score(ps),'EV_Revenue':sales_score(evs),'FCF_Yield':_score_fcf_yield(f)}
    key=profile.key
    if key in {'money_center_bank','regional_bank','insurance','consumer_finance','homebuilder'}: w={'Price_to_Book':.45,'Forward_PE':.35,'FCF_Yield':.20}
    elif key in {'saas','cybersecurity','eda_ip'}: w={'EV_Revenue':.35,'Price_to_Sales':.20,'FCF_Yield':.30,'Forward_PE':.15}
    elif key in {'biotech'}: w={'FCF_Yield':.20,'Price_to_Book':.20}  # intentionally low coverage; pipeline/rNPV should dominate.
    elif key in {'reit_general','data_center_reit','industrial_reit','residential_reit','retail_reit','healthcare_reit','tower_reit'}: w={'EV_EBITDA':.40,'FCF_Yield':.35,'Price_to_Book':.25}
    elif key in {'ep','integrated_oil','oil_services','midstream','refining','lng','copper_miner','gold_miner','steel','chemicals','materials_general'}: w={'EV_EBITDA':.42,'FCF_Yield':.38,'Forward_PE':.20}
    else: w={'Forward_PE':.34,'EV_EBITDA':.28,'FCF_Yield':.28,'Price_to_Sales':.10}
    score,cov,used=_weighted(vals,w)
    return score,cov,used,vals


def professional_valuation_score(f: dict, sector: str='', industry: str='', ticker: str='') -> dict:
    p=classify_equity_subindustry(sector,industry,ticker)
    score,cov,used,components=_valuation_metric_scores(f,p)
    note='Valuation score is a free-data proxy. Prefer peer-relative and historical ranges; specialist asset-based methods remain primary when listed.'
    if p.key=='biotech':
        note='Biotech accounting multiples are secondary; professional valuation should be cash-adjusted rNPV by asset/stage. Low valuation coverage is intentional.'
        # Without an observed rNPV/pipeline valuation, generic balance-sheet multiples
        # cannot represent full biotech valuation coverage.
        if not _present(f.get('rNPV')):
            cov=min(float(cov),40.0)
    return {'Valuation_Score':score,'Valuation_Coverage_%':cov,'Valuation_Components':components,'Valuation_Components_Used':used,'Preferred_Valuation_Methods':list(p.valuation),'Valuation_Note':note,'Equity_Model_Key':p.key,'Equity_Model':p.label}


def professional_equity_snapshot(f: dict, sector: str='', industry: str='', ticker: str='') -> dict:
    q=professional_quality_score(f,sector,industry,ticker)
    v=professional_valuation_score(f,sector,industry,ticker)
    out={**q, **{k:x for k,x in v.items() if k not in {'Equity_Model_Key','Equity_Model','Preferred_Valuation_Methods'}}}
    missing=[k for k in q['Critical_KPIs'] if not _present(f.get(k))]
    out['Observed_Specialist_KPIs']=[k for k in q['Critical_KPIs'] if _present(f.get(k))]
    out['Missing_Specialist_KPIs']=missing
    out['Specialist_KPI_Coverage_%']=round(100*(len(q['Critical_KPIs'])-len(missing))/len(q['Critical_KPIs']),1) if q['Critical_KPIs'] else 100.0
    return out


def add_professional_peer_valuation_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Peer-relative valuation using the model's preferred observable multiples.

    Works cross-sectionally on the screener. Lower positive multiple = better value;
    higher FCF yield = better value. Requires at least 3 valid peers per model.
    """
    out=df.copy()
    if 'Equity_Model_Key' not in out.columns:
        out['Equity_Model_Key']=[classify_equity_subindustry(r.get('Sector',''),r.get('Industry',''),r.get('Ticker','')).key for _,r in out.iterrows()]
    metrics=[('Forward_PE',False),('EV_EBITDA',False),('Price_to_Book',False),('Price_to_Sales',False),('FCF_Yield',True)]
    percentile_cols=[]
    for metric,higher_better in metrics:
        if metric not in out.columns: continue
        col=f'{metric}_Peer_Percentile'; out[col]=np.nan; percentile_cols.append(col)
        for _,g in out.groupby('Equity_Model_Key',dropna=False):
            vals=pd.to_numeric(g[metric],errors='coerce')
            if not higher_better: vals=vals.where(vals>0)
            if vals.notna().sum()>=3:
                pct=vals.rank(pct=True,method='average')*100
                if not higher_better: pct=100-pct
                out.loc[g.index,col]=pct.round(0)
    if percentile_cols:
        out['Peer_Valuation_Score']=out[percentile_cols].mean(axis=1,skipna=True).round(0)
        # Blend peer-relative evidence into standalone valuation, but never replace it blindly.
        if 'Valuation_Score' not in out: out['Valuation_Score']=np.nan
        blend=[]
        for _,r in out.iterrows():
            s=_num(r.get('Valuation_Score')); p=_num(r.get('Peer_Valuation_Score'))
            blend.append(round(.55*s+.45*p) if pd.notna(s) and pd.notna(p) else p if pd.notna(p) else s)
        out['Valuation_Score']=blend
    return out
