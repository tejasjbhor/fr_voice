"""
edu/tools/eval_rules.py — education-specific persona checkers.

Extends tools/prompt_eval/rules.py rather than replacing it. The mechanical
rules there — one question per reply, three sentences, no line breaks, no
markdown, honorific slips, kept-talking-after-goodbye — are domain-neutral and
apply to an admissions call exactly as they do to a health call. Reusing them
means a fix in either product benefits both.

What is added here is the set of failures that only exist because this agent is
selling something. In rough order of how much damage each does:

  invented_fact      — a rupee figure or a date that is not in the institution
                       file. The single most dangerous failure in this product:
                       a parent will plan around it.
  pressure_language  — scarcity and urgency. Forbidden outright in the persona.
  comparative_claim  — "better than", "number one". Legally exposed and
                       explicitly in prohibited_claims.
  guaranteed_seat    — only the admissions office confirms a seat.
  repeat_ask         — asked for something the parent already gave. The clearest
                       possible tell that this is a machine.
  pushed_after_no    — offered the visit again after it was declined.
  stacked_questions  — reuses the base rule but matters more here, because a
                       parent answering two questions at once answers neither.

Deliberately absent: any checker for warmth, for sounding like a counsellor
rather than a salesperson, or for whether an answer was useful. Those need
judgement, and a bad regex standing in for judgement poisons the numbers the
tool exists to produce. Same reasoning as the note at the top of
tools/prompt_eval/rules.py.

Usage — same shape as the base report:

    from edu.tools.eval_rules import check_session_edu, EDU_RULE_NAMES
    result = check_session_edu(turns, pack, institution)
"""

from __future__ import annotations

import re

from tools.prompt_eval.rules import (
    SESSION_RULES,
    TURN_RULES,
    SessionResult,
    Turn,
    Violation,
    _is_verbatim_pack_line,
)

EDU_RULE_NAMES = (
    "invented_fact",
    "pressure_language",
    "comparative_claim",
    "guaranteed_seat",
    "repeat_ask",
    "pushed_after_no",
    "sales_close",
)

# ── Facts ─────────────────────────────────────────────────────────

# Any rupee amount, in digits or spelled out the way TTS wants them.
_MONEY = re.compile(
    r"(?:rupees|rs\.?|₹|रुपये|रुपए)\s*([\d,]{3,}|[a-zा-ॿ\s]{4,30}?(?=\s|,|\.|$))",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d[\d,]{2,}")

# Dates in the shapes she would actually say them.
_DATE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|"
    r"august|september|october|november|december))\b|"
    r"\b((?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2})\b",
    re.IGNORECASE,
)


def _fact_corpus(institution) -> str:
    """Everything she is allowed to state, flattened and normalised for
    substring checking."""
    from edu.knowledge import build_knowledge_block

    text = build_knowledge_block(institution).lower()
    return re.sub(r"[,\s]+", " ", text)


def _normalise_number(raw: str) -> str:
    return re.sub(r"[,\s]", "", raw.lower())


def rule_invented_fact(turn: Turn, pack, institution=None) -> list[Violation]:
    """A figure or date she stated that is not in the institution file.

    Digits only, and only groups of three or more, because that is where the
    damage is — fees, deadlines, phone numbers. Small numbers ("two
    instalments", "grade five") are checked by nothing here on purpose: they are
    everywhere in ordinary speech and would drown the signal.

    Known limitation: a number she spelled out in words in Devanagari
    ("ब्याण्णव हजार") will not be caught by the digit path. That is the case for
    reading a sample of Marathi transcripts by hand rather than trusting this
    number, and it is why this checker reports a floor, not a total.
    """
    if institution is None:
        return []
    corpus = _fact_corpus(institution)
    out = []

    for match in _DIGITS.finditer(turn.message):
        value = _normalise_number(match.group(0))
        if len(value) < 3:
            continue
        if value not in _normalise_number(corpus):
            out.append(
                Violation(
                    "invented_fact",
                    f"figure {match.group(0)!r} is not in the institution file",
                    turn.id,
                    turn.session_id,
                    turn.message[:90],
                )
            )

    for match in _DATE.finditer(turn.message):
        stated = (match.group(1) or match.group(2) or "").lower()
        stem = re.sub(r"(st|nd|rd|th)\b", "", stated)
        if stem and stem not in corpus:
            out.append(
                Violation(
                    "invented_fact",
                    f"date {stated!r} is not in the institution file",
                    turn.id,
                    turn.session_id,
                    turn.message[:90],
                )
            )
    return out


