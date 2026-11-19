"""
edu/lang_loader.py — the education counterpart of shared/lang.py.

Packs are built once per process and cached. This is not an optimisation, it is
a correctness requirement: `build_system_blocks()` must return a byte-identical
static prefix on every turn of a call, and rebuilding the pack per call risks a
different institution mtime, a different random choice, or simply a different
object — any of which turns a cache read into a cache write and quietly triples
the cost of the call. CLAUDE.md's warning applies here too: a working cache and
a broken one look identical in `input_tokens` alone.

A note on mid-call language switching
-------------------------------------
It is not supported, and it cannot be enabled from this module. The language is
resolved once per call in telephony/session.py and handed to
core/stt_service.transcribe() as a fixed Sarvam `language_code`, so a parent
who switches from Marathi to English mid-sentence is transcribed by a Marathi
model either way. Making that work needs auto-detecting or code-mixed ASR, a
per-turn language state, and a voice that survives the switch — an
infrastructure change, not a configuration one. Until then: one language per
lead, set on the lead record.
"""

from __future__ import annotations

from edu import config
from edu.institution import Institution, get_institution
from edu.pack_factory import build_pack

_SPECS = {}
_CACHE: dict[str, object] = {}


def _spec(code: str):
    """Imported lazily so a deployment that only uses French never imports unused packs."""
    if code in _SPECS:
        return _SPECS[code]

    if code in ("fr-FR", "fr"):
        from edu.packs import french as spec
    else:
        from edu.packs import english as spec

    _SPECS[code] = spec
    return spec


def load_edu_lang_service(code: str, inst: Institution | None = None):
    """Drop-in replacement for shared.lang.load_lang_service.

    Returns an object exposing the same names the call engine reaches for, so
    services/conversation_engine.py and telephony/session.py need no changes.
    """
    code = (code or config.DEFAULT_LANGUAGE).strip()
    if code not in ("fr-FR", "en-IN"):
        code = "fr-FR"

    if code not in _CACHE:
        _CACHE[code] = build_pack(_spec(code), inst or get_institution())
    return _CACHE[code]


def reset_cache() -> None:
    """Drop cached packs. For tests and for reloading an edited institution
    file without restarting — never call this while a call is in flight."""
    _CACHE.clear()


def voice_language(lang_svc) -> str:
    """BCP-47 code passed to STT and TTS. Same contract as shared.lang."""
    return lang_svc.CODE


def uses_elevenlabs(lang_svc) -> bool:
    """French TTS is ElevenLabs; STT for French is Gladia."""
    return voice_language(lang_svc).split("-")[0].lower() in ("es", "fr")
