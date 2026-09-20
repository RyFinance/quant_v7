import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from research.insider import evaluate as ev
from research.insider import prices as px
from research.insider import sec_data as sd
from research.insider import signals as sg


# -- synthetic SEC tables ---------------------------------------------------------------------------
def _tables(rows):
    """rows: dicts with acc, filed, doc, cik, sym, owner, rel, title, trans, code, shares, price, ad."""
    sub = pd.DataFrame([{"ACCESSION_NUMBER": r["acc"], "FILING_DATE": pd.Timestamp(r["filed"]),
                         "DOCUMENT_TYPE": r.get("doc", "4"), "ISSUERCIK": r.get("cik", "0000123"),
                         "ISSUERNAME": "X", "ISSUERTRADINGSYMBOL": r.get("sym", "abc")} for r in rows]
                       ).drop_duplicates("ACCESSION_NUMBER")
    own = pd.DataFrame([{"ACCESSION_NUMBER": r["acc"], "RPTOWNERCIK": r.get("owner", "1"), "RPTOWNERNAME": "N",
                         "RPTOWNER_RELATIONSHIP": r.get("rel", "Director"), "RPTOWNER_TITLE": r.get("title")}
                        for r in rows]).drop_duplicates(["ACCESSION_NUMBER", "RPTOWNERCIK"])
    trn = pd.DataFrame([{"ACCESSION_NUMBER": r["acc"], "NONDERIV_TRANS_SK": str(i), "TRANS_DATE": pd.Timestamp(r["trans"]),
                         "TRANS_CODE": r.get("code", "P"), "TRANS_SHARES": float(r.get("shares", 1000)),
                         "TRANS_PRICEPERSHARE": float(r.get("price", 30.0)),
                         "TRANS_ACQUIRED_DISP_CD": r.get("ad", "A" if r.get("code", "P") == "P" else "D")}
                        for i, r in enumerate(rows)])
    return sub, own, trn, sd.cik_ticker_map(sub)


def _om(rows):
    sub, own, trn, ct = _tables(rows)
    return sg.open_market(sub, own, trn, ct)


# -- parsing and tickers ----------------------------------------------------------------------------
def test_parse_sec_date_formats():
    s = pd.Series(["03-JAN-2006", "15-dec-2015", "2020-02-29", None, "garbage"])
    out = sd.parse_sec_date(s)
    assert out.iloc[0] == pd.Timestamp("2006-01-03")
    assert out.iloc[1] == pd.Timestamp("2015-12-15")
    assert out.iloc[2] == pd.Timestamp("2020-02-29")
    assert out.iloc[3:].isna().all()


def test_clean_symbol():
    assert sd.clean_symbol("NYSE: abc") == "ABC"
    assert sd.clean_symbol("brk.b") == "BRK-B"
    assert sd.clean_symbol(" XYZ, XYZW") == "XYZ"
    for bad in ("NONE", "n/a", "", None, float("nan"), "123"):
        assert sd.clean_symbol(bad) is None


def test_cik_ticker_map_follows_changes_and_recycled_symbols():
    sub = pd.DataFrame({
        "ISSUERCIK": ["0001", "0001", "0002", "0003"],
        "FILING_DATE": pd.to_datetime(["2008-01-02", "2012-01-02", "2010-01-04", "2020-01-02"]),
        "ISSUERTRADINGSYMBOL": ["OLD", "NEW", "RECY", "recy"],
    })
    m = sd.cik_ticker_map(sub).set_index("issuer_cik")["ticker"]
    assert m["1"] == "NEW"          # ticker change followed through the CIK
    assert m["3"] == "RECY"         # the recycled symbol goes to the CIK that filed last
    assert "2" not in m.index       # the earlier holder of the recycled symbol is unmatched


def test_zip_links_and_parse_zip(tmp_path):
    html = '<a href="/files/structureddata/data/insider-transactions-data-sets/2006q1_form345.zip">x</a>'
    assert sd.zip_links(html) == ["https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2006q1_form345.zip"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", "\t".join(sd.SUB_COLS + ["REMARKS"]) + "\nA1\t03-JAN-2006\t4\t0000123\tX Inc\tXYZ\tsay \"hi\"\n")
        z.writestr("REPORTINGOWNER.tsv", "\t".join(sd.OWN_COLS) + "\nA1\t0009\tJane\tDirector,Officer\tCEO\n")
        z.writestr("NONDERIV_TRANS.tsv", "\t".join(sd.TRN_COLS) + "\nA1\t1\t02-JAN-2006\tP\t1,000\t25.5\tA\n"
                                                                  "A1\t2\t02-JAN-2006\tM\t500\t1\tA\n")
    p = tmp_path / "2006q1_form345.zip"
    p.write_bytes(buf.getvalue())
    out = sd.parse_zip(p)
    assert out["submissions"]["FILING_DATE"].iloc[0] == pd.Timestamp("2006-01-03")
    assert list(out["trades"]["TRANS_CODE"]) == ["P"]  # option exercise dropped
    assert out["trades"]["TRANS_SHARES"].iloc[0] == 1000.0
    assert set(out["code_counts"]["code"]) == {"P", "M"}


