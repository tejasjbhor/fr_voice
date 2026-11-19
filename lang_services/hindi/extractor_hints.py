"""Hindi extraction hints."""
HINTS = {
    "sleep_poor": ["नींद नहीं","नहीं सोया","नींद खराब","रात जागे","उठता रहा","नींद नहीं आई"],
    "sleep_good": ["नींद अच्छी","अच्छी नींद","सो गया","नींद पूरी हुई"],
    "food_skip":  ["खाना नहीं","नहीं खाया","भूख नहीं","खाना छोड़ा","उपवास"],
    "food_good":  ["खाना खाया","खा लिया","खाना हो गया","खाना अच्छा था"],
    "water_low":  ["पानी कम","पानी नहीं पिया","पानी भूल गया"],
    "water_good": ["पानी पिया","पानी पी रहा हूँ","पानी ठीक है"],
    "mood_low":   ["उदास","दुखी","अकेला","थका हुआ","ठीक नहीं लग रहा","मन नहीं"],
    "mood_good":  ["ठीक हूँ","अच्छा लग रहा","खुश हूँ","मज़ा आया"],
    "sugar_keywords": ["शुगर","sugar","ग्लूकोज","मधुमेह"],
    "dizziness_kw":   ["चक्कर","घूम रहा","सिर घूमा"],
    "headache_kw":    ["सिरदर्द","सिर में दर्द","सिर भारी"],
    "chest_kw":       ["छाती में दर्द","छाती भारी","सीने में"],
    "breathing_bad_kw": ["साँस नहीं","साँस तकलीफ","साँस अटकती"],
}

CRITICAL_TOPICS = ["sleep","food","water","bp","sugar","mood"]

# NOTE: the live steer questions are STEER_QUESTIONS in personality.py, next to
# the prompt that uses them. A duplicate set used to live here and was never read.
