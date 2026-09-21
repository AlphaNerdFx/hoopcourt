"""The llama-cpp fallback backend, and how build_generator reaches it.

Nothing in the suite touched either until v1.0.0 was being prepared, and the
cost of that was exact: `DEFAULT_LOCAL_FILE` named
`qwen2.5-7b-instruct-q4_k_m.gguf`, a file that has never existed in the repo it
names. Qwen publishes single files only up to q3_k_m; q4_k_m is split in two.
So the documented default local backend raised `ValueError: No file found`,
`build_generator` caught it, returned None, and `/health` reported
`generator: null` -- exactly what it reports on a machine with no backend
installed at all.

These tests need no model and no network. The repo listing below is the real
one, captured from the Hugging Face API, which is the fixture pattern
docs/project/TESTING.md prescribes for anything that otherwise needs an
artefact CI cannot have.
"""
from __future__ import annotations

import logging
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model import generation  # noqa: E402
from src.model.generation import (  # noqa: E402
    DEFAULT_LOCAL_QUANT,
    available_quantisations,
    build_generator,
    resolve_gguf_files,
)

# Qwen/Qwen2.5-7B-Instruct-GGUF, every .gguf it publishes, as of 2026-09-21.
QWEN_LISTING = (
    "qwen2.5-7b-instruct-fp16-00001-of-00004.gguf",
    "qwen2.5-7b-instruct-fp16-00002-of-00004.gguf",
    "qwen2.5-7b-instruct-fp16-00003-of-00004.gguf",
    "qwen2.5-7b-instruct-fp16-00004-of-00004.gguf",
    "qwen2.5-7b-instruct-q2_k.gguf",
    "qwen2.5-7b-instruct-q3_k_m.gguf",
    "qwen2.5-7b-instruct-q4_0-00001-of-00002.gguf",
    "qwen2.5-7b-instruct-q4_0-00002-of-00002.gguf",
    "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
    "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
    "qwen2.5-7b-instruct-q5_0-00001-of-00002.gguf",
    "qwen2.5-7b-instruct-q5_0-00002-of-00002.gguf",
    "qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf",
    "qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf",
    "qwen2.5-7b-instruct-q6_k-00001-of-00002.gguf",
    "qwen2.5-7b-instruct-q6_k-00002-of-00002.gguf",
    "qwen2.5-7b-instruct-q8_0-00001-of-00003.gguf",
    "qwen2.5-7b-instruct-q8_0-00002-of-00003.gguf",
    "qwen2.5-7b-instruct-q8_0-00003-of-00003.gguf",
)


# --------------------------------------------------------------------------
# The defect itself
# --------------------------------------------------------------------------

def test_the_repo_has_no_unsharded_q4_k_m():
    """The premise the old constant rested on, stated so it cannot rot quietly."""
    assert "qwen2.5-7b-instruct-q4_k_m.gguf" not in QWEN_LISTING


def test_the_default_quantisation_resolves_against_the_real_listing():
    """Restore the old `...-q4_k_m.gguf` spelling and this goes red."""
    assert resolve_gguf_files(QWEN_LISTING, DEFAULT_LOCAL_QUANT) == [
        "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
        "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
    ]


def test_shards_come_back_in_load_order_not_listing_order():
    """llama.cpp opens the split from shard 1, so order is load-bearing."""
    shuffled = (
        "qwen2.5-7b-instruct-q8_0-00003-of-00003.gguf",
        "qwen2.5-7b-instruct-q8_0-00001-of-00003.gguf",
        "qwen2.5-7b-instruct-q8_0-00002-of-00003.gguf",
    )
    assert resolve_gguf_files(shuffled, "qwen2.5-7b-instruct-q8_0") == [
        "qwen2.5-7b-instruct-q8_0-00001-of-00003.gguf",
        "qwen2.5-7b-instruct-q8_0-00002-of-00003.gguf",
        "qwen2.5-7b-instruct-q8_0-00003-of-00003.gguf",
    ]


def test_an_unsplit_quantisation_is_a_single_file():
    assert resolve_gguf_files(QWEN_LISTING, "qwen2.5-7b-instruct-q3_k_m") == [
        "qwen2.5-7b-instruct-q3_k_m.gguf"
    ]


def test_a_stem_is_not_matched_as_a_prefix_of_another():
    """`q4_0` and `q4_k_m` share a prefix; matching loosely would mix them."""
    assert resolve_gguf_files(QWEN_LISTING, "qwen2.5-7b-instruct-q4_0") == [
        "qwen2.5-7b-instruct-q4_0-00001-of-00002.gguf",
        "qwen2.5-7b-instruct-q4_0-00002-of-00002.gguf",
    ]


