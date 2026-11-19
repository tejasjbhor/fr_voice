"""
tools/prompt_eval/cache_check.py — is the persona cache even possible?

    python -m tools.prompt_eval.cache_check

build_system_blocks() puts a cache_control marker on the static persona block,
which reads as "the persona is cached for the whole call". It is only cached if
that block clears the serving model's minimum cacheable prefix. Under it, the
API caches nothing, reports nothing, and raises nothing — the marker is simply
ignored and every turn of every call pays full input price.

That minimum is model-specific and not monotonic across generations: Haiku 4.5
wants 4096 tokens, Sonnet 4.6 wants 1024. A prompt that caches fine on one
model silently stops caching when the model changes, including via a
per-language CLAUDE_MODEL_<LANG> override.

Token counts come from the real tokenizer via /v1/messages/count_tokens, which
is free and not billed. Character counts are useless here — Devanagari runs far
more tokens per character than Latin text, so the Hindi and Marathi packs are
much closer to the threshold than their file sizes suggest.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

import requests
from colorama import Fore, Style
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.llm_service import _model_for, cache_min_prefix_tokens  # noqa: E402
from tools.prompt_eval import PACKS  # noqa: E402

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"
))

_COUNT_URL = "https://api.anthropic.com/v1/messages/count_tokens"


def count_tokens(text: str | None, model: str, api_key: str) -> int:
    """
    Exact token count for `text` as a system block on `model`.

    `text=None` omits the system field entirely, which is how the envelope
    overhead is measured — the endpoint rejects an empty system block.
    """
    payload = {"model": model, "messages": [{"role": "user", "content": "."}]}
    if text is not None:
        payload["system"] = [{"type": "text", "text": text}]
    resp = requests.post(
        _COUNT_URL,
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["input_tokens"]


_overhead_cache: dict[str, int] = {}


def _overhead(model: str, api_key: str) -> int:
    """Tokens the envelope costs, so the persona figure is the persona alone."""
    if model not in _overhead_cache:
        _overhead_cache[model] = count_tokens(None, model, api_key)
    return _overhead_cache[model]


def check(sample_name: str = "Ramesh") -> int:
    api_key = (os.getenv("CLAUDE_API_KEY") or "").strip()
    if not api_key:
        print(f"{Fore.RED}CLAUDE_API_KEY is not set — count_tokens needs it "
              f"(the endpoint itself is free).{Style.RESET_ALL}")
        return 2

    rows, failing = [], 0
    for code, module in PACKS.items():
        try:
            personality = importlib.import_module(f"{module}.personality")
        except Exception as e:                                  # pragma: no cover
            print(f"{Fore.YELLOW}skipping {code}: {e}{Style.RESET_ALL}")
            continue

        model = _model_for(code)
        floor = cache_min_prefix_tokens(model)
        persona = personality._persona(sample_name)
        tokens = count_tokens(persona, model, api_key) - _overhead(model, api_key)

        ok = tokens >= floor
        failing += 0 if ok else 1
        rows.append((code, model, len(persona), tokens, floor, ok))

    width_model = max(len(r[1]) for r in rows) if rows else 10
    print(f"\n  {'lang':<7} {'model':<{width_model}} {'chars':>7} "
          f"{'tokens':>7} {'needs':>7}  caches?")
    print(f"  {'-'*7} {'-'*width_model} {'-'*7} {'-'*7} {'-'*7}  {'-'*7}")
    for code, model, chars, tokens, floor, ok in rows:
        colour = Fore.GREEN if ok else Fore.RED
        verdict = "yes" if ok else f"NO — short by {floor - tokens}"
        print(f"  {code:<7} {model:<{width_model}} {chars:>7} "
              f"{tokens:>7} {floor:>7}  {colour}{verdict}{Style.RESET_ALL}")

    if failing:
        print(f"\n  {Fore.RED}{failing} of {len(rows)} packs never cache.{Style.RESET_ALL} "
              f"Their cache_control marker is inert: the whole persona is\n"
              f"  re-billed at full input rate on every turn of every call, and "
              f"nothing in the API\n  response says so. Either grow the persona "
              f"past the floor or accept the cost —\n  but do not read the marker "
              f"as evidence the cache works.\n")
    else:
        print(f"\n  {Fore.GREEN}All packs clear their model's floor.{Style.RESET_ALL} "
              f"Confirm it is actually happening on\n  a live call: "
              f"cache_read_input_tokens should be > 0 from turn 2 onward.\n")
    return 1 if failing else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--name", default="Ramesh",
                    help="sample user name interpolated into the persona")
    args = ap.parse_args()
    return check(args.name)


if __name__ == "__main__":
    raise SystemExit(main())
