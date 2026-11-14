"""D2: sealing of extracted text (capture/extraction_crypto.py), without a database. Synthetic text only."""
import pytest
from cryptography.fernet import Fernet

from swasthyoid.api import deps
from swasthyoid.capture import extraction, extraction_crypto as crypto

FIELDS = {"prescriber_name": {"value": "SYNTH-PRIVATE-NAME", "raw": "SYNTH-PRIVATE-NAME", "confidence": 0.9},
          "advice_text": {"value": "বাংলা পরীক্ষা", "confidence": 0.8}, "medications": []}


def test_fields_round_trip_including_bengali_and_the_stored_form_holds_no_plaintext():
    sealed = crypto.seal_fields(FIELDS)
    assert set(sealed) == {"v", "enc"} and sealed["v"] == 1 and crypto.is_sealed(sealed)
    assert "SYNTH-PRIVATE-NAME" not in str(sealed) and "prescriber_name" not in str(sealed)
    assert crypto.open_fields(sealed) == FIELDS


def test_sealing_is_randomised_so_equal_fields_do_not_give_equal_tokens():
    assert crypto.seal_fields(FIELDS)["enc"] != crypto.seal_fields(FIELDS)["enc"]


def test_a_row_written_before_d2_is_read_as_it_is():
    assert crypto.open_fields({"prescriber_name": {"value": "plain"}}) == {"prescriber_name": {"value": "plain"}}
    assert crypto.open_fields({}) == {} and not crypto.is_sealed({}) and not crypto.is_sealed({"v": 1})
    assert not crypto.is_sealed({"v": 1, "enc": 5}) and not crypto.is_sealed({"v": 1, "enc": "x", "extra": 1})


def test_a_wrong_key_fails_closed_instead_of_returning_anything(monkeypatch):
    sealed, token = crypto.seal_fields(FIELDS), crypto.seal_text("SYNTH-PRIVATE-RAW")
    monkeypatch.setenv("EXTRACTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(crypto.Undecryptable) as failure:
        crypto.open_fields(sealed)
    assert "SYNTH" not in repr(failure.value) and str(failure.value) == ""
    with pytest.raises(crypto.Undecryptable):
        crypto.open_text(token)


def test_a_tampered_or_corrupt_token_fails_closed():
    sealed = crypto.seal_fields(FIELDS)
    damaged = {"v": 1, "enc": sealed["enc"][:-4] + "AAAA"}
    with pytest.raises(crypto.Undecryptable):
        crypto.open_fields(damaged)
    with pytest.raises(crypto.Undecryptable):
        crypto.open_text("not a token")
    with pytest.raises(crypto.Undecryptable):
        crypto.open_text("অ")  # not even ASCII


def test_text_round_trips_and_the_hash_is_a_plain_sha256_of_the_utf8_text():
    assert crypto.open_text(crypto.seal_text("SYNTH-PRIVATE-RAW")) == "SYNTH-PRIVATE-RAW"
    assert "SYNTH" not in crypto.seal_text("SYNTH-PRIVATE-RAW")
    assert crypto.sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert crypto.sha256("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.parametrize("value, reason", [(None, "missing"), ("", "empty"), ("   ", "empty"), ("not-a-key", "invalid"),
                                           ("a" * 44, "invalid")])
def test_the_key_must_be_present_and_a_valid_fernet_key(monkeypatch, value, reason):
    if value is None:
        monkeypatch.delenv("EXTRACTION_KEY")
    else:
        monkeypatch.setenv("EXTRACTION_KEY", value)
    with pytest.raises(crypto.KeyError_) as problem:
        crypto.check_key()
    assert problem.value.args == (reason,)
    assert "not-a-key" not in repr(problem.value)  # the reason is a fixed word, never the value


def test_nothing_is_claimed_without_the_key_and_the_api_refuses_to_start(monkeypatch):
    monkeypatch.delenv("EXTRACTION_KEY")
    with pytest.raises(RuntimeError, match="EXTRACTION_KEY is missing"):
        extraction._settings({})  # run_due and extract stop before any claim
    with pytest.raises(RuntimeError, match="EXTRACTION_KEY is missing"):
        deps.check_config()
    monkeypatch.setenv("EXTRACTION_KEY", "garbage")
    with pytest.raises(RuntimeError, match="EXTRACTION_KEY is invalid") as problem:
        deps.check_config()
    assert "garbage" not in str(problem.value)
