"""
edu/qualification.py — the education analogue of core/extractor.py.

Saathicare already solved this problem in a different costume. `fast_extract()`
plus `should_steer()` collect a set of named slots across a free-flowing
conversation, without a checklist, deciding turn by turn whether to nudge
toward one that is still missing. Rename the slots and that is lead
qualification. This module keeps the shape and the timing rules and swaps the
slot set, because the shape is the valuable part.

Two things here are genuinely different from the health version, and both come
from the difference in who called whom:

1. ANSWER-FIRST. Saathicare rings a lonely person and gently steers toward the
   topics it needs. An admissions call is one where the parent has questions,
   and steering over an unanswered question is the single most irritating thing
   this agent can do. So `should_steer()` refuses to steer on any turn where
   the parent asked something.

2. NO SLOT IS WORTH THE CALL. In health, a missed vital means a missed alert.
   Here, a parent who never says which area they live in is still a good lead.
   Steering is capped and gives up early rather than becoming an interrogation.
"""

from __future__ import annotations

import re

# ── Slots ─────────────────────────────────────────────────────────
# Ordered by how much each one changes what the school does next.
SLOTS = (
    "grade",           # which class/grade the child is going into
    "child_age",
    "locality",        # where the family lives — drives transport and fit
    "intake",          # which academic year / how soon
    "board_pref",      # CBSE / ICSE / State / IB
    "boarding",        # day scholar vs hostel
    "decision_stage",  # exploring | comparing | ready
    "fee_concern",     # they raised cost as an issue
    "visit_intent",    # would come to campus
    "callback_time",   # when to ring back
)

# The ones that decide whether this is a lead a counsellor should pick up.
CRITICAL_SLOTS = ["grade", "child_age", "locality", "intake", "visit_intent"]

# Steering priority. Grade first because every other answer depends on it —
# fees, eligibility and timings are all per-grade, so a call that never
# establishes the grade gives vague answers to everything.
STEER_PRIORITY = [
    "grade",
    "intake",
    "locality",
    "child_age",
    "visit_intent",
]

# Slots worth one gentle nudge but never worth chasing.
SOFT_SLOTS = {"board_pref", "boarding", "decision_stage", "fee_concern", "callback_time"}


# ── Numerals ──────────────────────────────────────────────────────
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
}

# Pre-primary grades, which have no number at all and are the most common
# admission enquiry a school gets.
_PRE_PRIMARY = {
    "nursery": "Nursery", "playgroup": "Playgroup", "play group": "Playgroup",
    "pre-kg": "Pre-KG", "prekg": "Pre-KG", "pre kg": "Pre-KG",
    "lkg": "LKG", "l k g": "LKG", "junior kg": "LKG", "jr kg": "LKG",
    "ukg": "UKG", "u k g": "UKG", "senior kg": "UKG", "sr kg": "UKG",
    "kindergarten": "LKG",
}

_GRADE_WORDS = r"(?:class|classes|std|standard|grade|इयत्ता|इयत्तेत|कक्षा|क्लास)"

# "class 5", "grade 5", "इयत्ता ५", "कक्षा 5"
_GRADE_NUM = re.compile(_GRADE_WORDS + r"\s*(?:number\s*)?(\d{1,2})\b", re.IGNORECASE)
# "5th class", "5 वी", "10th"
_ORDINAL_GRADE = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th|वी|वीं|वि)\b(?:\s*" + _GRADE_WORDS + r")?",
    re.IGNORECASE,
)
# "class five"
_GRADE_WORD_NUM = re.compile(
    _GRADE_WORDS + r"\s+(" + "|".join(_WORD_NUMBERS) + r")\b", re.IGNORECASE
)

_AGE = re.compile(
    r"\b(\d{1,2})\s*(?:years?|yrs?|year-old|साल|वर्ष|वर्षाचा|वर्षाची|वर्षांचा|वर्षांची)\b",
    re.IGNORECASE,
)
_AGE_WORD = re.compile(
    r"\b(" + "|".join(k for k in _WORD_NUMBERS if len(k) > 3) + r")\s*(?:years?|yrs?)\s*old\b",
    re.IGNORECASE,
)

# Just the unit, for the language-word path below. Devanagari age words inflect
# heavily (वर्षांचा / वर्षांची / वर्षाचा / साल का), so this matches the stem.
_AGE_UNIT = re.compile(r"(?:years?|yrs?|वर्ष|वरष|साल)", re.IGNORECASE)

_BOARDS = {
    "cbse": "CBSE", "c b s e": "CBSE",
    "icse": "ICSE", "i c s e": "ICSE", "cisce": "ICSE",
    "ib": "IB", "international baccalaureate": "IB",
    "igcse": "IGCSE", "cambridge": "IGCSE",
    "state board": "State", "ssc": "State", "hsc": "State",
    "राज्य मंडळ": "State", "स्टेट बोर्ड": "State",
}


def _fold(text: str) -> str:
    return (text or "").translate(_DEVA_DIGITS).lower().strip()


