"""
edu/packs/english.py — English (en-IN) language spec.

Language mechanics and native few-shots only. Nothing here knows what an
admission is; that lives in edu/persona.py. Everything imported from
lang_services.english.personality is conversation mechanics that was never
health-specific — see the note in edu/pack_factory.py.
"""

import re as _re

from edu.tail_text import FAREWELL, STEER_QUESTIONS  # noqa: F401  (re-exported)

# ── Reused mechanics ──────────────────────────────────────────────
from lang_services.english.personality import (
    BEREAVEMENT_WORDS,
    DECLINE_WORDS,
    EMERGENCY_KEYWORDS,
    EXIT_WORDS as _BASE_EXIT_WORDS,
    SELF_EXIT_BLOCKERS as _BASE_SELF_EXIT_BLOCKERS,
    SELF_EXIT_WORDS,
    UNAVAILABLE_WORDS as _BASE_UNAVAILABLE_WORDS,
    WRONG_PERSON_WORDS,
)

CODE = "en-IN"
NAME = "English"
PACK_VERSION = "en-edu-v1"

# ── Word lists, extended for this domain ──────────────────────────
# The health packs deliberately exclude anything that could occur in ordinary
# health talk. The equivalent care here is the opposite direction: a parent
# saying "I'll think about it" is NOT ending the call, and must never be read
# as one.
EXIT_WORDS = list(_BASE_EXIT_WORDS)

UNAVAILABLE_WORDS = list(_BASE_UNAVAILABLE_WORDS) + [
    "at work",
    "in office",
    "picking up",
    "dropping",
    "school run",
]

# Phrases that must stop announced_hangup() firing. "I'll let you go" is a
# goodbye; "let me send you the details" is not, and neither is anything about
# the child leaving their current school.
SELF_EXIT_BLOCKERS = list(_BASE_SELF_EXIT_BLOCKERS) + [
    "let me send",
    "i'll send you",
    "before you go",
    "leaving school",
    "left the school",
    "changing school",
]

TRAILING_PARTICLES = []

# ── Fixed lines ───────────────────────────────────────────────────
# {agent} and {institution} are filled by the pack factory.

GREETINGS = {
    "first": [
        "Hello, am I speaking with {name}? This is {agent} calling from "
        "{institution}. Is now an alright time for a quick word about admissions?",
        "Hello {name}, this is {agent} from {institution}. I'm calling about "
        "admissions for the coming year — is this a good moment?",
    ],
    "callback": [
        "Hello {name}, it's {agent} from {institution} again. Is this a "
        "better time?",
        "Hello {name}, {agent} here from {institution} — we spoke a little "
        "while ago. Do you have a minute now?",
    ],
}

CLOSINGS = {
    "neutral": [
        "Thank you for your time, {name}. Do call us if anything else comes to "
        "mind.",
        "That's everything from my side, {name}. We're here whenever you want "
        "to know more.",
    ],
    "visit": [
        "Lovely — we'll see you then, {name}. Someone will send you the "
        "directions.",
        "That's settled then, {name}. We'll look forward to meeting you.",
    ],
    "callback": [
        "I'll have our counsellor call you, {name}. Thank you for your time.",
        "Someone will be in touch shortly, {name}. Thanks for talking to me.",
    ],
}

GREETING = "Hello {name}, this is {agent} calling from {institution}."
CLOSING = "Thank you for your time, {name}."

FALLBACK = "Sorry, I didn't catch that. Could you say it again?"
STILL_THERE = "{name}? Are you still there? I can't hear you."

# Not this product's business, but a parent can have a real emergency on any
# call, and the cross-language baseline in conversation_engine fires regardless
# of what the pack lists. So the line has to exist and has to be right.
EMERGENCY = (
    "That sounds serious. Please call one one two right now — I'll let you go."
)

# The exact phrasing she is told to use when a fact is missing. Matched by
# edu/outcome.py to count unanswered questions, so keep these in step with the
# persona's instruction.
DEFER_MARKERS = [
    "counsellor confirm",
    "counselor confirm",
    "have our counsellor",
    "have our counselor",
    "exact answer",
]

