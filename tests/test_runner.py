import os
import subprocess
import sys
import threading
import time

import pytest


def test_process_records_real_stdout_stderr_and_failure_exit(tmp_path):
    from gamebuild.runner import run_process
    log = tmp_path / "build.log"
    result = run_process([sys.executable, "-c", "import sys;print('hello');print('error', file=sys.stderr);sys.exit(7)"], tmp_path, log, 5)
    assert result["exit_code"] == 7
    assert result["timed_out"] is False
    assert result["cancelled"] is False
    assert "hello" in log.read_text()
    assert "error" in log.read_text()


def test_unbounded_stdout_is_drained_but_log_is_bounded(tmp_path):
    from gamebuild.runner import run_process
    log = tmp_path / "build.log"
    result = run_process([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*5000000)"], tmp_path, log, 5)
    assert result["exit_code"] == 0
    assert log.stat().st_size <= 1024 * 1024
    assert result["log_truncated"] is True


def test_timeout_terminates_real_process(tmp_path):
    from gamebuild.runner import run_process
    result = run_process([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, tmp_path / "timeout.log", .2)
    assert result["timed_out"] is True
    assert result["exit_code"] != 0
    assert result["duration"] < 5


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_entire_process_tree_stops_producing_heartbeat(tmp_path, stop):
    from gamebuild.runner import run_process
    # A surviving grandchild would continue writing this file after runner returns.
    beat = tmp_path / "heartbeat"
    grandchild = "import time;from pathlib import Path;p=Path(" + repr(str(beat)) + ");\nwhile True:\n p.write_text(str(time.time()));time.sleep(.03)"
    child = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(grandchild) + "]);time.sleep(30)"
    parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(child) + "]);time.sleep(30)"
    cancel = threading.Event()
    def signal_when_started():
        deadline = time.monotonic() + 5
        while not beat.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        if stop == "cancel":
            cancel.set()
    thread = threading.Thread(target=signal_when_started)
    thread.start()
    result = run_process([sys.executable, "-c", parent], tmp_path, tmp_path / "tree.log", 1.5 if stop == "timeout" else 7, cancel)
    thread.join()
    assert beat.exists(), "descendant never reached test heartbeat"
    before = beat.read_text()
    time.sleep(.15)
    assert beat.read_text() == before
    assert result["cancelled" if stop == "cancel" else "timed_out"] is True


def test_cancelled_request_never_launches_command(tmp_path):
    from gamebuild.runner import run_process
    event = threading.Event()
    event.set()
    result = run_process([sys.executable, "-c", "open('launched','w').write('bad')"], tmp_path, tmp_path / "log", 5, event)
    assert result["cancelled"] is True
    assert not (tmp_path / "launched").exists()


def test_parent_exit_reaps_background_descendant_and_closes_log_pipe(tmp_path):
    from gamebuild.runner import run_process
    code = "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print('parent complete')"
    result = run_process([sys.executable, "-c", code], tmp_path, tmp_path / "background.log", 5)
    assert result["exit_code"] == 0
    assert result["duration"] < 3
    assert "parent complete" in (tmp_path / "background.log").read_text()
