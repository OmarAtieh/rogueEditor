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
    import argparse
    import sys
    
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="RogueEditor - Pokemon Rogue Save Editor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python RogueEditor.py                    # Launch GUI (default)
  python RogueEditor.py --cli              # Launch CLI interface
  python RogueEditor.py --username myuser --password mypass  # Auto-login GUI
  python RogueEditor.py --u myuser --p mypass  # Auto-login GUI (shorthand)
  python RogueEditor.py --cli --u myuser --p mypass  # Auto-login CLI (shorthand)
        """
    )
    
    # Mode selection
    parser.add_argument('--cli', action='store_true', 
                       help='Launch CLI interface instead of GUI (default)')
    
    # Auto-login parameters
    parser.add_argument('--username', '--u', '-u', 
                       help='Username for automatic login')
    parser.add_argument('--password', '--p', '-p', 
                       help='Password for automatic login')
    
    # Other CLI options
    parser.add_argument('--noninteractive', action='store_true', 
                       help='Run smoke validation using .env credentials and exit')
    parser.add_argument('--csid', 
                       help='Client session id (from browser) for slot endpoints')
    
    args = parser.parse_args()
    
    # Handle noninteractive mode (delegate to CLI)
    if args.noninteractive:
        try:
            import cli
            sys.argv = ['RogueEditor.py', '--noninteractive']
            if args.csid:
                sys.argv.extend(['--csid', args.csid])
            cli.main()
        except Exception as e:
            print(f"Failed to launch CLI: {e}")
            sys.exit(1)
    
    # Default to GUI mode unless --cli is specified
    if args.cli:
        # Launch CLI with auto-login if credentials provided
        try:
            import cli
            if args.username and args.password:
                # Set up auto-login for CLI
                sys.argv = ['RogueEditor.py', '--username', args.username, '--password', args.password]
            else:
                sys.argv = ['RogueEditor.py']
            if args.csid:
                sys.argv.extend(['--csid', args.csid])
            cli.main()
        except Exception as e:
            print(f"Failed to launch CLI: {e}")
            sys.exit(1)
    else:
        # Launch GUI with auto-login if credentials provided
        try:
            from gui import run as run_gui
            
            if args.username and args.password:
                # Set up auto-login for GUI
                import os
                os.environ['ROGUEEDITOR_AUTO_USERNAME'] = args.username
                os.environ['ROGUEEDITOR_AUTO_PASSWORD'] = args.password
            
            sys.exit(run_gui())
        except Exception as e:
            print(f"Failed to launch GUI: {e}")
            sys.exit(1)
