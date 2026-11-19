"""
services/conversation_engine.py — One Conversation Turn
=========================================================
Clean separation of concerns:
  - Record mic
  - STT (parallel with context build)
  - Build prompt from personality (free conversation)
  - Stream LLM → TTS per sentence (parallel)
  - Save to DB
  - Update session state
"""

import asyncio
import os
import random
import re
import time
import unicodedata

from colorama import Fore, Style
from dotenv import load_dotenv

from core.stt_service import transcribe
from core.gladia_service import (
    is_french_language,
    record_and_transcribe as gladia_record_and_transcribe,
    transcribe_file_live as gladia_transcribe_file_live,
)
from core.tts_service import (
    prewarm_phrases,
    synthesize_cached,
    synthesize_phrase,
    text_to_speech_full,
)
from core.llm_service import stream_tokens
from core.audio       import (
    AudioPlayer, record_audio, get_audio_duration, listen_while_playing,
)
from core.database    import save_conversation
from shared.lang      import load_lang_service, voice_language
from shared.prompts   import END_SIGNAL, build_system

load_dotenv()

# Sentence + early yield boundaries
_SENTENCE_RE = re.compile(r"(?<=[.!?।…])\s+")
_EARLY_RE    = re.compile(r"(?<=[,\u0964:…])\s+")

# Abbreviations whose trailing dot must NOT be treated as a sentence end.
# Mirrors the same guard in core/tts_service.py — kept in sync manually.
# This one applies to the *streaming* splitter (_split); tts_service covers
# the batch splitter (_split_sentences used for greetings / closings).
_ABBREV_RE   = re.compile(
    r"\b(M|Mme|Mlle|Dr|Me|Prof|Sr|Sra|Mr|Mrs|Ms|St|Etc|etc|vs|Jr|Yr|no|No)\.$",
    re.IGNORECASE,
)

# Each phrase becomes a separate TTS call, and Sarvam gives every call its own
# sentence-final intonation contour. A phrase that isn't a whole thought
# therefore sounds clipped, and stitching several together sounds robotic.
#
# MIN_EARLY was 12, which split "हं," and "ji." off as standalone utterances and
# broke questions across two contours ("Is it steady," / "or does it come and
# go?"). The comma split exists only to get first audio out sooner, so it is now
# allowed for the FIRST phrase of a reply and only for a clause long enough to
# stand on its own.
MIN_EARLY  = int(os.getenv("TTS_MIN_EARLY_CHARS", "22"))

# Never speak a fragment shorter than this alone — merge it with what follows so
# short sentences share one natural contour.
MIN_PHRASE = int(os.getenv("TTS_MIN_PHRASE_CHARS", "12"))

# The first sentence of a reply may be shorter ("Parfait.", "D'accord.") — TTS
# time grows with length, so a short opener gets first audio out much sooner.
MIN_FIRST = int(os.getenv("TTS_MIN_FIRST_CHARS", "6"))

# Time from the caller falling silent to her first "hmm...". Measured from the
# moment they stop speaking (the watchdog now starts before STT), so this is a
# real acknowledgement delay rather than an extra wait tacked on after STT.
THINKING_MS      = int(os.getenv("THINKING_SOUND_THRESHOLD_MS", 500))
THINKING_ENABLED = os.getenv("THINKING_SOUND_ENABLED","true").lower() == "true"

# The first filler covers a normal reply. A slow turn (routinely several
# seconds on Marathi's Sonnet override, see CLAUDE.md) used to go dead silent
# after that one sound until the real reply arrived — which is what reads as
# a dropped call. These let the watchdog re-arm instead of firing once.
THINKING_REPEAT_MS  = int(os.getenv("THINKING_SOUND_REPEAT_MS", 2500))
THINKING_MAX_REPEATS = int(os.getenv("THINKING_SOUND_MAX_REPEATS", 2))
# Speakers bleed into the next mic grab on a laptop. Wait after she finishes
# before listening, and drop transcripts that are just her own last line.
POST_TTS_GAP_S = float(os.getenv("POST_TTS_LISTEN_GAP_S", "0.7"))


def _split(buffer: str, allow_early: bool = True) -> tuple[list, str]:
    """
    Pull speakable phrases out of the streaming buffer.

    `allow_early` should be True only while nothing has been spoken yet — the
    comma split buys time-to-first-audio, and past the first phrase it costs
    more in naturalness than it saves in latency.

    Abbreviation guard: if a candidate complete-chunk ends with a known
    abbreviation (M., Dr., Mme., etc.) the dot was NOT a sentence boundary —
    the chunk is held in `pending` and merged with the next chunk instead of
    being emitted as a standalone phrase. This prevents "M." from being
    synthesised alone with sentence-final intonation.
    """
    parts = _SENTENCE_RE.split(buffer)
    if len(parts) > 1:
        complete, rest = parts[:-1], parts[-1]
        out, pending = [], ""
        for chunk in complete:
            chunk = chunk.strip()
            if not chunk:
                continue
            pending = f"{pending} {chunk}".strip() if pending else chunk
            # Abbreviation guard — keep accumulating if this dot wasn't a
            # real sentence end (e.g. "M.", "Dr.", "Mme.").
            if _ABBREV_RE.search(pending):
                continue
            floor = MIN_FIRST if (allow_early and not out) else MIN_PHRASE
            if len(pending) >= floor:
                out.append(pending)
                pending = ""
        if pending:
            # Too short or abbreviation-ended — hold it back so it joins what
            # follows.  Keep a trailing separator so the caller can append the
            # next token without running words together ("समझ गई।आराम").
            rest = f"{pending} {rest}" if rest else f"{pending} "
        return out, rest

    if allow_early and len(buffer) >= MIN_EARLY:
        parts = _EARLY_RE.split(buffer)
        if len(parts) > 1:
            head = " ".join(p.strip() for p in parts[:-1]).strip()
            if len(head) >= MIN_EARLY:
                return [head], parts[-1]
    return [], buffer


def _clean(text: str) -> str:
    if not text: return ""
    text = re.sub(r"<think>.*?</think>","",text,flags=re.DOTALL|re.IGNORECASE)
    return text.strip().strip('"').strip("'")


