"""
edu/session_manager.py — call state for an admissions call.

Subclasses services.SessionManager rather than replacing it, so everything that
already works — turn counting, the miss ladder, the farewell phases, the
per-call UsageMeter — keeps working untouched. What changes is what gets
extracted, when to steer, how long the call may run, and what the call is worth
at the end.

Three overrides carry the real differences:

  _run_fast_extract   health slots -> qualification slots
  build_llm_context   adds the running summary, escalation state and the
                      answer-first gate
  is_call_done        a longer, cost-bounded call instead of a hard 12 turns

The running summary deserves a note. Saathicare replays the last 8 exchanges
and keeps nothing else, which is fine for a 12-turn check-in. An admissions
call runs longer, and a parent who was quoted a fee on turn 3 and asks about it
again on turn 19 must hear the same number. The summary is built from what was
actually extracted plus the topics covered, costs no API call, and rides in the
per-turn tail.
"""

from __future__ import annotations

from edu import config, escalation, outcome, qualification
from services.session_manager import SessionManager


class EduSessionManager(SessionManager):
    """One instance per admissions call."""

    def __init__(self, user: dict, lang_service, institution=None):
        super().__init__(user, lang_service)

        from edu.institution import get_institution

        self.institution = institution or get_institution()

        # Qualification state. `extracted` is inherited and reused as-is; only
        # what goes into it changes.
        self.critical_topics = list(qualification.CRITICAL_SLOTS)
        self.steers_used = 0
        self.asked_question_this_turn = False

        # Escalation. Sticky: once a call needs a human it needs a human, and a
        # later ordinary turn must not clear it.
        self.escalation_reason: str | None = None
        self.unknown_count = 0

        # Topics she has actually answered, for the running summary.
        self.topics_covered: list[str] = []

        # Saathicare loads a health history summary in __init__. There is no
        # equivalent here yet; previous-contact context comes from the lead
        # store when one is configured.
        self.history_summary = self._load_lead_history()

    # ── History ───────────────────────────────────────────────────

    def _load_lead_history(self) -> dict:
        try:
            from edu.lead_store import get_lead_history

            return get_lead_history(self.user.get("phone")) or {}
        except Exception:
            # A missing or unreachable lead store must never stop a call from
            # connecting. Worst case she opens with the first-contact greeting.
            return {}

    # ── Extraction ────────────────────────────────────────────────

    def _run_fast_extract(self):
        """Replaces the health extractor. Called by record_sathi_turn()."""
        hints = getattr(self.lang, "HINTS", {}) or {}
        found = qualification.fast_qualify(
            user_text=self.last_user_msg,
            agent_text=self.last_sathi_msg,
            hints=hints,
            catchment_areas=self.institution.catchment_areas,
            catchment_aliases=self.institution.catchment_aliases,
            numerals=getattr(self.lang, "NUMERALS", {}),
        )
        qualification.merge(self.extracted, found)

        # Count the turns she could not answer. Drives both the escalation
        # trigger and, after the fact, the ranked list of gaps in the
        # institution file — which is the most useful report this system
        # produces in its first month of calls.
        markers = getattr(self.lang, "DEFER_MARKERS", []) or []
        if outcome.is_deferral(self.last_sathi_msg, markers):
            self.unknown_count += 1

        if self.escalation_reason is None:
            reason = escalation.check(
                self.last_user_msg, hints, unknown_count=self.unknown_count
            )
            if reason:
                self.escalation_reason = reason

    def record_user_turn(self, text: str, audio_duration: float = 0):
        super().record_user_turn(text, audio_duration=audio_duration)
        # Evaluated here, before the reply is built, because the answer-first
        # gate has to know about the question that is still outstanding.
        self.asked_question_this_turn = qualification.parent_asked_question(
            text, getattr(self.lang, "HINTS", {}) or {}
        )

    # ── Prompt context ────────────────────────────────────────────

    def _running_summary(self) -> str:
        bits = []
        if self.topics_covered:
            bits.append("Already answered: " + ", ".join(self.topics_covered) + ".")
        if self.extracted.get("fee_concern"):
            bits.append("They have said the fee feels high — do not re-pitch it.")
        if self.extracted.get("visit_intent") == "declined":
            bits.append("They have already declined a visit. Do not ask again.")
        return " ".join(bits)

    def build_llm_context(self) -> dict:
        steer, topic = qualification.should_steer(
            turn_number=self.turn_number,
            extracted=self.extracted,
            wrap_up_from=max(6, config.EDU_MAX_TURNS - config.EDU_WIND_DOWN_TURNS),
            asked_question=self.asked_question_this_turn,
            steers_used=self.steers_used,
        )
        if steer and topic and topic not in qualification.NON_STEER_TOPICS:
            self.steers_used += 1

        return {
            "turn_number": self.turn_number,
            "last_user_message": self.last_user_msg,
            "last_sathi_message": self.last_sathi_msg,
            "history_summary": self.history_summary,
            "running_summary": self._running_summary(),
            "extracted_so_far": self.extracted,
            "should_steer": steer,
            "steer_topic": topic,
            "phase": self.phase,
            "farewell_reason": self.farewell_reason,
            "escalation_reason": self.escalation_reason,
            "winding_down": self.is_winding_down(),
        }

    def get_llm_messages(self, max_turns: int = None) -> list:
        turns = max_turns or config.EDU_HISTORY_TURNS
        return self.history[-(turns * 2):]

    # ── Call length ───────────────────────────────────────────────

    def is_winding_down(self) -> bool:
        return self.turn_number >= max(
            1, config.EDU_MAX_TURNS - config.EDU_WIND_DOWN_TURNS
        )

    def over_cost_budget(self) -> bool:
        cap = config.EDU_MAX_CALL_COST_INR
        return cap > 0 and self.llm_cost_inr >= cap

    def is_call_done(self) -> bool:
        """Same exit conditions as the base class, plus a cost ceiling, and
        with the turn cap read from edu config rather than the health one.

        Checked at turn boundaries only, so it never cuts her off mid-sentence.
        """
        if self.phase == "farewell":
            return True
        if self.phase == "emergency_followup" and self.emergency_followup_done():
            return True
        if self.out_of_time():
            return True
        if self.over_cost_budget():
            return True
        return self.turn_number >= config.EDU_MAX_TURNS

    # ── Result ────────────────────────────────────────────────────

    def call_outcome(self) -> dict:
        """Disposition, score and next action. Call once after the call ends."""
        return outcome.summarise(
            farewell_reason=self.farewell_reason,
            extracted=self.extracted,
            turn_count=self.turn_number,
            escalation_reason=self.escalation_reason,
            unknown_count=self.unknown_count,
            heard_anything=bool(self.history),
        )

    def persist_outcome(self) -> dict | None:
        """Write the disposition to the lead store. Returns what was written,
        or None if the store is unavailable — a failure here must never
        propagate into the call teardown path."""
        result = self.call_outcome()
        try:
            from edu.lead_store import save_call_outcome

            save_call_outcome(
                phone=self.user.get("phone"),
                session_id=self.session_id,
                language=self.language,
                prompt_version=self.prompt_version,
                result=result,
            )
        except Exception:
            return None
        return result
