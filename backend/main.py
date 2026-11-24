import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

import config
import db
import llm

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="LLM Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] = None


@app.exception_handler(Exception)
async def unhandled_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
async def health():
    ok = db.db_ok() and len(config.API_KEYS) > 0
    body = {
        "status": "ok" if ok else "degraded",
        "keys_configured": len(config.API_KEYS),
        "cache_enabled": llm.litellm.cache is not None,
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)


@app.post("/chat")
async def chat(
    req: ChatRequest,
    x_simulate_failure: Optional[str] = Header(default=None),
):
    start = time.perf_counter()

    simulation = {}
    if config.ENABLE_FAILURE_SIMULATION:
        simulation = llm.parse_simulation(x_simulate_failure)

    stored_prompt = db.get_session_system_prompt(req.session_id)
    system_prompt = req.system_prompt or stored_prompt or config.DEFAULT_SYSTEM_PROMPT

    messages = (
        [{"role": "system", "content": system_prompt}]
        + db.get_history(req.session_id)
        + [{"role": "user", "content": req.message}]
    )

    try:
        result = await llm.complete(messages, simulation)
    except llm.AllProvidersUnavailable:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})
    except llm.UpstreamError:
        return JSONResponse(status_code=502, content={"detail": "upstream provider error"})

    reply = result.pop("reply")
    result["latency_ms"] = int((time.perf_counter() - start) * 1000)

    db.save_exchange(req.session_id, req.message, reply, result, req.system_prompt or None)

    return {"session_id": req.session_id, "reply": reply, "metadata": result}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": db.get_messages(session_id)}