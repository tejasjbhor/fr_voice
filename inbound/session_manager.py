"""Call state for an inbound helpline conversation."""

from __future__ import annotations

from inbound import config, extract
from inbound.store import save_query
from services.session_manager import SessionManager


class InboundSessionManager(SessionManager):
    """One instance per inbound helpline call."""

    def __init__(self, user: dict, lang_service):
        super().__init__(user, lang_service)
        self.critical_topics = list(
            getattr(lang_service, "CRITICAL_TOPICS", None)
            or ["topic", "summary_note"]
        )
        # No elder health history for helpline guests.
        self.history_summary = {}

    def _run_fast_extract(self):
        hints = getattr(self.lang, "HINTS", {}) or {}
        new_data = extract.fast_extract(
            user_text=self.last_user_msg,
            agent_text=self.last_sathi_msg,
            hints=hints,
        )
        for key, val in new_data.items():
            if val is not None and val is not False:
                if key not in self.extracted or self.extracted[key] is None:
                    self.extracted[key] = val

    def is_winding_down(self) -> bool:
        return self.turn_number >= max(1, config.MAX_TURNS - config.WIND_DOWN_TURNS)

    def is_call_done(self) -> bool:
        if self.phase == "farewell":
            return True
        if self.phase == "emergency_followup" and self.emergency_followup_done():
            return True
        if self.out_of_time():
            return True
        if config.MAX_CALL_COST_INR > 0 and self.llm_cost_inr >= config.MAX_CALL_COST_INR:
            return True
        return self.turn_number >= config.MAX_TURNS

    def get_llm_messages(self, max_turns: int = 10) -> list:
        return self.history[-(config.HISTORY_TURNS * 2):]

    def persist_outcome(self) -> str | None:
        """Write JSONL query record after hang-up. No health extract."""
        record = {
            "session_id": self.session_id,
            "user_id": self.user.get("id"),
            "phone": self.user.get("phone"),
            "name": self.user.get("name"),
            "language": self.user.get("language"),
            "turns": self.turn_number,
            "extracted": dict(self.extracted or {}),
            "llm_cost_inr": round(float(self.llm_cost_inr or 0), 4),
            "prompt_version": getattr(self.lang, "PROMPT_VERSION", ""),
        }
        return save_query(record)
