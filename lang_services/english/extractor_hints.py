"""English extraction hints."""
HINTS = {
    "sleep_poor": ["didn't sleep","no sleep","couldn't sleep","awake all night","bad sleep","poor sleep"],
    "sleep_good": ["slept well","good sleep","slept nicely","rested"],
    "food_skip":  ["didn't eat","skipped","no food","not hungry","nothing to eat"],
    "food_good":  ["ate","had food","had breakfast","had lunch","had dinner"],
    "water_low":  ["didn't drink water","less water","forgot water","dehydrated"],
    "water_good": ["drinking water","had water","drank water"],
    "mood_low":   ["feeling sad","not well","down","depressed","lonely","tired","exhausted"],
    "mood_good":  ["feeling good","fine","okay","happy","better"],
    "sugar_keywords": ["sugar","blood sugar","glucose","diabetes"],
    "dizziness_kw":   ["dizzy","dizziness","spinning","faint"],
    "headache_kw":    ["headache","head hurts","head pain","heavy head"],
    "chest_kw":       ["chest pain","chest tight","chest heavy"],
    "breathing_bad_kw": ["can't breathe","breathing problem","short of breath"],
}
CRITICAL_TOPICS = ["sleep","food","water","bp","sugar","mood"]

# NOTE: the live steer questions are STEER_QUESTIONS in personality.py, next to
# the prompt that uses them. A duplicate set used to live here and was never read.
