"""
edu/tools/prospectus_lint.py — is this institution file fit to take calls?

    python -m edu.tools.prospectus_lint
    python -m edu.tools.prospectus_lint edu/data/institutions/other_school.json

Offline. No API calls, no cost. Answers three questions:

  1. Which questions can the agent not answer? Every gap here is a call where a
     parent asks something reasonable and is told a counsellor will confirm.

  2. Does the static prefix clear the model's minimum cacheable prefix? This is
     the trap CLAUDE.md documents: the `cache_control` marker is not the
     mechanism. Below the floor the API caches nothing, reports nothing and
     raises nothing, and the whole persona is re-billed on every single turn
     while the code reads as though it were cached.

  3. How big is each language pack's prefix? Devanagari tokenises about 2.6x
     denser than Latin, so the same institution costs very different amounts in
     Marathi and English.

Run it after every edit to an institution file, and after any change to
edu/persona.py.
"""

from __future__ import annotations

import os
import sys

# Allow `python -m edu.tools.prospectus_lint` from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from edu import knowledge  # noqa: E402
from edu.institution import Institution, InstitutionError  # noqa: E402
from edu.lang_loader import load_edu_lang_service, reset_cache  # noqa: E402

LANGS = ("fr-FR", "en-IN")

# Which model each language actually runs on. Mirrors _model_for() in
# core/llm_service.py: CLAUDE_MODEL_<LANG> overrides CLAUDE_MODEL.
def _model_for(code: str) -> str:
    lang = code.split("-")[0].upper()
    return (
        os.getenv(f"CLAUDE_MODEL_{lang}")
        or os.getenv("CLAUDE_MODEL")
        or "claude-haiku-4-5"
    )


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else None

    try:
        inst = Institution.load(path)
    except InstitutionError as e:
        print(f"FAIL  {e}")
        return 2

    print(f"Institution : {inst.name} ({inst.display_kind()}, {inst.city})")
    print(f"File        : {inst.source_path}")
    print(f"Grades open : {', '.join(inst.grades_open) or '(none listed)'}")
    print()

    # ── 1. Coverage ───────────────────────────────────────────────
    missing = inst.unknown_topics()
    if missing:
        print("QUESTIONS SHE CANNOT ANSWER")
        for m in missing:
            print(f"  - {m.replace('_', ' ')}")
        print(
            "\n  Each of these becomes a deferral on a live call. Three "
            "deferrals in one call triggers a counsellor handoff.\n"
        )
    else:
        print("Coverage    : every expected topic is present.\n")

    if not inst.catchment_areas:
        print(
            "WARNING     : no catchment_areas listed. Locality is one of the five "
            "critical qualification slots and it is extracted by matching this "
            "list, so it will never be filled.\n"
        )

    if not inst.prohibited_claims:
        print(
            "WARNING     : no prohibited_claims listed. At minimum, forbid "
            "guaranteeing a seat and quoting scholarship amounts.\n"
        )

    # ── 2 & 3. Sizing and cache verdict ───────────────────────────
    block = knowledge.build_knowledge_block(inst)
    print(f"Knowledge block: {len(block)} chars, ~{knowledge.estimate_tokens(block)} tokens\n")

    print(f"{'lang':<8}{'static prefix':>16}{'floor':>8}{'model':>22}  verdict")
    print("-" * 74)

    worst = 0
    reset_cache()
    for code in LANGS:
        try:
            pack = load_edu_lang_service(code, inst)
        except Exception as e:  # pragma: no cover
            print(f"{code:<8}{'ERROR':>16}  {e}")
            worst = max(worst, 2)
            continue

        blocks = pack.build_system_blocks("Test Parent", {"turn_number": 1})
        static = blocks[0]["text"]
        tokens = knowledge.estimate_tokens(static)
        model = _model_for(code)
        floor = knowledge.cache_floor_for(model)

        if tokens >= floor:
            verdict = "caches"
        else:
            verdict = f"NEVER CACHES (short by {floor - tokens})"
            worst = max(worst, 1)

        print(f"{code:<8}{tokens:>16}{floor:>8}{model:>22}  {verdict}")

    print()
    if worst == 1:
        print(
            "A prefix below the floor is billed in full on every turn. Either add "
            "facts to the institution file, or point that language at a model with "
            "a lower floor via CLAUDE_MODEL_<LANG>. Verify on a live call: "
            "cache_read_input_tokens should be above zero from turn 2 onward."
        )
    else:
        print("All packs clear their cache floor.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
