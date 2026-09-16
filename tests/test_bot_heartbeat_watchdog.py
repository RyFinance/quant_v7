"""Tests for bot/heartbeat.py and bot/watchdog.py (the dead-man's-switch).
Time manipulation uses real file mtimes (os.utime) rather than mocking
time.time() globally -- exercises the actual staleness-detection code path.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import pytest

from bot.alerting import ALERT_DEAD_MANS_SWITCH, BotAlerter
from bot.heartbeat import read_heartbeat_age_seconds, read_heartbeat_timestamp, touch_heartbeat
from bot.watchdog import check_dead_mans_switch


def test_module_global_reassignment_redirects_bare_calls(tmp_path, monkeypatch):
    """Regression test for a real bug found 2026-08-19: touch_heartbeat's
    signature used to be `path: Path = HEARTBEAT_FILE` -- a def-time-bound
    default that a later `bot.heartbeat.HEARTBEAT_FILE = other_path`
    reassignment would NOT actually redirect. Confirms a caller that
    reassigns the module global and then calls touch_heartbeat() with NO
    arguments (exactly how bot/run_cycle.py calls it) is correctly
    redirected."""
    import bot.heartbeat as hb_module
    redirected = tmp_path / "redirected_heartbeat.txt"
    monkeypatch.setattr(hb_module, "HEARTBEAT_FILE", redirected)

    hb_module.touch_heartbeat()  # bare call, no path argument -- must use the reassigned global
    assert redirected.exists()
    assert hb_module.read_heartbeat_age_seconds() < 2.0
    assert hb_module.read_heartbeat_timestamp() is not None


def test_touch_heartbeat_creates_fresh_file(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    touch_heartbeat(hb)
    assert hb.exists()
    assert read_heartbeat_age_seconds(hb) < 2.0


def test_missing_heartbeat_is_infinitely_stale(tmp_path):
    assert read_heartbeat_age_seconds(tmp_path / "nope.txt") == float("inf")


def test_read_heartbeat_timestamp_roundtrip(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    before = time.time()
    touch_heartbeat(hb)
    ts = read_heartbeat_timestamp(hb)
    assert ts is not None
    assert abs(ts - before) < 2.0


def test_watchdog_silent_when_heartbeat_fresh(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    touch_heartbeat(hb)
    alerter = BotAlerter(alerts_path=tmp_path / "alerts.jsonl")
    monday = datetime(2026, 8, 17, 12, 0, 0)  # a real Monday
    fired = check_dead_mans_switch(max_age_hours=26, now=monday, heartbeat_path=hb, alerter=alerter)
    assert fired is False


def test_watchdog_fires_on_stale_heartbeat_on_weekday(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    touch_heartbeat(hb)
    # back-date the file's mtime by 30 hours -- simulates a real crash gap
    stale_time = time.time() - 30 * 3600
    os.utime(hb, (stale_time, stale_time))

    alerts_path = tmp_path / "alerts.jsonl"
    alerter = BotAlerter(alerts_path=alerts_path)
    monday = datetime(2026, 8, 17, 12, 0, 0)
    fired = check_dead_mans_switch(max_age_hours=26, now=monday, heartbeat_path=hb, alerter=alerter)

    assert fired is True
    lines = alerts_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == ALERT_DEAD_MANS_SWITCH
    assert record["age_hours"] > 26


def test_watchdog_fires_on_missing_heartbeat_on_weekday(tmp_path):
    hb = tmp_path / "never_written.txt"
    alerter = BotAlerter(alerts_path=tmp_path / "alerts.jsonl")
    monday = datetime(2026, 8, 17, 12, 0, 0)
    fired = check_dead_mans_switch(max_age_hours=26, now=monday, heartbeat_path=hb, alerter=alerter)
    assert fired is True


def test_watchdog_silent_on_weekend_even_if_stale(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    touch_heartbeat(hb)
    stale_time = time.time() - 100 * 3600  # very stale
    os.utime(hb, (stale_time, stale_time))

    alerter = BotAlerter(alerts_path=tmp_path / "alerts.jsonl")
    saturday = datetime(2026, 8, 15, 12, 0, 0)  # a real Saturday
    fired = check_dead_mans_switch(max_age_hours=26, now=saturday, heartbeat_path=hb, alerter=alerter)
    assert fired is False


def test_watchdog_respects_custom_threshold(tmp_path):
    hb = tmp_path / "heartbeat.txt"
    touch_heartbeat(hb)
    stale_time = time.time() - 10  # 10 seconds old
    os.utime(hb, (stale_time, stale_time))

    alerter = BotAlerter(alerts_path=tmp_path / "alerts.jsonl")
    monday = datetime(2026, 8, 17, 12, 0, 0)
    fired = check_dead_mans_switch(max_age_hours=0.001, now=monday, heartbeat_path=hb, alerter=alerter)  # ~3.6s threshold
    assert fired is True
