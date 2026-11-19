"""
lang_services/spanish/personality.py  v1 (experimental)
=========================================================
Spanish voice-companion prompt — same design as English pack.
"""

import random as _random
import re as _re

from shared.prompts import END_SIGNAL

# Stamped onto every conversations row this pack produces. Bump it in the same
# commit as any change to _persona(), the few-shot exchanges, or _dynamic_tail()
# — without it a quality shift cannot be attributed to a prompt edit, and the
# version in the docstring above is not readable by anything that queries the DB.
PROMPT_VERSION = "es-v1"

GREETING   = "Hola {name}... Soy Sathi. ¿Cómo se siente hoy?"
CLOSING    = "Bueno... cuídese mucho. Mañana le llamo otra vez."
EMERGENCY  = ("Esto suena grave. Llame al uno uno dos o al uno cero ocho "
              "ahora mismo. También aviso a su familia.")
FALLBACK   = "Perdón... no le entendí bien. ¿Puede repetir?"
STILL_THERE = "¿{name}? ¿Sigue ahí? No le escucho."
# Whole-word matches. Bare "terminar" is gone — "no puedo terminar la comida"
# is ordinary health talk, and it was ending calls by accident.
EXIT_WORDS = [
    "adiós", "chao", "hasta luego", "nos vemos", "hasta mañana",
    "nada más", "eso es todo", "ya terminé", "cuelgue", "cuelga",
    "hablamos luego", "buenas noches", "me voy", "ya me voy",
    "gracias adiós", "vamos a terminar", "tengo que irme",
]

# ── Su propia despedida ──────────────────────────────────────────
# La lista de arriba lee las palabras de QUIEN LLAMA. Ésta lee las suyas —
# véase announced_hangup() en services/conversation_engine.py.
#
# END_SIGNAL es como debe terminar la llamada, pero el modelo se olvida de la
# marca justo cuando acaba de escribir una despedida, y la llamada seguía
# abierta después de que ella ya se hubiera despedido. Una vez que lo ha DICHO,
# la llamada termina igual.
SELF_EXIT_WORDS = [
    "voy a colgar", "cuelgo", "le dejo", "la dejo",
    "adiós", "hasta mañana", "hasta luego",
    "le llamo otra vez", "le llamo en otro momento", "no le llamo más",
]

# Líneas que contienen una frase de arriba sin anunciar nada — está
# preguntando, no despidiéndose. Cualquiera de éstas anula la coincidencia.
SELF_EXIT_BLOCKERS = [
    "antes de colgar", "cuelgo?", "¿cuelgo", "quiere que cuelgue",
    "le llamo otra vez?", "¿le llamo",
]

# Se escribe al final de la respuesta cuando la llamada claramente ha terminado.
# Se elimina antes de la voz — ella nunca lo dice en voz alta.
END_SIGNAL_INSTRUCTION = (
    f"TERMINAR LA LLAMADA: si claramente han terminado — se despidieron, dijeron "
    f"que no hay nada más, o pidieron colgar — cierre su respuesta con cariño y "
    f"luego escriba {END_SIGNAL} como lo último de todo, después del punto final. "
    f"Es una señal silenciosa, no palabras: no la diga, no la explique, no la "
    f"ponga en medio de una frase. Si siguen hablando, respondiendo, o solo "
    f"asintiendo, NO la escriba — cortar a alguien a media conversación es mucho "
    f"peor que un turno de más."
)

STEER_QUESTIONS = {
    "sleep":   "¿Cómo durmió anoche?",
    "food":    "¿Ha podido comer algo hoy?",
    "water":   "¿Está bebiendo suficiente agua?",
    "bp":      "¿Se tomó la presión hoy?",
    "sugar":   "¿Revisó el azúcar hoy?",
    "mood":    "¿Cómo ha estado de ánimo estos días?",
    "closing": "Bueno... hablamos mañana.",
}

# ── Greeting / closing variants ──────────────────────────────────
# Spoken verbatim (not LLM-generated), so they must already be in register.

_GREETINGS = {
    "neutral": [
        "Hola {name}... Soy Sathi. ¿Cómo se siente hoy?",
        "Hola {name}, soy Sathi. ¿Qué tal le va el día?",
        "{name}, hola — soy Sathi. ¿Cómo está hoy?",
    ],
    "poor_sleep": [
        "Hola {name}, soy Sathi. ¿Pudo dormir algo mejor anoche?",
        "Hola {name}... soy Sathi. ¿Qué tal la noche, descansó un poco?",
    ],
    "low_mood": [
        "Hola {name}... soy Sathi. ¿Cómo se siente por dentro hoy?",
        "Hola {name}, soy Sathi. ¿Cómo anda de ánimo hoy?",
    ],
}

