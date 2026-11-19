"""
core/alert_engine.py — Trend Analysis + Family Alert System
Shared by all language services.
"""

from core.database import get_recent_records


def analyse(user_id: int) -> tuple:
    """
    Analyse 7-day health records.
    Returns (alert_level, reason).
    Levels: green / yellow / orange / red / emergency
    """
    records = get_recent_records(user_id, days=7)
    if not records:
        return "green", "No records yet"

    poor_sleep   = sum(1 for r in records if r.get("sleep_quality") == "poor")
    skipped_food = sum(1 for r in records if r.get("food_intake")   == "skipped")
    low_mood     = sum(1 for r in records if r.get("mood")          == "low")
    dizziness    = sum(1 for r in records if r.get("dizziness"))
    chest        = any(r.get("chest_discomfort") for r in records)
    no_breathing = any(not r.get("breathing_ok", True) for r in records)

    if chest or no_breathing:
        return "emergency", "Chest discomfort or breathing issue reported"

    reasons = []
    if poor_sleep >= 5:   reasons.append(f"{poor_sleep} days poor sleep")
    if skipped_food >= 4: reasons.append(f"{skipped_food} days skipped meals")
    if reasons: return "red", " | ".join(reasons)

    if poor_sleep >= 3:   reasons.append(f"{poor_sleep} days poor sleep")
    if skipped_food >= 2: reasons.append(f"{skipped_food} days skipped meals")
    if dizziness >= 2:    reasons.append(f"{dizziness} days dizziness")
    if reasons: return "orange", " | ".join(reasons)

    if low_mood >= 3:
        return "yellow", f"{low_mood} days low mood"

    return "green", "All reported normal"


def get_recent_summary(user_id: int) -> dict:
    """
    Get last 7 days summary for context injection.
    Returns dict with trends for personality prompt.
    """
    records = get_recent_records(user_id, days=7)
    if not records:
        return {}

    last = records[0]
    last_bp    = None
    last_sugar = None
    for r in records:
        if not last_bp    and r.get("bp_systolic"):
            last_bp    = f"{r['bp_systolic']}/{r['bp_diastolic']}"
        if not last_sugar and r.get("sugar_fasting"):
            last_sugar = str(r["sugar_fasting"])
        if last_bp and last_sugar:
            break

    return {
        "poor_sleep_days":    sum(1 for r in records if r.get("sleep_quality") == "poor"),
        "skipped_food_days":  sum(1 for r in records if r.get("food_intake")   == "skipped"),
        "low_mood_days":      sum(1 for r in records if r.get("mood")          == "low"),
        "last_bp":            last_bp,
        "last_sugar":         last_sugar,
        "recent_mood":        last.get("mood"),
        "recent_sleep":       last.get("sleep_quality"),
        "recent_energy":      last.get("energy_level"),
    }
