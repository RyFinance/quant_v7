"""Survivorship-bias-free universe history.

Source: Wikipedia's "List of S&P 500 companies" page. It carries two tables
we need:
  1. Current constituents (ticker, name, sector, date added).
  2. "Selected changes to the list of S&P 500 components" — a historical log
     of additions/removals with dates, going back to ~1990s (deepest for
     recent decades). This is what lets us avoid survivorship bias: we can
     reconstruct which names were actually in the index on any given
     historical date, rather than backfilling today's membership.

Deviation from quant_v6 roadmap: that roadmap never addressed survivorship
bias at all (it only ever queries current tickers). This module is new for
v7, driven directly by the spec's explicit requirement.

Plain `urllib.request.urlopen()` gets HTTP 403 from Wikipedia — a User-Agent
header identifying the client is required (confirmed empirically).
"""
from __future__ import annotations

import io
import urllib.request
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from schemas.market_data import UniverseMember

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# As of a 2026-08-11 edit, the "Selected changes" table was split out of the
# main list page into its own dedicated article (edit comment: "move to
# [[Historical components of the S&P 500]], format" -- confirmed via the
# page's revision history). Still Wikipedia, still a real source; just a
# different URL than the one the current-constituents table lives on.
WIKI_HISTORY_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
USER_AGENT = "Mozilla/5.0 (research script; contact manavmohem@gmail.com)"


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _fetch_wiki_html() -> str:
    return _fetch_html(WIKI_URL)


def fetch_current_constituents() -> pd.DataFrame:
    """Return today's S&P 500 constituent table: Symbol, Security, GICS Sector, Date added."""
    html = _fetch_wiki_html()
    tables = pd.read_html(io.StringIO(html))
    current = tables[0]
    current = current.rename(columns={
        "Symbol": "ticker",
        "Security": "name",
        "GICS Sector": "sector",
        "Date added": "date_added",
    })
    current["ticker"] = current["ticker"].str.replace(".", "-", regex=False).str.upper()
    logger.info(f"fetched {len(current)} current S&P 500 constituents from Wikipedia")
    return current[["ticker", "name", "sector", "date_added"]]


def fetch_historical_changes() -> pd.DataFrame:
    """Return the S&P 500 constituent-changes table from the dedicated
    "Historical components of the S&P 500" Wikipedia article (see
    WIKI_HISTORY_URL note above -- this table used to live on the main list
    page but was split out).

    Columns are a two-level header (Effective Date / Added-Ticker /
    Added-Security / Removed-Ticker / Removed-Security / Reason / Refs). We
    flatten that into a long-form frame: one row per add/remove event.
    """
    html = _fetch_html(WIKI_HISTORY_URL)
    tables = pd.read_html(io.StringIO(html))
    changes = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if any("Added" in c for c in cols) and any("Removed" in c for c in cols):
            changes = t
            break
    if changes is None:
        raise RuntimeError("could not locate the historical changes table on the Wikipedia history page")

    changes.columns = ["_".join([str(x) for x in col if "Unnamed" not in str(x)]).strip("_")
                        for col in changes.columns.to_flat_index()]

    date_col = next(c for c in changes.columns if "date" in c.lower())
    added_ticker_col = next((c for c in changes.columns if "Added" in c and "Ticker" in c), None)
    removed_ticker_col = next((c for c in changes.columns if "Removed" in c and "Ticker" in c), None)

    events = []
    for _, row in changes.iterrows():
        date = row[date_col]
        if added_ticker_col and pd.notna(row.get(added_ticker_col)):
            events.append({"date": date, "ticker": str(row[added_ticker_col]).upper(), "action": "added"})
        if removed_ticker_col and pd.notna(row.get(removed_ticker_col)):
            events.append({"date": date, "ticker": str(row[removed_ticker_col]).upper(), "action": "removed"})

    out = pd.DataFrame(events)
    logger.info(f"fetched {len(out)} historical S&P 500 add/remove events from Wikipedia")
    return out


def build_universe_history(
    current: Optional[pd.DataFrame] = None,
    changes: Optional[pd.DataFrame] = None,
) -> list[UniverseMember]:
    """Reconstruct membership intervals per ticker from current constituents + change log.

    Approach: every current constituent gets an open interval starting at its
    "date added" (or earliest known change event, if date_added is missing/NaT).
    Every ticker that was `removed` in the historical change log but is NOT a
    current constituent gets a closed interval ending at its removal date; its
    start date is the most recent `added` event for that ticker if one exists
    in the change log, else unknown (we conservatively use the earliest date in
    the change log as a lower bound rather than guessing further back).
    """
    if current is None:
        current = fetch_current_constituents()
    if changes is None:
        changes = fetch_historical_changes()

    changes = changes.copy()
    changes["date"] = pd.to_datetime(changes["date"], errors="coerce")
    changes = changes.dropna(subset=["date"])
    earliest_known = changes["date"].min() if not changes.empty else pd.Timestamp("1900-01-01")

    members: list[UniverseMember] = []
    current_tickers = set(current["ticker"])

    for _, row in current.iterrows():
        start = pd.to_datetime(row.get("date_added"), errors="coerce")
        if pd.isna(start):
            start = earliest_known
        members.append(UniverseMember(
            ticker=row["ticker"], name=row.get("name"), sector=row.get("sector"),
            start_date=start.to_pydatetime(), end_date=None,
        ))

    removed = changes[changes["action"] == "removed"]
    for ticker, grp in removed.groupby("ticker"):
        if ticker in current_tickers:
            continue  # re-added later, already covered by the current-constituent row
        end = grp["date"].max()
        added_events = changes[(changes["ticker"] == ticker) & (changes["action"] == "added") & (changes["date"] < end)]
        start = added_events["date"].max() if not added_events.empty else earliest_known
        members.append(UniverseMember(ticker=ticker, start_date=start.to_pydatetime(), end_date=end.to_pydatetime()))

    logger.info(f"reconstructed {len(members)} historical membership intervals "
                f"({len(current_tickers)} current, {len(members) - len(current_tickers)} historical-only)")
    return members


def is_member_on(ticker: str, as_of: datetime, history: list[UniverseMember]) -> bool:
    """True if `ticker` was an S&P 500 member on date `as_of`, per reconstructed history."""
    ticker = ticker.upper()
    for m in history:
        if m.ticker != ticker:
            continue
        if m.start_date <= as_of and (m.end_date is None or as_of <= m.end_date):
            return True
    return False
