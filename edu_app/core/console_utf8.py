"""Shared console helpers for Windows-safe UTF-8 output."""

import sys


def configure_console_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows cp1252 consoles when printing emoji."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
