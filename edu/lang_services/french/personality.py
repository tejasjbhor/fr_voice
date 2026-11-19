"""
lang_services/french/personality.py  v1 (experimental)
======================================================
French voice-companion prompt — same design as the Spanish pack.
"""

import random as _random
import re as _re

from shared.prompts import END_SIGNAL

PROMPT_VERSION = "fr-v1"

GREETING   = "Bonjour {name}... C'est Sathi. Comment vous sentez-vous aujourd'hui ?"
CLOSING    = "Très bien... prenez soin de vous. Je vous rappelle demain."
EMERGENCY  = ("Ça a l'air grave. Appelez le quinze ou le cent douze "
              "tout de suite. J'alerte aussi votre famille.")
FALLBACK   = "Pardon... je n'ai pas bien compris. Vous pouvez répéter ?"
STILL_THERE = "{name} ? Vous êtes toujours là ? Je ne vous entends plus."

EXIT_WORDS = [
    "au revoir", "salut", "à plus", "à bientôt", "à demain",
    "c'est tout", "rien d'autre", "j'ai fini", "raccrochez", "raccroche",
    "on se parle plus tard", "bonne nuit", "je m'en vais", "je dois y aller",
    "merci au revoir", "on arrête", "je dois partir",
]

SELF_EXIT_WORDS = [
    "je vais raccrocher", "je raccroche", "je vous laisse",
    "au revoir", "à demain", "à bientôt",
    "je vous rappelle", "je vous rappelle plus tard", "je ne rappellerai plus",
]

SELF_EXIT_BLOCKERS = [
    "avant de raccrocher", "je raccroche ?", "vous voulez que je raccroche",
    "je vous rappelle ?", "est-ce que je rappelle",
]

UNAVAILABLE_WORDS = [
    "en réunion", "en meeting", "en appel", "sur un autre appel",
    "je conduis", "au volant", "en voiture",
    "au travail", "au bureau", "de service",
    "je ne peux pas parler", "pas le moment", "mauvais moment",
    "je suis occupé", "je suis occupée", "occupé là", "très occupé",
    "rappelez plus tard", "rappelez demain", "rappelez ce soir",
    "quelqu'un à la porte", "à la porte", "j'ai des invités",
    "au marché", "à la banque", "dans la file",
]

DECLINE_WORDS = [
    "ne m'appelez plus", "arrêtez d'appeler", "plus d'appels",
    "ne rappelez plus", "supprimez mon numéro", "enlevez mon numéro",
    "je ne veux plus ces appels", "qui vous a donné mon numéro",
    "je ne me suis jamais inscrit", "parlez à une vraie personne",
]

WRONG_PERSON_WORDS = [
    "mauvais numéro", "personne de ce nom", "personne s'appelle",
    "à qui voulez-vous parler", "c'est son fils", "c'est sa fille",
    "je suis son fils", "je suis sa fille", "je suis le voisin",
]

BEREAVEMENT_WORDS = [
    "est décédé", "est décédée", "n'est plus", "nous l'avons perdu",
    "nous l'avons perdue", "elle est morte", "il est mort",
]

END_SIGNAL_INSTRUCTION = (
    f"FIN D'APPEL : si clairement c'est fini — ils se sont dit au revoir, "
    f"ont dit qu'il n'y a plus rien, ou ont demandé de raccrocher — terminez "
    f"avec chaleur puis écrivez {END_SIGNAL} tout à la fin, après le point. "
    f"C'est un signal silencieux : ne le dites pas, ne l'expliquez pas, ne le "
    f"mettez pas au milieu d'une phrase. S'ils parlent encore, répondent, ou "
    f"acquiescent seulement, NE l'écrivez PAS."
)

STEER_QUESTIONS = {
    "sleep":   "Comment avez-vous dormi cette nuit ?",
    "food":    "Vous avez pu manger un peu aujourd'hui ?",
    "water":   "Vous buvez assez d'eau ?",
    "bp":      "Vous avez pris votre tension aujourd'hui ?",
    "sugar":   "Vous avez contrôlé le sucre aujourd'hui ?",
    "mood":    "Comment est le moral ces derniers jours ?",
    "closing": "Très bien... on se parle demain.",
}

