from __future__ import annotations

import json
import os
from typing import Optional, Dict, Any

_BASE_CACHE: Optional[Dict[str, Any]] = None
_NAME_INDEX: Optional[Dict[str, list[int]]] = None

from .utils import repo_path


DATA_BASE_STATS_JSON = repo_path("data", "base_stats.json")


def load_base_stats_catalog() -> Dict[str, Any]:
    """Load base stats catalog built from the spreadsheet.

    Returns the JSON dict with keys:
      - by_dex: { dex_str: { name, stats [HP,Atk,Def,SpA,SpD,Spe], total, source } }
      - source: metadata
    """
    global _BASE_CACHE
    if _BASE_CACHE is not None:
        return _BASE_CACHE
    if not os.path.exists(DATA_BASE_STATS_JSON):
        _BASE_CACHE = {"by_dex": {}, "source": {}}
        return _BASE_CACHE
    with open(DATA_BASE_STATS_JSON, "r", encoding="utf-8") as f:
        _BASE_CACHE = json.load(f)
    return _BASE_CACHE


def get_base_stats_by_species_id(dex_id: int) -> Optional[list[int]]:
    data = load_base_stats_catalog()
    by_dex = data.get("by_dex") or {}
    entry = by_dex.get(str(int(dex_id)))
    if not entry:
        return None
    stats = entry.get("stats")
    if isinstance(stats, list) and len(stats) == 6:
        return [int(x) for x in stats]
    return None


def _norm_name(s: str) -> str:
    s = s.strip().lower()
    for ch in [" ", "-", ".", "'", ":"]:
        s = s.replace(ch, "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s


def get_base_stats_by_name(name: str) -> Optional[list[int]]:
    """Lookup base stats by species name (case/spacing tolerant).

    This provides a secondary path if dex id matching fails. It builds an
    index of normalized species names -> stats on first use.
    """
    global _NAME_INDEX
    data = load_base_stats_catalog()
    by_dex = data.get("by_dex") or {}
    if _NAME_INDEX is None:
        idx: Dict[str, list[int]] = {}
        for _dex, entry in by_dex.items():
            try:
                nm = str(entry.get("name") or "")
                stats = entry.get("stats")
                if isinstance(stats, list) and len(stats) == 6 and nm:
                    idx[_norm_name(nm)] = [int(x) for x in stats]
            except Exception:
                continue
        _NAME_INDEX = idx
    key = _norm_name(str(name or ""))
    if key and _NAME_INDEX and key in _NAME_INDEX:
        return list(_NAME_INDEX[key])
    return None