# ── Extraction ────────────────────────────────────────────────────


def _grade(text: str, numerals: dict | None = None) -> str | None:
    folded = _fold(text)
    for phrase, label in _PRE_PRIMARY.items():
        if phrase in folded:
            return label

    # Language-supplied ordinals: "पाचवीची", "दसवीं". These are the ordinary way
    # to name a class in Hindi and Marathi, and they carry case suffixes, so
    # they are matched as substrings and longest-first — "बारावी" must win over
    # "दुसरी" inside "बारावीच्या", and a short entry matched first would
    # mis-read it.
    ordinals = (numerals or {}).get("ordinals") or {}
    for phrase in sorted(ordinals, key=len, reverse=True):
        if _fold(phrase) in folded:
            return _grade_label(ordinals[phrase])

    m = _GRADE_NUM.search(folded)
    if m:
        return _grade_label(m.group(1))

    m = _GRADE_WORD_NUM.search(folded)
    if m:
        return _grade_label(_WORD_NUMBERS[m.group(1).lower()])

    # Bare ordinal only counts next to a grade word or on its own in a short
    # utterance — "10th" in a long sentence is as likely to be a date.
    m = _ORDINAL_GRADE.search(folded)
    if m and (len(folded.split()) <= 8 or re.search(_GRADE_WORDS, folded, re.IGNORECASE)):
        return _grade_label(m.group(1))
    return None


def _grade_label(n) -> str | None:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return f"Grade {n}" if 1 <= n <= 12 else None


def _age(text: str, numerals: dict | None = None) -> int | None:
    folded = _fold(text)
    m = _AGE.search(folded)
    if m:
        age = int(m.group(1))
        return age if 2 <= age <= 25 else None
    m = _AGE_WORD.search(folded)
    if m:
        age = _WORD_NUMBERS.get(m.group(1).lower())
        return age if age and 2 <= age <= 25 else None

    # Language-supplied number words next to an age unit: "नऊ वर्षांचा".
    # Requires the unit to be present, because a bare "नऊ" in a sentence is far
    # more likely to be a fee, a time or a grade than an age.
    numbers = (numerals or {}).get("numbers") or {}
    if numbers and _AGE_UNIT.search(folded):
        for word in sorted(numbers, key=len, reverse=True):
            if _fold(word) in folded:
                age = numbers[word]
                return age if 2 <= age <= 25 else None
    return None


def _board(text: str) -> str | None:
    folded = _fold(text)
    for phrase, label in _BOARDS.items():
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", folded):
            return label
    return None


def _locality(text: str, areas: list[str], aliases: dict | None = None) -> str | None:
    """Where the family lives.

    Matched against the institution's own catchment list rather than a language
    pack, because "Kothrud" is only a meaningful answer next to a school that
    serves Kothrud. A generic place-name extractor would fire on every mention
    of anywhere.

    Aliases exist because a Marathi caller says कोथरूड, not Kothrud, and the
    two share no characters — a Latin catchment list matches nothing at all on
    a Devanagari transcript. Rather than transliterate (which gets Indian place
    names wrong often enough to matter), the institution file carries the
    spellings its own callers actually use. Case suffixes are handled by
    substring matching: कोथरूडला contains कोथरूड.
    """
    folded = _fold(text)
    aliases = aliases or {}
    for area in areas or []:
        candidates = [area] + list(aliases.get(area, []))
        for candidate in candidates:
            c = _fold(candidate)
            if c and c in folded:
                return area
    return None


def _hint_hit(text: str, hints: dict, key: str) -> bool:
    folded = _fold(text)
    for phrase in hints.get(key, []) or []:
        p = _fold(phrase)
        if p and p in folded:
            return True
    return False


