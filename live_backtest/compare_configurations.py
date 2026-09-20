"""Head-to-head replay of the live code path under several traded-universe and
position-sizing configurations.

Each configuration runs the REAL bot/run_cycle.py path day by day over the
cached model's holdout window through live_backtest/run_historical_replay.py --
same watcher, scoring, risk gate, execution client and holding-period exits,
with only the pinned-data providers swapped in. The only thing that differs
between runs is the traded universe and the two risk caps, so the comparison
isolates configuration, not code.

Read-only with respect to the live bot: the replay harness isolates the ledger,
alerts, kill switch and heartbeat under live_backtest/state/.

COSTS: PaperExecutionClient now charges the 10 bps round trip itself on every
close (risk/transaction_costs.py), so every number here is already NET of
fees -- which matters because the configurations differ in turnover (189 to 655
trades) and comparing them gross would flatter the busier ones.
`cost_drag_annual` reports what those charged fees actually came to per year.

Run: PYTHONPATH=. .venv/bin/python -m live_backtest.compare_configurations
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from loguru import logger

import bot.earnings_watcher as earnings_watcher_module
import bot.run_cycle as run_cycle_module
import live_backtest.compute_final_metrics as final_metrics
import live_backtest.run_historical_replay as replay
from risk.limits import RiskLimits

OUT_DIR = Path(__file__).parent.parent / "reports" / "config_sweep"
RESULTS_PATH = OUT_DIR / "sweep_results.json"
CHART_PATH = OUT_DIR / "configuration_comparison.png"
COST_BPS_ROUND_TRIP = 10.0

# (key, label, universe, per-position cap, gross exposure cap)
def configurations() -> list[tuple]:
    wide = earnings_watcher_module.load_validated_universe()
    narrow = earnings_watcher_module.load_breaker_universe()
    return [
        ("old_pead_75", "Old PEAD · 75 names, 10% positions", narrow, 0.10, 0.60),
        ("wide_2p5", "New · 503 names, 2.5% positions (live)", wide, 0.025, 0.60),
        ("wide_3p5", "Sized 1.4x · 3.5% positions, 85% gross", wide, 0.035, 0.85),
        ("wide_5p0", "Sized 2x · 5% positions, 100% gross", wide, 0.05, 1.00),
        ("wide_10p0", "Wide universe, old 10% positions", wide, 0.10, 0.60),
    ]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _equity_by_day(cycle_log_path: Path) -> dict[str, float]:
    """NAV after the last cycle of each replayed day."""
    return {r["as_of_date"]: r["nav_after"] for r in _read_jsonl(cycle_log_path)}


def run_configuration(key: str, label: str, tickers: list[str], position_cap: float, gross_cap: float) -> dict:
    replay.REPLAY_LEDGER = replay.REPLAY_STATE_DIR / f"sweep_{key}_ledger.jsonl"
    replay.REPLAY_CYCLE_LOG = replay.REPLAY_STATE_DIR / f"sweep_{key}_cycle_log.jsonl"
    run_cycle_module.BOT_RISK_LIMITS = RiskLimits(max_position_pct=position_cap, max_total_exposure_pct=gross_cap)
    earnings_watcher_module.load_validated_universe = lambda t=tickers: t

    started = time.time()
    replay.run_replay(force_fresh=True)
    metrics = final_metrics.main(cycle_log_path=replay.REPLAY_CYCLE_LOG, ledger_path=replay.REPLAY_LEDGER,
                                 out_path=OUT_DIR / f"{key}_metrics.json")
    metrics.pop("methodology", None)

    equity = _equity_by_day(replay.REPLAY_CYCLE_LOG)
    series = pd.Series({pd.Timestamp(d): v for d, v in equity.items()}).sort_index()
    closes = [r for r in _read_jsonl(replay.REPLAY_LEDGER) if r["event"] == "close"]
    years = (series.index[-1] - series.index[0]).days / 365.25
    # What the execution client actually charged, annualized against average NAV.
    drag = sum(r.get("cost", 0.0) for r in closes) / series.mean() / years

    metrics.update({
        "label": label, "n_tickers": len(tickers),
        "position_cap_pct": position_cap, "gross_cap_pct": gross_cap,
        "cost_drag_annual": round(drag, 5),
        "gross_annualized_return": round(metrics["annualized_return"] + drag, 5),
        "net_annualized_return": round(metrics["annualized_return"], 5),
        "minutes": round((time.time() - started) / 60, 1),
    })
    logger.info(f"{label}: {metrics['n_trades']} trades, net {metrics['net_annualized_return']:.2%}/yr, "
                f"vol {metrics['annualized_std']:.2%}, Sharpe {metrics['sharpe_ratio']:.2f}, "
                f"max DD {metrics['max_drawdown']:.1%}")
    return {"metrics": metrics, "equity": equity}


def render_chart(results: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    # De-emphasis gray for the incumbent; dataviz categorical slots for the rest.
    colors = {"old_pead_75": "#98a1ae", "wide_2p5": "#3987e5", "wide_3p5": "#199e70",
              "wide_5p0": "#d95926", "wide_10p0": "#c98500"}
    widths = {"old_pead_75": 2.2, "wide_2p5": 2.2, "wide_3p5": 2.6, "wide_5p0": 2.0, "wide_10p0": 1.6}
    dashes = {"wide_10p0": (0, (5, 3))}
    bg, surface, ink, ink2, ink3, grid = "#000000", "#0d0d10", "#f5f5f7", "#a0a4ad", "#6c7079", "#1c1c20"

    fig, ax = plt.subplots(figsize=(15, 8.2), dpi=110)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(surface)
    for key, _, _, _, _ in configurations():
        blob = results[key]
        series = pd.Series({pd.Timestamp(d): v for d, v in blob["equity"].items()}).sort_index()
        m = blob["metrics"]
        ax.plot(series.index, series.values, color=colors[key], linewidth=widths[key],
                linestyle=dashes.get(key, "-"), solid_capstyle="round",
                zorder=3 if key == "wide_3p5" else 2,
                label=f"{m['label']}    ${series.iloc[-1]:,.0f}   ·  net {m['net_annualized_return']:.2%}/yr"
                      f"  ·  Sharpe {m['sharpe_ratio']:.2f}  ·  max DD {m['max_drawdown']:.1%}")

    ax.axhline(100_000, color=ink3, linewidth=1, alpha=0.5, zorder=1)
    ax.set_title("Same bot, same code path, five configurations", color=ink, fontsize=19, weight="bold", loc="left", pad=46)
    ax.text(0, 1.012, "Replay of the live run_cycle() path on pinned data · 2021-08-11 → 2025-06-27 · $100,000 start"
                      " · net of 10 bps round-trip costs",
            transform=ax.transAxes, color=ink3, fontsize=11.5)
    ax.yaxis.set_major_formatter(lambda v, p: f"${v:,.0f}")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color=grid, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.tick_params(colors=ink2, labelsize=11, length=0)
    legend = ax.legend(loc="upper left", frameon=True, facecolor=surface, edgecolor=grid,
                       fontsize=11.5, labelcolor=ink2, borderpad=1, labelspacing=0.75)
    legend.get_frame().set_linewidth(1)
    fig.tight_layout()
    fig.savefig(CHART_PATH, facecolor=bg)
    logger.info(f"chart written to {CHART_PATH}")


def write_markdown(results: dict) -> None:
    rows = sorted((r["metrics"] for r in results.values()), key=lambda m: -m["net_annualized_return"])
    lines = [
        "# Configuration comparison — traded universe and position sizing",
        "",
        "Every row is the REAL `bot/run_cycle.py` path replayed day by day over the cached model's",
        "holdout window (2021-08-11 → 2025-06-27, 974 trading days) via",
        "`live_backtest/run_historical_replay.py`. Only the traded universe and the two risk caps differ.",
        "",
        "| Configuration | Names | Trades | Gross return | Fees charged | **Net return** | Volatility | Sharpe | Max drawdown | Win rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in rows:
        lines.append(
            f"| {m['label']} | {m['n_tickers']} | {m['n_trades']} | {m['gross_annualized_return']:.2%} | "
            f"{m['cost_drag_annual']:.2%} | **{m['net_annualized_return']:.2%}** | {m['annualized_std']:.2%} | "
            f"{m['sharpe_ratio']:.2f} | {m['max_drawdown']:.1%} | {m['win_rate']:.1%} |")
    lines += [
        "",
        "![Equity progression](configuration_comparison.png)",
        "",
        "## Reading this honestly",
        "",
        "- **The window is not pristine.** 2021-08 → 2025-06 is the holdout the model was validated on and",
        "  that this project has now examined repeatedly. It is out-of-sample for the model's fit, not for",
        "  the accumulated choices made while studying it.",
        "- **Costs are charged flat.** The execution client charges 10 bps round trip on every close, the same",
        "  assumption the cost-adjusted training label uses, so these curves are net of fees. Slippage,",
        "  borrow on shorts and market impact are still unmodeled.",
        "- **Sizing changes risk, not edge.** The sized-up rows earn more because they bet more, not",
        "  because the signal improved; their drawdowns grow roughly in step.",
        "- **The wider universe is what improved quality.** Same return as the old configuration at a third",
        "  less volatility, because one 10% position is replaced by several 2.5% ones.",
        "- **Gross exposure never exceeds 100%**, so no configuration here borrows; margin cost is not modeled.",
        "",
        "Reproduce: `PYTHONPATH=. .venv/bin/python -m live_backtest.compare_configurations`",
    ]
    (OUT_DIR / "COMPARISON.md").write_text("\n".join(lines) + "\n")
    logger.info(f"summary written to {OUT_DIR / 'COMPARISON.md'}")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {key: run_configuration(key, label, tickers, position_cap, gross_cap)
               for key, label, tickers, position_cap, gross_cap in configurations()}
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    render_chart(results)
    write_markdown(results)
    return results


if __name__ == "__main__":
    main()
