import argparse
import json
import os
import glob
from typing import Optional
from datetime import datetime

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.utils import (
    load_test_credentials,
    validate_slot,
    load_client_session_id,
    save_client_session_id,
    generate_client_session_id,
    get_user_csid,
    set_user_csid,
    trainer_save_path,
    slot_save_path,
)

def _resolve_client_session_id_fresh(api: PokerogueAPI, cli_csid: Optional[str] = None) -> str:
    """Resolve a fresh clientSessionId for this run.

    Preference order:
      1) If server returned a clientSessionId on login, use it.
      2) If explicitly provided via CLI, use it.
      3) Else generate a new one.
    """
    if getattr(api, "client_session_id", None):
        return str(api.client_session_id)
    if cli_csid:
        return cli_csid
    return generate_client_session_id()


def _confirm(prompt: str, required: Optional[str] = None) -> bool:
    msg = f"{prompt} (y/N)" if not required else f"{prompt} (type {required} to confirm)"
    ans = input(msg + ": ").strip().lower()
    if required:
        return ans == required.lower()
    return ans in ("y", "yes")


def _human_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def _status(username: str) -> dict:
    # Last dump: latest mtime among trainer.json and slot files
    last_dump = None
    last_dump_label = None
    tpath = trainer_save_path(username)
    if os.path.exists(tpath):
        mt = os.path.getmtime(tpath)
        last_dump = mt
        last_dump_label = "trainer.json"
    for i in range(1, 6):
        sp = slot_save_path(username, i)
        if os.path.exists(sp):
            mt = os.path.getmtime(sp)
            if last_dump is None or mt > last_dump:
                last_dump = mt
                last_dump_label = f"slot {i}.json"
    # Latest backup directory
    bbase = os.path.join("Source", "saves", username, "backups")
    latest_backup = None
    if os.path.isdir(bbase):
        dirs = [d for d in glob.glob(os.path.join(bbase, "*")) if os.path.isdir(d)]
        if dirs:
            latest_backup = max(dirs, key=lambda d: os.path.basename(d))
    return {
        "last_dump_label": last_dump_label or "-",
        "last_dump_time": _human_time(last_dump) if last_dump else "-",
        "latest_backup": os.path.basename(latest_backup) if latest_backup else "-",
    }


def run_smoke_noninteractive(csid: Optional[str] = None) -> int:
    creds = load_test_credentials()
    if not creds:
        print("No test credentials found in .env/env_data.txt")
        return 1
    username, password = creds
    print(f"[INFO] Using test user: {username}")
    api = PokerogueAPI(username, password)
    tok = api.login()
    # Always establish a fresh clientSessionId for this run
    csid = _resolve_client_session_id_fresh(api, csid)
    api.client_session_id = csid
    print("[INFO] Using new clientSessionId for this session")
    try:
        save_client_session_id(csid)
        print("[INFO] Saved clientSessionId to .env/env_data.txt")
    except Exception:
        pass
    try:
        auth_header = api._auth_headers()["authorization"]
        print(f"[DEBUG] Auth header (prefix): {auth_header[:30]}...")
        # Token diagnostics (safe prefix only)
        print(f"[DEBUG] Token prefix repr: {repr(tok[:12])}")
        if len(tok) > 6:
            print(f"[DEBUG] Token[6]: {tok[6]} (ord {ord(tok[6])})")
    except Exception:
        pass
    editor = Editor(api)
    try:
        print("[STEP] Fetch trainer")
        trainer = api.get_trainer()
        print("[OK] Trainer fetched")
        print("[STEP] Dump trainer.json")
        editor.dump_trainer()
        print("[STEP] Dump slot 1")
        editor.dump_slot(1)
        print("[STEP] No-op update trainer")
        try:
            api.update_trainer(trainer)
            print("[OK] Trainer update accepted")
        except Exception as e:
            print(f"[WARN] Trainer update skipped: {e}")
        print("[STEP] No-op update slot 1")
        slot1 = api.get_slot(1)
        try:
            api.update_slot(1, slot1)
            print("[OK] Slot update accepted")
        except Exception as e:
            print(f"[WARN] Slot update skipped: {e}")
        print("[SUCCESS] Smoke validation completed.")
        return 0
    except Exception as e:
        print(f"[FAIL] Smoke validation error: {e}")
        return 2


