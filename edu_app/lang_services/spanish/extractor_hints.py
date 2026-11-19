"""Spanish extraction hints."""
HINTS = {
    "sleep_poor": ["no dormí", "no pude dormir", "despierto toda la noche", "mal dormir", "insomnio"],
    "sleep_good": ["dormí bien", "buen sueño", "descansé"],
    "food_skip":  ["no comí", "no he comido", "sin comer", "sin hambre", "nada de comida"],
    "food_good":  ["comí", "he comido", "desayuné", "almorcé", "cené"],
    "water_low":  ["no bebí agua", "poca agua", "olvidé el agua", "deshidratado"],
    "water_good": ["bebiendo agua", "tomé agua", "bebo agua"],
    "mood_low":   ["triste", "mal", "deprimido", "solo", "cansado", "agotado"],
    "mood_good":  ["bien", "contento", "feliz", "mejor"],
    "sugar_keywords": ["azúcar", "glucosa", "diabetes"],
    "dizziness_kw":   ["mareo", "mareado", "vértigo", "desmayo"],
    "headache_kw":    ["dolor de cabeza", "me duele la cabeza", "jaqueca"],
    "chest_kw":       ["dolor en el pecho", "pecho apretado", "opresión en el pecho"],
    "breathing_bad_kw": ["no puedo respirar", "falta de aire", "me cuesta respirar"],
}
CRITICAL_TOPICS = ["sleep", "food", "water", "bp", "sugar", "mood"]

# NOTE: the live steer questions are STEER_QUESTIONS in personality.py, next to
# the prompt that uses them. A duplicate set used to live here and was never read.
