from swasthyoid.core.audit import GENESIS, chain, verify_chain
from swasthyoid.identity import health_id


def build(n):
    entries, prev = [], GENESIS
    for i in range(n):
        entries.append(chain(prev, {"action": "read", "actor_id": f"user-{i}", "result": "allow"}))
        prev = entries[-1]["entry_hash"]
    return entries


def test_chain_verifies_and_detects_tampering():
    entries = build(4)
    assert verify_chain([]) is None
    assert verify_chain(entries) is None

    edited = [dict(e) for e in entries]
    edited[2]["result"] = "deny"
    assert verify_chain(edited) == 2

    assert verify_chain(entries[:1] + entries[2:]) == 1  # deleted entry
    assert verify_chain([entries[1], entries[0]] + entries[2:]) == 0  # reordered
    assert verify_chain(entries[:2] + [{"action": "read"}]) == 2  # malformed
    assert verify_chain(entries, head="f" * 64) == 0  # wrong anchor


def test_health_id():
    ids = {health_id.generate() for _ in range(200)}
    assert len(ids) == 200
    assert all(health_id.is_valid(i) for i in ids)

    assert health_id.is_valid("SID-0000000000")
    sample = ids.pop()
    wrong = sample[:-1] + str((int(sample[-1]) + 1) % 10)
    assert not health_id.is_valid(wrong)
    for bad in ["", None, 1234567890, "SID-123", "sid-0000000000", "SID-00000000000", "SID-000000000a", "SID-0000000000\n"]:
        assert not health_id.is_valid(bad)
