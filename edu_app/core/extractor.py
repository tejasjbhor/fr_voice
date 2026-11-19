"""
core/extractor.py — Silent Background Health Data Extractor
============================================================
This is the KEY to free conversation without a checklist.

After each conversation turn, this runs silently in the background.
It reads what was said and extracts any health data mentioned.

The user never knows this is happening.
Sathi never asks direct checklist questions.
Data is collected naturally as topics come up in conversation.

Two extraction methods:
  1. FAST: Keyword matching (instant, no API cost)
     Catches obvious mentions: "झोप नाही झाली", "BP 145"
  
  2. DEEP: LLM extraction (after call ends, full conversation)
     Catches nuanced mentions: "रात्री बराच वेळ जागा होतो" → sleep=poor
"""

import re
import asyncio
from core import llm_service
from colorama import Fore, Style


# ══════════════════════════════════════════════════════════════════
# FAST EXTRACTOR — keyword-based, runs after every turn
# ══════════════════════════════════════════════════════════════════

# BP pattern: "145/92", "145 over 92", "१४५ वर ९२".
# This used to be a character class — [/over वर] — which matches a single
# character, so only the "145/92" form ever worked. On a phone call STT returns
# the spoken form ("145 over 92"), so verbal readings were silently dropped and
# Sathi kept asking for a blood pressure she had already been told.
BP_PATTERN = re.compile(
    r"(\d{2,3})\s*(?:[/\\-]|over|by|upon|वर|पर|बटा|बाय)\s*(\d{2,3})",
    re.IGNORECASE)

# Sugar pattern: "138" near sugar keyword
SUGAR_PATTERN = re.compile(r"\b(\d{2,3})\b")

# Pulse pattern
PULSE_PATTERN = re.compile(
    r"(?:pulse|नाडी|हृदय)\s*[:\-]?\s*(\d{2,3})", re.IGNORECASE)


def fast_extract(user_text: str, sathi_text: str,
                 lang_hints: dict) -> dict:
    """
    Instant keyword extraction from one conversation turn.
    No API call. Returns partial health data dict.
    Only extracts what is CLEARLY mentioned.

    lang_hints = language-specific keyword maps from lang_service
    """
    # Numeric vitals scan both sides — Sathi sometimes reads a BP/sugar
    # number back for confirmation ("so that's 145 over 90"), and that
    # repetition is a legitimate second chance to catch it.
    #
    # Everything below (sleep/food/water/mood/symptoms) scans `user_text`
    # ONLY. These are plain-word keyword lists ("better", "okay", "fine"...)
    # and Sathi's own scripted lines are full of exactly that vocabulary —
    # greetings ask "sleep any better?", closings say "that's good to hear".
    # Blending her words in used to attribute her own phrasing to the
    # caller: fast_extract("", "...sleep any better...") produced
    # {'mood': 'good'} with zero user turns. Keyword matching can't tell a
    # question from a statement, so the only safe fix is to not hand it
    # Sathi's side of the conversation for these fields at all.
    combined = (user_text + " " + sathi_text).lower()
    user_only = user_text.lower()
    result    = {}

    # ── Vitals — numbers ─────────────────────────────────────────
    bp_match = BP_PATTERN.search(combined)
    if bp_match:
        sys_val = int(bp_match.group(1))
        dia_val = int(bp_match.group(2))
        # Sanity check: realistic BP range
        if 70 <= sys_val <= 250 and 40 <= dia_val <= 150:
            result["bp_systolic"]  = sys_val
            result["bp_diastolic"] = dia_val

    pulse_match = PULSE_PATTERN.search(combined)
    if pulse_match:
        pulse = int(pulse_match.group(1))
        if 40 <= pulse <= 200:
            result["pulse"] = pulse

    # Sugar: look for number near sugar keyword
    sugar_keywords = lang_hints.get("sugar_keywords", [])
    if any(kw in combined for kw in sugar_keywords):
        nums = SUGAR_PATTERN.findall(combined)
        for n in nums:
            val = int(n)
            if 50 <= val <= 600:  # realistic blood sugar range
                result["sugar_fasting"] = val
                break

    # ── Sleep quality ─────────────────────────────────────────────
    sleep_poor = lang_hints.get("sleep_poor", [])
    sleep_good = lang_hints.get("sleep_good", [])
    if any(kw in user_only for kw in sleep_poor):
        result["sleep_quality"] = "poor"
    elif any(kw in user_only for kw in sleep_good):
        result["sleep_quality"] = "good"

    # ── Food intake ───────────────────────────────────────────────
    food_skip = lang_hints.get("food_skip", [])
    food_good = lang_hints.get("food_good", [])
    if any(kw in user_only for kw in food_skip):
        result["food_intake"] = "skipped"
    elif any(kw in user_only for kw in food_good):
        result["food_intake"] = "good"

    # ── Water ─────────────────────────────────────────────────────
    water_low  = lang_hints.get("water_low", [])
    water_good = lang_hints.get("water_good", [])
    if any(kw in user_only for kw in water_low):
        result["water_intake"] = "low"
    elif any(kw in user_only for kw in water_good):
        result["water_intake"] = "good"

    # ── Mood ──────────────────────────────────────────────────────
    mood_low  = lang_hints.get("mood_low", [])
    mood_good = lang_hints.get("mood_good", [])
    if any(kw in user_only for kw in mood_low):
        result["mood"] = "low"
    elif any(kw in user_only for kw in mood_good):
        result["mood"] = "good"

    # ── Symptoms ─────────────────────────────────────────────────
    if any(kw in user_only for kw in lang_hints.get("dizziness_kw", [])):
        result["dizziness"] = True
    if any(kw in user_only for kw in lang_hints.get("headache_kw", [])):
        result["headache"] = True
    if any(kw in user_only for kw in lang_hints.get("chest_kw", [])):
        result["chest_discomfort"] = True
    if any(kw in user_only for kw in lang_hints.get("breathing_bad_kw", [])):
        result["breathing_ok"] = False

    return result


