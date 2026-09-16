"""PEAD labeling -- reuses signals/labeling.py's forward-cumulative-abnormal-
return + threshold/cost-adjusted machinery directly (it's generic over any
(date, ticker, signal) frame, not specific to the mean-reversion signal it
was originally built for).

HOLDING PERIOD = 20 trading days (~1 calendar month): the classic PEAD
literature studies both ~60-day (one-quarter) and shorter ~20-day windows;
20 days is used here as primary since (a) it reduces overlap with the
NEXT quarterly earnings event for most reporters, giving more independent
observations, and (b) the drift, where it exists, is typically front-
loaded in the weeks immediately following the surprise.

REAL, HONEST FINDING FROM CALIBRATION (see reports/run_pead_pipeline.py's
threshold-selection step): the raw mean position_return (sign(SUE) *
forward abnormal return) is NEGATIVE at every horizon tested (10/20/60
days) on this specific universe -- the OPPOSITE of classic PEAD
continuation. This is plausibly because PEAD is a well-documented SMALL-
CAP / low-analyst-coverage anomaly, and this build's 75-name universe was
explicitly constructed (Phase 1) to be the most LIQUID, most heavily-
covered large-cap subset of the S&P 500 -- exactly where the literature
says PEAD should be weakest or absent. Reported here, not smoothed over;
the ML filter step still proceeds with full rigor since a negative
unconditional mean doesn't rule out a real edge in some subset of events
(e.g. only the largest-SUE surprises), which is exactly what Part D-style
validation is for.

FIXED_THRESHOLD_RETURN = 1.0% over 20 days (~12-13% annualized-equivalent
bar) -- calibrated to land near the 60th percentile of the real position-
return distribution (0.96%), giving a reasonably balanced label despite
the negative unconditional mean. Cost-adjusted label reuses the SAME
10bps round-trip assumption as risk/transaction_costs.py for consistency
across strategies built in this project.
"""
from __future__ import annotations

from signals.labeling import add_labels, compute_forward_position_return

HOLDING_PERIOD_DAYS = 20
FIXED_THRESHOLD_RETURN = 0.01


def build_labeled_pead_signals(residual_returns, signal_df, holding_period: int = HOLDING_PERIOD_DAYS,
                                fixed_threshold: float = FIXED_THRESHOLD_RETURN, cost_bps: float = 10.0):
    with_returns = compute_forward_position_return(residual_returns, signal_df, holding_period=holding_period)
    return add_labels(with_returns, fixed_threshold=fixed_threshold, cost_bps=cost_bps)