def test_is_csuite():
    yes = ["CEO", "President & CEO", "Chief Financial Officer", "EVP & CFO", "Pres.", "President", "Co-CEO"]
    no = ["Executive Vice President", "SVP, President of Retail Division", "Vice President Finance", "Director",
          "COO", None, "VP"]
    assert all(sg.is_csuite(t) for t in yes)
    assert not any(sg.is_csuite(t) for t in no)


# -- point-in-time filing dates ---------------------------------------------------------------------
def test_open_market_uses_filing_date_and_drops_amendments_forms5_and_stale():
    rows = [
        {"acc": "a", "filed": "2010-03-05", "trans": "2010-03-01"},
        {"acc": "b", "filed": "2010-03-06", "trans": "2010-03-01", "doc": "4/A"},
        {"acc": "c", "filed": "2010-03-06", "trans": "2010-03-01", "doc": "5"},
        {"acc": "d", "filed": "2011-06-01", "trans": "2010-03-01"},          # 457 days late: dropped
        {"acc": "e", "filed": "2010-03-01", "trans": "2010-03-05"},          # trade after filing: error
        {"acc": "f", "filed": "2010-03-05", "trans": "2010-03-01", "code": "P", "ad": "D"},  # inconsistent
    ]
    om, own = _om(rows)
    assert list(om["accession"]) == ["a"]
    assert om["filing_date"].iloc[0] == pd.Timestamp("2010-03-05")
    assert om["value"].iloc[0] == 30_000.0


def test_n2_event_dated_at_filing_not_trade():
    om, own = _om([{"acc": "a", "filed": "2012-05-10", "trans": "2012-05-01", "rel": "Officer", "title": "CEO"}])
    e = sg.events_n2(om, own)
    assert list(e["signal_date"]) == [pd.Timestamp("2012-05-10")]
    om2, own2 = _om([{"acc": "a", "filed": "2012-05-10", "trans": "2012-05-01", "rel": "Officer", "title": "CEO",
                      "shares": 100}])  # $3k < $25k
    assert sg.events_n2(om2, own2).empty
    om3, own3 = _om([{"acc": "a", "filed": "2012-05-10", "trans": "2012-05-01", "rel": "Officer",
                      "title": "Executive Vice President"}])
    assert sg.events_n2(om3, own3).empty


def test_n1_cluster_fires_only_when_second_filing_is_public():
    rows = [
        {"acc": "a", "filed": "2011-04-04", "trans": "2011-04-01", "owner": "1"},
        {"acc": "b", "filed": "2011-04-20", "trans": "2011-04-15", "owner": "2"},
    ]
    om, own = _om(rows)
    e = sg.events_n1(om, own)
    assert list(e["signal_date"]) == [pd.Timestamp("2011-04-20")]
    # the second purchase filed late: on its filing date the first purchase is > 30 days old, and the
    # second trade itself is outside the window too, so no event ever fires
    rows[1].update({"filed": "2011-06-10", "trans": "2011-05-01"})
    om, own = _om(rows)
    e = sg.events_n1(om, own)
    assert e.empty
    # a single insider buying twice is not a cluster
    om, own = _om([{"acc": "a", "filed": "2011-04-04", "trans": "2011-04-01", "owner": "1"},
                   {"acc": "b", "filed": "2011-04-06", "trans": "2011-04-05", "owner": "1"}])
    assert sg.events_n1(om, own).empty
    # ten-percent owners who are neither officers nor directors do not count
    om, own = _om([{"acc": "a", "filed": "2011-04-04", "trans": "2011-04-01", "owner": "1"},
                   {"acc": "b", "filed": "2011-04-06", "trans": "2011-04-05", "owner": "2", "rel": "TenPercentOwner"}])
    assert sg.events_n1(om, own).empty