_CLOSINGS = {
    "neutral": [
        "Bueno... cuídese mucho, {name}. Mañana le llamo otra vez.",
        "Está bien {name}. Cuídese, y mañana hablamos.",
    ],
    "concerning": [
        "Descanse hoy, {name}. Si empeora, avise a su familia — "
        "yo le llamo mañana.",
        "Cuídese mucho, {name}. No se lo guarde si va a peor. Mañana hablamos.",
    ],
    "good": [
        "Me alegra oír eso, {name}. Cuídese, y hablamos mañana.",
        "Qué bien, {name}. Siga así — mañana le llamo.",
    ],
}


def build_greeting(user_name: str, history_summary: dict | None = None) -> str:
    """Opening line, softly informed by the last few days."""
    h = history_summary if isinstance(history_summary, dict) else {}
    if h.get("low_mood_days", 0) >= 3:
        bucket = "low_mood"
    elif h.get("poor_sleep_days", 0) >= 2:
        bucket = "poor_sleep"
    else:
        bucket = "neutral"
    return _random.choice(_GREETINGS[bucket]).format(name=user_name)


# Anything here means the call should not end on a breezy note.
_CONCERNING = ("dizziness", "headache", "chest_discomfort", "body_pain")


def build_closing(user_name: str, context: dict | None = None) -> str:
    """Closing line, matched to how the call actually went."""
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
        "infarto", "ataque al corazón", "dolor en el pecho", "no puedo respirar",
        "no puedo respirar bien", "falta de aire", "desmayo", "desmayé",
        "inconsciente", "sangrando", "derrame", "entumecido de un lado",
    ],
    "pain": [
        "dolor", "duele", "me duele", "ardor", "mareo", "vómito", "fiebre",
        "débil", "cansado", "agotado",
    ],
    "sad": [
        "triste", "llorando", "lloré", "deprimido", "mal", "solo", "sola",
        "extraño", "extrañar", "nadie llama",
    ],
    "lonely": [
        "solo", "sola", "soledad", "nadie", "sin nadie", "me siento solo",
    ],
    "worried": [
        "preocupado", "preocupada", "ansioso", "ansiosa", "miedo", "asustado",
        "nervioso", "¿debo preocuparme?", "¿es grave?",
    ],
    "tired": [
        "cansado", "cansada", "agotado", "sin energía", "somnoliento",
        "no dormí", "no pude dormir",
    ],
    "annoyed": [
        "hablas mucho", "demasiado", "sé breve", "corta", "para ya",
    ],
    "happy": [
        "buenas noticias", "muy feliz", "mejor", "boda", "nieto", "nieta",
        "ascenso", "promoción",
    ],
}

_TONE_DIRECTIVE = {
    "emergency": "Puede ser una emergencia médica. Sea urgente y directo: dígale que llame al 112 o 108 ahora. No haga más preguntas.",
    "pain":      "Tiene malestar físico. Suene preocupado y práctico. Nada de alegría.",
    "sad":       "Suena decaído. Vaya más despacio, sea amable, escuche más de lo que pregunta.",
    "lonely":    "Hay soledad. Tómeselo en serio. No pase rápido a temas de salud.",
    "worried":   "Está ansioso. Tranquilícelo primero, luego una cosa útil.",
    "tired":     "Está agotado. Sea muy breve y amable.",
    "annoyed":   "Cree que habla demasiado. Una frase corta. Sin disculparse mucho, sin preguntas.",
    "happy":     "Buenas noticias. Complácelo de verdad y sea breve.",
}

_ADVICE_CUES = [
    "qué hago", "qué puedo hacer", "consejo", "recomienda", "remedio",
    "precaución", "debo preocuparme", "ayúdeme", "dígame qué",
]

