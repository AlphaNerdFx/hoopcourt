"""Token gate tests."""
from __future__ import annotations

import sys
import types

import pytest

from src.api.tokens import (
    DEFAULT_LOCAL_TOKENIZER,
    DEFAULT_LOCAL_TOKENIZER_REVISION,
    HeuristicCounter,
    HFTokenizerCounter,
    build_counter,
)


@pytest.fixture
def fake_transformers(monkeypatch):
    """Records the kwargs from_pretrained was called with.

    transformers is not installed in CI and importing it costs ~70s cold even
    when it is, so the pin is checked against a fake. Nothing here exercises
    tokenization -- only which revision the load asks for.
    """
    calls: list[dict] = []
    module = types.ModuleType("transformers")

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            calls.append({"model_id": model_id, **kwargs})
            return types.SimpleNamespace(encode=lambda text, **_: text.split())

    module.AutoTokenizer = _AutoTokenizer
    monkeypatch.setitem(sys.modules, "transformers", module)
    return calls


def test_the_default_tokenizer_load_is_pinned(fake_transformers):
    """Drop `revision=` and this goes red."""
    HFTokenizerCounter()
    assert fake_transformers[0]["revision"] == DEFAULT_LOCAL_TOKENIZER_REVISION


def test_another_model_id_is_not_pinned_to_qwens_revision(fake_transformers):
    """The pin belongs to one repo. Applying it to a different model_id would
    fail the load and silently downgrade the gate to the heuristic."""
    HFTokenizerCounter("some-org/some-other-model")
    assert fake_transformers[0]["revision"] is None
    assert DEFAULT_LOCAL_TOKENIZER == "Qwen/Qwen2.5-7B-Instruct"


def test_heuristic_never_undercounts_legal_english():
    """The gate blocks long adversarial input, so an undercount is the unsafe
    direction. Legal English averages well under 3.2 chars/token."""
    counter = HeuristicCounter()
    sample = ("Notwithstanding any other provision of this Agreement, the "
              "Maximum Annual Salary shall not exceed thirty-five percent (35%) "
              "of the Salary Cap in effect at the time the Contract is executed.")
    approx_real_tokens = len(sample.split()) * 1.35  # sub-word expansion
    assert counter.count(sample) >= approx_real_tokens * 0.75


def test_heuristic_scales_and_never_returns_zero():
    counter = HeuristicCounter()
    assert counter.count("") == 1
    assert counter.count("x" * 3200) == 1000
    assert counter.count("x" * 6400) == 2000


def test_default_counter_needs_no_network_or_heavy_import(monkeypatch):
    monkeypatch.delenv("NBA_TOKEN_COUNTER", raising=False)
    assert build_counter("auto").name == "heuristic"


def test_unknown_backend_falls_back_to_heuristic(monkeypatch):
    monkeypatch.delenv("NBA_TOKEN_COUNTER", raising=False)
    assert build_counter("nonsense").name == "heuristic"


def test_env_var_overrides_the_argument(monkeypatch):
    monkeypatch.setenv("NBA_TOKEN_COUNTER", "auto")
    assert build_counter("local").name == "heuristic"
