"""Tests for bot/launchd_control.py -- the hardcoded launchctl control
surface. EVERY test here mocks subprocess.run; the real `launchctl` binary
is NEVER invoked by this test file. This is critical: this project's own
established discipline (see tests/test_bot_risk_gate.py, test_bot_execution.py
etc.) is that the test suite must never mutate real production state, and
here "real production state" includes the actually-scheduled launchd jobs
that run this bot unattended -- a test that really bootstraps/boots-out the
real com.rytty.quant_v7.pead_bot job would be far worse than the past
bot_alerts.jsonl/heartbeat.txt contamination bugs this project already hit
and fixed, since it could disable (or spuriously re-trigger, via
RunAtLoad=true) the actual live paper-trading schedule.
"""
from __future__ import annotations

import inspect
import subprocess

import pytest

import bot.launchd_control as lc


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_run(monkeypatch):
    calls: list[dict] = []
    responses: list[_FakeCompletedProcess] = []

    def _fake(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        if responses:
            return responses.pop(0)
        return _FakeCompletedProcess(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lc.subprocess, "run", _fake)
    return {"calls": calls, "responses": responses}


# -- source-guard: no shell=True anywhere in this module ---------------------

def test_module_never_uses_shell_true():
    source = inspect.getsource(lc)
    assert "shell=True" not in source
    assert "shell =True" not in source
    assert "shell= True" not in source


def test_run_never_passes_shell_true(fake_run):
    lc._run(["launchctl", "print", "gui/501/x"])
    for call in fake_run["calls"]:
        assert call["kwargs"].get("shell") is not True


# -- hardcoded label/path contract --------------------------------------------

def test_controlled_jobs_are_the_only_two_real_labels():
    keys = {key for key, _label, _plist in lc.CONTROLLED_JOBS}
    assert keys == {"pead_bot", "pead_watchdog"}
    assert lc.PEAD_BOT_LABEL == "com.rytty.quant_v7.pead_bot"
    assert lc.PEAD_WATCHDOG_LABEL == "com.rytty.quant_v7.pead_watchdog"


def test_plist_paths_point_at_real_launch_agents_dir():
    from pathlib import Path
    assert lc.PEAD_BOT_PLIST == Path.home() / "Library" / "LaunchAgents" / "com.rytty.quant_v7.pead_bot.plist"
    assert lc.PEAD_WATCHDOG_PLIST == Path.home() / "Library" / "LaunchAgents" / "com.rytty.quant_v7.pead_watchdog.plist"


@pytest.mark.parametrize("fn_name", ["get_job_status", "bootstrap_job", "bootout_job"])
def test_unknown_key_raises_value_error(fn_name):
    fn = getattr(lc, fn_name)
    with pytest.raises(ValueError):
        fn("some_other_arbitrary_job_label")


# -- get_job_status: exact argv + parsing -------------------------------------

def test_get_job_status_calls_print_with_exact_argv(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=113, stdout="", stderr="Bad request."))
    lc.get_job_status("pead_bot")
    assert fake_run["calls"][0]["cmd"] == ["launchctl", "print", f"{lc.DOMAIN}/{lc.PEAD_BOT_LABEL}"]


def test_get_job_status_not_loaded(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=113, stdout="", stderr="Could not find service"))
    status = lc.get_job_status("pead_bot")
    assert status.loaded is False
    assert status.error is None
    assert status.state is None


def test_get_job_status_loaded_parses_state_and_exit_code(fake_run):
    stdout = "\n".join([
        "gui/501/com.rytty.quant_v7.pead_bot = {",
        "\tstate = not running",
        "\truns = 2",
        "\tlast exit code = 0",
        "}",
    ])
    fake_run["responses"].append(_FakeCompletedProcess(returncode=0, stdout=stdout, stderr=""))
    status = lc.get_job_status("pead_bot")
    assert status.loaded is True
    assert status.state == "not running"
    assert status.last_exit_code == 0
    assert status.error is None


def test_get_job_status_unexpected_returncode_fails_loud_not_silent(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=99, stdout="", stderr="something weird"))
    status = lc.get_job_status("pead_bot")
    assert status.loaded is False
    assert status.error is not None
    assert "99" in status.error
    assert "something weird" in status.error


# -- bootstrap_job idempotency table ------------------------------------------

def test_bootstrap_job_success(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=0, stdout="", stderr=""))
    result = lc.bootstrap_job("pead_bot")
    assert result.ok is True
    assert result.already_in_state is False
    assert fake_run["calls"][0]["cmd"] == ["launchctl", "bootstrap", lc.DOMAIN, str(lc.PEAD_BOT_PLIST)]


