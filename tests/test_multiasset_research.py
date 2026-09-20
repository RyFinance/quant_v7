"""Unit tests for the multi-asset research machinery (research/multiasset/).

The hold-out lock is the protocol's backbone: these tests pin that it refuses
post-cutoff dates until the pre-registration file exists AND its exact hash is
in the registry, so an edited pre-registration relocks the window.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from research.multiasset import panel, sleeves


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    prereg = tmp_path / "research/multiasset/PREREGISTRATION_holdout.md"
    registry = tmp_path / "research/preregistrations.jsonl"
    prereg.parent.mkdir(parents=True)
    registry.write_text("")
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    monkeypatch.setattr(panel, "HOLDOUT_PREREG", prereg)
    monkeypatch.setattr(panel, "REGISTRY", registry)
    return prereg, registry


def _register(prereg, registry):
    rec = {"file": "research/multiasset/PREREGISTRATION_holdout.md",
           "sha256": hashlib.sha256(prereg.read_bytes()).hexdigest()}
    registry.write_text(json.dumps(rec) + "\n")


def test_holdout_locked_without_preregistration(isolated_registry):
    with pytest.raises(panel.HoldoutLocked):
        panel.resolve_end("2019-06-30")
    assert panel.resolve_end(None) == panel.DEV_END
    assert panel.resolve_end("2016-01-04") == pd.Timestamp("2016-01-04")


def test_holdout_unlocks_only_with_matching_hash(isolated_registry):
    prereg, registry = isolated_registry
    prereg.write_text("the plan")
    with pytest.raises(panel.HoldoutLocked):       # written but not registered
        panel.resolve_end("2019-06-30")
    _register(prereg, registry)
    assert panel.resolve_end("2019-06-30") == pd.Timestamp("2019-06-30")
    assert panel.resolve_end("2030-01-01") == panel.HOLDOUT_END
    prereg.write_text("the plan, edited after the fact")
    with pytest.raises(panel.HoldoutLocked):       # any edit relocks it
        panel.resolve_end("2019-06-30")


def test_side_weights_long_top_short_bottom():
    w = sleeves.side_weights(pd.Series({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0, "f": 0.0}), 2)
    assert w.to_dict() == {"a": 0.5, "b": 0.5, "c": 0.0, "d": 0.0, "e": -0.5, "f": -0.5}
    assert w.sum() == pytest.approx(0.0)


def test_side_weights_split_ties_across_the_cut():
    # three names tied at the long cut compete for the one remaining slot
    w = sleeves.side_weights(pd.Series({"a": 9.0, "b": 5.0, "c": 5.0, "d": 5.0, "e": 1.0, "f": 0.0}), 2)
    assert w["a"] == pytest.approx(0.5)
    assert w[["b", "c", "d"]].tolist() == pytest.approx([1 / 6] * 3)
    assert w[w > 0].sum() == pytest.approx(1.0) and w[w < 0].sum() == pytest.approx(-1.0)


def test_side_weights_too_few_names_is_flat():
    assert (sleeves.side_weights(pd.Series({"a": 1.0, "b": 2.0, "c": np.nan}), 2) == 0).all()


def test_despike_removes_reverting_prints_and_keeps_real_moves():
    idx = pd.date_range("2014-01-06", periods=8, freq="B")
    s = pd.Series([0.0070, 0.0070, 0.0000, 0.0067, 0.0067, 0.0100, 0.0102, 0.0103], index=idx)
    out = panel.despike(s)
    assert idx[2] not in out.index            # 0.70% -> 0.00% -> 0.67%: a vendor zero
    assert idx[5] in out.index                # 0.67% -> 1.00% and stays: a real move


def test_run_weights_lags_two_sessions_and_charges_turnover():
    idx = pd.date_range("2020-01-01", periods=5, freq="B")
    excess = pd.DataFrame({"x": [0.0, 0.01, 0.01, 0.01, 0.01]}, index=idx)
    weights = pd.DataFrame({"x": [1.0, 1.0, 1.0, 1.0, 1.0]}, index=idx)
    res = sleeves.run_weights(weights, excess, cost=1e-3)
    assert res.gross.tolist() == pytest.approx([0.0, 0.0, 0.01, 0.01, 0.01])   # earns from t+2
    assert res.cost.tolist() == pytest.approx([0.0, 1e-3, 0.0, 0.0, 0.0])      # traded at the t+1 close
