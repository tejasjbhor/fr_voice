"""Hindi inbound helpline — mechanics from Saathi Hindi pack."""

from lang_services.hindi.personality import (
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
from lang_services.hindi.tts_config import TTS_CONFIG

CODE = "hi-IN"
NAME = "Hindi"
PACK_VERSION = "hi-inbound-v1"

GREETING = (
    "नमस्ते... मैं {agent} बोल रही हूँ। आपने {service} पर कॉल किया है। "
    "बताइए, मैं आपकी कैसे मदद करूँ?"
)
CLOSING = "कॉल करने के लिए धन्यवाद। अपना ध्यान रखिए।"
EMERGENCY = (
    "यह बात गंभीर लग रही है। कृपया अभी आपातकालीन नंबर पर कॉल कीजिए।"
)
FALLBACK = "माफ़ कीजिए... मैं सुन नहीं पाई। फिर से बोलिए?"
STILL_THERE = "हैलो? आप अभी भी लाइन पर हैं?"

LANGUAGE_RULE = (
    "केवल सरल हिंदी में बोलो। औपचारिक आप का प्रयोग करो, कभी तुम नहीं। "
    "स्त्रीलिंग क्रियाएँ। अधिकतम दो-तीन छोटे वाक्य।"
)

FEWSHOTS = """
Caller: मेडिकल कैंप कहाँ है?
You: मेडिकल कैंप मुख्य द्वार के हेल्प डेस्क के पास है। क्या आप जहाँ हैं वहाँ से रास्ता बताऊँ?
Caller: मेरा बैग खो गया।
You: बैग खोने की बात सुनकर दुख हुआ। रंग क्या था, और आखिरी बार कहाँ देखा था?
Caller: बस इतना ही, धन्यवाद।
You: मदद करके अच्छा लगा। अपना ध्यान रखिए। <<END>>
"""

HINTS = {
    "topics": {
        "रास्ता": "directions",
        "कहाँ": "directions",
        "समय": "timings",
        "खो": "lost_item",
        "बैग": "lost_item",
        "तक्रार": "complaint",
        "मदत": "general_help",
        "आपातकाल": "emergency",
    }
}
