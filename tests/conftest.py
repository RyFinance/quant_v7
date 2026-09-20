"""Suite-wide isolation for live state files that library code appends to.

earnings.ingestion.fetch_ticker_earnings_live records every announcement date it
sees into bot/state/earnings_schedule_log.jsonl. Tests (including the ones that
hit the real network, or fake a yfinance Ticker) must never write the real bot's
log, so every test gets its own empty one.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_schedule_log(tmp_path, monkeypatch):
    import earnings.ingestion as ingestion

    monkeypatch.setattr(ingestion, "SCHEDULE_LOG_FILE", tmp_path / "earnings_schedule_log.jsonl")
    yield
