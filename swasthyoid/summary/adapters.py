"""LLM text and embedding adapter contracts for M5 (P3; FRD 8.1, 8.2; D9; owner question 15 open).

The platform integrates no model. These are the interfaces a model adapter will implement once the owner supplies a model,
its specification and an explicit approval. Plain data only:

  LLM text adapter, interface version 1: summarize(request) -> response
    request  {"interface_version": 1, "sections": [section id, ...], "rules": [text, ...],
              "events": [{"event_id", "event_type", "date", "payload"}, ...]}       (permitted events only)
    response {"model_id": text, "sections": [{"id", "sentences": [{"text", "citations": [event id],
              "facts": [{"event_id", "field", "value"}]}]}]}
  Embedding adapter, interface version 1: embed(texts: [text]) -> [[float, ...], ...] (one vector per text, same length)

One adapter per interface per deployment, named by SUMMARY_LLM_ADAPTER and SEARCH_EMBEDDING_ADAPTER; unset means none,
and the documented degraded path applies (template summary, keyword search). There is no fallback to another adapter.
Only test adapters exist, and they are refused outside test mode, when registered and when resolved (FRD 8.1 rule 8).
No document text or event value is ever logged here.
"""
import math
import os

from swasthyoid import runtime_mode

INTERFACE_VERSION = 1
SETTINGS = {"llm": "SUMMARY_LLM_ADAPTER", "embedding": "SEARCH_EMBEDDING_ADAPTER"}
_registered = {"llm": {}, "embedding": {}}

# Prompt rules sent with every LLM request (FRD 8.4). They constrain the model; the validator, not the model, decides.
PROMPT_RULES = (
    "Use only the events supplied. State nothing that is not in them.",
    "Every sentence cites the ids of the events it uses, and lists each value it states as a fact with its event and field.",
    "No diagnosis, no advice, no dosing judgement, and never call a medication active, current, stopped or completed.",
    "Write only the sections named, in the order given. The diagnoses section is never written.",
)


class AdapterRefused(Exception):
    """A test adapter outside test mode, or an adapter name that is not registered. args[0] is a code."""


def register_test_adapter(kind, name, adapter):
    if not runtime_mode.is_test_mode():
        raise AdapterRefused("test_adapter_outside_test_mode")
    _registered[kind][name] = adapter


def clear_test_adapters():
    for table in _registered.values():
        table.clear()


def resolve(kind):
    """The configured adapter of this kind, or None when none is configured. Raises AdapterRefused when the configured
    name is not available here (the caller then takes its degraded path, never another adapter)."""
    name = os.environ.get(SETTINGS[kind], "").strip()
    if not name:
        return None
    if not runtime_mode.is_test_mode():
        raise AdapterRefused("no_approved_adapter")  # only test adapters exist (owner question 15)
    if name not in _registered[kind]:
        raise AdapterRefused("adapter_not_registered")
    return _registered[kind][name]


def check_embeddings(vectors, count):
    """The embedding contract's output check: one non-empty finite vector per text, all the same length."""
    if not (isinstance(vectors, list) and len(vectors) == count and vectors):
        raise ValueError("wrong number of vectors")
    width = len(vectors[0]) if isinstance(vectors[0], list) else 0
    for v in vectors:
        if not (isinstance(v, list) and len(v) == width > 0
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)):
            raise ValueError("malformed vector")
    return vectors