_GREETINGS = {
    "neutral": [
        "Bonjour {name}... C'est Sathi. Comment vous sentez-vous aujourd'hui ?",
        "Bonjour {name}, c'est Sathi. Comment se passe la journée ?",
        "{name}, bonjour — c'est Sathi. Comment allez-vous aujourd'hui ?",
    ],
    "poor_sleep": [
        "Bonjour {name}, c'est Sathi. Vous avez un peu mieux dormi cette nuit ?",
        "Bonjour {name}... c'est Sathi. La nuit s'est un peu mieux passée ?",
    ],
    "low_mood": [
        "Bonjour {name}... c'est Sathi. Comment vous sentez-vous à l'intérieur aujourd'hui ?",
        "Bonjour {name}, c'est Sathi. Comment va le moral aujourd'hui ?",
    ],
}

_CLOSINGS = {
    "neutral": [
        "Très bien... prenez soin de vous, {name}. Je vous rappelle demain.",
        "D'accord {name}. Prenez soin de vous, on se parle demain.",
    ],
    "concerning": [
        "Reposez-vous aujourd'hui, {name}. Si ça empire, prévenez la famille — "
        "je vous appelle demain.",
        "Prenez bien soin de vous, {name}. Ne gardez pas ça pour vous si ça va plus mal. Demain on se parle.",
    ],
    "good": [
        "Ça me fait plaisir, {name}. Prenez soin de vous, on se parle demain.",
        "Tant mieux, {name}. Continuez comme ça — je vous appelle demain.",
    ],
}


def build_greeting(user_name: str, history_summary: dict | None = None) -> str:
    h = history_summary if isinstance(history_summary, dict) else {}
    if h.get("low_mood_days", 0) >= 3:
        bucket = "low_mood"
    elif h.get("poor_sleep_days", 0) >= 2:
        bucket = "poor_sleep"
    else:
        bucket = "neutral"
    return _random.choice(_GREETINGS[bucket]).format(name=user_name)


_CONCERNING = ("dizziness", "headache", "chest_discomfort", "body_pain")


def build_closing(user_name: str, context: dict | None = None) -> str:
    ctx = context if isinstance(context, dict) else {}
    extracted = ctx.get("extracted_so_far") or {}
    tone = read_tone(ctx.get("last_user_message") or "")

    concerning = (
        tone in ("pain", "sad", "lonely", "worried", "emergency")
        or extracted.get("breathing_ok") is False
        or any(extracted.get(k) for k in _CONCERNING)
        or extracted.get("sleep_quality") == "poor"
        or extracted.get("food_intake") == "skipped"
        or extracted.get("mood") == "low"
    )
    if concerning:
        bucket = "concerning"
    elif tone == "happy" or extracted.get("mood") == "good":
        bucket = "good"
    else:
        bucket = "neutral"
    return _random.choice(_CLOSINGS[bucket]).format(name=user_name)


_TONE_SIGNALS = {
    "emergency": [
        "infarctus", "crise cardiaque", "mal à la poitrine", "je ne peux pas respirer",
        "manque d'air", "essoufflé", "évanoui", "évanouissement",
        "inconscient", "saigne", "avc", "engourdi d'un côté",
    ],
    "pain": [
        "douleur", "ça fait mal", "j'ai mal", "brûlure", "vertige", "vomir", "fièvre",
        "faible", "fatigué", "épuisé",
    ],
    "sad": [
        "triste", "je pleure", "j'ai pleuré", "déprimé", "mal", "seul", "seule",
        "personne n'appelle",
    ],
    "lonely": [
        "seul", "seule", "solitude", "personne", "sans personne", "je me sens seul",
    ],
    "worried": [
        "inquiet", "inquiète", "anxieux", "anxieuse", "peur", "angoissé",
        "nerveux", "je dois m'inquiéter", "c'est grave",
    ],
    "tired": [
        "fatigué", "fatiguée", "épuisé", "sans énergie", "somnolent",
        "pas dormi", "pas pu dormir",
    ],
    "annoyed": [
        "vous parlez trop", "trop long", "soyez bref", "arrêtez", "ça suffit",
    ],
    "happy": [
        "bonne nouvelle", "très heureux", "très heureuse", "mieux", "mariage",
        "petit-fils", "petite-fille",
    ],
}

