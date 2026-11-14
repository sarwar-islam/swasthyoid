"""S5 Part A: the lease is renewed once after the images are read, before the engine starts.

No database: the real _attempt() runs against a fake connection that records every statement in
one shared, ordered event list, with document reading and the engine patched. Any statement the
test does not expect fails it. Synthetic data only."""
import contextlib
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.capture import documents, extraction

IMAGE = b"SYNTHETIC-IMAGE-BYTES"
RESULT = {"engine": "fake", "raw_text": "", "fields": {}}
LOST = "ocr attempt lease lost: code=LeaseLost stage=attempt document={} attempt=2"
STATEMENTS = (("UPDATE documents SET extraction_lifetime_attempts", "begin"),
              ("UPDATE documents SET next_extraction_at", "renew"),
              ("UPDATE documents SET status = %s", "fail"),
              ("SELECT 1 FROM documents", "fence"),
              ("INSERT INTO extractions", "store"),
              ("UPDATE documents SET status = 'needs_review'", "done"))


class Result:
    def __init__(self, rowcount=1, row=(1,)):
        self.rowcount, self.row = rowcount, row

    def fetchone(self):
        return self.row


class Conn:
    """Records each statement's name in the shared event list; can fail the renewal, the fence or the budget."""

    def __init__(self, events, *, renewed=True, renew_error=None, lose_connection=False, fence_row=(1,), begin_row=(1,)):
        self.events, self.renewed, self.renew_error = events, renewed, renew_error
        self.lose_connection, self.fence_row, self.closed = lose_connection, fence_row, False
        self.begin_row = begin_row

    def transaction(self):
        return contextlib.nullcontext()

    def execute(self, sql, params=None):
        head = " ".join(sql.split())
        for prefix, name in STATEMENTS:
            if head.startswith(prefix):
                self.events.append(name)
                if name == "renew":
                    if self.renew_error:
                        self.closed = self.lose_connection  # a lost connection reports itself closed
                        raise self.renew_error
                    return Result(rowcount=1 if self.renewed else 0)
                if name == "fence":
                    return Result(row=self.fence_row)
                if name == "begin":
                    return Result(row=self.begin_row)
                return Result()
        raise AssertionError(f"unexpected statement: {head[:60]}")


class World:
    pass


@pytest.fixture
def world(monkeypatch):
    w = World()
    w.events = []
    w.job = {"id": uuid4(), "patient_id": uuid4(), "doc_type": "other", "attempt": 2, "version": 1, "token": uuid4()}
    w.options = extraction._settings({})

    def get(conn, document_id):
        w.events.append("get")
        return {"images": [{"n": 1, "content_type": "image/png"}, {"n": 2, "content_type": "image/png"}]}

    def read_image(conn, document_id, n):
        w.events.append(f"read {n}")
        return "image/png", IMAGE

    def run_engine(engine, pages, doc_type, hard_timeout, heartbeat, renew):
        w.events.append("engine")
        return RESULT

    monkeypatch.setattr(documents, "get", get)
    monkeypatch.setattr(documents, "read_image", read_image)
    monkeypatch.setattr(extraction, "_run_engine", run_engine)
    w.run = lambda conn: extraction._attempt(conn, w.job, None, None, w.options)
    return w


def logged(caplog):
    return [r for r in caplog.records if r.name == extraction.log.name]


def messages(caplog):
    return [r.getMessage() for r in logged(caplog)]


READS = ["get", "read 1", "read 2"]


