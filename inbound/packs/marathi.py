"""Marathi inbound helpline — mechanics from Saathi Marathi pack."""

from lang_services.marathi.personality import (
    BEREAVEMENT_WORDS,
    DECLINE_WORDS,
    EXIT_WORDS,
    SELF_EXIT_BLOCKERS,
    SELF_EXIT_WORDS,
    UNAVAILABLE_WORDS,
    WRONG_PERSON_WORDS,
    fix_honorifics,
    honorific_slips,
    prepare_for_tts,
)
from lang_services.marathi.tts_config import TTS_CONFIG

CODE = "mr-IN"
NAME = "Marathi"
PACK_VERSION = "mr-inbound-v1"

GREETING = (
    "नमस्कार... मी {agent} बोलतेय. तुम्ही {service} वर कॉल केला आहे. "
    "सांगा, मी तुमची कशी मदत करू?"
)
CLOSING = "कॉल केल्याबद्दल धन्यवाद. आपली काळजी घ्या."
EMERGENCY = (
    "ही गोष्ट गंभीर वाटते. कृपया आत्ताच आपत्कालीन क्रमांकावर कॉल करा."
)
FALLBACK = "माफ करा... मला ऐकू आलं नाही. पुन्हा सांगाल का?"
STILL_THERE = "हॅलो? तुम्ही अजून लाइनवर आहात का?"

LANGUAGE_RULE = (
    "फक्त सोप्या मराठीत बोला. औपचारिक तुम्ही वापरा, कधीच तू/तुम्ही चुकीचे मिश्रण नाही. "
    "स्त्रीलिंग क्रियापद. दोन-तीन छोटे वाक्य."
)

FEWSHOTS = """
Caller: मेडिकल कॅम्प कुठे आहे?
You: मेडिकल कॅम्प मुख्य प्रवेशद्वाराच्या हेल्प डेस्कजवळ आहे. तुम्ही कुठून येत आहात ते सांगाल का?
Caller: माझी बॅग हरवली.
You: बॅग हरवल्याचं ऐकून वाईट वाटलं. रंग काय होता आणि शेवटचं कुठे पाहिली होती?
Caller: झालं, धन्यवाद.
You: मदत करून बरं वाटलं. आपली काळजी घ्या. <<END>>
"""

HINTS = {
    "topics": {
        "कुठे": "directions",
        "रस्ता": "directions",
        "वेळ": "timings",
        "हरव": "lost_item",
        "बॅग": "lost_item",
        "तक्रार": "complaint",
        "मदत": "general_help",
        "आपत्काल": "emergency",
    }
}
