import pytest

import config
import llm
from conftest import ProviderError


def chat(client, session, message, headers=None, **extra):
    body = {"session_id": session, "message": message, **extra}
    return client.post("/chat", json=body, headers=headers or {})


# ---------- health ----------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


# ---------- basic chat ----------
def test_live_chat_contract(client, fake_llm):
    r = chat(client, "s-1", "What is the capital of France?")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-1"
    assert body["reply"]
    m = body["metadata"]
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert m["model"] == config.MODEL
    assert isinstance(m["latency_ms"], int)
    assert isinstance(m["input_tokens"], int) and isinstance(m["output_tokens"], int)
    assert m["key_id"] == "key_1"
    assert m["fallback_attempts"] == 0


# ---------- caching ----------
def test_same_message_in_new_session_is_cache_hit(client, fake_llm):
    first = chat(client, "s-1", "What is the capital of France?").json()
    second = chat(client, "s-2", "What is the capital of France?").json()
    m = second["metadata"]
    assert m["resolution_source"] == "LLM_CACHE"
    assert m["key_id"] is None
    assert m["fallback_attempts"] == 0
    assert second["reply"] == first["reply"]
    assert m["input_tokens"] == first["metadata"]["input_tokens"]
    assert m["output_tokens"] == first["metadata"]["output_tokens"]


def test_different_message_is_never_a_cache_hit(client, fake_llm):
    chat(client, "s-1", "What is the capital of France?")
    other = chat(client, "s-2", "What is the capital of Spain?").json()
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"


# ---------- multi-turn and sessions ----------
def test_history_is_sent_on_follow_up(client, fake_llm):
    chat(client, "s-1", "My name is Asha.")
    chat(client, "s-1", "What is my name?")
    sent = fake_llm.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "My name is Asha."


def test_sessions_are_separate(client, fake_llm):
    chat(client, "s-1", "My name is Asha.")
    chat(client, "s-2", "What is my name?")
    sent = fake_llm.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]


def test_history_endpoint(client, fake_llm):
    chat(client, "s-1", "hello")
    chat(client, "s-1", "again")
    r = client.get("/sessions/s-1/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-1"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user", "assistant"]
    assert body["messages"][0]["content"] == "hello"
    meta = body["messages"][1]["metadata"]
    assert {"resolution_source", "input_tokens", "output_tokens"} <= set(meta)


def test_unknown_session_is_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_system_prompt_override_is_used_and_kept(client, fake_llm):
    chat(client, "s-1", "hi", system_prompt="Answer like a pirate.")
    assert fake_llm.calls[-1]["messages"][0] == {"role": "system", "content": "Answer like a pirate."}
    chat(client, "s-1", "again")
    assert fake_llm.calls[-1]["messages"][0]["content"] == "Answer like a pirate."
    chat(client, "s-2", "hi")
    assert fake_llm.calls[-1]["messages"][0]["content"] == config.DEFAULT_SYSTEM_PROMPT


# ---------- failover ----------
@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_real_provider_error_fails_over_to_key_2(client, fake_llm, status):
    fake_llm.fail["test-key-1"] = ProviderError(status)
    r = chat(client, "s-1", "hello")
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2"
    assert m["fallback_attempts"] == 1


def test_all_keys_failing_returns_clean_503_and_saves_nothing(client, fake_llm):
    fake_llm.fail["test-key-1"] = ProviderError(429)
    fake_llm.fail["test-key-2"] = ProviderError(500)
    r = chat(client, "s-1", "hello")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-1/messages").status_code == 404


def test_transient_5xx_is_retried_on_the_same_key(client, fake_llm, monkeypatch):
    monkeypatch.setattr(config, "SAME_KEY_RETRIES", 1)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(llm, "_backoff", no_wait)
    fake_llm.fail_first["test-key-1"] = [ProviderError(503)]
    m = chat(client, "s-1", "hello").json()["metadata"]
    assert m["key_id"] == "key_1"
    assert m["fallback_attempts"] == 0


def test_bad_request_is_not_failed_over_and_returns_json(client, fake_llm):
    fake_llm.fail["test-key-1"] = ProviderError(400)
    r = chat(client, "s-1", "hello")
    assert r.status_code == 502
    assert "detail" in r.json()
    assert [c["key"] for c in fake_llm.calls] == ["test-key-1"]
    assert client.get("/sessions/s-1/messages").status_code == 404


# ---------- X-Simulate-Failure ----------
def test_simulate_key_1_429_uses_key_2_and_skips_cache(client, fake_llm):
    chat(client, "s-0", "hello")  # puts "hello" in the cache
    r = chat(client, "s-1", "hello", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert m["key_id"] == "key_2"
    assert m["fallback_attempts"] == 1
    last = fake_llm.calls[-1]
    assert last["key"] == "test-key-2" and last["bypass_cache"] is True
    assert "test-key-1" not in [c["key"] for c in fake_llm.calls[1:]]  # key_1 never really called


def test_simulate_two_keys(client, fake_llm):
    r = chat(client, "s-1", "hello", headers={"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert r.status_code == 503


def test_simulate_all_keys_returns_503_and_saves_nothing(client, fake_llm):
    r = chat(client, "s-1", "hello", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert fake_llm.calls == []
    assert client.get("/sessions/s-1/messages").status_code == 404


def test_simulation_is_ignored_when_switch_is_off(client, fake_llm, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_FAILURE_SIMULATION", False)
    r = chat(client, "s-1", "hello", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1"


# ---------- validation ----------
@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s", "message": ""},
        {"session_id": "s", "message": "   "},
        {"session_id": "s", "message": "x" * 4001},
        {"session_id": "", "message": "hi"},
        {"session_id": "s"},
        {"message": "hi"},
        {"session_id": "x" * 129, "message": "hi"},
    ],
)
def test_invalid_requests_return_422(client, fake_llm, payload):
    r = client.post("/chat", json=payload)
    assert r.status_code == 422
    assert "detail" in r.json()
    assert fake_llm.calls == []


def test_malformed_json_returns_422(client, fake_llm):
    r = client.post("/chat", content="{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_message_of_exactly_4000_chars_is_accepted(client, fake_llm):
    assert chat(client, "s-1", "x" * 4000).status_code == 200