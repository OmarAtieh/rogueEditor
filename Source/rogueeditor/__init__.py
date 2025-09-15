"""Modular package for rogueEditor.

Contains API client, configuration, and higher-level editor services.
This package enables incremental migration away from the monolithic
`Source/RogueEditor.py` without breaking existing workflows.
"""

from .api import PokerogueAPI  # re-export for convenience
from .session_manager import SessionManager, SessionObserver, SessionState  # session management

