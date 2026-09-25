"""Token counting for the 1,000-token prompt gate.

BUILD_SEQUENCE.md Step 5 counts with ``tiktoken`` / ``cl100k_base``. That is
OpenAI's BPE and matches neither backend this project ships: the local model is
Qwen/Llama (a different vocabulary) and the optional cloud model is Claude
(another). The gate would be enforced against a number 10-30% off from what the
model actually sees -- in the permissive direction for some inputs, which is the
direction that matters for a limit whose stated purpose is blocking long-context
adversarial input (SECURITY.md sec.1.2).

So the counter is chosen to match whichever model will receive the prompt.
"""
from __future__ import annotations

import os
from typing import Protocol

# Legal English tokenizes densely: long words, many numerals, heavy punctuation.
# 3.2 chars/token is deliberately pessimistic so the heuristic never *under*
# counts and lets an oversized prompt through.
HEURISTIC_CHARS_PER_TOKEN = 3.2

# Same reasoning as DEFAULT_LOCAL_REVISION in src/model/generation.py: an
# unpinned from_pretrained takes whatever `main` holds at call time. The
# exposure is smaller here -- a tokenizer, not weights, and transformers will
# not execute code from it without trust_remote_code -- but it is the same hole
# one file over, and the fix is one argument.
DEFAULT_LOCAL_TOKENIZER = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_LOCAL_TOKENIZER_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    @property
    def name(self) -> str: ...


class HeuristicCounter:
    """Dependency-free fallback. Used when no tokenizer can be loaded."""

    @property
    def name(self) -> str:
        return "heuristic"

    def count(self, text: str) -> int:
        return max(1, int(len(text) / HEURISTIC_CHARS_PER_TOKEN + 0.5))


class HFTokenizerCounter:
    """Exact counts for the local GGUF model, using its HF tokenizer.

    Downloads the tokenizer only (a few MB) -- not the multi-GB weights -- so the
    gate is exact long before any generation backend is installed.
    """

    def __init__(self, model_id: str = DEFAULT_LOCAL_TOKENIZER,
                 allow_download: bool | None = None,
                 revision: str | None = None):
        from transformers import AutoTokenizer

        # The pin belongs to one repo, so it applies only when that is the repo
        # asked for. Pinning someone else's model_id to Qwen's SHA would fail
        # the load and silently downgrade the gate to the heuristic.
        if revision is None and model_id == DEFAULT_LOCAL_TOKENIZER:
            revision = DEFAULT_LOCAL_TOKENIZER_REVISION
        if allow_download is None:
            allow_download = os.environ.get(
                "NBA_ALLOW_TOKENIZER_DOWNLOAD", ""
            ).lower() in ("1", "true", "yes")
        # Default to the local cache only. Reaching for the network here blocks
        # application startup for as long as the connection takes to fail --
        # ~100s on an offline machine -- for a counter that has a correct,
        # conservative fallback. Downloading is therefore opt-in.
        self._tok = AutoTokenizer.from_pretrained(
            model_id, revision=revision, local_files_only=not allow_download
        )
        self._model_id = model_id

    @property
    def name(self) -> str:
        return f"hf:{self._model_id}"

    def count(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False))


class AnthropicCounter:
    """Exact counts for the optional cloud backend."""

    def __init__(self, model: str = "claude-opus-5", client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client, self._model = client, model

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    def count(self, text: str) -> int:
        return self._client.messages.count_tokens(
            model=self._model, messages=[{"role": "user", "content": text}]
        ).input_tokens


def build_counter(backend: str = "auto",
                  local_model_id: str = DEFAULT_LOCAL_TOKENIZER,
                  cloud_model: str = "claude-opus-5") -> TokenCounter:
    """Pick the counter matching the configured generation backend.

    ``auto`` (the default) is the heuristic. Exact counting is opt-in because
    merely *importing* transformers costs ~70s on a cold filesystem, which would
    be paid at application startup for a gate whose fallback already errs on the
    safe side. Set NBA_TOKEN_COUNTER=local (or cloud) to pay for exactness.
    """
    backend = os.environ.get("NBA_TOKEN_COUNTER", backend).lower()

    if backend == "cloud":
        try:
            return AnthropicCounter(cloud_model)
        except Exception:
            return HeuristicCounter()
    if backend == "local":
        try:
            return HFTokenizerCounter(local_model_id)
        except Exception:
            # Not cached, transformers absent, offline, or gated. The heuristic
            # over-counts, so the gate stays conservative either way.
            return HeuristicCounter()
    return HeuristicCounter()
