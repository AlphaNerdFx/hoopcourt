"""Generation backends.

Generation is the last thing wired up and the only optional part of the system:
retrieval, routing and the whole evaluation suite run without it. That ordering
is deliberate. On this project's own reference hardware the CUDA toolchain does
not currently work -- torch reports the NVIDIA driver too old for its build -- so
a design that put local inference on the critical path would have blocked
everything behind a driver upgrade.

Backends are chosen by a one-method protocol:

* ``OllamaGenerator``    -- preferred when an Ollama daemon is reachable. It is
  how most people already run local models, it needs no compiler, and it manages
  weights and memory itself. Pair it with an Apache-2.0 model such as Mistral 7B
  to keep the whole stack permissively licensed.
* ``LocalGGUFGenerator``  -- direct llama-cpp binding. Qwen2.5-7B-Instruct
  (Apache-2.0), free and offline, but it has to compile. Chosen over Llama-3.1-8B because the Llama Community License carries
  acceptable-use restrictions and a 700M-MAU clause that sit badly with this
  project's MIT licence; Llama remains supported by passing its repo id.
* ``AnthropicGenerator`` -- optional, bring-your-own-key. Never required, never
  used by the tests, never needed to install or evaluate the project.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from src.model.prompt_templates import build_messages

# 8192, not the spec's 2048. A 7-8B GQA model spends ~128 KiB/token of KV cache,
# so 8192 tokens is ~1 GiB on top of ~4.9 GiB of Q4_K_M weights -- about 6 GiB,
# which fits the 8 GB RTX 4060 in CLAUDE.md sec.3.1. At 2048 the budget is simply
# impossible: a 1,000-token question plus five retrieved legal chunks plus the
# system prompt exceeds the window before generation starts, so the prompt is
# silently truncated and the citations the design depends on are the first thing
# to fall off the end.
DEFAULT_N_CTX = 8192
DEFAULT_MAX_TOKENS = 600

# Ollama defaults. Mistral 7B is Apache-2.0, unlike Llama 3.x, so it keeps the
# default stack permissively licensed end to end.
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "mistral:7b"

# Ollama disables mmap when the host is under memory pressure, which turns a
# 4.1 GiB memory-mapped file into ~6 GiB of anonymous RSS that the kernel cannot
# evict. On a machine with 7.4 GiB usable -- a WSL2 default, which is half the
# Windows total rather than the 16 GiB in CLAUDE.md sec.3.1 -- the OOM killer
# takes llama-server, systemd restarts ollama, and every request in flight dies
# with RemoteDisconnected or a connection refused. Measured: 3 of 26 evaluation
# questions lost this way in a single run.
#
# The server comes back by itself, so the request is recoverable and only the
# transport failed. Retrying is the difference between a lost answer and a slow
# one; the per-attempt timeout already covers the model reload that follows.
OLLAMA_RETRY_ATTEMPTS = 3
OLLAMA_RETRY_BACKOFF = (10.0, 30.0)

DEFAULT_LOCAL_REPO = "Qwen/Qwen2.5-7B-Instruct-GGUF"
# A quantisation *stem*, deliberately not a filename. The constant this replaced
# was "qwen2.5-7b-instruct-q4_k_m.gguf", and no such file has ever existed in
# that repo: Qwen publishes single files only up to q3_k_m, and everything from
# q4_0 upwards is split. See resolve_gguf_files for why neither spelling of a
# split model reaches a model through Llama.from_pretrained.
DEFAULT_LOCAL_QUANT = "qwen2.5-7b-instruct-q4_k_m"
# The upstream revision, pinned. Without it hf_hub_download resolves whatever
# `main` points at when it runs, so a compromise of the Qwen repo -- or an
# innocent re-publish -- hands llama_cpp several GB of GGUF that nothing here
# ever measured, and llama_cpp loads it. A commit SHA is the only spelling that
# cannot move underneath us; a branch or a tag can be repointed in place.
# Bump it deliberately, re-running the manual gate in docs/project/TESTING.md.
DEFAULT_LOCAL_REVISION = "bb5d59e06d9551d752d08b292a50eb208b07ab1f"  # 2024-09-20
DEFAULT_CLOUD_MODEL = "claude-opus-5"

logger = logging.getLogger("hoopcourt.generation")

# `<stem>-00001-of-00002.gguf`: llama.cpp's own split naming, five digits each.
_GGUF_SHARD = re.compile(r"^(?P<stem>.+)-(?P<index>\d{5})-of-(?P<total>\d{5})\.gguf$")


class Generator(Protocol):
    def generate(self, query: str, chunks: Sequence[dict[str, Any]],
                 route: dict[str, Any], style: str = "scholar") -> str: ...
    @property
    def name(self) -> str: ...


def lookup_concept_analogy(
    conn: sqlite3.Connection, trigger_keyword: str | None
) -> dict[str, Any] | None:
    """Fetch a modern analogy for an extinct concept (casual mode only)."""
    if not trigger_keyword:
        return None
    row = conn.execute(
        "SELECT archaic_term, modern_analogy, simplified_explanation "
        "FROM historical_concept_mapper WHERE archaic_term = ?",
        (trigger_keyword.lower(),),
    ).fetchone()
    return dict(row) if row else None


class OllamaGenerator:
    """Generation through a local Ollama daemon.

    Chosen as the first backend to try because it is usually already there. It
    also sidesteps a constraint this project hit on its own reference hardware:
    a 7B model at Q4_K_M needs about 4.9 GB of weights, which does not fit
    comfortably in 5 GB of free system RAM when run in-process. Ollama memory
    maps the weights and evicts them between calls, so the same model that would
    not load directly runs fine here.
    """

    def __init__(self, model: str = DEFAULT_OLLAMA_MODEL,
                 base_url: str = DEFAULT_OLLAMA_URL, timeout: int = 900,
                 keep_alive: str = "30m"):
        import urllib.error
        import urllib.request

        self._urllib = urllib.request
        self._model = model
        self._base = base_url.rstrip("/")
        # A cold load of a 7B on this class of machine takes 140-190s before a
        # single token is produced, so a short timeout kills the request while
        # the model is still being read off disk. keep_alive holds it in memory
        # so a batch of queries pays that cost once rather than repeatedly.
        self._timeout = timeout
        self._keep_alive = keep_alive

        # Fail construction rather than the first query, so build_generator can
        # fall through to another backend.
        req = urllib.request.Request(f"{self._base}/api/tags")
        with urllib.request.urlopen(req, timeout=15) as r:
            names = {m["name"] for m in json.load(r).get("models", [])}
        if model not in names:
            raise RuntimeError(
                f"ollama has no model {model!r}; pulled: {sorted(names)}")

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def generate(self, query, chunks, route, style="scholar", analogy=None) -> str:
        messages = build_messages(query, chunks, style, analogy, route)
        payload = json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
            # Grounding matters more than fluency, so decoding is deterministic.
            "keep_alive": self._keep_alive,
            "options": {"temperature": 0.0, "num_ctx": DEFAULT_N_CTX,
                        "num_predict": DEFAULT_MAX_TOKENS},
        }).encode("utf-8")
        return self._post_with_retry(payload)

    def _post_with_retry(self, payload: bytes) -> str:
        """POST /api/chat, retrying only failures that are worth retrying.

        A transport failure means the server went away mid-request: it is about
        the connection, not the question, and the same payload will succeed once
        ollama is back. An HTTP error response is the opposite -- the server
        answered, and answered that the request was wrong -- so it is raised
        immediately rather than repeated three times.
        """
        import http.client
        import time
        import urllib.error

        transient = (http.client.RemoteDisconnected, http.client.IncompleteRead,
                     ConnectionResetError, ConnectionRefusedError)
        last: Exception | None = None
        for attempt in range(OLLAMA_RETRY_ATTEMPTS):
            req = self._urllib.Request(
                f"{self._base}/api/chat", data=payload,
                headers={"Content-Type": "application/json"})
            try:
                with self._urllib.urlopen(req, timeout=self._timeout) as r:
                    body = json.load(r)
            except urllib.error.HTTPError as exc:
                # 4xx is about the request and will fail again identically.
                # 5xx is about the server: ollama answers 500 when llama-server
                # dies or cannot allocate, including a transient
                # "cudaMalloc failed: out of memory" while a previous model is
                # still releasing VRAM. That succeeds seconds later, so it is
                # retried like any other transport failure.
                if exc.code < 500:
                    raise
                last = exc
                if attempt == OLLAMA_RETRY_ATTEMPTS - 1:
                    break
                time.sleep(OLLAMA_RETRY_BACKOFF[
                    min(attempt, len(OLLAMA_RETRY_BACKOFF) - 1)])
                continue
            except (urllib.error.URLError, *transient) as exc:
                # URLError wraps the socket error, including the refused
                # connection seen while systemd is restarting the unit.
                last = exc
                if attempt == OLLAMA_RETRY_ATTEMPTS - 1:
                    break
                time.sleep(OLLAMA_RETRY_BACKOFF[
                    min(attempt, len(OLLAMA_RETRY_BACKOFF) - 1)])
                continue
            return (body.get("message") or {}).get("content", "").strip()
        raise RuntimeError(
            f"ollama at {self._base} failed {OLLAMA_RETRY_ATTEMPTS} times; "
            f"last error {type(last).__name__}: {last}") from last


def available_quantisations(names: Iterable[str]) -> set[str]:
    """The quantisation stems a repo listing offers, shards collapsed to one.

    Only used to make a resolution failure actionable: the useful thing to print
    when a quantisation has gone away is which ones are there instead.
    """
    stems: set[str] = set()
    for name in names:
        if not name.endswith(".gguf"):
            continue
        match = _GGUF_SHARD.match(name)
        stems.add(match.group("stem") if match else name[: -len(".gguf")])
    return stems


def resolve_gguf_files(names: Iterable[str], quant: str) -> list[str]:
    """Pick the file(s) holding one quantisation out of a repo listing.

    A GGUF quantisation is not reliably one file, and this project shipped for
    its whole life assuming it was. The official Qwen2.5-7B-Instruct-GGUF repo
    publishes no `qwen2.5-7b-instruct-q4_k_m.gguf` at all; that quantisation
    exists only as `...-00001-of-00002.gguf` and `...-00002-of-00002.gguf`.

    `Llama.from_pretrained` matches with one `fnmatch` and insists on exactly
    one hit, so it accepts neither natural spelling: the unsharded name raises
    `ValueError: No file found` and the glob `...-q4_k_m*.gguf` raises
    `ValueError: Multiple files found`. Its `additional_files` argument can be
    made to work, but only by naming shard 1 as the filename and shard 2 as an
    extra, which writes the upstream split layout into constants here -- where a
    re-quantisation upstream breaks it again in exactly the same silent way.
    Resolving against the listing instead keeps the constant a quantisation,
    which is the thing a person actually chooses.

    Returned in load order. llama.cpp opens a split model from its first shard
    and finds the rest by name in the same directory, so every shard has to be
    present and the caller wants the first one's path.
    """
    listing = list(names)
    exact = f"{quant}.gguf"
    if exact in listing:
        return [exact]

    shards: dict[int, str] = {}
    totals: set[int] = set()
    for name in listing:
        match = _GGUF_SHARD.match(name)
        if match is None or match.group("stem") != quant:
            continue
        shards[int(match.group("index"))] = name
        totals.add(int(match.group("total")))

    if not shards:
        raise FileNotFoundError(
            f"no GGUF for quantisation {quant!r}; the listing offers "
            f"{sorted(available_quantisations(listing))}")
    if len(totals) > 1:
        raise FileNotFoundError(
            f"{quant!r} is split inconsistently: its shards disagree about the "
            f"total, claiming {sorted(totals)}")
    (total,) = totals
    missing = [i for i in range(1, total + 1) if i not in shards]
    if missing:
        # Downloading shard 1 alone produces a file llama.cpp opens and then
        # fails on partway through loading, which is a worse error than this.
        raise FileNotFoundError(
            f"{quant!r} is missing shard(s) {missing} of {total}; a partial "
            f"split will not load")
    return [shards[i] for i in range(1, total + 1)]


def download_gguf(repo_id: str = DEFAULT_LOCAL_REPO,
                  quant: str = DEFAULT_LOCAL_QUANT,
                  revision: str = DEFAULT_LOCAL_REVISION) -> str:
    """Fetch every file of `quant` from `repo_id`; return the first shard's path.

    Each call is a no-op once the files are in the Hugging Face cache, so this
    is a download on first use and a lookup afterwards.

    That first use is announced at warning level on purpose. `build_generator`
    is called from the API's lifespan, so on a machine with no Ollama and no
    `NBA_GGUF_PATH` this is 4.7 GB fetched while `uvicorn` appears to hang with
    nothing on stdout -- measured at 768 seconds here. Before the shard fix the
    same configuration failed in about a second, so silence used to be
    survivable and now is not.
    """
    from huggingface_hub import hf_hub_download, list_repo_files

    # Both calls take the same revision on purpose. Listing `main` and then
    # downloading a pinned commit resolves shard names against one tree and
    # fetches them from another, which is how a pin ends up looking correct
    # while still moving.
    files = resolve_gguf_files(list_repo_files(repo_id, revision=revision), quant)
    logger.warning(
        "fetching %s from %s (%d file%s) if not already cached; the first run "
        "downloads several GB and startup will block until it finishes. Set "
        "NBA_GGUF_PATH to a local .gguf to skip this.",
        quant, repo_id, len(files), "" if len(files) == 1 else "s")
    # Every shard lands in the same snapshot directory, which is exactly where
    # llama.cpp looks for the ones after the first.
    paths = [hf_hub_download(repo_id=repo_id, filename=name, revision=revision)
             for name in files]
    return paths[0]


class LocalGGUFGenerator:
    """Local llama-cpp backend. Works on CPU with no CUDA toolchain (slowly)."""

    def __init__(self, model_path: str | None = None,
                 repo_id: str = DEFAULT_LOCAL_REPO,
                 quant: str = DEFAULT_LOCAL_QUANT,
                 revision: str = DEFAULT_LOCAL_REVISION,
                 n_ctx: int = DEFAULT_N_CTX,
                 n_gpu_layers: int = -1):
        from llama_cpp import Llama

        if model_path:
            self._name = os.path.basename(model_path)
        else:
            model_path = download_gguf(repo_id, quant, revision)
            self._name = f"{repo_id}/{quant}"
        self._llm = Llama(model_path=model_path, n_ctx=n_ctx,
                          n_gpu_layers=n_gpu_layers, verbose=False)

    @property
    def name(self) -> str:
        return f"local:{self._name}"

    def count_tokens(self, text: str) -> int:
        """The model's own tokenizer -- the correct basis for the prompt gate."""
        return len(self._llm.tokenize(text.encode("utf-8")))

    def generate(self, query, chunks, route, style="scholar", analogy=None) -> str:
        messages = build_messages(query, chunks, style, analogy, route)
        # temperature=0: grounding matters more than fluency here.
        out = self._llm.create_chat_completion(
            messages=messages, max_tokens=DEFAULT_MAX_TOKENS, temperature=0.0
        )
        return out["choices"][0]["message"]["content"].strip()


