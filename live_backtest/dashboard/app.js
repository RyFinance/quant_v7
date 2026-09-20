/* PEAD Desk dashboard client.
 *
 * Everything here is read-only except the two schedule controls, which POST
 * to /api/control/start and /api/control/stop (see backend.py's module
 * docstring). Server-provided strings reach the DOM only through esc() or
 * textContent.
 */
(function () {
  "use strict";

  // ---------- config ----------
  const DEFAULT_POLL_MS = 20000;
  const EVENT_FEED_LIMIT = 100;
  // Report files (Monte Carlo, replay metrics) change rarely and the Monte
  // Carlo JSON is large, so re-read them every 15th poll or on manual refresh.
  const REFERENCE_EVERY_N_POLLS = 15;
  // The bot cycles about once per trading day, so a heartbeat several hours
  // old is normal. Warn as it nears the backend's 26h stale threshold.
  const HEARTBEAT_WARN_S = 20 * 3600;
  const HEARTBEAT_STALE_S = 26 * 3600;
  const CHART_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", system-ui, sans-serif';
  const BACKFILL_TITLE = "Replayed through the fixed bot for the Jul–Sep 2026 season it missed (live_backtest/backfill_missed_season.py)";

  // ---------- small utilities ----------
  const $ = (id) => document.getElementById(id);
  const isNum = (x) => typeof x === "number" && Number.isFinite(x);

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ } },
  };

  function fmtNum(x, digits = 2) {
    if (!isNum(x)) return "—";
    return x.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function fmtInt(x) { return isNum(x) ? Math.round(x).toLocaleString() : "—"; }
  function fmtMoney(x, digits = 2) {
    if (!isNum(x)) return "—";
    const body = Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    return (x < 0 ? "−$" : "$") + body;
  }
  function fmtSignedMoney(x) { return isNum(x) ? (x > 0 ? "+" : "") + fmtMoney(x) : "—"; }
  // Fraction in, percent out: 0.0123 -> "1.23%".
  function fmtPct(x, digits = 2, signed = false) {
    if (!isNum(x)) return "—";
    const v = x * 100;
    const sign = v < 0 ? "−" : (signed && v > 0 ? "+" : "");
    return sign + Math.abs(v).toFixed(digits) + "%";
  }
  function toneForSign(x) { return !isNum(x) || x === 0 ? "neutral" : x > 0 ? "good" : "crit"; }

  function fmtAgo(seconds) {
    if (!isNum(seconds)) return "—";
    const s = Math.max(0, Math.floor(seconds));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d > 0) return d + "d " + h + "h ago";
    if (h > 0) return h + "h " + m + "m ago";
    if (m > 0) return m + "m ago";
    return "just now";
  }

  const dateFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  const stampFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const clockFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

  // "2026-09-16" -> "Sep 16, 2026" (parsed as a local calendar date).
  function fmtDate(s) {
    if (s === null || s === undefined || s === "") return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s));
    return m ? dateFmt.format(new Date(+m[1], +m[2] - 1, +m[3])) : String(s);
  }
  function fmtStamp(ts) { return isNum(ts) ? stampFmt.format(new Date(ts * 1000)) : "—"; }
  function dayOf(s) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || "")); return m ? m[0] : null; }

  function humanize(s) {
    if (!s) return "Event";
    const t = String(s).replace(/_/g, " ");
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function withAlpha(hex, alpha) {
    const m = /^#([0-9a-f]{6})$/i.exec(hex);
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
  }

  async function getJSON(url) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) { console.warn("Non-OK response for", url, res.status); return { ok: false, data: null }; }
      return { ok: true, data: await res.json() };
    } catch (err) {
      console.warn("Fetch failed for", url, err);
      return { ok: false, data: null };
    }
  }

  // ---------- markup helpers ----------
  const ICONS = {
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    chart: '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    view: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    ticker: '<path d="M3 3v18h18"/><path d="m7 14 4-4 3 3 5-6"/>',
    theme: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  };
  function svg(name, cls) {
    return '<svg class="icon' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
  }
  function chip(label, tone) { return '<span class="chip" data-tone="' + tone + '">' + esc(label) + "</span>"; }
  function backfillTag(flag) { return flag ? '<span class="tag" title="' + esc(BACKFILL_TITLE) + '">Backfill</span>' : ""; }
  function emptyState(icon, title, text) {
    return '<div class="empty">' + svg(icon, "empty-icon") +
      '<div class="empty-title">' + esc(title) + '</div><div class="empty-text">' + esc(text) + "</div></div>";
  }
  function emptyRow(colspan, icon, title, text) {
    return '<tr><td colspan="' + colspan + '">' + emptyState(icon, title, text) + "</td></tr>";
  }

  // ---------- vocabulary ----------
  const KIND_META = {
    cycle_run: { label: "Cycle run", tone: "neutral", group: "cycles" },
    entry_placed: { label: "Entry placed", tone: "good", group: "trades" },
    position_opened: { label: "Position opened", tone: "good", group: "trades" },
    exit: { label: "Exit", tone: "info", group: "trades" },
    position_closed: { label: "Position closed", tone: "info", group: "trades" },
    entry_skipped: { label: "Entry skipped", tone: "neutral", group: "trades" },
    risk_blocked: { label: "Risk blocked", tone: "warn", group: "risk" },
    circuit_breaker_halt: { label: "Circuit breaker halt", tone: "warn", group: "risk" },
    kill_switch_engaged: { label: "Kill switch engaged", tone: "crit", group: "risk" },
    drawdown_cap_tripped: { label: "Drawdown cap tripped", tone: "crit", group: "risk" },
    dead_mans_switch: { label: "Dead man's switch", tone: "crit", group: "risk" },
    earnings_feed_stale: { label: "Earnings feed stale", tone: "crit", group: "risk" },
    error: { label: "Error", tone: "crit", group: "risk" },
  };
  function kindMeta(kind) { return KIND_META[kind] || { label: humanize(kind), tone: "neutral", group: "other" }; }

  const TIER_META = {
    armed: { label: "Armed", tone: "good", detail: "Normal operation" },
    halt_new_entries: { label: "Halt new entries", tone: "warn", detail: "New entries blocked" },
    full_flatten: { label: "Full flatten", tone: "crit", detail: "Flattening all positions" },
  };
  function tierMeta(tier) {
    return TIER_META[tier] || { label: tier ? humanize(tier) : "Unknown", tone: "neutral", detail: "Tier not recognized" };
  }
  function sideChip(direction) {
    if (direction === "long") return chip("Long", "info");
    if (direction === "short") return chip("Short", "serious");
    return chip(direction ? humanize(direction) : "—", "neutral");
  }
  const TIMING_LABEL = {
    before_open: "Before open", before_close: "Before close", during_session: "During session",
    after_close: "After close", unknown: "Time not set",
  };

  // ---------- state ----------
  const data = { status: null, launchd: null, stats: null, positions: [], trades: [], signals: [],
                 cycles: [], alerts: [], feed: [], upcoming: null, equity: null, mc: null, lbm: null, ok: {} };
  const ui = {
    view: "overview",
    tab: store.get("pead.tab") || "trades",
    feedFilter: store.get("pead.feedFilter") || "all",
    range: store.get("pead.chartRange") || "all",
    pollMs: Number(store.get("pead.pollMs") || DEFAULT_POLL_MS),
    theme: store.get("pead.theme") || "system",
    filters: { search: "", side: "all", status: "all", range: "all" },
    sort: {
      trades: { key: "entry_date", dir: "desc" },
      positions: { key: "entry_date", dir: "desc" },
      signals: { key: "as_of_date", dir: "desc" },
      cycles: { key: "ts", dir: "desc" },
      alerts: { key: "ts", dir: "desc" },
      upcoming: { key: "earnings_date", dir: "asc" },
    },
  };
  const TABS = ["trades", "positions", "signals", "cycles", "alerts"];
  const VIEWS = ["overview", "activity", "research"];
  if (TABS.indexOf(ui.tab) === -1) ui.tab = "trades";
  if (!isNum(ui.pollMs)) ui.pollMs = DEFAULT_POLL_MS;

  // ---------- filtering & sorting ----------
  function rowText(row) {
    return [row.ticker, row.direction, row.reason, row.detail, row.message, row.kind, row.as_of_date, row.entry_date]
      .filter(Boolean).join(" ").toLowerCase();
  }

  function withinRange(dateish) {
    if (ui.filters.range === "all") return true;
    const day = dayOf(dateish);
    if (!day) return true;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - Number(ui.filters.range));
    return new Date(day + "T00:00:00") >= cutoff;
  }

  function applyFilters(rows, kind) {
    const q = ui.filters.search.trim().toLowerCase();
    return rows.filter((row) => {
      if (q && rowText(row).indexOf(q) === -1) return false;
      if (ui.filters.side !== "all" && row.direction && row.direction !== ui.filters.side) return false;
      if (ui.filters.side !== "all" && kind === "trades" && !row.direction) return false;
      if (kind === "trades" && ui.filters.status !== "all") {
        const s = ui.filters.status;
        if (s === "open" && row.open !== true) return false;
        if (s === "closed" && row.open !== false) return false;
        if (s === "winners" && !(isNum(row.realized_pnl) && row.realized_pnl > 0)) return false;
        if (s === "losers" && !(isNum(row.realized_pnl) && row.realized_pnl < 0)) return false;
      }
      const dateField = row.entry_date || row.as_of_date || (isNum(row.ts) ? new Date(row.ts * 1000).toISOString() : null);
      return withinRange(dateField);
    });
  }

  function sortValue(row, key) {
    if (key === "return") return isNum(row.realized_pnl) && row.notional ? row.realized_pnl / row.notional : null;
    if (key === "n_entries") return (row.entries || []).filter((e) => e && e.allowed).length;
    if (key === "n_exits") return (row.exits || []).length;
    if (key === "n_errors") return (row.errors || []).length;
    if (key === "tradable") return row.earnings_date;
    const v = row[key];
    return v === undefined ? null : v;
  }

  function sortRows(rows, kind) {
    const { key, dir } = ui.sort[kind];
    const factor = dir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {
      const va = sortValue(a, key), vb = sortValue(b, key);
      const na = va === null || va === undefined, nb = vb === null || vb === undefined;
      if (na && nb) return 0;
      if (na) return 1;   // missing values sink, whichever direction
      if (nb) return -1;
      if (typeof va === "boolean" || typeof vb === "boolean") return (Number(va) - Number(vb)) * factor;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * factor;
      return String(va).localeCompare(String(vb)) * factor;
    });
  }

  function prepared(kind) {
    const source = { trades: data.trades, positions: data.positions, signals: data.signals,
                     cycles: data.cycles, alerts: data.alerts }[kind] || [];
    return sortRows(applyFilters(source, kind), kind);
  }

  // ---------- connection & health ----------
  function renderConnection(ok) {
    $("conn").dataset.state = ok ? "live" : "offline";
    $("conn-label").textContent = ok ? "Live" : "Offline";
    $("backend-banner").hidden = ok;
  }

  function setHealth(id, tone, value, detail) {
    const el = $(id);
    el.dataset.tone = tone;
    el.querySelector(".health-value").textContent = value;
    const detailEl = el.querySelector(".health-detail");
    detailEl.textContent = detail || " ";
    detailEl.title = detail || "";
  }

  function renderStatus(res) {
    if (!res.ok || !res.data) {
      ["hi-kill", "hi-breaker", "hi-heartbeat", "hi-cycle"].forEach((id) => setHealth(id, "neutral", "Unknown", "Status unavailable"));
      return;
    }
    const d = res.data;
    if (d.kill_switch_engaged === true) {
      setHealth("hi-kill", "crit", "Engaged", d.kill_switch_reason ? String(d.kill_switch_reason) : "No reason given");
    } else if (d.kill_switch_engaged === false) {
      setHealth("hi-kill", "good", "Clear", "No restrictions");
    } else {
      setHealth("hi-kill", "neutral", "Unknown", "");
    }

    const tier = tierMeta(d.circuit_breaker_tier);
    setHealth("hi-breaker", tier.tone, tier.label, tier.detail);

    const age = d.heartbeat_age_seconds;
    const stale = d.heartbeat_stale === true || (isNum(age) && age > HEARTBEAT_STALE_S);
    if (!isNum(age)) setHealth("hi-heartbeat", "crit", "Never", "No heartbeat recorded");
    else if (stale) setHealth("hi-heartbeat", "crit", fmtAgo(age), "Stale: the bot may be down");
    else if (age >= HEARTBEAT_WARN_S) setHealth("hi-heartbeat", "warn", fmtAgo(age), "Nearing the 26h stale threshold");
    else setHealth("hi-heartbeat", "good", fmtAgo(age), "Within the daily cycle window");

    const lc = d.last_cycle;
    if (lc && typeof lc === "object") {
      const errs = Array.isArray(lc.errors) ? lc.errors.length : 0;
      const errText = errs === 0 ? "no errors" : errs + (errs === 1 ? " error" : " errors");
      setHealth("hi-cycle", errs > 0 ? "crit" : "good", fmtDate(lc.as_of_date), "Ran " + fmtStamp(lc.ts) + " · " + errText);
    } else {
      setHealth("hi-cycle", "neutral", "No cycles yet", "");
    }
  }

  // Deliberately NOT getJSON here: telling "backend unreachable" apart from
  // "backend reachable but the paper-mode guard failed (HTTP 500)" is
  // safety-relevant (see backend.py's _paper_mode_or_500), and getJSON
  // collapses both into ok:false.
  async function fetchLaunchdStatus() {
    try {
      const res = await fetch("/api/launchd_status", { cache: "no-store" });
      let payload = null;
      try { payload = await res.json(); } catch (e) { /* non-JSON body, tolerate */ }
      return { reachable: true, status: res.status, ok: res.ok, data: payload };
    } catch (err) {
      return { reachable: false, status: null, ok: false, data: null };
    }
  }

  function jobHealth(job) {
    if (!job) return ["neutral", "Unknown", "Status unavailable"];
    if (job.error) return ["crit", "Error", String(job.error)];
    if (!job.loaded) return ["warn", "Stopped", "Not loaded in launchd"];
    const exitCode = job.last_exit_code;
    const state = job.state ? humanize(job.state) : "Loaded";
    const exitText = isNum(exitCode) ? " · last exit " + exitCode : "";
    return [isNum(exitCode) && exitCode !== 0 ? "warn" : "good", "Running", state + exitText];
  }

  let controlsBusy = false;
  let controlsVerified = false;

  function renderLaunchd(info) {
    const modeChip = $("mode-chip");
    let verified = false;
    let jobs = null;

    if (!info.reachable) {
      modeChip.dataset.tone = "neutral";
      modeChip.textContent = "Trading mode unknown: backend offline";
    } else if (info.status === 500 || !info.ok || !info.data || info.data.mode_verified !== true || !info.data.mode) {
      // The most safety-critical branch on this page: the backend did not
      // confirm paper-only mode. Never show anything that could be mistaken
      // for a verified state, and keep the controls disabled.
      modeChip.dataset.tone = "crit";
      modeChip.textContent = "Paper-mode guard failed: refusing to control";
      jobs = info.data && info.data.jobs ? info.data.jobs : null;
    } else {
      verified = true;
      jobs = info.data.jobs || {};
      modeChip.dataset.tone = "good";
      modeChip.textContent = (info.data.mode === "PAPER_TRADE" ? "Paper-trade mode" : String(info.data.mode)) + " verified";
    }
    $("guard-banner").hidden = !(info.reachable && !verified);
    controlsVerified = verified;

    setHealth("hi-schedule", ...jobHealth(jobs && jobs.pead_bot));
    setHealth("hi-watchdog", ...jobHealth(jobs && jobs.pead_watchdog));

    // Start/stop are idempotent on the backend; disabling the no-op one just
    // makes the current state obvious. With an unknown or errored job state
    // both stay available.
    const pair = jobs ? [jobs.pead_bot, jobs.pead_watchdog] : [];
    const known = pair.length === 2 && pair.every((j) => j && !j.error);
    const allLoaded = known && pair.every((j) => j.loaded);
    const noneLoaded = known && pair.every((j) => !j.loaded);
    const startDisabled = !verified || controlsBusy || allLoaded;
    const stopDisabled = !verified || controlsBusy || noneLoaded;
    for (const el of [$("btn-start"), $("menu-start")]) el.disabled = startDisabled;
    for (const el of [$("btn-stop"), $("menu-stop")]) el.disabled = stopDisabled;
    $("btn-start").title = allLoaded && verified ? "Schedule is already running" : "";
    $("btn-stop").title = noneLoaded && verified ? "Schedule is already stopped" : "";
  }

  // ---------- account & performance ----------
  function renderAccount() {
    const s = data.ok.stats ? data.stats : null;
    const nav = s ? s.current_nav : null;
    const retPct = s ? s.total_return_pct : null;  // already in percent units
    $("nav-value").textContent = fmtMoney(nav);

    const delta = $("nav-delta"), pnl = $("acct-pnl");
    if (isNum(retPct) && isNum(nav)) {
      const start = isNum(s.starting_capital) ? s.starting_capital : nav / (1 + retPct / 100);
      delta.textContent = (retPct < 0 ? "−" : retPct > 0 ? "+" : "") + Math.abs(retPct).toFixed(2) + "%";
      delta.dataset.tone = toneForSign(retPct);
      $("nav-delta-note").textContent = "since inception · started at " + fmtMoney(start, 0);
      pnl.textContent = fmtSignedMoney(nav - start);
      pnl.dataset.tone = toneForSign(nav - start);
    } else {
      delta.textContent = "—"; delta.dataset.tone = "neutral";
      $("nav-delta-note").textContent = s ? "" : "stats unavailable";
      pnl.textContent = "—"; pnl.dataset.tone = "neutral";
    }

    $("acct-closed").textContent = s && isNum(s.n_trades) ? fmtInt(s.n_closed_trades) + " of " + fmtInt(s.n_trades) : "—";
    const positions = data.ok.positions ? data.positions : null;
    $("acct-open").textContent = positions ? fmtInt(positions.length) : "—";

    const unrealized = s ? s.unrealized_pnl : null;
    const unrealizedEl = $("acct-unrealized");
    unrealizedEl.textContent = isNum(unrealized) ? fmtSignedMoney(unrealized) : "—";
    unrealizedEl.dataset.tone = toneForSign(unrealized);
    const markDates = positions ? positions.map((p) => p.last_close_date).filter(Boolean).sort() : [];
    $("acct-mark-date").textContent = markDates.length ? "· " + fmtDate(markDates[markDates.length - 1]) : "";

    const marked = $("nav-marked");
    const markedNav = s && isNum(s.marked_nav) ? s.marked_nav : (isNum(nav) && isNum(unrealized) ? nav + unrealized : null);
    if (isNum(markedNav) && positions && positions.length) {
      marked.innerHTML = "Marked to market <b>" + esc(fmtMoney(markedNav)) + "</b> including open positions";
      marked.hidden = false;
    } else {
      marked.hidden = true;
    }

    const nBackfill = s ? s.n_backfilled_trades : 0;
    const note = $("backfill-note");
    if (isNum(nBackfill) && nBackfill > 0) {
      note.textContent = fmtInt(nBackfill) + " of these trades were backfilled: the Jul 1 – Sep 16 season the bot missed, " +
        "replayed through the fixed bot at each day's real close. They are tagged Backfill in the trade log.";
      note.hidden = false;
    } else {
      note.hidden = true;
    }
  }

  function renderPerformance() {
    const s = data.ok.stats ? data.stats : null;
    $("kpi-sharpe").textContent = s ? fmtNum(s.sharpe_ratio) : "—";
    $("kpi-sortino").textContent = s ? fmtNum(s.sortino_ratio) : "—";
    $("kpi-maxdd").textContent = s ? fmtPct(s.max_drawdown) : "—";
    $("kpi-winrate").textContent = s ? fmtPct(s.win_rate, 1) : "—";
    $("kpi-winrate-note").textContent = s && isNum(s.n_closed_trades)
      ? "Of " + fmtInt(s.n_closed_trades) + " closed trade" + (s.n_closed_trades === 1 ? "" : "s")
      : "Closed trades";
    $("stats-note").hidden = !(s && s.insufficient_data === true);

    const basis = $("perf-basis");
    if (s && isNum(s.risk_free_rate)) {
      const through = s.risk_free_through ? "published through " + fmtDate(s.risk_free_through) + ", then carried forward" : "";
      let text = "Ratios use the NAV marked at each day's close, in excess of the 1-month T‑bill (" +
        fmtPct(s.risk_free_rate) + " a year on average" + (through ? "; " + through : "") + "). Idle cash earns nothing.";
      if (isNum(s.stale_marks) && s.stale_marks > 0) {
        text += " " + fmtInt(s.stale_marks) + " position-day" + (s.stale_marks === 1 ? " was" : "s were") +
          " marked at an older close or at cost.";
      }
      basis.textContent = text;
      basis.hidden = false;
    } else {
      basis.hidden = true;
    }
  }

  // ---------- charts ----------
  const charts = { equity: null, mc: null };
  const chartSig = { equity: "", mc: "" };

  function chartTheme() {
    return {
      label: cssVar("--label"), label3: cssVar("--label-3"),
      grid: cssVar("--grid"), axis: cssVar("--axis"),
      surface: cssVar("--surface-solid"), tooltipBorder: cssVar("--hairline-2"),
      accent: cssVar("--accent"), neutral: cssVar("--chart-neutral"),
    };
  }

  // Vertical hairline at the hovered x position.
  const crosshairPlugin = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
      const active = chart.tooltip ? chart.tooltip.getActiveElements() : [];
      if (!active.length) return;
      const x = active[0].element.x, area = chart.chartArea, ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, area.top);
      ctx.lineTo(x, area.bottom);
      ctx.lineWidth = 1;
      ctx.strokeStyle = chart.options.plugins.crosshair.color;
      ctx.stroke();
      ctx.restore();
    },
  };

  function baseLineOptions(t, opts) {
    const tickFont = { family: CHART_FONT, size: 11 };
    const x = {
      grid: { display: false },
      border: { color: t.axis },
      ticks: { color: t.label3, font: tickFont, maxTicksLimit: 7, maxRotation: 0, autoSkip: true },
    };
    if (opts.xTitle) x.title = { display: true, text: opts.xTitle, color: t.label3, font: tickFont, padding: { top: 6 } };
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 4, right: 6 } },
      plugins: {
        legend: { display: false },
        crosshair: { color: t.axis },
        tooltip: {
          backgroundColor: t.surface, borderColor: t.tooltipBorder, borderWidth: 1,
          cornerRadius: 12, padding: 12, caretSize: 0,
          titleColor: t.label3, titleFont: { family: CHART_FONT, size: 11, weight: "500" }, titleMarginBottom: 6,
          bodyColor: t.label, bodyFont: { family: CHART_FONT, size: 12.5, weight: "600" }, bodySpacing: 5,
          usePointStyle: true, boxPadding: 6,
          itemSort: opts.itemSort, callbacks: opts.callbacks,
        },
      },
      scales: {
        x: x,
        y: {
          grace: "4%", grid: { color: t.grid }, border: { display: false },
          ticks: { color: t.label3, font: tickFont, padding: 8, maxTicksLimit: 6, callback: (v) => fmtMoney(Number(v), 0) },
        },
      },
    };
  }

  function showChartEmpty(key, emptyId, canvasId, icon, title, text) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
    chartSig[key] = "";
    $(canvasId).hidden = true;
    const empty = $(emptyId);
    empty.innerHTML = emptyState(icon, title, text);
    empty.hidden = false;
  }

  // Filters `dates` and every parallel array in `series` to the chosen range.
  function rangeFiltered(dates, series) {
    if (ui.range === "all") return { dates, series };
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - Number(ui.range));
    const out = { dates: [], series: series.map(() => []) };
    dates.forEach((d, i) => {
      const day = dayOf(d);
      if (!day || new Date(day + "T00:00:00") >= cutoff) {
        out.dates.push(d);
        series.forEach((s, k) => out.series[k].push(s[i]));
      }
    });
    return out.dates.length >= 2 ? out : { dates, series };
  }

  function renderEquity() {
    const res = data.equity || { ok: false, data: null };
    const d = res.ok && res.data ? res.data : null;
    // Daily marked NAV (what the ratios are computed from), with the cash-basis
    // NAV on the same days; falls back to realized NAV by exit date.
    const m = d && d.marked && Array.isArray(d.marked.dates) && d.marked.dates.length ? d.marked : null;
    const all = m
      ? { dates: m.dates, series: [m.nav, Array.isArray(m.cash_basis_nav) ? m.cash_basis_nav : []] }
      : { dates: d && Array.isArray(d.dates) ? d.dates : [], series: [d && Array.isArray(d.nav) ? d.nav : []] };
    const { dates, series } = rangeFiltered(all.dates, all.series);
    const nav = series[0];
    const cash = m && series[1].length === dates.length ? series[1] : null;

    $("equity-sub").textContent = dates.length
      ? (m ? "NAV marked at each day's close since " : "Realized NAV by exit date since ") + fmtDate(dates[0])
      : "NAV marked at each day's close";

    const legend = $("equity-legend");
    const lastOf = (arr) => arr[arr.length - 1];
    if (dates.length && cash) {
      legend.innerHTML =
        '<span class="legend-item"><i class="key key-line"></i>Marked to market <b>' + esc(fmtMoney(lastOf(nav), 0)) + "</b></span>" +
        '<span class="legend-item"><i class="key key-dashed"></i>Cash basis, open positions at cost <b>' + esc(fmtMoney(lastOf(cash), 0)) + "</b></span>";
      legend.hidden = false;
    } else {
      legend.innerHTML = "";
      legend.hidden = true;
    }

    if (!res.ok) return showChartEmpty("equity", "equity-empty", "equity-chart", "alert", "Equity curve unavailable", "The backend could not be reached.");
    if (typeof Chart === "undefined") return showChartEmpty("equity", "equity-empty", "equity-chart", "alert", "Chart library failed to load", "Check the network connection, then reload.");
    if (!dates.length) return showChartEmpty("equity", "equity-empty", "equity-chart", "chart", "No trades yet", "The equity curve appears once the first position is opened.");

    const sig = [ui.range, m ? "marked" : "realized", dates.length, lastOf(dates), lastOf(nav), cash ? lastOf(cash) : ""].join("|");
    if (charts.equity && sig === chartSig.equity) return;
    chartSig.equity = sig;
    $("equity-empty").hidden = true;
    $("equity-chart").hidden = false;

    const t = chartTheme();
    const labels = dates.map(fmtDate);
    const datasets = [{
      key: "marked", label: m ? "Marked" : "NAV", data: nav,
      borderColor: t.accent, borderWidth: 2, borderCapStyle: "round", borderJoinStyle: "round",
      pointRadius: nav.length === 1 ? 4 : 0, pointHoverRadius: 5,
      pointBackgroundColor: t.accent, pointHoverBackgroundColor: t.accent,
      pointHoverBorderColor: t.surface, pointHoverBorderWidth: 2,
      tension: 0, fill: "start", order: 1,
      backgroundColor: (c) => {
        const area = c.chart.chartArea;
        if (!area) return "transparent";
        const g = c.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
        g.addColorStop(0, withAlpha(t.accent, 0.22));
        g.addColorStop(1, withAlpha(t.accent, 0));
        return g;
      },
    }];
    if (cash) {
      datasets.push({
        key: "cash", label: "Cash basis", data: cash,
        borderColor: t.neutral, borderWidth: 1.5, borderDash: [5, 4], fill: false,
        pointRadius: 0, pointHoverRadius: 3, pointHoverBackgroundColor: t.neutral,
        pointHoverBorderColor: t.surface, pointHoverBorderWidth: 2, tension: 0, order: 2,
      });
    }

    if (charts.equity && charts.equity.data.datasets.length === datasets.length) {
      charts.equity.data.labels = labels;
      datasets.forEach((ds, k) => { charts.equity.data.datasets[k].data = ds.data; charts.equity.data.datasets[k].label = ds.label; });
      charts.equity.update("none");
      return;
    }
    if (charts.equity) charts.equity.destroy();
    const keyColor = { marked: t.accent, cash: t.neutral };
    charts.equity = new Chart($("equity-chart"), {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: baseLineOptions(t, {
        itemSort: (a, b) => a.datasetIndex - b.datasetIndex,
        callbacks: {
          label: (ctx) => fmtMoney(ctx.parsed.y) + "  " + ctx.dataset.label,
          labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
          labelColor: (ctx) => {
            const c = keyColor[ctx.dataset.key] || t.accent;
            return { borderColor: c, backgroundColor: c, borderWidth: 2 };
          },
        },
      }),
      plugins: [crosshairPlugin],
    });
  }

  function renderMonteCarlo() {
    const res = data.mc || { ok: false, data: null };
    const d = res.ok && res.data ? res.data : null;
    const available = !!d && d.available !== false;
    const fan = available ? d.fan_chart_nav_by_step : null;
    const real = available ? d.real_equity_curve_by_step : null;
    const hasFan = !!fan && Array.isArray(fan.step) && Array.isArray(fan.p5) && Array.isArray(fan.p50) && Array.isArray(fan.p95) && fan.step.length > 0;
    const hasReal = !!real && Array.isArray(real.step) && Array.isArray(real.nav) && real.nav.length > 0;
    const legend = $("mc-legend");

    if (!res.ok || !available || !hasFan || typeof Chart === "undefined") {
      legend.innerHTML = "";
      $("mc-sub").textContent = "Resampled trade sequences vs. the realized path";
      if (!res.ok) return showChartEmpty("mc", "mc-empty", "mc-chart", "alert", "Monte Carlo unavailable", "The backend could not be reached.");
      if (typeof Chart === "undefined") return showChartEmpty("mc", "mc-empty", "mc-chart", "alert", "Chart library failed to load", "Check the network connection, then reload.");
      return showChartEmpty("mc", "mc-empty", "mc-chart", "chart", "Monte Carlo not available yet", "Run the live-path Monte Carlo to generate reports/pead_live_backtest_monte_carlo.json.");
    }

    const last = (arr) => arr[arr.length - 1];
    const sig = [fan.step.length, last(fan.p5), last(fan.p50), last(fan.p95), hasReal ? last(real.nav) : "none"].join("|");
    if (charts.mc && sig === chartSig.mc) return;
    chartSig.mc = sig;
    $("mc-empty").hidden = true;
    $("mc-chart").hidden = false;

    const draws = isNum(d.n_bootstrap_draws) ? fmtInt(d.n_bootstrap_draws) + " bootstrap draws" : "Bootstrap draws";
    $("mc-sub").textContent = draws + " · " + (isNum(d.n_trades) ? fmtInt(d.n_trades) + " trades" : fan.step.length + " steps");
    legend.innerHTML =
      (hasReal ? '<span class="legend-item"><i class="key key-line"></i>Realized <b>' + esc(fmtMoney(last(real.nav), 0)) + "</b></span>" : "") +
      '<span class="legend-item"><i class="key key-median"></i>Simulated median <b>' + esc(fmtMoney(last(fan.p50), 0)) + "</b></span>" +
      '<span class="legend-item"><i class="key key-band"></i>5th–95th percentile <b>' +
      esc(fmtMoney(last(fan.p5), 0)) + " – " + esc(fmtMoney(last(fan.p95), 0)) + "</b></span>";

    const t = chartTheme();
    const bandKey = withAlpha(t.accent, 0.5);
    const rank = { realized: 0, median: 1, p95: 2, p5: 3 };
    const keyColor = { realized: t.accent, median: t.neutral, p95: bandKey, p5: bandKey };
    const datasets = [
      { key: "p95", label: "95th percentile", data: fan.p95, borderWidth: 0, borderColor: "transparent", backgroundColor: withAlpha(t.accent, 0.16), fill: "+1", pointRadius: 0, pointHoverRadius: 0, order: 3 },
      { key: "p5", label: "5th percentile", data: fan.p5, borderWidth: 0, borderColor: "transparent", backgroundColor: "transparent", fill: false, pointRadius: 0, pointHoverRadius: 0, order: 3 },
      { key: "median", label: "Simulated median", data: fan.p50, borderWidth: 1.5, borderColor: t.neutral, fill: false, pointRadius: 0, pointHoverRadius: 3, pointHoverBackgroundColor: t.neutral, pointHoverBorderColor: t.surface, pointHoverBorderWidth: 2, tension: 0, order: 2 },
    ];
    if (hasReal) {
      datasets.push({ key: "realized", label: "Realized", data: real.nav, borderWidth: 2, borderColor: t.accent, borderCapStyle: "round", borderJoinStyle: "round", fill: false, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: t.accent, pointHoverBorderColor: t.surface, pointHoverBorderWidth: 2, tension: 0, order: 1 });
    }

    if (charts.mc) charts.mc.destroy();
    charts.mc = new Chart($("mc-chart"), {
      type: "line",
      data: { labels: fan.step.map((n) => (isNum(n) ? n + 1 : n)), datasets: datasets },
      options: baseLineOptions(t, {
        xTitle: "Trades completed",
        itemSort: (a, b) => rank[a.dataset.key] - rank[b.dataset.key],
        callbacks: {
          title: (items) => (items.length ? "After trade " + items[0].label : ""),
          label: (ctx) => fmtMoney(ctx.parsed.y, 0) + "  " + ctx.dataset.label,
          labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
          labelColor: (ctx) => {
            const c = keyColor[ctx.dataset.key] || t.neutral;
            return { borderColor: c, backgroundColor: c, borderWidth: 2 };
          },
        },
      }),
      plugins: [crosshairPlugin],
    });
  }

  // ---------- research: distribution & replay metrics ----------
  let distSig = "";

  function distRow(name, source, q, realized) {
    if (!q || !isNum(q.p5) || !isNum(q.p50) || !isNum(q.p95)) return "";
    const values = [q.p5, q.p50, q.p95].concat(isNum(realized) ? [realized] : []);
    let lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 0.01;
    lo -= pad; hi += pad;
    const pos = (v) => ((v - lo) / (hi - lo) * 100).toFixed(2);
    const label = name + ": 5th percentile " + fmtPct(q.p5) + ", median " + fmtPct(q.p50) + ", 95th percentile " + fmtPct(q.p95) +
      (isNum(realized) ? ", realized " + fmtPct(realized) : "");
    return '<div class="dist-row">' +
      '<div class="dist-row-head"><span class="dist-name">' + esc(name) + '</span><span class="dist-src">' + esc(source) + "</span></div>" +
      '<div class="dist-bar" role="img" aria-label="' + esc(label) + '" title="' + esc(label) + '">' +
      '<span class="dist-band" style="left:' + pos(Math.min(q.p5, q.p95)) + "%;width:" + (pos(Math.max(q.p5, q.p95)) - pos(Math.min(q.p5, q.p95))).toFixed(2) + '%"></span>' +
      '<span class="dist-median" style="left:' + pos(q.p50) + '%"></span>' +
      (isNum(realized) ? '<span class="dist-real" style="left:' + pos(realized) + '%"></span>' : "") +
      "</div>" +
      '<div class="dist-values">' +
      "<span>5th<b>" + esc(fmtPct(q.p5)) + "</b></span><span>Median<b>" + esc(fmtPct(q.p50)) + "</b></span>" +
      "<span>95th<b>" + esc(fmtPct(q.p95)) + "</b></span>" +
      (isNum(realized) ? "<span>Realized<b>" + esc(fmtPct(realized)) + "</b></span>" : "") +
      "</div></div>";
  }

  function renderDistribution() {
    const res = data.mc || { ok: false, data: null };
    const box = $("dist-content");
    const d = res.ok && res.data ? res.data : null;
    if (!res.ok || !d || d.available === false || !d.bootstrap) {
      distSig = "";
      box.innerHTML = emptyState(res.ok ? "chart" : "alert",
        res.ok ? "No simulation results yet" : "Distribution unavailable",
        res.ok ? "Bootstrap and permutation summaries appear after the Monte Carlo run." : "The backend could not be reached.");
      return;
    }
    const b = d.bootstrap || {}, p = d.permutation || {}, r = d.real_realized || {};
    const sig = JSON.stringify([b, p, r, d.n_bootstrap_draws, d.n_permutation_draws]);
    if (sig === distSig) return;
    distSig = sig;

    const parts = [];
    if (isNum(b.pct_draws_ending_negative)) {
      parts.push('<div class="dist-headline"><div class="big">' + esc(fmtPct(b.pct_draws_ending_negative, 1)) + "</div>" +
        '<div class="txt"><b>of bootstrap draws end below starting capital.</b><br>Resampling the ' +
        esc(isNum(d.n_trades) ? fmtInt(d.n_trades) : "") + " realized trades with replacement.</div></div>");
    }
    parts.push('<div class="legend"><span class="legend-item"><i class="key key-band"></i>5th–95th pct</span>' +
      '<span class="legend-item"><i class="key key-tick"></i>Median</span>' +
      '<span class="legend-item"><i class="key key-dot"></i>Realized</span></div>');
    parts.push(distRow("Ending return", "Bootstrap", b.ending_return_pct, r.ending_return));
    parts.push(distRow("Max drawdown", "Bootstrap", b.max_drawdown_pct, r.max_drawdown));
    parts.push(distRow("Max drawdown", "Trade-order permutation", p.max_drawdown_pct, r.max_drawdown));
    if (p.note) parts.push('<p class="footnote">' + esc(p.note) + "</p>");

    $("dist-sub").textContent = [
      isNum(d.n_bootstrap_draws) ? fmtInt(d.n_bootstrap_draws) + " bootstrap draws" : null,
      isNum(d.n_permutation_draws) ? fmtInt(d.n_permutation_draws) + " permutations" : null,
    ].filter(Boolean).join(" · ") || "Where the realized result sits among simulations";
    box.innerHTML = '<div class="dist">' + parts.join("") + "</div>";
  }

  const LBM_FIELDS = [
    ["annualized_return", "Annualized return", "pct"], ["annualized_std", "Volatility", "pct"],
    ["sharpe_ratio", "Sharpe ratio", "num"], ["sortino_ratio", "Sortino ratio", "num"],
    ["calmar_ratio", "Calmar ratio", "num"], ["total_return", "Total return", "pct"],
    ["max_drawdown", "Max drawdown", "pct"], ["win_rate", "Win rate", "pct1"],
    ["n_trades", "Trades", "int"], ["turnover_annualized", "Turnover", "turn"],
  ];
  const LBM_SKIP = new Set(["available", "methodology", "start_date", "end_date", "n_days_replayed"]);
  let lbmSig = "";

  function fmtField(kind, v) {
    if (kind === "pct") return fmtPct(v);
    if (kind === "pct1") return fmtPct(v, 1);
    if (kind === "num") return fmtNum(v);
    if (kind === "int") return fmtInt(v);
    if (kind === "turn") return isNum(v) ? fmtNum(v) + "×" : "—";
    if (v === null || v === undefined || typeof v === "object") return "—";
    return String(v);
  }

  function renderBacktestMetrics() {
    const res = data.lbm || { ok: false, data: null };
    const box = $("lbm-content"), period = $("lbm-period");
    const d = res.ok ? res.data : null;
    if (!res.ok || !d || d.available === false) {
      lbmSig = ""; period.hidden = true;
      box.innerHTML = emptyState(res.ok ? "chart" : "alert",
        res.ok ? "Replay metrics not available yet" : "Replay metrics unavailable",
        res.ok ? "Run live_backtest/run_historical_replay.py to generate them." : "The backend could not be reached.");
      return;
    }
    const sig = JSON.stringify(d);
    if (sig === lbmSig) return;
    lbmSig = sig;

    if (d.start_date || d.end_date) {
      period.textContent = fmtDate(d.start_date) + " – " + fmtDate(d.end_date) +
        (isNum(d.n_days_replayed) ? " · " + fmtInt(d.n_days_replayed) + " trading days" : "");
      period.hidden = false;
    } else {
      period.hidden = true;
    }

    const seen = new Set();
    let tiles = "";
    for (const [key, label, kind] of LBM_FIELDS) {
      if (!Object.prototype.hasOwnProperty.call(d, key)) continue;
      seen.add(key);
      tiles += '<div class="metric"><div class="metric-label">' + esc(label) + '</div><div class="metric-value">' + esc(fmtField(kind, d[key])) + "</div></div>";
    }
    let extras = "";
    for (const key of Object.keys(d)) {
      if (seen.has(key) || LBM_SKIP.has(key)) continue;
      const v = d[key];
      if (v !== null && typeof v === "object") continue;
      extras += "<span>" + esc(humanize(key)) + "<b>" + esc(fmtField("str", v)) + "</b></span>";
    }
    box.innerHTML =
      (tiles ? '<div class="cells metric-grid">' + tiles + "</div>" : "") +
      (extras ? '<div class="extra-fields">' + extras + "</div>" : "") +
      (d.methodology ? '<details class="method"><summary>Methodology</summary><p>' + esc(d.methodology) + "</p></details>" : "");
  }

  // ---------- research: pre-registered test verdicts ----------
  let rtSig = "";
  const SLEEVE_LABEL = {
    tsmom: "Trend, ETFs", tsmom_broad: "Trend, 58 markets", tsmom_broad_multi: "Trend, multi-horizon",
    fx_carry: "FX carry", dollar_carry: "Dollar carry", bond_carry: "Bond carry", vix_basis: "VIX futures basis",
    intraday_momentum: "Intraday momentum (ES, NQ)", xs_momentum: "Cross-asset momentum", fx_momentum: "FX momentum",
    fx_value: "FX value", bond_momentum: "Bond momentum", bond_value: "Bond value", turn_of_month: "Turn of the month",
    overnight_persistence: "Overnight persistence", intraday_persistence: "Intraday persistence",
    overnight_intraday_reversal: "Overnight reversal", crypto_tsmom_1w: "1-week trend",
    crypto_tsmom_multi: "Multi-horizon trend", crypto_trend_long_only: "Long-only trend",
  };

  function fmtSharpe(v) { return isNum(v) ? v.toFixed(2) : "—"; }

  function renderResearchTests() {
    const res = data.rt || { ok: false, data: null };
    const box = $("rt-content"), sleevesBox = $("rt-sleeves"), score = $("rt-score");
    const d = res.ok ? res.data : null;
    if (!res.ok || !d || !d.available) {
      rtSig = ""; score.hidden = true; $("rt-legend").innerHTML = "";
      const msg = res.ok ? ["chart", "No pre-registered results yet", "Verdicts appear once a registered hold-out has been run."]
                         : ["alert", "Research results unavailable", "The backend could not be reached."];
      box.innerHTML = emptyState.apply(null, msg);
      sleevesBox.innerHTML = "";
      return;
    }
    const sig = JSON.stringify(d);
    if (sig === rtSig) return;
    rtSig = sig;

    const target = d.target || { sharpe: 2, cagr: 0.1 };
    const passed = d.tests.filter((t) => t.passed).length;
    score.textContent = passed + " of " + d.tests.length + " passed";
    score.dataset.tone = passed === d.tests.length ? "good" : passed ? "warn" : "crit";
    score.hidden = false;

    const num = (label, value, text, bench, miss) =>
      '<div class="verdict-num"><div class="l">' + esc(label) + '</div><div class="v' + (miss ? " miss" : "") + '">' +
      esc(text) + '</div><div class="b" title="' + esc(bench) + '">' + esc(bench) + "</div></div>";

    box.innerHTML = d.tests.map((t) => {
      const r = t.result || {}, b = t.benchmark || {}, bn = b.name || "Benchmark";
      const win = (t.window || []).filter(Boolean).map(fmtDate).join(" – ");
      return '<div class="verdict">' +
        "<div>" +
          '<div class="verdict-name">' + esc(t.name) + "</div>" +
          '<div class="verdict-q">' + esc(t.question) + "</div>" +
          '<div class="verdict-meta">' + esc(win) + " · pass rule: " + esc(t.criterion) +
            (t.registered_at ? " · registered " + esc(fmtDate(t.registered_at)) : "") + "</div>" +
        "</div>" +
        '<div><span class="chip" data-tone="' + (t.passed ? "good" : "crit") + '">' + (t.passed ? "Passed" : "Failed") + "</span></div>" +
        num("Sharpe", r.sharpe, fmtSharpe(r.sharpe), bn + " " + fmtSharpe(b.sharpe),
            !(isNum(r.sharpe) && r.sharpe >= target.sharpe)) +
        num("Return / yr", r.cagr, fmtPct(r.cagr, 1), bn + " " + fmtPct(b.cagr, 1),
            !(isNum(r.cagr) && r.cagr >= target.cagr)) +
        num("Max drawdown", r.max_dd, fmtPct(r.max_dd, 1), bn + " " + fmtPct(b.max_dd, 1), false) +
        num(r.t_label || "t-stat", r.t_stat, isNum(r.t_stat) ? r.t_stat.toFixed(2) : "—", "needs ≥ 2.00",
            !(isNum(r.t_stat) && r.t_stat >= 2)) +
        "</div>";
    }).join("");

    // dumbbells: development (hollow) to hold-out (filled), target as a dashed line
    const rows = (d.sleeves || []).filter((x) => isNum(x.dev_sharpe) || isNum(x.holdout_sharpe));
    const vals = rows.flatMap((x) => [x.dev_sharpe, x.holdout_sharpe]).filter(isNum);
    const lo = Math.floor(Math.min(-0.5, ...vals) * 2) / 2 - 0.1;
    const hi = Math.max(target.sharpe, ...vals) + 0.25;
    const pos = (v) => ((v - lo) / (hi - lo) * 100).toFixed(2) + "%";
    $("rt-legend").innerHTML =
      '<span class="legend-item"><span class="legend-hollow"></span>Development (before the cutoff)</span>' +
      '<span class="legend-item"><span class="legend-filled"></span>Hold-out (after, run once)</span>' +
      '<span class="legend-item"><span class="legend-dash"></span>Target Sharpe ' + esc(fmtSharpe(target.sharpe)) + "</span>";
    const families = [["multi-asset", "Multi-asset · hold-out 2018 – 2026"], ["crypto", "Crypto · hold-out 2022 – 2026"]];
    let html = "";
    for (const [fam, title] of families) {
      const group = rows.filter((x) => x.family === fam)
        .sort((a, b) => (isNum(b.holdout_sharpe) ? b.holdout_sharpe : -9) - (isNum(a.holdout_sharpe) ? a.holdout_sharpe : -9));
      if (!group.length) continue;
      html += '<div class="db-group"><div class="db-group-title">' + esc(title) + "</div>";
      for (const x of group) {
        const name = SLEEVE_LABEL[x.name] || humanize(x.name);
        const dv = x.dev_sharpe, hv = x.holdout_sharpe;
        const label = name + ": development Sharpe " + fmtSharpe(dv) + ", hold-out Sharpe " + fmtSharpe(hv) + (x.in_book ? ", in the tested book" : "");
        const link = isNum(dv) && isNum(hv)
          ? '<span class="db-link" style="left:' + pos(Math.min(dv, hv)) + ";width:calc(" + pos(Math.max(dv, hv)) + " - " + pos(Math.min(dv, hv)) + ')"></span>' : "";
        html += '<div class="db-row" role="img" aria-label="' + esc(label) + '" title="' + esc(label) + '">' +
          '<div class="db-name">' + esc(name) + (x.in_book ? '<span class="tag">tested</span>' : "") + "</div>" +
          '<div class="db-track"><span class="db-zero" style="left:' + pos(0) + '"></span>' +
            '<span class="db-target" style="left:' + pos(target.sharpe) + '"></span>' + link +
            (isNum(dv) ? '<span class="db-dev" style="left:' + pos(dv) + '"></span>' : "") +
            (isNum(hv) ? '<span class="db-hold" style="left:' + pos(hv) + '"></span>' : "") +
          "</div>" +
          '<div class="db-val">' + esc(fmtSharpe(dv)) + " → <b>" + esc(fmtSharpe(hv)) + "</b></div>" +
          "</div>";
      }
      html += "</div>";
    }
    let ticks = "";
    for (let v = Math.ceil(lo); v <= Math.floor(hi); v += 1) ticks += '<span style="left:' + pos(v) + '">' + v + "</span>";
    html += '<div class="db-axis" aria-hidden="true"><div></div><div class="db-ticks">' + ticks + "</div><div></div></div>";
    sleevesBox.innerHTML = html;
  }

  // ---------- tables ----------
  function setCount(id, n) { $(id).textContent = String(n); }

  function renderTrades() {
    const rows = prepared("trades");
    setCount("count-trades", rows.length);
    const tbody = $("trades-tbody");
    if (!rows.length) {
      tbody.innerHTML = data.ok.trades
        ? emptyRow(11, "list", data.trades.length ? "No trades match these filters" : "No trades yet",
            data.trades.length ? "Clear the filters to see all trades." : "Every fill from the paper ledger is listed here.")
        : emptyRow(11, "alert", "Trade log unavailable", "The backend could not be reached.");
      return;
    }
    tbody.innerHTML = rows.map((t, i) => {
      const pnl = t.realized_pnl;
      const cls = isNum(pnl) ? (pnl > 0 ? " pos" : pnl < 0 ? " neg" : "") : "";
      const ret = isNum(pnl) && isNum(t.notional) && t.notional ? pnl / t.notional : null;
      return '<tr data-row="trades" data-index="' + i + '" tabindex="0">' +
        "<td>" + (t.open === true ? chip("Open", "info") : chip("Closed", "neutral")) + backfillTag(t.backfill) + "</td>" +
        '<td class="ticker">' + esc(t.ticker) + "</td>" +
        "<td>" + sideChip(t.direction) + "</td>" +
        "<td>" + esc(fmtDate(t.entry_date)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(t.entry_price)) + "</td>" +
        "<td>" + esc(fmtDate(t.exit_date)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(t.exit_price)) + "</td>" +
        '<td class="num">' + esc(fmtPct(t.size_fraction)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(t.notional)) + "</td>" +
        '<td class="num' + cls + '">' + esc(isNum(ret) ? fmtPct(ret, 2, true) : "—") + "</td>" +
        '<td class="num' + cls + '">' + esc(fmtSignedMoney(pnl)) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderPositions() {
    const rows = prepared("positions");
    setCount("count-positions", rows.length);
    const tbody = $("positions-tbody");
    if (!rows.length) {
      tbody.innerHTML = data.ok.positions
        ? emptyRow(9, "inbox", data.positions.length ? "No positions match these filters" : "No open positions",
            data.positions.length ? "Clear the filters to see all positions." : "Positions appear here when the bot enters a trade.")
        : emptyRow(9, "alert", "Positions unavailable", "The backend could not be reached.");
      return;
    }
    tbody.innerHTML = rows.map((p, i) => {
      const u = p.unrealized_pnl;
      const cls = isNum(u) ? (u > 0 ? " pos" : u < 0 ? " neg" : "") : "";
      return '<tr data-row="positions" data-index="' + i + '" tabindex="0">' +
        '<td><span class="ticker">' + esc(p.ticker) + "</span>" + backfillTag(p.backfill) + "</td>" +
        "<td>" + sideChip(p.direction) + "</td>" +
        "<td>" + esc(fmtDate(p.entry_date)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(p.entry_price)) + "</td>" +
        '<td class="num" title="' + esc(p.last_close_date ? "Close on " + fmtDate(p.last_close_date) : "") + '">' + esc(fmtMoney(p.last_close)) + "</td>" +
        '<td class="num">' + esc(fmtPct(p.size_fraction)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(p.notional)) + "</td>" +
        '<td class="num' + cls + '">' + esc(fmtSignedMoney(u)) + "</td>" +
        '<td class="num">' + esc(fmtInt(p.days_held)) + "</td>" +
        "</tr>";
    }).join("");
  }

  function signalOutcome(s) {
    if (s.allowed === true) return chip("Traded", "good");
    if (s.reason === "no_conviction") return chip("Passed", "neutral");
    if (s.reason === "circuit_breaker_halt") return chip("Breaker", "warn");
    if (s.reason === "risk_blocked") return chip("Blocked", "serious");
    return chip(s.reason ? humanize(s.reason) : "—", "neutral");
  }

  function renderSignals() {
    const rows = prepared("signals");
    setCount("count-signals", rows.length);
    const tbody = $("signals-tbody");
    if (!rows.length) {
      tbody.innerHTML = data.ok.signals
        ? emptyRow(8, "chart", data.signals.length ? "No signals match these filters" : "No scored events yet",
            data.signals.length ? "Clear the filters to see every scored event." : "Each earnings report the bot scores is listed here with its decision.")
        : emptyRow(8, "alert", "Signals unavailable", "The backend could not be reached.");
      return;
    }
    tbody.innerHTML = rows.map((s, i) => {
      const proba = s.calibrated_proba;
      const pct = isNum(proba) ? Math.max(0, Math.min(1, proba)) * 100 : 0;
      return '<tr data-row="signals" data-index="' + i + '" tabindex="0">' +
        "<td>" + esc(fmtDate(s.as_of_date)) + "</td>" +
        '<td><span class="ticker">' + esc(s.ticker) + "</span>" + backfillTag(s.backfill) + "</td>" +
        "<td>" + sideChip(s.direction) + "</td>" +
        '<td class="num">' + esc(fmtNum(s.sue)) + "</td>" +
        '<td class="num"><span class="bar-cell">' + esc(isNum(proba) ? fmtPct(proba, 1) : "—") +
          '<span class="bar-track"><span class="bar-fill" style="width:' + pct.toFixed(0) + '%"></span></span></span></td>' +
        '<td class="num">' + esc(isNum(s.size_fraction) && s.size_fraction > 0 ? fmtPct(s.size_fraction) : "—") + "</td>" +
        "<td>" + signalOutcome(s) + "</td>" +
        '<td class="text-cell">' + esc(s.detail) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderCycles() {
    const rows = prepared("cycles");
    setCount("count-cycles", rows.length);
    const tbody = $("cycles-tbody");
    if (!rows.length) {
      tbody.innerHTML = data.ok.cycles
        ? emptyRow(11, "list", data.cycles.length ? "No cycles match these filters" : "No cycles logged yet",
            data.cycles.length ? "Clear the filters to see every run." : "Each scheduled run of the bot adds a row here.")
        : emptyRow(11, "alert", "Cycle log unavailable", "The backend could not be reached.");
      return;
    }
    tbody.innerHTML = rows.map((c, i) => {
      const tier = tierMeta(c.breaker_tier);
      const entries = (c.entries || []).filter((e) => e && e.allowed).length;
      const exits = (c.exits || []).length;
      const errors = (c.errors || []).length;
      const session = c.session_open === undefined
        ? '<span class="muted" title="Logged before session checks existed">—</span>'
        : '<span title="' + esc(c.session_detail) + '">' + (c.session_open ? chip("Open", "info") : chip("Closed", "neutral")) + "</span>";
      return '<tr data-row="cycles" data-index="' + i + '" tabindex="0">' +
        "<td>" + esc(fmtDate(c.as_of_date)) + "</td>" +
        '<td class="muted">' + esc(fmtStamp(c.ts)) + "</td>" +
        "<td>" + session + "</td>" +
        "<td>" + chip(tier.label, tier.tone) + "</td>" +
        "<td>" + (c.kill_switch_engaged === true ? chip("Engaged", "crit") : chip("Clear", "neutral")) + "</td>" +
        '<td class="num">' + esc(fmtMoney(c.nav_before)) + "</td>" +
        '<td class="num">' + esc(fmtMoney(c.nav_after)) + "</td>" +
        '<td class="num">' + esc(fmtInt(c.entries_considered)) + "</td>" +
        '<td class="num">' + entries + "</td>" +
        '<td class="num">' + exits + "</td>" +
        '<td class="num' + (errors > 0 ? " neg" : "") + '">' + errors + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderAlerts() {
    const rows = prepared("alerts");
    setCount("count-alerts", rows.length);
    const tbody = $("alerts-tbody");
    if (!rows.length) {
      tbody.innerHTML = data.ok.alerts
        ? emptyRow(3, "bell", data.alerts.length ? "No alerts match these filters" : "No alerts",
            data.alerts.length ? "Clear the filters to see every alert." : "Risk and watchdog alerts from the bot appear here.")
        : emptyRow(3, "alert", "Alerts unavailable", "The backend could not be reached.");
      return;
    }
    tbody.innerHTML = rows.map((a, i) => {
      const meta = kindMeta(a.kind);
      return '<tr data-row="alerts" data-index="' + i + '" tabindex="0">' +
        '<td class="muted">' + esc(fmtStamp(a.ts)) + "</td>" +
        "<td>" + chip(meta.label, meta.tone) + backfillTag(a.backfill) + "</td>" +
        '<td class="text-cell">' + esc(a.message) + "</td>" +
        "</tr>";
    }).join("");
  }

  // Mirrors bot/earnings_watcher.py::effective_trading_date: an after-close
  // report is first tradable at the next business day's close.
  function tradableFrom(isoStamp, timing) {
    const day = dayOf(isoStamp);
    if (!day) return "—";
    const [y, m, d] = day.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    if (timing === "after_close") date.setDate(date.getDate() + 1);
    while (date.getDay() === 0 || date.getDay() === 6) date.setDate(date.getDate() + 1);
    return dateFmt.format(date);
  }

  function renderUpcoming() {
    const res = data.upcoming || { ok: false, data: null };
    const tbody = $("upcoming-tbody");
    const d = res.ok ? res.data : null;
    const list = d && Array.isArray(d.events) ? sortRows(d.events, "upcoming") : [];
    setCount("count-upcoming", list.length);
    if (!res.ok) { tbody.innerHTML = emptyRow(6, "alert", "Schedule unavailable", "The backend could not be reached."); return; }
    if (!d || d.available === false) {
      tbody.innerHTML = emptyRow(6, "list", "No schedule yet", "The next bot cycle writes the earnings calendar for the traded universe.");
      return;
    }
    if (!list.length) {
      tbody.innerHTML = emptyRow(6, "list", "No reports scheduled", "Nothing in the universe reports in the next " + fmtInt(d.horizon_days) + " days.");
      return;
    }
    $("upcoming-sub").textContent = "Next " + fmtInt(d.horizon_days) + " days · from the " + fmtDate(d.as_of_date) + " cycle";
    tbody.innerHTML = list.map((e) => "<tr>" +
      "<td>" + esc(fmtDate(e.earnings_date)) + "</td>" +
      '<td class="muted">' + esc(TIMING_LABEL[e.timing] || "—") + "</td>" +
      '<td class="ticker">' + esc(e.ticker) + "</td>" +
      '<td class="num">' + esc(fmtMoney(e.eps_estimate)) + "</td>" +
      '<td class="num">' + esc(tradableFrom(e.earnings_date, e.timing)) + "</td>" +
      '<td class="num">' + esc(isNum(e.days_until) ? (e.days_until === 0 ? "Today" : e.days_until + "d") : "—") + "</td>" +
      "</tr>").join("");
  }

  // ---------- event feed ----------
  const FILTERS = ["all", "cycles", "trades", "risk"];

  function renderFeed() {
    const res = data.feed || { ok: false, data: null };
    const list = $("feed-list");
    for (const btn of document.querySelectorAll("[data-filter]")) {
      btn.setAttribute("aria-pressed", String(btn.dataset.filter === ui.feedFilter));
    }
    if (!res.ok) {
      FILTERS.forEach((f) => { $("fc-" + f).textContent = ""; });
      $("feed-age").textContent = "Cycle runs, fills and risk alerts";
      list.innerHTML = "<li>" + emptyState("alert", "Event feed unavailable", "The backend could not be reached.") + "</li>";
      return;
    }
    const events = (Array.isArray(res.data) ? res.data : []).filter(Boolean);
    const counts = { all: events.length, cycles: 0, trades: 0, risk: 0 };
    for (const e of events) {
      const g = kindMeta(e.kind).group;
      if (g in counts) counts[g] += 1;
    }
    FILTERS.forEach((f) => { $("fc-" + f).textContent = counts[f] + (f === "all" && events.length >= EVENT_FEED_LIMIT ? "+" : ""); });

    const newest = events.length && isNum(events[0].ts) ? events[0].ts : null;
    $("feed-age").textContent = newest !== null ? "Latest event " + fmtAgo(Date.now() / 1000 - newest) : "Cycle runs, fills and risk alerts";

    const shown = ui.feedFilter === "all" ? events : events.filter((e) => kindMeta(e.kind).group === ui.feedFilter);
    if (!shown.length) {
      list.innerHTML = "<li>" + emptyState("inbox", events.length ? "Nothing in this filter" : "No events yet",
        events.length ? "Try another filter to see other event types." : "Cycle runs and alerts will stream in here.") + "</li>";
      return;
    }
    list.innerHTML = shown.map((e) => {
      const meta = kindMeta(e.kind);
      return '<li class="feed-item" data-tone="' + meta.tone + '">' +
        '<span class="feed-dot" aria-hidden="true"></span><div>' +
        '<div class="feed-top"><span class="feed-kind">' + esc(meta.label) + backfillTag(e.backfill) +
        '</span><time class="feed-time">' + esc(fmtStamp(e.ts)) + "</time></div>" +
        '<div class="feed-text" title="' + esc(e.summary) + '">' + esc(e.summary) + "</div></div></li>";
    }).join("");
  }

  // ---------- detail sheet ----------
  function defList(pairs) {
    return '<dl class="sheet-list">' + pairs.filter(Boolean).map(([k, v]) =>
      "<dt>" + esc(k) + "</dt><dd>" + v + "</dd>").join("") + "</dl>";
  }

  function signalFor(ticker, day) {
    return data.signals.find((s) => s.ticker === ticker && s.allowed === true && dayOf(s.as_of_date) === dayOf(day)) ||
           data.signals.find((s) => s.ticker === ticker && dayOf(s.as_of_date) === dayOf(day)) || null;
  }

  function signalSection(sig) {
    if (!sig) return "";
    return '<div class="sheet-section"><h3>Why the bot took it</h3>' + defList([
      ["Standardized surprise (SUE)", esc(fmtNum(sig.sue))],
      ["Model probability", esc(isNum(sig.calibrated_proba) ? fmtPct(sig.calibrated_proba, 1) : "—")],
      ["Kelly size", esc(isNum(sig.size_fraction) ? fmtPct(sig.size_fraction) : "—")],
      ["Decision", esc(sig.detail || sig.reason || "—")],
      sig.earnings_date ? ["Reported", esc(fmtDate(sig.earnings_date))] : null,
    ]) + "</div>";
  }

  function openSheet(kind, row) {
    const sheet = $("sheet"), scrim = $("sheet-scrim");
    let title = "", sub = "", body = "";

    if (kind === "trades" || kind === "positions") {
      const isTrade = kind === "trades";
      // An open trade's mark lives in the positions payload, not the ledger.
      const mark = isTrade && row.open ? data.positions.find((p) => p.ticker === row.ticker) : null;
      const pnl = isTrade ? (row.open ? (mark ? mark.unrealized_pnl : null) : row.realized_pnl) : row.unrealized_pnl;
      const ret = isNum(pnl) && isNum(row.notional) && row.notional ? pnl / row.notional : null;
      const state = isTrade ? (row.open ? "Open" : "Closed") : "Open";
      title = row.ticker || "Trade";
      sub = [row.direction ? humanize(row.direction) : "", state, row.backfill ? "Backfilled" : ""].filter(Boolean).join(" · ");
      body =
        '<div class="sheet-figure"><div class="big ' + (isNum(pnl) ? (pnl > 0 ? "pos" : pnl < 0 ? "neg" : "") : "") + '" style="color:' +
          (isNum(pnl) && pnl !== 0 ? (pnl > 0 ? "var(--good-ink)" : "var(--crit-ink)") : "inherit") + '">' +
          esc(fmtSignedMoney(pnl)) + "</div>" +
          '<div class="cap">' + esc(isTrade && row.open === false ? "Realized" : "Open") + " P&L" +
          (isTrade && row.open && !mark ? " · not marked" : "") +
          (isNum(ret) ? " · " + esc(fmtPct(ret, 2, true)) : "") + "</div></div>" +
        defList([
          ["Entry date", esc(fmtDate(row.entry_date))],
          ["Entry price", esc(fmtMoney(row.entry_price))],
          isTrade && !row.open ? ["Exit date", esc(fmtDate(row.exit_date))] : null,
          isTrade && !row.open ? ["Exit price", esc(fmtMoney(row.exit_price))] : null,
          mark || !isTrade ? ["Last close", esc(fmtMoney(mark ? mark.last_close : row.last_close))] : null,
          mark || !isTrade ? ["Marked on", esc(fmtDate(mark ? mark.last_close_date : row.last_close_date))] : null,
          ["Size of NAV", esc(fmtPct(row.size_fraction))],
          ["Notional", esc(fmtMoney(row.notional))],
          isNum(row.gross_pnl) ? ["P&L before costs", esc(fmtSignedMoney(row.gross_pnl))] : null,
          isNum(row.cost) ? ["Trading cost", esc("−" + fmtMoney(row.cost))] : null,
          isNum(row.days_held) ? ["Days held", esc(fmtInt(row.days_held))] : null,
        ]) +
        signalSection(signalFor(row.ticker, row.entry_date));
    } else if (kind === "signals") {
      title = row.ticker || "Signal";
      sub = [fmtDate(row.as_of_date), row.direction ? humanize(row.direction) : "", row.backfill ? "Backfilled" : ""].filter(Boolean).join(" · ");
      body =
        '<div class="sheet-figure"><div class="big">' + esc(isNum(row.calibrated_proba) ? fmtPct(row.calibrated_proba, 1) : "—") + "</div>" +
        '<div class="cap">Model probability that the trade clears its cost bar</div></div>' +
        defList([
          ["Standardized surprise (SUE)", esc(fmtNum(row.sue))],
          ["Direction", esc(row.direction ? humanize(row.direction) : "—")],
          ["Kelly size", esc(isNum(row.size_fraction) && row.size_fraction > 0 ? fmtPct(row.size_fraction) : "0.00%")],
          ["Outcome", esc(row.allowed ? "Traded" : "Not traded")],
          ["Reported", esc(fmtDate(row.earnings_date))],
        ]) +
        '<div class="sheet-section"><h3>Gate decision</h3><p class="sheet-quote">' + esc(row.detail || row.reason || "—") + "</p></div>";
    } else if (kind === "cycles") {
      const entries = (row.entries || []);
      title = fmtDate(row.as_of_date);
      sub = "Cycle ran " + fmtStamp(row.ts);
      body = defList([
        ["Session", esc(row.session_open === undefined ? "—" : row.session_open ? "Open" : "Closed")],
        ["Circuit breaker", esc(tierMeta(row.breaker_tier).label)],
        ["Kill switch", esc(row.kill_switch_engaged ? "Engaged" : "Clear")],
        ["NAV before", esc(fmtMoney(row.nav_before))],
        ["NAV after", esc(fmtMoney(row.nav_after))],
        ["Events considered", esc(fmtInt(row.entries_considered))],
        ["Entries placed", String(entries.filter((e) => e && e.allowed).length)],
        ["Exits", String((row.exits || []).length)],
      ]) +
      (row.session_detail ? '<div class="sheet-section"><h3>Session check</h3><p class="sheet-quote">' + esc(row.session_detail) + "</p></div>" : "") +
      (entries.length ? '<div class="sheet-section"><h3>Decisions</h3><p class="sheet-quote">' +
        entries.map((e) => esc(e.ticker + " " + (e.allowed ? "traded" : "skipped") + " — " + (e.detail || e.reason || ""))).join("<br>") + "</p></div>" : "") +
      ((row.errors || []).length ? '<div class="sheet-section"><h3>Errors</h3><p class="sheet-quote">' +
        row.errors.map((e) => esc(String(e))).join("<br>") + "</p></div>" : "");
    } else if (kind === "alerts") {
      const meta = kindMeta(row.kind);
      title = meta.label;
      sub = fmtStamp(row.ts) + (row.backfill ? " · Backfilled" : "");
      body = '<div class="sheet-section" style="margin-top:0;border:0;padding-top:0"><p class="sheet-quote">' + esc(row.message) + "</p></div>" +
        defList(Object.keys(row).filter((k) => ["ts", "kind", "message", "backfill"].indexOf(k) === -1)
          .map((k) => [humanize(k), esc(String(row[k]))]));
    }

    $("sheet-title").textContent = title;
    $("sheet-sub").textContent = sub;
    $("sheet-body").innerHTML = body;
    scrim.hidden = false; sheet.hidden = false;
    requestAnimationFrame(() => { scrim.classList.add("open"); sheet.classList.add("open"); });
    $("sheet-close").focus();
  }

  function closeSheet() {
    const sheet = $("sheet"), scrim = $("sheet-scrim");
    sheet.classList.remove("open"); scrim.classList.remove("open");
    setTimeout(() => { sheet.hidden = true; scrim.hidden = true; }, 240);
  }

  document.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-row]");
    if (!row) return;
    const kind = row.dataset.row;
    const rows = prepared(kind);
    const item = rows[Number(row.dataset.index)];
    if (item) openSheet(kind, item);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const row = e.target.closest && e.target.closest("tr[data-row]");
    if (!row) return;
    e.preventDefault();
    row.click();
  });
  $("sheet-close").addEventListener("click", closeSheet);
  $("sheet-scrim").addEventListener("click", closeSheet);

  // ---------- toasts ----------
  function toast(message, tone) {
    const el = document.createElement("div");
    el.className = "toast";
    el.dataset.tone = tone;
    el.setAttribute("role", tone === "crit" ? "alert" : "status");
    const text = document.createElement("span");
    text.textContent = message;
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss");
    close.innerHTML = svg("x");
    close.addEventListener("click", () => el.remove());
    el.append(text, close);
    $("toasts").appendChild(el);
    if (tone !== "crit") setTimeout(() => el.remove(), 6000);  // errors stay until dismissed
  }

  // ---------- confirm modal ----------
  // An in-page dialog instead of window.confirm(): browsers can silently
  // suppress native confirm() (repeated-dialog suppression, some privacy
  // extensions, sandboxed contexts), and a suppressed confirm() returns false
  // with no visible error, which looks exactly like a dead button.
  function confirmDialog(opts, onConfirm) {
    const modal = $("confirm-modal"), ok = $("confirm-ok"), cancel = $("confirm-cancel");
    const opener = document.activeElement;
    $("confirm-title").textContent = opts.title;
    $("confirm-body").textContent = opts.body;
    $("confirm-icon").dataset.tone = opts.tone;
    $("confirm-icon").innerHTML = svg(opts.tone === "crit" ? "alert" : "play");
    ok.textContent = opts.confirmLabel;
    ok.className = "btn " + (opts.tone === "crit" ? "btn-danger" : "btn-accent");

    modal.hidden = false;
    requestAnimationFrame(() => modal.classList.add("open"));
    cancel.focus();

    function close() {
      modal.classList.remove("open");
      setTimeout(() => { modal.hidden = true; }, 180);
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", close);
      modal.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey, true);
      if (opener && typeof opener.focus === "function") opener.focus();
    }
    function onOk() { close(); onConfirm(); }
    function onBackdrop(e) { if (e.target === modal) close(); }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key === "Tab") { e.preventDefault(); (document.activeElement === cancel ? ok : cancel).focus(); }
    }
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", close);
    modal.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey, true);
  }

  // ---------- schedule controls ----------
  async function postControl(action) {
    controlsBusy = true;
    for (const id of ["btn-start", "btn-stop", "menu-start", "menu-stop"]) $(id).disabled = true;
    toast((action === "start" ? "Starting" : "Stopping") + " the schedule: calling launchctl…", "neutral");
    try {
      const res = await fetch("/api/control/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      let payload = null;
      try { payload = await res.json(); } catch (e) { /* non-JSON body, tolerate */ }
      if (!res.ok) toast("Control action failed (" + res.status + "): " + (payload && payload.detail ? payload.detail : "unknown error"), "crit");
      else toast((action === "start" ? "Start" : "Stop") + " command sent successfully.", "good");
    } catch (err) {
      toast("Control action failed: could not reach the backend.", "crit");
    } finally {
      controlsBusy = false;
      renderLaunchd(await fetchLaunchdStatus());
    }
  }

  function confirmStart() {
    confirmDialog({
      title: "Start the paper-trade schedule?",
      body: "This calls launchctl bootstrap on the real pead_bot and pead_watchdog LaunchAgents. " +
        "Because RunAtLoad=true, it immediately triggers one real (paper-only) run_cycle() now, " +
        "in addition to future scheduled runs.\n\nThis bot is paper-trade only. No live-trading path exists.",
      confirmLabel: "Start schedule", tone: "good",
    }, () => postControl("start"));
  }
  function confirmStop() {
    confirmDialog({
      title: "Stop the paper-trade schedule?",
      body: "This unloads both pead_bot and its dead-man's-switch watchdog together, so no false " +
        "stale-heartbeat alerts fire while paused.\n\nNo further paper cycles run until you start the schedule again.",
      confirmLabel: "Stop schedule", tone: "crit",
    }, () => postControl("stop"));
  }
  $("btn-start").addEventListener("click", confirmStart);
  $("btn-stop").addEventListener("click", confirmStop);

  // ---------- menus ----------
  let openMenu = null;

  function closeMenu() {
    if (!openMenu) return;
    const { root, button, panel } = openMenu;
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    root.classList.remove("open");
    openMenu = null;
  }

  function setupMenu(root) {
    const button = root.querySelector("button[aria-haspopup='menu']");
    const panel = root.querySelector(".menu-panel");
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = openMenu && openMenu.panel === panel;
      closeMenu();
      if (wasOpen) return;
      panel.hidden = false;
      button.setAttribute("aria-expanded", "true");
      root.classList.add("open");
      openMenu = { root, button, panel };
    });
    panel.addEventListener("keydown", (e) => {
      const items = Array.from(panel.querySelectorAll(".menu-item:not(:disabled)"));
      const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Escape") { e.preventDefault(); closeMenu(); button.focus(); }
    });
  }
  document.querySelectorAll(".menu").forEach(setupMenu);
  document.addEventListener("click", () => closeMenu());

  // Bot menu actions
  $("menu-start").addEventListener("click", () => { closeMenu(); confirmStart(); });
  $("menu-stop").addEventListener("click", () => { closeMenu(); confirmStop(); });

  function applyPollChoice() {
    for (const btn of document.querySelectorAll("[data-poll]")) {
      btn.setAttribute("aria-checked", String(Number(btn.dataset.poll) === ui.pollMs));
    }
    document.documentElement.style.setProperty("--poll-duration", (ui.pollMs || 20000) / 1000 + "s");
  }
  for (const btn of document.querySelectorAll("[data-poll]")) {
    btn.addEventListener("click", () => {
      ui.pollMs = Number(btn.dataset.poll);
      store.set("pead.pollMs", String(ui.pollMs));
      applyPollChoice();
      restartPolling();
      closeMenu();
      toast(ui.pollMs ? "Auto-refresh every " + (ui.pollMs / 1000) + " seconds" : "Auto-refresh off", "neutral");
    });
  }

  // ---------- theme ----------
  function applyTheme() {
    if (ui.theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", ui.theme);
    for (const btn of document.querySelectorAll("[data-theme]")) {
      btn.setAttribute("aria-checked", String(btn.dataset.theme === ui.theme));
    }
    rethemeCharts();
  }
  function rethemeCharts() {
    for (const key of Object.keys(charts)) {
      if (charts[key]) { charts[key].destroy(); charts[key] = null; }
      chartSig[key] = "";
    }
    safeRender(renderEquity);
    safeRender(renderMonteCarlo);
  }
  for (const btn of document.querySelectorAll(".menu-item[data-theme]")) {
    btn.addEventListener("click", () => {
      ui.theme = btn.dataset.theme;
      store.set("pead.theme", ui.theme);
      applyTheme();
      closeMenu();
    });
  }
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (ui.theme === "system") rethemeCharts();
  });

  // ---------- views & tabs ----------
  function setView(name, fromHash) {
    if (VIEWS.indexOf(name) === -1) name = "overview";
    ui.view = name;
    for (const v of VIEWS) {
      $("nav-" + v).setAttribute("aria-selected", String(v === name));
      $("view-" + v).hidden = v !== name;
    }
    if (!fromHash) location.hash = name;
    // Chart.js sizes to a visible container, so redraw once this view shows.
    if (name === "overview") { chartSig.equity = ""; safeRender(renderEquity); }
    if (name === "research") { chartSig.mc = ""; safeRender(renderMonteCarlo); }
  }
  for (const v of VIEWS) $("nav-" + v).addEventListener("click", () => setView(v));
  window.addEventListener("hashchange", () => setView(location.hash.replace("#", ""), true));

  function setTab(name) {
    if (TABS.indexOf(name) === -1) name = "trades";
    ui.tab = name;
    store.set("pead.tab", name);
    for (const t of TABS) {
      const btn = document.querySelector("#activity-tabs [data-tab='" + t + "']");
      btn.setAttribute("aria-selected", String(t === name));
      $("panel-" + t).hidden = t !== name;
    }
    renderFilterSummary();
  }
  $("activity-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tab]");
    if (btn) setTab(btn.dataset.tab);
  });

  // ---------- filters ----------
  function renderFilterSummary() {
    const total = { trades: data.trades, positions: data.positions, signals: data.signals,
                    cycles: data.cycles, alerts: data.alerts }[ui.tab] || [];
    const shown = prepared(ui.tab).length;
    const active = ui.filters.search || ui.filters.side !== "all" || ui.filters.status !== "all" || ui.filters.range !== "all";
    $("filter-result").textContent = active ? "Showing " + shown + " of " + total.length : shown + " rows";
    $("filter-clear").hidden = !active;
    $("search-clear").hidden = !ui.filters.search;
  }

  function renderActivity() {
    safeRender(renderTrades);
    safeRender(renderPositions);
    safeRender(renderSignals);
    safeRender(renderCycles);
    safeRender(renderAlerts);
    renderFilterSummary();
  }

  const OPTION_LABELS = {
    side: { all: "All", long: "Long", short: "Short" },
    status: { all: "All", open: "Open", closed: "Closed", winners: "Winners", losers: "Losers" },
    range: { all: "All time", 7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days" },
  };

  function setupFilterMenu(id, field) {
    const root = $(id);
    const valueEl = root.querySelector("[data-value]");
    function sync() {
      valueEl.textContent = OPTION_LABELS[field][ui.filters[field]] || String(ui.filters[field]);
      for (const item of root.querySelectorAll("[data-option]")) {
        item.setAttribute("aria-checked", String(item.dataset.option === String(ui.filters[field])));
      }
    }
    for (const item of root.querySelectorAll("[data-option]")) {
      item.addEventListener("click", () => {
        ui.filters[field] = item.dataset.option;
        sync(); closeMenu(); renderActivity();
      });
    }
    sync();
  }
  setupFilterMenu("menu-side", "side");
  setupFilterMenu("menu-status", "status");
  setupFilterMenu("menu-range", "range");

  $("filter-search").addEventListener("input", (e) => {
    ui.filters.search = e.target.value;
    renderActivity();
  });
  $("search-clear").addEventListener("click", () => {
    ui.filters.search = "";
    $("filter-search").value = "";
    renderActivity();
    $("filter-search").focus();
  });
  $("filter-clear").addEventListener("click", () => {
    ui.filters = { search: "", side: "all", status: "all", range: "all" };
    $("filter-search").value = "";
    setupFilterMenu("menu-side", "side");
    setupFilterMenu("menu-status", "status");
    setupFilterMenu("menu-range", "range");
    renderActivity();
  });

  // ---------- sorting ----------
  function setupSorting(tableId, kind, rerender) {
    const table = $(tableId);
    table.querySelectorAll("th[data-sort-key]").forEach((th) => {
      th.querySelector("button").addEventListener("click", () => {
        const key = th.dataset.sortKey;
        const current = ui.sort[kind];
        ui.sort[kind] = { key, dir: current.key === key && current.dir === "desc" ? "asc" : "desc" };
        syncSortIndicators(tableId, kind);
        rerender();
      });
    });
    syncSortIndicators(tableId, kind);
  }
  function syncSortIndicators(tableId, kind) {
    const { key, dir } = ui.sort[kind];
    $(tableId).querySelectorAll("th[data-sort-key]").forEach((th) => {
      if (th.dataset.sortKey === key) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
  }
  setupSorting("table-trades", "trades", () => safeRender(renderTrades));
  setupSorting("table-positions", "positions", () => safeRender(renderPositions));
  setupSorting("table-signals", "signals", () => safeRender(renderSignals));
  setupSorting("table-cycles", "cycles", () => safeRender(renderCycles));
  setupSorting("table-alerts", "alerts", () => safeRender(renderAlerts));
  setupSorting("table-upcoming", "upcoming", () => safeRender(renderUpcoming));

  // ---------- chart range & feed filter ----------
  for (const btn of document.querySelectorAll("[data-range]")) {
    btn.addEventListener("click", () => {
      ui.range = btn.dataset.range;
      store.set("pead.chartRange", ui.range);
      for (const b of document.querySelectorAll("[data-range]")) b.setAttribute("aria-pressed", String(b.dataset.range === ui.range));
      chartSig.equity = "";
      safeRender(renderEquity);
    });
    btn.setAttribute("aria-pressed", String(btn.dataset.range === ui.range));
  }
  document.querySelector("[data-filter]").parentElement.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-filter]");
    if (!btn) return;
    ui.feedFilter = btn.dataset.filter;
    store.set("pead.feedFilter", ui.feedFilter);
    $("feed-list").scrollTop = 0;
    safeRender(renderFeed);
  });

  // ---------- command palette ----------
  let paletteItems = [], paletteIndex = 0;

  function baseCommands() {
    const cmds = [
      { icon: "view", label: "Go to Overview", hint: "View", run: () => setView("overview") },
      { icon: "view", label: "Go to Activity", hint: "View", run: () => setView("activity") },
      { icon: "view", label: "Go to Research", hint: "View", run: () => setView("research") },
      { icon: "list", label: "Show trades", hint: "Tab", run: () => { setView("activity"); setTab("trades"); } },
      { icon: "list", label: "Show open positions", hint: "Tab", run: () => { setView("activity"); setTab("positions"); } },
      { icon: "chart", label: "Show signals", hint: "Tab", run: () => { setView("activity"); setTab("signals"); } },
      { icon: "list", label: "Show cycles", hint: "Tab", run: () => { setView("activity"); setTab("cycles"); } },
      { icon: "bell", label: "Show alerts", hint: "Tab", run: () => { setView("activity"); setTab("alerts"); } },
      { icon: "refresh", label: "Refresh now", hint: "Action", run: () => refreshAll(true) },
      { icon: "theme", label: "Theme: system", hint: "Appearance", run: () => { ui.theme = "system"; store.set("pead.theme", ui.theme); applyTheme(); } },
      { icon: "theme", label: "Theme: light", hint: "Appearance", run: () => { ui.theme = "light"; store.set("pead.theme", ui.theme); applyTheme(); } },
      { icon: "theme", label: "Theme: dark", hint: "Appearance", run: () => { ui.theme = "dark"; store.set("pead.theme", ui.theme); applyTheme(); } },
      { icon: "clock", label: "Winners only", hint: "Filter", run: () => { setView("activity"); setTab("trades"); ui.filters.status = "winners"; setupFilterMenu("menu-status", "status"); renderActivity(); } },
      { icon: "clock", label: "Losers only", hint: "Filter", run: () => { setView("activity"); setTab("trades"); ui.filters.status = "losers"; setupFilterMenu("menu-status", "status"); renderActivity(); } },
      { icon: "x", label: "Clear filters", hint: "Filter", run: () => $("filter-clear").click() },
    ];
    if (controlsVerified) {
      cmds.push({ icon: "play", label: "Start schedule…", hint: "Bot", run: confirmStart });
      cmds.push({ icon: "stop", label: "Stop schedule…", hint: "Bot", run: confirmStop });
    }
    const tickers = new Set();
    for (const row of data.trades.concat(data.positions, data.signals)) if (row.ticker) tickers.add(row.ticker);
    for (const t of Array.from(tickers).sort()) {
      cmds.push({
        icon: "ticker", label: t, hint: "Filter by ticker",
        run: () => { setView("activity"); ui.filters.search = t; $("filter-search").value = t; renderActivity(); },
      });
    }
    return cmds;
  }

  function renderPalette(query) {
    const q = query.trim().toLowerCase();
    paletteItems = baseCommands().filter((c) => !q || c.label.toLowerCase().indexOf(q) !== -1 || c.hint.toLowerCase().indexOf(q) !== -1);
    paletteIndex = 0;
    const list = $("palette-list");
    if (!paletteItems.length) {
      list.innerHTML = '<li class="palette-empty">No matching command</li>';
      return;
    }
    list.innerHTML = paletteItems.map((c, i) =>
      '<li><button class="palette-item" type="button" role="option" data-index="' + i + '" aria-selected="' + (i === 0) + '">' +
      svg(c.icon) + "<span>" + esc(c.label) + '</span><span class="hint">' + esc(c.hint) + "</span></button></li>").join("");
  }

  function highlightPalette() {
    const items = $("palette-list").querySelectorAll(".palette-item");
    items.forEach((el, i) => {
      el.setAttribute("aria-selected", String(i === paletteIndex));
      if (i === paletteIndex) el.scrollIntoView({ block: "nearest" });
    });
  }

  function openPalette() {
    const palette = $("palette"), input = $("palette-input");
    palette.hidden = false;
    requestAnimationFrame(() => palette.classList.add("open"));
    input.value = "";
    renderPalette("");
    input.focus();
  }
  function closePalette() {
    const palette = $("palette");
    palette.classList.remove("open");
    setTimeout(() => { palette.hidden = true; }, 180);
  }
  function runPalette(index) {
    const cmd = paletteItems[index];
    closePalette();
    if (cmd) cmd.run();
  }

  $("palette-btn").addEventListener("click", openPalette);
  $("palette-input").addEventListener("input", (e) => renderPalette(e.target.value));
  $("palette-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); paletteIndex = Math.min(paletteIndex + 1, paletteItems.length - 1); highlightPalette(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); paletteIndex = Math.max(paletteIndex - 1, 0); highlightPalette(); }
    else if (e.key === "Enter") { e.preventDefault(); runPalette(paletteIndex); }
  });
  $("palette-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".palette-item");
    if (btn) runPalette(Number(btn.dataset.index));
  });
  $("palette").addEventListener("click", (e) => { if (e.target === $("palette")) closePalette(); });

  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (e.key === "Escape") {
      if (!$("palette").hidden) { closePalette(); return; }
      if (!$("sheet").hidden) { closeSheet(); return; }
      closeMenu();
      return;
    }
    if (typing) return;
    if (e.key === "/") { e.preventDefault(); setView("activity"); $("filter-search").focus(); }
    else if (e.key === "r") refreshAll(true);
  });

  // ---------- orchestration ----------
  let refreshing = false, pollCount = 0, pollTimer = null;

  function safeRender(fn) {
    const args = Array.prototype.slice.call(arguments, 1);
    try { fn.apply(null, args); } catch (err) { console.error("Render failed:", fn.name, err); }
  }

  function restartPollLine() {
    const bar = $("poll-line");
    bar.classList.remove("run");
    void bar.offsetWidth;  // restart the CSS animation
    if (ui.pollMs) bar.classList.add("run");
  }

  function restartPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    if (!ui.pollMs) { $("poll-line").classList.remove("run"); return; }
    pollTimer = setInterval(() => { if (!document.hidden) refreshAll(); }, ui.pollMs);
    restartPollLine();
  }

  async function refreshAll(force) {
    if (refreshing) return;
    refreshing = true;
    document.body.classList.add("is-refreshing");
    const withReference = force === true || pollCount % REFERENCE_EVERY_N_POLLS === 0 || !data.mc || !data.lbm || !data.rt;
    pollCount += 1;
    try {
      const [status, launchd, stats, positions, trades, signals, equity, alerts, cycles, feed, upcoming, mc, lbm, rt] = await Promise.all([
        getJSON("/api/status"),
        fetchLaunchdStatus(),
        getJSON("/api/stats"),
        getJSON("/api/positions"),
        getJSON("/api/trades?limit=500"),
        getJSON("/api/signals?limit=500"),
        getJSON("/api/equity_curve"),
        getJSON("/api/alerts?limit=200"),
        getJSON("/api/cycle_log?limit=200"),
        getJSON("/api/event_feed?limit=" + EVENT_FEED_LIMIT),
        getJSON("/api/upcoming_earnings"),
        withReference ? getJSON("/api/monte_carlo") : Promise.resolve(data.mc),
        withReference ? getJSON("/api/live_backtest_metrics") : Promise.resolve(data.lbm),
        withReference ? getJSON("/api/research_tests") : Promise.resolve(data.rt),
      ]);

      data.status = status.data;
      data.stats = stats.data;
      data.positions = positions.ok && Array.isArray(positions.data) ? positions.data : [];
      data.trades = trades.ok && Array.isArray(trades.data) ? trades.data : [];
      data.signals = signals.ok && Array.isArray(signals.data) ? signals.data : [];
      data.cycles = cycles.ok && Array.isArray(cycles.data) ? cycles.data : [];
      data.alerts = alerts.ok && Array.isArray(alerts.data) ? alerts.data : [];
      data.feed = feed;
      data.upcoming = upcoming;
      data.equity = equity;
      data.mc = mc;
      data.lbm = lbm;
      data.rt = rt;
      data.ok = { stats: stats.ok, positions: positions.ok, trades: trades.ok, signals: signals.ok,
                  cycles: cycles.ok, alerts: alerts.ok };

      safeRender(renderConnection, status.ok);
      safeRender(renderStatus, status);
      safeRender(renderLaunchd, launchd);
      safeRender(renderAccount);
      safeRender(renderPerformance);
      safeRender(renderEquity);
      renderActivity();
      safeRender(renderUpcoming);
      safeRender(renderFeed);
      safeRender(renderResearchTests);
      safeRender(renderBacktestMetrics);
      safeRender(renderMonteCarlo);
      safeRender(renderDistribution);

      $("last-updated").textContent = clockFmt.format(new Date());
    } finally {
      refreshing = false;
      document.body.classList.add("ready");
      document.body.classList.remove("is-refreshing");
      restartPollLine();
    }
  }

  $("refresh-btn").addEventListener("click", () => refreshAll(true));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshAll(); });

  setView(location.hash.replace("#", "") || "overview", true);
  setTab(ui.tab);
  applyTheme();
  applyPollChoice();
  restartPolling();
  refreshAll(true);
})();
