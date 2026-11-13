"""Model calls: disk cache, kill switch, retries. OpenAI-compatible Chat Completions on the Meta Model API.

cache key = sha256(model, base_url, messages, temperature, seed, max_tokens, extra request params). A cache hit
costs $0 and never touches the ledger. Any HTTP-200 answer is cached, including empty / truncated ones (they were
billed). Failed calls (after retries) are logged to the ledger with status="error" and cost 0, and not cached, so a
rerun retries them.

`seed` is sent only if config `send_seed` is true; it is always part of the cache key, so seeds act as replicate
indices even if the API has no seed parameter (then variation comes from temperature > 0).
The API key is read from the environment at call time and never stored, printed or logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import requests

from sor.budget import Budget, price_usd
from sor.config import model_entry

Transport = Callable[[dict], tuple[int, dict | str, dict]]


class ParamUnsupported(RuntimeError):
    """The API rejected `seed` or `temperature` (HTTP 400). Stops the run; flip send_seed/send_temperature."""


class MissingKey(RuntimeError):
    pass


@dataclass
class CallResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    status: str = "ok"            # ok | error
    finish_reason: str | None = None
    reasoning_text: str | None = None
    error: str | None = None
    attempts: int = 0
    cache_key: str = ""
    original_cost_usd: float = 0.0  # what the call cost when it was first made (cache hits: cost_usd = 0)
    extra: dict = field(default_factory=dict)


_ENCODER = None


def count_tokens(messages: list[dict]) -> int:
    """Proxy token count (o200k_base; the Meta tokenizer is not public). Falls back to chars / 3.5."""
    global _ENCODER
    text = "\n".join(m["content"] for m in messages)
    if _ENCODER is None:
        try:
            import tiktoken
            _ENCODER = tiktoken.get_encoding("o200k_base")
        except Exception:  # noqa: BLE001 - offline: crude fallback
            _ENCODER = False
    n = len(_ENCODER.encode(text)) if _ENCODER else int(len(text) / 3.5)
    return n + 4 * len(messages)


def http_transport(cfg: dict) -> Transport:
    session = requests.Session()

    def send(payload: dict) -> tuple[int, dict | str, dict]:
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise MissingKey(f"environment variable {cfg['api_key_env']} is not set")
        r = session.post(cfg["base_url"].rstrip("/") + "/chat/completions", json=payload,
                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                         timeout=cfg["request_timeout_s"])
        try:
            body = r.json()
        except ValueError:
            body = r.text[:2000]
        return r.status_code, body, dict(r.headers)

    return send


class ModelClient:
    def __init__(self, cfg: dict, budget: Budget, cache_dir: Path, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self.budget = budget
        self.cache_dir = Path(cache_dir)
        self.transport = transport or http_transport(cfg)
        self.sleep = sleep

    # --- request + cache -----------------------------------------------------------------------------
    def request_params(self, model: str, messages: list[dict], temperature: float, seed: int) -> dict:
        payload = {"model": model, "messages": messages, "max_tokens": self.cfg["max_tokens"]}
        if self.cfg.get("send_temperature", True):
            payload["temperature"] = temperature
        if self.cfg.get("send_seed", True):
            payload["seed"] = seed
        if self.cfg.get("reasoning_effort"):
            payload["reasoning_effort"] = self.cfg["reasoning_effort"]
        return payload

    def cache_key(self, model: str, messages: list[dict], temperature: float, seed: int) -> str:
        extra = {k: v for k, v in (("reasoning_effort", self.cfg.get("reasoning_effort")),
                                   ("send_seed", self.cfg.get("send_seed", True)),
                                   ("send_temperature", self.cfg.get("send_temperature", True))) if v not in
                 (None, True)}
        blob = json.dumps({"model": model, "base_url": self.cfg["base_url"], "messages": messages,
                           "temperature": temperature, "seed": seed, "max_tokens": self.cfg["max_tokens"],
                           **({"extra": extra} if extra else {})}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def peek(self, model: str, messages: list[dict], temperature: float, seed: int) -> CallResult | None:
        """Cached result or None; never calls the API."""
        key = self.cache_key(model, messages, temperature, seed)
        p = self._cache_path(key)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        r = CallResult(**{k: v for k, v in d["result"].items() if k in CallResult.__dataclass_fields__})
        r.original_cost_usd = d["result"]["cost_usd"]
        r.cost_usd, r.cached, r.cache_key = 0.0, True, key
        return r

    def _store(self, key: str, payload: dict, result: CallResult, tag: str) -> None:
        p = self._cache_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"request": payload, "tag": tag, "result": asdict(result)}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)

    def max_cost(self, model: str, messages: list[dict]) -> float:
        entry = model_entry(self.cfg, model)
        est_in = int(count_tokens(messages) * self.cfg["estimate"]["input_token_margin"])
        return price_usd(entry, est_in, self.cfg["max_tokens"])

    # --- the call --------------------------------------------------------------------------------------
    def call_model(self, messages: list[dict], seed: int, temperature: float, model: str, tag: str) -> CallResult:
        cached = self.peek(model, messages, temperature, seed)
        if cached is not None:
            return cached
        entry = model_entry(self.cfg, model)
        key = self.cache_key(model, messages, temperature, seed)
        payload = self.request_params(model, messages, temperature, seed)
        reservation = self.budget.reserve(self.max_cost(model, messages))  # raises BudgetExceeded: nothing sent
        t0 = time.perf_counter()
        attempt, last_error = 0, None
        try:
            while True:
                attempt += 1
                try:
                    status, body, headers = self.transport(payload)
                except (requests.ConnectionError, requests.Timeout) as exc:
                    status, body, headers, last_error = None, None, {}, f"{type(exc).__name__}: {str(exc)[:200]}"
                if status == 200 and isinstance(body, dict):
                    break
                if status is not None:
                    last_error = f"HTTP {status}: {json.dumps(body)[:400] if isinstance(body, dict) else body[:400]}"
                if status == 400 and isinstance(last_error, str) and any(
                        p in last_error.lower() for p in ("seed", "temperature")):
                    self.budget.record(reservation, {"tag": tag, "model": model, "status": "error", "cost_usd": 0.0,
                                                     "error": last_error, "cache_key": key})
                    reservation = 0.0
                    raise ParamUnsupported(f"{model} rejected a sampling parameter: {last_error}. Set send_seed / "
                                           "send_temperature to false in config.yaml.")
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt > self.cfg["max_retries"]:
                    result = CallResult(text="", status="error", error=last_error, attempts=attempt, cache_key=key,
                                        latency_s=round(time.perf_counter() - t0, 3))
                    self.budget.record(reservation, {"tag": tag, "model": model, "status": "error",
                                                     "cost_usd": 0.0, "error": last_error, "attempts": attempt,
                                                     "cache_key": key})
                    reservation = 0.0
                    return result
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(30.0, 2.0 ** (attempt - 1))
                except ValueError:
                    delay = min(30.0, 2.0 ** (attempt - 1))
                self.sleep(delay * (1 + 0.25 * random.random()))
        except BaseException:
            if reservation:
                self.budget.release(reservation)
            raise

        choice = body["choices"][0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        in_tok, out_tok = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        cost = price_usd(entry, in_tok, out_tok)
        result = CallResult(
            text=message.get("content") or "", input_tokens=in_tok, output_tokens=out_tok,
            reasoning_tokens=int(details.get("reasoning_tokens") or 0), cost_usd=cost,
            latency_s=round(time.perf_counter() - t0, 3), cached=False, status="ok",
            finish_reason=choice.get("finish_reason"), reasoning_text=message.get("reasoning_content"),
            attempts=attempt, cache_key=key, original_cost_usd=cost)
        self.budget.record(reservation, {"tag": tag, "model": model, "status": "ok", "input_tokens": in_tok,
                                         "output_tokens": out_tok, "reasoning_tokens": result.reasoning_tokens,
                                         "cost_usd": cost, "latency_s": result.latency_s,
                                         "finish_reason": result.finish_reason, "attempts": attempt,
                                         "cache_key": key})
        self._store(key, payload, result, tag)
        return result
