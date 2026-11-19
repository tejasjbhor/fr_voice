"""
core/llm_service.py — Provider-agnostic LLM streaming
Shared by all language services.
Supports: Claude API (production) | Ollama (dev/test)

Selection (.env):
  LLM_PROVIDER=auto     → Claude if CLAUDE_API_KEY is set, else Ollama
  LLM_PROVIDER=claude   → force Claude (needs key)
  LLM_PROVIDER=ollama   → force local Ollama

Comment out / clear CLAUDE_API_KEY and set LLM_PROVIDER=auto (or ollama)
to run fully local.
"""

import asyncio, json, os, re, time
from typing import AsyncGenerator
import aiohttp
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()


def _claude_key_ok(key: str) -> bool:
    """True when a real Anthropic API key is present (not empty/placeholder)."""
    k = (key or "").strip()
    if not k:
        return False
    low = k.lower()
    if low.startswith("your_") or "your_claude" in low or "api_key_here" in low:
        return False
    if low in ("changeme", "xxx", "none", "null"):
        return False
    return True


def _resolve_provider() -> str:
    """
    auto  → Claude when key exists, else Ollama
    claude / ollama → forced
    """
    raw = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    key = os.getenv("CLAUDE_API_KEY", "")

    if raw == "ollama":
        return "ollama"
    if raw == "claude":
        return "claude"
    # auto (default) and any unknown value
    if _claude_key_ok(key):
        return "claude"
    return "ollama"


CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL",   "claude-haiku-4-5")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://localhost:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL",   "qwen2.5:7b-instruct")
LLM_TIMEOUT    = int(os.getenv("LLM_TIMEOUT", 30))
LLM_PROVIDER   = _resolve_provider()  # resolved after reading key

CLAUDE_COST = {
    "claude-haiku-4-5":  {"input": 0.000083, "output": 0.000415},
    "claude-sonnet-4-6": {"input": 0.000249, "output": 0.001245},
}

# Prompt-cache multipliers on the input rate. A cached prefix is written once at
# a premium and read back cheaply; billing them at the plain input rate (which
# is what happened before these existed) overstates a cache hit by 10x and
# understates the write.
CACHE_WRITE_MULTIPLIER = 1.25   # 5-minute TTL
CACHE_READ_MULTIPLIER  = 0.10

# Smallest prefix the API will cache, per model. Below this the cache_control
# marker is silently ignored — no error, just cache_creation_input_tokens = 0
# forever. Haiku 4.5 has the highest minimum of any current model, and three of
# the four language packs are under it (see tools/prompt_eval/cache_check.py).
CACHE_MIN_PREFIX_TOKENS = {
    "claude-haiku-4-5":  4096,
    "claude-opus-4-6":   4096,
    "claude-sonnet-4-6": 1024,
    "claude-sonnet-4-5": 1024,
    "claude-opus-4-8":   1024,
    "claude-sonnet-5":   1024,
    "claude-opus-5":      512,
}
DEFAULT_CACHE_MIN_PREFIX_TOKENS = 4096


def cache_min_prefix_tokens(model: str) -> int:
    """Minimum cacheable prefix for `model`, pessimistic when unlisted."""
    return CACHE_MIN_PREFIX_TOKENS.get(model, DEFAULT_CACHE_MIN_PREFIX_TOKENS)

# Rates are per token in ₹. A model missing from the table is billed at this
# one, which is why _rates_for() says so out loud instead of guessing quietly —
# a per-language override (CLAUDE_MODEL_MR=...) used to be priced as Haiku with
# no indication that the number was wrong.
DEFAULT_COST_MODEL = "claude-haiku-4-5"
_unpriced_models: set[str] = set()


