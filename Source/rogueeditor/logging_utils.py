from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime


ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
_LOG_DIR = os.path.normpath(os.path.join(ROOT_DIR, "debug", "logs"))
_LOG_NAME = "app.log"


def ensure_log_dir() -> str:
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception:
        pass
    return _LOG_DIR


def log_file_path() -> str:
    return os.path.join(ensure_log_dir(), _LOG_NAME)


def setup_logging(level: int = logging.DEBUG) -> logging.Logger:
    """Configure a rotating file logger under debug/logs/app.log.

    Returns the configured top-level logger ("rogueeditor").
    """
    ensure_log_dir()
    logger = logging.getLogger("rogueeditor")
    logger.setLevel(level)

    # Avoid duplicate handlers if called twice
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        fhandler = RotatingFileHandler(log_file_path(), maxBytes=512_000, backupCount=3, encoding="utf-8")
        fhandler.setLevel(logging.DEBUG)
        fhandler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(fhandler)

    # Add a simple console handler at INFO if none present
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(ch)

    logger.debug("Logging initialized at %s", log_file_path())
    return logger


def install_excepthook(logger: logging.Logger | None = None) -> None:
    """Install a sys.excepthook that logs uncaught exceptions with traceback."""
    lg = logger or logging.getLogger("rogueeditor")

    def _hook(exc_type, exc, tb):
        lg.error("Uncaught exception:")
        for line in traceback.format_exception(exc_type, exc, tb):
            lg.error(line.rstrip())
        # Chain to default hook for console visibility
        sys.__excepthook__(exc_type, exc, tb)

    try:
        sys.excepthook = _hook
    except Exception:
        pass


def log_environment(logger: logging.Logger | None = None) -> None:
    """Log environment diagnostics helpful for GUI/Tk issues."""
    import platform
    lg = logger or logging.getLogger("rogueeditor")
    lg.debug("Environment diagnostics start")
    lg.info("Platform: %s", platform.platform())
    lg.info("Python: %s", sys.version.replace("\n", " "))
    lg.info("Executable: %s", sys.executable)
    lg.info("CWD: %s", os.getcwd())
    lg.info("Thread: %s | main=%s", threading.current_thread().name, threading.current_thread() is threading.main_thread())

    # Environment variables of interest
    for k in ("TCL_LIBRARY", "TK_LIBRARY", "PYTHONPATH", "PATH"):
        v = os.environ.get(k)
        if v:
            lg.info("%s: %s", k, v)
        else:
            lg.info("%s: <unset>", k)

    # Tkinter diagnostics (without creating a Tk root)
    try:
        import tkinter as tk  # type: ignore
        lg.info("tkinter: %s", getattr(tk, "__file__", "<builtin>"))
        lg.info("TkVersion: %s", getattr(tk, "TkVersion", "?"))
        lg.info("TclVersion: %s", getattr(tk, "TclVersion", "?"))
    except Exception as e:
        lg.warning("tkinter import failed: %s", e)
    try:
        import _tkinter as _tk  # type: ignore
        lg.info("_tkinter: %s", getattr(_tk, "__file__", "<builtin>"))
    except Exception as e:
        lg.warning("_tkinter import failed: %s", e)

    lg.debug("Environment diagnostics end")


class _StderrTee:
    def __init__(self, logger: logging.Logger, original):
        self._logger = logger
        self._orig = original

    def write(self, s: str):
        try:
            if s and not s.isspace():
                self._logger.error("[stderr] %s", s.rstrip())
        except Exception:
            pass
        try:
            self._orig.write(s)
        except Exception:
            pass

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass


def attach_stderr_tee(logger: logging.Logger | None = None) -> None:
    """Mirror anything written to sys.stderr into the logger at ERROR level.

    Useful for capturing native library error lines (e.g., Tcl/Tk) that bypass Python exceptions.
    """
    lg = logger or logging.getLogger("rogueeditor")
    try:
        sys.stderr = _StderrTee(lg, sys.stderr)
    except Exception:
        pass


def log_exception_context(msg: str, logger: logging.Logger | None = None) -> None:
    lg = logger or logging.getLogger("rogueeditor")
    lg.error(msg)
    lg.error("Last exception:")
    lg.error(traceback.format_exc())


def crash_hint() -> str:
    """Return a short hint with the log file location to show users."""
    lf = log_file_path()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{ts}] See log for details: {lf}"
