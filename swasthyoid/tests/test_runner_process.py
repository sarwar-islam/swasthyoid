"""Step 8 slices 8.3 and 8.4: the runner as a real process (swasthyoid/workers/extract.py).

Real subprocesses against a real PostgreSQL database: signal delivery, forced termination,
hard-kill recovery, spawn and import failures, concurrent runners. Signal and process-group
behavior is measured on Linux only (skipped elsewhere). These tests need DATABASE_URL, so they
skip on a machine without PostgreSQL and run in CI. Synthetic data only.
"""
import os
import signal
import subprocess
import sys
import time
import uuid

import pytest

from swasthyoid.tests.test_extraction_integration import job, patient, prod, upload  # noqa: F401
from swasthyoid.tests.test_runner_startup import COMMAND, REPO, clean_env, run_runner

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="signal and process-group behavior is measured on Linux")
ADAPTERS = "swasthyoid.tests.adapters.fake_adapters:"


def env_for(tmp_path, adapter, seconds="600", loop=True):
    env = clean_env(DATABASE_URL=os.environ["DATABASE_URL"], APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM="1",
                    OCR_ADAPTER=ADAPTERS + adapter, FAKE_ADAPTER_LOG=str(tmp_path / "adapter.log"),
                    FAKE_ADAPTER_SECONDS=seconds)
    if loop:
        env["EXTRACTION_POLL_SECONDS"] = "0.2"
    return env


def wait_until(condition, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.1)
    return False