def _rates_for(model: str) -> dict:
    rates = CLAUDE_COST.get(model)
    if rates is None:
        if model not in _unpriced_models:
            _unpriced_models.add(model)
            print(f"\n  {Fore.YELLOW}⚠️  No price listed for '{model}' — billing it at "
                  f"{DEFAULT_COST_MODEL} rates. Add it to CLAUDE_COST.{Style.RESET_ALL}")
        rates = CLAUDE_COST[DEFAULT_COST_MODEL]
    return rates


class UsageMeter:
    """
    Token and cost accumulator for ONE call.

    This used to be a module-level dict driven by reset_costs() / get_costs().
    The phone server handles many calls at once in a single process, so two
    concurrent callers accumulated into the same counters and whichever call
    started later reset the other's totals to zero — every api_costs row was
    wrong the moment two people were on the line together.

    Cost is accrued per usage event at the rate of the model that produced it,
    so a per-language model override is priced correctly even when a single call
    mixes models.

    Cache tokens are counted separately because `input_tokens` from the API is
    the UNCACHED remainder only, not the whole prompt. Reading input_tokens
    alone — which is all this used to do — makes a working cache look like a
    shrinking prompt and a broken cache look identical to a working one. The
    real prompt size is total_prompt_tokens; whether the persona cache is
    working at all is cache_read_input_tokens > 0 from the second turn on.
    """

    __slots__ = ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens",
                 "cost_inr")

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0
        self.cost_inr = 0.0

    def record(self, model: str, input_tokens: int = 0, output_tokens: int = 0,
               cache_creation_input_tokens: int = 0,
               cache_read_input_tokens: int = 0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        rates = _rates_for(model)
        self.cost_inr += (
            input_tokens * rates["input"]
            + output_tokens * rates["output"]
            + cache_creation_input_tokens * rates["input"] * CACHE_WRITE_MULTIPLIER
            + cache_read_input_tokens * rates["input"] * CACHE_READ_MULTIPLIER
        )

    @property
    def total_prompt_tokens(self) -> int:
        """Whole prompt, cached or not — what input_tokens looks like it is."""
        return (self.input_tokens
                + self.cache_creation_input_tokens
                + self.cache_read_input_tokens)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.output_tokens

    @property
    def cache_hit_ratio(self) -> float:
        """Share of prompt tokens served from cache. 0.0 means no cache at all."""
        prompt = self.total_prompt_tokens
        return (self.cache_read_input_tokens / prompt) if prompt else 0.0

    def as_dict(self) -> dict:
        return {
            "input_tokens":  self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens":     self.cache_read_input_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_tokens":  self.total_tokens,
            "cache_hit_ratio": self.cache_hit_ratio,
            "cost_inr":      self.cost_inr,
        }


# Process-wide meter for entry points that only ever run one call at a time
# (local mic mode, smoke scripts). The phone server passes a per-session meter.
_default_meter = UsageMeter()


def reset_costs() -> None:
    """Reset the process-wide meter. Single-call entry points only."""
    global _default_meter
    _default_meter = UsageMeter()


def get_costs() -> dict:
    """Read the process-wide meter. Single-call entry points only."""
    return _default_meter.as_dict()


def check() -> bool:
    mode = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    if LLM_PROVIDER == "claude":
        if not _claude_key_ok(CLAUDE_API_KEY):
            print(f"{Fore.RED}❌ CLAUDE_API_KEY missing or placeholder{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}   Set a real key, or use LLM_PROVIDER=ollama / comment out the key with auto{Style.RESET_ALL}")
            return False
        print(f"{Fore.GREEN}✅ LLM: Claude | {CLAUDE_MODEL}{Style.RESET_ALL}")
        return True

    # Ollama path (forced or auto-fallback)
    if mode in ("auto", "") and not _claude_key_ok(CLAUDE_API_KEY):
        print(f"{Fore.CYAN}ℹ️  No Claude key — using local Ollama{Style.RESET_ALL}")

    import requests
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models",[])]
        base   = OLLAMA_MODEL.split(":")[0]
        if any(base in m for m in models):
            print(f"{Fore.GREEN}✅ LLM: Ollama | {OLLAMA_MODEL}{Style.RESET_ALL}")
            return True
        print(f"{Fore.YELLOW}⚠️  Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}{Style.RESET_ALL}")
        return False
    except Exception:
        print(f"{Fore.RED}❌ Ollama not running — start: ollama serve{Style.RESET_ALL}")
        return False


def _model_for(language: str | None) -> str:
    """
    Per-language model override, e.g. CLAUDE_MODEL_MR=claude-sonnet-4-6.
    Low-resource languages (Marathi especially) are noticeably more accurate on
    a stronger model, so they can be upgraded without paying for it everywhere.
    """
    if language:
        code = language.split("-")[0].strip().upper()
        override = (os.getenv(f"CLAUDE_MODEL_{code}") or "").strip()
        if override:
            return override
    return CLAUDE_MODEL


def _system_to_text(system) -> str:
    """Flatten Anthropic-style system blocks into plain text (Ollama path)."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(
            b.get("text", "") for b in system if isinstance(b, dict)
        ).strip()
    return str(system or "")


async def stream_tokens(system_prompt,
                        messages: list,
                        language: str | None = None,
                        meter: UsageMeter | None = None) -> AsyncGenerator[str, None]:
    """
    Stream raw tokens from Claude or Ollama.
    `system_prompt` may be a plain string or a list of Anthropic system blocks
    (which allows marking the static persona prefix as cacheable).
    `language` selects a per-language model override when one is configured.
    `meter` should be the calling session's UsageMeter — anything sharing the
    process-wide default while another call is live gets mixed-up totals.
    Caller handles sentence splitting and TTS.
    """
    if LLM_PROVIDER == "claude":
        async for t in _claude_stream(system_prompt, messages,
                                      model=_model_for(language),
                                      meter=meter):
            yield t
    else:
        async for t in _ollama_stream(_system_to_text(system_prompt), messages):
            yield t


async def complete(prompt: str) -> str:
    """Non-streaming completion — used for health extraction."""
    if LLM_PROVIDER == "claude":
        return await _claude_complete(prompt)
    return await _ollama_complete(prompt)


async def keepalive():
    """Keep Ollama model in GPU VRAM between turns."""
    if LLM_PROVIDER != "ollama": return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{OLLAMA_URL}/api/generate",
                json={"model":OLLAMA_MODEL,"prompt":" ","num_predict":1,"keep_alive":"10m"},
                timeout=aiohttp.ClientTimeout(total=3))
    except Exception: pass


# ── Claude ────────────────────────────────────────────────────────

def _has_cache_marker(system) -> bool:
    return isinstance(system, list) and any(
        isinstance(b, dict) and b.get("cache_control") for b in system
    )


_cache_warned: set[str] = set()


def _warn_if_cache_dead(model: str, system, usage: dict) -> None:
    """
    Say so when a cache_control marker produced neither a write nor a read.

    This is the failure the API gives no signal for: a prefix shorter than the
    model's minimum is not cached and not complained about, so the marker looks
    like it is working while every turn pays full price. Warned once per model
    per process — it is a config fact, not a per-turn event.
    """
    if model in _cache_warned or not _has_cache_marker(system):
        return
    if (usage.get("cache_creation_input_tokens") or 0) > 0:
        return
    if (usage.get("cache_read_input_tokens") or 0) > 0:
        return
    _cache_warned.add(model)
    floor = cache_min_prefix_tokens(model)
    print(f"\n  {Fore.YELLOW}⚠️  Prompt cache is not engaging on '{model}' "
          f"(needs a prefix of ~{floor} tokens). Every turn is paying full "
          f"input price. Run: python -m tools.prompt_eval.cache_check"
          f"{Style.RESET_ALL}")


async def _claude_stream(system, messages: list,
                         model: str | None = None,
                         meter: UsageMeter | None = None) -> AsyncGenerator[str, None]:
    model = model or CLAUDE_MODEL
    meter = meter if meter is not None else _default_meter
    headers = {"x-api-key":CLAUDE_API_KEY,
               "anthropic-version":"2023-06-01",
               "content-type":"application/json"}
    payload = {"model":model,"max_tokens":250,
               "system":system,"messages":messages,"stream":True}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.anthropic.com/v1/messages",
                    headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    # Older API versions reject cache_control — retry plain once
                    if resp.status == 400 and not isinstance(system, str):
                        print(f"\n  {Fore.YELLOW}⚠️  Claude rejected cached system prompt; "
                              f"retrying without cache{Style.RESET_ALL}")
                        async for t in _claude_stream(_system_to_text(system),
                                                      messages, model=model,
                                                      meter=meter):
                            yield t
                        return
                    print(f"\n  {Fore.RED}❌ Claude {resp.status}: {body}{Style.RESET_ALL}")
                    return
                async for raw in resp.content:
                    line = raw.decode("utf-8",errors="ignore").strip()
                    if not line or not line.startswith("data:"): continue
                    ds = line[5:].strip()
                    if ds == "[DONE]": break
                    try: ev = json.loads(ds)
                    except: continue
                    t = ev.get("type","")
                    if t == "content_block_delta":
                        d = ev.get("delta",{})
                        if d.get("type") == "text_delta":
                            yield d.get("text","")
                    elif t == "message_delta":
                        meter.record(model,
                            output_tokens=ev.get("usage",{}).get("output_tokens",0))
                    elif t == "message_start":
                        u = ev.get("message",{}).get("usage",{}) or {}
                        meter.record(model,
                            input_tokens=u.get("input_tokens",0),
                            cache_creation_input_tokens=u.get("cache_creation_input_tokens",0) or 0,
                            cache_read_input_tokens=u.get("cache_read_input_tokens",0) or 0)
                        _warn_if_cache_dead(model, system, u)
    except asyncio.TimeoutError:
        print(f"\n  {Fore.RED}❌ Claude timeout{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n  {Fore.RED}❌ Claude: {e}{Style.RESET_ALL}")


async def _claude_complete(prompt: str) -> str:
    headers = {"x-api-key":CLAUDE_API_KEY,"anthropic-version":"2023-06-01",
               "content-type":"application/json"}
    payload = {"model":CLAUDE_MODEL,"max_tokens":400,
               "messages":[{"role":"user","content":prompt}]}
    async with aiohttp.ClientSession() as s:
        async with s.post("https://api.anthropic.com/v1/messages",
                headers=headers,json=payload,
                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["content"][0]["text"]


# ── Ollama ────────────────────────────────────────────────────────

async def _ollama_stream(system: str, messages: list) -> AsyncGenerator[str, None]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role":"system","content":system}] + messages,
        "stream": True, "think": False,
        "options": {"temperature":0.8,"num_predict":200,
                    "num_ctx":2048,"top_p":0.9,"repeat_penalty":1.1},
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{OLLAMA_URL}/api/chat", json=payload,
                    timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                resp.raise_for_status()
                async for raw in resp.content:
                    line = raw.decode("utf-8",errors="ignore").strip()
                    if not line: continue
                    try: chunk = json.loads(line)
                    except: continue
                    token = chunk.get("message",{}).get("content","")
                    if token: yield token
                    if chunk.get("done"): break
        asyncio.create_task(keepalive())
    except Exception as e:
        print(f"\n  {Fore.RED}❌ Ollama: {e}{Style.RESET_ALL}")


async def _ollama_complete(prompt: str) -> str:
    payload = {"model":OLLAMA_MODEL,"prompt":prompt,"stream":False,"think":False,
               "options":{"temperature":0.1,"num_predict":400,"num_ctx":2048}}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{OLLAMA_URL}/api/generate",json=payload,
                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            return data.get("response","{}")
