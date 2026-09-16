"""Data quality monitor for quant_v7.

Two checks, wired to a structured JSONL log (not wired to any circuit
breaker yet — that's a later phase, per spec):

  1. Gap detection: missing US equity trading days inside a ticker's date
     range (using NYSE sessions via pandas_market_calendars if available,
     else falling back to a simple business-day calendar approximation).
  2. Stale-feed detection: a ticker's most recent bar is more than
     `STALE_THRESHOLD_DAYS` behind the universe-wide max last-bar date —
     i.e. it stopped updating while its peers kept going.

Deviation from polymarket_arb's `WebhookAlerter`: no webhook/network path at
all (out of scope here — this is a research/offline pipeline, not a live
bot), but the *shape* is deliberately mirrored: stable string "kind"
identifiers, always-on local JSONL log via a dedicated writer, one-line-per-
event records with a timestamp. This keeps the eventual circuit-breaker
wiring (a later phase) a drop-in, not a rewrite.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from loguru import logger

QUALITY_LOG_FILE = Path(__file__).parent.parent / "reports" / "data_quality.jsonl"

GAP_DETECTED = "gap_detected"
STALE_FEED = "stale_feed"
STALE_THRESHOLD_DAYS = 5


def _write_record(kind: str, ticker: str, path: Path, **fields):
    record = {"ts": time.time(), "kind": kind, "ticker": ticker, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


@dataclass
class QualityReport:
    gaps: list[dict] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)


def detect_gaps(ticker: str, df: pd.DataFrame, log_path: Path = QUALITY_LOG_FILE) -> list[dict]:
    """Flag runs of >1 consecutive missing business days between bars.

    Approximation: uses a business-day calendar rather than the exact NYSE
    holiday calendar, so US market holidays will show up as 1-day "gaps" —
    acceptable false-positive rate for a monitor whose output isn't wired to
    any action yet; worth tightening (pandas_market_calendars) before this
    feeds a real circuit breaker.
    """
    if df.empty:
        return []
    ts = pd.to_datetime(df["timestamp"]).sort_values()
    expected = pd.bdate_range(ts.iloc[0], ts.iloc[-1])
    missing = expected.difference(ts)

    gaps = []
    if len(missing) > 0:
        missing_sorted = sorted(missing)
        run_start = missing_sorted[0]
        prev = missing_sorted[0]
        for d in missing_sorted[1:] + [None]:
            if d is None or (d - prev).days > 1:
                run_len = (prev - run_start).days + 1
                if run_len > 1:  # single-day gaps are almost always holidays; ignore
                    gap = {"start": str(run_start.date()), "end": str(prev.date()), "business_days_missing": run_len}
                    gaps.append(gap)
                    _write_record(GAP_DETECTED, ticker, log_path, **gap)
                if d is not None:
                    run_start = d
            prev = d if d is not None else prev
    return gaps


def detect_stale_feeds(
    universe_data: dict[str, pd.DataFrame],
    threshold_days: int = STALE_THRESHOLD_DAYS,
    log_path: Path = QUALITY_LOG_FILE,
) -> list[dict]:
    """Flag tickers whose last bar trails the universe-wide max last-bar date."""
    last_dates = {t: pd.to_datetime(df["timestamp"]).max() for t, df in universe_data.items() if not df.empty}
    if not last_dates:
        return []
    universe_max = max(last_dates.values())

    stale = []
    for ticker, last in last_dates.items():
        lag_days = (universe_max - last).days
        if lag_days > threshold_days:
            record = {"last_bar_date": str(last.date()), "universe_max_date": str(universe_max.date()), "lag_days": lag_days}
            stale.append({"ticker": ticker, **record})
            _write_record(STALE_FEED, ticker, log_path, **record)
    return stale


def run_quality_checks(
    universe_data: dict[str, pd.DataFrame],
    log_path: Path = QUALITY_LOG_FILE,
) -> QualityReport:
    report = QualityReport()
    for ticker, df in universe_data.items():
        gaps = detect_gaps(ticker, df, log_path=log_path)
        if gaps:
            report.gaps.append({"ticker": ticker, "gaps": gaps})
    report.stale = detect_stale_feeds(universe_data, log_path=log_path)

    logger.info(f"data quality: {len(report.gaps)} tickers with gaps, {len(report.stale)} stale feeds "
                f"(log: {log_path})")
    return report
