"""App assembly for the modular GUI.

During migration, `Source/gui.py` remains the primary entry point. Once all
sections are extracted, `Source/gui.py` will import and call `run()` from here.

For now, this file provides a placeholder `run()` to enable early switching
if desired. The full App class and assembly logic will move here in Phase 4.
"""

def run():  # placeholder to be replaced in Phase 4
    from .. import __name__ as _pkg  # noqa: F401
    raise SystemExit("gui.app.run() is not wired yet; continue using Source/gui.py during migration.")

