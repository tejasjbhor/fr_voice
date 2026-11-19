"""
edu/outcome.py — what the call was worth, decided after it ends.

Saathicare's equivalent is the HealthRecord row. Here the artefact is a lead
disposition plus a next action, because the entire point of the platform is
what happens after the call, not the call.

Deliberately rule-based rather than a second LLM pass. The inputs are already
structured (farewell reason, filled slots, escalation flag), an extra API call
adds latency to a hangup path, and a rule you can read is a rule a counsellor
can trust when they disagree with the disposition.
"""

from __future__ import annotations

from edu import qualification

# Terminal dispositions, in the order they are checked.
OUTCOMES = (
    "do_not_call",
    "wrong_person",
    "bereavement",
    "escalated",
    "visit_booked",
    "callback_requested",
    "qualified",
    "engaged",
    "not_interested",
    "unreachable",
    "no_engagement",
)

NEXT_ACTION = {
    "do_not_call": "Suppress permanently. Do not contact again on any campaign.",
    "wrong_person": "Remove this number from the lead. Re-verify contact details.",
    "bereavement": "Suppress. Do not contact again without an explicit human review.",
    "escalated": "Counsellor callback, priority. See escalation_reason.",
    "visit_booked": "Confirm the twenty-minute demo and send the maitria.ai link.",
    "callback_requested": "Counsellor callback at the requested time.",
    "qualified": "Counsellor callback within 48 hours.",
    "engaged": "Send the information pack. Retry once after a week.",
    "not_interested": "Close the lead. No retry.",
    "unreachable": "Retry inside the calling window, subject to attempt caps.",
    "no_engagement": "Retry once. Close if the second call also goes nowhere.",
}


def classify(
    *,
    farewell_reason: str | None,
    extracted: dict,
    turn_count: int,
    escalation_reason: str | None = None,
    heard_anything: bool = True,
) -> str:
    extracted = extracted or {}

    if farewell_reason == "declined":
        return "do_not_call"
    if farewell_reason == "wrong_person":
        return "wrong_person"
    if farewell_reason == "bereavement":
        return "bereavement"

    if not heard_anything or turn_count == 0:
        return "unreachable"

    if escalation_reason:
        return "escalated"

    if extracted.get("visit_intent") == "yes":
        return "visit_booked"
    if extracted.get("callback_time"):
        return "callback_requested"

    cov = qualification.coverage(extracted)
    if extracted.get("visit_intent") == "declined" and cov["ratio"] < 0.4:
        return "not_interested"

    # Three or more critical slots filled means the parent engaged properly and
    # a counsellor has something to work with.
    if len(cov["have"]) >= 3:
        return "qualified"

    if turn_count >= 4:
        return "engaged"
    return "no_engagement"


def score(extracted: dict, outcome: str, turn_count: int) -> int:
    """0-100. A ranking aid for a counsellor's morning list, nothing more.

    Intentionally crude. A score that looks precise invites people to trust it
    past what five keyword slots can support, and the honest signal here is
    coarse: did they engage, did they say yes to the visit, is the grade one we
    are actually open for.
    """
    if outcome in ("do_not_call", "wrong_person", "bereavement", "not_interested"):
        return 0

    pts = 0
    cov = qualification.coverage(extracted)
    pts += int(cov["ratio"] * 40)

    if extracted.get("visit_intent") == "yes":
        pts += 30
    elif extracted.get("callback_time"):
        pts += 15
    elif extracted.get("visit_intent") == "declined":
        pts -= 10

    stage = extracted.get("decision_stage")
    pts += {"ready": 20, "comparing": 10, "exploring": 0}.get(stage, 0)

    if extracted.get("intake") == "this year":
        pts += 10

    # A long call is engagement; a very short one is not. Capped so a chatty
    # call cannot outrank a decisive one.
    pts += min(turn_count, 10)

    if extracted.get("fee_concern"):
        pts -= 5

    return max(0, min(100, pts))


def summarise(
    *,
    farewell_reason: str | None,
    extracted: dict,
    turn_count: int,
    escalation_reason: str | None = None,
    unknown_count: int = 0,
    heard_anything: bool = True,
) -> dict:
    outcome = classify(
        farewell_reason=farewell_reason,
        extracted=extracted,
        turn_count=turn_count,
        escalation_reason=escalation_reason,
        heard_anything=heard_anything,
    )
    cov = qualification.coverage(extracted)
    return {
        "outcome": outcome,
        "next_action": NEXT_ACTION.get(outcome, ""),
        "score": score(extracted, outcome, turn_count),
        "slots": dict(extracted),
        "slots_missing": cov["missing"],
        "turns": turn_count,
        "escalation_reason": escalation_reason,
        "unanswered_questions": unknown_count,
        "suppress": outcome in ("do_not_call", "bereavement", "wrong_person"),
    }


# ── Counting what she could not answer ────────────────────────────
# The persona is told to use one fixed phrase when a fact is missing (see
# edu/persona.DEFER_PHRASE_EN and each pack's DEFER_PHRASE). Counting it gives
# two things for free: the escalation trigger, and a ranked list of the
# questions the institution file needs to answer next. That second one is the
# most useful report this system produces in its first month.


def is_deferral(agent_text: str, defer_markers: list[str]) -> bool:
    folded = (agent_text or "").lower()
    return any(m.lower() in folded for m in defer_markers if m)
