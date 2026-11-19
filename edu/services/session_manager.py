"""
services/session_manager.py — Call State Manager
=================================================
Tracks everything that happens during one call:
  - Conversation history
  - What health data has been extracted so far
  - Whether to steer the conversation
  - Turn count and timing

This is the brain that coordinates the conversation
without the language service knowing about it.
"""

import os
import time
import uuid
from core.extractor  import fast_extract, should_steer
from core.alert_engine import get_recent_summary
from core.llm_service import UsageMeter

# How many turns a call runs before Sathi closes it. The last WIND_DOWN_TURNS
# turns are spent bringing the conversation to a natural end — the call used to
# simply stop dead on turn 12, mid-thought, and then play a fixed closing.
MAX_TURNS       = int(os.getenv("MAX_CALL_TURNS", "12"))
WIND_DOWN_TURNS = int(os.getenv("WIND_DOWN_TURNS", "2"))

# Consecutive turns we can fail to hear before giving up on the call.
MAX_MISSES = int(os.getenv("MAX_CONSECUTIVE_MISSES", "3"))

# Wall-clock ceiling on one call, in seconds. 0 disables it, which is what
# every call used to be: this was set in .env but read nowhere in the code,
# so a slow, chatty call had no upper bound at all. The cap is checked at the
# end of a turn, so it never cuts her off mid-sentence.
MAX_CALL_SECONDS = int(os.getenv("MAX_CALL_SECONDS", "0"))


