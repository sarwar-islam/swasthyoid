"""_run_engine: the child process, its pipe, and cleanup (S2, S3). No database.

The real-process tests pin the unchanged behaviour. Everything about errors during polling,
starting and cleanup uses fake pipe ends and a fake process, so it is deterministic and starts
nothing. Synthetic data only."""
import logging
from datetime import timedelta

import pytest

from swasthyoid.capture import extraction, ocr
from swasthyoid.tests import fake_engines

INTERRUPTS = [KeyboardInterrupt, SystemExit]
LEAK = "synthetic text that must not be logged"


def run(engine=fake_engines.good, *, hard=10, heartbeat=0.2, renew=lambda: True):
    return extraction._run_engine(engine, [b"x"], "other", timedelta(seconds=hard),
                                  timedelta(seconds=heartbeat), renew)


# ---- unchanged behaviour, real child processes

def test_a_good_engine_result_is_returned():
    assert run(fake_engines.good) == fake_engines.RESULT


def test_an_engine_error_is_reported_by_type_only():
    with pytest.raises(extraction.AttemptFailed) as e:
        run(fake_engines.boom)
    assert e.value.args[0] == "RuntimeError"


def test_a_hanging_engine_hits_the_hard_timeout():
    with pytest.raises(extraction.AttemptFailed) as e:
        run(fake_engines.hang, hard=1)
    assert e.value.args[0] == "HardTimeout"


def test_a_lost_lease_stops_the_attempt():
    with pytest.raises(extraction.LeaseLost):
        run(fake_engines.hang, renew=lambda: False)


def test_a_child_that_dies_is_worker_died():
    with pytest.raises(extraction.AttemptFailed) as e:
        run(fake_engines.die)
    assert e.value.args[0] == "WorkerDied"


# ---- fakes: no process is started

class End:
    """One end of the pipe: records close(), and can raise from poll(), recv() or close()."""

    def __init__(self, poll=False, recv=None, close_error=None):
        self.closed, self._poll, self._recv, self._close_error = False, poll, recv, close_error

    def poll(self, timeout):
        if isinstance(self._poll, BaseException):
            raise self._poll
        return self._poll

    def recv(self):
        return self._recv

    def close(self):
        self.closed = True
        if self._close_error:
            raise self._close_error


class Process:
    pid = None  # never started, so the real ocr.stop_child returns at once

    def __init__(self, start_error):
        self.start_error = start_error

    def start(self):
        if self.start_error:
            raise self.start_error


def fake_spawn(monkeypatch, results, out, start_error=None):
    class Context:
        def Pipe(self, duplex=False):
            return results, out

        def Process(self, *args, **kwargs):
            return Process(start_error)

    monkeypatch.setattr(extraction.multiprocessing, "get_context", lambda name: Context())


def stop_raising(error):
    def stop_child(proc):
        raise error
    return stop_child


def good_result():
    return End(poll=True, recv=("ok", {"engine": "x"}))


def test_s2_poll_raising_broken_pipe_is_worker_died(monkeypatch):
    """The Windows case, on every platform: poll() itself raises BrokenPipeError."""
    results, out = End(poll=BrokenPipeError()), End()
    fake_spawn(monkeypatch, results, out)
    with pytest.raises(extraction.AttemptFailed) as e:
        run()
    assert e.value.args[0] == "WorkerDied" and results.closed and out.closed


def test_s3_a_child_that_fails_to_start_keeps_its_error_and_both_ends_close(monkeypatch):
    results, out = End(), End()
    fake_spawn(monkeypatch, results, out, start_error=OSError("synthetic start failure"))
    with pytest.raises(OSError, match="synthetic start failure"):
        run()
    assert results.closed and out.closed


def test_nothing_failing_returns_the_result_and_closes_both_ends(monkeypatch):
    results, out = good_result(), End()
    fake_spawn(monkeypatch, results, out)
    assert run() == {"engine": "x"} and results.closed and out.closed


# (fake pipe ends, run arguments, start error, the primary exception that must come out)
PRIMARIES = {
    "start_oserror": (dict(), {}, OSError("synthetic start failure"), OSError),
    "broken_pipe": (dict(poll=BrokenPipeError()), {}, None, extraction.AttemptFailed),
    "lease_lost": (dict(poll=False), dict(renew=lambda: False), None, extraction.LeaseLost),
    "hard_timeout": (dict(poll=False), dict(hard=0.3, heartbeat=0.05), None, extraction.AttemptFailed),
}


