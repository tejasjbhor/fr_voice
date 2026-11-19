"""
lang_services/marathi/extractor_hints.py
Marathi-specific keywords for fast health data extraction.
Used by core/extractor.py fast_extract().
"""

HINTS = {
    # Sleep
    "sleep_poor": [
        "झोप नाही", "झोपलो नाही", "झोप नीट नाही", "रात्री जागा",
        "जागा राहिलो", "उशिरापर्यंत जागा", "झोप उडाली", "नीट झोप नाही",
        "झोप येत नाही", "अर्धी झोप",
    ],
    "sleep_good": [
        "झोप छान", "नीट झोपलो", "चांगली झोप", "शांत झोप",
        "भरपूर झोपलो",
    ],

    # Food
    "food_skip": [
        "जेवण नाही", "जेवलो नाही", "भूक नाही", "खाल्लं नाही",
        "उपाशी", "जेवण सोडलं", "जेवण नाही केलं",
    ],
    "food_good": [
        "जेवण झालं", "जेवलो", "छान जेवलो", "नीट जेवलो",
        "जेवण केलं",
    ],

    # Water
    "water_low": [
        "पाणी कमी", "पाणी नाही प्यालो", "पाणी विसरलो",
        "पाणी कमी पिलं",
    ],
    "water_good": [
        "पाणी पिलं", "भरपूर पाणी", "पाणी नीट पिलं",
    ],

    # Mood
    "mood_low": [
        "उदास", "बरं नाही वाटत", "थकलेलो", "दुःखी", "एकटं वाटतं",
        "मन खाली", "उत्साह नाही", "कंटाळा",
    ],
    "mood_good": [
        "बरं वाटतं", "छान वाटतं", "आनंदी", "खुश", "मस्त",
    ],

    # Sugar keyword signals
    "sugar_keywords": [
        "साखर", "शुगर", "sugar", "ग्लुकोज",
    ],

    # Symptoms
    "dizziness_kw":     ["चक्कर", "गरगर", "घेरी", "चक्कर आली"],
    "headache_kw":      ["डोकेदुखी", "डोकं दुखतं", "डोकं जड"],
    "chest_kw":         ["छाती दुखत", "छातीत", "छाती जड"],
    "breathing_bad_kw": ["श्वास घेत नाही", "श्वास त्रास", "श्वास अडतो"],
}

# Topics that need to be covered each call (in priority order)
CRITICAL_TOPICS = ["sleep", "food", "water", "bp", "sugar", "mood"]

# NOTE: the live steer questions are STEER_QUESTIONS in personality.py, next to
# the prompt that uses them. A duplicate set used to live here and was never read.