def test_cmp_classification_is_point_in_time():
    base = [{"acc": f"s{y}", "filed": f"{y}-03-10", "trans": f"{y}-03-05", "code": "S", "owner": "7"}
            for y in (2006, 2007)]
    routine = base + [{"acc": "s2008", "filed": "2008-03-10", "trans": "2008-03-05", "code": "S", "owner": "7"}]
    om, own = _om(routine)
    c = sg.classify_cmp(om, own, 2009)
    assert list(c["kind"]) == ["routine"]
    opp = base + [{"acc": "s2008", "filed": "2008-07-10", "trans": "2008-07-05", "code": "S", "owner": "7"}]
    om, own = _om(opp)
    assert list(sg.classify_cmp(om, own, 2009)["kind"]) == ["opportunistic"]
    # the 2008 trade filed in January 2009 is not known at the start of 2009: unclassified
    late = base + [{"acc": "s2008", "filed": "2009-01-05", "trans": "2008-12-20", "code": "S", "owner": "7"}]
    om, own = _om(late)
    assert sg.classify_cmp(om, own, 2009).empty


def test_n3_events_need_opportunistic_classification():
    hist = [{"acc": f"s{y}", "filed": f"{y}-0{m}-10", "trans": f"{y}-0{m}-05", "code": "S", "owner": "7"}
            for y, m in ((2006, 3), (2007, 5), (2008, 7))]
    buy = {"acc": "p", "filed": "2009-02-10", "trans": "2009-02-06", "code": "P", "owner": "7"}
    om, own = _om(hist + [buy])
    e = sg.events_n3(om, own)
    assert list(e["signal_date"]) == [pd.Timestamp("2009-02-10")]
    other = dict(buy, owner="8", acc="q")  # an unclassified insider in the same firm
    om, own = _om(hist + [other])
    assert sg.events_n3(om, own).empty


# -- entry timing and the universe filter -----------------------------------------------------------
def _panel(n_days=60, tickers=("A", "B", "C"), price=20.0, dvol_shares=200_000):
    cal = pd.bdate_range("2010-01-04", periods=n_days)
    raw = pd.DataFrame(price, index=cal, columns=list(tickers))
    dv = pd.DataFrame(price * dvol_shares, index=cal, columns=list(tickers))
    return cal, raw, dv


def test_entry_is_the_session_after_the_filing_date():
    cal, raw, dv = _panel()
    passes, _ = ev.filter_and_costs(raw, dv)
    has_open = np.ones(raw.shape, dtype=bool)
    d_trading = cal[30]
    d_saturday = cal[34] + pd.Timedelta(days=1)  # cal[34] is a Friday
    assert cal[34].dayofweek == 4
    evs = pd.DataFrame({"ticker": ["A", "B"], "signal_date": [d_trading, d_saturday]})
    placed, counts = ev.place_events(evs, cal, raw.columns, passes.to_numpy(), has_open)
    assert list(placed["s"]) == [30, 34] and list(placed["entry"]) == [31, 35]
    assert counts == {"events": 2, "with_prices": 2, "pass_filter": 2, "entered": 2}


def test_filter_has_no_look_ahead():
    cal, raw, dv = _panel()
    p1, c1 = ev.filter_and_costs(raw, dv)
    s = 30
    raw2, dv2 = raw.copy(), dv.copy()
    raw2.iloc[s + 1:] = 1.0          # price collapses after the filter date
    dv2.iloc[s + 1:] = 0.0
    p2, c2 = ev.filter_and_costs(raw2, dv2)
    pd.testing.assert_frame_equal(p1.iloc[:s + 1], p2.iloc[:s + 1])
    pd.testing.assert_frame_equal(c1.iloc[:s + 2], c2.iloc[:s + 2])  # the cost at t uses ADV through t-1
    # conversely, a stock that only becomes eligible later is not eligible at s
    raw3 = raw.copy()
    raw3.iloc[: s + 1, 0] = 4.0
    p3, _ = ev.filter_and_costs(raw3, dv)
    assert not p3.iloc[s, 0] and p3.iloc[s + 1:, 0].iloc[ev.ADV_WINDOW:].all()


def test_filter_needs_full_adv_history_and_thresholds():
    cal, raw, dv = _panel()
    p, _ = ev.filter_and_costs(raw, dv)
    assert not p.iloc[ev.ADV_WINDOW - 2].any() and p.iloc[ev.ADV_WINDOW - 1].all()
    dv_low = dv * (1.9e6 / dv.iloc[0, 0])
    p_low, _ = ev.filter_and_costs(raw, dv_low)
    assert not p_low.to_numpy().any()
    p_price, _ = ev.filter_and_costs(raw * (4.99 / 20.0), dv)
    assert not p_price.to_numpy().any()