class SessionManager:
    """
    One instance per phone call.
    Manages state so conversation_engine stays clean.
    """

    def __init__(self, user: dict, lang_service):
        self.user        = user
        self.lang        = lang_service
        self.session_id  = str(uuid.uuid4())
        self.started_at  = time.monotonic()

        # Conversation state
        self.turn_number     = 0
        self.history         = []    # [{role, content}] for LLM
        self.last_user_msg   = ""
        self.last_sathi_msg  = ""

        # Conversation phase: None | "farewell" | "emergency_followup".
        # Set by the call loop; read by the personality tail.
        self.phase           = None
        self.emergency_turns = 0

        # Why the farewell started — one of conversation_engine.EXIT_REASONS.
        # "goodbye" and "they're in a meeting" both end the call, but she has
        # to say something quite different on the way out, so the reason
        # travels into the prompt rather than stopping at the phase flag.
        self.farewell_reason = None

        # Consecutive turns where STT returned nothing (see note_miss / note_heard)
        self.consecutive_misses = 0

        # Last filler played, so we don't repeat it back to back
        self.last_thinking_sound = None

        # Extraction state
        self.extracted       = {}    # accumulated health data this call
        self.critical_topics = getattr(lang_service, 'CRITICAL_TOPICS',
                               ["sleep","food","water","bp","sugar","mood"])

        # History from DB (loaded once at call start) — always a dict for prompts
        summary = get_recent_summary(user["id"])
        self.history_summary = summary if isinstance(summary, dict) else {}

        # Cost tracking. The LLM meter belongs to this call and must be passed
        # into stream_tokens() — sharing one across concurrent calls is what the
        # old module-level counters did, and it made every cost row wrong.
        self.total_stt_sec   = 0.0
        self.total_tts_chars = 0
        self.usage           = UsageMeter()

        # Optional full-call audio (user + AI) — set by main.py
        self.call_recorder   = None

    def start_turn(self) -> int:
        self.turn_number += 1
        if self.phase == "emergency_followup":
            self.emergency_turns += 1
        return self.turn_number

    def record_user_turn(self, text: str, audio_duration: float = 0):
        """Call after STT — records user's words."""
        self.last_user_msg  = text
        self.total_stt_sec += audio_duration
        self.history.append({"role": "user", "content": text})

    def record_sathi_turn(self, text: str, tts_chars: int = 0):
        """Call after LLM response — records Sathi's words."""
        self.last_sathi_msg  = text
        self.total_tts_chars += tts_chars
        self.history.append({"role": "assistant", "content": text})

        # Run fast extractor silently after every turn
        self._run_fast_extract()

    def _run_fast_extract(self):
        """
        Silent extraction after each turn.
        Merges new findings into self.extracted.
        No API call — pure keyword matching.
        """
        hints = getattr(self.lang, 'HINTS', {})
        new_data = fast_extract(
            user_text=self.last_user_msg,
            sathi_text=self.last_sathi_msg,
            lang_hints=hints,
        )
        # Merge — don't overwrite already-extracted values
        for key, val in new_data.items():
            if val is not None and val is not False:
                if key not in self.extracted or self.extracted[key] is None:
                    self.extracted[key] = val

    # ── Hearing the caller ────────────────────────────────────────

    def note_miss(self) -> int:
        """STT returned nothing this turn. Returns the consecutive miss count."""
        self.consecutive_misses += 1
        return self.consecutive_misses

    def note_heard(self):
        """We understood them — reset the recovery ladder."""
        self.consecutive_misses = 0

    def gave_up_hearing(self) -> bool:
        return self.consecutive_misses >= MAX_MISSES

    # ── Phases ────────────────────────────────────────────────────

    def begin_farewell(self, reason: str = "goodbye"):
        """
        The call is ending — she gets one last turn to answer properly.

        `reason` is why (see conversation_engine.classify_exit): a goodbye, a
        bad moment, an opt-out, the wrong person, or a death. The first caller
        to set it wins, so a later, weaker read cannot overwrite a grave one.
        """
        self.phase = "farewell"
        if self.farewell_reason is None:
            self.farewell_reason = reason or "goodbye"

    def begin_emergency_followup(self):
        """She has given the emergency instruction; now she stays on the line."""
        self.phase = "emergency_followup"
        self.emergency_turns = 0

    def emergency_followup_done(self) -> bool:
        """Stay on for a couple of turns after an emergency, then let them go."""
        return self.emergency_turns >= 2

    def build_llm_context(self) -> dict:
        """
        Build context dict for personality.build_prompt().
        Called before every LLM turn.
        """
        steer, steer_topic = should_steer(
            turn_number=self.turn_number,
            extracted_so_far=self.extracted,
            critical_topics=self.critical_topics,
            wrap_up_from=max(4, MAX_TURNS - 4),
        )

        return {
            "turn_number":       self.turn_number,
            "last_user_message": self.last_user_msg,
            "last_sathi_message":self.last_sathi_msg,
            "history_summary":   self.history_summary,
            "extracted_so_far":  self.extracted,
            "should_steer":      steer,
            "steer_topic":       steer_topic,
            "phase":             self.phase,
            "farewell_reason":   self.farewell_reason,
            "winding_down":      self.is_winding_down(),
        }

    def get_llm_messages(self, max_turns: int = 10) -> list:
        """Return last N turns as LLM message list."""
        return self.history[-(max_turns * 2):]

    def elapsed(self) -> float:
        """Seconds since the call connected."""
        return time.monotonic() - self.started_at

    def out_of_time(self) -> bool:
        """True once the wall-clock cap is set and reached."""
        return MAX_CALL_SECONDS > 0 and self.elapsed() >= MAX_CALL_SECONDS

    def is_winding_down(self) -> bool:
        """True for the last few turns, so she can close the call herself."""
        return self.turn_number >= max(1, MAX_TURNS - WIND_DOWN_TURNS)

    def is_call_done(self) -> bool:
        """Should we end the call?"""
        if self.phase == "farewell":
            return True
        if self.phase == "emergency_followup" and self.emergency_followup_done():
            return True
        if self.out_of_time():
            return True
        return self.turn_number >= MAX_TURNS

    @property
    def total_tokens(self) -> int:
        """LLM tokens this call. Was a hardcoded 0 that got saved to api_costs."""
        return self.usage.total_tokens

    @property
    def llm_cache_write_tokens(self) -> int:
        return self.usage.cache_creation_input_tokens

    @property
    def llm_cache_read_tokens(self) -> int:
        return self.usage.cache_read_input_tokens

    @property
    def llm_cost_inr(self) -> float:
        return self.usage.cost_inr

    @property
    def language(self) -> str:
        return self.user.get("language", "fr-FR")

    @property
    def prompt_version(self) -> str | None:
        """Version of the language pack's prompt, stamped onto each saved turn."""
        return getattr(self.lang, "PROMPT_VERSION", None)

    @property
    def user_name(self) -> str:
        return self.user.get("name", "Ji")
