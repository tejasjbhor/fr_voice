"""Inbound counterpart of shared/lang.py — packs cached per process."""

from __future__ import annotations

from inbound import config
from inbound.pack_factory import build_pack

_CACHE: dict[str, object] = {}


def _spec(code: str):
    if code in ("hi-IN", "hi"):
        from inbound.packs import hindi as spec
    elif code in ("mr-IN", "mr"):
        from inbound.packs import marathi as spec
    else:
        from inbound.packs import english as spec
    return spec


def load_inbound_lang_service(code: str | None = None):
    code = (code or config.DEFAULT_LANGUAGE).strip()
    if code not in config.SUPPORTED_LANGUAGES:
        code = config.DEFAULT_LANGUAGE
    if code not in _CACHE:
        _CACHE[code] = build_pack(_spec(code))
    return _CACHE[code]


def reset_cache() -> None:
    _CACHE.clear()


def voice_language(lang_svc) -> str:
    return lang_svc.CODE
