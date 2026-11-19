"""
tools/prompt_eval/selftest.py — do the checkers still detect anything?

    python -m tools.prompt_eval.selftest

This exists because of an asymmetry in the report: a rule that is broken and a
rule that is passing both print 0.0%. Without a fixture that is KNOWN to be a
violation, a regex that stops matching — a renamed constant, a pack that drops
honorific_slips, a changed END_SIGNAL — turns into good news on the dashboard.

Each case is a line the persona explicitly forbids, paired with the rule that
must catch it. Negative cases matter as much: the checkers run over real calls,
and one that fires on ordinary warm speech would send prompt work chasing a
problem that is not there.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.lang import load_lang_service            # noqa: E402
from tools.prompt_eval.rules import Turn, check_session  # noqa: E402


def _turns(lang: str, *pairs) -> list[Turn]:
    """(role, message) pairs -> a chronological session."""
    return [Turn(id=i, session_id="t", role=r, message=m, language=lang, index=i)
            for i, (r, m) in enumerate(pairs)]


# (name, language, turns, rules that MUST fire, rules that must NOT fire)
CASES = [
    ("clean hindi reply", "hi-IN",
     [("user", "आज थोड़ा थका हुआ हूँ"), ("sathi", "हम्म... रात नींद ठीक नहीं हुई क्या?")],
     [], ["too_many_sentences", "too_many_questions", "honorific_slip", "line_breaks"]),

    ("four sentences", "en-IN",
     [("user", "my knee hurts"),
      ("sathi", "That sounds hard. It has been three days. You should rest it. Shall I check tomorrow?")],
     ["too_many_sentences"], []),

    ("ellipsis is not a sentence break", "hi-IN",
     [("user", "बेटे का फ़ोन नहीं आया"), ("sathi", "हम्म... ये बात दिल पर बैठती है।")],
     [], ["too_many_sentences"]),

    ("two questions stacked", "hi-IN",
     [("user", "घुटने में दर्द है"), ("sathi", "ये कब से है? और क्या खाया?")],
     ["too_many_questions"], []),

    ("informal तुम at the patient", "hi-IN",
     [("user", "ठीक हूँ"), ("sathi", "अच्छा, तुम्हें आराम करना चाहिए।")],
     ["honorific_slip"], []),

    ("bullet list and line breaks", "en-IN",
     [("user", "what should I do"), ("sathi", "Try this:\n- warm compress\n- rest")],
     ["line_breaks", "list_formatting"], []),

    ("leaked end signal", "en-IN",
     [("user", "bye"), ("sathi", "Take care of yourself. <<END>>")],
     ["end_signal_leaked"], []),

    ("call-centre register", "en-IN",
     [("user", "hello"), ("sathi", "How may I help you today?")],
     ["helpdesk_phrase"], []),

    ("admits to being an AI", "en-IN",
     [("user", "are you a real person"), ("sathi", "I am an AI assistant.")],
     ["ai_disclosure"], []),

    ("re-greets mid-call", "hi-IN",
     [("user", "हाँ"), ("sathi", "अच्छा।"), ("user", "ठीक है"),
      ("sathi", "नमस्ते, Sathi बोल रही हूँ।")],
     ["reintroduced_herself"], []),

    # The two failures the whole exercise was started for.
    ("kept talking after 'I'm in a meeting'", "hi-IN",
     [("user", "मैं अभी मीटिंग में हूँ, बात नहीं हो सकती"),
      ("sathi", "अरे, गलत वक्त पर फ़ोन कर दिया।"),
      ("user", "हाँ"),
      ("sathi", "अच्छा, एक बात बताइए — नींद कैसी रही?")],
     ["kept_talking_after_unavailable"], []),

    ("one reply after the exit signal is correct", "hi-IN",
     [("user", "मैं अभी मीटिंग में हूँ, बात नहीं हो सकती"),
      ("sathi", "अरे, गलत वक्त पर फ़ोन कर दिया। मैं फिर कभी कर लूँगी।")],
     [], ["kept_talking_after_unavailable"]),

    ("announced the hang-up then carried on", "mr-IN",
     [("user", "बरं"), ("sathi", "ठीक आहे, ठेवते. काळजी घ्या."),
      ("user", "हो"), ("sathi", "आणखी एक विचारते — जेवण झालं का?")],
     ["announced_hangup_then_continued"], []),

    ("same opener three times", "en-IN",
     [("user", "a"), ("sathi", "Hmm. I see."),
      ("user", "b"), ("sathi", "Hmm. That is hard."),
      ("user", "c"), ("sathi", "Hmm. Rest today.")],
     ["repeated_opener"], []),

    ("two different openers is fine", "en-IN",
     [("user", "a"), ("sathi", "Hmm. I see."),
      ("user", "b"), ("sathi", "Hmm. That is hard."),
      ("user", "c"), ("sathi", "That sounds tiring.")],
     [], ["repeated_opener"]),
]


def main() -> int:
    failures = []
    for name, lang, pairs, must_fire, must_not_fire in CASES:
        pack = load_lang_service(lang)
        result = check_session(_turns(lang, *pairs), pack)
        fired = {v.rule for v in result.violations}
        for rule in must_fire:
            if rule not in fired:
                failures.append(f"{name}: expected {rule!r}, got {sorted(fired) or 'nothing'}")
        for rule in must_not_fire:
            if rule in fired:
                failures.append(f"{name}: {rule!r} fired on a line that is fine")

    for f in failures:
        print(f"FAIL  {f}")
    print(f"\n{len(CASES) - len({f.split(':')[0] for f in failures})}"
          f"/{len(CASES)} cases passed")
    if failures:
        print("A failing checker silently reports 0.0% in the report — fix before trusting it.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
