"""Lightweight keyword extraction for inbound query calls (no LLM)."""

from __future__ import annotations

import re

# Slots we try to fill over the call. None means "not heard yet".
SLOTS = ("topic", "location", "callback_phone", "urgency", "summary_note")


def fast_extract(user_text: str, agent_text: str = "", hints: dict | None = None) -> dict:
    """
    Merge simple signals from the latest user turn.
    `hints` may supply extra keyword lists from the language pack.
    """
    text = (user_text or "").strip()
    low = text.lower()
    out: dict = {}
    hints = hints or {}

    topic_map = hints.get("topics") or {
        "lost": "lost_item",
        "missing": "lost_item",
        "direction": "directions",
        "where": "directions",
        "timing": "timings",
        "time": "timings",
        "open": "timings",
        "complaint": "complaint",
        "problem": "complaint",
        "help": "general_help",
        "emergency": "emergency",
        "ambulance": "emergency",
        "police": "emergency",
        # Hindi / Marathi roman + common Devanagari stems handled below
        "रास्ता": "directions",
        "दिशा": "directions",
        "समय": "timings",
        "वेळ": "timings",
        "हरव": "lost_item",
        "तक्रार": "complaint",
        "मदत": "general_help",
        "आपातकाल": "emergency",
    }
    for stem, topic in topic_map.items():
        if stem.lower() in low or stem in text:
            out["topic"] = topic
            break

    if any(w in low for w in ("urgent", "emergency", "now", "तुरंत", "आत्ता", "जरूरी")):
        out["urgency"] = "high"
    elif text:
        out.setdefault("urgency", "normal")

    # Phone-like callback in the utterance
    m = re.search(r"(\+?\d[\d\s\-]{8,}\d)", text)
    if m:
        digits = re.sub(r"[^\d+]", "", m.group(1))
        if len(re.sub(r"\D", "", digits)) >= 10:
            out["callback_phone"] = digits

    # Short free-text note (first substantive user line)
    if len(text) >= 12:
        out["summary_note"] = text[:240]

    loc_hints = hints.get("location_words") or (
        "at ", "near ", "in ", "के पास", "में", "मध्ये", "जवळ"
    )
    for w in loc_hints:
        if w.lower() in low or w in text:
            # Keep a short slice after the cue when possible
            out["location"] = text[:120]
            break

    return out
