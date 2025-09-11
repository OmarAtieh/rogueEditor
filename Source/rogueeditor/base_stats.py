from __future__ import annotations

import json
import os
from typing import Optional, Dict, Any

from .utils import repo_path


DATA_BASE_STATS_JSON = repo_path("data", "base_stats.json")


def load_base_stats_catalog() -> Dict[str, Any]:
    """Load base stats catalog built from the spreadsheet.

    Returns the JSON dict with keys:
      - by_dex: { dex_str: { name, stats [HP,Atk,Def,SpA,SpD,Spe], total, source } }
      - source: metadata
    """
    if not os.path.exists(DATA_BASE_STATS_JSON):
        return {"by_dex": {}, "source": {}}
    with open(DATA_BASE_STATS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


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