_PUNCT_RE = re.compile(r"[.,!?;:\u0964\u2026\"'`()\[\]-]+")
_NUKTA    = "\u093c"
_ZERO_W   = ("\u200c", "\u200d")


def _fold(text: str) -> str:
    """
    Lowercase and remove Devanagari spelling variation that STT introduces.
    Sarvam may return "फ़ोन" (with nukta) where our keyword list has "फोन", and
    either form may be precomposed or decomposed, so strip the nukta entirely.
    """
    t = unicodedata.normalize("NFD", (text or "").lower()).replace(_NUKTA, "")
    for z in _ZERO_W:
        t = t.replace(z, "")
    return unicodedata.normalize("NFC", t)


def _looks_like_echo(user_text: str, session, lang_service) -> bool:
    """
    True when the mic almost certainly captured her last line, not the caller.

    FIX: raised word-overlap threshold 0.65 → 0.75 and added an 8-word length
    guard. At 0.65, a caller saying "Hmm, right, I understand" after Camille
    said "I see, right?" hit 67% overlap and was silently discarded. The higher
    threshold keeps echo suppression effective for genuine playback bleed while
    preserving real short responses. The length guard means any utterance with
    more than 8 words that overlaps is assumed to contain novel content and is
    not discarded — longer responses are overwhelmingly real speech, not echo.
    """
    words = _norm_words(user_text)
    if len(words) < 2:
        return False
    candidates = [
        getattr(session, "last_sathi_msg", "") or "",
        getattr(session, "last_thinking_sound", "") or "",
    ]
    tts_cfg = getattr(lang_service, "TTS_CONFIG", None) or {}
    candidates.extend(thinking_sounds_for(tts_cfg))
    uw = set(words)
    folded = _fold(user_text)
    for cand in candidates:
        c = _fold(cand)
        if len(c) < 4:
            continue
        if folded in c or c in folded:
            return True
        cw = set(_norm_words(c))
        # Length guard: utterances longer than 8 words are almost certainly
        # real speech, even if they share common filler words with Sathi.
        if len(words) > 8:
            continue
        if len(uw) >= 2 and cw and len(uw & cw) / len(uw) >= 0.75:
            return True
    return False


def _norm_words(text: str) -> list:
    """Fold spelling, then split into words with punctuation as a separator."""
    return _PUNCT_RE.sub(" ", _fold(text)).split()


def _ends_with(words: list, phrase: list) -> bool:
    return len(words) >= len(phrase) and words[-len(phrase):] == phrase


def _contains(words: list, phrase: list, max_trailing: int = None) -> bool:
    """
    True when `phrase` appears in `words`.

    With max_trailing set, the match must also be near the END of the line:
    "ठीक है साथी फोन रखो अभी" is a hang-up, but "बेटा आया था बाद में बात होगी
    उससे" merely mentions talking later and used to end the call on them.
    """
    n = len(phrase)
    for i in range(len(words) - n + 1):
        if words[i:i + n] != phrase:
            continue
        if max_trailing is None or len(words) - (i + n) <= max_trailing:
            return True
    return False


# Clause boundaries for finding the closing clause. Sentence punctuation only —
# splitting on commas as well makes the closing clause short enough that
# ordinary speech qualifies for the _contains() path, and "I slept badly, my
# back hurts and nothing else helps" starts hanging up on people.
_CLAUSE_RE = re.compile(r"[.!?।…]+")

# How many words a wrap-up line can hold before a mid-sentence hang-up phrase
# stops counting. Raising this to 12 catches two more real goodbyes and costs
# ten false hang-ups: at 12, "I slept badly, my back hurts and nothing else
# helps" and "साखर तपासली, बाकी काही नाही वाटत" both end the call. Stays at 8.
_CONTAINS_MAX_WORDS = 8

# ...and how many words may follow the matched phrase. A goodbye trails at most
# a particle ("फोन रखो अभी"); "बाद में बात होगी उससे" trails a whole verb phrase
# and is someone talking ABOUT calling later, not hanging up.
_CONTAINS_MAX_TRAILING = 1

# Only the loose _contains() path needs a length guard — a long utterance there
# is health storytelling. The tail match below is safe at any length because it
# looks at the closing clause only.
_CONTAINS_MAX_CHARS = 80

# Deliberately NOT extended: running _contains() over the closing clause of a
# long utterance. It catches "आता मी फोन ठेवते बरं का" (a real goodbye with a
# politeness particle after the verb), but it also fires on "साखर तपासली, बाकी
# काही नाही वाटत" and "I ate breakfast, I'm done with the medicine for today".
# Ending a call on someone mid-sentence is far worse than one extra turn, so
# that whole class of goodbye is left to the model's END_SIGNAL instead.


def _trim_particles(words: list, particles: set) -> list:
    """
    Drop sentence-final filler from the end of a line.

    "फोन ठेवते आता हं" and "फोन ठेवते" are the same goodbye, but _ends_with()
    only sees the second one. The particles a pack lists here carry no meaning
    of their own, so removing them cannot turn ordinary speech into a goodbye —
    it only lets the phrase that is already there reach the end of the line.
    """
    if not particles:
        return words
    out = list(words)
    while out and out[-1] in particles:
        out.pop()
    return out


