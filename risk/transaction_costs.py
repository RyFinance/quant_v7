"""Part E4 -- transaction cost model. Built early (referenced by Phase 3's
signal labeling, C2) since the "cost-adjusted" label needs the same cost
number the backtest engine later charges -- if labeling used one cost
assumption and the backtest used another, the ML filter would be trained
against a target that doesn't match what it's evaluated against.

Single flat round-trip assumption for the whole (equity-only, liquidity-
filtered) universe, not a per-ticker/liquidity-tiered model:

  - bid-ask spread, one-way:      ~2 bps
  - commission (modern broker):   ~0 bps (many US equity brokers are
                                   commission-free; kept at 0 rather than
                                   assuming a specific broker)
  - market-impact, one-way:       ~3 bps (small-to-moderate size against
                                   names that passed our 63-day average
                                   dollar-volume liquidity filter in
                                   Phase 1 Task 1 -- these are large/mid
                                   cap, not illiquid microcaps)
  ---------------------------------------------------------------
  one-way total:  ~5 bps  ->  round trip (entry + exit): ~10 bps

This is a documented assumption, not fit to a specific broker/venue's
actual fill data (we have none). Section 4.4 of the spec explicitly wants
a sensitivity sweep around whatever base number is chosen -- see
`COST_SWEEP_BPS` and backtest/cost_sensitivity.py -- specifically because
a single point estimate is not something to bet the whole go/no-go
decision on.
"""
from __future__ import annotations

ROUND_TRIP_COST_BPS_DEFAULT = 10.0
COST_SWEEP_BPS = [2.0, 5.0, 10.0]  # spec Section 4.4 example sweep: 0.02%, 0.05%, 0.10%


def round_trip_cost_bps(asset_class: str = "equity", cost_bps: float = ROUND_TRIP_COST_BPS_DEFAULT) -> float:
    """Round-trip cost in basis points. `asset_class` accepted for interface
    stability (a future crypto/prediction-market leg would need a different
    number) but this build is equities-only, so it's currently unused."""
    return cost_bps


def cost_as_return(cost_bps: float = ROUND_TRIP_COST_BPS_DEFAULT) -> float:
    return cost_bps / 10_000.0
