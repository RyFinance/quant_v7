# SEC insider purchases (Forms 3/4/5): pre-registration

Registered 2026-09-19, before any SEC insider filing was downloaded, parsed or counted. SEC answered
every automated request (2026-09-18, and again on 2026-09-19) with HTTP 403. That is its block for
User-Agents without a contact e-mail, and none will be invented. So not a single event, coverage
statistic or return exists yet. Once the ZIPs are obtained, the coverage step
(`python -m research.insider.sec_data coverage`) runs before the development evaluation. Any change it
forces must be registered as an amendment before any return is computed.

Code: `research/insider/{sec_data,signals,prices,evaluate}.py`; tests: `tests/test_insider.py`.

## Why this is a legitimate new test

Every price window from 2003 to 2026 has already been examined by this project. What is new is the
**information set**: 20 years of point-in-time SEC insider filings (DERA "Insider Transactions Data
Sets", quarterly from 2006 Q1). No quant_v7 experiment has used them. The LSE vault's
`insider_trades` rows start 2025-09/10 (checked 2026-09-18), so they are not usable here. The price
windows are not pristine, so a pass is evidence about the insider signal, not about the market
path. A pass still means a forward paper test from its own registration date, not capital.

## Data

- **Filings.** `data/sec_insider/raw/*_form345.zip`, from the links on the SEC index page. Tables
  used: SUBMISSION (ACCESSION_NUMBER, FILING_DATE, DOCUMENT_TYPE, ISSUERCIK, ISSUERTRADINGSYMBOL),
  REPORTINGOWNER (RPTOWNERCIK, RPTOWNER_RELATIONSHIP, RPTOWNER_TITLE) and NONDERIV_TRANS
  (TRANS_DATE, TRANS_CODE, TRANS_SHARES, TRANS_PRICEPERSHARE, TRANS_ACQUIRED_DISP_CD).
- **Transactions kept.** Original Form 4 only (DOCUMENT_TYPE `4`). Amendments (4/A) and annual
  Form 5 reports are excluded, to avoid double counting and stale reports. Only non-derivative
  open-market trades are kept:
  - `P` with acquired/disposed code `A` (purchase);
  - `S` with code `D` (sale).
  Shares and price must both be > 0. Value = shares × price per share.
  Data cleaning (fixed, not tuned): drop a trade if TRANS_DATE is after FILING_DATE, or more than
  365 days before it.
- **Insider roles.**
  - *Officer/director*: RPTOWNER_RELATIONSHIP contains "Director" or "Officer".
  - *C-suite*: an officer whose title matches CEO, "chief executive", CFO, "chief financial" or
    "president" (including "pres."). A "president" match does not count if the title also
    contains vice/EVP/SVP/VP.
  - Ten-percent owners who are neither officers nor directors are excluded from every signal. They
    are usually funds. They do count in the N3 trading history.
- **Issuer → ticker.** Each ISSUERCIK is mapped to the cleaned ISSUERTRADINGSYMBOL of its most recent
  filing. A ticker claimed by several CIKs (a recycled symbol) goes to the CIK that filed most
  recently. The other CIKs are left unmatched. This follows ticker changes through the CIK and
  keeps a recycled ticker from pulling another company's price history. The map uses every filing
  available, including those after the development window. It only links issuers to price
  histories and carries no signal or return information. Unmatched filings are counted and
  reported.
- **Prices.** yfinance official daily session bars (`auto_adjust=False, actions=True`) for every
  mapped ticker, from 2005-10-01. Uses:
  - *Returns*: dividend- and split-adjusted opens and closes. The adjusted open is
    open × adj_close / close.
  - *Filter*: the RAW price, i.e. split-adjusted close × the product of later split ratios. A split
    can only change later prices, so the filter never sees one early.
  - *Dollar volume*: split-adjusted close × split-adjusted volume, which equals raw dollar volume.
  LSE vault candles are not used. Tickers that yfinance does not serve are unmatched and counted.
- **Risk-free and market.** `research.options_signals.signals.french_daily()` (daily rf, mkt_rf).

## Candidates (four, and only four)

Each candidate produces **events**: (ticker, signal date = FILING_DATE). Only filings with
FILING_DATE ≤ the signal date are visible when an event is built.

1. **N1_cluster — cluster buying** (Lakonishok & Lee 2001; Jeng, Metrick & Zeckhauser 2003).
   An event fires for an issuer on a filing date d that carries an officer/director purchase, if two
   conditions hold. Over all officer/director purchases with FILING_DATE ≤ d and
   TRANS_DATE ≥ d − 30 calendar days:
   - at least 2 distinct owner CIKs are officers or directors; and
   - the total purchase value is ≥ $50,000.
2. **N2_csuite — C-suite purchases.** An event fires for an issuer on a filing date d if its C-suite
   officers' purchases filed that day sum to ≥ $25,000.
3. **N3_opportunistic — opportunistic purchases** (Cohen, Malloy & Pomorski 2012). Insiders are
   classified at the start of each calendar year Y, per (owner CIK, issuer CIK) pair. The inputs are
   open-market P/S trades by that owner in that issuer, in any role, with TRANS_DATE in Y−3, Y−2 or
   Y−1 and FILING_DATE ≤ 31 Dec of Y−1.
   - A pair with at least one trade in each of the three years is *routine* if one calendar month
     has a trade in all three years.
   - Otherwise it is *opportunistic*.
   - A pair without a trade in all three years is unclassified.

   An event fires on the filing date of any purchase by an opportunistic officer/director in year
   Y. There is no value floor, as in CMP. The data start in 2006, so N3 can first fire in 2009.
4. **N4_composite.** The equal-weight average of the N1, N2 and N3 sleeves' daily net returns. A
   sleeve with no positions sits in T-bills. The weights are fixed and never fitted.

## Timing and holding period

- Signal date = FILING_DATE. A Form 4 accepted as late as 22:00 ET still carries that day's
  filing date (Reg S-T 13(a)(4)). So entry is at the open of the first session **strictly after**
  the filing date.
- **Hold 63 trading days** (fixed now for all candidates, before any result): exit at the open of the
  63rd session after entry. A new event for a name already held restarts its 63-session clock.
  - *Why 63 rather than 21:*
    - Lakonishok & Lee find the purchase effect over the following 6–12 months, not only the first
      month.
    - Jeng, Metrick & Zeckhauser report that only about half of the 6-month abnormal return on
      insider purchases arrives in the first month.
    - At 15–40 bps per side on small names, a 21-day hold turns the book over about 12 times a
      year. That costs roughly 3.6–9.6%/yr, against 1.2–3.2%/yr for 63 days.
  - CMP measure one-month returns. The 63-day hold is a deliberate, stated departure for all
    candidates, including N3.

## Portfolio

- **Long book.** Equal weight across all active positions. Rebalance to 1/N at the open on any day
  the active set changes; otherwise weights drift. Marked to market daily at the official close.
  With no positions the book holds T-bills (French rf), so its excess return is 0.
- **Accounting** (exact, per session t):
  - the overnight gap open_t/close_{t−1} is applied to the drifted weights;
  - the open trade to the new targets is charged cost = Σ|Δw_j| × c_j;
  - then the intraday return close_t/open_t is applied;
  - cash earns rf_t.

  The reported return is the daily net return minus rf_t.
- **Missing bars.** Closes are carried forward. A missing open is replaced by the prior close. An
  event needs a real open on its entry day, otherwise it is skipped.
- **Hedged version** (reported, not gated). Whenever the book is invested, short the market at
  h_t = β̂_t × NAV, where β̂_t is the OLS slope of the book's daily excess return on mkt_rf. The
  estimate uses the last 126 invested sessions before t, needs at least 60 of them (otherwise 1.0),
  and is clipped to [0, 2]. Hedged excess = excess − h_t × mkt_rf_t − h_t × borrow/252 −
  |h_t − h_{t−1}| × 1 bp. Short proceeds earn rf.

## Universe filter (known at entry)

The filter is checked at session s = the last session on or before the signal date. Everything it
uses is known at the close of s, before the entry open:
- the raw close at s is ≥ $5; and
- ADV20, the mean dollar volume over the 20 sessions ending at s, is ≥ $2M. All 20 sessions must
  have bars.

## Costs

- **Per side, by liquidity tier.** The tier comes from ADV20 through the previous close, known
  before the trade:

  | ADV20 | Cost per side |
  |---|---|
  | > $50M | 5 bps |
  | $5M–$50M | 15 bps |
  | < $5M | 40 bps |

  A missing ADV is charged 40 bps.
- **Hedge.** 1 bp per side on changes in hedge notional, plus borrow of 0.25%/yr on the short.
- **Stress.** All of the above ×2.

## Control (same universe, same dates)

For each event, 20 random draws (fixed seeds) pick a ticker uniformly from those that pass the same
universe filter on the same signal date and have an open on the entry day. The pick enters and
exits on the event's own dates, through the same book, costs and rules.
- *Control Sharpe* = the median of the 20 draws' net Sharpes.
- *Paired test*: the daily difference between the candidate's net excess return and the mean of
  the 20 control draws' net excess returns. It uses a one-sided circular block bootstrap (21-day
  blocks, 5,000 draws) for mean ≤ 0.