def test_raw_price_undoes_later_splits_only():
    # a 10:1 forward split on day 2: the stock traded at $40, then $4. yfinance shows split-adjusted closes
    # of $4 throughout, which would wrongly fail the $5 filter before the split.
    f = pd.DataFrame({"date": pd.bdate_range("2010-01-04", periods=4), "open": [4.0, 4.0, 4.0, 4.1],
                      "high": 0.0, "low": 0.0, "close": [4.0, 4.0, 4.0, 4.1], "adj_close": [3.9, 3.9, 3.9, 4.0],
                      "volume": [1e6] * 4, "splits": [0.0, 0.0, 10.0, 0.0]})
    d = px.derive(f)
    assert list(d["raw_close"]) == pytest.approx([40.0, 40.0, 4.0, 4.1])
    assert d["dollar_vol"].iloc[0] == pytest.approx(4.0 * 1e6)   # = $40 x 100k raw shares
    assert d["open_tr"].iloc[0] == pytest.approx(4.0 * 3.9 / 4.0)  # open on the total-return scale


def test_events_without_filter_pass_or_open_are_skipped():
    cal, raw, dv = _panel()
    raw.iloc[:, 1] = 3.0
    passes, _ = ev.filter_and_costs(raw, dv)
    has_open = np.ones(raw.shape, dtype=bool)
    has_open[41, 2] = False
    evs = pd.DataFrame({"ticker": ["A", "B", "C", "ZZZ"], "signal_date": [cal[40]] * 4})
    placed, counts = ev.place_events(evs, cal, raw.columns, passes.to_numpy(), has_open)
    assert list(placed["ticker"]) == ["A"]
    assert counts == {"events": 4, "with_prices": 3, "pass_filter": 2, "entered": 1}


# -- book and cost accounting -----------------------------------------------------------------------
def _flat(T, K):
    return np.ones((T, K)), np.ones((T, K))


def test_single_position_pays_cost_on_entry_and_exit_only():
    T, K = 10, 2
    gap, intra = _flat(T, K)
    cost = np.full((T, K), 0.0015)
    rf = np.zeros(T)
    act = np.zeros((T, K), dtype=bool)
    act[2:5, 0] = True  # hold 3 sessions: enter open of 2, exit open of 5
    bk = ev.run_book(act, gap, intra, cost, rf)
    assert bk["net"].iloc[2] == pytest.approx(-0.0015)
    assert bk["net"].iloc[5] == pytest.approx(-0.0015)
    assert bk["net"].drop([2, 5]).abs().max() < 1e-15
    assert bk["gross"].abs().max() < 1e-15
    assert bk["stress"].iloc[2] == pytest.approx(-0.0030)
    assert bk["turnover"].sum() == pytest.approx(2.0)
    assert list(bk["positions"]) == [0, 0, 1, 1, 1, 0, 0, 0, 0, 0]


def test_turnover_is_exact_when_a_second_name_enters_after_drift():
    T, K = 6, 2
    gap, intra = _flat(T, K)
    intra[1, 0] = 1.10                   # name 0 gains 10% on day 1
    cost = np.zeros((T, K))
    cost[:, 0], cost[:, 1] = 0.0005, 0.0040
    act = np.zeros((T, K), dtype=bool)
    act[1:, 0] = True
    act[2:, 1] = True
    bk = ev.run_book(act, gap, intra, cost, np.zeros(T))
    # day 2: drifted weight of name 0 is 1.0 -> target 0.5 each: sell 0.5 of name 0, buy 0.5 of name 1
    assert bk["turnover"].iloc[2] == pytest.approx(1.0)
    assert bk["cost"].iloc[2] == pytest.approx(0.5 * 0.0005 + 0.5 * 0.0040)
    assert bk["net"].iloc[1] == pytest.approx(1.0 * (1 - 0.0005) * 1.10 - 1)
    assert bk["cost"].iloc[3:].sum() == 0.0  # no rebalance while the active set is unchanged


def test_idle_book_earns_tbills_and_overnight_gap_is_counted():
    T, K = 5, 1
    gap, intra = _flat(T, K)
    gap[2, 0] = 1.05
    intra[2, 0] = 1.02
    rf = np.full(T, 0.0001)
    act = np.zeros((T, K), dtype=bool)
    act[1:3, 0] = True
    bk = ev.run_book(act, gap, intra, np.zeros((T, K)), rf)
    assert bk["net"].iloc[0] == pytest.approx(0.0001)          # all cash
    assert bk["net"].iloc[2] == pytest.approx(1.05 * 1.02 - 1)  # held through the gap and the day
    assert bk["net"].iloc[3] == pytest.approx(1.0 * (1 + 0.0001) - 1)  # sold at the open, cash after