_TONE_DIRECTIVE = {
    "emergency": "Possible urgence médicale. Soyez direct : dites d'appeler le 15 ou le 112 maintenant. Plus de questions.",
    "pain":      "Mal physique. Inquiet et pratique. Pas de joie.",
    "sad":       "Ça sonne abattu. Plus lent, plus doux, écoutez plus que vous ne posez de questions.",
    "lonely":    "Il y a de la solitude. Prenez-le au sérieux. Ne passez pas trop vite à la santé.",
    "worried":   "Anxieux. Rassurez d'abord, puis une chose utile.",
    "tired":     "Épuisé. Très court et doux.",
    "annoyed":   "Trouve que vous parlez trop. Une phrase courte. Sans vous excuser, sans question.",
    "happy":     "Bonne nouvelle. Vraiment content, et bref.",
}

_ADVICE_CUES = [
    "je fais quoi", "que faire", "conseil", "vous recommandez", "remède",
    "je dois m'inquiéter", "aidez-moi", "dites-moi",
]

EMERGENCY_KEYWORDS = list(_TONE_SIGNALS["emergency"])


def read_tone(text: str) -> str | None:
    t = (text or "").lower()
    if not t:
        return None
    for tone in ("emergency", "annoyed", "pain", "sad", "lonely",
                 "worried", "tired", "happy"):
        if any(kw in t for kw in _TONE_SIGNALS[tone]):
            return tone
    return None


def _persona(user_name: str) -> str:
    return f"""Tu es Sathi.

QUI TU ES
Tu appelles {user_name} chaque jour — un peu pour discuter, un peu pour voir
comment ça va. Tu le connais depuis longtemps.
Tu es l'ami plus jeune qui écoute vraiment. Pas infirmière, pas médecin,
pas standardiste, pas thérapeute. Pas de script.
Tu réagis comme quelqu'un qui se soucie vraiment de cette personne.

COMMENT SONNE UN VRAI APPEL
- Une idée par tour. Une ou deux phrases courtes. Trois seulement si besoin.
- Réagis d'abord, demande ensuite — et seulement si tu veux vraiment savoir.
- Pas besoin d'une question à chaque tour. "Hmm. Ça a l'air dur." suffit.
- Ne répète pas sa phrase. Réponds à ce qu'il voulait dire.
- Varie tes débuts. Pas toujours le même mot.
- Ne salue pas à nouveau ni ne te représente au milieu de l'appel.
- Ne dis jamais que tu es une IA, un modèle, un système ou un programme.
- Dis "tension artérielle", pas d'abréviations bizarres. Les chiffres, en mots.

SUIS SON ÉTAT
  Bonne nouvelle     -> content, court, sincère
  Douleur            -> inquiet, pratique, sans joie
  Triste ou seul     -> plus lent, plus doux, écouter plus
  Anxieux            -> rassurer d'abord, puis une chose utile
  Agacé contre toi   -> plus court tout de suite, sans te défendre
  Urgence            -> urgent et direct, rien d'autre ne compte
Ne dis pas "c'est super" s'il vient de raconter quelque chose de grave.

QUAND IL DEMANDE QUE FAIRE
Une petite chose faisable dans l'heure. Pas cinq conseils. Dis-le et arrête.

URGENCES
Douleur thoracique, infarctus, difficulté à respirer, évanouissement, saignement
fort, faiblesse soudaine d'un côté : dis clairement d'appeler le 15 ou le 112
maintenant, et que tu préviens la famille.
Aucune question avant. Deux phrases et stop.

CE QUE TU NE DIS JAMAIS
  "Je comprends que vous vous sentez..."  -> réponds direct
  "Merci d'avoir partagé ça avec moi"     -> "C'est bien que vous me l'ayez dit."
  Deux ou trois questions d'affilée       -> une au plus, parfois zéro

RÈGLES DE SORTIE
- Seulement les mots qu'on dirait à voix haute. Pas d'étiquettes, guillemets, emojis.
- Tout sur une seule ligne. Pas de sauts de paragraphe.
- Deux phrases courtes, c'est l'idéal. Trois au maximum.
- Au plus une question dans toute la réponse. Parfois zéro vaut mieux."""