def fast_qualify(
    user_text: str,
    agent_text: str,
    hints: dict,
    catchment_areas: list[str] | None = None,
    catchment_aliases: dict | None = None,
    numerals: dict | None = None,
) -> dict:
    """One turn's worth of slot extraction. No API call, no latency.

    Scans the parent's words for everything. Scans the agent's words only for
    the visit confirmation, because "shall I put you down for Saturday at
    eleven" is hers, and the parent's "yes" carries no content on its own.
    """
    hints = hints or {}
    found: dict = {}

    # Maîtria: métier and firm size live in the same slot names the rest of
    # the pipeline already reads (grade / child_age). Hint keys take priority
    # so "12 mètres" never becomes Grade 12.
    if _hint_hit(user_text, hints, "metier_architecte"):
        found["grade"] = "architecte / MOE"
    elif _hint_hit(user_text, hints, "metier_vendeur"):
        found["grade"] = "vendeur sur-mesure"
    else:
        grade = _grade(user_text, numerals)
        if grade:
            found["grade"] = grade

    if _hint_hit(user_text, hints, "team_solo"):
        found["child_age"] = "solo"
    elif _hint_hit(user_text, hints, "team_cabinet"):
        found["child_age"] = "cabinet"
    elif _hint_hit(user_text, hints, "team_agence"):
        found["child_age"] = "agence"
    elif not any(hints.get(k) for k in ("metier_architecte", "metier_vendeur")):
        age = _age(user_text, numerals)
        if age:
            found["child_age"] = age

    area = _locality(user_text, catchment_areas or [], catchment_aliases)
    if area:
        found["locality"] = area

    if _hint_hit(user_text, hints, "product_reglementation"):
        found["board_pref"] = "analyse réglementaire"
    elif _hint_hit(user_text, hints, "product_configurateur"):
        found["board_pref"] = "configurateur"
    else:
        board = _board(user_text)
        if board:
            found["board_pref"] = board

    if _hint_hit(user_text, hints, "boarding_yes"):
        found["boarding"] = "hostel"
    elif _hint_hit(user_text, hints, "boarding_no"):
        found["boarding"] = "day"

    if _hint_hit(user_text, hints, "intake_now"):
        found["intake"] = "this year"
    elif _hint_hit(user_text, hints, "intake_next"):
        found["intake"] = "next year"

    if _hint_hit(user_text, hints, "stage_ready"):
        found["decision_stage"] = "ready"
    elif _hint_hit(user_text, hints, "stage_comparing"):
        found["decision_stage"] = "comparing"
    elif _hint_hit(user_text, hints, "stage_exploring"):
        found["decision_stage"] = "exploring"

    if _hint_hit(user_text, hints, "fee_concern"):
        found["fee_concern"] = True

    # Visit intent is the one slot where a false positive is expensive — a lead
    # marked "visit booked" that was never booked wastes a counsellor's morning.
    # So it needs the parent to have agreed, not merely to have been asked.
    if _hint_hit(user_text, hints, "visit_no"):
        found["visit_intent"] = "declined"
    elif _hint_hit(user_text, hints, "visit_yes"):
        found["visit_intent"] = "yes"

    if _hint_hit(user_text, hints, "callback"):
        found["callback_time"] = "requested"

    return found


def merge(extracted: dict, new: dict) -> dict:
    """First answer wins, exactly as core/extractor does.

    One exception: visit_intent may be upgraded from declined to yes and back.
    A parent who says "not this week" and then "actually Saturday works" has
    changed their mind, and the later answer is the true one.
    """
    for key, val in (new or {}).items():
        if val is None or val is False:
            continue
        if key == "visit_intent":
            extracted[key] = val
        elif extracted.get(key) in (None, "", False):
            extracted[key] = val
    return extracted


# ── Did the parent ask something? ─────────────────────────────────


def parent_asked_question(text: str, hints: dict) -> bool:
    """Whether this turn contains a question that is still owed an answer.

    Phone STT rarely returns a question mark, so this reads interrogative cues
    from the language pack instead. Erring toward True is the safe direction:
    the only cost is one turn without a nudge.
    """
    if not (text or "").strip():
        return False
    if "?" in text:
        return True
    return _hint_hit(text, hints or {}, "question_cues")


# ── Steering ──────────────────────────────────────────────────────


# Only qualification nudges count against the steer cap. The visit ask and the
# closing are wind-down moves — they are the point of the call, not an
# interruption of it, and counting them made an ordinary ending look like an
# interrogation in the smoke report.
NON_STEER_TOPICS = {"closing", "visit_intent"}


def coverage(extracted: dict) -> dict:
    """How much of the critical set is filled — used for lead scoring."""
    have = [s for s in CRITICAL_SLOTS if extracted.get(s) not in (None, "", False)]
    return {
        "have": have,
        "missing": [s for s in CRITICAL_SLOTS if s not in have],
        "ratio": len(have) / len(CRITICAL_SLOTS),
    }


def should_steer(
    turn_number: int,
    extracted: dict,
    wrap_up_from: int = 20,
    asked_question: bool = False,
    steers_used: int = 0,
    max_steers: int = 5,
) -> tuple[bool, str | None]:
    """Whether to nudge toward a missing slot, and which one.

    Rules, in order:
      - Turns 1-2: never. Let them ask what they rang about.
      - Any turn where the parent asked something: never. Answer them.
      - Past max_steers: never. It has become an interview.
      - From wrap_up_from: steer to the visit, then to closing.
      - Otherwise: the highest-priority critical slot still empty.
    """
    if turn_number <= 2:
        return False, None

    if turn_number >= wrap_up_from:
        if extracted.get("visit_intent") in (None, "", False):
            return True, "visit_intent"
        return True, "closing"

    if asked_question:
        return False, None

    if steers_used >= max_steers:
        return False, None

    for slot in STEER_PRIORITY:
        if extracted.get(slot) in (None, "", False):
            # The visit ask is not a qualification nudge; it belongs to the
            # wind-down, and asking for it on turn 4 is exactly the pushy
            # behaviour the persona forbids.
            if slot == "visit_intent" and turn_number < wrap_up_from - 4:
                continue
            return True, slot

    return False, None
