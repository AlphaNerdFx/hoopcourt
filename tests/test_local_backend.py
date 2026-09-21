"""The llama-cpp fallback backend, and how build_generator reaches it.

Nothing in the suite touched either until v1.0.0 was being prepared, and the
cost of that was exact: `DEFAULT_LOCAL_FILE` named
`qwen2.5-7b-instruct-q4_k_m.gguf`, a file that has never existed in the repo it
names. Qwen publishes single files only up to q3_k_m; q4_k_m is split in two.
So the documented default local backend raised `ValueError: No file found`,
`build_generator` caught it, returned None, and `/health` reported
`generator: null` -- exactly what it reports on a machine with no backend
installed at all.

These tests need no model and, with one opt-in exception, no network. The repo
listing below is the real one, captured from the Hugging Face API, and the
compiled binding is faked outright -- the fixture pattern
docs/project/TESTING.md prescribes for anything that otherwise needs an artefact
CI cannot have. The exception is marked `network` and skipped unless
`NBA_NETWORK_TESTS` is set, because a snapshot cannot notice upstream moving.
"""
from __future__ import annotations

import logging
import os
import sys
import types
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model import generation  # noqa: E402
from src.model.generation import (  # noqa: E402
    DEFAULT_LOCAL_QUANT,
    DEFAULT_LOCAL_REPO,
    DEFAULT_N_CTX,
    LocalGGUFGenerator,
    available_quantisations,
    build_generator,
    download_gguf,
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

@pytest.mark.network
@pytest.mark.skipif(not os.environ.get("NBA_NETWORK_TESTS"),
                    reason="set NBA_NETWORK_TESTS=1 to query Hugging Face")
def test_the_default_quantisation_still_exists_upstream():
    """The only check here that can notice Qwen re-quantising.

    Everything else in this file runs against QWEN_LISTING, which is a snapshot.
    A snapshot pins our logic and is structurally blind to the upstream change
    that caused the defect in the first place, so that check has to reach the
    network. Opt-in, because the rest of the suite is offline by design.
    """
    from huggingface_hub import list_repo_files

    files = resolve_gguf_files(list_repo_files(DEFAULT_LOCAL_REPO),
                               DEFAULT_LOCAL_QUANT)
    assert files, f"{DEFAULT_LOCAL_QUANT} no longer resolves in {DEFAULT_LOCAL_REPO}"
    assert all(name.endswith(".gguf") for name in files)


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


# --------------------------------------------------------------------------
# download_gguf and LocalGGUFGenerator, with the hub and the binding faked
#
# The build_generator tests above all monkeypatch LocalGGUFGenerator away, so
# without this section the download path and the constructor would have no
# coverage at all -- which is how the original defect survived.
# --------------------------------------------------------------------------

@pytest.fixture
def fake_hub(monkeypatch):
    """Stands in for huggingface_hub. Returns the list of files asked for."""
    requested: list[str] = []
    module = types.ModuleType("huggingface_hub")
    module.list_repo_files = lambda repo_id: list(QWEN_LISTING)

    def _hf_hub_download(repo_id, filename):
        requested.append(filename)
        return f"/cache/{repo_id.replace('/', '--')}/snapshots/abc123/{filename}"

    module.hf_hub_download = _hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return requested


@pytest.fixture
def fake_llama_cpp(monkeypatch):
    """Stands in for the compiled binding, which CI does not have at all."""
    loaded: dict[str, object] = {}
    module = types.ModuleType("llama_cpp")

    class _Llama:
        def __init__(self, **kwargs):
            loaded.update(kwargs)

    module.Llama = _Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    return loaded


def test_download_gguf_fetches_every_shard_and_returns_the_first(fake_hub):
    path = download_gguf(DEFAULT_LOCAL_REPO, DEFAULT_LOCAL_QUANT)
    # Both, not just the one llama.cpp is handed: it opens the split from shard
    # 1 and finds the rest by name in the same directory, so a missing shard 2
    # fails partway through loading rather than at download time.
    assert fake_hub == [
        "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
        "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
    ]
    assert path.endswith("qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf")


def test_download_gguf_fetches_one_file_for_an_unsplit_quantisation(fake_hub):
    path = download_gguf(DEFAULT_LOCAL_REPO, "qwen2.5-7b-instruct-q3_k_m")
    assert fake_hub == ["qwen2.5-7b-instruct-q3_k_m.gguf"]
    assert path.endswith("qwen2.5-7b-instruct-q3_k_m.gguf")


def test_download_gguf_announces_itself_before_blocking_startup(fake_hub, caplog):
    with caplog.at_level(logging.WARNING, logger="hoopcourt.generation"):
        download_gguf(DEFAULT_LOCAL_REPO, DEFAULT_LOCAL_QUANT)
    # build_generator runs inside the API lifespan, so this is several GB
    # fetched while uvicorn appears to hang. It must not be silent, and it must
    # name the way out.
    assert "NBA_GGUF_PATH" in caplog.text


def test_a_resolution_failure_stops_before_any_download(fake_hub):
    with pytest.raises(FileNotFoundError):
        download_gguf(DEFAULT_LOCAL_REPO, "qwen2.5-7b-instruct-q4_k_s")
    assert fake_hub == []


def test_the_default_generator_loads_the_first_shard(fake_hub, fake_llama_cpp):
    generator = LocalGGUFGenerator()
    assert generator.name == (
        "local:Qwen/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m")
    assert fake_llama_cpp["model_path"].endswith(
        "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf")
    assert fake_llama_cpp["n_ctx"] == DEFAULT_N_CTX


def test_an_explicit_model_path_never_reaches_the_hub(fake_llama_cpp, monkeypatch):
    """NBA_GGUF_PATH means "use this file", not "check upstream first"."""
    def _no_hub(*_args, **_kwargs):
        pytest.fail("a local model path must not trigger a repo lookup")

    module = types.ModuleType("huggingface_hub")
    module.list_repo_files = _no_hub
    module.hf_hub_download = _no_hub
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)

    generator = LocalGGUFGenerator(model_path="/models/mine.gguf")
    assert generator.name == "local:mine.gguf"
    assert fake_llama_cpp["model_path"] == "/models/mine.gguf"
