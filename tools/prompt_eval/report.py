"""
tools/prompt_eval/report.py — which persona rules are actually being broken?

    python -m tools.prompt_eval.report
    python -m tools.prompt_eval.report --lang en-IN --examples 3
    python -m tools.prompt_eval.report --since 2026-07-01 --csv out.csv

Runs tools/prompt_eval/rules.py over the historical `conversations` table and
prints a violation rate per rule, per language. Reads only; no API calls, no
cost, safe to run against production.

Read the output as a work queue, not a scorecard. A rule at 0% does not need a
better few-shot example. A rule at 30% is where prompt work pays.

Language attribution: rows written before conversations.language existed have
it NULL, and those fall back to the user's language as it is TODAY. That is a
guess, and it is wrong for anyone who has ever switched language — the count of
guessed rows is printed so the number can be discounted honestly. Rows written
from here on carry their own language and prompt_version.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

from colorama import Fore, Style
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.db_engine import get_session_factory          # noqa: E402
from core.models import Conversation, User              # noqa: E402
from shared.lang import load_lang_service               # noqa: E402
from tools.prompt_eval.rules import (                   # noqa: E402
    ALL_RULE_NAMES, Turn, check_session,
)


# ── language attribution for rows written before conversations.language ──
#
# users.language is the caller's language TODAY, which on this data is wrong for
# most rows: the seeded user reads en-IN while the stored turns are visibly
# Hindi and Marathi. Believing it means the honorific checker — which only
# exists for Hindi and Marathi — never runs on the turns it was written for, and
# the whole per-language split is fiction.
#
# So legacy rows get their language read off the text instead. Script settles
# Devanagari vs Latin; the marker words below settle Hindi vs Marathi, and are
# chosen to be common and unambiguous rather than clever. This is a heuristic
# for old rows only — anything written from now on carries its own language.

_MARATHI_MARKERS = ("आहे", "नाही", "तुम्ही", "काळजी", "झोप", "जेवण",
                    "बरं", "ठेवते", "कसं", "छान", "होतं", "आहात")
_HINDI_MARKERS = ("हूँ", "हूं", "है", "नहीं", "आपको", "रखिए", "क्या",
                  "रही", "लग रहा", "कीजिए", "हुआ", "बताइए")
_SPANISH_MARKERS = ("¿", "está", "cómo", "señor", "gracias", "usted", "siente")


def infer_language(text: str, fallback: str) -> tuple[str, bool]:
    """
    Guess a turn's language from its text. Returns (code, was_inferred).

    Falls back to `fallback` when the text carries no signal — a bare "हाँ" or
    "ok" is not enough to attribute, and guessing on it would be noise.
    """
    t = text or ""
    devanagari = sum(1 for ch in t if "ऀ" <= ch <= "ॿ")
    if devanagari >= 3:
        mr = sum(t.count(m) for m in _MARATHI_MARKERS)
        hi = sum(t.count(m) for m in _HINDI_MARKERS)
        if mr > hi:
            return "mr-IN", True
        if hi > mr:
            return "hi-IN", True
        return fallback if fallback in ("hi-IN", "mr-IN") else "hi-IN", True
    low = t.lower()
    if sum(low.count(m) for m in _SPANISH_MARKERS) >= 2:
        return "es-ES", True
    return fallback, False


def _session_language(messages: list[str], fallback: str) -> tuple[str, bool]:
    """
    One language for the whole call, by majority vote over its turns.

    Per-turn inference alone would split a single call across packs the moment
    the caller said "ok" in English, and the session-level rules need all the
    turns of a call under one pack to mean anything.
    """
    votes: Counter[str] = Counter()
    inferred_any = False
    for m in messages:
        code, inferred = infer_language(m, fallback)
        if inferred:
            votes[code] += 1
            inferred_any = True
    if not votes:
        return fallback, False
    return votes.most_common(1)[0][0], inferred_any


def load_turns(since: str | None = None, only_lang: str | None = None,
               trust_stored_only: bool = False):
    """
    Every stored turn, grouped by session and ordered within it.

    Returns (sessions, guessed_language_rows) where sessions is
    {session_id: [Turn, ...]}.
    """
    guessed = 0
    with get_session_factory()() as s:
        user_lang = dict(s.execute(select(User.id, User.language)).all())
        stmt = select(Conversation).order_by(
            Conversation.session_id, Conversation.created_at.asc(), Conversation.id.asc()
        )
        if since:
            stmt = stmt.where(Conversation.created_at >= since)
        rows = s.scalars(stmt).all()

        by_session: dict[str, list] = defaultdict(list)
        for r in rows:
            by_session[r.session_id].append(r)

        sessions: dict[str, list[Turn]] = defaultdict(list)
        for session_id, session_rows in by_session.items():
            stored = next((r.language for r in session_rows if r.language), None)
            if stored:
                lang, inferred = stored, False
            else:
                fallback = user_lang.get(session_rows[0].user_id) or "en-IN"
                if trust_stored_only:
                    lang, inferred = fallback, False
                else:
                    lang, inferred = _session_language(
                        [r.message or "" for r in session_rows], fallback)
                guessed += len(session_rows)
                if not inferred:
                    lang = fallback

            if only_lang and lang != only_lang:
                continue
            for i, r in enumerate(session_rows):
                sessions[session_id].append(Turn(
                    id=r.id, session_id=session_id, role=r.role,
                    message=r.message or "", language=lang,
                    index=i, prompt_version=r.prompt_version,
                ))
    return sessions, guessed


def run(since=None, only_lang=None, examples=2, csv_path=None,
        trust_stored_only=False) -> int:
    sessions, guessed = load_turns(since, only_lang, trust_stored_only)
    if not sessions:
        print("No conversations matched.")
        return 1

    # denominators: turn rules are per sathi turn, session rules per session
    turns_by_lang: Counter[str] = Counter()
    sessions_by_lang: Counter[str] = Counter()
    hits: dict[str, Counter[str]] = defaultdict(Counter)
    # Session-scoped rules can fire more than once in one call (three different
    # repeated openers is three violations of one rule), so the numerator for
    # their rate is calls affected, not violations counted.
    calls_affected: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[tuple[str, str], list] = defaultdict(list)
    all_rows = []

    _SESSION_SCOPED = ("kept_talking_after_", "announced_hangup_then_continued",
                       "repeated_opener")

    def is_session_rule(name: str) -> bool:
        return name.startswith(_SESSION_SCOPED)

    for session_id, turns in sessions.items():
        lang = turns[0].language
        pack = load_lang_service(lang)
        res = check_session(turns, pack)
        turns_by_lang[lang] += res.sathi_turns
        sessions_by_lang[lang] += 1
        seen_here = set()
        for v in res.violations:
            hits[lang][v.rule] += 1
            if v.rule not in seen_here:
                seen_here.add(v.rule)
                calls_affected[lang][v.rule] += 1
            if len(samples[(lang, v.rule)]) < examples:
                samples[(lang, v.rule)].append(v)
            all_rows.append({
                "language": lang, "session_id": session_id, "turn_id": v.turn_id,
                "rule": v.rule, "detail": v.detail, "excerpt": v.excerpt,
            })

    print(f"\n{Fore.CYAN}Persona rule violations — deterministic checks only"
          f"{Style.RESET_ALL}")
    print(f"{'='*74}")
    for lang in sorted(turns_by_lang):
        n_turns, n_sessions = turns_by_lang[lang], sessions_by_lang[lang]
        print(f"\n  {Fore.CYAN}{lang}{Style.RESET_ALL}  "
              f"{n_sessions} calls / {n_turns} model-written replies")
        print(f"  {'rule':<34} {'hits':>5} {'rate':>7}   scope")
        print(f"  {'-'*34} {'-'*5} {'-'*7}   {'-'*7}")
        for rule in ALL_RULE_NAMES:
            n = hits[lang][rule]
            session_scoped = is_session_rule(rule)
            if session_scoped:
                numer, denom = calls_affected[lang][rule], n_sessions
            else:
                numer, denom = n, n_turns
            rate = (numer / denom * 100) if denom else 0.0
            if n == 0:
                colour = Fore.GREEN
            elif rate >= 10:
                colour = Fore.RED
            else:
                colour = Fore.YELLOW
            print(f"  {rule:<34} {colour}{n:>5} {rate:>6.1f}%{Style.RESET_ALL}"
                  f"   {'call' if session_scoped else 'reply'}")
            for v in samples[(lang, rule)]:
                print(f"      {Fore.WHITE}· {v.detail}{Style.RESET_ALL}")
                if v.excerpt:
                    print(f"        {v.excerpt!r}")

    if guessed:
        how = ("the user's current language"
               if trust_stored_only else
               "the text itself (script + marker words), per call")
        print(f"\n  {Fore.YELLOW}note:{Style.RESET_ALL} {guessed} rows predate "
              f"conversations.language; their language was inferred from\n"
              f"        {how}. Treat per-language splits on those as indicative.\n"
              f"        Rows written from now on carry their own language and "
              f"prompt_version.")

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "language", "session_id", "turn_id", "rule", "detail", "excerpt"])
            w.writeheader()
            w.writerows(all_rows)
        print(f"\n  wrote {len(all_rows)} violations to {csv_path}")

    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--lang", help="restrict to one BCP-47 code, e.g. en-IN")
    ap.add_argument("--since", help="ISO date, e.g. 2026-07-01")
    ap.add_argument("--examples", type=int, default=2,
                    help="offending excerpts to print per rule (default 2)")
    ap.add_argument("--csv", dest="csv_path", help="also write every violation to this file")
    ap.add_argument("--trust-stored-only", action="store_true",
                    help="do not infer language for legacy rows; use users.language "
                         "(shows how misattributed the pre-migration data is)")
    a = ap.parse_args()
    return run(a.since, a.lang, a.examples, a.csv_path, a.trust_stored_only)


if __name__ == "__main__":
    raise SystemExit(main())