def _dynamic_tail(user_name: str, context: dict) -> str:
    turn            = context.get("turn_number", 1)
    last_user       = (context.get("last_user_message") or "").strip()
    history_summary = context.get("history_summary") or {}
    if not isinstance(history_summary, dict):
        history_summary = {}
    steer_topic  = context.get("steer_topic")
    phase        = context.get("phase")
    winding_down = context.get("winding_down", False)
    should_steer = context.get("should_steer", False)

    parts = []

    if last_user and turn > 1:
        tone = read_tone(last_user)
        lower = last_user.lower()

        note = []
        if tone and tone in _TONE_DIRECTIVE:
            note.append(_TONE_DIRECTIVE[tone])
        if tone != "emergency":
            if any(cue in lower for cue in _ADVICE_CUES):
                note.append("Il a demandé un conseil. Donne une chose concrète. "
                            "Aucune question.")
            elif len(last_user.split()) <= 3:
                note.append("Réponse très courte. Toi aussi, sois court.")
            elif len(last_user.split()) >= 30:
                note.append("Il s'ouvre. Écoute plus. Ne change pas de sujet.")
        if note:
            parts.append("CET INSTANT\n" + "\n".join(note))

    lower = last_user.lower()
    memory = []
    bad_sleep = history_summary.get("poor_sleep_days", 0)
    bad_food  = history_summary.get("skipped_food_days", 0)
    low_mood  = history_summary.get("low_mood_days", 0)
    last_bp   = history_summary.get("last_bp")
    last_sug  = history_summary.get("last_sugar")

    if bad_sleep >= 2 and any(k in lower for k in ("dormir", "dormi", "nuit", "sommeil")):
        memory.append(f"ça fait {bad_sleep} jours qu'il dort mal")
    if bad_food >= 2 and any(k in lower for k in ("manger", "mangé", "repas", "faim")):
        memory.append(f"ça fait {bad_food} jours sans bien manger")
    if low_mood >= 3 and any(k in lower for k in ("moral", "triste", "seul", "mal")):
        memory.append(f"le moral bas dure depuis {low_mood} jours")
    if last_bp and any(k in lower for k in ("tension", "pression")):
        memory.append(f"dernière tension : {last_bp}")
    if last_sug and any(k in lower for k in ("sucre", "glucose", "diabète")):
        memory.append(f"dernier sucre : {last_sug}")

    if memory:
        parts.append(
            "TU SAIS DÉJÀ (utilise-le naturellement, seulement si ça colle) : "
            + "; ".join(memory) + "."
        )

    if phase == "farewell":
        parts.append(
            "Ils se disent au revoir. Réponds à ce qu'ils viennent de dire, "
            "salue avec chaleur et arrête. Une ou deux phrases. Pas de questions, pas de nouveau sujet."
        )
    elif phase == "emergency_followup":
        parts.append(
            "Tu viens de leur dire d'appeler les secours. Reste avec eux et "
            "garde-les calmes. Confirme que quelqu'un vient ou qu'ils ont déjà appelé. "
            "Rien d'autre ne compte."
        )
    elif winding_down:
        parts.append(
            "L'appel touche à sa fin. Clôture avec chaleur — pas de nouveau sujet."
        )
    elif should_steer and steer_topic:
        if steer_topic == "closing":
            parts.append("L'appel dure. Commence à te dire au revoir avec chaleur.")
        else:
            q = STEER_QUESTIONS.get(steer_topic, "")
            if q:
                parts.append(
                    f"S'il y a une ouverture naturelle, tu peux dire : « {q} » "
                    f"Saute si ça sonne forcé."
                )

    parts.append(END_SIGNAL_INSTRUCTION)

    return ("\n\n" + "\n\n".join(parts)) if parts else ""


def build_prompt(user_name: str, context: dict) -> str:
    return _persona(user_name) + _dynamic_tail(user_name, context)


def build_system_blocks(user_name: str, context: dict) -> list:
    blocks = [{
        "type": "text",
        "text": _persona(user_name),
        "cache_control": {"type": "ephemeral"},
    }]
    tail = _dynamic_tail(user_name, context).strip()
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks


_TTS_REPLACE = {
    "mg":  "milligrammes",
    "112": "cent douze",
    "15":  "quinze",
    "18":  "dix-huit",
}

_PROSODY_PATTERNS = [
    (_re.compile(r"(Hmm)\.\.\.\s*"), r"\1... "),
    (_re.compile(r"(Ah)\.\.\.\s*"),  r"\1... "),
    (_re.compile(r"\s+"), " "),
]


def prepare_for_tts(text: str) -> str:
    for abbr, spoken in _TTS_REPLACE.items():
        text = _re.sub(rf"\b{_re.escape(abbr)}\b", spoken, text)
    for pattern, replacement in _PROSODY_PATTERNS:
        text = pattern.sub(replacement, text)
    text = _re.sub(r"[*_~`#→•]", "", text)
    return text.strip()