# ══════════════════════════════════════════════════════════════════
# DEEP EXTRACTOR — LLM-based, runs once at end of call
# ══════════════════════════════════════════════════════════════════

_EXTRACTION_PROMPT = """Extract health data from this conversation as JSON only.
Return ONLY valid JSON. No markdown, no backticks, no explanation.

The conversation was in {language}. Extract what was actually said.
Only extract values that were CLEARLY mentioned.
null = not mentioned at all.

{{
  "bp_systolic": null,
  "bp_diastolic": null,
  "sugar_fasting": null,
  "sugar_pp": null,
  "pulse": null,
  "sleep_quality": null,
  "food_intake": null,
  "water_intake": null,
  "energy_level": null,
  "mood": null,
  "headache": false,
  "dizziness": false,
  "chest_discomfort": false,
  "breathing_ok": true,
  "body_pain": false,
  "notes": ""
}}

Values:
  sleep/food/water/energy: "good" | "average" | "poor"
  mood: "good" | "neutral" | "low" | "sad"

Conversation:
{conversation}"""


async def deep_extract(conversation_text: str,
                       language_name: str = "Marathi") -> dict:
    """
    LLM-based extraction of full conversation.
    Called once at end of call — not per turn.
    """
    print(f"  {Fore.CYAN}📋  Deep extraction...{Style.RESET_ALL}",
          end="", flush=True)
    import time, json
    start = time.time()

    prompt = _EXTRACTION_PROMPT.format(
        language=language_name,
        conversation=conversation_text,
    )

    try:
        raw = await llm_service.complete(prompt)
        raw = raw.replace("```json","").replace("```","").strip()
        m   = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0) if m else raw)
        print(f" {Fore.GREEN}✅ ({time.time()-start:.2f}s){Style.RESET_ALL}")
        return parsed
    except json.JSONDecodeError:
        print(f" {Fore.YELLOW}⚠️  parse failed{Style.RESET_ALL}")
        return {}
    except Exception as e:
        print(f" {Fore.RED}❌ {e}{Style.RESET_ALL}")
        return {}


# ══════════════════════════════════════════════════════════════════
# STEERING ADVISOR — tells session when to gently guide conversation
# ══════════════════════════════════════════════════════════════════

# A topic counts as "covered" once ANY of its keys has been extracted.
# These names must match what fast_extract() and deep_extract() actually write —
# steering used to compare against the topic names themselves ("bp", "sleep"),
# which never appear as keys, so every topic looked permanently missing and
# Sathi asked about blood pressure on every call regardless of what was said.
TOPIC_KEYS = {
    "sleep": ["sleep_quality"],
    "food":  ["food_intake"],
    "water": ["water_intake"],
    "bp":    ["bp_systolic", "bp_diastolic"],
    "sugar": ["sugar_fasting", "sugar_pp"],
    "mood":  ["mood"],
}

STEER_PRIORITY = ["bp", "sugar", "sleep", "food", "water", "mood"]
VITAL_TOPICS   = ["bp", "sugar"]


def _is_covered(topic: str, extracted_so_far: dict) -> bool:
    """True once any key belonging to this topic holds a real value."""
    for key in TOPIC_KEYS.get(topic, [topic]):
        val = extracted_so_far.get(key)
        if val is not None and val is not False and val != "":
            return True
    return False


def should_steer(turn_number: int,
                 extracted_so_far: dict,
                 critical_topics: list,
                 wrap_up_from: int = 8) -> tuple[bool, str | None]:
    """
    Decides if Sathi should gently steer toward uncovered topics.

    Rules:
    - First 3 turns: NEVER steer — let conversation breathe
    - Turn 4: steer only if a vital (BP/sugar) is still missing
    - Turn 5+: steer toward the most important uncovered topic
    - wrap_up_from onwards: wind down regardless

    Returns (should_steer: bool, topic_to_steer_toward: str | None)
    """
    if turn_number <= 3:
        return False, None

    if turn_number >= wrap_up_from:
        return True, "closing"

    missing = [t for t in critical_topics if not _is_covered(t, extracted_so_far)]
    if not missing:
        return False, None

    # Turn 4 is early — only interrupt the flow for a vital we still don't have.
    candidates = STEER_PRIORITY if turn_number >= 5 else VITAL_TOPICS
    for topic in candidates:
        if topic in missing:
            return True, topic

    return False, None
