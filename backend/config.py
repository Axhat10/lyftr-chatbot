import os
from dotenv import load_dotenv

load_dotenv()


def _bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


API_KEYS = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
MODEL = os.getenv("LLM_MODEL", "gemini/gemma-4-26b-a4b-it")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if o.strip()
]
ENABLE_FAILURE_SIMULATION = _bool(os.getenv("ENABLE_FAILURE_SIMULATION", "false"))
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant.")
CACHE_TYPE = os.getenv("CACHE_TYPE", "disk")  # "disk" or "local"
CACHE_DIR = os.getenv("CACHE_DIR", "./data/cache")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))
SAME_KEY_RETRIES = int(os.getenv("SAME_KEY_RETRIES", "1"))
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "").strip()