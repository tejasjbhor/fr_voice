"""
edu/ — Education voice product built on the Saathicare engine.

Nothing in this package modifies the existing codebase. It supplies:
  - a language pack that satisfies the same duck-typed contract the call
    engine already expects (edu/pack_factory.py, edu/packs/*),
  - a SessionManager subclass that swaps health extraction for lead
    qualification (edu/session_manager.py),
  - the institution knowledge block that rides the prompt cache
    (edu/institution.py, edu/knowledge.py),
  - outcome, escalation, compliance and lead storage.

Integration is two lines in telephony/session.py. See edu/INTEGRATION.md.
"""

__all__ = [
    "config",
    "compliance",
    "escalation",
    "institution",
    "knowledge",
    "lang_loader",
    "lead_store",
    "outcome",
    "pack_factory",
    "persona",
    "qualification",
    "session_manager",
    "tail_text",
]
