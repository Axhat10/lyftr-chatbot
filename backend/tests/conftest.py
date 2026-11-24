import json
import os
from types import SimpleNamespace

# These must be set BEFORE the app is imported.
os.environ["LLM_API_KEYS"] = "test-key-1,test-key-2"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["SAME_KEY_RETRIES"] = "0"
os.environ["LLM_MODEL"] = "gemini/test-model"

import pytest
from fastapi.testclient import TestClient

import db
import llm
import main


class ProviderError(Exception):
    """Pretends to be a provider error with an HTTP status."""

    def __init__(self, status):
        super().__init__(f"provider returned {status}")
        self.status_code = status


class FakeResp:
    def __init__(self, text, cached, inp, out):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]
        self.usage = SimpleNamespace(prompt_tokens=inp, completion_tokens=out)
        self._hidden_params = {"cache_hit": cached}


class FakeLLM:
    """Stands in for the provider call. Never touches the network."""

    def __init__(self):
        self.calls = []        # every call: {"key", "messages", "bypass_cache"}
        self.fail = {}         # key -> exception raised on every call
        self.fail_first = {}   # key -> list of exceptions raised once each, in order
        self.cache = {}

    async def __call__(self, key, messages, bypass_cache):
        self.calls.append({"key": key, "messages": messages, "bypass_cache": bypass_cache})
        if key in self.fail:
            raise self.fail[key]
        if self.fail_first.get(key):
            raise self.fail_first[key].pop(0)

        signature = json.dumps(messages)
        if not bypass_cache and signature in self.cache:
            text, inp, out = self.cache[signature]
            return FakeResp(text, True, inp, out), text

        text = "echo: " + messages[-1]["content"]
        inp = sum(len(m["content"].split()) for m in messages)
        out = len(text.split())
        self.cache[signature] = (text, inp, out)
        return FakeResp(text, False, inp, out), text


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "_call_key", fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c