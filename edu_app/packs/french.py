"""
edu/packs/french.py — French (fr-FR) language spec.

STT is Gladia. TTS is ElevenLabs. Behavioural rules stay in English
(edu/persona.py); few-shots and spoken lines are French.
"""

import re as _re

from edu.tail_text import FAREWELL, STEER_QUESTIONS  # noqa: F401

from lang_services.french.personality import (
    BEREAVEMENT_WORDS,
    DECLINE_WORDS,
    EMERGENCY_KEYWORDS,
    EXIT_WORDS as _BASE_EXIT_WORDS,
    SELF_EXIT_BLOCKERS as _BASE_SELF_EXIT_BLOCKERS,
    SELF_EXIT_WORDS,
    UNAVAILABLE_WORDS as _BASE_UNAVAILABLE_WORDS,
    WRONG_PERSON_WORDS,
)

CODE = "fr-FR"
NAME = "French"
PACK_VERSION = "fr-edu-v1"

EXIT_WORDS = list(_BASE_EXIT_WORDS)

UNAVAILABLE_WORDS = list(_BASE_UNAVAILABLE_WORDS) + [
    "au travail",
    "au bureau",
    "je vais chercher",
    "je dépose",
]

SELF_EXIT_BLOCKERS = list(_BASE_SELF_EXIT_BLOCKERS) + [
    "laissez-moi envoyer",
    "je vous envoie",
    "avant que vous partiez",
    "changer d'école",
    "quitte l'école",
]

TRAILING_PARTICLES = []

GREETINGS = {
    "first": [
        "Bonjour, je parle bien à {name} ? Ici {agent}, de {institution}. "
        "Vous avez une minute pour l'admission ?",
        "Bonjour {name}, c'est {agent} de {institution}. J'appelle au sujet "
        "des admissions pour la rentrée — c'est un bon moment ?",
    ],
    "callback": [
        "Bonjour {name}, c'est {agent} de {institution} à nouveau. C'est un "
        "meilleur moment ?",
        "Bonjour {name}, {agent} de {institution} — on s'est parlé il y a "
        "peu. Vous avez une minute maintenant ?",
    ],
}

CLOSINGS = {
    "neutral": [
        "Merci pour votre temps, {name}. N'hésitez pas à nous rappeler.",
        "C'est tout de mon côté, {name}. On est là si vous voulez en savoir plus.",
    ],
    "visit": [
        "Parfait — on vous attend, {name}. Quelqu'un vous enverra le plan.",
        "C'est noté, {name}. Au plaisir de vous rencontrer.",
    ],
    "callback": [
        "Notre conseiller vous rappellera, {name}. Merci pour votre temps.",
        "Quelqu'un vous recontacte bientôt, {name}. Merci d'avoir pris l'appel.",
    ],
}

GREETING = "Bonjour {name}, ici {agent} de {institution}."
CLOSING = "Merci pour votre temps, {name}."
FALLBACK = "Pardon, je n'ai pas bien compris. Vous pouvez répéter ?"
STILL_THERE = "{name} ? Vous êtes toujours là ? Je ne vous entends plus."
EMERGENCY = (
    "Ça a l'air grave. Appelez le quinze tout de suite — je vous laisse."
)

DEFER_MARKERS = [
    "counsellor confirm",
    "conseiller confirmer",
    "notre conseiller",
    "je ferai confirmer",
    "réponse exacte",
    "confirm",
]