def test_bootstrap_job_already_loaded_is_idempotent_ok(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=5, stdout="", stderr="Bootstrap failed: 5: Input/output error"))
    result = lc.bootstrap_job("pead_bot")
    assert result.ok is True
    assert result.already_in_state is True
    assert result.returncode == 5


def test_bootstrap_job_other_failure_is_not_ok(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=1, stdout="", stderr="permission denied"))
    result = lc.bootstrap_job("pead_bot")
    assert result.ok is False
    assert result.already_in_state is False
    assert result.stderr == "permission denied"


# -- bootout_job idempotency table ---------------------------------------------

def test_bootout_job_success(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=0, stdout="", stderr=""))
    result = lc.bootout_job("pead_bot")
    assert result.ok is True
    assert result.already_in_state is False
    assert fake_run["calls"][0]["cmd"] == ["launchctl", "bootout", f"{lc.DOMAIN}/{lc.PEAD_BOT_LABEL}"]


def test_bootout_job_already_unloaded_is_idempotent_ok(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=3, stdout="", stderr="Boot-out failed: 3: No such process"))
    result = lc.bootout_job("pead_bot")
    assert result.ok is True
    assert result.already_in_state is True
    assert result.returncode == 3


def test_bootout_job_other_failure_is_not_ok(fake_run):
    fake_run["responses"].append(_FakeCompletedProcess(returncode=1, stdout="", stderr="unexpected"))
    result = lc.bootout_job("pead_bot")
    assert result.ok is False
    assert result.stderr == "unexpected"


# -- start/stop operation ordering --------------------------------------------

def test_start_bot_operation_bootstraps_watchdog_then_bot(fake_run):
    lc.start_bot_operation()
    cmds = [c["cmd"] for c in fake_run["calls"]]
    assert cmds[0] == ["launchctl", "bootstrap", lc.DOMAIN, str(lc.PEAD_WATCHDOG_PLIST)]
    assert cmds[1] == ["launchctl", "bootstrap", lc.DOMAIN, str(lc.PEAD_BOT_PLIST)]


def test_stop_bot_operation_boots_out_bot_then_watchdog(fake_run):
    lc.stop_bot_operation()
    cmds = [c["cmd"] for c in fake_run["calls"]]
    assert cmds[0] == ["launchctl", "bootout", f"{lc.DOMAIN}/{lc.PEAD_BOT_LABEL}"]
    assert cmds[1] == ["launchctl", "bootout", f"{lc.DOMAIN}/{lc.PEAD_WATCHDOG_LABEL}"]


def test_start_bot_operation_result_shape(fake_run):
    result = lc.start_bot_operation()
    assert set(result.keys()) == {"watchdog", "bot"}
    assert result["bot"]["ok"] is True
    assert result["watchdog"]["ok"] is True


def test_stop_bot_operation_result_shape(fake_run):
    result = lc.stop_bot_operation()
    assert set(result.keys()) == {"bot", "watchdog"}


# -- get_operation_status derived state ---------------------------------------

def _loaded_print_response():
    return _FakeCompletedProcess(returncode=0, stdout="\tstate = not running\n\tlast exit code = 0\n", stderr="")


def _unloaded_print_response():
    return _FakeCompletedProcess(returncode=113, stdout="", stderr="Could not find service")


def test_operation_status_running_when_both_loaded(fake_run):
    fake_run["responses"].extend([_loaded_print_response(), _loaded_print_response()])
    status = lc.get_operation_status()
    assert status["operation_state"] == "RUNNING"
    assert status["jobs"]["pead_bot"]["loaded"] is True
    assert status["jobs"]["pead_watchdog"]["loaded"] is True


def test_operation_status_stopped_when_neither_loaded(fake_run):
    fake_run["responses"].extend([_unloaded_print_response(), _unloaded_print_response()])
    status = lc.get_operation_status()
    assert status["operation_state"] == "STOPPED"


def test_operation_status_partial_when_mismatched(fake_run):
    fake_run["responses"].extend([_loaded_print_response(), _unloaded_print_response()])
    status = lc.get_operation_status()
    assert status["operation_state"] == "PARTIAL"


def test_operation_status_error_when_probe_fails(fake_run):
    fake_run["responses"].extend([
        _FakeCompletedProcess(returncode=77, stdout="", stderr="boom"),
        _loaded_print_response(),
    ])
    status = lc.get_operation_status()
    assert status["operation_state"] == "ERROR"
    assert status["jobs"]["pead_bot"]["error"] is not None


# -- _run timeout/argument-list hygiene ----------------------------------------

def test_run_uses_capture_and_timeout(monkeypatch):
    captured = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(lc.subprocess, "run", _fake)
    lc._run(["launchctl", "print", "gui/501/x"])
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["timeout"] == 10.0
    assert isinstance(captured["cmd"], list)