class AnthropicGenerator:
    """Optional cloud backend. Requires the user's own ANTHROPIC_API_KEY."""

    def __init__(self, model: str = DEFAULT_CLOUD_MODEL, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client, self._model = client, model

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    def count_tokens(self, text: str) -> int:
        return self._client.messages.count_tokens(
            model=self._model, messages=[{"role": "user", "content": text}]
        ).input_tokens

    def generate(self, query, chunks, route, style="scholar", analogy=None) -> str:
        messages = build_messages(query, chunks, style, analogy, route)
        system, turns = messages[0]["content"], messages[1:]
        response = self._client.messages.create(
            model=self._model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system,
            messages=turns,
            thinking={"type": "adaptive"},
        )
        return "".join(
            b.text for b in response.content if getattr(b, "type", "") == "text"
        ).strip()


def build_generator(mode: str | None = None) -> Generator | None:
    """Construct the configured backend, or None if generation is unavailable.

    Returning None is a supported state: the API answers with sources and
    ``grounded`` set, and simply omits the prose answer.

    Every failure on the way there is logged, because the silence cost this
    project a defect. A backend that could not be built was indistinguishable
    from no backend being configured -- both returned None and ``/health``
    reported ``generator: null`` either way -- which is how the default model
    constant spent the whole project naming a file that does not exist upstream.
    """
    mode = (mode or os.environ.get("BACKEND_MODE", "local")).lower()

    if mode == "cloud":
        try:
            return AnthropicGenerator(
                os.environ.get("NBA_CLOUD_MODEL", DEFAULT_CLOUD_MODEL))
        except Exception as exc:
            logger.warning("cloud backend unavailable, serving retrieval only "
                           "(%s: %s)", type(exc).__name__, exc)
            return None

    if mode == "local":
        # Ollama first: it is usually already running, needs no compiler, and
        # handles the memory pressure that stops a 7B loading in-process here.
        try:
            return OllamaGenerator(
                os.environ.get("NBA_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                os.environ.get("NBA_OLLAMA_URL", DEFAULT_OLLAMA_URL))
        except Exception as exc:
            # Expected on a machine that simply has no ollama, so this is not a
            # warning: the fallback below is the documented next step.
            ollama_exc = exc
            logger.info("ollama unavailable, falling back to llama-cpp "
                        "(%s: %s)", type(exc).__name__, exc)
        try:
            return LocalGGUFGenerator(model_path=os.environ.get("NBA_GGUF_PATH"))
        except Exception as exc:
            # Both failed, so the INFO above is the missing half of the story and
            # nothing will show it: no handler is configured anywhere in src/, so
            # logging.lastResort drops everything below WARNING. Under uvicorn an
            # operator saw only "no local generation backend" and could not tell
            # whether ollama had even been tried. Carry both reasons here.
            logger.warning(
                "no local generation backend, serving retrieval only "
                "(llama-cpp %s: %s; ollama %s: %s)",
                type(exc).__name__, exc,
                type(ollama_exc).__name__, ollama_exc)
            return None

    logger.warning("BACKEND_MODE %r is not 'local' or 'cloud'; "
                   "generation disabled", mode)
    return None