def test_cost_tiers():
    idx = pd.bdate_range("2010-01-04", periods=25)
    dv = pd.DataFrame({"big": 60e6, "mid": 10e6, "small": 3e6, "edge": 50e6}, index=idx)
    raw = pd.DataFrame(10.0, index=idx, columns=dv.columns)
    _, cost = ev.filter_and_costs(raw, dv)
    last = cost.iloc[-1]
    assert last["big"] == 0.0005 and last["mid"] == 0.0015 and last["small"] == 0.0040 and last["edge"] == 0.0015
    assert (cost.iloc[: ev.ADV_WINDOW] == 0.0040).all().all()  # unknown ADV is charged the top tier


def test_hedge_costs_and_beta():
    T = 300
    rng = np.random.default_rng(1)
    mkt = rng.normal(0, 0.01, T)
    x = 1.5 * mkt + rng.normal(0, 0.001, T)
    inv = np.ones(T, dtype=bool)
    hedged, h = ev.hedge(x, inv, mkt)
    assert np.all(h[: ev.HEDGE["min_obs"]] == 1.0)
    assert h[-1] == pytest.approx(1.5, abs=0.05)
    t = 200
    expect = x[t] - h[t] * mkt[t] - h[t] * ev.HEDGE["borrow"] / 252 - abs(h[t] - h[t - 1]) * ev.HEDGE["trade"]
    assert hedged[t] == pytest.approx(expect)
    hedged2, _ = ev.hedge(x, inv, mkt, mult=2.0)
    assert np.all(hedged2 <= hedged + 1e-15)
    idle, h0 = ev.hedge(np.zeros(T), np.zeros(T, dtype=bool), mkt)
    assert np.all(h0 == 0) and np.all(idle == 0)


def test_control_draws_use_the_same_dates_and_filter():
    cal, raw, dv = _panel(tickers=("A", "B", "C", "D"))
    raw.iloc[:, 3] = 2.0   # D never passes
    passes, _ = ev.filter_and_costs(raw, dv)
    has_open = np.ones(raw.shape, dtype=bool)
    has_open[41, 2] = False  # C has no open on the entry day
    evs = pd.DataFrame({"ticker": ["A"] * 30, "signal_date": [cal[40]] * 30})
    placed, _ = ev.place_events(evs, cal, raw.columns, passes.to_numpy(), has_open)
    cp = ev.control_placements(placed, passes.to_numpy(), has_open, seed=3)
    assert set(cp["j"]) <= {0, 1}
    assert (cp["s"] == placed["s"]).all() and (cp["entry"] == placed["entry"]).all()
    cp2 = ev.control_placements(placed, passes.to_numpy(), has_open, seed=3)
    assert (cp["j"] == cp2["j"]).all()


# -- validation lock --------------------------------------------------------------------------------
def test_validation_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "PREREG", tmp_path / "preregistrations.jsonl")
    ev.check_upto(ev.DEV_END)
    with pytest.raises(PermissionError):
        ev.check_upto(ev.DEV_END + pd.Timedelta(days=1))
    unlock = tmp_path / ev.UNLOCK
    unlock.parent.mkdir(parents=True)
    unlock.write_text("unlock")
    (tmp_path / "preregistrations.jsonl").write_text(json.dumps({"file": ev.UNLOCK, "sha256": "wrong"}) + "\n")
    with pytest.raises(PermissionError):
        ev.check_upto(ev.VAL_END)
    import hashlib
    good = hashlib.sha256(b"unlock").hexdigest()
    (tmp_path / "preregistrations.jsonl").write_text(json.dumps({"file": ev.UNLOCK, "sha256": good}) + "\n")
    ev.check_upto(ev.VAL_END)


def _write_parsed(tmp_path, rows):
    sub, own, trn, ct = _tables(rows)
    om, ow = sg.open_market_raw(sub, own, trn)
    om.to_parquet(tmp_path / "om.parquet", index=False)
    ow.to_parquet(tmp_path / "own.parquet", index=False)
    ct.to_parquet(tmp_path / "cik_ticker.parquet", index=False)


def test_load_open_market_truncates_at_filing_date(tmp_path, monkeypatch):
    _write_parsed(tmp_path, [
        {"acc": "a", "filed": "2015-12-31", "trans": "2015-12-29"},
        {"acc": "b", "filed": "2016-01-04", "trans": "2015-12-30", "owner": "2"},
    ])
    monkeypatch.setattr(sd, "DATA", tmp_path)
    om, own = sd.load_open_market(upto=ev.DEV_END)
    assert list(om["accession"]) == ["a"] and list(own["accession"]) == ["a"]
    assert list(om["ticker"]) == ["ABC"]
    om_all, _ = sd.load_open_market()
    assert len(om_all) == 2


