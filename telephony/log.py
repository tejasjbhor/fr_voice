"""Structured logging for the call server."""

import logging
import sys


def setup_logging() -> logging.Logger:
    log = logging.getLogger("sathi")
    if log.handlers:
        return log

    log.setLevel(logging.INFO)
    log.propagate = False

    fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler("sathi_call.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(sh)
    log.addHandler(fh)
    return log
