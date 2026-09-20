"""Client for the London Strategic Edge data vault.

https://api.londonstrategicedge.com/vault -- daily and intraday candles, macro
series and point-in-time reference datasets (insider trades, financial reports,
dividends, splits). Used for research history that yfinance does not reach:
US stock daily candles from 2003 (yfinance-era data here starts 2015) and
SEC-sourced insider and fundamentals records.

Key handling: read from the LSE_API_KEY environment variable or quant_v7/.env
(gitignored, mode 600). It is sent only as the x-api-key header and never
logged or written anywhere else.

Transport quirks, found the hard way:
  * The front door rejects Python's default urllib User-Agent with 403, which
    reads exactly like an expired key. An explicit User-Agent is always sent.
  * Every page is capped at the plan's max_rows_per_request (5,000). Candle and
    reference pulls page forward on their date column; rows repeated at the page
    boundary are dropped by their unique key, and a page that is entirely one
    date and entirely full raises instead of looping forever.
  * The plan allows a fixed number of calls per minute and concurrent vault
    requests (/usage reports both). A shared limiter keeps every thread under
    both; 429 and 503 are retried with backoff, anything else fails loudly.

Data caveats recorded here so they are never forgotten:
  * US stock "1d" candles are UTC CALENDAR-DAY bars that include pre-market and
    after-hours trading, NOT the official 9:30-16:00 ET session. On an after-
    close earnings day the daily "close" already contains most of the reaction
    (ORCL 2025-06-11: official close $176.38, vault 1d close $189.75). Daily
    returns correlate only ~0.93 with official-session returns. Build session
    bars from intraday candles, or use an official-close source, for anything
    where the close matters.
  * The stock universe holds only CURRENTLY listed symbols (no delisted or
    acquired names), so it does not remove survivorship bias.
  * Dividend amounts are NOT split-adjusted even though prices are.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from loguru import logger

BASE_URL = "https://api.londonstrategicedge.com/vault"
ENV_FILE = Path(__file__).parent.parent / ".env"
USER_AGENT = "quant_v7-research/1.0"
PAGE_ROWS = 5000
RETRY_STATUSES = {429, 503}
MAX_RETRIES = 6


class VaultError(RuntimeError):
    pass


def load_api_key() -> str:
    key = os.environ.get("LSE_API_KEY")
    if not key and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LSE_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise VaultError("LSE_API_KEY is not set (environment or quant_v7/.env)")
    return key


class RateLimiter:
    """At most `per_minute` starts per rolling minute and `concurrency` in flight."""

    def __init__(self, per_minute: int, concurrency: int):
        self.interval = 60.0 / per_minute
        self.slots = threading.BoundedSemaphore(concurrency)
        self.lock = threading.Lock()
        self.next_start = 0.0

    def __enter__(self):
        self.slots.acquire()
        with self.lock:
            now = time.monotonic()
            wait = self.next_start - now
            self.next_start = max(now, self.next_start) + self.interval
        if wait > 0:
            time.sleep(wait)
        return self

    def __exit__(self, *exc):
        self.slots.release()


class Vault:
    def __init__(self, api_key: str | None = None, calls_per_minute: int = 180, concurrency: int = 2,
                 transport=None, sleep=time.sleep):
        self._key = api_key or load_api_key()
        # Stay a little under the plan's 200/min so retries have headroom.
        self.limiter = RateLimiter(calls_per_minute, concurrency)
        self._transport = transport or self._urllib_transport
        self._sleep = sleep
        self.bytes_used = 0

    # -- transport -------------------------------------------------------------
    def _urllib_transport(self, method, url, body=None, headers=None):
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
              extra_headers: dict | None = None, raw: bool = False):
        query = {k: v for k, v in (params or {}).items() if v is not None}
        url = BASE_URL + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"x-api-key": self._key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        headers.update(extra_headers or {})
        for attempt in range(MAX_RETRIES + 1):
            with self.limiter:
                status, resp_headers, content = self._transport(method, url, payload, headers)
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                delay = min(60.0, 2.0 ** attempt)
                logger.warning(f"vault {status} on {path}; retrying in {delay:.0f}s")
                self._sleep(delay)
                continue
            if status >= 400:
                try:
                    detail = json.loads(content).get("detail")
                except Exception:
                    detail = content[:200]
                raise VaultError(f"{method} {path} -> {status}: {detail}")
            self.bytes_used += int({k.lower(): v for k, v in resp_headers.items()}.get("x-data-bytes") or 0)
            return content if raw else json.loads(content)
        raise VaultError(f"{method} {path}: retries exhausted")

    # -- discovery -------------------------------------------------------------
    def usage(self) -> dict:
        return self._call("GET", "/usage")

    def catalog(self) -> list[dict]:
        return self._call("GET", "/catalog")

    # -- paged reads -------------------------------------------------------------
    def _paged(self, path: str, params: dict, date_field: str, key_fields: tuple[str, ...]) -> pd.DataFrame:
        rows: list[dict] = []
        seen: set[tuple] = set()
        start = params.get("start")
        while True:
            page = self._call("GET", path, {**params, "start": start, "order": "asc", "limit": PAGE_ROWS})
            fresh = [r for r in page if tuple(r.get(k) for k in key_fields) not in seen]
            for r in fresh:
                seen.add(tuple(r.get(k) for k in key_fields))
            rows.extend(fresh)
            if len(page) < PAGE_ROWS:
                break
            first, last = page[0].get(date_field), page[-1].get(date_field)
            if first == last:
                raise VaultError(f"{path}: a full page shares one {date_field} ({last}); cannot page past it safely")
            if not fresh:
                raise VaultError(f"{path}: pagination made no progress at {last}")
            # Re-request from the last date itself: rows on that date may continue
            # onto the next page, and the unique key drops the ones already seen.
            start = self._cursor(last)
        return pd.DataFrame(rows)

    @staticmethod
    def _cursor(value) -> str:
        """Rows carry timestamps like '2023-06-07 00:00:00.000000', which the
        vault rejects as a start parameter; it takes YYYY-MM-DD or ISO datetimes."""
        ts = pd.Timestamp(value)
        return ts.strftime("%Y-%m-%d") if ts == ts.normalize() else ts.strftime("%Y-%m-%dT%H:%M:%S")

    def candles(self, symbol: str, timeframe: str = "1d", start: str | None = None,
                end: str | None = None, dataset: str | None = None) -> pd.DataFrame:
        df = self._paged("/candles", {"symbol": symbol, "timeframe": timeframe, "end": end, "dataset": dataset,
                                      "start": start}, date_field="ts", key_fields=("ts",))
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.sort_values("ts").reset_index(drop=True)
        return df

    def series(self, symbol: str, start: str | None = None, end: str | None = None,
               dataset: str | None = None) -> pd.DataFrame:
        """One macro or bond-yield series as date/value rows (economics or bonds)."""
        df = self._paged("/series", {"symbol": symbol, "start": start, "end": end, "dataset": dataset},
                         date_field="date", key_fields=("date",))
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        return df

    REF_DATE_FIELD = {
        "insider_trades": "transaction_date", "financial_reports": "date", "dividends": "effective_date",
        "stock_splits": "effective_date", "economic_calendar": "datetime", "cot": "date", "bond_yields": "date",
    }

    def reference(self, dataset: str, **filters) -> pd.DataFrame:
        date_field = self.REF_DATE_FIELD.get(dataset)
        if date_field is None:  # undated sets (profiles, fundamentals) fit one page per symbol
            return pd.DataFrame(self._call("GET", f"/ref/{dataset}", {**filters, "limit": PAGE_ROWS}))
        return self._paged(f"/ref/{dataset}", filters, date_field=date_field, key_fields=("id",))
