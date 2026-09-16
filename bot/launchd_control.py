"""Hardcoded launchctl control surface for the two REAL LaunchAgents that
schedule this bot -- com.rytty.quant_v7.pead_bot (the scheduled paper-trading
cycle) and com.rytty.quant_v7.pead_watchdog (its dead-man's-switch monitor).

SAFETY DESIGN: every public function's `key` parameter is checked against
the fixed CONTROLLED_JOBS tuple below, which is the ONLY place plist paths
and labels are defined. There is no parameter through which a caller --
including the dashboard's FastAPI layer -- can pass an arbitrary label or
path into a subprocess call. Every subprocess invocation goes through the
single `_run()` call site, always as an explicit argument list with the
shell flag never enabled, so there is no shell-injection surface even in
principle.

This module does not create a second execution path for the bot. It only
toggles the SAME scheduled invocation (`python3 -m bot.run_cycle`) that
already runs unattended via launchd -- bootstrap/bootout load or unload the
existing plist, they never spawn bot.run_cycle directly.

Both plists have RunAtLoad=true: bootstrap-ing an unloaded job immediately
triggers one real run, not just future scheduled fires. Callers that turn
this into a user-facing "start" action must say so explicitly.

Idempotency behavior below (returncode 5 on an already-bootstrapped job,
returncode 3 on an already-booted-out job, returncode 113 on `print` for a
job that isn't loaded) is real, documented macOS launchctl behavior,
empirically confirmed against this exact darwin build during development:
`launchctl print` on a definitely-unloaded label returns 113 with
"Could not find service ... in domain for user gui: <uid>" on stderr;
re-bootstrapping an already-loaded job is a safe no-op (verified: it does
not increment the job's `runs` counter, i.e. does not refire RunAtLoad).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

UID = os.getuid()
DOMAIN = f"gui/{UID}"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

PEAD_BOT_LABEL = "com.rytty.quant_v7.pead_bot"
PEAD_BOT_PLIST = LAUNCH_AGENTS_DIR / f"{PEAD_BOT_LABEL}.plist"
PEAD_WATCHDOG_LABEL = "com.rytty.quant_v7.pead_watchdog"
PEAD_WATCHDOG_PLIST = LAUNCH_AGENTS_DIR / f"{PEAD_WATCHDOG_LABEL}.plist"

# The ONLY jobs this module will ever touch, keyed by a short internal name.
# (key, label, plist_path)
CONTROLLED_JOBS: tuple[tuple[str, str, Path], ...] = (
    ("pead_bot", PEAD_BOT_LABEL, PEAD_BOT_PLIST),
    ("pead_watchdog", PEAD_WATCHDOG_LABEL, PEAD_WATCHDOG_PLIST),
)
_JOBS_BY_KEY = {key: (label, plist) for key, label, plist in CONTROLLED_JOBS}

_BOOTSTRAP_ALREADY_LOADED_CODE = 5
_BOOTOUT_ALREADY_UNLOADED_CODE = 3
_PRINT_NOT_LOADED_CODE = 113


def _lookup(key: str) -> tuple[str, Path]:
    if key not in _JOBS_BY_KEY:
        raise ValueError(f"unknown job key {key!r} -- must be one of {sorted(_JOBS_BY_KEY)}")
    return _JOBS_BY_KEY[key]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """The ONLY subprocess.run call site in this module. `cmd` is always a
    list built from hardcoded constants plus fixed literal launchctl
    subcommand strings -- the shell flag is never enabled, and nothing is
    string-interpolated into the argument list."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)


@dataclass(frozen=True)
class JobStatus:
    key: str
    label: str
    loaded: bool
    state: Optional[str]  # "not running" / "running" / None if not loaded
    last_exit_code: Optional[int]
    error: Optional[str]  # populated only on an unexpected probe failure


@dataclass(frozen=True)
class ControlResult:
    key: str
    action: str  # "bootstrap" | "bootout"
    ok: bool
    already_in_state: bool
    returncode: int
    stderr: str


def _parse_print_output(stdout: str) -> tuple[Optional[str], Optional[int]]:
    state = None
    last_exit_code = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("state = "):
            state = stripped[len("state = "):].strip()
        elif stripped.startswith("last exit code = "):
            try:
                last_exit_code = int(stripped[len("last exit code = "):].strip())
            except ValueError:
                pass
    return state, last_exit_code


