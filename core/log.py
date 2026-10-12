"""A small rotating log file, so a problem can be diagnosed after the fact. It never records the AI brief, tokens or game
contents: only what Plunge did and the errors it hit."""
import logging
import logging.handlers
import sys
import threading

from . import paths

LOGGER = logging.getLogger("plunge")
_READY = {"on": False}


def log_dir():
    return paths.DATA / "logs"


def setup():
    """Idempotent. Also catches errors nobody else handles, so a crash leaves a trace."""
    if _READY["on"]:
        return LOGGER
    _READY["on"] = True
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(log_dir() / "plunge.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(h)
        LOGGER.setLevel(logging.INFO)
    except OSError:
        pass                                           # logging must never stop the app from starting

    def hook(exc_type, exc, tb):
        LOGGER.error("unhandled error", exc_info=(exc_type, exc, tb))
    sys.excepthook = hook
    threading.excepthook = lambda a: LOGGER.error("unhandled error in a thread", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return LOGGER