@pytest.mark.parametrize("name", PRIMARIES)
def test_a_failing_cleanup_never_replaces_the_primary_exception(monkeypatch, caplog, name):
    ends, kwargs, start_error, expected = PRIMARIES[name]
    results, out = End(**ends), End()
    fake_spawn(monkeypatch, results, out, start_error=start_error)
    monkeypatch.setattr(ocr, "stop_child", stop_raising(RuntimeError(LEAK)))
    with caplog.at_level(logging.WARNING, logger=extraction.log.name):
        with pytest.raises(expected) as e:
            run(**kwargs)
    assert type(e.value) is expected
    assert not isinstance(e.value.__context__, RuntimeError)  # the cleanup error is not chained onto it
    assert results.closed and out.closed
    assert "code=RuntimeError stage=cleanup" in caplog.text and LEAK not in caplog.text


def test_a_failing_stop_child_after_a_good_result_propagates(monkeypatch):
    results, out = good_result(), End()
    fake_spawn(monkeypatch, results, out)
    monkeypatch.setattr(ocr, "stop_child", stop_raising(RuntimeError(LEAK)))
    with pytest.raises(RuntimeError):
        run()
    assert results.closed and out.closed


def test_a_failing_results_close_after_a_good_result_propagates_and_out_still_closes(monkeypatch):
    results, out = End(poll=True, recv=("ok", {"engine": "x"}), close_error=OSError("close failed")), End()
    fake_spawn(monkeypatch, results, out)
    with pytest.raises(OSError, match="close failed"):
        run()
    assert results.closed and out.closed


def test_a_failing_out_close_with_a_primary_exception_keeps_it_and_closes_results(monkeypatch):
    results, out = End(), End(close_error=OSError("close failed"))
    fake_spawn(monkeypatch, results, out, start_error=ValueError("synthetic start failure"))
    with pytest.raises(ValueError, match="synthetic start failure"):
        run()
    assert results.closed and out.closed


# ---- an interrupt during cleanup is never suppressed and never skips a close

@pytest.mark.parametrize("interrupt", INTERRUPTS)
def test_an_interrupt_in_stop_child_after_a_good_result_propagates(monkeypatch, interrupt):
    results, out = good_result(), End()
    fake_spawn(monkeypatch, results, out)
    monkeypatch.setattr(ocr, "stop_child", stop_raising(interrupt()))
    with pytest.raises(interrupt):
        run()
    assert results.closed and out.closed


@pytest.mark.parametrize("interrupt", INTERRUPTS)
def test_an_interrupt_in_stop_child_with_a_primary_exception_propagates(monkeypatch, interrupt):
    results, out = End(), End()
    fake_spawn(monkeypatch, results, out, start_error=OSError("synthetic start failure"))
    monkeypatch.setattr(ocr, "stop_child", stop_raising(interrupt()))
    with pytest.raises(interrupt) as e:
        run()
    assert isinstance(e.value.__context__, OSError)  # the primary is kept as its context
    assert results.closed and out.closed


@pytest.mark.parametrize("interrupt", INTERRUPTS)
def test_an_interrupt_in_out_close_does_not_skip_results_close(monkeypatch, interrupt):
    results, out = End(), End(close_error=interrupt())
    fake_spawn(monkeypatch, results, out, start_error=OSError("synthetic start failure"))
    with pytest.raises(interrupt):
        run()
    assert results.closed and out.closed


@pytest.mark.parametrize("interrupt", INTERRUPTS)
def test_an_interrupt_outranks_an_ordinary_cleanup_error(monkeypatch, interrupt):
    results, out = good_result(), End(close_error=interrupt())
    fake_spawn(monkeypatch, results, out)
    monkeypatch.setattr(ocr, "stop_child", stop_raising(RuntimeError(LEAK)))  # first the error, then the interrupt
    with pytest.raises(interrupt):
        run()
    assert results.closed and out.closed


@pytest.mark.parametrize("interrupt", INTERRUPTS)
def test_an_interrupt_as_the_primary_is_kept_when_cleanup_also_fails(monkeypatch, caplog, interrupt):
    results, out = End(poll=interrupt()), End()
    fake_spawn(monkeypatch, results, out)
    monkeypatch.setattr(ocr, "stop_child", stop_raising(RuntimeError(LEAK)))
    with caplog.at_level(logging.WARNING, logger=extraction.log.name):
        with pytest.raises(interrupt):
            run()
    assert results.closed and out.closed
    assert "code=RuntimeError stage=cleanup" in caplog.text and LEAK not in caplog.text
