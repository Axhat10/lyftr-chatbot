import uuid
import httpx

BASE = "http://localhost:8000"
run = uuid.uuid4().hex[:6]  # makes messages unique on every run


def chat(session, message, sim=None):
    headers = {"X-Simulate-Failure": sim} if sim else {}
    r = httpx.post(
        f"{BASE}/chat",
        json={"session_id": session, "message": message},
        headers=headers,
        timeout=90,
    )
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def show(title, status, body):
    print(f"\n=== {title} ===")
    print("status:", status)
    if status == 200:
        m = body["metadata"]
        print("reply:", body["reply"][:70].replace("\n", " "))
        keys = ("resolution_source", "key_id", "fallback_attempts",
                "latency_ms", "input_tokens", "output_tokens")
        print({k: m[k] for k in keys})
    else:
        print("body:", body)


msg = f"What is the capital of France? ({run})"

show("1. live call", *chat(f"a-{run}", msg))
show("2. same message, new session (expect LLM_CACHE)", *chat(f"b-{run}", msg))
show("3. memory (reply should mention France)", *chat(f"a-{run}", "What did I just ask?"))
show("4. key_1=429 (expect key_2, fallback_attempts 1)",
     *chat(f"c-{run}", f"Name a fruit ({run})", sim="key_1=429"))
show("5. *=429 (expect 503)",
     *chat(f"d-{run}", f"Name a color ({run})", sim="*=429"))
show("6. empty message (expect 422)", *chat(f"e-{run}", "   "))

r = httpx.get(f"{BASE}/sessions/a-{run}/messages")
print("\n=== 7. history of session a ===")
print("status:", r.status_code, "| messages:", len(r.json().get("messages", [])), "(expect 4)")

r = httpx.get(f"{BASE}/sessions/d-{run}/messages")
print("\n=== 8. failed request left no history (expect 404) ===")
print("status:", r.status_code, r.json())

r = httpx.get(f"{BASE}/sessions/nope/messages")
print("\n=== 9. unknown session (expect 404) ===")
print("status:", r.status_code, r.json())