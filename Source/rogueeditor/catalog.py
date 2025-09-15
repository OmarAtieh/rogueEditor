from __future__ import annotations

import json
import os
import re
from typing import Dict, Tuple
import csv

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
DATA_POKEBALLS_JSON = repo_path("data", "pokeballs.json")
DATA_TYPES_JSON = repo_path("data", "types.json")
DATA_TYPE_MATRIX_JSON = repo_path("data", "type_matrix.json")
DATA_EXP_TABLES_JSON = repo_path("data", "exp_tables.json")
DATA_POKEMON_TYPES_JSON = repo_path("data", "pokemon_types.json")
DATA_GROWTH_MAP_JSON = repo_path("data", "growth_map.json")
DATA_POKEMON_CATALOG_JSON = repo_path("data", "pokemon_catalog.json")
DATA_TYPE_COLORS_JSON = repo_path("data", "type_colors.json")


def _parse_ts_enum(path: str) -> Dict[str, int]:
    # Parses a TS enum where identifiers increment implicitly or have explicit assignments
    # Skips line (//) and block (/* ... */) comments robustly.
    enum: Dict[str, int] = {}
    if not os.path.exists(path):
        return enum
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    current = -1
    in_enum = False
    in_block_comment = False
    for raw in lines:
        line = raw
        # Handle multi-line block comments
        if in_block_comment:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        # Strip inline /* ... */ comments (possibly multiple per line)
        while "/*" in line:
            pre, rest = line.split("/*", 1)
            if "*/" in rest:
                rest = rest.split("*/", 1)[1]
                line = pre + rest
                # Continue in case of multiple comment sections
                continue
            else:
                # Starts a block comment; discard rest of line and mark state
                line = pre
                in_block_comment = True
                break
        if in_block_comment:
            continue
        line = line.strip()
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
        # Remove trailing // comments
        line = re.sub(r"//.*$", "", line).strip()
        if not line:
            continue
        # Cases: NAME = 123, or NAME,
        m = re.match(r"^([A-Z0-9_]+)\s*=\s*([0-9]+)\s*,?\s*$", line)
        if m:
            name, val = m.group(1), int(m.group(2))
            enum[name] = val
            current = val
            continue
        m2 = re.match(r"^([A-Z0-9_]+)\s*,?\s*$", line)
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
    # Helper to choose GameData path across versions (/, /1, /2)
    def _gd_path(*rel):
        base = repo_path("..", "tmpServerFiles", "GameData")
        # Prefer unversioned, then v1, then v2
        candidates = [
            os.path.join(base, *rel),
            os.path.join(base, "1", *rel),
            os.path.join(base, "2", *rel),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        # Fallback to the first for error context
        return candidates[0]

    # Moves
    move_enum = _parse_ts_enum(_gd_path("move-id.ts"))
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


# --- New catalogs from TmpServerFiles/GameData/2 ---

def _ts_path2(*parts: str) -> str:
    return repo_path("..", "TmpServerFiles", "GameData", "2", *parts)


def load_pokeball_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    # PokeballType enum (0-based)
    if os.path.exists(DATA_POKEBALLS_JSON):
        with open(DATA_POKEBALLS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        nti = {k.lower(): int(v) for k, v in data.get("name_to_id", {}).items()}
        itn = {int(k): v for k, v in data.get("id_to_name", {}).items()}
        return nti, itn
    enum = _parse_ts_enum(_ts_path2("pokeball.ts"))
    nti = {k.lower(): v for k, v in enum.items()}
    itn = {v: k for k, v in enum.items()}
    if nti:
        os.makedirs(os.path.dirname(DATA_POKEBALLS_JSON), exist_ok=True)
        with open(DATA_POKEBALLS_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    return nti, itn


def load_types_catalog() -> Tuple[Dict[str, int], Dict[int, str]]:
    # PokemonType enum
    if os.path.exists(DATA_TYPES_JSON):
        with open(DATA_TYPES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        nti = {k.lower(): int(v) for k, v in data.get("name_to_id", {}).items()}
        itn = {int(k): v for k, v in data.get("id_to_name", {}).items()}
        return nti, itn
    enum = _parse_ts_enum(_ts_path2("pokemon-type.ts"))
    nti = {k.lower(): v for k, v in enum.items()}
    itn = {v: k for k, v in enum.items()}
    if nti:
        with open(DATA_TYPES_JSON, "w", encoding="utf-8") as f:
            json.dump({"name_to_id": nti, "id_to_name": {str(k): v for k, v in itn.items()}}, f, ensure_ascii=False, indent=2)
    return nti, itn


def _parse_type_matrix_from_ts(ts_path: str) -> Dict[str, Dict[str, float]]:
    """Parse getTypeDamageMultiplier from GameData/2/type.ts robustly.

    We expect a structure like:
      switch (defType) {
        case PokemonType.NORMAL:
          switch (attackType) {
            case PokemonType.FIGHTING:
              return 2;
            case PokemonType.GHOST:
              return 0;
            default:
              return 1;
          }
        ...
      }
    We capture grouped 'case' fallthroughs by accumulating attacker cases until a 'return X;' line.
    """
    if not os.path.exists(ts_path):
        return {}
    # Ensure type names map
    _, type_id_to_name = load_types_catalog()
    type_names = [v.lower() for v in type_id_to_name.values()]
    with open(ts_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    import re
    matrix: Dict[str, Dict[str, float]] = {}
    # Find outer defType switch cases
    outer = re.search(r"switch\s*\(defType\)\s*\{(.*)\}\s*$", txt, re.S | re.M)
    scope = outer.group(1) if outer else txt
    for m in re.finditer(r"case\s+PokemonType\.([A-Z_]+)\s*:\s*(.*?)\n\s*break\s*;", scope, re.S):
        def_name = m.group(1).lower()
        body = m.group(2)
        # Locate inner attackType switch block
        inner = re.search(r"switch\s*\(attackType\)\s*\{(.*?)\}\s*", body, re.S)
        row: Dict[str, float] = {name: 1.0 for name in type_names}
        if inner:
            block = inner.group(1)
            # Iterate lines, accumulate cases until a return
            pending: list[str] = []
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                mc = re.match(r"case\s+PokemonType\.([A-Z_]+)\s*:\s*$", line)
                if mc:
                    pending.append(mc.group(1).lower())
                    continue
                mr = re.match(r"return\s*([0-9\.]+)\s*;", line)
                if mr and pending:
                    val = float(mr.group(1))
                    for att in pending:
                        row[att] = val
                    pending = []
                # ignore default and other tokens
        matrix[def_name] = row
    return matrix


def _norm_type_name(s: str) -> str:
    return str(s or "").strip().lower().replace(" ", "_").replace("-", "_")


def _parse_type_matrix_from_csv(csv_path: str) -> Dict[str, Dict[str, float]]:
    """Parse a CSV chart of defensive effectiveness.

    Expected layout (defense types by row, attack types by column):
      , Normal, Fire, Water, ...
      Normal, 1, 1, 1, ...
      Fire, 1, 0.5, 0.5, ...

    The parser attempts to detect orientation and normalizes type names to lowercase tokens
    matching the enum in pokemon-type.ts (via load_types_catalog()).
    """
    if not os.path.exists(csv_path):
        return {}
    # Known enum names + 3-letter abbrev mapping
    _, id_to_name = load_types_catalog()
    known_list = [str(v).strip().lower() for v in id_to_name.values()]
    known = set(known_list)
    abbrev = {k[:3]: k for k in known_list}

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        return {}

    # Normalize headers
    header = rows[0]
    head_cells = [c.strip() for c in header]
    # Default: columns are defense types, rows are attack types
    def_raw = [c.strip().lower() for c in head_cells[1:] if c]
    att_raw = [r[0].strip().lower() for r in rows[1:] if r]
    def_norm = [d if d in known else abbrev.get(d, d) for d in def_raw]
    att_norm = [a if a in known else abbrev.get(a, a) for a in att_raw]
    def_ok = all(d in known for d in def_norm) and len(def_norm) > 0
    att_ok = all(a in known for a in att_norm) and len(att_norm) > 0

    if not (def_ok and att_ok):
        # Try flipped: columns attackers, rows defenders
        att_raw2 = def_raw
        def_raw2 = att_raw
        att_norm = [a if a in known else abbrev.get(a, a) for a in att_raw2]
        def_norm = [d if d in known else abbrev.get(d, d) for d in def_raw2]
        if not (all(a in known for a in att_norm) and all(d in known for d in def_norm)):
            return {}
        # Build transposed
        matrix: Dict[str, Dict[str, float]] = {d: {a: 1.0 for a in att_norm} for d in def_norm}
        for ri, r in enumerate(rows[1:], start=1):
            if not r:
                continue
            d = def_norm[ri-1] if ri-1 < len(def_norm) else None
            if not d:
                continue
            for ci, a in enumerate(att_norm, start=1):
                try:
                    val = float(str(r[ci]).strip())
                except Exception:
                    val = 1.0
                matrix[d][a] = val
        return matrix

    # Build matrix with defaults of 1.0 (columns=defense, rows=attack)
    matrix: Dict[str, Dict[str, float]] = {d: {a: 1.0 for a in att_norm} for d in def_norm}
    for ri, r in enumerate(rows[1:], start=1):
        if not r:
            continue
        a = att_norm[ri-1] if ri-1 < len(att_norm) else None
        if not a:
            continue
        for ci, d in enumerate(def_norm, start=1):
            try:
                val = float(str(r[ci]).strip())
            except Exception:
                val = 1.0
            matrix[d][a] = val
    return matrix


def load_type_matchup_matrix() -> Dict[str, Dict[str, float]]:
    # Prefer definitive CSV source when present
    csv_path = _ts_path2("PokemonTypeMatchupChart.csv")
    if os.path.exists(csv_path):
        mat = _parse_type_matrix_from_csv(csv_path)
        if mat:
            try:
                with open(DATA_TYPE_MATRIX_JSON, "w", encoding="utf-8") as f:
                    json.dump(mat, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return mat
    # Fallback to cached JSON
    if os.path.exists(DATA_TYPE_MATRIX_JSON):
        try:
            with open(DATA_TYPE_MATRIX_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Last resort: parse TS
    mat = _parse_type_matrix_from_ts(_ts_path2("type.ts"))
    if mat:
        try:
            with open(DATA_TYPE_MATRIX_JSON, "w", encoding="utf-8") as f:
                json.dump(mat, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return mat


def load_exp_tables() -> Dict[str, object]:
    # Returns { growth_names: [...], tables: [[...]*levels] }
    if os.path.exists(DATA_EXP_TABLES_JSON):
        with open(DATA_EXP_TABLES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    path = _ts_path2("exp.ts")
    if not os.path.exists(path):
        return {"growth_names": [], "tables": []}
    import re
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    # Parse GrowthRate enum order
    names = []
    enum_m = re.search(r"export\s+enum\s+GrowthRate\s*\{([^}]+)\}", txt, re.S)
    if enum_m:
        for line in enum_m.group(1).splitlines():
            line = line.strip().strip(',')
            if not line:
                continue
            name = line.split('=')[0].strip()
            if name:
                names.append(name)
    # Parse expLevels arrays
    tables: list[list[int]] = []
    arr_m = re.search(r"const\s+expLevels\s*=\s*\[(.*?)]\s*;\s*\n\nexport", txt, re.S)
    if arr_m:
        arr_txt = arr_m.group(1)
        sub_arrays = re.findall(r"\[(.*?)\]", arr_txt, re.S)
        for sa in sub_arrays:
            nums = []
            for n in re.findall(r"-?\d+", sa):
                try:
                    nums.append(int(n))
                except Exception:
                    pass
            if nums:
                tables.append(nums)
    data = {"growth_names": names, "tables": tables}
    with open(DATA_EXP_TABLES_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def exp_for_level(growth_index: int, level: int) -> int:
    """Return cumulative EXP required for a given level.

    Behavior:
    - For levels within the parsed table, return the exact breakpoint.
    - For levels above the table (e.g., >100), assume each subsequent level requires
      the same EXP delta as the last known step (L_max - (L_max-1)).
      This is an explicit assumption until official curves beyond 100 are provided.
    """
    data = load_exp_tables()
    tables = data.get("tables") or []
    try:
        if level < 1:
            level = 1
        if 0 <= growth_index < len(tables):
            tbl = tables[growth_index]
            n = len(tbl)
            if n == 0:
                return 0
            if level <= n:
                return int(tbl[level - 1])
            # beyond table: extend linearly by last delta
            if n >= 2:
                delta = int(tbl[-1]) - int(tbl[-2])
            else:
                delta = int(tbl[-1])
            extra_levels = level - n
            return int(tbl[-1]) + max(0, extra_levels) * max(0, delta)
    except Exception:
        pass
    return 0


def level_from_exp(growth_index: int, exp: int) -> int:
    """Return the floored level for a given cumulative EXP.

    - For EXP within the table, find last breakpoint <= EXP.
    - For EXP beyond the last table entry, extend using the last delta per level.
    """
    data = load_exp_tables()
    tables = data.get("tables") or []
    try:
        if exp < 0:
            exp = 0
        if 0 <= growth_index < len(tables):
            tbl = tables[growth_index]
            n = len(tbl)
            if n == 0:
                return 1
            # within table
            lvl = 1
            for i, bp in enumerate(tbl, start=1):
                if exp >= bp:
                    lvl = i
                else:
                    break
            if exp <= tbl[-1]:
                return int(lvl)
            # beyond table: linear extension by last delta
            if n >= 2:
                delta = int(tbl[-1]) - int(tbl[-2])
            else:
                delta = int(tbl[-1])
            if delta <= 0:
                return int(n)
            extra = exp - int(tbl[-1])
            add_levels = extra // delta
            return int(n + add_levels)
    except Exception:
        pass
    return 1


def load_growth_group_map() -> Dict[int, int]:
    """Map dex id (int) -> growth index (int) using the CSV provided.

    Source CSV: TmpServerFiles/GameData/2/ListOfPokémonByExperienceType.csv
    Expected columns: '#', 'Pokémon', 'Experience type'

    Normalization:
    - CSV names like 'Medium Slow'/'Medium Fast'/'Fast'/'Slow'/'Fluctuating'/'Erratic'
      are normalized to enum tokens 'MEDIUM_SLOW', 'MEDIUM_FAST', 'FAST', 'SLOW', 'FLUCTUATING', 'ERRATIC'.
    - We then match against the exp.ts GrowthRate enum order parsed via load_exp_tables().
    """
    if os.path.exists(DATA_GROWTH_MAP_JSON):
        try:
            with open(DATA_GROWTH_MAP_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            # keys stored as str; convert to int
            return {int(k): int(v) for k, v in data.items()}
        except Exception:
            pass
    csv_path = _ts_path2("ListOfPokémonByExperienceType.csv")
    if not os.path.exists(csv_path):
        # Try ASCII fallback name without accent
        alt = _ts_path2("ListOfPokemonByExperienceType.csv")
        csv_path = alt if os.path.exists(alt) else csv_path
    if not os.path.exists(csv_path):
        return {}
    # Build mapping from normalized growth name to index using exp.ts enum order
    exp_tables = load_exp_tables()
    growth_names = [str(n).strip().upper() for n in (exp_tables.get("growth_names") or [])]
    name_to_index: Dict[str, int] = {growth_names[i]: i for i in range(len(growth_names))}
    # Also accept friendly names with spaces
    # Map common CSV names to enum tokens
    friendly_to_enum = {
        "FAST": "FAST",
        "SLOW": "SLOW",
        "MEDIUM SLOW": "MEDIUM_SLOW",
        "MEDIUM FAST": "MEDIUM_FAST",
        "FLUCTUATING": "FLUCTUATING",
        "ERRATIC": "ERRATIC",
    }
    result: Dict[int, int] = {}
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    dex = int(str(row.get('#') or row.get('dex') or row.get('id') or '').strip() or '0')
                except Exception:
                    continue
                raw_type = str(row.get('Experience type') or row.get('experience type') or '').strip()
                if not raw_type:
                    continue
                key = raw_type.upper()
                enum_name = friendly_to_enum.get(key) or key.replace(' ', '_')
                idx = name_to_index.get(enum_name)
                if isinstance(idx, int):
                    result[dex] = idx
    except Exception:
        return {}
    # Persist JSON cache
    try:
        os.makedirs(os.path.dirname(DATA_GROWTH_MAP_JSON), exist_ok=True)
        with open(DATA_GROWTH_MAP_JSON, "w", encoding="utf-8") as f:
            json.dump({str(k): int(v) for k, v in result.items()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


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


# --- Pokemon catalog + type colors ---
def load_pokemon_catalog() -> Dict[str, object]:
    if not os.path.exists(DATA_POKEMON_CATALOG_JSON):
        return {}
    with open(DATA_POKEMON_CATALOG_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def load_type_colors() -> Dict[str, str]:
    if os.path.exists(DATA_TYPE_COLORS_JSON):
        try:
            with open(DATA_TYPE_COLORS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    default = {
        "normal": "#A8A77A",
        "fire": "#EE8130",
        "water": "#6390F0",
        "electric": "#F7D02C",
        "grass": "#7AC74C",
        "ice": "#96D9D6",
        "fighting": "#C22E28",
        "poison": "#A33EA1",
        "ground": "#E2BF65",
        "flying": "#A98FF3",
        "psychic": "#F95587",
        "bug": "#A6B91A",
        "rock": "#B6A136",
        "ghost": "#735797",
        "dragon": "#6F35FC",
        "dark": "#705746",
        "steel": "#B7B7CE",
        "fairy": "#D685AD",
        "stellar": "#8899FF",
        "unknown": "#AAAAAA",
    }
    try:
        os.makedirs(os.path.dirname(DATA_TYPE_COLORS_JSON), exist_ok=True)
        with open(DATA_TYPE_COLORS_JSON, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return default
