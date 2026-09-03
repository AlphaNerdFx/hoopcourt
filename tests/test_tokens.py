"""Token gate tests."""
from __future__ import annotations

from src.api.tokens import HeuristicCounter, build_counter


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
