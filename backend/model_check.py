import os, sys, time, json, urllib.request
import litellm
from dotenv import load_dotenv

load_dotenv()
litellm.drop_params = True
key = os.environ["LLM_API_KEYS"].split(",")[0]

if len(sys.argv) == 1:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=1000"
    data = json.load(urllib.request.urlopen(url))
    skip = ("tts", "lyria", "robotics", "computer-use", "antigravity", "deep-research",
            "embedding", "image", "veo", "imagen", "live", "audio", "aqa")
    for m in data["models"]:
        n = m["name"].replace("models/", "")
        if "generateContent" in m.get("supportedGenerationMethods", []) and not any(s in n for s in skip):
            print(n)
    sys.exit()

for name in sys.argv[1:]:
    ok, total_ms = 0, 0
    for i in range(5):
        t = time.perf_counter()
        try:
            litellm.completion(model=f"gemini/{name}",
                               messages=[{"role": "user", "content": f"Say hi {i}"}],
                               api_key=key, timeout=40)
            ok += 1
            total_ms += int((time.perf_counter() - t) * 1000)
        except Exception as e:
            print("  ", name, "call", i + 1, "->", type(e).__name__)
        time.sleep(2)
    avg = total_ms // ok if ok else None
    print(f"{name}: {ok}/5 ok, avg {avg} ms")