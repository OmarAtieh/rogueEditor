from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, Optional

from .api import PokerogueAPI
from .utils import (
    load_pokemon_index,
    dump_json,
    load_json,
    trainer_save_path,
    slot_save_path,
    user_save_dir,
    invert_dex_map,
    find_team_candidates,
    get_by_path,
    select_from_catalog,
)
from .catalog import load_move_catalog, load_ability_catalog, load_nature_catalog, load_weather_catalog, load_modifier_catalog


class Editor:
    def __init__(self, api: PokerogueAPI):
        self.api = api

    # 1. Hatch all eggs
    def hatch_all_eggs(self) -> None:
        data = self.api.get_trainer()
        eggs = data.get("eggs") or []
        if not eggs:
            print("You have no eggs to hatch!")
            return
        for egg in eggs:
            egg["hatchWaves"] = 0
        data["eggs"] = eggs
        self.api.update_trainer(data)
        print("Done! -> Your eggs will hatch after the next wave!")

    # 2. Dump trainer data
    def dump_trainer(self, path: Optional[str] = None) -> None:
        data = self.api.get_trainer()
        path = path or trainer_save_path(self.api.username)
        dump_json(path, data)
        print(f"Wrote {path}")

    # 3. Dump slot data
    def dump_slot(self, slot: int, path: Optional[str] = None) -> None:
        data = self.api.get_slot(slot)
        path = path or slot_save_path(self.api.username, slot)
        dump_json(path, data)
        print(f"Wrote {path}")

    # 4. Update trainer from file
    def update_trainer_from_file(self, path: Optional[str] = None) -> None:
        path = path or trainer_save_path(self.api.username)
        if not os.path.exists(path):
            print(f"{path} was not found!")
            return
        try:
            data = load_json(path)
        except Exception as e:
            print(f"Invalid JSON in {path}: {e}")
            return
        if not isinstance(data, dict):
            print(f"{path} must contain a JSON object at the top level.")
            return
        self.api.update_trainer(data)
        print("Your trainer data has been updated!")

    # 5. Update slot from file
    def update_slot_from_file(self, slot: int, path: Optional[str] = None) -> None:
        path = path or slot_save_path(self.api.username, slot)
        if not os.path.exists(path):
            print(f"{path} was not found!")
            return
        try:
            data = load_json(path)
        except Exception as e:
            print(f"Invalid JSON in {path}: {e}")
            return
        if not isinstance(data, dict):
            print(f"{path} must contain a JSON object at the top level.")
            return
        self.api.update_slot(slot, data)
        print(f"Your save data has been updated in slot: {slot}!")

    # 6. Starter edit (interactive)
    def starter_edit_interactive(self) -> None:
        index = load_pokemon_index()
        dex_map: Dict[str, str] = index.get("dex", {})
        data = self.api.get_trainer()

        dex_id = input("Which Pokemon? (Pokemon name / Pokedex ID): ").strip()
        # Normalize ID
        if dex_id.isnumeric():
            if dex_id not in data.get("starterData", {}):
                print(f"There's no Pokemon with the ID: {dex_id}")
                return
        else:
            key = dex_id.lower()
            if key in dex_map:
                dex_id = dex_map[key]
            else:
                print(f"There's no Pokemon with the Name: {dex_id}")
                return

        is_shiny = int(input("Shiny? (1: Yes, 2: No): ").strip())
        caught = int(input("Caught count (>=1): ").strip())
        hatched = int(input("Hatched count (>=0): ").strip())
        seen_count = int(input("Seen count (>=caught): ").strip())
        # Use standard Pokémon stat order for IVs: HP, Attack, Defense, Sp. Atk, Sp. Def, Speed
        hp_iv = int(input("HP IV: ").strip())
        atk_iv = int(input("Attack IV: ").strip())
        def_iv = int(input("Defense IV: ").strip())
        spatk_iv = int(input("Special Attack IV: ").strip())
        spdef_iv = int(input("Special Defense IV: ").strip())
        spd_iv = int(input("Speed IV: ").strip())
        # Optional advanced fields
        try:
            ability_attr = int(input("Ability attr (default 7): ").strip() or "7")
        except ValueError:
            ability_attr = 7
        try:
            passive_attr = int(input("Passive attr (default 0): ").strip() or "0")
        except ValueError:
            passive_attr = 0
        try:
            value_reduction = int(input("Value reduction (default 0): ").strip() or "0")
        except ValueError:
            value_reduction = 0

        is_shiny_attr = 255 if is_shiny == 1 else 253
        data.setdefault("dexData", {})[dex_id] = {
            "seenAttr": 479,
            "caughtAttr": is_shiny_attr,
            "natureAttr": 67108862,
            "seenCount": seen_count,
            "caughtCount": caught,
            "hatchedCount": hatched,
            # Correct order: [HP, Attack, Defense, Sp. Atk, Sp. Def, Speed]
            "ivs": [hp_iv, atk_iv, def_iv, spatk_iv, spdef_iv, spd_iv],
        }
        data.setdefault("starterData", {})[dex_id] = {
            "moveset": None,
            "eggMoves": 15,
            "candyCount": caught + (hatched * 2),
            "abilityAttr": ability_attr,
            "passiveAttr": passive_attr,
            "valueReduction": value_reduction,
        }
        self.api.update_trainer(data)
        print(f"The Pokemon with the dex entry of {dex_id} has been updated!")

    # 7. Egg gacha (interactive)
    def egg_gacha_interactive(self) -> None:
        data = self.api.get_trainer()
        current = data.get("voucherCounts") or {}
        # Normalize existing counts
        def cur(k: str) -> int:
            try:
                return int(current.get(k, 0))
            except Exception:
                return 0
        print("Enter deltas (can be negative). Leave blank for 0.")
        try:
            d0 = int(input(f"[Common] Δ (current {cur('0')}): ").strip() or "0")
            d1 = int(input(f"[Rare] Δ (current {cur('1')}): ").strip() or "0")
            d2 = int(input(f"[Epic] Δ (current {cur('2')}): ").strip() or "0")
            d3 = int(input(f"[Legendary] Δ (current {cur('3')}): ").strip() or "0")
        except ValueError:
            print("Invalid delta input")
            return
        updated = {
            "0": max(0, cur("0") + d0),
            "1": max(0, cur("1") + d1),
            "2": max(0, cur("2") + d2),
            "3": max(0, cur("3") + d3),
        }
        data["voucherCounts"] = updated
        self.api.update_trainer(data)
        print("Your gacha tickets have been updated (incremental change applied).")

    # 8. Unlock all starters
    def unlock_all_starters(self) -> None:
        data = self.api.get_trainer()
        total_caught = 0
        total_seen = 0

        for entry in list(data.get("dexData", {}).keys()):
            caught = random.randint(150, 250)
            seen = random.randint(150, 350)
            total_caught += caught
            total_seen += seen

            data["dexData"][entry] = {
                "seenAttr": 479,
                "caughtAttr": 255,
                "natureAttr": 67108862,
                "seenCount": seen,
                "caughtCount": caught,
                "hatchedCount": 0,
                "ivs": [31, 31, 31, 31, 31, 31],
            }

            data.setdefault("starterData", {})[entry] = {
                "moveset": None,
                "eggMoves": 15,
                "candyCount": caught + 20,
                "abilityAttr": 7,
                "passiveAttr": 0,
                "valueReduction": 0,
            }

            data.setdefault("gameStats", {})["battles"] = total_caught + random.randint(
                1, total_caught or 1
            )
            data["gameStats"]["pokemonCaught"] = total_caught
            data["gameStats"]["pokemonSeen"] = total_seen
            data["gameStats"]["shinyPokemonCaught"] = len(list(data.get("dexData", {}))) * 2

        self.api.update_trainer(data)
        print("All starter Pokemon have been unlocked with perfect IVs and shiny forms!")

    # 9. Pokedex listing
    def pokedex_list(self) -> None:
        index = load_pokemon_index()
        dex_map: Dict[str, str] = index.get("dex", {})
        lines = [f"{dex_map[name]}: {name}" for name in dex_map]
        print("\n".join(lines))

    # 10. Set starter candies (by name or dex id)
    def set_starter_candies(self, identifier: str, candies: int) -> None:
        if candies < 0:
            print("Candy count must be >= 0")
            return
        data = self.api.get_trainer()
        index = load_pokemon_index()
        dex_map: Dict[str, str] = index.get("dex", {})

        dex_id = identifier.strip()
        if not dex_id.isnumeric():
            key = dex_id.lower()
            if key not in dex_map:
                print(f"There's no Pokemon with the Name: {identifier}")
                return
            dex_id = dex_map[key]

        # Ensure starterData entry exists
        data.setdefault("starterData", {})
        entry = data["starterData"].get(dex_id) or {
            "moveset": None,
            "eggMoves": 15,
            "candyCount": 0,
            "abilityAttr": 7,
            "passiveAttr": 0,
            "valueReduction": 0,
        }
        entry["candyCount"] = candies
        data["starterData"][dex_id] = entry

        self.api.update_trainer(data)
        print(f"Candy count for dex {dex_id} set to {candies}.")

    def inc_starter_candies(self, identifier: str, delta: int) -> None:
        data = self.api.get_trainer()
        index = load_pokemon_index()
        dex_map: Dict[str, str] = index.get("dex", {})
        dex_id = identifier.strip()
        if not dex_id.isnumeric():
            key = dex_id.lower()
            if key not in dex_map:
                print(f"There's no Pokemon with the Name: {identifier}")
                return
            dex_id = dex_map[key]
        data.setdefault("starterData", {})
        entry = data["starterData"].get(dex_id) or {
            "moveset": None,
            "eggMoves": 15,
            "candyCount": 0,
            "abilityAttr": 7,
            "passiveAttr": 0,
            "valueReduction": 0,
        }
        entry["candyCount"] = max(0, int(entry.get("candyCount", 0)) + delta)
        data["starterData"][dex_id] = entry
        self.api.update_trainer(data)
        print(f"Candy count for dex {dex_id} changed by {delta} -> {entry['candyCount']}.")

    def unlock_all_passives(self, identifier: str, mask: int = 7) -> None:
        data = self.api.get_trainer()
        index = load_pokemon_index()
        dex_map: Dict[str, str] = index.get("dex", {})
        dex_id = identifier.strip()
        if not dex_id.isnumeric():
            key = dex_id.lower()
            if key not in dex_map:
                print(f"There's no Pokemon with the Name: {identifier}")
                return
            dex_id = dex_map[key]
        data.setdefault("starterData", {})
        entry = data["starterData"].get(dex_id) or {
            "moveset": None,
            "eggMoves": 15,
            "candyCount": 0,
            "abilityAttr": 7,
            "passiveAttr": 0,
            "valueReduction": 0,
        }
        entry["passiveAttr"] = mask
        data["starterData"][dex_id] = entry
        self.api.update_trainer(data)
        print(f"All passives unlocked for dex {dex_id} (mask={mask}).")

    def system_verify(self) -> None:
        resp = self.api.system_verify()
        valid = resp.get("valid")
        if valid:
            print("System session is active and valid.")
        else:
            print("System session was not active. Server state returned and session updated.")
            if "systemData" in resp:
                print("Server system snapshot received.")

    def backup_all(self) -> str:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(user_save_dir(self.api.username), "backups", ts)
        os.makedirs(base, exist_ok=True)
        # System (trainer-like)
        trainer = self.api.get_trainer()
        dump_json(os.path.join(base, "trainer.json"), trainer)
        # Slots 1..5
        for slot in range(1, 6):
            try:
                s = self.api.get_slot(slot)
                dump_json(os.path.join(base, f"slot {slot}.json"), s)
            except Exception:
                # Skip missing slots
                continue
        print(f"Backup created at: {base}")
        return base

    def restore_from_backup(self, backup_dir: str, restore_slots: Optional[list[int]] = None) -> None:
        # Restore trainer
        trainer_path = os.path.join(backup_dir, "trainer.json")
        if os.path.exists(trainer_path):
            trainer = load_json(trainer_path)
            self.api.update_trainer(trainer)
        # Restore slots
        slots = restore_slots or [1, 2, 3, 4, 5]
        for slot in slots:
            path = os.path.join(backup_dir, f"slot {slot}.json")
            if os.path.exists(path):
                data = load_json(path)
                try:
                    self.api.update_slot(slot, data)
                except Exception as e:
                    print(f"[WARN] Failed to restore slot {slot}: {e}")
        print("Restore completed.")

    # --- Active Run Team helpers ---
    def analyze_team(self, slot: int) -> None:
        data = self.api.get_slot(slot)
        cands = find_team_candidates(data)
        if not cands:
            print("No plausible team arrays found.")
            return
        index = load_pokemon_index()
        inv = invert_dex_map(index)
        for idx, (path, team) in enumerate(cands, start=1):
            print(f"[{idx}] Team path: {'.'.join(path)} (size={len(team)})")
            for i, mon in enumerate(team, start=1):
                did = str(mon.get("dexId") or mon.get("speciesId") or mon.get("pokemonId") or mon.get("species") or "?")
                name = inv.get(did, did)
                lvl = mon.get("level") or mon.get("lvl") or "?"
                print(f"  {i}. {name} (dex {did}) lvl={lvl}")

    def edit_team_interactive(self, slot: int) -> None:
        # Load and detect
        data = self.api.get_slot(slot)
        cands = find_team_candidates(data)
        if not cands:
            print("No plausible team arrays found.")
            return
        if len(cands) > 1:
            print("Multiple team candidates found:")
            for idx, (path, team) in enumerate(cands, start=1):
                print(f"  {idx}. {'.'.join(path)} (size={len(team)})")
            try:
                sel = int(input("Select team #: ").strip())
                path, team = cands[sel-1]
            except Exception:
                print("Invalid selection")
                return
        else:
            path, team = cands[0]
        # Show team
        index = load_pokemon_index()
        inv = invert_dex_map(index)
        def label(mon):
            did = str(mon.get("dexId") or mon.get("speciesId") or mon.get("pokemonId") or mon.get("species") or "?")
            return inv.get(did, did)
        print(f"Editing team at: {'.'.join(path)}")
        for i, mon in enumerate(team, start=1):
            print(f"  {i}. {label(mon)} lvl={mon.get('level') or mon.get('lvl')}")
        try:
            which = int(input("Which slot to edit (1-based): ").strip())
            mon = team[which-1]
        except Exception:
            print("Invalid selection")
            return
        # Edit fields safely
        # Level
        lv_in = input("New level (blank to keep): ").strip()
        if lv_in:
            try:
                lv = int(lv_in)
                if "level" in mon:
                    mon["level"] = lv
                elif "lvl" in mon:
                    mon["lvl"] = lv
            except ValueError:
                print("Invalid level; skipped")
        # IVs if present
        ivs = mon.get("ivs")
        if isinstance(ivs, list) and len(ivs) == 6:
            print("Enter IVs (blank to keep): HP, Atk, Def, SpA, SpD, Spe")
            prompts = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
            new_ivs = ivs[:]
            for idx, label_name in enumerate(prompts):
                val = input(f"  {label_name}: ").strip()
                if val:
                    try:
                        new_ivs[idx] = int(val)
                    except ValueError:
                        print(f"    Invalid {label_name}; kept {ivs[idx]}")
            mon["ivs"] = new_ivs
        # Moves (support various formats); allow name or id
        moves_key = None
        moves_val = None
        for k in ("moves", "moveIds", "moveset"):
            v = mon.get(k)
            if isinstance(v, list) and 1 <= len(v) <= 4:
                moves_key = k
                moves_val = v
                break
        if moves_key:
            move_name_to_id, move_id_to_name = load_move_catalog()
            print("Edit moves (id or name; blank=keep, '-'=clear)")
            for i in range(4):
                cur = moves_val[i] if i < len(moves_val) else None
                # Normalize current display
                if isinstance(cur, dict):
                    cid = cur.get("id") or cur.get("moveId") or cur
                else:
                    cid = cur
                name_disp = move_id_to_name.get(int(cid), cid) if isinstance(cid, int) else cid
                val = input(f"  Move {i+1} (current {name_disp}): ").strip()
                if not val:
                    continue
                if val == "-":
                    # Clear move slot if possible
                    if i < len(moves_val):
                        if isinstance(moves_val[i], dict):
                            if "id" in moves_val[i]:
                                moves_val[i]["id"] = 0
                            elif "moveId" in moves_val[i]:
                                moves_val[i]["moveId"] = 0
                            else:
                                moves_val[i] = 0
                        else:
                            moves_val[i] = 0
                    else:
                        moves_val.append(0)
                    continue
                if val.isdigit():
                    mid = int(val)
                else:
                    res = select_from_catalog("    Search move: ", move_name_to_id)
                    if res is None:
                        print("    Skipped; kept current")
                        continue
                    mid = res
                if i < len(moves_val):
                    if isinstance(moves_val[i], dict):
                        if "id" in moves_val[i]:
                            moves_val[i]["id"] = mid
                        elif "moveId" in moves_val[i]:
                            moves_val[i]["moveId"] = mid
                        else:
                            moves_val[i] = mid
                    else:
                        moves_val[i] = mid
                else:
                    moves_val.append(mid)
            mon[moves_key] = moves_val
        # Held item
        item_key = None
        for k in ("heldItemId", "heldItemID", "heldItem", "item"):
            if k in mon:
                item_key = k
                break
        if item_key:
            cur_item = mon.get(item_key)
            val = input(f"Held item id (current {cur_item}, blank=keep, '-'=clear): ").strip()
            if val == "-":
                mon[item_key] = 0
            elif val:
                try:
                    mon[item_key] = int(val)
                except ValueError:
                    print("    Invalid item id; kept")
        # Ability id (not to be confused with abilityAttr); allow name or id
        abil_key = None
        for k in ("abilityId", "ability"):
            if k in mon:
                abil_key = k
                break
        if abil_key:
            cur_abil = mon.get(abil_key)
            # Display name if possible
            abil_name_to_id, abil_id_to_name = load_ability_catalog()
            disp = abil_id_to_name.get(int(cur_abil), cur_abil) if isinstance(cur_abil, int) else cur_abil
            val = input(f"Ability (id or name) (current {disp}, blank=keep): ").strip()
            if val:
                if val.isdigit():
                    mon[abil_key] = int(val)
                else:
                    res = select_from_catalog("    Search ability: ", abil_name_to_id)
                    if res is not None:
                        mon[abil_key] = res
                    else:
                        print("    Kept current ability")
        # Nature (if present) allow name or id
        nat_key = None
        for k in ("natureId", "nature"):
            if k in mon:
                nat_key = k
                break
        if nat_key:
            cur_nat = mon.get(nat_key)
            nat_name_to_id, nat_id_to_name = load_nature_catalog()
            disp = nat_id_to_name.get(int(cur_nat), cur_nat) if isinstance(cur_nat, int) else cur_nat
            val = input(f"Nature (id or name) (current {disp}, blank=keep): ").strip()
            if val:
                if val.isdigit():
                    mon[nat_key] = int(val)
                else:
                    res = select_from_catalog("    Search nature: ", nat_name_to_id)
                    if res is not None:
                        mon[nat_key] = res
                    else:
                        print("    Kept current nature")

    def analyze_run_conditions(self, slot: int) -> None:
        data = self.api.get_slot(slot)
        # Weather
        w = None
        for k in ("weather", "weatherType", "currentWeather"):
            if k in data:
                w = data.get(k)
                break
        if w is None:
            print("Weather: not found")
        else:
            _, wid2n = load_weather_catalog()
            label = wid2n.get(int(w), w) if isinstance(w, int) else w
            print(f"Weather: {label}")
        # Modifiers
        mods = None
        for k in ("modifiers", "activeModifiers"):
            if k in data and isinstance(data[k], list):
                mods = data[k]
                break
        if mods is None:
            print("Modifiers: not found")
        else:
            _, mid2n = load_modifier_catalog()
            print("Modifiers:")
            for m in mods:
                if isinstance(m, dict):
                    mid = m.get("id") or m.get("type") or m.get("modifierId")
                else:
                    mid = m
                name = mid2n.get(int(mid), mid) if isinstance(mid, int) else mid
                print(f"  - {name}")

    def edit_run_weather(self, slot: int) -> None:
        data = self.api.get_slot(slot)
        wkey = None
        for k in ("weather", "weatherType", "currentWeather"):
            if k in data:
                wkey = k
                break
        if not wkey:
            print("Weather field not found in session.")
            return
        n2i, i2n = load_weather_catalog()
        cur = data.get(wkey)
        disp = i2n.get(int(cur), cur) if isinstance(cur, int) else cur
        val = input(f"Weather (id or name) (current {disp}, blank=keep): ").strip()
        if not val:
            print("No change.")
            return
        try:
            data[wkey] = int(val)
        except ValueError:
            key = val.lower().replace(" ", "_")
            if key in n2i:
                data[wkey] = n2i[key]
            else:
                print("Invalid weather.")
                return
        save_path = slot_save_path(self.api.username, slot)
        dump_json(save_path, data)
        print(f"Wrote edited slot to {save_path}")
        if input("Upload changes to server? (y/N): ").strip().lower() in ("y", "yes"):
            try:
                # Ensure uploaded payload matches saved file exactly
                payload = load_json(save_path)
                self.api.update_slot(slot, payload)
                print("Server updated.")
            except Exception as e:
                print(f"[WARN] Failed to update server: {e}")

    # --- Modifiers / Items on Pokemon ---
    def list_modifiers(self, slot: int) -> None:
        data = self.api.get_slot(slot)
        mods = data.get("modifiers") or []
        party = {p.get("id"): p for p in (data.get("party") or []) if isinstance(p, dict) and "id" in p}
        inv = invert_dex_map(load_pokemon_index())
        print("Modifiers:")
        for m in mods:
            if not isinstance(m, dict):
                continue
            tid = m.get("typeId")
            player = m.get("player")
            args = m.get("args") or []
            target = None
            if args and isinstance(args, list) and isinstance(args[0], int) and args[0] in party:
                mon = party[args[0]]
                did = str(mon.get("species") or mon.get("dexId") or mon.get("speciesId") or "?")
                target = f" -> {inv.get(did, did)} (id {args[0]})"
            print(f" - {tid} (player={player}, args={args}){target or ''}")

    def list_modifiers_detailed(self, slot: int) -> list[tuple[int, dict]]:
        data = self.api.get_slot(slot)
        mods = data.get("modifiers") or []
        detailed = []
        for i, m in enumerate(mods):
            if isinstance(m, dict):
                detailed.append((i, m))
        return detailed

    def group_modifiers(self, slot: int) -> tuple[list[tuple[int, dict]], dict[int, list[tuple[int, dict]]]]:
        detailed = self.list_modifiers_detailed(slot)
        party_map: dict[int, list[tuple[int, dict]]] = {}
        player_mods: list[tuple[int, dict]] = []
        for idx, m in detailed:
            args = m.get("args") or []
            if args and isinstance(args, list) and len(args) > 0 and isinstance(args[0], int):
                target_id = args[0]
                party_map.setdefault(target_id, []).append((idx, m))
            else:
                player_mods.append((idx, m))
        return player_mods, party_map

    def add_player_modifier(self, slot: int, type_id: str, args: list[int] | None = None, stack: int = 1) -> None:
        data = self.api.get_slot(slot)
        mods = data.setdefault("modifiers", [])
        entry = {
            "args": args or None,
            "className": None,
            "player": True,
            "stackCount": int(stack),
            "typeId": type_id.upper(),
        }
        mods.append(entry)
        save_path = slot_save_path(self.api.username, slot)
        dump_json(save_path, data)

    def remove_modifier_by_index(self, slot: int, mod_index: int) -> bool:
        data = self.api.get_slot(slot)
        mods = data.get("modifiers") or []
        if 0 <= mod_index < len(mods):
            del mods[mod_index]
            data["modifiers"] = mods
            save_path = slot_save_path(self.api.username, slot)
            dump_json(save_path, data)
            return True
        return False

    def add_item_to_mon(self, slot: int, team_index: int, item_type: str) -> None:
        data = self.api.get_slot(slot)
        party = data.get("party") or []
        try:
            mon = party[team_index - 1]
        except Exception:
            print("Invalid team index")
            return
        mon_id = mon.get("id")
        if not isinstance(mon_id, int):
            print("Selected mon has no id; cannot attach item.")
            return
        mods = data.setdefault("modifiers", [])
        # Known simple templates; extend as needed
        t_upper = item_type.upper()
        entry = None
        if t_upper == "BERRY":
            from .catalog import load_berry_catalog
            berry_name_to_id, berry_id_to_name = load_berry_catalog()
            val = input("Berry (name or id): ").strip()
            if not val:
                print("No berry specified.")
                return
            try:
                berry_id = int(val)
            except ValueError:
                key = val.lower().replace(" ", "_")
                if key in berry_name_to_id:
                    berry_id = berry_name_to_id[key]
                else:
                    print("Unknown berry.")
                    return
            entry = {
                "args": [mon_id, berry_id],
                "player": True,
                "stackCount": 1,
                "typeId": t_upper,
                "typePregenArgs": [berry_id],
            }
        else:
            # Generic patterns
            accuracy_items = {"WIDE_LENS", "MULTI_LENS"}
            one_arg_items = {
                "FOCUS_BAND", "MYSTICAL_ROCK", "SOOTHE_BELL", "SCOPE_LENS", "LEEK", "EVIOLITE",
                "SOUL_DEW", "GOLDEN_PUNCH", "GRIP_CLAW", "QUICK_CLAW", "KINGS_ROCK", "LEFTOVERS",
                "SHELL_BELL", "TOXIC_ORB", "FLAME_ORB", "BATON"
            }
            if t_upper in accuracy_items:
                try:
                    boost = int(input("Accuracy boost amount (default 5): ").strip() or "5")
                except ValueError:
                    boost = 5
                entry = {
                    "args": [mon_id, boost],
                    "player": True,
                    "stackCount": 1,
                    "typeId": t_upper,
                }
            elif t_upper == "BASE_STAT_BOOSTER":
                from .catalog import load_stat_catalog
                stat_name_to_id, _ = load_stat_catalog()
                stat_in = input("Stat (id or name; e.g., attack/defense/sp_attack...): ").strip()
                if not stat_in:
                    print("No stat provided.")
                    return
                try:
                    stat_id = int(stat_in)
                except ValueError:
                    key = stat_in.lower().replace(" ", "_")
                    if key in stat_name_to_id:
                        stat_id = stat_name_to_id[key]
                    else:
                        print("Unknown stat.")
                        return
                entry = {
                    "args": [mon_id, stat_id],
                    "player": True,
                    "stackCount": 1,
                    "typeId": t_upper,
                    "typePregenArgs": [stat_id],
                }
            elif t_upper in one_arg_items:
                entry = {
                    "args": [mon_id],
                    "player": True,
                    "stackCount": 1,
                    "typeId": t_upper,
                }
            else:
                print("Unsupported item type for quick attach.")
                return
        mods.append(entry)
        save_path = slot_save_path(self.api.username, slot)
        dump_json(save_path, data)
        print(f"Attached {t_upper} to team slot {team_index}. Wrote {save_path}")
        if input("Upload changes to server? (y/N): ").strip().lower() in ("y", "yes"):
            try:
                payload = load_json(save_path)
                self.api.update_slot(slot, payload)
                print("Server updated.")
            except Exception as e:
                print(f"[WARN] Failed to update server: {e}")

    def remove_item_from_mon(self, slot: int, team_index: int, item_type: str) -> None:
        data = self.api.get_slot(slot)
        party = data.get("party") or []
        try:
            mon = party[team_index - 1]
        except Exception:
            print("Invalid team index")
            return
        mon_id = mon.get("id")
        mods = data.get("modifiers") or []
        before = len(mods)
        mods = [m for m in mods if not (isinstance(m, dict) and m.get("typeId") == item_type.upper() and (not (m.get("args") and isinstance(m.get("args"), list)) or m["args"][0] == mon_id))]
        removed = before - len(mods)
        data["modifiers"] = mods
        save_path = slot_save_path(self.api.username, slot)
        dump_json(save_path, data)
        print(f"Removed {removed} matching {item_type.upper()} from team slot {team_index}. Wrote {save_path}")
        if removed and input("Upload changes to server? (y/N): ").strip().lower() in ("y", "yes"):
            try:
                payload = load_json(save_path)
                self.api.update_slot(slot, payload)
                print("Server updated.")
            except Exception as e:
                print(f"[WARN] Failed to update server: {e}")
