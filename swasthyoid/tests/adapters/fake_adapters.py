"""Test-only OCR adapters for interface version 0 (capture/ocr.py). Not OCR: they return fixed
synthetic text. Referenced as "swasthyoid.tests.adapters.fake_adapters:<factory>", which is
refused outside test mode. Each records what it did in FAKE_ADAPTER_LOG when that is set."""
import os
import socket
import subprocess
import sys
import time

SECRET = "synthetic patient text that must never be logged or stored"
IDENTITY = {"engine_id": "fake-v0", "model_version": "0.0-test", "interface_versions": [0], "test_only": True,
            "adapter_version": "fake-1"}


def note(event):
    path = os.environ.get("FAKE_ADAPTER_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(event + "\n")


class Good:
    def identity(self):
        note("identity")
        return dict(IDENTITY)

    def prepare(self):
        note("prepare")

    def page(self, page):
        return {"page_number": page["page_number"],
                "items": [{"text": f"synthetic line {page['page_number']}", "confidence": 0.9,
                           "position": [[0, 0], [10, 0], [10, 5], [0, 5]]}]}

    def read(self, document):
        note("read")
        return {"interface_version": 0, "engine_id": IDENTITY["engine_id"],
                "model_version": IDENTITY["model_version"], "pages": [self.page(p) for p in document]}

    def release(self):
        note("release")


class Empty(Good):
    def page(self, page):
        return {"page_number": page["page_number"], "items": []}


class Malformed(Good):
    def page(self, page):
        return {"page_number": page["page_number"]}  # no items


class Boom(Good):
    def read(self, document):
        raise RuntimeError(SECRET)


class Dies(Good):
    def read(self, document):
        os._exit(3)


class HangsReading(Good):
    def read(self, document):
        time.sleep(3600)


class SlowReading(Good):
    """Reads for FAKE_ADAPTER_SECONDS, recording that it started and its process id, then succeeds."""
    def read(self, document):
        note("read-start")
        note(f"child:{os.getpid()}")
        time.sleep(float(os.environ["FAKE_ADAPTER_SECONDS"]))
        return super().read(document)


class HangsIdentity(Good):
    def identity(self):
        time.sleep(3600)


class Network(Good):
    def read(self, document):
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        except OSError as e:
            note(f"network:{e}")
            raise
        return super().read(document)


class Spawns(Good):
    """Starts a grandchild, records its pid, then hangs until killed."""
    new_session = False

    def read(self, document):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                                 start_new_session=self.new_session)
        note(f"pid:{child.pid}")
        time.sleep(3600)


class SpawnsNewSession(Spawns):
    new_session = True


class WrongIdentityInResult(Good):
    def read(self, document):
        result = super().read(document)
        result["engine_id"] = "someone-else"
        return result


class NotTestOnly(Good):
    def identity(self):
        note("identity")
        return {**IDENTITY, "test_only": False}


class FlipsIdentity(Good):
    """A different identity in the OCR child than in the probe (FLIP_MARKER file present)."""
    def identity(self):
        if os.path.exists(os.environ.get("FLIP_MARKER", "-")):
            return {**IDENTITY, "model_version": "0.0-other"}
        return dict(IDENTITY)


class PatchesValidator(Good):
    """Disables the validator inside the OCR child, then returns malformed output: the worker
    must validate again."""
    def read(self, document):
        from swasthyoid.capture import ocr
        ocr.validate_result = lambda result, page_count, identity: result
        return {"interface_version": 0, "engine_id": IDENTITY["engine_id"],
                "model_version": IDENTITY["model_version"], "pages": [{"page_number": 1}]}


class ExtraChecksum(Good):
    """Finds the probe's channel and sends a forged second checksum before its identity."""
    def identity(self):
        import gc
        import json
        from multiprocessing.connection import _ConnectionBase
        for obj in gc.get_objects():
            if isinstance(obj, _ConnectionBase) and not obj.closed and obj.writable:
                obj.send_bytes(json.dumps(["checksum", "0" * 64]).encode("utf-8"))
        return dict(IDENTITY)


good, empty, malformed, boom, dies = Good, Empty, Malformed, Boom, Dies
patches_validator, extra_checksum = PatchesValidator, ExtraChecksum
hangs_reading, hangs_identity, network = HangsReading, HangsIdentity, Network
spawns, spawns_new_session = Spawns, SpawnsNewSession
slow_reading = SlowReading
wrong_identity_in_result, not_test_only, flips_identity = WrongIdentityInResult, NotTestOnly, FlipsIdentity