# --------------------------------------------------------------------------
# Failures worth distinguishing
# --------------------------------------------------------------------------

def test_a_missing_quantisation_names_the_ones_that_exist():
    with pytest.raises(FileNotFoundError) as exc:
        resolve_gguf_files(QWEN_LISTING, "qwen2.5-7b-instruct-q4_k_s")
    message = str(exc.value)
    assert "q4_k_s" in message
    # An error that only says "not found" sends the reader to a browser.
    assert "qwen2.5-7b-instruct-q4_k_m" in message


def test_an_incomplete_split_is_refused_rather_than_half_downloaded():
    partial = ("qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",)
    with pytest.raises(FileNotFoundError) as exc:
        resolve_gguf_files(partial, DEFAULT_LOCAL_QUANT)
    assert "[2]" in str(exc.value)


def test_shards_disagreeing_about_the_total_are_refused():
    inconsistent = (
        "model-q4_k_m-00001-of-00002.gguf",
        "model-q4_k_m-00002-of-00003.gguf",
    )
    with pytest.raises(FileNotFoundError) as exc:
        resolve_gguf_files(inconsistent, "model-q4_k_m")
    assert "disagree" in str(exc.value)


def test_available_quantisations_collapses_a_split_to_one_name():
    stems = available_quantisations(QWEN_LISTING)
    assert "qwen2.5-7b-instruct-q4_k_m" in stems
    assert "qwen2.5-7b-instruct-q4_k_m-00001-of-00002" not in stems
    # 19 files, 9 quantisations: fp16 in 4 parts, q2_k and q3_k_m whole, five
    # more in 2 parts each, q8_0 in 3.
    assert len(stems) == 9


def test_non_gguf_files_are_ignored():
    assert available_quantisations(("README.md", "LICENSE", "a.gguf")) == {"a"}


# --------------------------------------------------------------------------
# build_generator: which backend, in which order, and what it says when neither
# --------------------------------------------------------------------------

class _FakeLocal:
    def __init__(self, model_path=None, **kwargs):
        self.model_path = model_path

    @property
    def name(self) -> str:
        return "local:fake"


def _unreachable_ollama(*_args, **_kwargs):
    raise urllib.error.URLError("Connection refused")


@pytest.fixture
def no_gguf_env(monkeypatch):
    monkeypatch.delenv("NBA_GGUF_PATH", raising=False)
    monkeypatch.delenv("BACKEND_MODE", raising=False)


def test_ollama_is_preferred_when_it_is_reachable(monkeypatch, no_gguf_env):
    monkeypatch.setattr(generation, "OllamaGenerator",
                        lambda *a, **k: "the-ollama-one")
    monkeypatch.setattr(generation, "LocalGGUFGenerator",
                        lambda *a, **k: pytest.fail("fell back unnecessarily"))
    assert build_generator("local") == "the-ollama-one"


def test_falls_back_to_llama_cpp_when_ollama_is_unreachable(
        monkeypatch, no_gguf_env):
    monkeypatch.setattr(generation, "OllamaGenerator", _unreachable_ollama)
    monkeypatch.setattr(generation, "LocalGGUFGenerator", _FakeLocal)
    generator = build_generator("local")
    assert isinstance(generator, _FakeLocal)
    # No NBA_GGUF_PATH means "download the default", not "no model".
    assert generator.model_path is None


def test_nba_gguf_path_is_passed_through(monkeypatch, no_gguf_env):
    monkeypatch.setattr(generation, "OllamaGenerator", _unreachable_ollama)
    monkeypatch.setattr(generation, "LocalGGUFGenerator", _FakeLocal)
    monkeypatch.setenv("NBA_GGUF_PATH", "/models/mine.gguf")
    assert build_generator("local").model_path == "/models/mine.gguf"


def test_both_backends_failing_returns_none_and_says_why(
        monkeypatch, no_gguf_env, caplog):
    monkeypatch.setattr(generation, "OllamaGenerator", _unreachable_ollama)

    def no_llama_cpp(*_args, **_kwargs):
        raise ImportError("No module named 'llama_cpp'")

    monkeypatch.setattr(generation, "LocalGGUFGenerator", no_llama_cpp)
    with caplog.at_level(logging.INFO, logger="hoopcourt.generation"):
        assert build_generator("local") is None

    # The distinction that was missing: which backend failed, and why.
    assert "ollama unavailable" in caplog.text
    assert "No module named 'llama_cpp'" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_an_unrecognised_backend_mode_is_not_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="hoopcourt.generation"):
        assert build_generator("offline") is None
    assert "offline" in caplog.text