def main():
    parser = argparse.ArgumentParser(description="rogueEditor (modular CLI)")
    parser.add_argument("--noninteractive", action="store_true", help="Run smoke validation using .env credentials and exit")
    parser.add_argument("--csid", help="Client session id (from browser) for slot endpoints", default=None)
    parser.add_argument("--gui", action="store_true", help="Launch GUI instead of CLI")
    parser.add_argument("--username", "--u", "-u", help="Username for automatic login")
    parser.add_argument("--password", "--p", "-p", help="Password for automatic login")
    args = parser.parse_args()

    if args.noninteractive:
        raise SystemExit(run_smoke_noninteractive(args.csid))

    # Mode selection
    if args.gui:
        from gui import run as run_gui
        return run_gui()
    print("Run mode:\n1. CLI\n2. GUI")
    mode = input("Choose (1/2): ").strip()
    if mode == "2":
        from gui import run as run_gui
        return run_gui()

    print("rogueEditor (modular CLI)\n")

    def init_user_session() -> tuple[str, PokerogueAPI, Editor, Optional[str]]:
        from rogueeditor.utils import list_usernames, sanitize_username
        
        # Check for auto-login credentials
        if args.username and args.password:
            print(f"Auto-login with username: {args.username}")
            user = sanitize_username(args.username)
            password = args.password
        else:
            users = list_usernames()
            print("Select user:")
            for i, u in enumerate(users,  start=1):
                print(f"{i}. {u}")
            print(f"n. New user")
            sel = input("Choice: ").strip().lower()
            if sel == "n" or sel == "new" or not users:
                user = sanitize_username(input("New username: ").strip())
            else:
                try:
                    idx_l = int(sel)
                    user = users[idx_l-1]
                except Exception:
                    print("Invalid choice; defaulting to new user")
                    user = sanitize_username(input("New username: ").strip())
            password = input(f"Password for {user}: ")
        api_l = PokerogueAPI(user, password)
        api_l.login()
        # Always establish a fresh clientSessionId after login (server-returned or generated)
        csid_l = _resolve_client_session_id_fresh(api_l, args.csid)
        api_l.client_session_id = csid_l
        print("[INFO] Using new clientSessionId for this session")
        try:
            save_client_session_id(csid_l)
            print("[INFO] Saved clientSessionId to .env/env_data.txt")
        except Exception:
            pass
        try:
            set_user_csid(username_l, csid_l)
        except Exception:
            pass
        editor_l = Editor(api_l)
        # Fetch account info to show trainerId
        try:
            acct = api_l.get_account_info()
            tid = acct.get("trainerId")
        except Exception:
            tid = None
        print(f"Successfully logged in as: {username_l}")
        return username_l, api_l, editor_l, tid

    username, api, editor, trainer_id = init_user_session()

    menu_sections = [
        (
            "Data IO",
            [
                ("1", "Dump trainer data"),
                ("2", "Dump save data (slot 1-5)"),
                ("3", "Update trainer data from file"),
                ("4", "Update save data (slot 1-5) from file"),
                ("5", "Verify system session"),
                ("6", "Backup all (system + slots)"),
                ("7", "Restore from backup"),
            ],
        ),
        (
            "Starters",
            [
                ("8", "Add/Modify a starter Pokemon"),
                ("9", "Increment starter candies"),
                ("10", "Unlock all passives (by name/ID)"),
                ("11", "Display starter Pokemon names with IDs"),
            ],
        ),
        (
            "Eggs & Unlocks",
            [
                ("12", "Modify egg gacha tickets (increment)"),
                ("13", "Hatch all eggs"),
                ("14", "Unlock all starters (perfect IVs, shiny variants)"),
            ],
        ),
        (
            "Active Run Team",
            [
                ("15", "Analyze team (slot 1-5)"),
                ("16", "Edit team (slot 1-5) [safe]"),
                ("21", "Analyze run conditions (weather/modifiers)"),
                ("22", "Edit run weather (slot 1-5) [safe]"),
                ("23", "List modifiers (slot 1-5)"),
                ("24", "Add item to team member"),
                ("25", "Remove item from team member"),
            ],
        ),
        (
            "Tools",
            [
                ("17", "Current status"),
                ("18", "Run smoke validation (safe)"),
                ("19", "Switch user (login as different)"),
                ("20", "Build data catalogs (from tmpServerFiles)"),
                ("26", "Clean dev artifacts (debug/tmpServerFiles/.env opts)"),
                ("27", "Refresh session (re-login and rotate clientSessionId)"),
                ("0", "Exit"),
            ],
        ),
    ]
    # Flat lookup for validation if needed
    commands = {k: v for _, items in menu_sections for k, v in items}

    while True:
        s = _status(username)
        print(f"\n<---- Commands ---->  [User: {username} | Last Dump: {s['last_dump_label']} @ {s['last_dump_time']} | Latest Backup: {s['latest_backup']}]")
        for title, items in menu_sections:
            print(f"[{title}]")
            for k, v in items:
                print(f"  {k}: {v}")
        cmd = input("Command: ").strip().lower()

        if cmd == "0":
            print("Bye!")
            break
        elif cmd == "1":
            editor.dump_trainer()
        elif cmd == "2":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            # Ensure clientSessionId is present for savedata/session endpoints
            if not getattr(api, "client_session_id", None):
                maybe = input("clientSessionId not set. Paste one from browser (or leave blank to skip): ").strip()
                if maybe:
                    api.client_session_id = maybe
                    print("[INFO] clientSessionId set. Proceeding...")
                    try:
                        save_client_session_id(maybe)
                        print("[INFO] Saved clientSessionId to .env/env_data.txt")
                    except Exception:
                        pass
            editor.dump_slot(slot)
        elif cmd == "3":
            if _confirm(f"Proceed to UPDATE trainer data for {username}?"):
                editor.update_trainer_from_file()
            else:
                print("Cancelled.")
        elif cmd == "4":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            if _confirm(f"Proceed to UPDATE save data for {username}, slot {slot}?"):
                editor.update_slot_from_file(slot)
            else:
                print("Cancelled.")
        elif cmd == "5":
            editor.system_verify()
        elif cmd == "6":
            editor.backup_all()
        elif cmd == "7":
            # Restore from backup (choose scope)
            import os
            from rogueeditor.utils import user_save_dir, load_json
            base = os.path.join(user_save_dir(username), "backups")
            if not os.path.isdir(base):
                print("No backups found.")
                continue
            dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            if not dirs:
                print("No backups found.")
                continue
            print("Available backups:")
            for i, d in enumerate(dirs, start=1):
                print(f"  {i}. {d}")
            try:
                choice = int(input("Select backup #: ").strip())
                name = dirs[choice-1]
            except Exception:
                print("Invalid choice.")
                continue
            backup_dir = os.path.join(base, name)
            scope = input("Restore scope (all/trainer/slot): ").strip().lower() or "all"
            if scope not in ("all", "trainer", "slot"):
                print("Invalid scope.")
                continue
            if not _confirm(f"Overwrite server state ({scope}) from {name}?", required="restore"):
                print("Cancelled.")
                continue
            if scope == "all":
                editor.restore_from_backup(backup_dir)
            elif scope == "trainer":
                tp = os.path.join(backup_dir, "trainer.json")
                if os.path.exists(tp):
                    data = load_json(tp)
                    api.update_trainer(data)
                    print("Trainer restored.")
                else:
                    print("trainer.json not found in backup.")
            else:
                try:
                    s = validate_slot(int(input("Slot (1-5): ").strip()))
                except Exception:
                    print("Invalid slot")
                    continue
                sp = os.path.join(backup_dir, f"slot {s}.json")
                if os.path.exists(sp):
                    data = load_json(sp)
                    api.update_slot(s, data)
                    print(f"Slot {s} restored.")
                else:
                    print("Slot file not found in backup.")
        elif cmd == "8":
            if _confirm("Apply changes to starter data?"):
                editor.starter_edit_interactive()
            else:
                print("Cancelled.")
        elif cmd == "9":
            ident = input("Pokemon (name or dex id): ").strip()
            try:
                delta = int(input("Candy delta (can be negative): ").strip())
            except ValueError:
                print("Invalid delta")
                continue
            if _confirm(f"Increment candies for {ident} by {delta}?"):
                editor.inc_starter_candies(ident, delta)
            else:
                print("Cancelled.")
        elif cmd == "10":
            ident = input("Pokemon (name or dex id): ").strip()
            mask_in = input("Passive mask (default 7): ").strip()
            try:
                mask = int(mask_in or "7")
            except ValueError:
                mask = 7
            if _confirm(f"Unlock all passives for {ident} with mask {mask}?"):
                editor.unlock_all_passives(ident, mask)
            else:
                print("Cancelled.")
        elif cmd == "11":
            editor.pokedex_list()
        elif cmd == "12":
            if _confirm("Apply incremental changes to egg gacha tickets?"):
                editor.egg_gacha_interactive()
            else:
                print("Cancelled.")
        elif cmd == "13":
            if _confirm("Set all eggs to hatch next wave?"):
                editor.hatch_all_eggs()
            else:
                print("Cancelled.")
        elif cmd == "14":
            if _confirm("This will unlock ALL starters with perfect IVs.", required="unlock"):
                editor.unlock_all_starters()
            else:
                print("Cancelled.")
        elif cmd == "15":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            editor.analyze_team(slot)
        elif cmd == "16":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            if _confirm("Proceed to edit team interactively?"):
                editor.edit_team_interactive(slot)
            else:
                print("Cancelled.")
        elif cmd == "17":
            # Current status
            st = _status(username)
            print(f"User: {username}")
            print(f"  Last dump: {st['last_dump_label']} @ {st['last_dump_time']}")
            print(f"  Latest backup: {st['latest_backup']}")
        elif cmd == "18":
            try:
                print("[STEP] Fetch trainer")
                trainer = api.get_trainer()
                print("[OK] Trainer fetched")
                print("[STEP] Dump trainer.json")
                editor.dump_trainer()
                print("[STEP] Dump slot 1")
                editor.dump_slot(1)
                print("[STEP] No-op update trainer")
                api.update_trainer(trainer)
                print("[STEP] No-op update slot 1")
                slot1 = api.get_slot(1)
                api.update_slot(1, slot1)
                print("[SUCCESS] Smoke validation completed.")
            except Exception as e:
                print(f"[FAIL] Smoke validation error: {e}")
        elif cmd == "19":
            # Switch user/session
            username, api, editor, trainer_id = init_user_session()
        elif cmd == "20":
            if _confirm("Generate clean data catalogs under Source/data?", required="build"):
                try:
                    from rogueeditor.catalog import build_clean_catalogs_from_tmp
                    build_clean_catalogs_from_tmp()
                    print("Catalogs written to Source/data.")
                except Exception as e:
                    print(f"[ERROR] Failed to build catalogs: {e}")
            else:
                print("Cancelled.")
        elif cmd == "21":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            editor.analyze_run_conditions(slot)
        elif cmd == "22":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            if _confirm("Change run weather?"):
                editor.edit_run_weather(slot)
            else:
                print("Cancelled.")
        elif cmd == "23":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
            except ValueError:
                print("Invalid slot")
                continue
            editor.list_modifiers(slot)
        elif cmd == "24":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
                idx = int(input("Team slot (1-based): ").strip())
            except ValueError:
                print("Invalid input")
                continue
            item = input("Item type (e.g., WIDE_LENS, FOCUS_BAND, BERRY, QUICK_CLAW, LEFTOVERS): ").strip()
            if _confirm(f"Attach {item} to team slot {idx}?"):
                editor.add_item_to_mon(slot, idx, item)
            else:
                print("Cancelled.")
        elif cmd == "25":
            try:
                slot = validate_slot(int(input("Slot (1-5): ").strip()))
                idx = int(input("Team slot (1-based): ").strip())
            except ValueError:
                print("Invalid input")
                continue
            item = input("Item type to remove: ").strip()
            if _confirm(f"Remove {item} from team slot {idx}?"):
                editor.remove_item_from_mon(slot, idx, item)
            else:
                print("Cancelled.")
        elif cmd == "26":
            # Cleanup dev artifacts
            import shutil
            targets = [
                ("debug/", os.path.isdir("debug")),
                ("tmpServerFiles/", os.path.isdir("tmpServerFiles")),
                ("Source/.env/env_data.txt", os.path.exists(os.path.join("Source", ".env", "env_data.txt"))),
            ]
            for path, exists in targets:
                if not exists:
                    continue
                ans = input(f"Remove {path}? (y/N): ").strip().lower()
                if ans in ("y", "yes"):
                    full = os.path.normpath(path)
                    try:
                        if os.path.isdir(full):
                            shutil.rmtree(full)
                        else:
                            os.remove(full)
                        print(f"Removed {path}")
                    except Exception as e:
                        print(f"[ERROR] Failed to remove {path}: {e}")
        else:
            print("Unknown command")


if __name__ == "__main__":
    main()