HINTS = {
    "question_cues": [
        "quoi", "comment", "quand", "où", "quel", "qui", "pourquoi",
        "est-ce que", "pouvez-vous", "y a-t-il", "dites-moi", "je voudrais savoir",
    ],
    "visit_yes": [
        "je viens", "on vient", "je peux venir", "on peut venir",
        "samedi ça marche", "dimanche ça marche", "réservez", "ça me va",
    ],
    "visit_no": [
        "je ne peux pas venir", "trop loin", "pas le temps de visiter",
        "plus tard", "pas maintenant", "on verra",
    ],
    "callback": [
        "rappelez-moi", "appelez plus tard", "appelez demain",
        "envoyez-moi les détails", "whatsapp",
    ],
    "intake_now": [
        "cette année", "cette rentrée", "tout de suite", "dès que possible",
        "avril", "juin",
    ],
    "intake_next": ["l'année prochaine", "la rentrée suivante", "pas cette année"],
    "stage_ready": [
        "on a décidé", "je veux postuler", "prêt à postuler", "comment postuler",
        "remplir le dossier",
    ],
    "stage_comparing": [
        "on compare", "plusieurs écoles", "d'autres écoles", "shortlist",
        "on hésite entre",
    ],
    "stage_exploring": [
        "je me renseigne", "je demande juste", "je commence à regarder",
    ],
    "fee_concern": [
        "cher", "un peu élevé", "assez élevé", "budget", "moins cher",
        "hors budget", "coûteux", "baisser les frais",
    ],
    "boarding_yes": ["internat", "pension", "dormir sur place"],
    "boarding_no": ["externe", "rentrer à la maison", "pas d'internat"],
    "wants_human": [
        "parler à quelqu'un", "une vraie personne", "le proviseur",
        "un conseiller", "vous êtes un robot", "c'est un répondeur",
    ],
    "special_needs": [
        "besoins particuliers", "dyslexie", "autisme", "tdah",
        "fauteuil", "appareil auditif",
    ],
    "complaint": [
        "plainte", "très déçu", "trompé", "personne n'a rappelé", "perte de temps",
    ],
    "fee_negotiation": [
        "remise", "bourse", "réduction", "frère", "sœur", "assouplir",
    ],
    "rushed": ["vite", "pressé", "faites vite", "pas le temps"],
    "hesitant": ["pas sûr", "je ne sais pas", "je dois réfléchir", "peut-être"],
    "annoyed": [
        "je vous l'ai déjà dit", "arrêtez d'appeler", "pas intéressé", "laissez-moi",
    ],
    "keen": [
        "ça m'intéresse", "très bien", "dites-m'en plus", "intéressé",
    ],
}

CRITICAL_TOPICS = ["grade", "child_age", "locality", "intake", "visit_intent"]
NUMERALS = {"ordinals": {}, "numbers": {}}

TTS_CONFIG = {
    "speaker": "elevenlabs",
    "pace": 0.95,
    "pause_ms": 320,
    "temperature": 0.7,
    "thinking_sounds": ["Bien...", "D'accord...", "Je vois...", "Un instant..."],
    "soft_thinking_sounds": ["Bien...", "Je vois..."],
}

_TTS_REPLACE = {
    "€": "euros ",
    "EUR": "euros",
    "HT": "hors taxes",
    "TTC": "toutes taxes comprises",
    "&": "et",
}

_PROSODY = [
    (_re.compile(r"\s+"), " "),
]


def prepare_for_tts(text: str) -> str:
    for abbr, spoken in _TTS_REPLACE.items():
        text = _re.sub(rf"(?<![A-Za-z]){_re.escape(abbr)}(?![A-Za-z])", spoken, text)
    for pattern, replacement in _PROSODY:
        text = pattern.sub(replacement, text)
    text = _re.sub(r"[*_~`#→•]", "", text)
    return text.strip()


_TONE_SIGNALS = {
    "worried": HINTS["annoyed"] + HINTS["hesitant"],
    "tired": HINTS["rushed"],
    "happy": HINTS["keen"],
}


def read_tone(text: str) -> str | None:
    folded = (text or "").lower()
    if not folded.strip():
        return None
    for tone in ("worried", "tired", "happy"):
        if any(cue in folded for cue in _TONE_SIGNALS[tone]):
            return tone
    return None


LANGUAGE_RULE = """LANGUAGE
Speak French throughout. Natural spoken register, never written French read
aloud. Short sentences. Numbers in words when spoken."""

FEWSHOTS = """THE FEEL WE WANT

They: "C'est combien pour la cinquième ?"
You: "Pour la cinquième, c'est quatre-vingt-douze mille euros l'année, fournitures et uniforme compris."

They: "Avec le transport ?"
You: "Non, le transport est à part — entre huit et douze mille selon le quartier. Vous êtes de quel côté ?"

They: "Un peu cher, non ?"
You: "C'est un vrai montant, je ne vais pas dire le contraire. Vous visiez combien, à peu près ? Je vous dirai honnêtement si on rentre."

They: "Quel est votre programme ?"
You: "On est sur un cursus jusqu'en terminale."

They: "Vous avez un internat ?"
You: "Non, on est un externat seulement. Si l'internat est indispensable, on ne serait pas le bon choix."

They: "Je peux venir voir ?"
You: "Bien sûr — les samedis matin vers onze heures, c'est le plus simple. Ça vous irait ce samedi ?"

They: "Je conduis là."
You: "Oh — désolé de vous attraper au volant. Je rappelle un autre moment, conduisez prudemment. <<END>>"

They: "Ne m'appelez plus."
You: "Bien sûr. Désolé de vous avoir dérangé — je n'appellerai plus. <<END>>"
"""
