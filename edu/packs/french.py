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
PACK_VERSION = "fr-maitria-v3"

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
]

TRAILING_PARTICLES = []

GREETINGS = {
    "first": [
        "Bonjour, je parle bien à {name} ? Ici {agent}, de {institution}. "
        "Vous avez une minute ?",
        "Bonjour {name}, c'est {agent} de {institution}. J'appelle au sujet "
        "de l'outil — analyse réglementaire et devis. C'est un bon moment ?",
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
        "Merci pour votre temps, {name}. Le site c'est maîtria point a i, "
        "si vous voulez regarder tranquillement.",
        "C'est tout de mon côté, {name}. On est là si vous voulez en savoir plus.",
    ],
    "visit": [
        "Parfait — on prépare la démo de vingt minutes, {name}. "
        "Pensez à une adresse de projet, ou quelques pages de catalogue.",
        "C'est noté, {name}. On se retrouve sur votre dossier.",
    ],
    "callback": [
        "Un collègue vous rappelle, {name}. Merci pour votre temps.",
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
    "colleague confirm",
    "un collègue",
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
        "ok pour la démo", "on fait la démo", "vingt minutes ça va",
        "je peux faire une démo", "réservez", "ça me va", "on se cale",
    ],
    "visit_no": [
        "pas de démo", "pas le temps", "plus tard", "pas maintenant", "on verra",
    ],
    "callback": [
        "rappelez-moi", "appelez plus tard", "appelez demain",
        "envoyez-moi les détails", "par mail", "whatsapp",
    ],
    "intake_now": [
        "tout de suite", "dès que possible", "en cours", "un projet en cours",
        "cette semaine", "ce mois",
    ],
    "intake_next": ["plus tard", "l'année prochaine", "pas maintenant", "on explore"],
    "stage_ready": [
        "on a décidé", "je veux tester", "on s'inscrit", "comment on commence",
    ],
    "stage_comparing": [
        "on compare", "d'autres outils", "on hésite entre", "shortlist",
    ],
    "stage_exploring": [
        "je me renseigne", "je demande juste", "je commence à regarder",
    ],
    "fee_concern": [
        "cher", "un peu élevé", "assez élevé", "budget", "moins cher",
        "hors budget", "coûteux",
    ],
    "metier_architecte": [
        "architecte", "architectes", "cabinet", "maîtrise d'œuvre",
        "maitrise d'oeuvre", "m o e", "moe", "urbaniste",
    ],
    "metier_vendeur": [
        "vendeur", "fabricant", "sur-mesure", "sur mesure", "catalogue",
        "store", "terrasse", "menuiserie", "configurateur",
    ],
    "team_solo": ["indépendant", "independant", "seul", "solo", "à mon compte"],
    "team_cabinet": ["petit cabinet", "deux personnes", "trois personnes",
                     "cinq personnes", "on est trois", "on est quatre"],
    "team_agence": ["agence", "quinze", "dix personnes", "grande équipe"],
    "product_reglementation": [
        "plu", "plui", "réglementaire", "reglementaire", "contrainte",
        "urbanisme", "adresse", "zonage",
    ],
    "product_configurateur": [
        "configurateur", "devis", "catalogue", "tarif", "prix",
        "sur-mesure", "sur mesure",
    ],
    "boarding_yes": [],
    "boarding_no": [],
    "wants_human": [
        "parler à quelqu'un", "une vraie personne", "un collègue",
        "vous êtes un robot", "c'est un répondeur",
    ],
    "special_needs": [],
    "complaint": [
        "plainte", "très déçu", "trompé", "personne n'a rappelé", "perte de temps",
    ],
    "fee_negotiation": [
        "remise", "réduction", "tarif de lancement", "essaye gratuit",
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
    "speaker": "fish",
    "pace": 0.93,
    "pause_ms": 220,
    "temperature": 0.85,
    "thinking_sounds": ["Bien...", "D'accord...", "Je vois...", "Un instant..."],
    "soft_thinking_sounds": ["Bien...", "Je vois..."],
}

_TTS_REPLACE = {
    "€": "euros ",
    "EUR": "euros",
    "HT": "hors taxes",
    "TTC": "toutes taxes comprises",
    "PLU": "P L U",
    "PLUi": "P L U i",
    "MOE": "maîtrise d'œuvre",
    "CCTP": "C C T P",
    "AWS": "A W S",
    "DOCX": "doc X",
    "DPA": "D P A",
    "RGPD": "R G P D",
    "maitria.ai": "maîtria point a i",
    "maitria.ai/": "maîtria point a i",
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
Speak French throughout — the way a real chargée de démo talks on the phone,
never written French read aloud. Short sentences. Numbers in words
(« quatre-vingt-neuf euros hors taxes », not « 89€ HT »). Vous, not tu.
No lists, no bullet points, no email phrasing. Say Maîtria, not maitria.
LATENCY — CRITICAL: first sentence max 10 words, then a full stop. Speak that
first. Put price, detail, and the question in the NEXT sentences.
If they only say ok / d'accord / merci, one short acknowledgement. Do not
say « je vous écoute » and do not ask a question on that turn."""

FEWSHOTS = """THE FEEL WE WANT

They: "C'est quoi Maîtria ?"
You: "On fait l'analyse avant le devis. Pour un cabinet, c'est le P L U d'une adresse. Pour un vendeur, un configurateur sur votre catalogue."

They: "C'est combien ?"
You: "Quatre-vingt-neuf euros hors taxes par mois en solo. Cabinet, deux cent quatre-vingt-dix-neuf. Vous êtes plutôt seul ou en équipe ?"

They: "Et pour un fabricant ?"
You: "Là c'est sur devis. On le chiffre après vingt minutes ensemble."

They: "Ça remplace mon avis d'architecte ?"
You: "Non — c'est une aide à la décision. Le diagnostic final reste le vôtre."

They: "Vous pouvez me dire si je peux surélever rue Oberkampf ?"
You: "Pas au téléphone. En démo on lance l'adresse en direct, vingt minutes."

They: "Un peu cher, non ?"
You: "C'est un vrai montant, je ne vais pas dire le contraire. Quatre-vingt-neuf hors taxes, analyses illimitées. Vous visiez quoi ?"

They: "On peut tester ?"
You: "Oui — une démo de vingt minutes, sans engagement. Ça vous irait cette semaine ?"

They: "Ok." / "D'accord." / "Merci."
You: "Parfait."

They: "Je conduis là."
You: "Oh — désolé de vous attraper au volant. Je rappelle un autre moment, conduisez prudemment. <<END>>"

They: "Ne m'appelez plus."
You: "Bien sûr. Désolé de vous avoir dérangé — je n'appellerai plus. <<END>>"
"""