# ── Extraction hints ──────────────────────────────────────────────
# Substring matched, case-folded. Keep entries short and unambiguous; a phrase
# that shows up in ordinary conversation will fire constantly.
HINTS = {
    "question_cues": [
        "what", "how", "when", "where", "which", "who", "why",
        "can i", "can you", "could you", "is there", "are there", "do you",
        "does the", "tell me", "i want to know", "any idea",
    ],
    "visit_yes": [
        "i'll come", "we'll come", "i can come", "we can come", "sure i'll visit",
        "yes we'll visit", "happy to visit", "let's do saturday", "saturday works",
        "sunday works", "book it", "that works for me",
    ],
    "visit_no": [
        "can't come", "cannot come", "not able to come", "too far", "no time to visit",
        "maybe later", "not right now", "we'll see",
    ],
    "callback": [
        "call me back", "call later", "call me tomorrow", "ring me", "call in the evening",
        "send me the details", "whatsapp me", "send on whatsapp",
    ],
    "intake_now": [
        "this year", "this session", "coming year", "right away", "immediately",
        "as soon as possible", "april", "june admission",
    ],
    "intake_next": ["next year", "next session", "following year", "not this year"],
    "stage_ready": [
        "we've decided", "want to apply", "ready to apply", "how do i apply",
        "fill the form", "start the process",
    ],
    "stage_comparing": [
        "also looking at", "comparing", "few schools", "other schools", "shortlisted",
        "deciding between",
    ],
    "stage_exploring": [
        "just enquiring", "just asking", "just checking", "gathering information",
        "early stages", "just started looking",
    ],
    # "expensive" alone rather than "too expensive": a parent almost never says
    # the full phrase. The smoke script's "bit expensive compared to others, no?"
    # went unmatched on the narrower list, and that is exactly the objection the
    # persona has a rule for.
    "fee_concern": [
        "expensive", "bit high", "quite high", "afford", "cheaper",
        "out of budget", "beyond our budget", "costly", "reduce the fee",
        "on the higher side",
    ],
    "boarding_yes": ["hostel", "boarding", "stay there", "residential"],
    "boarding_no": ["day scholar", "day school", "come home", "not hostel"],
    "wants_human": [
        "speak to someone", "talk to a person", "real person", "human",
        "speak to the principal", "talk to counsellor", "talk to counselor",
        "put me through", "are you a robot", "are you a machine", "is this a recording",
    ],
    "special_needs": [
        "special needs", "learning disability", "dyslexia", "autism", "adhd",
        "wheelchair", "hearing aid", "speech therapy", "shadow teacher",
        "medical condition",
    ],
    "complaint": [
        "complaint", "very disappointed", "worst", "cheated", "misled",
        "no one responded", "nobody called back", "waste of time",
    ],
    "fee_negotiation": [
        "discount", "concession", "scholarship", "waiver", "sibling discount",
        "any relaxation", "reduce the fees",
    ],
    "rushed": ["quickly", "in a hurry", "make it fast", "be quick", "no time"],
    "hesitant": ["not sure", "don't know", "have to think", "let me think", "maybe"],
    "annoyed": [
        "already told you", "i said", "stop calling", "how many times",
        "not interested", "leave me alone",
    ],
    "keen": [
        "sounds good", "that's great", "very good", "interested", "please tell me more",
    ],
}

CRITICAL_TOPICS = ["grade", "child_age", "locality", "intake", "visit_intent"]

# Numeral vocabulary handed to the qualification extractor. English needs none
# beyond what edu/qualification.py already handles ("class five", "5th"), but
# the key is declared so every pack has the same shape.
NUMERALS = {"ordinals": {}, "numbers": {}}

# ── Voice ─────────────────────────────────────────────────────────
# Same speaker across all three packs, for the same reason the Saathicare packs
# converged on one: the agent should be one person whichever language the call
# happens to be in.
TTS_CONFIG = {
    "speaker": "priya",
    "pace": 0.95,
    "pause_ms": 320,
    "temperature": 0.7,
    "thinking_sounds": ["Sure...", "Right...", "Of course...", "Let me see..."],
    "soft_thinking_sounds": ["Sure...", "Right..."],
}

