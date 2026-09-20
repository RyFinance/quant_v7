"""Mechanism (M1-M7) and data-source tags for the 212 OSAP predictors.

Tags are assigned by rule from Chen-Zimmermann's own categories (Cat.Data, Cat.Economic),
then a short list of hand overrides where the rule is clearly wrong. Tags use only
information available at publication (the paper's category/economic story), not returns.

Taxonomy (research/EDGE_GRAVEYARD_PLAN.md, Phase 2):
  M1 first to a new dataset   M2 forced/non-informational flows   M3 limits to arbitrage
  M4 slow reaction            M5 economic links diffuse slowly    M6 risk premia
  M7 market-structure change (no OSAP predictor is primarily M7; the category stays empty)
"""
import pandas as pd

# Cat.Economic -> default mechanism
ECON_TO_MECH = {
    # M3 limits to arbitrage / lottery / illiquidity / short-sale constraints
    "short sale constraints": "M3", "liquidity": "M3", "volatility": "M3", "size": "M3",
    "turnover": "M3", "volume": "M3",
    # M4 slow reaction / behavioural under-reaction or mispricing
    "momentum": "M4", "earnings event": "M4", "earnings growth": "M4", "earnings forecast": "M4",
    "recommendation": "M4", "accruals": "M4", "composite accounting": "M4", "external financing": "M4",
    "short-term reversal": "M3",  # liquidity provision; lives where arbitrage is costly
    "sales growth": "M4", "payout indicator": "M4", "info proxy": "M4",
    # M5 economic links
    "lead lag": "M5",
    # M6 risk premia / q-theory
    "valuation": "M6", "risk": "M6", "default risk": "M6", "leverage": "M6", "investment": "M6",
    "investment alt": "M6", "investment growth": "M6", "profitability": "M6", "profitability alt": "M6",
    "long term reversal": "M6", "cash flow risk": "M6", "market risk": "M6", "asset composition": "M6",
    "R&D": "M6",
    # M1 by construction: new data
    "optionrisk": "M1", "informed trading": "M1", "ownership": "M1",
    "other": None,  # resolved by data source / overrides below
}

DATA_SOURCE = {"Price": "price", "Trading": "volume", "Accounting": "accounting", "Analyst": "analyst",
               "Options": "options", "13F": "flows_holdings", "Event": "event", "Other": "alt_other"}

# Hand overrides: (mechanism, reason)
OVERRIDES = {
    # M2 forced / recurring non-informational flows
    "Spinoff": ("M2", "index/mandate-driven selling of spun-off shares"),
    "ExchSwitch": ("M2", "listing change shifts investor base/index membership"),
    "DivSeason": ("M2", "predictable dividend-month demand"),
    "MomSeason": ("M2", "Heston-Sadka seasonality, attributed to recurring flows"),
    "MomSeason06YrPlus": ("M2", "seasonality"), "MomSeason11YrPlus": ("M2", "seasonality"),
    "MomSeason16YrPlus": ("M2", "seasonality"), "MomSeasonShort": ("M2", "seasonality"),
    "MomOffSeason": ("M2", "seasonality complement"), "MomOffSeason06YrPlus": ("M2", "seasonality complement"),
    "MomOffSeason11YrPlus": ("M2", "seasonality complement"), "MomOffSeason16YrPlus": ("M2", "seasonality complement"),
    "IndIPO": ("M4", "IPO underperformance (issuer timing)"), "AgeIPO": ("M4", "IPO underperformance"),
    "RDIPO": ("M4", "IPO underperformance"),
    "DelBreadth": ("M3", "breadth of ownership = short-sale constraints (Chen-Hong-Stein)"),
    "Activism1": ("M1", "13F/governance data"), "Activism2": ("M1", "13F/governance data"),
    "Governance": ("M1", "G-index hand-collected dataset"),
    "sinAlgo": ("M3", "norm-constrained investors avoid sin stocks"),
    "Herf": ("M6", "industry concentration risk"), "HerfAsset": ("M6", "industry concentration"),
    "HerfBE": ("M6", "industry concentration"),
    "hire": ("M6", "hiring rate: investment-based"),
    "CitationsRD": ("M1", "patent citation data"), "PatentsRD": ("M1", "patent data"),
    "iomom_cust": ("M5", "customer momentum"), "iomom_supp": ("M5", "supplier momentum"),
    "BetaFP": ("M3", "betting-against-beta: leverage constraints"),
    "Beta": ("M6", "CAPM beta"),
    "Price": ("M3", "low-price stocks"), "FirmAge": ("M3", "young firms: info/arbitrage limits"),
    "ChTax": ("M4", "tax expense surprise"), "Tax": ("M4", "tax-book gap as earnings quality"),
    "NetDebtPrice": ("M6", "leverage/valuation"), "OPLeverage": ("M6", "operating leverage"),
    "RDAbility": ("M4", "R&D ability underpriced"),
    "EarningsSurprise": ("M4", "PEAD"), "AnnouncementReturn": ("M4", "earnings-announcement drift"),
    "OptionVolume1": ("M1", "option volume data"), "OptionVolume2": ("M1", "option volume data"),
    "CPVolSpread": ("M1", "options"), "RIVolSpread": ("M1", "options"), "SmileSlope": ("M1", "options"),
    "skew1": ("M1", "options"), "dVolCall": ("M1", "options"), "dVolPut": ("M1", "options"),
    "dCPVolSpread": ("M1", "options"),
    "DivYieldST": ("M6", "predicted dividend yield"),
    "ShortInterest": ("M3", "short-sale constraints"),
    "MomOffSeason": ("M2", "seasonality complement"),
    "ProbInformedTrading": ("M3", "information asymmetry / liquidity"),
    "CredRatDG": ("M4", "slow reaction to rating downgrades"),
}


def tag(doc: pd.DataFrame) -> pd.DataFrame:
    d = doc.copy()
    mech, why = [], []
    for _, r in d.iterrows():
        if r["Acronym"] in OVERRIDES:
            m, w = OVERRIDES[r["Acronym"]]
        else:
            m = ECON_TO_MECH.get(r["Cat.Economic"])
            w = f"rule: Cat.Economic={r['Cat.Economic']}"
            if m is None:
                m = {"Options": "M1", "13F": "M1", "Other": "M1", "Price": "M4", "Event": "M4"}.get(r["Cat.Data"], "M4")
                w = f"rule: other/{r['Cat.Data']}"
        mech.append(m); why.append(w)
    d["mech"] = mech
    d["mech_reason"] = why
    d["data_src"] = d["Cat.Data"].map(DATA_SOURCE)
    return d
