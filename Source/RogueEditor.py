import json
import os
import sys

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.config import TRAINER_DATA_URL, GAMESAVE_SLOT_URL, DEFAULT_HEADERS
from rogueeditor.token import to_urlsafe_b64

"""
Legacy entry point (compat).

This adapter preserves the original pokeRogue class and method names
while delegating all functionality to the new modular package under
`Source/rogueeditor/`.
"""


class pokeRogue:
    def __init__(self, user: str, password: str, log_error: bool = True):
        # New modular API and editor
        self.api = PokerogueAPI(user, password)
        try:
            token = self.api.login()
        except Exception as e:
            if log_error:
                print(f"Error on __init__ self.auth -> {e}")
            raise

        # Compatibility attributes
        self.auth = token
        # Preserve legacy URL attributes (used only for display/debug historically)
        self.trainer_data_url = TRAINER_DATA_URL
        self.update_trainer_data_url = TRAINER_DATA_URL
        # Legacy file used trailing slash and 0-based slot appended; keep same shape
        self.gamesave_slot_url = f"{GAMESAVE_SLOT_URL}/"
        self.update_gamesave_slot_url = f"{GAMESAVE_SLOT_URL}/"

        # Build legacy-style auth headers for compatibility with debug scripts
        self.auth_headers = {
            **DEFAULT_HEADERS,
            "authorization": f"Bearer {to_urlsafe_b64(self.auth)}",
        }

        self.editor = Editor(self.api)

    # --- Low-level (legacy) API methods ---
    def get_trainer_data(self):
        return self.api.get_trainer()

    def get_gamesave_data(self, slot: int = 1):
        return self.api.get_slot(slot)

    def update_trainer_data(self, payload):
        return self.api.update_trainer(payload)

    def update_gamesave_data(self, slot, payload):
        return self.api.update_slot(slot, payload)

    # --- File helpers (legacy names) ---
    def dump_trainer_data(self):
        self.editor.dump_trainer("trainer.json")

    def dump_gamesave_data(self, slot=None):
        if slot is None:
            try:
                slot = int(input("Slot (1-5): ").strip())
            except Exception:
                print("Invalid slot")
                return
        self.editor.dump_slot(slot, f"slot {slot}.json")

    def update_trainer_data_from_file(self):
        self.editor.update_trainer_from_file("trainer.json")

    def update_gamesave_data_from_file(self, slot=None):
        if slot is None:
            try:
                slot = int(input("Slot (1-5): ").strip())
            except Exception:
                print("Invalid slot")
                return
        self.editor.update_slot_from_file(slot, f"slot {slot}.json")

    # --- High-level actions (legacy names) ---
    def pokedex(self):
        self.editor.pokedex_list()

    def unlock_all_starters(self):
        self.editor.unlock_all_starters()

    def starter_edit(self, dexId=None):  # keep signature for compatibility
        self.editor.starter_edit_interactive()

    def egg_gacha(self):
        self.editor.egg_gacha_interactive()

    def hatch_all_eggs(self):
        self.editor.hatch_all_eggs()


if __name__ == '__main__':
    # Delegate legacy entrypoint to the modular CLI for a single, unified UX
    try:
        import cli  # from Source/cli.py
        cli.main()
    except Exception as e:
        print(f"Failed to launch CLI: {e}")