# ── Pressure and claims ───────────────────────────────────────────

_PRESSURE = [
    "limited seats", "seats are filling", "filling fast", "hurry",
    "last chance", "only a few", "don't miss", "act now", "closing soon",
    "जल्दी करें", "सीटें कम", "जगा कमी", "मोजक्याच जागा", "शेवटची संधी",
]

_COMPARATIVE = [
    "better than", "best school", "number one", "no. 1", "top school",
    "leading school", "unlike other schools", "compared to other schools",
    "सबसे अच्छा", "नंबर वन", "सर्वोत्तम", "सगळ्यात चांगली",
]

_GUARANTEE = [
    "seat is reserved", "seat is confirmed", "guarantee", "guaranteed admission",
    "i can assure", "definitely get admission", "your seat is",
    "सीट पक्की", "जागा नक्की", "गॅरंटी", "गारंटी",
]

# Closing lines that belong to a salesperson, not a counsellor.
_SALES_CLOSE = [
    "shall i block", "let me block", "i'll reserve", "shall i reserve",
    "just say yes", "trust me", "you won't regret",
]


def _phrase_rule(name: str, phrases: list[str], detail: str):
    def check(turn: Turn, pack, institution=None) -> list[Violation]:
        folded = turn.message.lower()
        for phrase in phrases:
            if phrase in folded:
                return [
                    Violation(name, f"{detail}: {phrase!r}", turn.id,
                              turn.session_id, turn.message[:90])
                ]
        return []

    check.__name__ = f"rule_{name}"
    return check


rule_pressure_language = _phrase_rule(
    "pressure_language", _PRESSURE, "scarcity or urgency language"
)
rule_comparative_claim = _phrase_rule(
    "comparative_claim", _COMPARATIVE, "comparative claim about the institution"
)
rule_guaranteed_seat = _phrase_rule(
    "guaranteed_seat", _GUARANTEE, "implied a seat or outcome she cannot promise"
)
rule_sales_close = _phrase_rule(
    "sales_close", _SALES_CLOSE, "salesperson's close"
)


# ── Session-level ─────────────────────────────────────────────────

# Slot -> the ways she asks for it. Used to catch a second ask after the parent
# has already answered.
_ASK_PATTERNS = {
    "grade": [
        "which class", "which grade", "what class", "which standard",
        "कौन सी कक्षा", "कोणत्या इयत्ते", "कौन सी क्लास",
    ],
    "child_age": [
        "how old", "what is the age", "child's age",
        "कितने साल", "किती वर्ष", "उम्र क्या",
    ],
    "locality": [
        "which area", "where do you live", "which part of",
        "किस इलाके", "कुठल्या भागात", "कहाँ रहते",
    ],
}


def rule_repeat_ask(turns: list[Turn], pack, institution=None) -> list[Violation]:
    """She asked for something the parent had already told her.

    Session-level because the two turns can be far apart — and the further
    apart they are, the worse it sounds. This is the failure the running summary
    in edu/session_manager.py exists to prevent, so a non-zero rate here means
    that summary is not doing its job.
    """
    from edu import qualification

    out: list[Violation] = []
    known: dict = {}
    hints = getattr(pack, "HINTS", {}) or {}
    numerals = getattr(pack, "NUMERALS", {}) or {}
    areas = list(getattr(institution, "catchment_areas", []) or [])
    aliases = dict(getattr(institution, "catchment_aliases", {}) or {})

    for turn in turns:
        if turn.role != "sathi":
            found = qualification.fast_qualify(
                turn.message, "", hints,
                catchment_areas=areas, catchment_aliases=aliases, numerals=numerals,
            )
            qualification.merge(known, found)
            continue

        folded = turn.message.lower()
        for slot, patterns in _ASK_PATTERNS.items():
            if known.get(slot) in (None, "", False):
                continue
            for pattern in patterns:
                if pattern in folded:
                    out.append(
                        Violation(
                            "repeat_ask",
                            f"asked for {slot} again after being told "
                            f"{known[slot]!r}",
                            turn.id, turn.session_id, turn.message[:90],
                        )
                    )
                    break
    return out


_VISIT_OFFER = [
    "come and see", "campus visit", "visit the school", "come and visit",
    "would you like to visit", "शाळा बघायला", "स्कूल देखने", "भेट द्यायला",
]


