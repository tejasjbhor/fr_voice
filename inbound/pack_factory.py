"""Assemble an inbound language pack the call engine can duck-type."""

from __future__ import annotations

from inbound import config, persona
from shared.prompts import END_SIGNAL


class InboundPack:
    def __init__(self, spec):
        self.spec = spec
        self.CODE = spec.CODE
        self.NAME = spec.NAME
        self.PROMPT_VERSION = f"{persona.PERSONA_VERSION}/{spec.PACK_VERSION}"

        self.agent_name = config.AGENT_NAME
        self.agent_role = config.AGENT_ROLE
        self.service_name = config.SERVICE_NAME

        self._static_block = persona.build_persona(
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            service_name=self.service_name,
            language_rule=spec.LANGUAGE_RULE,
            fewshots=spec.FEWSHOTS,
        )

        # GREETING templates use {agent}/{service}/{name}; build_greeting fills them.
        self._greeting_template = spec.GREETING
        self.GREETING = spec.GREETING
        self.CLOSING = spec.CLOSING
        self.EMERGENCY = spec.EMERGENCY
        self.FALLBACK = spec.FALLBACK
        self.STILL_THERE = spec.STILL_THERE

        self.EXIT_WORDS = list(spec.EXIT_WORDS)
        self.SELF_EXIT_WORDS = list(spec.SELF_EXIT_WORDS)
        self.SELF_EXIT_BLOCKERS = list(spec.SELF_EXIT_BLOCKERS)
        self.UNAVAILABLE_WORDS = list(spec.UNAVAILABLE_WORDS)
        self.DECLINE_WORDS = list(spec.DECLINE_WORDS)
        self.WRONG_PERSON_WORDS = list(spec.WRONG_PERSON_WORDS)
        self.BEREAVEMENT_WORDS = list(spec.BEREAVEMENT_WORDS)
        self.EMERGENCY_KEYWORDS = [
            "emergency", "ambulance", "police", "108", "112",
            "आपातकाल", "एम्बुलेंस", "आपत्काल",
        ]
        # Number-only entries are stripped elsewhere; keep words only.
        self.EMERGENCY_KEYWORDS = [
            k for k in self.EMERGENCY_KEYWORDS if not k.isdigit()
        ]

        self.HINTS = dict(getattr(spec, "HINTS", {}) or {})
        self.CRITICAL_TOPICS = ["topic", "summary_note"]
        self.TTS_CONFIG = dict(spec.TTS_CONFIG)

        for optional in ("fix_honorifics", "honorific_slips"):
            fn = getattr(spec, optional, None)
            if callable(fn):
                setattr(self, optional, fn)

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
        parts = [
            f"THIS CALL\nCaller name on file: {user_name}. "
            f"Turn {context.get('turn_number', 1)}."
        ]
        extracted = context.get("extracted_so_far") or {}
        if extracted:
            known = "; ".join(f"{k}: {v}" for k, v in extracted.items() if v)
            parts.append(
                "DETAILS ALREADY CAPTURED\n"
                + known
                + "\nDo not re-ask these unless correcting them."
            )
        if context.get("phase") == "farewell":
            parts.append(
                "THE CALL IS ENDING\nThank them briefly for calling. "
                f"End your reply with {END_SIGNAL}."
            )
        elif context.get("winding_down"):
            parts.append(
                "WINDING DOWN\nOffer one last chance to ask something, "
                "then close politely."
            )
        return "\n\n".join(parts)

    def build_greeting(self, user_name: str, history_summary=None) -> str:
        return self._greeting_template.format(
            name=user_name or "ji",
            agent=self.agent_name,
            service=self.service_name,
        )

    def build_closing(self, user_name: str, context=None) -> str:
        return self.CLOSING

    def prepare_for_tts(self, text: str) -> str:
        return self.spec.prepare_for_tts(text)

    def read_tone(self, text: str) -> str | None:
        low = (text or "").lower()
        if any(w in low for w in ("emergency", "urgent", "आपातकाल", "आपत्काल")):
            return "emergency"
        return None


def build_pack(spec) -> InboundPack:
    return InboundPack(spec)