- The N4 control composites draw r of each sleeve's control.

## Windows

- **Development:** signal dates 2006-01-01 → 2015-12-31. Returns run from the first session on which
  the candidate can trade (2006-01-03; 2009-01-02 for N3) to 2015-12-31. Positions still open are
  marked at the 2015-12-31 close. In code, filings and prices after 2015-12-31 cannot be loaded in
  development mode.
- **Validation:** signal dates 2016-01-01 → 2026-06-30. The book starts flat. It is locked in code
  until `research/insider/VALIDATION_UNLOCK.md` is registered with a matching sha256. It runs once,
  and only for candidates that pass the development gate.

## Gates

Statistics are computed on daily excess returns and annualised with √252, matching the PEAD
benchmark (excess Sharpe 0.70, daily mark-to-market, net, over T-bills).

- **Development gate** (per candidate, base costs, unhedged long book). Both must hold:
  - net excess Sharpe ≥ 0.5;
  - it beats the control: the mean daily difference against the control is > 0 **and** the net
    Sharpe is above the control Sharpe.

  If none passes, the experiment stops with a null result.
- **Validation gate** (per selected candidate). All must hold:
  - net excess Sharpe ≥ 0.75, and above 0.70;
  - stressed (×2 costs) mean net excess return > 0;
  - one-sided block-bootstrap p < 0.05/4 = 0.0125 (Bonferroni over the four registered
    candidates);
  - the paired test against the control, p < 0.0125.