def test_parse_all_quarter_by_quarter_matches_single_pass(tmp_path, monkeypatch):
    def zip_bytes(sub_rows, own_rows, trn_rows):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("SUBMISSION.tsv", "\t".join(sd.SUB_COLS) + "\n" + "\n".join("\t".join(r) for r in sub_rows) + "\n")
            z.writestr("REPORTINGOWNER.tsv", "\t".join(sd.OWN_COLS) + "\n" + "\n".join("\t".join(r) for r in own_rows) + "\n")
            z.writestr("NONDERIV_TRANS.tsv", "\t".join(sd.TRN_COLS) + "\n" + "\n".join("\t".join(r) for r in trn_rows) + "\n")
        return buf.getvalue()
    raw = tmp_path / "raw"
    raw.mkdir()
    # issuer 1 files as OLD in 2006, then as NEW in 2007; issuer 2 once uses the symbol NONE
    (raw / "2006q1_form345.zip").write_bytes(zip_bytes(
        [["A1", "03-JAN-2006", "4", "0000001", "X", "OLD"], ["A2", "05-JAN-2006", "4", "0000002", "Y", "NONE"]],
        [["A1", "0009", "J", "Director", ""], ["A2", "0008", "K", "Officer", "CEO"]],
        [["A1", "1", "02-JAN-2006", "P", "100", "10", "A"], ["A2", "2", "04-JAN-2006", "S", "5", "10", "D"]]))
    (raw / "2007q1_form345.zip").write_bytes(zip_bytes(
        [["B1", "03-JAN-2007", "4", "0000001", "X", "NEW"]],
        [["B1", "0009", "J", "Director", ""]],
        [["B1", "3", "02-JAN-2007", "P", "100", "12", "A"]]))
    monkeypatch.setattr(sd, "DATA", tmp_path)
    monkeypatch.setattr(sd, "RAW", raw)
    monkeypatch.setattr(sd, "PARSED", tmp_path / "parsed")
    sd.parse_all()
    om, own = sd.load_open_market()
    assert sorted(om["accession"]) == ["A1", "A2", "B1"]
    assert set(om.loc[om["issuer_cik"] == "1", "ticker"]) == {"NEW"}   # old filings follow the CIK
    assert om.loc[om["accession"] == "A2", "ticker"].isna().all()      # never had a usable symbol
    assert own.set_index("accession").loc["A2", "is_csuite"]
    fc = pd.read_parquet(tmp_path / "filing_counts.parquet")
    assert fc["n"].sum() == 3


# -- end to end on synthetic data -------------------------------------------------------------------
def test_dev_run_end_to_end_on_synthetic_data(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    cal = pd.bdate_range("2005-10-03", "2016-03-31")
    tickers = [f"T{i}" for i in range(12)]
    pdir = tmp_path / "prices"
    pdir.mkdir()
    for t in tickers:
        c = 20 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, len(cal))))
        o = c * np.exp(rng.normal(0, 0.005, len(cal)))
        pd.DataFrame({"date": cal, "open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c,
                      "adj_close": c, "volume": 500_000.0, "splits": 0.0}).to_parquet(pdir / f"{t}.parquet", index=False)
    closes = {t: pd.read_parquet(pdir / f"{t}.parquet").set_index("date")["close"] for t in tickers}
    rows, k = [], 0
    for y in range(2006, 2016):
        for i, t in enumerate(tickers[:6]):
            # A sells every February (routine under CMP); B sells in a month that moves each year
            # (opportunistic); both buy together once a year (a cluster, and a C-suite purchase by A)
            for owner, rel, title, sell_m in (("A" + t, "Director,Officer", "President & CEO", 2),
                                              ("B" + t, "Director", None, 1 + (y % 3))):
                for m, code in ((sell_m, "S"), (6 + (y + i) % 5, "P")):
                    d = pd.Timestamp(y, m, 10 + i)
                    px_d = float(closes[t].loc[:d].iloc[-1])
                    rows.append({"acc": f"x{k}", "filed": d + pd.Timedelta(days=2), "trans": d, "cik": f"{i + 1:07d}",
                                 "sym": t, "owner": owner, "rel": rel, "title": title, "code": code,
                                 "price": px_d, "shares": int(40_000 / px_d) + 1})
                    k += 1
    sdir = tmp_path / "sec"
    sdir.mkdir()
    _write_parsed(sdir, rows)
    ff = pd.DataFrame({"mkt_rf": rng.normal(0.0003, 0.01, len(cal)), "rf": 0.00005}, index=cal)
    monkeypatch.setattr(sd, "DATA", sdir)
    monkeypatch.setattr(px, "PX_DIR", pdir)
    monkeypatch.setattr(ev, "OUT", tmp_path / "reports")
    monkeypatch.setattr(ev, "PREREG", tmp_path / "prereg.jsonl")
    monkeypatch.setattr(ev, "french_daily", lambda: ff)
    monkeypatch.setattr(ev, "N_CONTROL", 3)
    monkeypatch.setattr(ev, "DRAWS", 200)
    r = ev.run("dev")
    assert set(r["candidates"]) == set(ev.CANDIDATES)
    for name, c in r["candidates"].items():
        b = c["base"]
        assert np.isfinite(b["sharpe"]) and b["mean_positions"] > 0
        assert b["sharpe_gross"] >= b["sharpe"] - 1e-9 >= c["stress"]["sharpe"] - 2e-9
        assert len(c["control"]["control_sharpe_draws"]) == 3
    assert r["candidates"]["N3_opportunistic"]["eval_start"] == "2009-01-01"
    daily = pd.read_csv(tmp_path / "reports" / "dev" / "N1_cluster_daily.csv", index_col=0, parse_dates=True)
    assert daily.index.max() <= ev.DEV_END and daily.index.min() >= ev.DEV_START
    assert (tmp_path / "reports" / "dev" / "selection.json").exists()
    with pytest.raises(SystemExit):
        ev.run("validation")