def rule_pushed_after_no(turns: list[Turn], pack, institution=None) -> list[Violation]:
    """She offered the visit again after it was declined.

    The persona's ceiling is two asks and zero after a refusal. A parent who has
    said no once and is asked twice more remembers the call for the wrong
    reason.
    """
    from edu import qualification

    out: list[Violation] = []
    hints = getattr(pack, "HINTS", {}) or {}
    declined_at: int | None = None

    for index, turn in enumerate(turns):
        if turn.role != "sathi":
            found = qualification.fast_qualify(turn.message, "", hints)
            if found.get("visit_intent") == "declined" and declined_at is None:
                declined_at = index
            continue

        if declined_at is None or index <= declined_at:
            continue

        folded = turn.message.lower()
        if any(phrase in folded for phrase in _VISIT_OFFER):
            out.append(
                Violation(
                    "pushed_after_no",
                    "offered the visit again after it was declined",
                    turn.id, turn.session_id, turn.message[:90],
                )
            )
    return out


EDU_TURN_RULES = (
    rule_invented_fact,
    rule_pressure_language,
    rule_comparative_claim,
    rule_guaranteed_seat,
    rule_sales_close,
)

EDU_SESSION_RULES = (
    rule_repeat_ask,
    rule_pushed_after_no,
)


def check_session_edu(turns: list[Turn], pack, institution=None) -> SessionResult:
    """Base rules plus the education ones, over one call.

    `turns` must be in chronological order, same as the base check_session.
    """
    language = turns[0].language if turns else "?"
    result = SessionResult(
        session_id=turns[0].session_id if turns else "?", language=language
    )

    for turn in turns:
        if turn.role != "sathi":
            continue
        if _is_verbatim_pack_line(turn.message, pack):
            continue
        result.sathi_turns += 1
        for rule in TURN_RULES:
            result.violations.extend(rule(turn, pack))
        for rule in EDU_TURN_RULES:
            result.violations.extend(rule(turn, pack, institution))

    for rule in SESSION_RULES:
        result.violations.extend(rule(turns, pack))
    for rule in EDU_SESSION_RULES:
        result.violations.extend(rule(turns, pack, institution))

    return result


def selftest() -> int:
    """Fire every checker once against text built to trip it.

    The reason this exists is the one stated in tools/prompt_eval: a checker
    that has quietly stopped matching reports zero violations, which is
    indistinguishable from a rule that is passing. Run it after any edit here.

        python -m edu.tools.eval_rules
    """
    import os
    import sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

    from edu.institution import get_institution
    from edu.lang_loader import load_edu_lang_service

    inst = get_institution()
    pack = load_edu_lang_service("en-IN", inst)

    cases = {
        "invented_fact": "The fee for that grade is rupees 47,500 for the year.",
        "pressure_language": "Do come soon, seats are filling fast this month.",
        "comparative_claim": "We are the best school in this part of Pune.",
        "guaranteed_seat": "Your seat is confirmed, I can assure you of that.",
        "sales_close": "Shall I block a seat for you right now?",
    }

    failures = []
    for expected, message in cases.items():
        turn = Turn(id=1, session_id="selftest", role="sathi", message=message,
                    language="en-IN", index=1)
        fired = set()
        for rule in EDU_TURN_RULES:
            for violation in rule(turn, pack, inst):
                fired.add(violation.rule)
        status = "ok " if expected in fired else "FAIL"
        if expected not in fired:
            failures.append(expected)
        print(f"  {status} {expected:<20} fired: {', '.join(sorted(fired)) or '(nothing)'}")

    # Session-level
    convo = [
        Turn(1, "s", "user", "He's in class five.", "en-IN", 0),
        Turn(2, "s", "sathi", "Right, Grade five it is.", "en-IN", 1),
        Turn(3, "s", "user", "We can't come, too far.", "en-IN", 2),
        Turn(4, "s", "sathi", "Which class is he in again?", "en-IN", 3),
        Turn(5, "s", "sathi", "Would you like to visit the school on Saturday?", "en-IN", 4),
    ]
    fired = set()
    for rule in EDU_SESSION_RULES:
        for violation in rule(convo, pack, inst):
            fired.add(violation.rule)
    for expected in ("repeat_ask", "pushed_after_no"):
        status = "ok " if expected in fired else "FAIL"
        if expected not in fired:
            failures.append(expected)
        print(f"  {status} {expected:<20} fired: {', '.join(sorted(fired)) or '(nothing)'}")

    if failures:
        print(f"\n{len(failures)} checker(s) did not fire: {', '.join(failures)}")
        return 1
    print("\nAll checkers fire.")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
