"""Tests for the data quality monitor (Task 5). Base data is real (real
AAPL/MSFT bars via yfinance); the gap-detection test removes rows from a
real dataframe to force a gap deterministically -- that's a modification of
real data, not a synthetically generated price series, but it's noted here
explicitly per the "flag any synthetic data used in a test" instruction.
Skipped if offline.
"""
import json

import pandas as pd
import pytest

from data.ingestion import fetch_ticker_history
from quality.monitor import detect_gaps, detect_stale_feeds, run_quality_checks


@pytest.fixture(scope="module")
def aapl_df():
    df = fetch_ticker_history("AAPL", start="2024-01-01", end="2024-03-01")
    if df.empty:
        pytest.skip("network unavailable / yfinance unreachable")
    return df


def test_detect_gaps_clean_data_has_no_multiday_gaps(aapl_df, tmp_path):
    gaps = detect_gaps("AAPL", aapl_df, log_path=tmp_path / "quality.jsonl")
    assert gaps == []


def test_detect_gaps_flags_injected_gap(aapl_df, tmp_path):
    # Real bars with a deliberate 5-business-day block removed from the middle
    # (real data, artificially truncated -- not simulated prices).
    df = aapl_df.copy().sort_values("timestamp").reset_index(drop=True)
    mid = len(df) // 2
    injected = pd.concat([df.iloc[:mid], df.iloc[mid + 5:]]).reset_index(drop=True)

    log_path = tmp_path / "quality.jsonl"
    gaps = detect_gaps("AAPL", injected, log_path=log_path)
    assert len(gaps) >= 1
    assert any(g["business_days_missing"] >= 2 for g in gaps)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[0])
    assert record["kind"] == "gap_detected"
    assert record["ticker"] == "AAPL"


def test_detect_stale_feeds_flags_lagging_ticker(aapl_df, tmp_path):
    fresh = aapl_df.copy()
    stale = aapl_df.copy().iloc[:-10]  # real data, just missing the most recent 10 bars

    log_path = tmp_path / "quality.jsonl"
    stale_report = detect_stale_feeds({"FRESH": fresh, "STALE": stale}, threshold_days=5, log_path=log_path)

    assert any(s["ticker"] == "STALE" for s in stale_report)
    assert not any(s["ticker"] == "FRESH" for s in stale_report)


def test_run_quality_checks_end_to_end(aapl_df, tmp_path):
    log_path = tmp_path / "quality.jsonl"
    report = run_quality_checks({"AAPL": aapl_df}, log_path=log_path)
    assert report.gaps == []
    assert report.stale == []