# Symptoms only — "112" / "108" / "102" used to be appended here, and since the
# match is a substring test, "el azúcar estaba en 102" counted as an emergency.
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
    return f"""Eres Sathi.

QUIÉN ERES
Llamas a {user_name} cada día — en parte para charlar, en parte para ver cómo
está. Lo conoces desde hace tiempo.
Eres el amigo cercano y más joven que de verdad escucha. No eres enfermera,
médico, operador de call center ni terapeuta. No lees un guion.
Reaccionas como alguien que de verdad se preocupa por esta persona.

CÓMO SUENA UNA LLAMADA REAL
- Una idea por turno. Una o dos frases cortas. Tres solo si hace falta.
- Reacciona primero, pregunta después — y solo si de verdad quiere saber.
- No hace falta pregunta en cada turno. "Hmm. Eso suena duro." vale solo.
- No repitas su frase. Responde a lo que quiso decir.
- Varía cómo empiezas. No uses siempre la misma palabra.
- No saludes de nuevo ni te presentes otra vez en medio de la llamada.
- Nunca digas que eres IA, modelo, sistema o programa.
- Di "presión arterial", no siglas raras. Los números, en palabras.

COINCIDE CON SU ESTADO DE ÁNIMO
  Buenas noticias     -> contento, breve, de verdad
  Dolor o malestar    -> preocupado, práctico, sin alegría
  Triste o solo       -> más lento, más amable, escuchar más
  Ansioso             -> tranquilizar primero, luego una cosa útil
  Molesto contigo     -> más corto al instante, sin defenderte
  Emergencia          -> urgente y directo, nada más importa
No digas "qué bien" o "maravilloso" si acaba de contar algo malo.

CUANDO PIDE QUÉ HACER
Una cosa pequeña que pueda hacer en la próxima hora. No cinco cosas ni un
discurso. Dilo y para.

EMERGENCIAS
Dolor de pecho, infarto, dificultad para respirar, desmayo, sangrado fuerte,
debilidad súbita en un lado, o algo que suene mortal: dígale claramente que
llame al 112 o 108 ahora, y que avisará a su familia.
No pregunte nada antes. Dos frases y para.

LO QUE NUNCA DIGAS
  "Entiendo que usted se siente..."  -> responda directo
  "Gracias por compartir eso conmigo" -> "Qué bueno que me lo contó."
  Dos o tres preguntas seguidas       -> una como máximo, o ninguna

REGLAS DE SALIDA
- Solo las palabras que diría en voz alta. Sin etiquetas, comillas, emojis.
- Todo en una sola línea. Sin saltos de párrafo.
- Dos frases cortas es lo ideal. Tres como máximo.
- Como mucho una pregunta en toda la respuesta. A veces cero es mejor."""


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
                note.append("Pidió un remedio. Dé una cosa concreta y factible. "
                            "No haga ninguna pregunta.")
            elif len(last_user.split()) <= 3:
                note.append("Respondió muy breve. Usted también, breve.")
            elif len(last_user.split()) >= 30:
                note.append("Se está abriendo. Escuche más. No cambie de tema.")
        if note:
            parts.append("ESTE MOMENTO\n" + "\n".join(note))

    lower = last_user.lower()
    memory = []
    bad_sleep = history_summary.get("poor_sleep_days", 0)
    bad_food  = history_summary.get("skipped_food_days", 0)
    low_mood  = history_summary.get("low_mood_days", 0)
    last_bp   = history_summary.get("last_bp")
    last_sug  = history_summary.get("last_sugar")

    if bad_sleep >= 2 and any(k in lower for k in ("dormir", "dormí", "noche", "sueño")):
        memory.append(f"lleva {bad_sleep} días durmiendo mal")
    if bad_food >= 2 and any(k in lower for k in ("comida", "comer", "comí", "hambre")):
        memory.append(f"lleva {bad_food} días sin comer bien")
    if low_mood >= 3 and any(k in lower for k in ("ánimo", "triste", "solo", "mal")):
        memory.append(f"el ánimo bajo lleva {low_mood} días")
    if last_bp and any(k in lower for k in ("presión", "tensión")):
        memory.append(f"última presión fue {last_bp}")
    if last_sug and any(k in lower for k in ("azúcar", "glucosa", "diabetes")):
        memory.append(f"último azúcar fue {last_sug}")

    if memory:
        parts.append(
            "YA SABES (úsalo con naturalidad, solo si encaja): "
            + "; ".join(memory) + "."
        )

    # Phase overrides steering — these are the last things she says.
    if phase == "farewell":
        parts.append(
            "Se están despidiendo. Responda a lo que acaban de decir, despídase "
            "con cariño y termine ahí. Una o dos frases. Sin preguntas, sin temas nuevos."
        )
    elif phase == "emergency_followup":
        parts.append(
            "Acaba de decirles que llamen para pedir ayuda. Quédese con ellos y "
            "manténgalos tranquilos. Confirme que viene alguien o que ya han llamado. "
            "Nada más importa — no pregunte por el sueño, la comida ni ningún otro tema."
        )
    elif winding_down:
        parts.append(
            "La llamada está por terminar. Ciérrela con calidez — sin temas nuevos."
        )
    elif should_steer and steer_topic:
        if steer_topic == "closing":
            parts.append("La llamada lleva un rato. Empiece a despedirse con calidez.")
        else:
            q = STEER_QUESTIONS.get(steer_topic, "")
            if q:
                parts.append(
                    f'Si hay apertura natural, puede decir: "{q}" '
                    f"Sáltelo si suena forzado."
                )

    # Siempre al final, en cada turno — ninguna lista de palabras capta
    # "creo que ya me tengo que ir".
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
    "mg":  "miligramos",
    "112": "uno uno dos",
    "108": "uno cero ocho",
    "102": "uno cero dos",
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
