"""Guards for live_backtest/backfill_missed_season.py's writes into the real
paper account: it must refuse to run over existing trades, and --undo must
remove exactly the records it flagged."""
from __future__ import annotations

import json

import pytest

import live_backtest.backfill_missed_season as bf


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    paths = {"ledger": tmp_path / "ledger.jsonl", "alerts": tmp_path / "alerts.jsonl",
             "cycles": tmp_path / "backfill_cycle_log.jsonl"}
    monkeypatch.setattr(bf, "LEDGER_FILE", paths["ledger"])
    monkeypatch.setattr(bf, "ALERTS_LOG_FILE", paths["alerts"])
    monkeypatch.setattr(bf, "BACKFILL_CYCLE_LOG", paths["cycles"])
    return paths


def _write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def test_refuses_to_backfill_under_live_trades(isolated):
    _write(isolated["ledger"], [{"event": "open", "ticker": "AAPL"}])
    with pytest.raises(SystemExit, match="live trades"):
        bf.run_backfill()


def test_refuses_to_backfill_twice(isolated):
    _write(isolated["ledger"], [{"event": "open", "ticker": "AAPL", "backfill": True}])
    with pytest.raises(SystemExit, match="--undo"):
        bf.run_backfill()


def test_undo_removes_only_flagged_records(isolated):
    _write(isolated["ledger"], [{"event": "open", "ticker": "NFLX", "backfill": True},
                                {"event": "close", "ticker": "NFLX", "backfill": True}])
    _write(isolated["alerts"], [{"kind": "dead_mans_switch"}, {"kind": "position_opened", "backfill": True}])
    isolated["cycles"].write_text("{}\n")

    bf.undo_backfill()
    assert isolated["ledger"].read_text() == ""
    assert [json.loads(line)["kind"] for line in isolated["alerts"].read_text().splitlines()] == ["dead_mans_switch"]
    assert not isolated["cycles"].exists()


def test_undo_refuses_when_live_records_follow_the_backfill(isolated):
    _write(isolated["ledger"], [{"event": "open", "ticker": "ADBE", "backfill": True},
                                {"event": "close", "ticker": "ADBE"}])
    with pytest.raises(SystemExit, match="orphan"):
        bf.undo_backfill()
