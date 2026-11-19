"""
edu/tools/smoke_edu.py — run a scripted call without a phone, a model or a rupee.

    python -m edu.tools.smoke_edu
    python -m edu.tools.smoke_edu fr-FR

Drives a fixed parent-side transcript through the real qualification extractor,
the real steering rules, the real escalation checks and the real outcome
classifier, printing what the prompt tail would have said at each turn. Nothing
is called over the network.

This is the test that catches the things that actually break: a hint list that
stopped matching, a steer that fires while a question is unanswered, a slot
that never fills because the catchment list is empty. `tools/prompt_eval/selftest`
in the parent repo exists for the same reason — a checker that has quietly
stopped matching reports zero violations, which is indistinguishable from a
rule that is passing.

Exit code is non-zero if the contract check fails or the scripted call ends in
an outcome that the script should not have produced.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from edu import escalation, outcome, qualification  # noqa: E402
from edu.institution import get_institution  # noqa: E402
from edu.lang_loader import load_edu_lang_service  # noqa: E402

# Everything services/conversation_engine.py, telephony/session.py and
# services/session_manager.py reach for on a language pack. If this list stops
# matching the engine, the call fails at runtime on a live parent — so it is
# checked here first.
CONTRACT_ATTRS = [
    "CODE", "NAME", "PROMPT_VERSION",
    "GREETING", "CLOSING", "EMERGENCY", "FALLBACK", "STILL_THERE",
    "EMERGENCY_KEYWORDS", "EXIT_WORDS", "TRAILING_PARTICLES",
    "SELF_EXIT_WORDS", "SELF_EXIT_BLOCKERS",
    "UNAVAILABLE_WORDS", "DECLINE_WORDS", "WRONG_PERSON_WORDS", "BEREAVEMENT_WORDS",
    "TTS_CONFIG", "HINTS", "CRITICAL_TOPICS",
]
CONTRACT_CALLABLES = [
    "build_prompt", "build_system_blocks", "build_greeting", "build_closing",
    "prepare_for_tts", "read_tone",
]

# A parent who engages properly: asks questions, gives up the slots one at a
# time, raises a fee objection, and agrees to a visit.
SCRIPT_EN = [
    "Yes, speaking. Go ahead.",
    "What's the fee for class five?",
    "Does that include the bus?",
    "We're in Kothrud.",
    "Which board do you follow?",
    "He's nine years old.",
    "Bit expensive compared to others, no?",
    "We're looking at this year itself.",
    "When is the entrance test?",
    "Okay, can I come and see the school?",
    "Saturday works for me.",
    "That's all, thank you.",
]

SCRIPT_FR = [
    "Oui, j'écoute.",
    "Quels sont les frais pour la cinquième ?",
    "Est-ce que le bus est inclus ?",
    "Nous habitons à Lyon.",
    "Quel est le programme scolaire ?",
    "Il a neuf ans.",
    "C'est un peu cher par rapport aux autres, non ?",
    "On regarde pour cette année.",
    "Quand a lieu le test d'entrée ?",
    "On peut venir visiter l'école ?",
    "Samedi me convient.",
    "Merci, c'est tout.",
]

SCRIPTS = {"fr-FR": SCRIPT_FR, "en-IN": SCRIPT_EN}


def check_contract(pack) -> list[str]:
    problems = []
    for attr in CONTRACT_ATTRS:
        if not hasattr(pack, attr):
            problems.append(f"missing attribute: {attr}")
    for fn in CONTRACT_CALLABLES:
        if not callable(getattr(pack, fn, None)):
            problems.append(f"missing callable: {fn}")
    return problems


def main(argv: list[str]) -> int:
    code = argv[1] if len(argv) > 1 else "fr-FR"
    inst = get_institution()
    pack = load_edu_lang_service(code, inst)

    print(f"Pack        : {pack.NAME} ({pack.CODE})")
    print(f"Version     : {pack.PROMPT_VERSION}")
    print(f"Agent       : {pack.agent_name}, {pack.agent_role}")
    print(f"Institution : {inst.name}\n")

    problems = check_contract(pack)
    if problems:
        print("CONTRACT CHECK FAILED")
        for p in problems:
            print("  - " + p)
        return 2
    print("Contract    : ok — every name the call engine touches is present.\n")

    print("GREETING")
    print("  " + pack.build_greeting("M. Dupont", {}))
    print()

    hints = pack.HINTS
    extracted: dict = {}
    steers_used = 0
    unknown_count = 0
    esc_reason = None
    script = SCRIPTS.get(code, SCRIPT_FR)
    wrap_up_from = len(script) - 2

    print("CALL")
    print("-" * 78)
    for turn, said in enumerate(script, start=1):
        asked = qualification.parent_asked_question(said, hints)
        found = qualification.fast_qualify(
            said,
            "",
            hints,
            catchment_areas=inst.catchment_areas,
            catchment_aliases=inst.catchment_aliases,
            numerals=getattr(pack, "NUMERALS", {}),
        )
        qualification.merge(extracted, found)

        if esc_reason is None:
            esc_reason = escalation.check(said, hints, unknown_count=unknown_count)

        steer, topic = qualification.should_steer(
            turn_number=turn,
            extracted=extracted,
            wrap_up_from=wrap_up_from,
            asked_question=asked,
            steers_used=steers_used,
        )
        if steer and topic and topic not in qualification.NON_STEER_TOPICS:
            steers_used += 1

        flags = []
        if asked:
            flags.append("question")
        if found:
            flags.append("+" + ",".join(found))
        if steer:
            flags.append(f"steer->{topic}")
        if esc_reason:
            flags.append(f"escalate:{esc_reason}")

        print(f"{turn:>3}  {said}")
        if flags:
            print(f"     {' | '.join(flags)}")

    print("-" * 78)

    cov = qualification.coverage(extracted)
    result = outcome.summarise(
        farewell_reason="goodbye",
        extracted=extracted,
        turn_count=len(script),
        escalation_reason=esc_reason,
        unknown_count=unknown_count,
    )

    print("\nSLOTS FILLED")
    for k, v in extracted.items():
        print(f"  {k:<16} {v}")
    print(f"\n  critical coverage: {len(cov['have'])}/{len(qualification.CRITICAL_SLOTS)}"
          f"  missing: {', '.join(cov['missing']) or 'none'}")

    print(f"\nOUTCOME     : {result['outcome']}  (score {result['score']})")
    print(f"NEXT ACTION : {result['next_action']}")
    print(f"STEERS USED : {steers_used}")

    print("\nCLOSING")
    print("  " + pack.build_closing("M. Dupont", {"extracted_so_far": extracted}))

    # ── Assertions ────────────────────────────────────────────────
    failures = []
    if result["outcome"] not in ("visit_booked", "qualified"):
        failures.append(
            f"an engaged parent who agreed to a visit produced {result['outcome']!r}"
        )
    if "grade" not in extracted:
        failures.append("grade was never extracted from a script that states it twice")
    if "locality" not in extracted:
        failures.append(
            "locality was never extracted — check the institution's catchment_areas"
        )
    if steers_used > 5:
        failures.append(f"{steers_used} steers is an interrogation, not a conversation")

    if failures:
        print("\nFAILURES")
        for f in failures:
            print("  - " + f)
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