def test_fast_n1_matches_reference_rule():
    rng = np.random.default_rng(5)
    rows = []
    for k in range(600):
        filed = pd.Timestamp("2010-01-04") + pd.Timedelta(days=int(rng.integers(0, 400)))
        rows.append({"acc": f"a{k}", "filed": filed, "trans": filed - pd.Timedelta(days=int(rng.integers(0, 45))),
                     "cik": f"{int(rng.integers(1, 6)):07d}", "sym": f"S{int(rng.integers(1, 6))}",
                     "owner": str(int(rng.integers(1, 12))), "rel": ["Director", "Officer", "TenPercentOwner"][k % 3],
                     "shares": int(rng.integers(100, 3000)), "price": 10.0})
    om, own = _om(rows)
    fast, ref = sg.events_n1(om, own), sg._events_n1_reference(om, own)
    assert len(ref) > 20
    pd.testing.assert_frame_equal(fast.reset_index(drop=True), ref.reset_index(drop=True))


def test_a2_price_consistency():
    om, own = _om([
        {"acc": "ok", "filed": "2012-03-07", "trans": "2012-03-05", "price": 30.0},
        {"acc": "hi", "filed": "2012-03-07", "trans": "2012-03-05", "price": 61.0},          # > 2x
        {"acc": "lo", "filed": "2012-03-07", "trans": "2012-03-05", "price": 14.0},          # < 0.5x
        {"acc": "sale", "filed": "2012-03-07", "trans": "2012-03-05", "price": 999.0, "code": "S"},
        {"acc": "early", "filed": "2012-01-06", "trans": "2012-01-04", "price": 30.0},       # before prices
        {"acc": "stale", "filed": "2012-04-20", "trans": "2012-04-18", "price": 30.0},       # 16 days after last close
    ])
    closes = pd.Series([30.0, 30.0, 29.0], index=pd.to_datetime(["2012-02-01", "2012-03-02", "2012-04-02"]))
    ok = sg.price_consistent(om, lambda t: closes if t == "ABC" else None)
    got = dict(zip(om["accession"], ok))
    assert got == {"ok": True, "hi": False, "lo": False, "sale": True, "early": False, "stale": False}
    # a purchase without a mapped ticker or without prices never counts
    om2 = om.assign(ticker=None)
    assert not sg.price_consistent(om2, lambda t: closes)[(om2["code"] == "P").to_numpy()].any()
    assert not sg.price_consistent(om, lambda t: None)[(om["code"] == "P").to_numpy()].any()


def test_a1_universe_is_recent_filers(tmp_path, monkeypatch):
    d = tmp_path / "data" / "sec_insider"
    d.mkdir(parents=True)
    pd.DataFrame({"issuer_cik": ["1", "2", "3"], "ticker": ["NEW", "OLD", "EDGE"],
                  "last_filing": pd.to_datetime(["2026-05-01", "2019-03-01", "2025-01-01"]),
                  "n_filings": [5, 5, 5]}).to_parquet(d / "cik_ticker.parquet", index=False)
    monkeypatch.setattr(px, "ROOT", tmp_path)
    assert px.universe_tickers() == ["EDGE", "NEW"]