def _wants_to_exit(user_text: str, exit_words: list, particles: list = None) -> bool:
    """
    End the call only on clear goodbye intent.

    Matching is on whole words with punctuation stripped, so "Okay, thank you
    so much. Bye." ends the call while "the pain won't stop" does not.

    The tail match runs against the LAST clause rather than the whole utterance.
    A real goodbye is often the end of a long sentence — "thank you so much for
    calling, I'm feeling much better now, bye" is over 80 characters and used to
    be thrown away wholesale before anything was even compared.

    Each candidate line is tried both as spoken and with trailing particles
    trimmed, never trimmed only: an entry that ends in a particle itself
    ("ठीक आहे मग") has to keep matching the line it was written for.
    """
    words = _norm_words(user_text)
    if not words:
        return False

    # Last clause: everything after the final sentence break, falling back to
    # the whole line when they spoke without punctuation.
    tail = [c for c in _CLAUSE_RE.split(user_text or "") if c.strip()]
    tail_words = _norm_words(tail[-1]) if tail else words

    particle_set = {p for p in (_fold(x).strip() for x in (particles or [])) if p}
    candidates = [tail_words, words]
    for base in (tail_words, words):
        trimmed = _trim_particles(base, particle_set)
        if trimmed and trimmed != base:
            candidates.append(trimmed)

    short_enough = (
        len(words) <= _CONTAINS_MAX_WORDS
        and len(" ".join(words)) <= _CONTAINS_MAX_CHARS
    )
    for w in exit_words:
        phrase = _norm_words(w)
        if not phrase:
            continue
        # A goodbye almost always lands at the end of the closing clause
        if any(_ends_with(c, phrase) for c in candidates):
            return True
        # Multi-word hang-up phrases ("फोन रखो", "hang up") may sit just short
        # of the end of a wrap-up line: "ठीक है साथी फोन रखो अभी"
        if len(phrase) > 1 and short_enough and _contains(
            words, phrase, max_trailing=_CONTAINS_MAX_TRAILING
        ):
            return True
    return False


# ── Why the call is ending, not just that it is ───────────────────────
#
# A goodbye is only one of the reasons a call has to stop. Four more come up
# constantly on a real line, and each needs a different last sentence from her:
#
#   unavailable  — "I'm in a meeting", "I'm driving", "call me later".
#                  She used to answer "alright, I'll wait until it's over".
#   declined     — "don't call me again", "remove my number".
#   wrong_person — a son/neighbour picked up, or it is the wrong number. She
#                  must not discuss the user's health with whoever answered.
#   bereavement  — the person she rings has died. One line, then stop.
#
# Priority runs grave -> opt-out -> wrong person -> busy -> goodbye, because a
# single utterance can look like two of them ("she passed away, don't call
# again") and the graver read is always the safer one to act on.
EXIT_REASONS = ("bereavement", "declined", "wrong_person", "unavailable", "goodbye")

# Language-pack attribute holding each reason's phrase list. Fetched with
# getattr so a pack that has not been given these lists (Spanish) simply keeps
# today's goodbye-only behaviour instead of raising.
_REASON_ATTRS = {
    "bereavement":  "BEREAVEMENT_WORDS",
    "declined":     "DECLINE_WORDS",
    "wrong_person": "WRONG_PERSON_WORDS",
    "unavailable":  "UNAVAILABLE_WORDS",
}

# Word ceiling for the stem match on "unavailable" only. Its stems are single
# nouns ("मीटिंग", "meeting"), so a long utterance can hit one incidentally —
# "माझा मुलगा मीटिंगमध्ये आहे, आणि मला काल झोप लागली नाही" is health talk, not a
# request to hang up. Someone who genuinely cannot talk says so in a breath.
# The other three lists carry unambiguous multi-word phrases and need no guard.
_STEM_MAX_WORDS = 12


def _matches_stems(user_text: str, stems: list, max_words: int = None) -> bool:
    """
    Folded substring match, for stems that take case suffixes.

    _wants_to_exit() compares whole words, which is right for goodbyes but
    cannot work here: Marathi and Hindi glue the postposition onto the noun, so
    the token "मीटिंगमध्ये" will never equal the list entry "मीटिंग". A substring
    test does. It is safe only because these lists are deliberately chosen not
    to collide with health talk — see the comments on each list in the language
    packs, and note what is missing from them ("eating", "sleeping", "doctor").
    """
    if not stems:
        return False
    folded = _fold(user_text or "")
    if not folded.strip():
        return False
    if max_words is not None and len(folded.split()) > max_words:
        return False
    for stem in stems:
        s = _fold(stem).strip()
        if s and s in folded:
            return True
    return False


def classify_exit(user_text: str, lang_service) -> str | None:
    """
    Why this call should end, or None to carry on.

    Returns one of EXIT_REASONS. Feed the result straight to
    SessionManager.begin_farewell(reason) — the personality tail reads it back
    out of the context and picks the closing instruction to match.
    """
    if not (user_text or "").strip():
        return None
    for reason in ("bereavement", "declined", "wrong_person", "unavailable"):
        stems = list(getattr(lang_service, _REASON_ATTRS[reason], []) or [])
        cap = _STEM_MAX_WORDS if reason == "unavailable" else None
        if _matches_stems(user_text, stems, max_words=cap):
            return reason
    if _wants_to_exit(
        user_text,
        getattr(lang_service, "EXIT_WORDS", []) or [],
        getattr(lang_service, "TRAILING_PARTICLES", []) or [],
    ):
        return "goodbye"
    return None


# ── The model's own way of ending a call ──────────────────────────────
#
# No keyword list covers every goodbye — "बरं, मला आता जायचंय" means the same
# as "बाय" and matches nothing. The personality prompts ask her to write
# END_SIGNAL (defined in shared/prompts.py, re-exported here for the call
# loops) at the end of her reply when the caller is clearly finished; we strip
# it before TTS so it is never spoken, and end the call on that same turn.
#
# Tolerate the shapes models actually produce: <END>, << END >>, [[END]],
# (END), **<<END>>**. The wrapper is whatever the model felt like typing; the
# word in the middle is the only part we asked for.
_END_RE = re.compile(r"[*_]*[<\[(]{1,2}\s*END\s*[>\])]{0,2}[*_]*", re.IGNORECASE)

# ...and the shape with no wrapper at all, which only counts at the very end of
# the reply and only in capitals. Anchored and case-sensitive on purpose: an
# English reply may well contain the word "end" ("by the end of the week"), but
# it will never finish with a bare capitalised "END".
_BARE_END_RE = re.compile(r"(?:\A|[\s.।!?…])END[\s.।!?…*_]*\Z")


