"""
edu/pack_factory.py — assembles a language pack that the existing engine can use.

`services/conversation_engine.py`, `telephony/session.py` and
`services/session_manager.py` duck-type the language pack: they reach for
GREETING, EXIT_WORDS, prepare_for_tts, build_system_blocks and about twenty
other names. An education pack that exposes the same names drops straight in
with no change to any of them. That is the whole integration story — see
edu/INTEGRATION.md.

What this factory is really for
-------------------------------
The recommendation that came out of reading Saathicare was to split each
language pack in two: language mechanics on one side, domain persona on the
other. This is that split, made executable.

  - Domain persona (edu/persona.py)  — one copy, shared by every language.
  - Language mechanics (edu/packs/*) — script, honorifics, voice, word lists.
  - Institution facts (edu/knowledge.py) — one copy, English, per institution.

Three languages therefore cost three small spec files instead of three
700-line personality modules, and a fix to objection handling lands in all
three at once.

Reuse of the Saathicare packs is deliberate
-------------------------------------------
EXIT_WORDS, UNAVAILABLE_WORDS, DECLINE_WORDS, WRONG_PERSON_WORDS,
TRAILING_PARTICLES, SELF_EXIT_WORDS and the honorific repair for Marathi are
all conversation and language mechanics, not health. They were tuned against
real calls, including the traps recorded in CLAUDE.md, and rewriting them from
scratch for education would throw that away to no purpose. Each spec imports
them from `lang_services.<lang>.personality` and extends where education needs
something extra. That import is also the clearest possible demonstration that
the mechanics were never health-specific in the first place.
"""

from __future__ import annotations

import random
import re

from edu import config, escalation, knowledge, persona
from edu.institution import Institution, get_institution
from shared.prompts import END_SIGNAL


