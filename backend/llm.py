import asyncio
import logging
import os

import litellm
from litellm.caching.caching import Cache

import config

log = logging.getLogger("llm")

litellm.drop_params = True

litellm.cache = Cache(type="local")  # in-memory cache


class AllProvidersUnavailable(Exception):
    """Every key in the pool failed."""


class UpstreamError(Exception):
    """A non-retryable error, e.g. a bad request that another key cannot fix."""


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated {status}")
        self.status_code = status


class EmptyReply(Exception):
    status_code = 502


def parse_simulation(header) -> dict:
    """'key_1=429,key_2=500' -> {'key_1': 429, 'key_2': 500}. '*' means every key."""
    result = {}
    if not header:
        return result
    for part in header.split(","):
        if "=" not in part:
            continue
        name, status = (s.strip() for s in part.split("=", 1))
        if status.isdigit() and int(status) in (429, 500, 502, 503):
            result[name] = int(status)
    return result


def _status(exc):
    return getattr(exc, "status_code", None)


def should_failover(exc) -> bool:
    if isinstance(exc, (litellm.APIConnectionError, litellm.Timeout)):
        return True
    status = _status(exc)
    if status is None:
        return False
    return status in (401, 403, 408, 429) or status >= 500


async def _call_key(key: str, messages: list, bypass_cache: bool):
    extra = {"cache": {"no-cache": True}} if bypass_cache else {}
    if config.REASONING_EFFORT:
        extra["reasoning_effort"] = config.REASONING_EFFORT
    resp = await litellm.acompletion(
        model=config.MODEL,
        messages=messages,
        api_key=key,
        timeout=config.REQUEST_TIMEOUT,
        **extra,
    )
    text = resp.choices[0].message.content
    if not text or not text.strip():
        raise EmptyReply()
    return resp, text


async def complete(messages: list, simulation: dict) -> dict:
    failed = 0
    # A simulated request must reach the failover logic, so skip cache reads.
    bypass_cache = bool(simulation)

    for index, key in enumerate(config.API_KEYS, start=1):
        key_id = f"key_{index}"
        attempts = 1 + config.SAME_KEY_RETRIES

        for attempt in range(attempts):
            try:
                sim_status = simulation.get(key_id) or simulation.get("*")
                if sim_status:
                    raise SimulatedProviderError(sim_status)

                resp, text = await _call_key(key, messages, bypass_cache)
                cached = bool(resp._hidden_params.get("cache_hit"))
                return {
                    "reply": text,
                    "resolution_source": "LLM_CACHE" if cached else "LIVE_INFERENCE",
                    "model": config.MODEL,
                    "input_tokens": int(resp.usage.prompt_tokens or 0),
                    "output_tokens": int(resp.usage.completion_tokens or 0),
                    "key_id": None if cached else key_id,
                    "fallback_attempts": 0 if cached else failed,
                }
            except Exception as exc:
                if not should_failover(exc):
                    log.error("%s non-retryable error: %s", key_id, exc)
                    raise UpstreamError(type(exc).__name__) from exc
                simulated = isinstance(exc, SimulatedProviderError)
                transient = (not simulated) and _status(exc) in (500, 502, 503, 504)
                if transient and attempt < attempts - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                detail = str(exc)
                for secret in config.API_KEYS:
                    detail = detail.replace(secret, "[key]")
                log.warning("%s failed: %s | %s", key_id, type(exc).__name__, detail[:300])
                break

        failed += 1

    raise AllProvidersUnavailable()