def get_job_status(key: str) -> JobStatus:
    label, _plist = _lookup(key)
    result = _run(["launchctl", "print", f"{DOMAIN}/{label}"])
    if result.returncode == _PRINT_NOT_LOADED_CODE:
        return JobStatus(key=key, label=label, loaded=False, state=None, last_exit_code=None, error=None)
    if result.returncode == 0:
        state, last_exit_code = _parse_print_output(result.stdout)
        return JobStatus(key=key, label=label, loaded=True, state=state, last_exit_code=last_exit_code, error=None)
    # Anything else is unexpected -- fail loud, don't guess loaded/unloaded.
    return JobStatus(
        key=key, label=label, loaded=False, state=None, last_exit_code=None,
        error=f"launchctl print exited {result.returncode}: {result.stderr.strip()}",
    )


def bootstrap_job(key: str) -> ControlResult:
    label, plist = _lookup(key)
    result = _run(["launchctl", "bootstrap", DOMAIN, str(plist)])
    if result.returncode == 0:
        return ControlResult(key=key, action="bootstrap", ok=True, already_in_state=False,
                              returncode=0, stderr="")
    if result.returncode == _BOOTSTRAP_ALREADY_LOADED_CODE:
        return ControlResult(key=key, action="bootstrap", ok=True, already_in_state=True,
                              returncode=result.returncode, stderr=result.stderr.strip())
    return ControlResult(key=key, action="bootstrap", ok=False, already_in_state=False,
                          returncode=result.returncode, stderr=result.stderr.strip())


def bootout_job(key: str) -> ControlResult:
    label, _plist = _lookup(key)
    result = _run(["launchctl", "bootout", f"{DOMAIN}/{label}"])
    if result.returncode == 0:
        return ControlResult(key=key, action="bootout", ok=True, already_in_state=False,
                              returncode=0, stderr="")
    if result.returncode == _BOOTOUT_ALREADY_UNLOADED_CODE:
        return ControlResult(key=key, action="bootout", ok=True, already_in_state=True,
                              returncode=result.returncode, stderr=result.stderr.strip())
    return ControlResult(key=key, action="bootout", ok=False, already_in_state=False,
                          returncode=result.returncode, stderr=result.stderr.strip())


def get_operation_status() -> dict:
    statuses = {key: get_job_status(key) for key, _label, _plist in CONTROLLED_JOBS}
    if any(s.error for s in statuses.values()):
        operation_state = "ERROR"
    elif all(s.loaded for s in statuses.values()):
        operation_state = "RUNNING"
    elif not any(s.loaded for s in statuses.values()):
        operation_state = "STOPPED"
    else:
        operation_state = "PARTIAL"
    return {
        "operation_state": operation_state,
        "jobs": {key: _job_status_to_dict(status) for key, status in statuses.items()},
    }


def _job_status_to_dict(status: JobStatus) -> dict:
    return {
        "key": status.key, "label": status.label, "loaded": status.loaded,
        "state": status.state, "last_exit_code": status.last_exit_code, "error": status.error,
    }


def start_bot_operation() -> dict:
    """Bootstraps the watchdog FIRST, then the bot -- armed before primary
    runs. RunAtLoad=true on both plists means this immediately triggers one
    real run of each (unless already loaded, which is a verified no-op)."""
    watchdog_result = bootstrap_job("pead_watchdog")
    bot_result = bootstrap_job("pead_bot")
    return {
        "watchdog": _control_result_to_dict(watchdog_result),
        "bot": _control_result_to_dict(bot_result),
    }


def stop_bot_operation() -> dict:
    """Boots out the bot FIRST, then the watchdog -- the watchdog keeps
    watching right up until the primary job is confirmed torn down."""
    bot_result = bootout_job("pead_bot")
    watchdog_result = bootout_job("pead_watchdog")
    return {
        "bot": _control_result_to_dict(bot_result),
        "watchdog": _control_result_to_dict(watchdog_result),
    }


def _control_result_to_dict(result: ControlResult) -> dict:
    return {
        "key": result.key, "action": result.action, "ok": result.ok,
        "already_in_state": result.already_in_state,
        "returncode": result.returncode, "stderr": result.stderr,
    }
