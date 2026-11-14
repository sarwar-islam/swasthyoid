"""Process-tree termination for the OCR child (worker reliability, docs/DECISIONS.md "Process trees").
No database. A fake /proc table tests the walk and the kill order on any system; real processes test that nothing
the engine started survives a timeout, a normal exit, a lost lease or a repeat. Tests that need Linux process
groups, sessions or /proc are skipped elsewhere, and say so: Windows ends the tree with taskkill. Synthetic only."""
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

from swasthyoid.capture import extraction, ocr
from swasthyoid.tests import fake_trees

LINUX = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux sessions, groups and /proc")


# ---- the walk and the kill order, on a fake /proc table (any system)

def add_process(root, pid, name, parent):
    folder = root / str(pid)
    folder.mkdir()
    (folder / "stat").write_bytes(f"{pid} ({name}) S {parent} 1 1 0 -1 0".encode())


def fake_proc(tmp_path, table):
    """table: {pid: (name, parent pid)} written as /proc/<pid>/stat files."""
    for pid, (name, parent) in table.items():
        add_process(tmp_path, pid, name, parent)
    (tmp_path / "self").mkdir()  # not a number: ignored
    return str(tmp_path)


def test_descendants_follow_parent_ids_through_any_depth_and_ignore_unrelated_processes(tmp_path):
    root = fake_proc(tmp_path, {10: ("worker", 1), 11: ("child", 10), 12: ("grand (x) child", 11), 13: ("other", 1),
                                14: ("grand2", 11), 15: ("great", 12), 16: ("unrelated", 13)})
    assert sorted(ocr.descendants(10, root)) == [11, 12, 14, 15]
    assert ocr.descendants(13, root) == [16] and ocr.descendants(99, root) == []


def test_a_process_name_with_spaces_and_brackets_does_not_break_the_parent_id(tmp_path):
    root = fake_proc(tmp_path, {10: ("a)b (c d", 1), 11: ("x", 10)})
    assert ocr.descendants(10, root) == [11]


def test_a_missing_or_unreadable_proc_gives_no_descendants(tmp_path):
    assert ocr.descendants(10, str(tmp_path / "nowhere")) == []
    (tmp_path / "20").mkdir()  # no stat file: the process exited while the table was read
    (tmp_path / "21").mkdir()
    (tmp_path / "21" / "stat").write_bytes(b"garbage")
    assert ocr.descendants(1, str(tmp_path)) == []


class Recorder:
    def __init__(self, gone=()):
        self.calls, self.gone = [], set(gone)

    def __call__(self, pid, sig):
        self.calls.append((pid, sig))
        if pid in self.gone:
            raise ProcessLookupError


def test_every_descendant_is_stopped_then_killed_including_one_in_another_session(tmp_path):
    root = fake_proc(tmp_path, {10: ("w", 1), 11: ("c", 10), 12: ("g", 11), 13: ("daemon", 1)})
    send = Recorder()
    ocr.kill_descendants(10, freeze_root=True, proc_root=root, send=send)
    stops = [p for p, s in send.calls if s == ocr._STOP]
    kills = [p for p, s in send.calls if s == ocr._KILL]
    assert stops[0] == 10 and sorted(stops[1:]) == [11, 12]  # the root is frozen first, then what was found
    assert set(kills) == {11, 12} and 13 not in stops + kills  # the unrelated process is never touched
    last_stop = max(i for i, c in enumerate(send.calls) if c[1] == ocr._STOP)
    first_kill = min(i for i, c in enumerate(send.calls) if c[1] == ocr._KILL)
    assert last_stop < first_kill  # everything is frozen before anything is killed


def test_a_process_that_exits_first_is_skipped_and_nothing_is_raised(tmp_path):
    root = fake_proc(tmp_path, {10: ("w", 1), 11: ("c", 10), 12: ("g", 11)})
    ocr.kill_descendants(10, freeze_root=True, proc_root=root, send=Recorder(gone={10, 11, 12}))  # all already gone


def test_a_refused_signal_is_logged_by_code_only_and_does_not_stop_the_rest(tmp_path, caplog):
    root = fake_proc(tmp_path, {10: ("secret-name", 1), 11: ("c", 10), 12: ("c", 10)})
    calls = []

    def send(pid, sig):
        calls.append((pid, sig))
        if pid == 11:
            raise PermissionError("synthetic secret text")

    with caplog.at_level("WARNING"):
        ocr.kill_descendants(10, proc_root=root, send=send)
    assert (12, ocr._KILL) in calls
    assert "code=kill_permission" in caplog.text and "synthetic secret" not in caplog.text and "secret-name" not in caplog.text


def test_a_child_started_while_it_works_is_found_by_the_next_round(tmp_path, monkeypatch):
    root = fake_proc(tmp_path, {10: ("w", 1), 11: ("c", 10)})
    send, original, sizes = Recorder(), ocr.descendants, []

    def growing(pid, proc_root="/proc"):
        found = original(pid, proc_root)
        sizes.append(len(found))
        if len(sizes) == 1:  # a new grandchild appears right after the first scan
            add_process(tmp_path, 12, "late", 11)
        return found

    monkeypatch.setattr(ocr, "descendants", growing)
    ocr.kill_descendants(10, proc_root=root, send=send)
    assert (12, ocr._KILL) in send.calls and sizes[:2] == [1, 2]


