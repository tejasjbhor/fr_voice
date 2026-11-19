"""French extraction hints."""
HINTS = {
    "sleep_poor": ["pas dormi", "pas pu dormir", "éveillé toute la nuit", "mal dormi", "insomnie"],
    "sleep_good": ["bien dormi", "bon sommeil", "j'ai reposé"],
    "food_skip":  ["pas mangé", "rien mangé", "sans manger", "pas faim", "sauté le repas"],
    "food_good":  ["j'ai mangé", "petit-déjeuner", "déjeuner", "dîner"],
    "water_low":  ["pas bu d'eau", "peu d'eau", "oublié l'eau", "déshydraté"],
    "water_good": ["bu de l'eau", "je bois de l'eau", "assez d'eau"],
    "mood_low":   ["triste", "mal", "déprimé", "seul", "seule", "fatigué", "épuisé"],
    "mood_good":  ["bien", "content", "heureuse", "heureux", "mieux"],
    "sugar_keywords": ["sucre", "glucose", "diabète"],
    "dizziness_kw":   ["vertige", "étourdi", "malaise", "évanoui"],
    "headache_kw":    ["mal de tête", "migraine", "céphalée"],
    "chest_kw":       ["mal à la poitrine", "poitrine serrée", "oppression"],
    "breathing_bad_kw": ["peux pas respirer", "manque d'air", "souffle court"],
}
CRITICAL_TOPICS = ["sleep", "food", "water", "bp", "sugar", "mood"]
