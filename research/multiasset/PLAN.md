# Multi-asset edge search: protocol

Written 2026-09-18, **before any return from these sleeves was computed**. SHA-256 recorded in
`research/preregistrations.jsonl`.

## Goal and the honest arithmetic behind it

The user's target is an excess Sharpe of 2 and more than 10% a year. No single strategy in this
project has come close out of sample: the PEAD model scored 0.52 on 2004–2014 and failed its
pre-registered test, and every equity sleeve shares one universe, so blending them bought little
real diversification (effective independent bets 3.9 from 8 sleeves).

The one well-founded route to a high Sharpe is **combining several independent return streams**. With N sleeves of Sharpe *s* and average pairwise correlation ρ, the blend's Sharpe is
*s*·√(N / (1 + (N−1)ρ)). Five sleeves of 0.6 at ρ = 0.1 give about 1.1; reaching 2 needs roughly
ten such sleeves, or sleeves near 1.0. The expectation going in is **a Sharpe near 1, not 2**, and this
document commits to reporting whatever comes out.

## Data (all outside the US single-stock universe used so far)

`data/pull_multiasset.py`, manifest in `data/multiasset/manifest.json`:
ETFs across equity indices, bonds, commodities, currencies and REITs (yfinance, official closes,
total return); G10 FX spot and policy rates, 10-year government yields, ES/NQ 30-minute futures bars
and BTC/ETH (LSE vault); ^VIX, ^VIX3M, VIXY, SVXY and ^IRX (yfinance).

## Windows

| Window | Dates | Use |
|---|---|---|
| Development | data start → **2017-12-31** | build, debug and choose sleeves |
| Hold-out | **2018-01-01 → 2026-09-17** | touched once, after a separate pre-registration |

The loaders refuse any date after 2017-12-31 unless the hold-out pre-registration file exists and
its hash is registered. Every sleeve variant run in development is appended to
`reports/multiasset/dev_trials.jsonl`, so the number of tries is on record.

Known contamination, stated rather than hidden: the author of these rules has general knowledge
of how broad strategy families (trend following, carry, short volatility) fared after 2018. The
defence is that every sleeve uses **its original paper's parameters**, and the inclusion rule below
is mechanical.

## Candidate sleeves (parameters fixed from the literature, not tuned)

1. **Cross-asset time-series momentum.** Moskowitz, Ooi and Pedersen (2012). Sign of the trailing
   12-month excess return, position scaled to 40% annualized ex-ante volatility (EWMA, 60-day
   centre of mass), rebalanced monthly, averaged across the ETF universe.
2. **G10 FX carry.** Lustig and Verdelhan; Koijen, Moskowitz, Pedersen and Vrugt (2018). Monthly,
   long the three highest-policy-rate currencies and short the three lowest (USD included in the
   ranking); returns include the rate differential.
3. **Dollar carry.** Lustig, Roussanov and Verdelhan (2014). Long all foreign currencies against
   USD when their average policy rate exceeds the US rate, short otherwise.
4. **Global bond carry.** Koijen et al. (2018). Monthly, long the three 10-year bonds with the
   steepest 10-year-minus-policy-rate spread and short the three flattest, equal volatility
   weights, returns built from yields (duration approximation), FX-hedged.
5. **VIX futures basis.** Simon and Campasano (2014). Short VIX futures (−1× VIXY) whenever VIX is
   below VIX3M (contango), flat otherwise, judged at each close.
6. **Intraday market momentum.** Gao, Han, Li and Zhou (2018); Baltussen, Da, Lammers and Martens
   (2021). Take the sign of the return from the previous 16:00 ET close to 10:00 ET, trade that
   direction from 15:30 to 16:00 ET, and hold nothing overnight. Applied to ES and NQ at equal
   weight.
7. **Cross-sectional momentum across asset classes.** Asness, Moskowitz and Pedersen (2013).
   Within each ETF asset class, long the top third and short the bottom third by 12-month return
   skipping the latest month, monthly.

## Execution and costs (all sleeves)

- **Daily sleeves:** a position decided at close *t* earns returns from close *t+1* onward, which is
  a full day's implementation lag.
- **Intraday sleeve:** trades at the bar prices named above.
- **One-way costs:** 5 bps for ETFs, 1 bp for G10 spot FX, and for ES/NQ one tick of slippage plus
  $4.50 commission per round trip.
- **Borrow and financing:** 1% a year on short ETF notional, 3% on short VIXY. Positions are
  financed at the T-bill rate (^IRX), so sleeve returns are excess returns.

## Development-phase inclusion rule (fixed now)

A sleeve enters the combined portfolio only if **both** of these hold on its development window,
net of costs:

- excess Sharpe **≥ 0.30**
- at least **three** years of development history

## Combination rule (fixed now)

Equal risk. Each sleeve is scaled to 10% annualized volatility using its trailing 252-day realized
volatility (lagged one day), and the sleeves are averaged. The combined book is then scaled to
**10% annualized volatility** the same way, capped at 4× gross leverage per sleeve. No optimized
weights.

## What comes next

After development, a separate hold-out pre-registration names the included sleeves, the exact
code hash and the pass criteria, and is hashed before the hold-out is loaded once.
