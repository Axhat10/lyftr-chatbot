import uuid
import httpx

run = uuid.uuid4().hex[:6]
for header in ("key_1=429", "key_1=500"):
    r = httpx.post(
        "http://localhost:8000/chat",
        json={"session_id": f"f-{run}-{header}", "message": f"Name a fruit ({run} {header})"},
        headers={"X-Simulate-Failure": header},
        timeout=120,
    )
    body = r.json()
    print(header, "->", r.status_code, body.get("metadata", body) if r.status_code == 200 else body)