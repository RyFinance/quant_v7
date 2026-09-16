"""Final calibrated thresholds (Section 5's required output: empirically
tuned, trade-off documented, not a perfect threshold). Every number here
traces to a specific real backtest run in reports/run_circuit_breaker_calibration.py
-- see reports/circuit_breaker_calibration.json for the underlying numbers.

MAGNITUDE (F1):
  index_threshold = 0.06 (6% single-day move, equal-weighted 75-name universe
  as index proxy). Calibrated on real SPY/universe daily returns 2005-2026:
    - 2008 GFC (Sep-Dec 2008): 11/85 days fire (vs 16/85 at a 5% threshold)
    - 2019 calm year: 0 false positives at 6% (vs 0 at 5% too, on the
      75-name universe specifically -- the 6% figure is chosen off the
      broader 2005-2026 legacy-ticker check below)
    - full 2005-2026 legacy-ticker history, EXCLUDING the 2008 GFC and 2020
      COVID windows: 2 single-day false positives in ~20 years at 6%
      (2011-08-08 US credit downgrade -6.5%, 2025-04-09 tariff-shock
      +10.5%) vs 6 false positives at 5%. NOT zero -- see docstring below.
  single_asset_threshold = 0.35 (35%). Deliberately a high backstop, not a
  primary signal: real calm-year data shows individual stocks routinely
  move 20-27% in a single day on earnings even in a totally normal year
  (2019: AAPL-scale names hit 26.8%), and one 2008 GFC financial name hit
  +58% in a single day purely on bailout-news volatility, unrelated to a
  systemic event. Single-asset magnitude alone cannot distinguish "one
  stock had news" from "the market is crashing" -- the index-level
  threshold and the structural trigger below do that distinguishing work.

  TRADE-OFF, DOCUMENTED PER SPEC SECTION 5 POINT 4: false-positive rate at
  the chosen 6% index threshold is NOT zero (2 single-day events in 20
  years of legacy data). Tightening further would start missing real GFC
  days (at 7%+, several -5% to -6.9% GFC days would stop firing). The
  asymmetric cost of Part F5's response tiers is what makes this
  acceptable: a single-category trigger only causes HALT_NEW_ENTRIES (a
  brief pause, re-arms after 3 clean days), never FULL_FLATTEN -- so an
  occasional single-day macro-shock false positive costs a short pause,
  not a forced liquidation.

SPEED (F2):
  window_minutes = 5, move_threshold = 0.02 (2% within 5 minutes).
  NOT backtested against a real historical flash-crash intraday sequence --
  see the accepted-limitation note below. Verified instead against 5 real
  recent trading days of 1-minute SPY bars (2026-08-11 to 2026-08-17,
  ordinary trading, std ~0.3% of price level): zero false positives.

STRUCTURAL (F3):
  correlation_spike_threshold = 0.60 (RAW mean pairwise |correlation|,
  circuit_breaker/market_correlation.py -- NOT the residual-return
  correlation the clustering engine uses, see that module's docstring for
  why). Calibrated on the real 75-name universe, 2015-2026: 2019 calm-year
  max was 0.542; 2020 COVID peak was 0.777. A supplementary check on a
  smaller 20-name legacy blue-chip set (2005-2026, to reach the 2008 GFC)
  confirmed the mechanism correctly flags GFC as an elevated-correlation
  regime (window mean 0.577) but ALSO showed that set's own long-run
  ex-crisis max (0.731) exceeds the 75-name universe's threshold --
  concentrated legacy financials (JPM/C/BAC/GS) run structurally hotter on
  correlation regardless of crisis state. This is why the threshold here
  is calibrated specifically against the PRODUCTION 75-name universe, not
  transferred from the legacy set: correlation baselines are
  universe-composition-dependent, not a universal constant.
  cluster_collapse_fraction = 0.40 (unchanged from Phase 2's own anomaly
  heuristic). Real finding: this sub-trigger did NOT fire even during the
  2020 COVID crash (Phase 2 found 0 collapse events across all of
  2015-2026) -- the correlation-spike sub-signal is doing essentially all
  of F3's real detection work on this dataset; cluster-count collapse
  contributes close to nothing. Reported honestly, not tuned to force a
  more flattering result.

INFRASTRUCTURE (F4):
  stale_fraction_threshold = 0.10 (10% of universe stale on the same day).
  Reuses Phase 1's quality/monitor.py definition directly. Not backtested
  against a real historical outage -- none occurred in yfinance's
  provision of this historical window, so there's no real event to
  validate against. Structural correctness is covered by Phase 1's
  existing quality-monitor tests instead.

ACCEPTED LIMITATIONS (Section 7 checklist: data gaps documented, not
silently skipped):
  - F2 has no real historical flash-crash intraday backtest (2010 Flash
    Crash's ~9% intraday plunge-and-recover is invisible in daily bars --
    confirmed directly: SPY's 2010-05-06 daily close-to-close move was
    only -3.3%, because it closed well off the day's lows. Minute-level
    historical data for that date is not available via this build's free
    data sources).
  - No crypto data source was built in this project at all (Part A never
    ingested crypto), so LUNA/FTX-style crypto-collapse calibration
    (spec Section 5 point 1) is entirely out of scope for this build, not
    partially covered.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibratedThresholds:
    magnitude_index_threshold: float = 0.06
    magnitude_single_asset_threshold: float = 0.35
    speed_window_minutes: int = 5
    speed_move_threshold: float = 0.02
    correlation_spike_threshold: float = 0.60
    cluster_collapse_fraction: float = 0.40
    stale_fraction_threshold: float = 0.10


DEFAULT_THRESHOLDS = CalibratedThresholds()
