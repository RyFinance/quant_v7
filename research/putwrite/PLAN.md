# Short-dated SPY put writing: pre-registration

Written 2026-09-18 before any SPY/QQQ/IWM option price series was pulled for this purpose. The
only SPY option data seen in this project is one probe day (2015-01-05 tick export), inspected for
field layout (expiries, strike range, conditions), not for prices or returns.

## Hypothesis and source

Short-dated equity-index puts are priced above their expected payoff (a variance/crash risk
premium: Bondarenko 2014; Carr & Wu 2009; Andersen, Fusari & Todorov on weekly options). Inspired by
Wysocki (arXiv 2608.24786), whose ML result I do not trust, this tests the premium with a fixed rule.
The multi-asset hold-out showed that short volatility can blow up (VIX-basis sleeve −86%), so the
tail is part of the gate.

## Data

- `research/putwrite/pull.py` pulls LSE vault option exports (`timeframe=1d`, per-contract daily
  OHLCV of OPRA trades) for SPY, QQQ and IWM, 2014-06-01..2026-09-17, after the stock-options pull
  finishes. Spot is from yfinance `auto_adjust=False` raw close (these ETFs have no splits in the
  window). Split handling from `research/options_signals` is not needed.
- Trading calendar = dates with a SPY official bar.

## Rule (fixed)

On each trading day t, if the underlying has a put expiring on the next trading day t+1:
1. σ_t = 21-day close-to-close realised volatility of the underlying, annualised with √252, known at t.
2. Target strike K* = S_t · exp(−1.0 · σ_t · √(1/252)) (about a 16-delta put).
3. Among puts with that expiry that traded on t (volume ≥ 1), take the strike nearest K* (ties → the
   lower strike). Skip the day if its close is below $0.05.
4. Sell at the day-t close price minus costs. Hold to t+1. The position is closed at the underlying's
   t+1 official close at intrinsic value max(K − S_{t+1}, 0), plus costs if it is in the money.
5. Size: short notional K × 100 × contracts = 1.0 × NAV (cash-secured; no leverage). Daily excess
   return = (premium − payoff − costs) / K. Collateral earns RF and is excluded from excess return.

## Candidates (three)

- **P1_spy**: the rule on SPY, every eligible day.
- **P2_spy_vrp**: P1, but trade only when the chosen put's Black–Scholes implied volatility (from its
  close, trading-time T = 1/252 per trading day to expiry, French RF, no dividend adjustment) is above
  σ_t, i.e. when the premium is positive ex ante.
- **P3_etf3**: the P1 rule on SPY, QQQ and IWM, one-third of NAV each, on days each is eligible.

## Costs

- Base: half-spread $0.01/share (SPY, QQQ), $0.02 (IWM) on the sale; the same again on the buy-back
  when in the money; $0.65 commission per contract per side.
- Stress: half-spreads doubled; $1.00 per contract per side.
- Trade prints may already be at the bid; subtracting a half-spread from them is deliberately
  conservative.

## Windows and gates

- Development: 2014-06-01 → 2019-12-31. Validation: 2020-01-01 → 2026-09-17, run once, only for
  candidates that pass development, after `research/putwrite/VALIDATION_UNLOCK.md` is registered.
- Development gate: net base Sharpe (daily excess returns, √252, counting non-trading days as 0)
  ≥ 0.5.
- Validation pass: net base Sharpe ≥ 0.75; stressed mean > 0; one-sided circular-block bootstrap
  p < 0.05/3 (21-day blocks, 5,000 draws); **and** max drawdown at 1.0× notional no worse than SPY
  buy-and-hold over the same window.
- A pass means a forward paper test only. Changing strike distance, the VRP filter, the size or the
  window after seeing results is a new experiment.

## Expectation stated in advance

Put writing is famous for smooth returns interrupted by crashes. The validation window contains
2020-02/03, 2022, 2024-08-05 and 2025-04. Prior: gross Sharpe perhaps 0.5–1.5 and net well below,
with the tail gate the most likely point of failure. A negative result is informative.
