"""GUI package for rogueEditor.

During migration, the legacy monolith `Source/gui.py` remains the primary
implementation of the App. This package provides a compatibility `run()`
entrypoint so callers (e.g., CLI with `--gui`) can import `gui.run` while
we gradually extract modules.

See `debug/docs/GUI_MIGRATION_PLAN.md` for status.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType
from rogueeditor.logging_utils import (
    setup_logging,
    install_excepthook,
    log_environment,
    log_exception_context,
    crash_hint,
    attach_stderr_tee,
)
from rogueeditor.healthcheck import run_healthcheck


def _load_legacy_gui() -> ModuleType:
    """Dynamically load the legacy Source/gui.py module under a safe name.

    This avoids the package/module name collision with this package.
    """
    base = os.path.dirname(__file__)
    legacy_path = os.path.normpath(os.path.join(base, os.pardir, 'gui.py'))
    spec = importlib.util.spec_from_file_location('gui_legacy', legacy_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Unable to locate legacy GUI module at ' + legacy_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['gui_legacy'] = mod
    spec.loader.exec_module(mod)
    return mod


def run() -> int:
    """Launch the legacy GUI from Source/gui.py.

    Returns process exit code (0 on success).
    """
    # Initialize logging BEFORE loading legacy module to capture import-time errors
    logger = setup_logging()
    attach_stderr_tee(logger)
    install_excepthook(logger)
    log_environment(logger)
    try:
        # Always run a quick healthcheck before loading legacy GUI to capture Tk issues early
        try:
            run_healthcheck(trigger="preload")
        except Exception:
            log_exception_context("Preload healthcheck failed", logger)
        mod = _load_legacy_gui()
    except Exception:
        log_exception_context("Failed to load legacy GUI module", logger)
        print("[ERROR] Failed to load GUI module.")
        print(crash_hint())
        return 2
    # Prefer legacy run() if present, else construct App
    if hasattr(mod, 'run') and callable(getattr(mod, 'run')):
        try:
            return int(mod.run() or 0)
        except Exception:
            log_exception_context("Unhandled error during GUI run()", logger)
            print("[ERROR] Unhandled GUI error.")
            print(crash_hint())
            return 3
    if hasattr(mod, 'App'):
        try:
            # Fallback: construct App if run() is missing
            app = mod.App()
            app.mainloop()
            return 0
        except Exception:
            log_exception_context("Unhandled error creating legacy App", logger)
            print("[ERROR] Failed to start GUI.")
            print(crash_hint())
            return 4
    raise RuntimeError('Legacy GUI missing run()/App entrypoint')