class EduPack:
    """Duck-typed language pack for the education product.

    Instances expose exactly the surface the call engine touches. Built once
    per process by edu/lang_loader.py, not per call — build_system_blocks()
    must return a byte-identical persona prefix on every turn or the prompt
    cache never hits.
    """

    def __init__(self, spec, inst: Institution | None = None):
        self.spec = spec
        self.inst = inst or get_institution()

        self.CODE = spec.CODE
        self.NAME = spec.NAME

        # Stamped onto every conversations row. Combines the shared persona
        # version, this pack's version, and the institution file, because a
        # reply's quality depends on all three and attributing a regression to
        # the wrong one costs days.
        inst_tag = re.sub(r"[^a-z0-9]+", "-", (self.inst.name or "inst").lower()).strip("-")[:24]
        self.PROMPT_VERSION = f"{persona.PERSONA_VERSION}/{spec.PACK_VERSION}/{inst_tag}"

        self.agent_name = self.inst.agent_name or config.AGENT_NAME
        self.agent_role = self.inst.agent_role or config.AGENT_ROLE

        knobs = {
            "tone": config.TONE,
            "formality": config.FORMALITY,
            "verbosity": config.VERBOSITY,
            "sales": config.SALES_INTENSITY,
            "patience": config.PATIENCE,
        }
        knobs.update(self.inst.personality or {})
        self.knobs = knobs

        # ── The static prefix ─────────────────────────────────────
        # Persona and institution facts go in ONE block with ONE cache marker,
        # rather than two blocks with two. Both are static for the whole call,
        # and a single combined block is the shape most likely to clear the
        # model's minimum cacheable prefix — which, per CLAUDE.md, is the
        # difference between the marker doing something and doing nothing at
        # all. See edu/knowledge.py and `python -m edu.tools.prospectus_lint`.
        self._persona_text = persona.build_persona(
            inst=self.inst,
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            knobs=knobs,
            language_rule=spec.LANGUAGE_RULE,
            fewshots=spec.FEWSHOTS,
        )
        self._knowledge_text = knowledge.build_knowledge_block(self.inst)
        self._static_block = self._persona_text + "\n\n" + self._knowledge_text

        # ── Fixed lines ───────────────────────────────────────────
        self.GREETING = spec.GREETING
        self.CLOSING = spec.CLOSING
        self.EMERGENCY = spec.EMERGENCY
        self.FALLBACK = spec.FALLBACK
        self.STILL_THERE = spec.STILL_THERE

        # ── Word lists (mechanics, reused from the Saathicare packs) ──
        self.EXIT_WORDS = list(spec.EXIT_WORDS)
        self.TRAILING_PARTICLES = list(getattr(spec, "TRAILING_PARTICLES", []))
        self.SELF_EXIT_WORDS = list(spec.SELF_EXIT_WORDS)
        self.SELF_EXIT_BLOCKERS = list(spec.SELF_EXIT_BLOCKERS)
        self.UNAVAILABLE_WORDS = list(spec.UNAVAILABLE_WORDS)
        self.DECLINE_WORDS = list(spec.DECLINE_WORDS)
        self.WRONG_PERSON_WORDS = list(spec.WRONG_PERSON_WORDS)
        self.BEREAVEMENT_WORDS = list(spec.BEREAVEMENT_WORDS)

        # Kept non-empty on purpose. A parent can have a genuine medical
        # emergency while on a call about their child's admission, and the
        # cross-language baseline in conversation_engine fires regardless of
        # what this list holds — so the pack needs a sensible EMERGENCY line
        # even though emergencies are not this product's business.
        self.EMERGENCY_KEYWORDS = list(getattr(spec, "EMERGENCY_KEYWORDS", []))

        # ── Extraction ────────────────────────────────────────────
        self.HINTS = dict(spec.HINTS)
        self.CRITICAL_TOPICS = list(
            getattr(spec, "CRITICAL_TOPICS", None) or _default_critical()
        )
        self.DEFER_MARKERS = list(spec.DEFER_MARKERS)
        # Numeral vocabulary for the qualification extractor. Lives on the pack
        # because "पाचवी" is a language fact, not an admissions one.
        self.NUMERALS = dict(getattr(spec, "NUMERALS", {}) or {})
        self.STEER_QUESTIONS = dict(spec.STEER_QUESTIONS)

        # ── Voice ─────────────────────────────────────────────────
        self.TTS_CONFIG = dict(spec.TTS_CONFIG)

        # Optional mechanics some packs have and others do not. telephony
        # /session.py probes for honorific_slips with getattr, so absent is fine.
        for optional in ("fix_honorifics", "honorific_slips"):
            fn = getattr(spec, optional, None)
            if callable(fn):
                setattr(self, optional, fn)

    # ── Prompt building ───────────────────────────────────────────

    def build_system_blocks(self, user_name: str, context: dict) -> list:
        blocks = [
            {
                "type": "text",
                "text": self._static_block,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        tail = self._dynamic_tail(user_name, context).strip()
        if tail:
            blocks.append({"type": "text", "text": tail})
        return blocks

    def build_prompt(self, user_name: str, context: dict) -> str:
        return self._static_block + "\n\n" + self._dynamic_tail(user_name, context)

    def _dynamic_tail(self, user_name: str, context: dict) -> str:
        """Everything that changes between turns. Kept small and kept last so
        the prefix above it stays byte-identical and cacheable."""
        parts: list[str] = []
        turn = context.get("turn_number", 1)
        extracted = context.get("extracted_so_far") or {}
        phase = context.get("phase")
        winding_down = context.get("winding_down", False)
        steer_topic = context.get("steer_topic")
        should_steer = context.get("should_steer", False)
        esc = context.get("escalation_reason")
        summary = context.get("running_summary") or ""

        parts.append(f"THIS CALL SO FAR\nYou are speaking with {user_name}. Turn {turn}.")

        if summary:
            # Older turns fall out of the replayed history window; without this
            # she would answer the same fee question twice with two different
            # framings, which is the fastest way to lose a parent's trust.
            parts.append("WHAT HAS ALREADY BEEN COVERED\n" + summary)

        if extracted:
            known = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in extracted.items())
            parts.append(
                "WHAT THEY HAVE ALREADY TOLD YOU\n"
                + known
                + "\nDo not ask for any of this again."
            )

        if esc:
            parts.append("HANDLE THIS NOW\n" + escalation.instruction(esc))
        elif phase == "farewell":
            reason = context.get("farewell_reason") or "goodbye"
            parts.append("THE CALL IS ENDING\n" + self._farewell_instruction(reason))
        elif should_steer and steer_topic:
            line = self.STEER_QUESTIONS.get(steer_topic)
            if line:
                parts.append("ONE THING TO WORK IN, ONLY IF THEY ARE NOT MID-QUESTION\n" + line)
        elif winding_down:
            parts.append(
                "WINDING DOWN\nBring this to a natural close over the next couple of "
                "turns. If a visit or callback has not been settled, this is the "
                "moment to offer it once."
            )

        return "\n\n".join(parts)

    def _farewell_instruction(self, reason: str) -> str:
        base = self.spec.FAREWELL.get(reason) or self.spec.FAREWELL["goodbye"]
        return f"{base}\nEnd your reply with {END_SIGNAL}."

    # ── Fixed-line builders ───────────────────────────────────────

    def build_greeting(self, user_name: str, history_summary=None) -> str:
        """Opening line. The most important sentence in the call: it has about
        four seconds to establish who is calling and why before a parent
        decides this is a telemarketer."""
        h = history_summary if isinstance(history_summary, dict) else {}
        bucket = "callback" if h.get("previous_calls") else "first"
        template = random.choice(self.spec.GREETINGS[bucket])
        return template.format(
            name=user_name,
            agent=self.agent_name,
            institution=self.inst.name,
        )

    def build_closing(self, user_name: str, context=None) -> str:
        ctx = context if isinstance(context, dict) else {}
        extracted = ctx.get("extracted_so_far") or {}
        if extracted.get("visit_intent") == "yes":
            bucket = "visit"
        elif ctx.get("escalation_reason") or extracted.get("callback_time"):
            bucket = "callback"
        else:
            bucket = "neutral"
        template = random.choice(self.spec.CLOSINGS[bucket])
        return template.format(
            name=user_name,
            agent=self.agent_name,
            institution=self.inst.name,
        )

    # ── Text handling ─────────────────────────────────────────────

    def prepare_for_tts(self, text: str) -> str:
        return self.spec.prepare_for_tts(text)

    def read_tone(self, text: str) -> str | None:
        """Tone read, used only to pick a thinking sound that does not land
        badly. The health packs read for pain and distress; here the tones that
        matter are impatience and hesitation."""
        return self.spec.read_tone(text)


def _default_critical() -> list:
    from edu import qualification

    return list(qualification.CRITICAL_SLOTS)


def build_pack(spec, inst: Institution | None = None) -> EduPack:
    return EduPack(spec, inst)
