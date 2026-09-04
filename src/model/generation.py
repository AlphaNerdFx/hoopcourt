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
import os
import sqlite3
from collections.abc import Sequence
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

DEFAULT_LOCAL_REPO = "Qwen/Qwen2.5-7B-Instruct-GGUF"
DEFAULT_LOCAL_FILE = "qwen2.5-7b-instruct-q4_k_m.gguf"
DEFAULT_CLOUD_MODEL = "claude-opus-5"


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
                 base_url: str = DEFAULT_OLLAMA_URL, timeout: int = 300):
        import urllib.error
        import urllib.request

        self._urllib = urllib.request
        self._model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout

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
            "options": {"temperature": 0.0, "num_ctx": DEFAULT_N_CTX,
                        "num_predict": DEFAULT_MAX_TOKENS},
        }).encode("utf-8")
        req = self._urllib.Request(
            f"{self._base}/api/chat", data=payload,
            headers={"Content-Type": "application/json"})
        with self._urllib.urlopen(req, timeout=self._timeout) as r:
            body = json.load(r)
        return (body.get("message") or {}).get("content", "").strip()


class LocalGGUFGenerator:
    """Local llama-cpp backend. Works on CPU with no CUDA toolchain (slowly)."""

    def __init__(self, model_path: str | None = None,
                 repo_id: str = DEFAULT_LOCAL_REPO,
                 filename: str = DEFAULT_LOCAL_FILE,
                 n_ctx: int = DEFAULT_N_CTX,
                 n_gpu_layers: int = -1):
        from llama_cpp import Llama

        if model_path:
            self._llm = Llama(model_path=model_path, n_ctx=n_ctx,
                              n_gpu_layers=n_gpu_layers, verbose=False)
            self._name = os.path.basename(model_path)
        else:
            self._llm = Llama.from_pretrained(
                repo_id=repo_id, filename=filename, n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers, verbose=False,
            )
            self._name = f"{repo_id}/{filename}"

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
    """
    mode = (mode or os.environ.get("BACKEND_MODE", "local")).lower()

    if mode == "cloud":
        try:
            return AnthropicGenerator(
                os.environ.get("NBA_CLOUD_MODEL", DEFAULT_CLOUD_MODEL))
        except Exception:
            return None

    if mode == "local":
        # Ollama first: it is usually already running, needs no compiler, and
        # handles the memory pressure that stops a 7B loading in-process here.
        try:
            return OllamaGenerator(
                os.environ.get("NBA_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
                os.environ.get("NBA_OLLAMA_URL", DEFAULT_OLLAMA_URL))
        except Exception:
            pass
        try:
            return LocalGGUFGenerator(model_path=os.environ.get("NBA_GGUF_PATH"))
        except Exception:
            return None
    return None
