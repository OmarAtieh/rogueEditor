from __future__ import annotations

import json
import os
import re
from typing import Dict, Tuple

from .utils import repo_path


DATA_MOVES_JSON = repo_path("data", "moves.json")
DATA_ABILITIES_JSON = repo_path("data", "abilities.json")
DATA_ABILITY_ATTR_JSON = repo_path("data", "ability_attr.json")
DATA_NATURES_JSON = repo_path("data", "natures.json")
DATA_NATURE_EFFECTS_JSON = repo_path("data", "nature_effects.json")
DATA_WEATHER_JSON = repo_path("data", "weather.json")
DATA_STATS_JSON = repo_path("data", "stats.json")
DATA_MODIFIERS_JSON = repo_path("data", "modifiers.json")
DATA_BERRIES_JSON = repo_path("data", "berries.json")
DATA_ITEMS_JSON = repo_path("data", "items.json")


def _parse_ts_enum(path: str) -> Dict[str, int]:
    # Parses a TS enum where identifiers increment implicitly or have explicit assignments
    enum: Dict[str, int] = {}
    if not os.path.exists(path):
        return enum
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    current = -1
    in_enum = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("export enum"):
            in_enum = True
            current = -1
            continue
        if not in_enum:
            continue
        if line.startswith("}"):
            break
        if not line or line.startswith("/**") or line.startswith("*"):
            continue
        # Remove trailing commas and comments
        line = re.sub(r"//.*$", "", line).strip()
        if not line:
            continue
        # Cases: NAME = 123, or NAME,
        m = re.match(r"([A-Z0-9_]+)\s*=\s*([0-9]+)", line)
        if m:
            name, val = m.group(1), int(m.group(2))
            enum[name] = val
            current = val
        else:
            m2 = re.match(r"([A-Z0-9_]+)\s*,?$", line)
            if m2:
                name = m2.group(1)
                current += 1
                enum[name] = current
    return enum


def load_move_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    # Prefer clean JSON in data dir
    if os.path.exists(DATA_MOVES_JSON):
        with open(DATA_MOVES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        nti = {k.lower(): int(v) for k, v in data.get("name_to_id", {}).items()}
        itn = {int(k): v for k, v in data.get("id_to_name", {}).items()}
        return nti, itn
    # Fallback to tmpServerFiles parse (for local development)
    ts_path = repo_path("..", "tmpServerFiles", "GameData", "move-id.ts")
    enum = _parse_ts_enum(ts_path)
    name_to_id = {k.lower(): v for k, v in enum.items()}
    id_to_name = {v: k for k, v in enum.items()}
    return name_to_id, id_to_name


def load_ability_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    if os.path.exists(DATA_ABILITIES_JSON):
        with open(DATA_ABILITIES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        nti = {k.lower(): int(v) for k, v in data.get("name_to_id", {}).items()}
        itn = {int(k): v for k, v in data.get("id_to_name", {}).items()}
        return nti, itn
    ts_path = repo_path("..", "tmpServerFiles", "GameData", "ability-id.ts")
    enum = _parse_ts_enum(ts_path)
    name_to_id = {k.lower(): v for k, v in enum.items()}
    id_to_name = {v: k for k, v in enum.items()}
    return name_to_id, id_to_name


def load_ability_attr_mask() -> Dict[str, int]:
    # ABILITY_1, ABILITY_2, ABILITY_HIDDEN
    if os.path.exists(DATA_ABILITY_ATTR_JSON):
        with open(DATA_ABILITY_ATTR_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k.lower(): int(v) for k, v in data.items()}
    ts_path = repo_path("..", "tmpServerFiles", "GameData", "ability-attr.ts")
    mask: Dict[str, int] = {}
    if not os.path.exists(ts_path):
        return mask
    with open(ts_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            m = re.match(r"ABILITY_([A-Z_]+):\s*([0-9]+)", raw)
            if m:
                mask[m.group(1).lower()] = int(m.group(2))
    return mask


def build_clean_catalogs_from_tmp() -> None:
    """One-time builder: parse tmpServerFiles TS enums and write JSON under Source/data.

    Outputs:
      - data/moves.json: { name_to_id, id_to_name }
      - data/abilities.json: { name_to_id, id_to_name }
      - data/ability_attr.json: { attr_name: value }
    """
    # Moves
    move_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "move-id.ts"))
    if move_enum:
        nti = {k.lower(): v for k, v in move_enum.items()}
        itn = {v: k for k, v in move_enum.items()}
        os.makedirs(os.path.dirname(DATA_MOVES_JSON), exist_ok=True)
        with open(DATA_MOVES_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Abilities
    abil_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "ability-id.ts"))
    if abil_enum:
        nti = {k.lower(): v for k, v in abil_enum.items()}
        itn = {v: k for k, v in abil_enum.items()}
        with open(DATA_ABILITIES_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Ability attr mask
    attr_path = repo_path("..", "tmpServerFiles", "GameData", "ability-attr.ts")
    mask: Dict[str, int] = {}
    if os.path.exists(attr_path):
        with open(attr_path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                m = re.match(r"ABILITY_([A-Z_]+):\s*([0-9]+)", raw)
                if m:
                    mask[m.group(1).lower()] = int(m.group(2))
        with open(DATA_ABILITY_ATTR_JSON, "w", encoding="utf-8") as f:
            json.dump(mask, f, ensure_ascii=False, indent=2)
    # Natures
    nature_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "nature.ts"))
    if nature_enum:
        nti = {k.lower(): v for k, v in nature_enum.items()}
        itn = {v: k for k, v in nature_enum.items()}
        with open(DATA_NATURES_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Weather types
    weather_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "weather-type.ts"))
    if weather_enum:
        nti = {k.lower(): v for k, v in weather_enum.items()}
        itn = {v: k for k, v in weather_enum.items()}
        with open(DATA_WEATHER_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Stats
    stats_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "stat.ts"))
    if stats_enum:
        nti = {k.lower(): v for k, v in stats_enum.items()}
        itn = {v: k for k, v in stats_enum.items()}
        with open(DATA_STATS_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Modifiers
    modifier_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "modifier-type.ts"))
    if modifier_enum:
        nti = {k.lower(): v for k, v in modifier_enum.items()}
        itn = {v: k for k, v in modifier_enum.items()}
        with open(DATA_MODIFIERS_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Berries
    berry_enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", "berry-type.ts"))
    if berry_enum:
        nti = {k.lower(): v for k, v in berry_enum.items()}
        itn = {v: k for k, v in berry_enum.items()}
        with open(DATA_BERRIES_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    # Items (if present)
    item_path = repo_path("..", "tmpServerFiles", "GameData", "item-id.ts")
    if os.path.exists(item_path):
        item_enum = _parse_ts_enum(item_path)
        if item_enum:
            nti = {k.lower(): v for k, v in item_enum.items()}
            itn = {v: k for k, v in item_enum.items()}
            with open(DATA_ITEMS_JSON, "w", encoding="utf-8") as f:
                json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)


def load_generic_catalog(json_path: str, tmp_rel: str) -> Tuple[Dict[str, int], Dict[int, str]]:
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nti = {k.lower(): int(v) for k, v in data.get("name_to_id", {}).items()}
        itn = {int(k): v for k, v in data.get("id_to_name", {}).items()}
        return nti, itn
    enum = _parse_ts_enum(repo_path("..", "tmpServerFiles", "GameData", tmp_rel))
    nti = {k.lower(): v for k, v in enum.items()}
    itn = {v: k for k, v in enum.items()}
    return nti, itn


def load_nature_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_NATURES_JSON, "nature.ts")


