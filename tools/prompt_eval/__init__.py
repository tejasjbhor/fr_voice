"""
tools/prompt_eval — measuring the persona instead of guessing at it.

Two things live here, both offline and both free to run:

  cache_check.py  Does the static persona block actually clear the serving
                  model's minimum cacheable prefix? Below it the cache_control
                  marker is ignored silently and every turn pays full price.

  rules.py        The persona's mechanically checkable rules, as functions.
  report.py       Those rules run over the historical `conversations` table:
                  violation rate per rule, per language, no API spend.

The point of the second pair is to find which persona rules are actually being
broken in production before editing the prompt to fix rules that aren't.
"""

PACKS = {
    "en-IN": "lang_services.english",
    "hi-IN": "lang_services.hindi",
    "mr-IN": "lang_services.marathi",
    "es-ES": "lang_services.spanish",
}
