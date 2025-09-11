from __future__ import annotations

import json
import os
from typing import Optional, Any
import secrets
import base64
from collections.abc import Mapping
import difflib


def repo_path(*parts: str) -> str:
    base = os.path.dirname(os.path.dirname(__file__))  # Source/
    return os.path.join(base, *parts)


def load_test_credentials(env_path: str = ".env/env_data.txt") -> Optional[tuple[str, str]]:
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            user = pwd = None
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = (part.strip() for part in line.split("=", 1))
                if key == "test.user":
                    user = value
                elif key == "test.password":
                    pwd = value
        if user and pwd:
            return user, pwd
    except FileNotFoundError:
        pass
    return None


def load_client_session_id(env_path: str = ".env/env_data.txt") -> Optional[str]:
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = (part.strip() for part in line.split("=", 1))
                if key in ("clientSessionId", "client.session.id"):
                    return value
    except FileNotFoundError:
        pass
    return None


def save_client_session_id(csid: str, env_path: str = ".env/env_data.txt") -> None:
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    lines: list[str] = []
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    wrote = False
    new_lines: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if line.strip().startswith("clientSessionId") or line.strip().startswith("client.session.id"):
            new_lines.append(f"clientSessionId = {csid}")
            wrote = True
        else:
            new_lines.append(line)
    if not wrote:
        new_lines.append(f"clientSessionId = {csid}")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


def generate_client_session_id() -> str:
    # 24 bytes -> 32 chars base64 url-safe without padding
    raw = secrets.token_bytes(24)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def validate_slot(slot: int) -> int:
    if not isinstance(slot, int):
        raise ValueError("Slot must be an integer between 1 and 5")
    if slot < 1 or slot > 5:
        raise ValueError("Slot must be between 1 and 5")
    return slot


def dump_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_pokemon_index() -> dict:
    # Prefer Source/data/pokemon.json; fallback to ./data/pokemon.json
    candidates = [
        repo_path("data", "pokemon.json"),
        os.path.join("data", "pokemon.json"),
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("pokemon.json not found in Source/data or ./data")


def sanitize_username(username: str) -> str:
    return "".join(ch for ch in username if ch.isalnum() or ch in ("_", "-")) or "user"


def user_save_dir(username: str) -> str:
    return repo_path("saves", sanitize_username(username))


def trainer_save_path(username: str) -> str:
    return os.path.join(user_save_dir(username), "trainer.json")


def slot_save_path(username: str, slot: int) -> str:
    return os.path.join(user_save_dir(username), f"slot {slot}.json")


# Per-user config (stores clientSessionId, etc.)
USERS_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env", "users.json")


def load_users_config() -> dict:
    try:
        with open(USERS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_users_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(USERS_CONFIG_PATH), exist_ok=True)
    with open(USERS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_user_csid(username: str) -> Optional[str]:
    cfg = load_users_config()
    u = sanitize_username(username)
    return (cfg.get("users", {}).get(u) or {}).get("clientSessionId")


def set_user_csid(username: str, csid: str) -> None:
    cfg = load_users_config()
    u = sanitize_username(username)
    cfg.setdefault("users", {})
    cfg["users"].setdefault(u, {})
    cfg["users"][u]["clientSessionId"] = csid
    save_users_config(cfg)


def get_user_last_session_update(username: str) -> Optional[str]:
    cfg = load_users_config()
    u = sanitize_username(username)
    return (cfg.get("users", {}).get(u) or {}).get("lastSessionUpdate")


def set_user_last_session_update(username: str, when_str: str) -> None:
    cfg = load_users_config()
    u = sanitize_username(username)
    cfg.setdefault("users", {})
    cfg["users"].setdefault(u, {})
    cfg["users"][u]["lastSessionUpdate"] = when_str
    save_users_config(cfg)


def list_usernames() -> list[str]:
    cfg = load_users_config()
    return sorted((cfg.get("users") or {}).keys())


def invert_dex_map(index: dict) -> dict:
    dex = index.get("dex", {}) if isinstance(index, dict) else {}
    inv = {}
    for name, did in dex.items():
        inv[str(did)] = name
    return inv


def find_team_candidates(obj: Any, path: list[str] | None = None) -> list[tuple[list[str], list]]:
    """Recursively find plausible team arrays within a nested dict structure.

    Heuristics: list of 1-6 dicts, each having species/dex keys and optionally level.
    Returns a list of (path, list) where path is a list of dict keys leading to the list.
    """
    path = path or []
    found: list[tuple[list[str], list]] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if isinstance(v, list) and 1 <= len(v) <= 6 and all(isinstance(e, Mapping) for e in v):
                keys = {kk for e in v for kk in e.keys()}
                species_keys = {"species", "speciesId", "dexId", "pokemonId"}
                if keys & species_keys:
                    found.append((path + [str(k)], v))
            elif isinstance(v, Mapping):
                found.extend(find_team_candidates(v, path + [str(k)]))
    return found


def get_by_path(data: Any, path: list[str]) -> Any:
    cur = data
    for p in path:
        if isinstance(cur, Mapping):
            cur = cur.get(p)
        else:
            return None
    return cur


def set_by_path(data: Any, path: list[str], value: Any) -> bool:
    if not path:
        return False
    cur = data
    for p in path[:-1]:
        if isinstance(cur, Mapping):
            cur = cur.get(p)
        else:
            return False
    if isinstance(cur, Mapping):
        cur[path[-1]] = value
        return True
    return False


def normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def suggest_from_catalog(query: str, name_to_id: dict[str, int], limit: int = 10) -> list[str]:
    key = normalize_name(query)
    names = list(name_to_id.keys())
    # Substring matches first
    subs = [n for n in names if key in n]
    # Add close matches next
    close = difflib.get_close_matches(key, names, n=limit, cutoff=0.6)
    merged = []
    for n in subs + close:
        if n not in merged:
            merged.append(n)
        if len(merged) >= limit:
            break
    return merged


def select_from_catalog(prompt: str, name_to_id: dict[str, int]) -> int | None:
    """Interactive selector: accepts id, or shows suggestions for partial names.

    - Enter numeric id to accept directly
    - Enter name (partial) to get a suggestion list to pick by number
    - Enter blank to cancel (returns None)
    """
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        if raw.isdigit():
            return int(raw)
        key = normalize_name(raw)
        if key in name_to_id:
            return name_to_id[key]
        suggestions = suggest_from_catalog(raw, name_to_id, limit=10)
        if not suggestions:
            print("No matches; try again or enter id.")
            continue
        print("Matches:")
        for i, n in enumerate(suggestions, start=1):
            print(f"  {i}. {n}")
        sel = input("Pick # (or blank to refine): ").strip()
        if not sel:
            continue
        try:
            idx = int(sel)
            if 1 <= idx <= len(suggestions):
                return name_to_id[suggestions[idx-1]]
        except ValueError:
            pass
        print("Invalid selection; try again.")