def test_the_lease_is_renewed_after_all_images_are_read_and_before_the_engine(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        assert world.run(Conn(world.events)) is None
    assert world.events == READS + ["renew", "begin", "engine", "fence", "store", "done"]
    assert messages(caplog) == []


def test_a_lapsed_lease_after_reading_stops_before_the_engine_and_writes_nothing(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        assert world.run(Conn(world.events, renewed=False)) is None
    assert world.events == READS + ["renew"]  # no engine, and no fail, fence, store or done
    assert messages(caplog) == [LOST.format(world.job["id"])]


def test_the_lease_lost_warning_carries_only_the_document_and_the_attempt(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        world.run(Conn(world.events, renewed=False))
    (record,) = logged(caplog)
    assert record.args == (world.job["id"], 2)
    assert IMAGE.decode() not in caplog.text and str(world.job["patient_id"]) not in caplog.text
    assert "other" not in caplog.text and str(world.job["token"]) not in caplog.text


def test_a_lost_connection_during_the_renewal_still_raises_worker_connection_lost(world, caplog):
    error = psycopg.OperationalError("synthetic")
    with caplog.at_level("WARNING", logger=extraction.log.name):
        with pytest.raises(extraction.WorkerConnectionLost) as e:
            world.run(Conn(world.events, renew_error=error, lose_connection=True))
    assert e.value.__cause__ is error
    assert world.events == READS + ["renew"]  # no engine, and nothing written on the dead connection
    assert messages(caplog) == [
        f"ocr attempt failed: code=OperationalError stage=attempt document={world.job['id']} attempt=2"]


def test_another_database_error_at_the_renewal_is_recorded_as_a_failed_attempt(world, caplog):
    error = psycopg.errors.QueryCanceled("synthetic")  # a statement timeout: the connection stays usable
    with caplog.at_level("WARNING", logger=extraction.log.name):
        assert world.run(Conn(world.events, renew_error=error)) is None
    assert world.events == READS + ["renew", "fail"]
    assert messages(caplog) == [
        f"ocr attempt failed: code=QueryCanceled stage=attempt document={world.job['id']} attempt=2"]


def test_a_normal_attempt_logs_no_lease_warning(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        world.run(Conn(world.events))
    assert not any("lease lost" in m for m in messages(caplog))


def test_a_lease_lost_during_the_engine_stage_logs_the_same_warning(world, monkeypatch, caplog):
    def run_engine(*args):
        world.events.append("engine")
        raise extraction.LeaseLost()

    monkeypatch.setattr(extraction, "_run_engine", run_engine)
    with caplog.at_level("WARNING", logger=extraction.log.name):
        assert world.run(Conn(world.events)) is None
    assert world.events == READS + ["renew", "begin", "engine"]
    assert messages(caplog) == [LOST.format(world.job["id"])]


def test_a_lease_lost_at_the_fence_logs_the_same_warning_and_stores_nothing(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        assert world.run(Conn(world.events, fence_row=None)) is None
    assert world.events == READS + ["renew", "begin", "engine", "fence"]  # no store, no done
    assert messages(caplog) == [LOST.format(world.job["id"])]


def test_the_execution_is_counted_after_the_lease_check_and_immediately_before_the_engine(world):
    world.run(Conn(world.events))
    assert world.events.index("renew") < world.events.index("begin") < world.events.index("engine")


def test_a_lease_lost_at_the_moment_of_counting_never_starts_the_engine(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        # the guarded update matches nothing and the claim is gone (the second query, answered by fence_row)
        assert world.run(Conn(world.events, begin_row=None, fence_row=None)) is None
    assert world.events == READS + ["renew", "begin", "fence"]  # no engine, no store
    assert messages(caplog) == [LOST.format(world.job["id"])]


def test_an_exhausted_budget_never_starts_the_engine_and_closes_the_document(world, caplog):
    with caplog.at_level("WARNING", logger=extraction.log.name):
        # the guarded update matches nothing but the claim is still ours: the lifetime budget is used up
        assert world.run(Conn(world.events, begin_row=None, fence_row=(1,))) is None
    assert world.events == READS + ["renew", "begin", "fence", "fail"]  # no engine; the failure write closes it
    assert messages(caplog) == [
        f"ocr attempt failed: code=AttemptBudgetExhausted stage=attempt document={world.job['id']} attempt=2"]
