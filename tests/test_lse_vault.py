"""Tests for data/lse_vault.py against a fake transport (no network, no key)."""
from __future__ import annotations

import json

import pytest

from data.lse_vault import PAGE_ROWS, USER_AGENT, Vault, VaultError


class FakeVault:
    """Serves canned responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, method, url, body=None, headers=None):
        self.requests.append({"method": method, "url": url, "headers": headers or {}})
        status, payload = self.responses.pop(0)
        return status, {"X-Data-Bytes": "10"}, json.dumps(payload).encode()


def make_vault(responses):
    fake = FakeVault(responses)
    return Vault(api_key="lse_live_test", transport=fake, sleep=lambda s: None, calls_per_minute=10_000), fake


def rows(start_day, n, same_day=False):
    return [{"id": start_day * 100_000 + i, "ts": f"2020-01-{start_day if same_day else start_day + i:02d} 00:00:00.000000",
             "close": 1.0} for i in range(n)]


def test_sends_key_as_header_with_explicit_user_agent_never_in_url():
    """The vault answers Python's default urllib User-Agent with 403, which
    reads exactly like an expired key."""
    vault, fake = make_vault([(200, {"bytes_used_month": 1})])
    vault.usage()
    req = fake.requests[0]
    assert req["headers"]["x-api-key"] == "lse_live_test"
    assert req["headers"]["User-Agent"] == USER_AGENT
    assert "lse_live_test" not in req["url"]


def test_pages_forward_and_drops_boundary_repeats(monkeypatch):
    monkeypatch.setattr("data.lse_vault.PAGE_ROWS", 3)
    first = [{"id": i, "ts": f"2020-01-0{d} 00:00:00.000000"} for i, d in enumerate([1, 2, 3])]
    # The next page is requested from the last date (inclusive), so it repeats id 2.
    second = [{"id": 2, "ts": "2020-01-03 00:00:00.000000"}, {"id": 3, "ts": "2020-01-04 00:00:00.000000"}]
    vault, fake = make_vault([(200, first), (200, second)])
    df = vault._paged("/candles", {"symbol": "X", "start": "2020-01-01"}, date_field="ts", key_fields=("id",))
    assert df["id"].tolist() == [0, 1, 2, 3]
    assert "start=2020-01-03" in fake.requests[1]["url"]  # cursor reformatted to YYYY-MM-DD


def test_full_page_on_a_single_date_fails_instead_of_looping(monkeypatch):
    monkeypatch.setattr("data.lse_vault.PAGE_ROWS", 2)
    same = [{"id": i, "ts": "2020-01-05 00:00:00.000000"} for i in range(2)]
    vault, _ = make_vault([(200, same)])
    with pytest.raises(VaultError, match="shares one"):
        vault._paged("/candles", {"symbol": "X"}, date_field="ts", key_fields=("id",))


def test_retries_rate_limits_then_succeeds():
    vault, fake = make_vault([(429, {"detail": "rate"}), (503, {"detail": "busy"}), (200, {"ok": 1})])
    assert vault.usage() == {"ok": 1}
    assert len(fake.requests) == 3


def test_client_errors_fail_loudly_with_detail():
    vault, _ = make_vault([(403, {"detail": "key inactive"})])
    with pytest.raises(VaultError, match="403: key inactive"):
        vault.usage()


def test_cursor_formats_dates_and_datetimes():
    assert Vault._cursor("2023-06-07 00:00:00.000000") == "2023-06-07"
    assert Vault._cursor("2023-06-07 14:30:00.000000") == "2023-06-07T14:30:00"


def test_counts_data_bytes_for_the_monthly_allowance():
    vault, _ = make_vault([(200, {"a": 1}), (200, {"b": 2})])
    vault.usage()
    vault.usage()
    assert vault.bytes_used == 20
