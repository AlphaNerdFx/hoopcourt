"""Transport retry on the Ollama backend.

Written after a full evaluation run lost 3 of 26 questions to
`RemoteDisconnected` and `URLError`. The cause was not the model: ollama had
been OOM-killed and restarted by systemd while requests were in flight, so the
connection died and the question was scored as a generation failure.

The distinction these tests hold is between a failure about the connection,
which the same payload will survive on a second attempt, and a failure about the
request, which will not.
"""
from __future__ import annotations

import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.model.generation import OLLAMA_RETRY_ATTEMPTS, OllamaGenerator  # noqa: E402

MODEL = "mistral:7b"


class _Response(io.BytesIO):
    """Minimal stand-in for the context-managed object urlopen returns."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _tags() -> _Response:
    return _Response(json.dumps({"models": [{"name": MODEL}]}).encode())


def _chat(text: str) -> _Response:
    return _Response(json.dumps({"message": {"content": text}}).encode())


@pytest.fixture
def no_sleep(monkeypatch):
    """The real backoff is 10s then 30s, which is correct in production and
    intolerable in a test."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture
def generator(monkeypatch):
    """A generator whose construction check passes without a live ollama."""
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _tags())
    return OllamaGenerator(model=MODEL)


def _chunks():
    return [{"id": 1, "document": "2023 NBA CBA", "page": 10, "text": "Salary cap.",
             "article": "VII", "section": "2", "distance": 0.1,
             "source_tier": "primary"}]


def _route():
    return {"target_year": 2024, "route_action": "direct", "trigger_keyword": None}


def test_retries_a_dropped_connection_and_succeeds(monkeypatch, generator, no_sleep):
    """The exact failure seen in the run: the server goes away mid-request and
    comes back."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http.client.RemoteDisconnected("closed")
        return _chat("Answer [2023 NBA CBA, Article VII, Section 2, p. 10]")

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    out = generator.generate("cap?", _chunks(), _route())
    assert "2023 NBA CBA" in out
    assert calls["n"] == 2


def test_retries_a_refused_connection(monkeypatch, generator, no_sleep):
    """systemd restarting the unit refuses connections for a few seconds."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        return _chat("Answer [2023 NBA CBA, Article VII, Section 2, p. 10]")

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    assert generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == 3


def test_gives_up_after_the_attempt_limit(monkeypatch, generator, no_sleep):
    """Retrying forever would hang an evaluation run instead of failing it."""
    calls = {"n": 0}

    def always_down(*a, **k):
        calls["n"] += 1
        raise http.client.RemoteDisconnected("closed")

    monkeypatch.setattr(urllib.request, "urlopen", always_down)
    with pytest.raises(RuntimeError, match="failed 3 times"):
        generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == OLLAMA_RETRY_ATTEMPTS


def test_does_not_retry_an_http_error(monkeypatch, generator, no_sleep):
    """The server answered, and answered that the request was wrong. Sending it
    twice more changes nothing and hides the real error behind a timeout."""
    calls = {"n": 0}

    def bad_request(*a, **k):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat", 400, "Bad Request", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", bad_request)
    with pytest.raises(urllib.error.HTTPError):
        generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == 1


def test_a_first_attempt_success_costs_nothing(monkeypatch, generator, no_sleep):
    calls = {"n": 0}

    def fine(*a, **k):
        calls["n"] += 1
        return _chat("Answer [2023 NBA CBA, Article VII, Section 2, p. 10]")

    monkeypatch.setattr(urllib.request, "urlopen", fine)
    assert generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == 1


def test_a_5xx_is_retried(monkeypatch, generator, no_sleep):
    """ollama answers 500 when llama-server dies or cannot allocate, including
    a transient "cudaMalloc failed: out of memory" while a previous model is
    still releasing VRAM. Seen for real against a GPU that was 86% free seconds
    later. That is a server problem, not a request problem."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                "http://127.0.0.1:11434/api/chat", 500,
                "llama-server process has terminated", {}, None)
        return _chat("Answer [2023 NBA CBA, Article VII, Section 2, p. 10]")

    monkeypatch.setattr(urllib.request, "urlopen", flaky)
    assert generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == 2


@pytest.mark.parametrize("code", [400, 404, 422])
def test_a_4xx_is_still_raised_at_once(monkeypatch, generator, no_sleep, code):
    """A malformed request fails identically three times. Retrying only hides
    the real error behind two backoffs."""
    calls = {"n": 0}

    def bad(*a, **k):
        calls["n"] += 1
        raise urllib.error.HTTPError("http://x/api/chat", code, "nope", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", bad)
    with pytest.raises(urllib.error.HTTPError):
        generator.generate("cap?", _chunks(), _route())
    assert calls["n"] == 1