def text(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().rsplit(") ", 1)[1][0] != "Z"  # a zombie is dead
    except FileNotFoundError:
        return False


@pytest.fixture
def start(tmp_path):
    started = []

    def _start(env, *args):
        err = tmp_path / f"runner{len(started)}.err"
        proc = subprocess.Popen([*COMMAND, *args], cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=err.open("w"))
        started.append(proc)
        return proc, err

    yield _start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    log = tmp_path / "adapter.log"  # an orphaned OCR child must not outlive its test
    for line in text(log).splitlines():
        if line.startswith("child:") and alive(int(line[6:])):
            os.kill(int(line[6:]), signal.SIGKILL)


def child_pid(log):
    return int(next(line for line in text(log).splitlines() if line.startswith("child:"))[6:])


def row(prod, doc_id):
    with prod.connect() as conn:
        return (job(conn, doc_id)[:3],
                conn.execute("SELECT extraction_claim IS NOT NULL FROM documents WHERE id = %s", [doc_id]).fetchone()[0],
                conn.execute("SELECT count(*), count(DISTINCT version) FROM extractions WHERE document_id = %s",
                             [doc_id]).fetchone())


# ---- 8.3: the first signal

@LINUX
def test_the_first_sigterm_does_not_interrupt_the_running_attempt(prod, tmp_path, start):
    doc_id = upload(prod, patient(prod))
    proc, err = start(env_for(tmp_path, "slow_reading", seconds="4"))
    assert wait_until(lambda: "read-start" in text(tmp_path / "adapter.log")), text(err)
    proc.send_signal(signal.SIGTERM)  # the attempt is in flight
    assert proc.wait(90) == 0
    out = text(err)
    assert "code=stop_requested" in out and out.rstrip().endswith("code=graceful_shutdown")
    assert "second_signal_abort" not in out
    assert row(prod, doc_id) == (("needs_review", 1, None), False, (1, 1))  # finished, stored once, claim cleared


# ---- 8.3 and 8.4: the second signal and a hard kill leave a claim that expires and is recovered

@LINUX
@pytest.mark.parametrize("how", ["second_sigterm", "sigkill"])
def test_an_aborted_runner_leaves_a_claim_that_a_later_runner_recovers_exactly_once(prod, tmp_path, start, how):
    doc_id = upload(prod, patient(prod))
    name = f"runner-test-{uuid.uuid4().hex}"  # libpq reports it, so the runner's own backend can be found
    proc, err = start({**env_for(tmp_path, "slow_reading"), "PGAPPNAME": name})
    log = tmp_path / "adapter.log"
    assert wait_until(lambda: "child:" in text(log)), text(err)
    child = child_pid(log)

    def backends(conn):
        return conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s", [name]).fetchone()[0]

    with prod.connect() as conn:
        assert backends(conn) == 1  # the filter finds the live runner's connection (a control for the check below)
    if how == "second_sigterm":
        proc.send_signal(signal.SIGTERM)
        assert wait_until(lambda: "code=stop_requested" in text(err)), text(err)
        assert proc.poll() is None  # the first signal alone does not end a running attempt
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(60) == 3 and "code=second_signal_abort" in text(err)
    else:
        proc.kill()
        assert proc.wait(60) == -signal.SIGKILL
    assert wait_until(lambda: not alive(child)), "the OCR child outlived the runner"  # parent-gone watchdog
    with prod.connect() as conn:  # the runner's connection is closed and nothing is left open in the database
        assert wait_until(lambda: backends(conn) == 0), "the runner's database connection outlived it"
        assert wait_until(lambda: conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND state LIKE 'idle in transaction%'").fetchone()[0] == 0)
    assert row(prod, doc_id) == (("extracting", 1, None), True, (0, 0))  # claimed, nothing stored

    live = run_runner("--once", env=env_for(tmp_path, "good", loop=False))  # the lease is still running
    assert live.returncode == 0 and "code=cycle_done attempts=0 due=0 in_flight=1" in live.stderr, live.stderr
    assert row(prod, doc_id) == (("extracting", 1, None), True, (0, 0))  # the live claim is respected

    with prod.connect() as conn:
        conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() - interval '1 second' WHERE id = %s",
                     [doc_id])  # the lease runs out
    recovered = run_runner("--once", env=env_for(tmp_path, "good", loop=False))
    assert recovered.returncode == 0 and "code=cycle_done attempts=1 due=0 in_flight=0" in recovered.stderr
    assert row(prod, doc_id) == (("needs_review", 2, None), False, (1, 1))  # exactly one result for the version


# ---- 8.4: spawn and import failures, concurrent runners

@LINUX
def test_an_ocr_child_that_dies_is_recorded_as_workerdied_promptly(prod, tmp_path):
    doc_id = upload(prod, patient(prod))
    started = time.monotonic()
    done = run_runner("--once", env=env_for(tmp_path, "dies", loop=False))
    elapsed = time.monotonic() - started
    assert done.returncode == 0 and "code=cycle_done attempts=1" in done.stderr, done.stderr
    assert row(prod, doc_id) == (("extracting", 1, "WorkerDied"), False, (0, 0))  # counted, retried after the backoff
    assert elapsed < 20, f"WorkerDied took {elapsed:.1f}s"  # AC5: not the whole hard timeout


def test_an_adapter_that_cannot_be_imported_claims_nothing(prod, tmp_path):
    doc_id = upload(prod, patient(prod))
    env = env_for(tmp_path, "good", loop=False)
    env["OCR_ADAPTER"] = "swasthyoid.tests.adapters.no_such_module:good"
    done = run_runner("--once", env=env)
    assert done.returncode == 0 and "code=cycle_done attempts=0 due=1" in done.stderr, done.stderr
    assert row(prod, doc_id) == (("uploaded", 0, None), False, (0, 0))


def test_two_runners_at_once_extract_every_document_exactly_once(prod, tmp_path, start):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(6)]
    procs = [start(env_for(tmp_path, "good", loop=False), "--once") for _ in range(2)]  # loop mode would need a poll interval
    for proc, err in procs:
        assert proc.wait(180) == 0, text(err)
    for doc_id in ids:
        assert row(prod, doc_id) == (("needs_review", 1, None), False, (1, 1))
    attempts = sum(int(line.split("attempts=")[1].split()[0]) for _, err in procs
                   for line in text(err).splitlines() if "code=cycle_done" in line)
    assert attempts == 6  # no document was attempted twice
