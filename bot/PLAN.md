# PEAD paper-trading bot -- architecture & plan

**Status of the underlying signal**: `earnings/` implements a real PEAD
(post-earnings-announcement-drift) signal on real SUE computed from real
yfinance analyst-estimate data. It looks more promising than the abandoned
mean-reversion strategy (Phases 3-6), but it is **still being statistically
validated in a parallel track right now** -- this bot is scaffolding built
to be *ready* to paper-trade that signal once validation lands, not a
declaration that validation is finished. Nothing here assumes the PEAD
result is confirmed.

**Hard constraint, restated**: PAPER TRADING ONLY. No module in `bot/`
places, or is capable of placing, a real order against a real brokerage or
exchange account. No real API credentials are embedded or referenced
anywhere in this package. No continuously-running loop, scheduler, or cron
job exists or was started -- this is architecture and working components,
wired together and tested, not a deployment.

---

## 1. What was extracted from polymarket_arb, and the transfer judgment

Read (not modified): `polymarket_arb/polymarket_arb/{risk,alerting,arb_engine,
backtest_engine,config,models,logger}.py`, `clients/*`,
`monitoring/watchdog.py`, `streamlit_app.py` / `dashboard_status.py` /
`product_status.py`.

| Piece | Transfers directly? | Judgment |
|---|---|---|
| `risk.py`'s HARD FAIL-SAFE **pattern** (pure math, first-failure ABORTS, checked in a fixed order, no partial sizing/"reduce and retry") | **Pattern yes, code no** | This is the single most valuable thing in the read-through. quant_v7's own `risk/limits.py` *already* mirrors this pattern (its docstring says so explicitly, citing `polymarket_arb/risk.py:3`). `bot/risk_gate.py` extends `risk/limits.check_risk_limits` rather than re-deriving the stance a third time. |
| `risk.py`'s specific checks (balance, stale book, per-side liquidity, daily kill-switch $, emergency-stop file, macro-event window) | **No** | These are CLOB/arb-specific (order-book liquidity, dual-leg staleness, macro-news 2-hour windows around a rates decision). A single-name equity PEAD trade has no "book" to check for staleness and no macro-event-window concept quant_v7 has built. The **emergency-stop-file mechanic itself** (existence of a sentinel file = hard block) transfers with zero adaptation -- see `bot/kill_switch.py`. |
| `alerting.py`'s `WebhookAlerter` (no-op-when-unconfigured webhook + always-on local JSONL + dedup window) | **Pattern already ported once** | `circuit_breaker/alerts.py` already mirrors this shape verbatim (confirmed by reading it side-by-side with the original). `bot/alerting.py` is a third instance of the *same* shape, for bot-level events (position open/close, risk-blocked, breaker-halt, kill-switch), not a reimplementation from scratch. |
| `alerting.py`'s `Heartbeat` + `monitoring/watchdog.py` (external liveness monitor, stale-heartbeat -> crash alert) | **Not built** | Requires an actual running process to heartbeat against. This task explicitly forbids starting one ("do not build or start any actual continuously-running loop"), so there is nothing for a watchdog to watch yet. The pattern is noted here for whenever a real scheduled run exists. |
| `arb_engine.py` (combined-YES+NO-ask edge detection, dual-leg debounce) | **No** | Fundamentally a two-sided prediction-market arbitrage concept. PEAD is a single-name directional drift trade; there is no second leg. |
| `execution.py` (precomputed order templates, `asyncio.gather` dual-leg submit, partial-fill hedge-or-exit state machine) | **No, but the shape of the split does** | The CLOB order-book/fill model doesn't map onto equities at all. What *does* transfer is the explicit **paper vs. live execution-client split** (`config.py`'s `dry_run`/`paper_trade`/`live`, `clients/trading_client.py`'s "paper simulates a fill against a real book, live is a separate hard-gated path"). `bot/execution.py`'s `PaperExecutionClient`/`LiveExecutionClient` split is that same idea, ported to a broker-API shape (no order book, single real current-price fill) instead of a CLOB shape. |
| `config.py`'s `live` property / `live_signing_verified` gate, and `clients/trading_client.py`'s comment "live order submission is intentionally unbuilt and fails closed" | **Pattern transfers, strengthened** | polymarket_arb still *has* a live code path (gated behind flags a human sets). This task requires going further: `LiveExecutionClient` here is not gated behind a flag, it is an unconditional `NotImplementedError`. Deliberately stricter than the source pattern. |
| `models.py` (`MarketState`/`TradeRecord` hot-path dataclasses) | **No** | Tuned for per-tick WS book mutation. This bot has no tick loop; `bot/execution.py`'s `PaperPosition`/`PaperFill` are shaped for a fixed-holding-period equity trade instead. |
| `logger.py` (compact console + JSONL) | **Not reused directly** | quant_v7 already standardized on `loguru` (see every existing module). Re-introducing a second bespoke logger would fragment logging conventions for no benefit; the JSONL-ledger *idea* is reused (see `bot/alerting.py`, `bot/execution.py`'s ledger) even though the specific `BotLogger` class is not. |
| `scripts/*` watchdog/kill-switch-adjacent scripts (`preflight_check.py`, `verify_live_control.py`, `e2_alert_test_harness.py`) | **No, pattern noted** | Polymarket-CLOB-specific preflight checks (approvals, signing verification). The *category* of "a script that verifies safety invariants before anything runs" is worth having for this bot eventually (e.g. "is the kill switch clear, is the model cache fresh"), but building a new script wasn't asked for in this task and risked scope creep into deployment tooling. |
| `streamlit_app.py` / `dashboard_status.py` / `product_status.py` (live dashboard reading JSONL/state files) | **Not built** | A dashboard is a real, useful next step given `bot/execution.py`'s JSONL ledger and `bot/alerting.py`'s JSONL alert log are already exactly the kind of data these dashboards read. Out of scope for this task (scaffolding, not a UI), noted for later. |

---

## 2. Architecture

```
                      +---------------------------+
                      |   earnings_watcher.py      |
                      |  yfinance calendar query   |
                      |  (validated 75-name        |
                      |   universe only)           |
                      +-------------+---------------+
                                    |
                 upcoming (watch)   |   just-reported (trigger)
                                    v
                      +---------------------------+
                      |   signal_pipeline.py       |
                      |  earnings/sue.py           |
                      |   -> earnings/features.py  |
                      |   -> ml/ensemble.py        |
                      |      (fit_or_load, joblib  |
                      |       cached)               |
                      |   -> ml/calibration.py     |
                      |  = calibrated probability   |
                      +-------------+---------------+
                                    |
                                    v
                      +---------------------------+
                      |      risk_gate.py          |  <-- the ONLY path to an order
                      |  1. kill_switch file?      |
                      |  2. capital drawdown cap?  |
                      |  3. circuit_breaker tier   |
                      |     (breaker.py/triggers)  |
                      |  4. risk/limits.py caps    |
                      |  5. risk/kelly.py size>0   |
                      |  -> single-use approval    |
                      |     token or denial        |
                      +-------------+---------------+
                                    | approval token (single use)
                                    v
                      +---------------------------+
                      |       execution.py         |
                      |  PaperExecutionClient       |
                      |  fills at REAL current      |
                      |  price (yfinance), writes   |
                      |  JSONL ledger + position    |
                      |  book. token consumed here. |
                      |                             |
                      |  LiveExecutionClient:       |
                      |  NotImplementedError        |
                      |  (always)                   |
                      +-------------+---------------+
                                    |
                                    v
                      +---------------------------+
                      |    position_manager.py     |
                      |  holds position exactly    |
                      |  HOLDING_PERIOD_DAYS=20     |
                      |  trading days (earnings/     |
                      |  labeling.py), then exits    |
                      |  via execution client's      |
                      |  real current price. NO      |
                      |  adaptive TP/SL -- not what  |
                      |  the validated backtest did. |
                      +---------------------------+

Every stage's kill_switch/risk/circuit-breaker events, plus every position
open/close, are alerted via bot/alerting.py (JSONL log, no-op webhook) --
mirrors circuit_breaker/alerts.py's already-established pattern.
```

## 3. The pipeline, stage by stage

1. **`earnings_watcher.EarningsWatcher`** watches the Phase-1 validated
   universe (`reports/universe_selection.txt`, the same 75 tickers PEAD was
   built and backtested on -- never a different or expanded universe).
   `get_upcoming_earnings` answers "what reports in the next N days"
   (a real, working yfinance calendar query). `get_recently_reported`
   answers "what just reported" -- this is the actual entry trigger, since
   PEAD needs the real surprise, which only exists post-report.

2. **`signal_pipeline`** turns one just-reported event into a calibrated
   probability: `earnings.ingestion.fetch_ticker_earnings` (real trailing
   history for that ticker) -> `earnings.sue.compute_sue` (real SUE, same
   causal trailing-std construction as the validated build) ->
   feature row matching `earnings.features.PEAD_FEATURE_COLUMNS` ->
   `ml.ensemble.FittedEnsemble.predict_proba` -> `ml.calibration.Calibrator.
   transform`. The ensemble/calibrator/Kelly-payoff-ratio are fit once
   against the SAME cached `data/pead_labeled_features.parquet` used by
   `reports/run_pead_backtest.py`, then persisted via `joblib` to
   `bot/state/model/pead_model.joblib` (see `signal_pipeline.py`'s
   docstring for why: no model-persistence layer existed anywhere in
   quant_v7 before this, and re-fitting from scratch on every invocation,
   while correct, is unnecessary given PEAD decisions are not
   latency-sensitive the way a CLOB arb is).

   **Documented deviation**: the historical feature build computes
   `pre_earnings_return_5d/20d` from *residualized* (market-beta-stripped)
   returns via the Phase-1/2 batch pipeline. Live scoring here uses *raw*
   trailing returns from freshly fetched prices instead, because there is
   no live residual-return pipeline running in this scaffolding. This is a
   real, working number from real data -- but not the same feature
   distribution the model trained on. A real deployment should close this
   gap (e.g. run the Phase-1/2 residual pipeline on a schedule) before
   trusting live probabilities at face value.

3. **`risk_gate.evaluate`** is the sole choke point. Order, first failure
   blocks (mirrors `risk.py`'s HARD FAIL-SAFE stance):
   1. `kill_switch.is_kill_switch_engaged()` -- sentinel file check.
   2. `kill_switch.check_capital_drawdown_cap()` -- breach auto-engages the
      kill switch (a safety trip wire; see that module's docstring for why
      this is the one case the bot is allowed to write its own kill file,
      and why that is not a live-trading enablement path).
   3. `circuit_breaker` tier via `risk_gate.current_breaker_tier()`, which
      replays `circuit_breaker.triggers`/`market_correlation`/`breaker`
      against the latest real cached universe data (magnitude, structural/
      correlation, infrastructure -- NOT speed, which needs intraday data
      this pipeline doesn't carry; documented, same accepted-limitation
      class `circuit_breaker/calibration_config.py` already notes for F2).
      Tier != ARMED blocks new entries.
   4. `risk.kelly.fractional_kelly_size` -- size <= 0 is a `NO_CONVICTION`
      block, not a zero-size order.
   5. `risk.limits.check_risk_limits` -- position/exposure/daily-loss caps.

   A passing evaluation mints a **single-use approval token** (a random
   hex string tracked in an in-process set). `execution.PaperExecutionClient
   .place_order` requires one and calls `risk_gate.consume_approval`, which
   rejects a missing, reused, or fabricated token. This makes "place an
   order without passing the gate" a runtime `PermissionError`, not just a
   convention.

4. **`execution.PaperExecutionClient`** fills at a REAL current price
   (`yfinance`, via `get_current_price` -- last trade price, falling back
   to the most recent daily close), tracks an in-memory position book, and
   appends every open/close to a JSONL ledger
   (`bot/state/paper_ledger.jsonl`). No slippage/spread model -- matches
   the fidelity of `reports/run_pead_backtest.py`, which also only applies
   a flat transaction-cost bps assumption, not a microstructure model this
   strategy was never validated against.

5. **`position_manager.PositionManager`** closes a position once
   `earnings.labeling.HOLDING_PERIOD_DAYS` (20) trading days have elapsed
   since entry (business-day approximation, same simplification
   `quality/monitor.py` already uses for gap detection). No adaptive TP/SL
   -- `reports/run_pead_backtest.py`'s own docstring is explicit that
   PEAD's validated backtest used a fixed holding-period exit because
   `risk/adaptive_exits.py`'s cluster-relative TP/SL machinery has no PEAD
   equivalent. Inventing a different exit rule here would not be backed by
   anything that was actually validated.

## 4. What would be needed to ever go live

**Descriptive only.** Nothing below is built, wired, or reachable from any
code in this repository. Going live requires, at minimum:

- A real, funded brokerage account and a real broker API integration
  (e.g. Alpaca, Interactive Brokers) -- this codebase contains no broker
  client of any kind, paper or otherwise, beyond the yfinance-priced
  paper simulator.
- Real API credentials, provisioned and stored by a human through that
  broker's own supported mechanism -- never a file this bot reads
  automatically, never a value an agent generates or embeds.
- A human explicitly implementing `LiveExecutionClient` (it currently
  hard-raises `NotImplementedError` with a docstring saying exactly this)
  and explicitly wiring it in place of `PaperExecutionClient` -- a code
  change a human reviews and merges, not a runtime flag this bot flips on
  its own.
- A real-time (or at least same-day, pre-close) market data feed, since
  the paper client's "fetch a current price" approximation is adequate for
  a daily-decision paper bot but not for anything that would actually route
  an order.
- Independent confirmation that the PEAD signal has FINISHED its
  statistical validation (it is explicitly still in progress as of this
  writing) -- paper-trading a signal is not the same bar as trading it
  live with real capital.
- Live-specific risk controls this scaffolding does not attempt: real-time
  position reconciliation against the broker's own account state, handling
  of partial fills/rejects from a real order book, and a live version of
  the watchdog/heartbeat pattern noted in section 1 (nothing to watch until
  a real process runs continuously, which this task explicitly does not
  start).

None of the above is a "flip a config flag" step. Every one of them
requires a human to do something outside of any agent's autonomous action.
