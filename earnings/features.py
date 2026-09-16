"""PEAD feature extraction (Part C3-equivalent).

  - sue, abs_sue                    -- the standardized surprise itself and its magnitude
  - surprise_pct_winsorized         -- raw (winsorized) surprise, in case SUE's own
                                        standardization washes out information
  - pre_earnings_return_{5,20}d     -- momentum INTO the announcement (trailing,
                                        reuses signals/features.py's rolling-return
                                        helper, which is already causal/no-lookahead)
  - dollar_volume_rank              -- static liquidity proxy from Phase 1's Task 1
                                        universe ranking (reports/universe_ranking.csv)
                                        -- coarse (doesn't vary over time) but real,
                                        not fabricated
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from signals.features import compute_recent_returns
from earnings.sue import SURPRISE_PCT_WINSOR_LIMIT


def build_pead_feature_matrix(
    labeled_signals: pd.DataFrame,
    residual_returns: pd.DataFrame,
    universe_ranking: pd.DataFrame,
) -> pd.DataFrame:
    df = labeled_signals.copy()
    df["abs_sue"] = df["signal"].abs()
    df["surprise_pct_winsorized"] = np.clip(df["surprise_pct"], -SURPRISE_PCT_WINSOR_LIMIT, SURPRISE_PCT_WINSOR_LIMIT)

    recent = compute_recent_returns(residual_returns, windows=(5, 20))
    recent = recent.rename(columns={"recent_return_5d": "pre_earnings_return_5d", "recent_return_20d": "pre_earnings_return_20d"})
    df = df.merge(recent, on=["date", "ticker"], how="left")

    rank = universe_ranking[["ticker", "avg_dollar_volume"]].copy()
    rank["dollar_volume_rank"] = rank["avg_dollar_volume"].rank(ascending=False)
    df = df.merge(rank[["ticker", "dollar_volume_rank"]], on="ticker", how="left")

    feature_cols = ["signal", "abs_sue", "surprise_pct_winsorized", "pre_earnings_return_5d",
                     "pre_earnings_return_20d", "dollar_volume_rank"]
    before = len(df)
    df = df.dropna(subset=feature_cols + ["label_cost_adjusted", "label_fixed_threshold"])
    logger.info(f"built PEAD feature matrix: {len(df)} rows ({before - len(df)} dropped for missing data), "
                f"{len(feature_cols)} feature columns")
    return df


PEAD_FEATURE_COLUMNS = ["signal", "abs_sue", "surprise_pct_winsorized", "pre_earnings_return_5d",
                         "pre_earnings_return_20d", "dollar_volume_rank"]