- **Also reported, not gated:** gross Sharpe; the hedged Sharpe; a 95% block-bootstrap Sharpe
  interval with its `null_kind` against 0.70; Newey–West t (20 lags); deflated Sharpe (4 trials);
  CAGR; max drawdown; turnover; cost drag; mean positions; share of days invested; returns by
  year.
- A validation pass means a forward paper test on the LSE sim account, not capital. No threshold,
  window, holding period, filter, cost or role definition may change after results are seen. Any
  change is a new, separately registered experiment.

## Biases stated in advance

- **Survivorship.** Prices exist only for tickers listed today, so issuers that were delisted,
  acquired or went bankrupt between 2006 and 2026 are missing. Insider buying is common in
  distressed firms, some of which later failed, so this probably flatters the signal. The
  same-universe control has the same bias, so the paired test is the more reliable number. It is
  still not bias-free: the dead firms are missing from both sides, but at different rates.
- **Ticker matching.** Free-text ISSUERTRADINGSYMBOL values ("NONE", exchange prefixes, recycled
  symbols) lose some filings. The share lost is reported by year.

## Expectations stated in advance

The published effects are strongest in small, illiquid stocks and in pre-2000 samples, and have
decayed since publication. With the $5/$2M filter, filing-date entry and 2006+ data, the prior is a
long-book net excess Sharpe of about 0.3–0.7, mostly market beta, and a small control-adjusted
edge. Beating the 0.70 PEAD benchmark would be a surprise. An honest null is an acceptable outcome.
