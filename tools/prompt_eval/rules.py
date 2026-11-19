"""
tools/prompt_eval/rules.py — the persona's mechanical rules, as checkers.

Roughly half the persona is already stated as rules a regex can verify: one
question per reply, at most three sentences, no line breaks, no lists, आप never
तुम, let them go the moment they say they cannot talk. Those rules are checked
here, against turns that have already happened. No model is called and nothing
is billed.

The point is not to grade the model. It is to find out WHICH persona rules are
actually broken in production, so that prompt work goes to the rules that are
failing rather than the ones that read worst. A rule with a 0% violation rate
does not need a better example; a rule at 30% does.

Scope, stated plainly:

  * A checker only fires on something unambiguous. Where a rule needs judgement
    ("did she sound like a call-centre agent", "was that the right amount of
    warmth"), there is deliberately no checker here — that is the LLM judge's
    job, and a bad regex would poison the numbers it is meant to inform.
  * Turn-level checkers see one reply. Session-level checkers see the whole
    call, because the most expensive failures — she said goodbye and kept
    talking, they said they were driving and she asked one more question — are
    invisible in a single turn.
  * A checker never fires on a fixed line the model did not write. Greetings,
    EMERGENCY and the recovery lines come from the pack verbatim; counting them
    as violations measures our own constants, not the model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from services.conversation_engine import (
    announced_hangup,
    classify_exit,
    strip_end_signal,
)
from shared.prompts import END_SIGNAL


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    turn_id: int | None = None
    session_id: str | None = None
    excerpt: str = ""


@dataclass
class Turn:
    """One stored conversations row, plus where it sits in the call."""
    id: int
    session_id: str
    role: str
    message: str
    language: str
    index: int                 # 0-based position within the session
    is_last_sathi: bool = False
    prompt_version: str | None = None


# ── helpers ───────────────────────────────────────────────────────────

# Sentence enders across all four packs: Latin, Devanagari danda, ellipsis.
# "..." is her main prosody device ("हम्म... ये तो तकलीफ़ वाली बात है") and is
# NOT a sentence break — counting it as one would report every warm reply as
# over-length. It is collapsed before splitting.
_ELLIPSIS = re.compile(r"\.{2,}|…")
_SENTENCE_END = re.compile(r"[.!?।॥]+")
_QUESTION = re.compile(r"[?？]")

# Bullets, numbering and markdown — "List, नंबरिंग ... नहीं। ये बोली है, लिखाई नहीं।"
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_MARKDOWN = re.compile(r"\*\*|__|^#{1,6}\s|`", re.MULTILINE)


def sentences(text: str) -> list[str]:
    flat = _ELLIPSIS.sub(" ", text or "")
    return [s.strip() for s in _SENTENCE_END.split(flat) if s.strip()]


def _has_emoji(text: str) -> bool:
    return any(unicodedata.category(ch) == "So" for ch in text or "")


def _is_verbatim_pack_line(text: str, pack) -> bool:
    """
    True when this reply is a fixed line from the pack, not model output.

    Greetings, the emergency script and the two recovery lines are spoken
    verbatim. They are written to their own rules and measuring them tells us
    about our constants, not about the prompt.
    """
    stripped = (text or "").strip()
    if not stripped:
        return True
    templates = [getattr(pack, n, "") for n in
                 ("EMERGENCY", "FALLBACK", "STILL_THERE", "GREETING", "CLOSING")]
    templates += list(getattr(pack.personality, "_GREETINGS", {}).values() if
                      hasattr(pack, "personality") else [])
    for t in templates:
        if isinstance(t, list):
            continue
        if not t:
            continue
        # Templates carry {name}; compare the parts around it.
        head = t.split("{name}")[0].strip()
        if head and len(head) > 8 and stripped.startswith(head):
            return True
        if stripped == t.strip():
            return True
    return False


# ── turn-level checkers ───────────────────────────────────────────────
#
# Each takes (turn, pack) and returns a list of Violation. Registered in
# TURN_RULES at the bottom; the report iterates that, so adding a rule is one
# function plus one line.


def rule_line_breaks(turn: Turn, pack) -> list[Violation]:
    """"सब कुछ एक ही line में। कोई line break नहीं।" — this is a TTS rule."""
    if "\n" in turn.message:
        return [Violation("line_breaks",
                          f"{turn.message.count(chr(10))} line break(s)",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


def rule_sentence_count(turn: Turn, pack) -> list[Violation]:
    """"दो छोटे वाक्य — यही निशाना है। तीन से ज़्यादा कभी नहीं।" """
    n = len(sentences(turn.message))
    if n > 3:
        return [Violation("too_many_sentences", f"{n} sentences (max 3)",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


def rule_question_count(turn: Turn, pack) -> list[Violation]:
    """"पूरे जवाब में एक ही सवाल, उससे ज़्यादा नहीं।" """
    n = len(_QUESTION.findall(turn.message))
    if n > 1:
        return [Violation("too_many_questions", f"{n} questions (max 1)",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


def rule_formatting(turn: Turn, pack) -> list[Violation]:
    """"कोई bullet नहीं, कोई emoji नहीं" — none of this survives TTS."""
    out = []
    if _LIST_MARKER.search(turn.message):
        out.append(Violation("list_formatting", "bullet or numbered list",
                             turn.id, turn.session_id, turn.message[:90]))
    if _MARKDOWN.search(turn.message):
        out.append(Violation("markdown", "markdown syntax in a spoken line",
                             turn.id, turn.session_id, turn.message[:90]))
    if _has_emoji(turn.message):
        out.append(Violation("emoji", "emoji in a spoken line",
                             turn.id, turn.session_id, turn.message[:90]))
    return out


def rule_honorifics(turn: Turn, pack) -> list[Violation]:
    """
    आप only, never तुम. Hindi and Marathi packs only — the others have no
    T–V distinction to get wrong, and English/Spanish export no checker.

    Note this runs on the STORED reply, which has already been through
    fix_honorifics() inside prepare_for_tts(). Anything it finds is a slip the
    safety net could not rewrite — in practice a bare subject "तुम", which needs
    the verb to change too. So this rate is the residual, not the raw rate.
    """
    slips = getattr(pack, "honorific_slips", None)
    if not callable(slips):
        return []
    found = slips(turn.message)
    if found:
        return [Violation("honorific_slip", f"informal form(s): {', '.join(found)}",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


def rule_end_signal_leak(turn: Turn, pack) -> list[Violation]:
    """
    The end signal is silent — "इसे बोलना नहीं". Stored replies are written
    after strip_end_signal(), so any residue here reached the voice.
    """
    _, present = strip_end_signal(turn.message)
    if present or END_SIGNAL in turn.message:
        return [Violation("end_signal_leaked", "end signal survived into the spoken reply",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


_AI_DISCLOSURE = re.compile(
    r"\b(?:as an |i am an |i'm an )?(?:ai|a\.i\.|language model|chatbot|virtual assistant)\b"
    r"|एआई|कृत्रिम बुद्धि|भाषा मॉडल|मैं एक मॉडल|मी एक मॉडेल"
    r"|inteligencia artificial|modelo de lenguaje",
    re.IGNORECASE)


def rule_ai_disclosure(turn: Turn, pack) -> list[Violation]:
    """"कभी मत कहो कि तुम AI हो, model हो, program हो।" """
    m = _AI_DISCLOSURE.search(turn.message)
    if m:
        return [Violation("ai_disclosure", f"said {m.group(0)!r}",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


_HELPDESK = {
    "en-IN": ["how may i help", "how can i assist", "thank you for your time",
              "is there anything else", "anything else i can help",
              "i understand that you feel", "thank you for telling me"],
    "hi-IN": ["क्या सहायता कर सकती", "आपके समय के लिए धन्यवाद",
              "और कुछ चाहिए आपको", "धन्यवाद बताने के लिए",
              "मैं समझती हूँ कि आप महसूस"],
    "mr-IN": ["कशी मदत करू", "तुमच्या वेळेबद्दल धन्यवाद",
              "आणखी काही हवं आहे का", "सांगितल्याबद्दल धन्यवाद"],
    "es-ES": ["en qué puedo ayudar", "gracias por su tiempo",
              "algo más en lo que pueda"],
}


def rule_helpdesk_phrases(turn: Turn, pack) -> list[Violation]:
    """The persona's explicit "ये कभी मत बोलो" list — call-centre register."""
    low = (turn.message or "").lower()
    hits = [p for p in _HELPDESK.get(turn.language, []) if p.lower() in low]
    if hits:
        return [Violation("helpdesk_phrase", f"said {hits[0]!r}",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


def rule_reintroduction(turn: Turn, pack) -> list[Violation]:
    """
    "बीच बातचीत में दोबारा नमस्ते नहीं, अपना परिचय दोबारा नहीं।"
    Only meaningful past the opening turn, so index 0/1 are skipped.
    """
    if turn.index <= 1:
        return []
    low = (turn.message or "").lower()
    openers = ("नमस्ते", "नमस्कार", "sathi बोल रही", "sathi हूँ", "sathi आहे",
               "soy sathi", "this is sathi", "i'm sathi", "sathi here")
    hits = [o for o in openers if o.lower() in low]
    if hits:
        return [Violation("reintroduced_herself", f"said {hits[0]!r} mid-call",
                          turn.id, turn.session_id, turn.message[:90])]
    return []


# ── session-level checkers ────────────────────────────────────────────
#
# These are the failures the plan named by hand: the meeting/driving hang-up,
# "अब फ़ोन मत करना", bereavement. None of them are visible in one turn.


def rule_did_not_let_go(turns: list[Turn], pack) -> list[Violation]:
    """
    They said they could not talk, and the call carried on anyway.

    classify_exit() is the same function the live call loop uses, so this
    measures the deployed rule rather than a re-statement of it. One reply after
    the exit signal is correct and expected — "अरे, गलत वक्त पर फ़ोन कर दिया" —
    so only a SECOND sathi turn counts as a violation.
    """
    out = []
    sathi_after = 0
    triggered_at = None
    reason = None
    for t in turns:
        if t.role == "user":
            if triggered_at is None:
                r = classify_exit(t.message, pack)
                if r:
                    triggered_at, reason = t.index, r
            continue
        if triggered_at is not None and t.index > triggered_at:
            sathi_after += 1
            if sathi_after == 2:
                out.append(Violation(
                    f"kept_talking_after_{reason}",
                    f"caller signalled {reason!r} at turn {triggered_at}; "
                    f"she replied {sathi_after}+ more times",
                    t.id, t.session_id, t.message[:90]))
    return out


def rule_hangup_not_honoured(turns: list[Turn], pack) -> list[Violation]:
    """
    She said, in words, that she was hanging up — and then did not.

    announced_hangup() is the live safety net under END_SIGNAL. If it fires on a
    reply that is not the last of the call, the net did not hold that day.
    """
    out = []
    sathi = [t for t in turns if t.role == "sathi"]
    for i, t in enumerate(sathi[:-1]):
        if announced_hangup(t.message, pack):
            out.append(Violation(
                "announced_hangup_then_continued",
                f"said goodbye with {len(sathi) - i - 1} sathi turn(s) still to come",
                t.id, t.session_id, t.message[:90]))
    return out


def rule_repeated_opener(turns: list[Turn], pack) -> list[Violation]:
    """
    "हर जवाब एक ही शब्द से शुरू मत करो।" Three or more replies in one call
    opening on the same word is the tic this rule exists to prevent.
    """
    from collections import Counter
    firsts = Counter()
    where: dict[str, Turn] = {}
    for t in turns:
        if t.role != "sathi":
            continue
        words = re.sub(r"[^\w\sऀ-ॿ]", " ", t.message or "").split()
        if not words:
            continue
        w = words[0].lower()
        firsts[w] += 1
        where.setdefault(w, t)
    out = []
    for word, n in firsts.items():
        if n >= 3:
            t = where[word]
            out.append(Violation("repeated_opener",
                                 f"{n} replies open with {word!r}",
                                 t.id, t.session_id, t.message[:90]))
    return out


TURN_RULES = (
    rule_line_breaks,
    rule_sentence_count,
    rule_question_count,
    rule_formatting,
    rule_honorifics,
    rule_end_signal_leak,
    rule_ai_disclosure,
    rule_helpdesk_phrases,
    rule_reintroduction,
)

SESSION_RULES = (
    rule_did_not_let_go,
    rule_hangup_not_honoured,
    rule_repeated_opener,
)

# Every rule name a checker can emit, so the report can show 0% for rules that
# never fired rather than silently omitting them — a rule missing from the
# output is indistinguishable from a rule that passed, and that is the whole
# question this tool exists to answer.
ALL_RULE_NAMES = (
    "line_breaks", "too_many_sentences", "too_many_questions",
    "list_formatting", "markdown", "emoji", "honorific_slip",
    "end_signal_leaked", "ai_disclosure", "helpdesk_phrase",
    "reintroduced_herself",
    "kept_talking_after_unavailable", "kept_talking_after_declined",
    "kept_talking_after_wrong_person", "kept_talking_after_bereavement",
    "kept_talking_after_goodbye",
    "announced_hangup_then_continued", "repeated_opener",
)


@dataclass
class SessionResult:
    session_id: str
    language: str
    sathi_turns: int = 0
    violations: list[Violation] = field(default_factory=list)


def check_session(turns: list[Turn], pack) -> SessionResult:
    """Run every rule over one call. `turns` must be in chronological order."""
    language = turns[0].language if turns else "?"
    result = SessionResult(session_id=turns[0].session_id if turns else "?",
                           language=language)
    for t in turns:
        if t.role != "sathi":
            continue
        if _is_verbatim_pack_line(t.message, pack):
            continue
        result.sathi_turns += 1
        for rule in TURN_RULES:
            result.violations.extend(rule(t, pack))
    for rule in SESSION_RULES:
        result.violations.extend(rule(turns, pack))
    return result