@pytest.mark.parametrize("bad", [None, 0, 1, -5, "12", 3.5])
def test_kill_descendants_ignores_a_pid_that_is_not_a_real_child_id(tmp_path, bad):
    send = Recorder()
    ocr.kill_descendants(bad, freeze_root=True, proc_root=str(tmp_path), send=send)
    assert send.calls == []  # never signals pid 0, 1, a negative number (a whole group) or a non-number


# ---- real processes

def alive(pid):
    """Whether the process still runs (a zombie counts as gone). Never sends a signal."""
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out.split()
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as f:
            text = f.read()
    except OSError:
        return False
    return "\nState:\tZ" not in text


def wait_gone(pids, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not any(alive(p) for p in pids):
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def record(tmp_path, monkeypatch):
    path = tmp_path / "pids"
    monkeypatch.setenv("FAKE_PID_FILE", str(path))
    seen = []

    def pids(wanted=1, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = [int(x) for x in path.read_text().split()] if path.exists() else []
            if len(found) >= wanted:
                seen[:] = found
                return found
            time.sleep(0.2)
        pytest.fail("the engine never recorded its process")

    yield pids
    for pid in seen:  # a failing test must not leave processes behind
        if alive(pid):
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, 9)


def run(engine, hard=3):
    return extraction._run_engine(engine, [b"x"], "other", timedelta(seconds=hard), timedelta(seconds=0.2), lambda: True)


def test_a_timeout_ends_the_engines_child_process_too(record):
    with pytest.raises(extraction.AttemptFailed) as e:
        run(fake_trees.spawn_and_hang)
    assert e.value.args[0] == "HardTimeout"
    assert wait_gone(record())


def test_a_lost_lease_ends_the_engines_child_process_too(record):
    def lease_lost_once_the_engine_has_started():  # not before: the child needs time to start and record its process
        return not os.path.exists(os.environ["FAKE_PID_FILE"])

    with pytest.raises(extraction.LeaseLost):
        extraction._run_engine(fake_trees.spawn_and_hang, [b"x"], "other", timedelta(seconds=60),
                               timedelta(seconds=0.3), lease_lost_once_the_engine_has_started)
    assert wait_gone(record())


def test_repeated_timeouts_leave_no_process_behind(record):
    for _ in range(3):
        with pytest.raises(extraction.AttemptFailed):
            run(fake_trees.spawn_and_hang, hard=2)
    assert wait_gone(record(3))


def test_stopping_a_child_that_has_already_exited_is_harmless_and_reaps_it():
    child = multiprocessing.get_context("spawn").Process(target=sys.exit, args=(0,))
    child.start()
    child.join(60)  # exited and reaped: the race where the process is gone before the kill
    ocr.stop_child(child)
    ocr.stop_child(child)  # and a second time
    assert child.exitcode == 0 and not child.is_alive()


@LINUX
def test_a_descendant_in_its_own_session_is_ended_by_the_timeout(record):
    with pytest.raises(extraction.AttemptFailed) as e:
        run(fake_trees.spawn_new_session_and_hang)
    assert e.value.args[0] == "HardTimeout" and wait_gone(record())


@LINUX
def test_an_engine_that_returns_leaves_no_descendant_even_in_another_session(record):
    assert run(fake_trees.spawn_new_session_and_return) == fake_trees.RESULT  # the parent exits normally
    assert wait_gone(record())


@LINUX
def test_an_orphaned_daemon_started_by_the_engine_is_ended_by_the_timeout(record):
    with pytest.raises(extraction.AttemptFailed):
        run(fake_trees.daemon_and_hang)
    assert wait_gone(record())  # re-parented to the OCR child (its subreaper), found and killed


def test_cancellation_ends_the_engines_child_process_too(record):
    def cancelled_once_started():  # an interrupt (Ctrl-C, a shutdown handler) arriving while the engine runs
        if os.path.exists(os.environ["FAKE_PID_FILE"]):
            raise KeyboardInterrupt
        return True

    with pytest.raises(KeyboardInterrupt):
        extraction._run_engine(fake_trees.spawn_and_hang, [b"x"], "other", timedelta(seconds=60),
                               timedelta(seconds=0.2), cancelled_once_started)
    assert wait_gone(record())


REPO = Path(__file__).resolve().parents[2]
WORKER = """
from datetime import timedelta
from swasthyoid.capture import extraction
from swasthyoid.tests import fake_trees
extraction._run_engine(fake_trees.spawn_new_session_and_hang, [b"x"], "other", timedelta(minutes=5),
                       timedelta(seconds=1), lambda: True)
"""


@LINUX
@pytest.mark.parametrize("how", ["SIGKILL", "SIGTERM"])
def test_a_worker_that_is_killed_leaves_no_descendant_even_in_another_session(record, how):
    """The worker dies without cleanup (SIGKILL, or SIGTERM with no handler): the OCR child's watchdog sees the
    parent gone and ends its whole tree, including a descendant that started a session of its own."""
    worker = subprocess.Popen([sys.executable, "-c", WORKER], cwd=REPO)
    try:
        pids = record()
    finally:
        worker.send_signal(getattr(signal, how))
        worker.wait(30)
    assert wait_gone(pids)


@LINUX
def test_the_ocr_child_leads_its_own_process_group_and_adopts_orphans():
    result = run(fake_trees.report_process_state)
    group, pid, parent_group, subreaper = result["raw_text"].split()
    assert group == pid and group != parent_group  # its own group, not the worker's
    assert subreaper == "1"  # orphaned descendants come to it, not to init