def test_a2_filters_triggers_but_not_the_n3_history():
    hist = [{"acc": f"s{y}", "filed": f"{y}-0{m}-10", "trans": f"{y}-0{m}-05", "code": "S", "owner": "7"}
            for y, m in ((2006, 3), (2007, 5))]
    hist.append({"acc": "p2008", "filed": "2008-07-10", "trans": "2008-07-05", "code": "P", "owner": "7"})
    buy = {"acc": "p", "filed": "2009-02-10", "trans": "2009-02-06", "code": "P", "owner": "7"}
    om, own = _om(hist + [buy])
    # the 2008 purchase fails the price check: it may not trigger anything, but it still completes the
    # owner's three-year history, so the 2009 purchase (which passes) is an opportunistic event
    valid = (om["accession"] != "p2008").to_numpy()
    ev = sg.all_events(om, own, valid=valid)
    assert list(ev["N3_opportunistic"]["signal_date"]) == [pd.Timestamp("2009-02-10")]
    # and if the 2009 purchase itself fails, there is no event
    ev2 = sg.all_events(om, own, valid=(om["accession"] != "p").to_numpy())
    assert ev2["N3_opportunistic"].empty


def _bars(opens, closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({"date": pd.bdate_range("2012-01-02", periods=n), "open": opens,
                         "high": highs if highs is not None else [max(a, b) for a, b in zip(opens, closes)],
                         "low": lows if lows is not None else [min(a, b) for a, b in zip(opens, closes)],
                         "close": closes, "adj_close": closes, "volume": [1e6] * n, "splits": [0.0] * n})


def test_b1_bad_opens_become_missing():
    # day 2: open 10x both neighbours (bogus); day 4: genuine +150% gap that holds into the close
    d = px.derive(_bars([10, 10, 100, 10, 25, 25], [10, 10, 10, 10, 26, 25],
                        highs=[10, 10, 10, 10, 27, 26], lows=[10, 10, 10, 10, 24, 24]))
    assert np.isnan(d["open_tr"].iloc[2])        # also outside the day's range
    assert d["open_tr"].iloc[4] == 25            # real gap kept
    d2 = px.derive(_bars([10, 10, 30, 10], [10, 10, 10, 10], highs=[10, 10, 31, 10], lows=[10, 10, 9, 10]))
    assert np.isnan(d2["open_tr"].iloc[2])       # inside a (bogus) range, but 3x from both closes


def test_b2_close_spike_cleans_returns_but_not_the_filter():
    d = px.derive(_bars([10, 10, 10, 10, 10], [10, 10, 50, 10, 10]))
    assert np.isnan(d["close_tr"].iloc[2])       # carried forward in fill_prices
    assert d["raw_close"].iloc[2] == 50          # the filter sees what was reported that day
    # a spike on the last in-window day cannot be judged: the next close is outside the window
    d_dev = px.derive(_bars([10, 10, 10, 10, 10], [10, 10, 10, 50, 10]), upto=pd.Timestamp("2012-01-05"))
    assert d_dev["close_tr"].iloc[-1] == 50 and d_dev.index.max() == pd.Timestamp("2012-01-05")
    # a genuine jump that holds is kept
    d3 = px.derive(_bars([10, 10, 40, 40, 40], [10, 10, 40, 41, 40]))
    assert d3["close_tr"].iloc[2] == 40


def test_book_is_not_moved_by_a_cleaned_bogus_open():
    closes = [10.0] * 8
    opens = [10.0, 10.0, 10.0, 100.0, 10.0, 10.0, 10.0, 10.0]  # bogus open on day 3 (a rebalance day)
    d = px.derive(_bars(opens, closes, highs=[10.0] * 8, lows=[10.0] * 8))
    gap, intra = ev.fill_prices(d[["open_tr"]], d[["close_tr"]])
    act = np.zeros((8, 2), dtype=bool)
    act[1:, 0] = True
    act[3:, 1] = True   # a second name enters on day 3, forcing a rebalance at the bogus open
    g2, i2 = np.hstack([gap, np.ones((8, 1))]), np.hstack([intra, np.ones((8, 1))])
    bk = ev.run_book(act, g2, i2, np.zeros((8, 2)), np.zeros(8))
    assert bk["gross"].abs().max() < 1e-12      # flat prices: no spurious gain