def load_weather_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_WEATHER_JSON, "weather-type.ts")


def load_stat_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_STATS_JSON, "stat.ts")


def load_modifier_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_MODIFIERS_JSON, "modifier-type.ts")


def load_berry_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_BERRIES_JSON, "berry-type.ts")


def load_item_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    return load_generic_catalog(DATA_ITEMS_JSON, "item-id.ts")


# --- Nature effects (multipliers) ---
_STAT_INDEX = {
    "attack": 1,
    "defense": 2,
    "sp_attack": 3,
    "sp_defense": 4,
    "speed": 5,
}


def _default_nature_effects() -> Dict[str, Dict[str, str]]:
    # name -> {up, down}; neutral natures have same up/down
    return {
        # Neutral
        "hardy": {"up": "attack", "down": "attack"},
        "docile": {"up": "defense", "down": "defense"},
        "serious": {"up": "speed", "down": "speed"},
        "bashful": {"up": "sp_attack", "down": "sp_attack"},
        "quirky": {"up": "sp_defense", "down": "sp_defense"},
        # Attack+
        "lonely": {"up": "attack", "down": "defense"},
        "brave": {"up": "attack", "down": "speed"},
        "adamant": {"up": "attack", "down": "sp_attack"},
        "naughty": {"up": "attack", "down": "sp_defense"},
        # Defense+
        "bold": {"up": "defense", "down": "attack"},
        "relaxed": {"up": "defense", "down": "speed"},
        "impish": {"up": "defense", "down": "sp_attack"},
        "lax": {"up": "defense", "down": "sp_defense"},
        # Speed+
        "timid": {"up": "speed", "down": "attack"},
        "hasty": {"up": "speed", "down": "defense"},
        "jolly": {"up": "speed", "down": "sp_attack"},
        "naive": {"up": "speed", "down": "sp_defense"},
        # Sp. Atk+
        "modest": {"up": "sp_attack", "down": "attack"},
        "mild": {"up": "sp_attack", "down": "defense"},
        "quiet": {"up": "sp_attack", "down": "speed"},
        "rash": {"up": "sp_attack", "down": "sp_defense"},
        # Sp. Def+
        "calm": {"up": "sp_defense", "down": "attack"},
        "gentle": {"up": "sp_defense", "down": "defense"},
        "sassy": {"up": "sp_defense", "down": "speed"},
        "careful": {"up": "sp_defense", "down": "sp_attack"},
    }


def load_nature_effects() -> Dict[str, Dict[str, str]]:
    # Returns mapping of nature name (lowercase, underscores) -> {up, down}
    if os.path.exists(DATA_NATURE_EFFECTS_JSON):
        with open(DATA_NATURE_EFFECTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        # normalize keys
        out: Dict[str, Dict[str, str]] = {}
        for name, eff in data.items():
            key = name.strip().lower().replace(" ", "_")
            up = str(eff.get("up", "")).strip().lower().replace(" ", "_")
            down = str(eff.get("down", "")).strip().lower().replace(" ", "_")
            if up and down:
                out[key] = {"up": up, "down": down}
        if out:
            return out
    return _default_nature_effects()


def nature_multipliers_by_id() -> Dict[int, list[float]]:
    name_to_id, id_to_name = load_nature_catalog()
    eff = load_nature_effects()
    mults: Dict[int, list[float]] = {}
    for nid, name in id_to_name.items():
        key = name.strip().lower().replace(" ", "_")
        e = eff.get(key)
        arr = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        if e:
            up = _STAT_INDEX.get(e.get("up", ""))
            down = _STAT_INDEX.get(e.get("down", ""))
            if isinstance(up, int) and isinstance(down, int):
                if up == down:
                    pass
                else:
                    arr[up] = 1.1
                    arr[down] = 0.9
        mults[int(nid)] = arr
    return mults
