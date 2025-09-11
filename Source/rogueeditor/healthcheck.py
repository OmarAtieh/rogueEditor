from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict

from .logging_utils import (
    setup_logging,
    attach_stderr_tee,
    install_excepthook,
    log_environment,
    log_exception_context,
)


from .logging_utils import ROOT_DIR
_STATE_DIR = os.path.normpath(os.path.join(ROOT_DIR, "debug", "logs"))
_STATE_PATH = os.path.join(_STATE_DIR, "app_state.json")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_state_dir() -> str:
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
    except Exception:
        pass
    return _STATE_DIR


def state_path() -> str:
    ensure_state_dir()
    return _STATE_PATH


def load_state() -> Dict[str, Any]:
    try:
        with open(state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(data: Dict[str, Any]) -> None:
    ensure_state_dir()
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        # Best-effort only
        pass


def is_first_run() -> bool:
    st = load_state()
    return not bool(st.get("initialized"))


def last_run_success() -> bool | None:
    st = load_state()
    if "last_success" in st:
        return bool(st.get("last_success"))
    return None


def record_run_result(exit_code: int, trigger: str = "gui") -> None:
    st = load_state()
    st["initialized"] = True
    st["last_run_time"] = _now_str()
    st["last_exit_code"] = int(exit_code)
    st["last_success"] = (exit_code == 0)
    st["last_trigger"] = trigger
    save_state(st)


def _check_write_permissions(logger: logging.Logger) -> dict:
    res: Dict[str, Any] = {"ok": False}
    ensure_state_dir()
    test_path = os.path.join(_STATE_DIR, "_write_test.txt")
    try:
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(f"write test @ {time.time()}\n")
        res["ok"] = True
        os.remove(test_path)
    except Exception as e:
        logger.error("Write permission test failed: %s", e)
        res["error"] = str(e)
    return res


def _check_tk(logger: logging.Logger) -> dict:
    info: Dict[str, Any] = {}
    try:
        import tkinter as tk  # type: ignore
        info["tkinter_import"] = True
        info["TkVersion"] = getattr(tk, "TkVersion", "?")
        info["TclVersion"] = getattr(tk, "TclVersion", "?")
        # Try a minimal root
        try:
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            root.update()
            root.destroy()
            info["tk_root_ok"] = True
        except Exception as e:
            info["tk_root_ok"] = False
            info["tk_root_error"] = str(e)
            logger.error("tk.Tk() init failed: %s", e)
    except Exception as e:
        info["tkinter_import"] = False
        info["tk_import_error"] = str(e)
        logger.error("tkinter import failed: %s", e)
    # Env vars that often cause issues
    for k in ("TCL_LIBRARY", "TK_LIBRARY"):
        v = os.environ.get(k)
        info[k] = v or "<unset>"
    # PATH entries that look relevant
    try:
        parts = (os.environ.get("PATH") or "").split(os.pathsep)
        relevant = [p for p in parts if ("tcl" in p.lower() or "tk" in p.lower())]
        info["PATH_tcltk_entries"] = relevant
    except Exception:
        pass
    return info


def run_healthcheck(trigger: str = "startup") -> dict:
    """Run environment checks and log results. Returns a summary dict.

    This intentionally logs a lot of context to help diagnose GUI startup issues
    (e.g., TclNotifier class registration failures on Windows).
    """
    logger = setup_logging()
    attach_stderr_tee(logger)
    install_excepthook(logger)
    log_environment(logger)
    logger.info("[HEALTHCHECK] trigger=%s", trigger)

    summary: Dict[str, Any] = {"time": _now_str(), "trigger": trigger}
    summary["write_permissions"] = _check_write_permissions(logger)
    summary["tk"] = _check_tk(logger)
    # Save to state
    st = load_state()
    st["last_healthcheck"] = summary
    save_state(st)
    logger.info("[HEALTHCHECK] summary: %s", summary)
    return summary
