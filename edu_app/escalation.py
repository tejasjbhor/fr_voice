"""
edu/escalation.py — when a human counsellor should take over.

The education analogue of core/alert_engine.py. Saathicare escalates on a
medical signal; this escalates when the conversation has left what an automated
agent should be handling at all.

Note the deliberate inclusion of `special_needs`. A parent disclosing that their
child has a disability, a medical condition or a specific learning need is
telling you something that deserves a person's judgement — about whether the
institution can actually support the child, which is not a question a prompt
should answer. Treat that disclosure as sensitive: it is routed to a human and
it should not be used for lead scoring.
"""

from __future__ import annotations

# Ordered by urgency. The first match wins.
REASONS = (
    "asked_for_human",
    "special_needs",
    "complaint",
    "fee_negotiation",
    "repeated_unknown",
)

# How many times she can say she does not have a fact before the call has
# clearly outrun its knowledge block.
UNKNOWN_LIMIT = 3

URGENCY = {
    "asked_for_human": "high",
    "special_needs": "high",
    "complaint": "high",
    "fee_negotiation": "normal",
    "repeated_unknown": "normal",
}

# Slots that must not be written to the lead record when the reason is
# special_needs — see the module docstring.
SENSITIVE_REASONS = {"special_needs"}


def _fold(text: str) -> str:
    return (text or "").lower().strip()


def _hit(text: str, hints: dict, key: str) -> bool:
    folded = _fold(text)
    for phrase in (hints or {}).get(key, []) or []:
        p = _fold(phrase)
        if p and p in folded:
            return True
    return False


def check(user_text: str, hints: dict, unknown_count: int = 0) -> str | None:
    """Return an escalation reason for this turn, or None."""
    if _hit(user_text, hints, "wants_human"):
        return "asked_for_human"
    if _hit(user_text, hints, "special_needs"):
        return "special_needs"
    if _hit(user_text, hints, "complaint"):
        return "complaint"
    if _hit(user_text, hints, "fee_negotiation"):
        return "fee_negotiation"
    if unknown_count >= UNKNOWN_LIMIT:
        return "repeated_unknown"
    return None


def instruction(reason: str) -> str:
    """The line dropped into the per-turn prompt tail once escalation fires.

    She does not hang up on an escalation. She acknowledges, promises the
    callback, and lets the conversation finish naturally — a call cut short at
    the exact moment a parent raised something difficult is worse than no call.
    """
    return {
        "asked_for_human": (
            "They have asked to speak to a person. Say warmly that you will have "
            "a counsellor call them, confirm this is the right number, and stop "
            "trying to answer the question yourself."
        ),
        "special_needs": (
            "They have mentioned a medical condition, disability or specific "
            "learning need. Do not assess it, do not reassure them about it, and "
            "do not say whether the institution can accommodate it. Acknowledge "
            "it kindly in one sentence and say a counsellor will call to talk it "
            "through properly."
        ),
        "complaint": (
            "They are unhappy about something. Do not defend the institution and "
            "do not explain. Acknowledge it plainly, say someone will call them "
            "about it, and let them say their piece."
        ),
        "fee_negotiation": (
            "They are asking about a concession, discount or scholarship. You "
            "cannot offer or discuss any. Say a counsellor handles that and will "
            "call them."
        ),
        "repeated_unknown": (
            "You have not had the answer several times now. Say honestly that a "
            "counsellor can give them the full picture, and offer to arrange it."
        ),
    }.get(reason, "")