def strip_end_signal(text: str) -> tuple:
    """
    Remove the end-of-call sentinel from a phrase.

    Returns (clean_text, was_present). Always call this before prepare_for_tts()
    — _clean() only strips quotes and would happily send "<<END>>" to the voice.
    """
    if not text:
        return text, False
    cleaned = _END_RE.sub(" ", text)
    if cleaned == text:
        cleaned = _BARE_END_RE.sub(" ", text)
        if cleaned == text:
            return text, False
    # Collapse the space the substitution left behind, plus any orphan bracket.
    cleaned = re.sub(r"[<>\[\]]", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, True


# ── Her own goodbye, when the sentinel never arrives ──────────────────
#
# END_SIGNAL is how she is meant to end a call, and most of the time she does.
# But a model that has just written a warm goodbye forgets the marker often
# enough to matter: on a live Marathi call she answered "ठीक आहे, ठेवते. काळजी
# घ्या." — "alright, I'm hanging up, take care" — with no sentinel, and the loop
# took two more turns on a caller who had already been told the call was over.
#
# Nothing else could catch that. classify_exit() reads the CALLER's words only,
# and by then the caller has said their piece; the sentinel was the single
# thread holding up the whole hang-up, and it is the one part of the reply the
# model has no acoustic reason to get right.
#
# So her own words are read back too. Keyword matching is far safer here than on
# the caller's side: her phrasing comes from the persona rather than from an
# elderly stranger's free speech through STT, and the phrases below are ones she
# says only on the way out.
_SELF_EXIT_BASELINE = [
    "goodbye", "good bye", "bye bye", "bye for now",
    "i'll hang up", "i will hang up", "i'm hanging up", "i am hanging up",
    "i'll let you go", "i will let you go",
    "i'll end the call", "i will end the call",
]

# Phrases that contain a hang-up verb but do not announce one — she is asking
# whether to hang up, or promising to remember something. Any of these anywhere
# in the reply vetoes the whole match: one extra turn is a far smaller mistake
# than cutting the line while she is still asking a question.
_SELF_EXIT_BLOCKERS_BASELINE = [
    "shall i hang up", "should i hang up", "before i hang up",
    "do you want me to hang up", "want me to hang up",
    "before i say goodbye", "before we say goodbye",
]


def announced_hangup(sathi_text: str, lang_service) -> bool:
    """
    True when her own reply says, in words, that she is ending the call.

    The safety net under END_SIGNAL — see the note above. Feed it the full reply
    for one turn, and on True treat the turn exactly as a sentinel turn:
    SessionManager.begin_farewell(), then stop after this reply has played.
    """
    if not (sathi_text or "").strip():
        return False

    folded = _fold(sathi_text)
    blockers = list(getattr(lang_service, "SELF_EXIT_BLOCKERS", []) or [])
    for blocker in blockers + _SELF_EXIT_BLOCKERS_BASELINE:
        b = _fold(blocker).strip()
        if b and b in folded:
            return False

    words = _norm_words(sathi_text)
    if not words:
        return False
    phrases = list(getattr(lang_service, "SELF_EXIT_WORDS", []) or [])
    for entry in phrases + _SELF_EXIT_BASELINE:
        seq = _norm_words(entry)
        if seq and _contains(words, seq):
            return True
    return False


# Cross-language safety net: STT sometimes returns another script than the
# configured language, so every call also checks these.
#
# Deliberately no bare numbers here. "112" / "108" / "102" are the numbers SHE
# tells them to dial, not something the caller reports, and matching them as
# substrings turned every ordinary vital reading into an emergency: "शुगर 102",
# "BP 108 over 70" and "pulse 112" all fired the emergency script and pushed the
# call into emergency_followup. See _is_symptom_keyword().
_EMERGENCY_BASELINE = [
    "chest pain", "heart attack", "heartattack",
    "can't breathe", "cannot breathe", "cant breathe",
    "छाती दुखत", "छाती में दर्द", "सीने में दर्द", "सांस नहीं", "हार्ट अटैक",
    "श्वास नाही", "छातीत दुखत", "हार्ट अटॅक",
    "dolor en el pecho", "ataque al corazón", "no puedo respirar",
]


def _is_symptom_keyword(kw: str) -> bool:
    """
    True for keywords that describe how the caller feels.

    A keyword with no letters is a number, and every number an elderly caller
    says on this line is a vital — a sugar reading, a pulse, half a blood
    pressure. Matching one as an emergency is always wrong, so they are dropped
    here rather than only at the definition sites: a language pack that adds
    "108" back cannot silently reintroduce the false positive.
    """
    return any(ch.isalpha() for ch in kw)


def is_emergency(user_text: str, lang_service) -> bool:
    """Hard emergency stop. Keywords come from the language pack when present."""
    t = _fold(user_text)
    if not t.strip():
        return False
    keywords = list(getattr(lang_service, "EMERGENCY_KEYWORDS", []) or [])
    for kw in keywords + _EMERGENCY_BASELINE:
        kw = _fold(kw).strip()
        if kw and _is_symptom_keyword(kw) and kw in t:
            return True
    return False


def _recovery_line(lang_service, name: str, misses: int) -> str:
    """First miss gets 'say that again?'; the next gets 'are you still there?'."""
    if misses <= 1:
        line = getattr(lang_service, "FALLBACK", "") or ""
    else:
        line = (getattr(lang_service, "STILL_THERE", "")
                or getattr(lang_service, "FALLBACK", "") or "")
    return line.format(name=name) if "{name}" in line else line


async def _speak_fixed(text: str, lang_service, voice_lang: str,
                       tts_cfg: dict, recorder=None, prepared: bool = False):
    """Speak a fixed line (recovery / emergency) on the local audio device."""
    if not text or not text.strip():
        return
    if not prepared and hasattr(lang_service, "prepare_for_tts"):
        text = lang_service.prepare_for_tts(text)
    result = await text_to_speech_full(
        text, language=voice_lang,
        speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
        temperature=tts_cfg.get("temperature"),
        pause_ms=tts_cfg.get("pause_ms"),
    )
    wav = result.get("wav_bytes")
    if not wav:
        return
    if recorder:
        recorder.append_wav_bytes(wav)
    from core.audio import play_wav_bytes
    await play_wav_bytes(wav)


# Tones where a bright, exclamatory filler ("अरे...", "Oh...") would land badly.
_HEAVY_TONES = ("emergency", "pain", "sad", "lonely", "worried", "tired")


def pick_thinking_sound(tts_cfg: dict, user_text: str = "",
                        lang_service=None, avoid: str | None = None,
                        force_soft: bool = False) -> str:
    """
    Choose the filler she makes while thinking.

    This used to be sounds[turn_number % len(sounds)] — a fixed round-robin, so
    every call played the identical cycle, and a cheerful "अरे..." could land on
    top of bad news. Now the language pack's soft subset is used when the caller
    sounds unwell or low, and the choice is randomised without repeating.

    The immediate acknowledgement plays the moment they stop speaking, before
    STT has returned for *this* turn, so `user_text` here is the previous
    turn's transcript (`session.last_user_msg`) — a proxy for the caller's
    current mood, not a read of what they just said. On turn 1 it is empty,
    `read_tone("")` returns `None`, and `None` is not a heavy tone, so the
    full pool is used. `force_soft` remains available for callers that want to
    force the soft pool regardless of tone (e.g. tests); no current call site
    sets it.
    """
    sounds = [s for s in (tts_cfg.get("thinking_sounds") or []) if s] or ["..."]

    tone = None
    if not force_soft:
        reader = getattr(lang_service, "read_tone", None)
        if callable(reader):
            try:
                tone = reader(user_text or "")
            except Exception:
                tone = None

    pool = sounds
    if force_soft or tone in _HEAVY_TONES:
        pool = [s for s in (tts_cfg.get("soft_thinking_sounds") or []) if s] or sounds

    choices = [s for s in pool if s != avoid] or pool
    return random.choice(choices)


def thinking_sounds_for(tts_cfg: dict) -> list:
    """Every filler this language might use — for pre-warming the TTS cache."""
    seen = list(tts_cfg.get("thinking_sounds") or [])
    seen += list(tts_cfg.get("soft_thinking_sounds") or [])
    return [s for s in dict.fromkeys(seen) if s and s.strip()]


class ThinkingWatchdog:
    """
    Plays a soft filler while the caller waits, and — this is the part that
    used to be missing — keeps playing one every `repeat_ms` for as long as
    the wait continues, instead of firing exactly once. A single fixed-500ms
    filler is fine for a normal turn, but on a slow one (routinely several
    seconds on Marathi's Sonnet override) the line went dead silent after
    that one sound until the real reply arrived, which is indistinguishable
    from a dropped call. Cancelled the instant the first LLM token arrives,
    same as before, at any point including mid-sleep.
    """

    def __init__(self, player, tts_fn, sound: str, threshold_ms: int,
                 sound_fn=None, repeat_ms: int | None = None,
                 max_repeats: int | None = None):
        self._player      = player
        self._tts_fn      = tts_fn
        self._sound       = sound
        self._sound_fn    = sound_fn  # () -> str, picks each fired sound if given
        self._threshold   = threshold_ms / 1000.0
        self._repeat      = (repeat_ms if repeat_ms is not None else THINKING_REPEAT_MS) / 1000.0
        self._max_repeats = THINKING_MAX_REPEATS if max_repeats is None else max_repeats
        self._task        = None
        self.fired        = False
        self.fire_count   = 0

    async def start(self):
        self._task = asyncio.create_task(self._run())

    async def cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass

    def _next_sound(self) -> str:
        """Only used for repeats — the first fire always speaks `self._sound`,
        the sound already chosen (and recorded as last-played) by the caller
        before `start()` was called."""
        if self._sound_fn:
            try:
                return self._sound_fn() or self._sound
            except Exception:
                return self._sound
        return self._sound

    async def _run(self):
        try:
            await asyncio.sleep(self._threshold)
            if not THINKING_ENABLED: self.fired = True; return
            for i in range(1 + self._max_repeats):
                sound = self._sound if i == 0 else self._next_sound()
                wav = await self._tts_fn(sound)
                if wav:
                    await self._player.enqueue(wav)
                    self.fired = True
                    self.fire_count += 1
                    print(f"\n  {Fore.YELLOW}⏳  \"{sound}\"{Style.RESET_ALL}")
                if i >= self._max_repeats:
                    break
                await asyncio.sleep(self._repeat)
        except asyncio.CancelledError: pass


class OrderedTtsQueue:
    """
    Synthesize phrases in parallel, but enqueue playback in order.
    Prevents sentence 2 playing before sentence 1 when TTS finishes first.

    Any object with an async enqueue(bytes) works here — the local AudioPlayer
    and all three telephony players qualify.
    """

    def __init__(self, player):
        self._player = player
        self._lock = asyncio.Lock()
        self._ready: dict[int, bytes | None] = {}
        self._next = 0
        self.first_enqueued_at: float | None = None

    async def synthesize_and_enqueue(self, seq: int, text: str, language: str, tts_cfg: dict):
        wav = await synthesize_phrase(
            text, language=language,
            speaker=tts_cfg["speaker"],
            pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"))
        async with self._lock:
            self._ready[seq] = wav
            while self._next in self._ready:
                chunk = self._ready.pop(self._next)
                if chunk:
                    if self.first_enqueued_at is None:
                        self.first_enqueued_at = time.time()
                    await self._player.enqueue(chunk)
                self._next += 1


async def run_turn(session, lang_service, wav_path: str | None = None) -> dict:
    """
    Execute one complete conversation turn.
    Returns: { continue, user_text, sathi_text, stt_sec, tts_chars, next_wav }
    `wav_path` is set when the previous turn was interrupted — skip the mic wait.
    """
    t_turn   = time.time()
    language = session.language
    tts_cfg  = lang_service.TTS_CONFIG
    voice_lang = voice_language(lang_service)

    print(f"\n{Fore.BLUE}{'─'*60}")
    print(f"  Turn {session.turn_number} | {__import__('datetime').datetime.now().strftime('%H:%M:%S')}")
    print(f"{'─'*60}{Style.RESET_ALL}")

    # ── A. Record ─────────────────────────────────────────────────
    pre_recorded = wav_path
    live_stt = None
    if pre_recorded:
        wav = pre_recorded
        print(f"  {Fore.CYAN}⏩  Using interrupted speech.{Style.RESET_ALL}")
    else:
        wav_path = f"_turn_{session.session_id[:6]}_{session.turn_number}.wav"
        if is_french_language(voice_lang):
            live_stt = await gladia_record_and_transcribe(wav_path)
            wav = live_stt.get("path")
        else:
            wav = await record_audio(output_path=wav_path)
    if not wav:
        return {"continue": True, "stt_sec": 0, "tts_chars": 0}
    audio_dur = get_audio_duration(wav)

    recorder = getattr(session, "call_recorder", None)

    def _capture_tts(wav_bytes: bytes):
        if recorder:
            recorder.append_wav_bytes(wav_bytes)

    # Player and acknowledgement start BEFORE STT, so the soft "hmm..." lands
    # while transcription is still running rather than after it.
    player = AudioPlayer(on_enqueue=_capture_tts if recorder else None)
    await player.start()
    barge_path = f"_barge_{session.session_id[:6]}_{session.turn_number}.wav"
    barge_task = asyncio.create_task(listen_while_playing(player, barge_path))

    def _next_ack_sound() -> str:
        sound = pick_thinking_sound(
            tts_cfg, session.last_user_msg, lang_service,
            avoid=session.last_thinking_sound,
        )
        session.last_thinking_sound = sound
        return sound

    ack_sound = _next_ack_sound()
    watchdog = ThinkingWatchdog(
        player=player,
        tts_fn=lambda t: synthesize_cached(t, language=voice_lang,
                           speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
                           temperature=tts_cfg.get("temperature")),
        sound=ack_sound,
        sound_fn=_next_ack_sound,
        threshold_ms=THINKING_MS,
    )
    await watchdog.start()

    async def _abort_turn():
        await watchdog.cancel()
        if not barge_task.done():
            player.request_stop()
            player._done_speaking.set()
            barge_task.cancel()
        await player.interrupt()
        await player.stop()

    # ── B. STT ────────────────────────────────────────────────────
    if live_stt is not None:
        stt = live_stt
    elif pre_recorded and is_french_language(voice_lang):
        stt = await gladia_transcribe_file_live(wav, language=voice_lang)
        if not stt.get("transcript"):
            stt = await transcribe(wav, language=voice_lang)
    else:
        stt = await transcribe(wav, language=voice_lang)
    # Keep mic audio in call recording before temp file is deleted
    if recorder:
        recorder.append_wav_file(wav_path)
        recorder.append_silence(350)
    _cleanup(wav_path)
    user_text = stt.get("transcript", "").strip()

    # Nothing heard — say so rather than leaving them in silence.
    if not user_text:
        await _abort_turn()
        misses = session.note_miss()
        if session.gave_up_hearing():
            print(f"  {Fore.YELLOW}⚠️  Nothing heard {misses}x — closing.{Style.RESET_ALL}")
            return {"continue": False, "stt_sec": audio_dur, "tts_chars": 0}
        line = _recovery_line(lang_service, session.user_name, misses)
        print(f"  {Fore.YELLOW}⚠️  Nothing heard ({misses}): {line}{Style.RESET_ALL}")
        await _speak_fixed(line, lang_service, voice_lang, tts_cfg, recorder)
        return {"continue": True, "stt_sec": audio_dur, "tts_chars": len(line)}

    session.note_heard()

    if _looks_like_echo(user_text, session, lang_service):
        await _abort_turn()
        print(f"  {Fore.YELLOW}⚠️  Echo ignored — that was her own voice.{Style.RESET_ALL}")
        return {"continue": True, "stt_sec": audio_dur, "tts_chars": 0}

    # ── C. Record user turn in session ────────────────────────────
    session.record_user_turn(user_text, audio_duration=audio_dur)
    save_conversation(session.user["id"], session.session_id,
                      "user", user_text, audio_duration=audio_dur,
                      language=session.language,
                      prompt_version=session.prompt_version)

    # Emergency: speak the fixed line but keep the call open, so they can say
    # "it's just gas" or "my son is here". It used to hang up immediately.
    if session.phase != "emergency_followup" and is_emergency(user_text, lang_service):
        print(f"  {Fore.RED}🚨 EMERGENCY detected!{Style.RESET_ALL}")
        await _abort_turn()
        await _speak_fixed(lang_service.EMERGENCY, lang_service, voice_lang,
                           tts_cfg, recorder, prepared=True)
        session.record_sathi_turn(lang_service.EMERGENCY,
                                  tts_chars=len(lang_service.EMERGENCY))
        save_conversation(session.user["id"], session.session_id, "sathi",
                          lang_service.EMERGENCY, char_count=len(lang_service.EMERGENCY),
                          language=session.language,
                          prompt_version=session.prompt_version)
        session.begin_emergency_followup()
        return {"continue": True, "user_text": user_text, "stt_sec": audio_dur,
                "tts_chars": len(lang_service.EMERGENCY), "emergency": True}

    # Every reason to stop still earns one reply — she used to just vanish.
    exit_reason = classify_exit(user_text, lang_service)
    if exit_reason:
        print(f"  👋 Exit intent: {exit_reason}")
        session.begin_farewell(exit_reason)

    # ── D. Build prompt ───────────────────────────────────────────
    ctx           = session.build_llm_context()
    system_prompt = build_system(lang_service, session.user_name, ctx)
    messages      = session.get_llm_messages(max_turns=8)

    # ── E+F+G. Stream LLM → parallel TTS → play ──────────────────
    # (player and acknowledgement watchdog were started before STT)
    sathi_sentences  = []
    total_tts_chars  = 0
    pending_tts      = []
    phrase_seq       = 0
    ordered_tts      = OrderedTtsQueue(player)

    print(f"\n  {Fore.GREEN}🤖  Sathi:{Style.RESET_ALL}", end=" ", flush=True)

    token_buffer  = ""
    first_token   = False
    end_signalled = False

    def _accept(raw: str):
        """
        Clean one phrase, pull out the end-of-call signal, speak what is left.

        The signal must come off BEFORE prepare_for_tts — _clean() only strips
        quotes and would send "<<END>>" straight to the voice.
        """
        nonlocal end_signalled, phrase_seq, total_tts_chars
        text, ended = strip_end_signal(raw)
        if ended:
            end_signalled = True
        text = _clean(text.strip())
        if not text or len(text) < 2:
            return
        text = lang_service.prepare_for_tts(text)

        sathi_sentences.append(text)
        print(f"{Fore.GREEN}{text}{Style.RESET_ALL}", end=" ", flush=True)

        # Parallel TTS, ordered playback
        seq = phrase_seq
        phrase_seq += 1
        pending_tts.append(asyncio.create_task(
            ordered_tts.synthesize_and_enqueue(seq, text, voice_lang, tts_cfg)))
        total_tts_chars += len(text)

    stream = stream_tokens(system_prompt, messages, language=language,
                           meter=session.usage)
    try:
        async for token in stream:
            if not token: continue
            if player.interrupted:
                break

            # Cancel watchdog on first token
            if not first_token:
                await watchdog.cancel()
                first_token = True

            token_buffer += token
            # First clause goes to TTS immediately so they hear her sooner.
            phrases, token_buffer = _split(
                token_buffer, allow_early=not sathi_sentences,
            )

            for phrase in phrases:
                if player.interrupted:
                    break
                _accept(phrase)

            # She has said her goodbye — nothing follows the signal.
            if end_signalled:
                break
    finally:
        await stream.aclose()

    # Remaining buffer
    if token_buffer.strip():
        _accept(token_buffer)

    print()

    # The sentinel is the intended path, but models drop it. Once she has said
    # "ठेवते" out loud the call has to end whether or not she remembered to
    # mark it — see announced_hangup().
    if not end_signalled and announced_hangup(" ".join(sathi_sentences), lang_service):
        print(f"  {Fore.YELLOW}👋 She announced the hang-up in her own words"
              f"{Style.RESET_ALL}")
        end_signalled = True

    if end_signalled and session.phase != "farewell":
        print(f"  {Fore.YELLOW}👋 She ended the call herself (end signal)"
              f"{Style.RESET_ALL}")
        session.begin_farewell()

    # Wait for TTS, playback, or a barge-in.
    if pending_tts:
        await asyncio.gather(*pending_tts, return_exceptions=True)
    drain_task = asyncio.create_task(player.drain())
    next_wav = None
    try:
        done, _pending = await asyncio.wait(
            {drain_task, barge_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if barge_task in done:
            next_wav = barge_task.result()
            if next_wav:
                print(f"  {Fore.CYAN}⏩  You cut in — she stopped.{Style.RESET_ALL}")
                for t in pending_tts:
                    if not t.done():
                        t.cancel()
                await player.interrupt()
        else:
            player._done_speaking.set()
            next_wav = await barge_task
    except Exception:
        next_wav = None
    if not drain_task.done():
        await player.interrupt()
    await player.stop()
    if watchdog: await watchdog.cancel()
    if recorder:
        recorder.append_silence(350)
    if next_wav:
        pass
    elif POST_TTS_GAP_S > 0:
        await asyncio.sleep(POST_TTS_GAP_S)

    t_first_audio = ordered_tts.first_enqueued_at
    if t_first_audio is not None:
        since_turn = t_first_audio - t_turn
        after_speech = max(0.0, since_turn - audio_dur)
        print(f"  {Fore.CYAN}⚡ First audio at {since_turn:.2f}s"
              f"  ({after_speech:.2f}s after you stopped){Style.RESET_ALL}")

    sathi_full = " ".join(sathi_sentences).strip()

    # ── H. Record Sathi turn in session ──────────────────────────
    # This also runs fast_extract silently
    session.record_sathi_turn(sathi_full, tts_chars=total_tts_chars)
    if sathi_full:
        save_conversation(session.user["id"], session.session_id,
                          "sathi", sathi_full, char_count=len(sathi_full),
                          language=session.language,
                          prompt_version=session.prompt_version)

    total_turn = time.time() - t_turn
    fa = f"{t_first_audio - t_turn:.2f}s" if t_first_audio else "n/a"
    print(f"\n  {Fore.CYAN}⏱  {total_turn:.2f}s "
          f"(STT {stt.get('latency',0):.2f}s | audio {fa}){Style.RESET_ALL}")

    return {
        "continue":   True,
        "user_text":  user_text,
        "sathi_text": sathi_full,
        "next_wav":   next_wav,
        "stt_sec":    audio_dur,
        "tts_chars":  total_tts_chars,
    }


async def run_text_turn(session, lang_service, user_text: str, *, speak: bool = False) -> dict:
    """
    One turn from typed (or already-transcribed) user text — no microphone.

    Used by TELEPHONY_PROVIDER=local so the Android app can start a call and
    the developer finishes the conversation on a PC browser / CLI without
    Twilio. Saves the same conversation rows as a live call.
    """
    t_turn = time.time()
    language = session.language
    tts_cfg = lang_service.TTS_CONFIG
    voice_lang = voice_language(lang_service)
    user_text = (user_text or "").strip()
    if not user_text:
        return {"continue": True, "user_text": "", "sathi_text": "", "tts_chars": 0, "error": "empty"}

    session.start_turn()
    session.note_heard()
    session.record_user_turn(user_text, audio_duration=0)
    save_conversation(
        session.user["id"], session.session_id, "user", user_text,
        language=session.language, prompt_version=session.prompt_version,
    )

    if session.phase != "emergency_followup" and is_emergency(user_text, lang_service):
        session.record_sathi_turn(lang_service.EMERGENCY, tts_chars=len(lang_service.EMERGENCY))
        save_conversation(
            session.user["id"], session.session_id, "sathi", lang_service.EMERGENCY,
            char_count=len(lang_service.EMERGENCY),
            language=session.language, prompt_version=session.prompt_version,
        )
        session.begin_emergency_followup()
        audio_b64 = None
        if speak:
            r = await text_to_speech_full(
                lang_service.EMERGENCY, language=voice_lang,
                speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
                temperature=tts_cfg.get("temperature"),
                pause_ms=tts_cfg.get("pause_ms"),
            )
            if r.get("wav_bytes"):
                import base64
                audio_b64 = base64.b64encode(r["wav_bytes"]).decode("ascii")
        return {
            "continue": True,
            "user_text": user_text,
            "sathi_text": lang_service.EMERGENCY,
            "tts_chars": len(lang_service.EMERGENCY),
            "emergency": True,
            "call_done": session.is_call_done(),
            "audio_b64": audio_b64,
            "elapsed_s": round(time.time() - t_turn, 2),
        }

    exit_reason = classify_exit(user_text, lang_service)
    if exit_reason:
        session.begin_farewell(exit_reason)

    ctx = session.build_llm_context()
    system_prompt = build_system(lang_service, session.user_name, ctx)
    messages = session.get_llm_messages(max_turns=8)

    sathi_sentences = []
    total_tts_chars = 0
    token_buffer = ""
    end_signalled = False

    def _accept(raw: str):
        nonlocal end_signalled, total_tts_chars
        text, ended = strip_end_signal(raw)
        if ended:
            end_signalled = True
        text = _clean(text.strip())
        if not text or len(text) < 2:
            return
        text = lang_service.prepare_for_tts(text)
        sathi_sentences.append(text)
        total_tts_chars += len(text)

    stream = stream_tokens(system_prompt, messages, language=language, meter=session.usage)
    try:
        async for token in stream:
            if not token:
                continue
            token_buffer += token
            phrases, token_buffer = _split(token_buffer, allow_early=not sathi_sentences)
            for phrase in phrases:
                _accept(phrase)
            if end_signalled:
                break
    finally:
        await stream.aclose()

    if token_buffer.strip():
        _accept(token_buffer)

    if not end_signalled and announced_hangup(" ".join(sathi_sentences), lang_service):
        end_signalled = True
    if end_signalled and session.phase != "farewell":
        session.begin_farewell()

    sathi_full = " ".join(sathi_sentences).strip()
    session.record_sathi_turn(sathi_full, tts_chars=total_tts_chars)
    if sathi_full:
        save_conversation(
            session.user["id"], session.session_id, "sathi", sathi_full,
            char_count=len(sathi_full),
            language=session.language, prompt_version=session.prompt_version,
        )

    audio_b64 = None
    if speak and sathi_full:
        r = await text_to_speech_full(
            sathi_full, language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
            pause_ms=tts_cfg.get("pause_ms"),
        )
        if r.get("wav_bytes"):
            import base64
            audio_b64 = base64.b64encode(r["wav_bytes"]).decode("ascii")

    done = session.is_call_done()
    return {
        "continue": not done,
        "user_text": user_text,
        "sathi_text": sathi_full,
        "tts_chars": total_tts_chars,
        "call_done": done,
        "audio_b64": audio_b64,
        "elapsed_s": round(time.time() - t_turn, 2),
    }


async def iter_spoken_reply(session, lang_service, user_text: str):
    """
    Browser / remote turn: same LLM path as run_text_turn, but yields each
    spoken phrase (text + WAV) as soon as TTS is ready.
    Final yield: {kind: done, sathi_text, call_done}.
    """
    tts_cfg = lang_service.TTS_CONFIG
    voice_lang = voice_language(lang_service)
    language = session.language
    user_text = (user_text or "").strip()
    if not user_text:
        yield {"kind": "done", "sathi_text": "", "call_done": False, "error": "empty"}
        return

    session.start_turn()
    session.note_heard()
    session.record_user_turn(user_text, audio_duration=0)
    save_conversation(
        session.user["id"], session.session_id, "user", user_text,
        language=session.language, prompt_version=session.prompt_version,
    )

    async def _say(text: str):
        wav = await synthesize_phrase(
            text, language=voice_lang,
            speaker=tts_cfg["speaker"], pace=tts_cfg["pace"],
            temperature=tts_cfg.get("temperature"),
        )
        return text, wav

    if session.phase != "emergency_followup" and is_emergency(user_text, lang_service):
        session.record_sathi_turn(lang_service.EMERGENCY, tts_chars=len(lang_service.EMERGENCY))
        save_conversation(
            session.user["id"], session.session_id, "sathi", lang_service.EMERGENCY,
            char_count=len(lang_service.EMERGENCY),
            language=session.language, prompt_version=session.prompt_version,
        )
        session.begin_emergency_followup()
        text, wav = await _say(lang_service.EMERGENCY)
        yield {"kind": "phrase", "text": text, "wav": wav}
        yield {"kind": "done", "sathi_text": lang_service.EMERGENCY, "call_done": False}
        return

    exit_reason = classify_exit(user_text, lang_service)
    if exit_reason:
        session.begin_farewell(exit_reason)

    ctx = session.build_llm_context()
    system_prompt = build_system(lang_service, session.user_name, ctx)
    messages = session.get_llm_messages(max_turns=8)

    sathi_sentences = []
    token_buffer = ""
    end_signalled = False

    async def _accept(raw: str):
        nonlocal end_signalled
        text, ended = strip_end_signal(raw)
        if ended:
            end_signalled = True
        text = _clean(text.strip())
        if not text or len(text) < 2:
            return None
        text = lang_service.prepare_for_tts(text)
        sathi_sentences.append(text)
        spoken, wav = await _say(text)
        return {"kind": "phrase", "text": spoken, "wav": wav}

    stream = stream_tokens(system_prompt, messages, language=language, meter=session.usage)
    try:
        async for token in stream:
            if not token:
                continue
            token_buffer += token
            phrases, token_buffer = _split(token_buffer, allow_early=not sathi_sentences)
            for phrase in phrases:
                item = await _accept(phrase)
                if item:
                    yield item
            if end_signalled:
                break
    finally:
        await stream.aclose()

    if token_buffer.strip():
        item = await _accept(token_buffer)
        if item:
            yield item

    if not end_signalled and announced_hangup(" ".join(sathi_sentences), lang_service):
        end_signalled = True
    if end_signalled and session.phase != "farewell":
        session.begin_farewell()

    sathi_full = " ".join(sathi_sentences).strip()
    session.record_sathi_turn(sathi_full, tts_chars=len(sathi_full))
    if sathi_full:
        save_conversation(
            session.user["id"], session.session_id, "sathi", sathi_full,
            char_count=len(sathi_full),
            language=session.language, prompt_version=session.prompt_version,
        )

    yield {
        "kind": "done",
        "sathi_text": sathi_full,
        "call_done": session.is_call_done(),
    }


def _cleanup(path):
    import os
    try:
        if path and os.path.exists(path): os.remove(path)
    except Exception: pass