# ── Text preparation ──────────────────────────────────────────────
# Education-specific rather than reused: the health pack expands BP and reads
# out ambulance numbers, neither of which belongs here, while fees, grades and
# board acronyms all need handling and do not appear there at all.
_TTS_REPLACE = {
    "Rs": "rupees",
    "Rs.": "rupees",
    "INR": "rupees",
    "₹": "rupees ",
    "p.a.": "per year",
    "pa": "per year",
    "Std": "standard",
    "Std.": "standard",
    "Sr.": "senior",
    "Jr.": "junior",
    "approx": "roughly",
    "PTM": "parent teacher meeting",
    "co-ed": "co-educational",
    "&": "and",
}

_PROSODY = [
    (_re.compile(r"\bThank you for your valuable time\b", _re.I), "Thank you for your time"),
    (_re.compile(r"\bI completely understand your concern\b", _re.I), "That's fair"),
    (_re.compile(r"\bAs I mentioned earlier\b", _re.I), "Like I said"),
    (_re.compile(r"\bIs there anything else I can help you with\b", _re.I),
     "Anything else you'd like to know"),
    (_re.compile(r"\bWe are one of the (?:best|top|leading)\b", _re.I), "We're a"),
    (_re.compile(r"\s+"), " "),
]


def prepare_for_tts(text: str) -> str:
    for abbr, spoken in _TTS_REPLACE.items():
        text = _re.sub(rf"(?<![A-Za-z]){_re.escape(abbr)}(?![A-Za-z])", spoken, text)
    for pattern, replacement in _PROSODY:
        text = pattern.sub(replacement, text)
    text = _re.sub(r"[*_~`#→•]", "", text)
    return text.strip()


# ── Tone ──────────────────────────────────────────────────────────
# Returns names from the vocabulary services/conversation_engine._HEAVY_TONES
# already understands, because that tuple is what decides whether a bright
# filler is safe. The education moods are mapped onto it deliberately: an
# annoyed or hesitant parent gets the soft filler set, exactly as a person in
# pain does on the health product. Anything outside that tuple would silently
# have no effect.
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


# ── The register ──────────────────────────────────────────────────
# The few-shots carry the voice. Keep them short, keep them in the exact
# register we want back, and change them only with a PACK_VERSION bump.
LANGUAGE_RULE = """LANGUAGE
Speak Indian English throughout. Natural spoken register, contractions
everywhere, never written English read aloud. Some English-Hindi mixing is
normal in this context and is fine if they do it first — do not initiate it."""

FEWSHOTS = """THE FEEL WE WANT

They: "What's the fee for class five?"
You: "For Grade five it's rupees ninety-two thousand for the year, and that includes books and uniform."

They: "Is that with transport?"
You: "No, transport is separate — it's between eight and twelve thousand depending on your area. Which side of town are you on?"

They: "Kothrud."
You: "Kothrud we do cover, so that'd be the ten thousand slab. The bus reaches there around seven fifteen."

They: "Bit expensive, no?"
You: "It is a real amount, I won't pretend otherwise. What were you working with, roughly? Then I can tell you honestly whether we fit."

They: "What's your board?"
You: "We're CBSE, right through to Grade twelve."

They: "Do you have a hostel?"
You: "We don't, we're a day school only. If boarding is what you need, we wouldn't be the right fit for you."

They: "When's the last date to apply?"
You: "The thirtieth of November. There's no rush this week, but I wouldn't leave it to the last few days."

They: "What about the entrance test?"
You: "I'd rather give you the exact date than guess at it — I'll have our counsellor confirm that for you."

They: "My son is in third standard now."
You: "So Grade four for next year. Are you looking at the coming session, or the one after?"

They: "Can I come and see the place?"
You: "Please do — Saturday mornings are easiest, around eleven. Would this Saturday suit you?"

They: "I'll have to ask my husband first."
You: "Of course, it's a decision for both of you. Shall I have the details sent across so you can look at them together?"

They: "How many kids per class?"
You: "Twenty-eight is our cap, and most sections sit around twenty-five."

They: "I'm driving right now."
You: "Oh — sorry to catch you at the wheel. I'll call another time, you drive safe. <<END>>"

They: "Please don't call me again."
You: "Of course. Sorry to have troubled you — I won't call again. <<END>>"

They: "Who? No, there's no one here by that name."
You: "Sorry to have disturbed you. Have a good evening. <<END>>"
"""
