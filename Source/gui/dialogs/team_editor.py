"""Team Editor dialog (modular, WIP).

Subsections on the right:
  - Basics: level, friendship, HP, nickname, held item, status, ability, passives
  - Stats: base + calculated stats, IVs, nature, item-boost indicators
  - Moves: four move pickers with labels
  - Save/Upload bar

Left side: target selector (Trainer/Party) and party list.

Notes:
  - Calculated stats use a simplified Pokemon formula without EVs.
  - Base Stat Booster effects are assumed +10% per stack for the boosted stat.
    This is a best-effort approximation and is marked in the UI.
"""

from __future__ import annotations

import math
import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, Future

from rogueeditor import PokerogueAPI

# Debug helper function
def debug_log(message: str, component: str = "TeamEditor"):
    """Print timestamped debug message."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
    print(f"[{timestamp}] [DEBUG] {component}: {message}")
from rogueeditor.editor import Editor
from rogueeditor.utils import (
    invert_dex_map,
    load_pokemon_index,
    slot_save_path,
    dump_json,
    load_json,
)
from rogueeditor.catalog import (
    load_move_catalog,
    build_move_label_catalog,
    get_move_label,
    get_move_type_name,
    get_move_entry,
    get_move_base_pp,
    compute_ppup_bounds,
    load_ability_catalog,
    load_nature_catalog,
    nature_multipliers_by_id,
    load_stat_catalog,
    load_growth_group_map,
    exp_for_level,
    level_from_exp,
    load_pokemon_catalog,
    load_type_matchup_matrix,
    load_type_colors,
    load_types_catalog,
    load_pokeball_catalog,
)
from rogueeditor.base_stats import get_base_stats_by_species_id
from gui.common.catalog_select import CatalogSelectDialog
from .item_manager import ItemManagerDialog


class BackgroundCacheManager:
    """Global background cache manager for preemptive data loading."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cache_warmer")
        self._cache_futures: Dict[str, Future] = {}
        self._cached_data: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_lock = threading.Lock()

        # Cache expiration time (15 minutes) - longer to reduce recomputation
        self.cache_ttl = 900

    def is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        with self._cache_lock:
            if cache_key not in self._cache_timestamps:
                return False
            return (time.time() - self._cache_timestamps[cache_key]) < self.cache_ttl

    def get_cached_data(self, cache_key: str) -> Optional[Any]:
        """Get cached data if available and valid."""
        with self._cache_lock:
            if cache_key in self._cached_data and self.is_cache_valid(cache_key):
                return self._cached_data[cache_key]
        return None

    def set_cached_data(self, cache_key: str, data: Any):
        """Store data in cache with timestamp."""
        with self._cache_lock:
            self._cached_data[cache_key] = data
            self._cache_timestamps[cache_key] = time.time()

    def warm_team_analysis_cache(self, api: PokerogueAPI, slot: int, username: str = None) -> Future:
        """Start background caching for team analysis data."""
        cache_key = f"team_analysis_{username}_{slot}"

        # Return existing future if already running
        if cache_key in self._cache_futures and not self._cache_futures[cache_key].done():
            return self._cache_futures[cache_key]

        # Check if we have valid cached data
        if self.is_cache_valid(cache_key):
            # Return a completed future with cached data
            future = Future()
            future.set_result(self.get_cached_data(cache_key))
            return future

        print(f"Starting background cache warming for slot {slot}")
        future = self._executor.submit(self._compute_team_analysis_background, api, slot, cache_key)
        self._cache_futures[cache_key] = future
        return future

    def _compute_team_analysis_background(self, api: PokerogueAPI, slot: int, cache_key: str) -> Dict[str, Any]:
        """Compute team analysis data in background thread."""
        try:
            print(f"Background thread: Computing team analysis for slot {slot}")
            start_time = time.time()

            # Get slot data
            slot_data = api.get_slot(slot)
            party = slot_data.get("party") or []

            if not party:
                return {"error": "No party data"}

            # Pre-load all catalogs (with caching)
            from rogueeditor.catalog import load_pokemon_catalog, load_type_colors, load_type_matchup_matrix
            pokemon_catalog = load_pokemon_catalog() or {}
            type_colors = load_type_colors() or {}
            base_matrix = load_type_matchup_matrix() or {}
            # Use attack_vs orientation for defensive checks: matrix[attacking][defending]
            type_matrix = base_matrix.get('attack_vs') if isinstance(base_matrix.get('attack_vs'), dict) else base_matrix

            # Compute type matchups for each party member (optimized)
            party_matchups = []
            for i, mon in enumerate(party):
                if not mon:
                    continue

                try:
                    species_id = str(mon.get("species", 0))
                    catalog_entry = pokemon_catalog.get("by_dex", {}).get(species_id, {})
                    types = catalog_entry.get("types", {}) or {}

                    # Compute defensive matchups (optimized)
                    matchup_data = self._compute_defensive_matchups_optimized(types, type_matrix)
                    party_matchups.append({
                        "index": i,
                        "species_id": species_id,
                        "species_name": catalog_entry.get("name", f"Species#{species_id}"),
                        "types": types,
                        "matchups": matchup_data
                    })
                except Exception as e:
                    print(f"Error processing Pokemon {i} in background cache: {e}")
                    # Add a fallback entry
                    party_matchups.append({
                        "index": i,
                        "species_id": str(mon.get("species", 0)),
                        "species_name": f"Species#{mon.get('species', 0)}",
                        "types": {},
                        "matchups": {"x4": [], "x2": [], "x1": [], "x0.5": [], "x0.25": [], "x0": []}
                    })

            # Compute team-wide analysis (manager-local implementations)
            team_defensive_analysis = self._compute_team_defensive_analysis_from_party_matchups(party_matchups)
            team_offensive_analysis = self._compute_team_offensive_analysis_from_party(party, pokemon_catalog, type_matrix)

            result = {
                "party_matchups": party_matchups,
                "team_defensive": team_defensive_analysis,
                "team_offensive": team_offensive_analysis,
                "type_colors": type_colors,
                "pokemon_catalog": pokemon_catalog,
                "computation_time": time.time() - start_time
            }

            # Cache the result
            self.set_cached_data(cache_key, result)

            print(f"Background cache warming completed in {result['computation_time']:.2f}s")
            return result

        except Exception as e:
            print(f"Error in background cache computation: {e}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    def _compute_defensive_matchups(self, types: Dict[str, Any]) -> Dict[str, List[str]]:
        """Compute defensive type matchups."""
        try:
            matrix = load_type_matchup_matrix()
            return self._compute_defensive_matchups_optimized(types, matrix)
        except Exception as e:
            print(f"Error computing defensive matchups: {e}")
            return {"x4": [], "x2": [], "x1": [], "x0.5": [], "x0.25": [], "x0": []}

    def _compute_defensive_matchups_optimized(self, types: Dict[str, Any], matrix: Dict) -> Dict[str, List[str]]:
        """Optimized defensive type matchups computation."""
        type1 = (types.get("type1") or "").lower()
        type2 = (types.get("type2") or "").lower()

        # Calculate effectiveness for all attacking types
        matchups = {"x4": [], "x2": [], "x1": [], "x0.5": [], "x0.25": [], "x0": []}

        for attacking_type in matrix.keys():
            if attacking_type in ["unknown", ""]:
                continue

            eff1 = matrix.get(attacking_type, {}).get(type1, 1.0) if type1 else 1.0
            eff2 = matrix.get(attacking_type, {}).get(type2, 1.0) if type2 else 1.0
            total_eff = eff1 * eff2

            if total_eff == 0:
                matchups["x0"].append(attacking_type)
            elif total_eff == 0.25:
                matchups["x0.25"].append(attacking_type)
            elif total_eff == 0.5:
                matchups["x0.5"].append(attacking_type)
            elif total_eff == 1.0:
                matchups["x1"].append(attacking_type)
            elif total_eff == 2.0:
                matchups["x2"].append(attacking_type)
            elif total_eff == 4.0:
                matchups["x4"].append(attacking_type)

        return matchups

    def _compute_team_defensive_analysis_from_party_matchups(self, party_matchups: List[Dict]) -> Dict[str, Any]:
        """Compute team defensive analysis from party matchups data."""
        if not party_matchups:
            return {}

        try:
            # Enhanced team member data with names and types
            team_members = []
            effectiveness_grid = {}  # attacking_type -> {x4: count, x2: count, x1: count, x0.5: count, x0.25: count, x0: count}

            # All possible attacking types for comprehensive analysis
            all_types = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]

            # Initialize effectiveness grid
            for attack_type in all_types:
                effectiveness_grid[attack_type] = {"x4": 0, "x2": 0, "x1": 0, "x0.5": 0, "x0.25": 0, "x0": 0}

            # Process each team member
            for member in party_matchups:
                matchups = member.get("matchups", {})
                pokemon_name = member.get("species_name", "Unknown")
                types = member.get("types", {})

                team_members.append({
                    "name": pokemon_name,
                    "types": list(types.values()) if isinstance(types, dict) else types,
                    "defensive_types": "/".join(types.values()) if isinstance(types, dict) else "Unknown"
                })

                # Count effectiveness for each attacking type
                for attack_type in all_types:
                    found_effectiveness = False
                    for effectiveness, type_list in matchups.items():
                        if attack_type in type_list:
                            effectiveness_grid[attack_type][effectiveness] += 1
                            found_effectiveness = True
                            break

                    # If not found in any category, assume neutral (x1)
                    if not found_effectiveness:
                        effectiveness_grid[attack_type]["x1"] += 1

            # Risk analysis - identify critical and major weaknesses
            critical_weaknesses = []  # Types that hit 4+ members super effectively
            major_weaknesses = []     # Types that hit 2-3 members super effectively
            team_resistances = []     # Types the team resists well

            team_size = len(party_matchups)

            for attack_type, effectiveness in effectiveness_grid.items():
                super_effective_count = effectiveness["x4"] + effectiveness["x2"]
                resistant_count = effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"]

                if super_effective_count >= max(4, team_size * 0.67):  # 67% or 4+ members
                    critical_weaknesses.append((attack_type, super_effective_count, effectiveness))
                elif super_effective_count >= 2:
                    major_weaknesses.append((attack_type, super_effective_count, effectiveness))

                if resistant_count >= max(3, team_size * 0.5):  # 50% or 3+ members resist
                    team_resistances.append((attack_type, resistant_count, effectiveness))

            # Sort by severity
            critical_weaknesses.sort(key=lambda x: x[1], reverse=True)
            major_weaknesses.sort(key=lambda x: x[1], reverse=True)
            team_resistances.sort(key=lambda x: x[1], reverse=True)

            # Coverage gaps - types with no resistance
            coverage_gaps = []
            for attack_type, effectiveness in effectiveness_grid.items():
                if effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"] == 0:
                    super_effective = effectiveness["x4"] + effectiveness["x2"]
                    if super_effective > 0:
                        coverage_gaps.append((attack_type, super_effective))

            coverage_gaps.sort(key=lambda x: x[1], reverse=True)

            return {
                "team_members": team_members,
                "effectiveness_grid": effectiveness_grid,
                "critical_weaknesses": critical_weaknesses[:5],
                "major_weaknesses": major_weaknesses[:8],
                "team_resistances": team_resistances[:10],
                "coverage_gaps": coverage_gaps[:8],
                "team_size": team_size,
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team defensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}

    def _compute_team_offensive_analysis_from_party(self, party: List[Dict], pokemon_catalog: Dict, type_matrix: Dict) -> Dict[str, Any]:
        """Compute team offensive analysis from party data."""
        if not party:
            return {}

        try:
            # Collect all move types from the team
            all_move_types = set()
            team_members = []

            for i, mon in enumerate(party):
                if not mon:
                    continue

                try:
                    species_id = str(mon.get("species", 0))
                    catalog_entry = pokemon_catalog.get("by_dex", {}).get(species_id, {})
                    species_name = catalog_entry.get("name", f"Species#{species_id}")

                    # Get moves from the mon
                    moves = mon.get("moves", [])
                    move_types = []
                    for move_id in moves:
                        if isinstance(move_id, int):
                            move_entry = get_move_entry(move_id)
                            if move_entry and move_entry.get("type"):
                                move_type = move_entry["type"].lower()
                                move_types.append(move_type)
                                all_move_types.add(move_type)

                    team_members.append({
                        "name": species_name,
                        "move_types": move_types,
                        "move_count": len(move_types)
                    })

                except Exception as e:
                    print(f"Error processing Pokemon {i} in offensive analysis: {e}")

            # Analyze coverage against all defending types
            coverage_analysis = {}
            all_defending_types = ["normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison",
                                 "ground", "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy"]

            for def_type in all_defending_types:
                best_effectiveness = 0.0
                best_moves = []

                for move_type in all_move_types:
                    effectiveness = type_matrix.get(move_type, {}).get(def_type, 1.0)
                    if effectiveness > best_effectiveness:
                        best_effectiveness = effectiveness
                        best_moves = [move_type]
                    elif effectiveness == best_effectiveness and effectiveness > 0:
                        best_moves.append(move_type)

                coverage_analysis[def_type] = {
                    "best_effectiveness": best_effectiveness,
                    "best_moves": best_moves
                }

            # Categorize coverage
            super_effective = []
            neutral = []
            resisted = []

            for def_type, analysis in coverage_analysis.items():
                eff = analysis["best_effectiveness"]
                if eff >= 2.0:
                    super_effective.append((def_type, eff, analysis["best_moves"]))
                elif eff >= 1.0:
                    neutral.append((def_type, eff, analysis["best_moves"]))
                else:
                    resisted.append((def_type, eff, analysis["best_moves"]))

            # Sort by effectiveness
            super_effective.sort(key=lambda x: x[1], reverse=True)
            neutral.sort(key=lambda x: x[1], reverse=True)
            resisted.sort(key=lambda x: x[1], reverse=True)

            return {
                "team_members": team_members,
                "all_move_types": list(all_move_types),
                "coverage_analysis": coverage_analysis,
                "super_effective": super_effective,
                "neutral": neutral,
                "resisted": resisted,
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team offensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}

    def _get_cached_type_colors(self) -> Dict:
        """Get cached type colors."""
        cache_key = "type_colors"
        cached = self.get_cached_data(cache_key)
        if cached:
            return cached
        
        # Load and cache
        from rogueeditor.catalog import load_type_colors
        colors = load_type_colors() or {}
        self.set_cached_data(cache_key, colors)
        return colors

    def _get_cached_type_matrix(self) -> Dict:
        """Get cached type matrix."""
        cache_key = "type_matrix"
        cached = self.get_cached_data(cache_key)
        if cached:
            return cached
        
        # Load and cache
        from rogueeditor.catalog import load_type_matchup_matrix
        matrix = load_type_matchup_matrix()
        self.set_cached_data(cache_key, matrix)
        return matrix

    def invalidate_cache(self, username: str = None, slot: int = None):
        """Invalidate cached data for specific user/slot or all data."""
        with self._cache_lock:
            if username and slot:
                cache_key = f"team_analysis_{username}_{slot}"
                self._cached_data.pop(cache_key, None)
                self._cache_timestamps.pop(cache_key, None)
                print(f"Invalidated cache for {cache_key}")
            else:
                # Clear all cache
                self._cached_data.clear()
                self._cache_timestamps.clear()
                print("Invalidated all cache data")

    def _compute_team_defensive_analysis_from_party_matchups(self, party_matchups: List[Dict]) -> Dict[str, Any]:
        """Compute comprehensive team-wide defensive analysis."""
        if not party_matchups:
            return {}

        try:
            # Enhanced team member data with names and types
            team_members = []
            effectiveness_grid = {}  # attacking_type -> {x4: count, x2: count, x1: count, x0.5: count, x0.25: count, x0: count}

            # All possible attacking types for comprehensive analysis
            all_types = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]

            # Initialize effectiveness grid
            for attack_type in all_types:
                effectiveness_grid[attack_type] = {"x4": 0, "x2": 0, "x1": 0, "x0.5": 0, "x0.25": 0, "x0": 0}

            # Process each team member
            for member in party_matchups:
                matchups = member.get("matchups", {})
                pokemon_name = member.get("species_name", "Unknown")
                level = member.get("level", "?")
                types = member.get("types", {})
                type_list = []
                if isinstance(types, dict):
                    if types.get("type1"):
                        type_list.append(types["type1"])
                    if types.get("type2"):
                        type_list.append(types["type2"])
                elif isinstance(types, list):
                    type_list = types

                team_members.append({
                    "name": pokemon_name,
                    "level": level,
                    "types": type_list,
                    "defensive_types": "/".join(type_list) if type_list else "Unknown"
                })

                # Count effectiveness for each attacking type
                for attack_type in all_types:
                    found_effectiveness = False
                    for effectiveness, type_list in matchups.items():
                        if attack_type in type_list:
                            effectiveness_grid[attack_type][effectiveness] += 1
                            found_effectiveness = True
                            break

                    # If not found in any category, assume neutral (x1)
                    if not found_effectiveness:
                        effectiveness_grid[attack_type]["x1"] += 1

            # Risk analysis - identify critical and major weaknesses
            critical_weaknesses = []  # Types that hit 4+ members super effectively
            major_weaknesses = []     # Types that hit 2-3 members super effectively
            team_resistances = []     # Types the team resists well

            team_size = len(party_matchups)

            for attack_type, effectiveness in effectiveness_grid.items():
                super_effective_count = effectiveness["x4"] + effectiveness["x2"]
                resistant_count = effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"]

                if super_effective_count >= max(4, team_size * 0.67):  # 67% or 4+ members
                    critical_weaknesses.append((attack_type, super_effective_count, effectiveness))
                elif super_effective_count >= 2:
                    major_weaknesses.append((attack_type, super_effective_count, effectiveness))

                if resistant_count >= max(3, team_size * 0.5):  # 50% or 3+ members resist
                    team_resistances.append((attack_type, resistant_count, effectiveness))

            # Sort by severity
            critical_weaknesses.sort(key=lambda x: x[1], reverse=True)
            major_weaknesses.sort(key=lambda x: x[1], reverse=True)
            team_resistances.sort(key=lambda x: x[1], reverse=True)

            # Coverage gaps - types with no resistance
            coverage_gaps = []
            for attack_type, effectiveness in effectiveness_grid.items():
                if effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"] == 0:
                    super_effective = effectiveness["x4"] + effectiveness["x2"]
                    if super_effective > 0:
                        coverage_gaps.append((attack_type, super_effective))

            coverage_gaps.sort(key=lambda x: x[1], reverse=True)

            return {
                "team_members": team_members,
                "effectiveness_grid": effectiveness_grid,
                "critical_weaknesses": critical_weaknesses[:5],
                "major_weaknesses": major_weaknesses[:8],
                "team_resistances": team_resistances[:10],
                "coverage_gaps": coverage_gaps[:8],
                "team_size": team_size,
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team defensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}

    def _compute_team_offensive_analysis_from_party(self, party: List[Dict], pokemon_catalog: Dict, type_matrix: Dict) -> Dict[str, Any]:
        """Compute comprehensive team-wide offensive analysis."""
        if not party:
            return {}

        try:
            from rogueeditor.catalog import load_type_matrix_v2

            type_matrix = load_type_matrix_v2()
            if not type_matrix:
                return {"error": "Type matrix not available"}

            # Team members with their moves organized by type
            team_members = []
            all_team_moves = {}  # type -> list of (pokemon_name, move_name)

            # All possible defending types for analysis
            all_types = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]

            # Process each team member
            for member_data in party:
                if not member_data:
                    continue

                species_id = str(member_data.get("species", 0))
                catalog_entry = pokemon_catalog.get("by_dex", {}).get(species_id, {})
                pokemon_name = catalog_entry.get("name", f"Species#{species_id}")
                level = member_data.get("level", "?")
                moves = member_data.get("moveset", [])

                # Organize moves by type
                member_moves_by_type = {}
                for move_data in moves:
                    if not move_data:
                        continue
                    move_name = move_data.get("moveId", "Unknown Move")
                    move_type = move_data.get("type", "Normal")

                    if move_type not in member_moves_by_type:
                        member_moves_by_type[move_type] = []
                    member_moves_by_type[move_type].append(move_name)

                    # Add to team-wide move tracking
                    if move_type not in all_team_moves:
                        all_team_moves[move_type] = []
                    all_team_moves[move_type].append((pokemon_name, move_name))

                team_members.append({
                    "name": pokemon_name,
                    "level": level,
                    "moves_by_type": member_moves_by_type,
                    "total_moves": len([m for m in moves if m])
                })

            # Coverage analysis against all defending types
            coverage_analysis = {}
            for defending_type in all_types:
                coverage_analysis[defending_type] = {
                    "super_effective": {"count": 0, "types": []},      # 2x effectiveness
                    "neutral": {"count": 0, "types": []},              # 1x effectiveness
                    "not_very_effective": {"count": 0, "types": []},   # 0.5x effectiveness
                    "no_effect": {"count": 0, "types": []},            # 0x effectiveness
                    "best_coverage": None
                }

            # Analyze coverage for each defending type
            for defending_type in all_types:
                best_effectiveness = 0
                best_move_types = []

                for attacking_type, moves_list in all_team_moves.items():
                    if not moves_list:
                        continue

                    # Get effectiveness from type matrix
                    effectiveness = 1.0
                    if defending_type in type_matrix.get(attacking_type, {}):
                        effectiveness = type_matrix[attacking_type][defending_type]

                    # Categorize effectiveness
                    if effectiveness >= 2.0:
                        coverage_analysis[defending_type]["super_effective"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["super_effective"]["types"].append(attacking_type)
                        if effectiveness > best_effectiveness:
                            best_effectiveness = effectiveness
                            best_move_types = [attacking_type]
                        elif effectiveness == best_effectiveness:
                            best_move_types.append(attacking_type)
                    elif effectiveness == 1.0:
                        coverage_analysis[defending_type]["neutral"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["neutral"]["types"].append(attacking_type)
                    elif effectiveness > 0:
                        coverage_analysis[defending_type]["not_very_effective"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["not_very_effective"]["types"].append(attacking_type)
                    else:
                        coverage_analysis[defending_type]["no_effect"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["no_effect"]["types"].append(attacking_type)

                coverage_analysis[defending_type]["best_coverage"] = {
                    "effectiveness": best_effectiveness,
                    "types": best_move_types
                }

            # Risk analysis - find defending types we struggle against
            coverage_risks = []      # Types we have no super effective coverage against
            limited_coverage = []    # Types we have limited options against

            for defending_type, analysis in coverage_analysis.items():
                super_effective_count = analysis["super_effective"]["count"]
                total_coverage = (analysis["super_effective"]["count"] +
                                analysis["neutral"]["count"])

                if super_effective_count == 0:
                    if total_coverage == 0:
                        coverage_risks.append((defending_type, "No Coverage"))
                    else:
                        coverage_risks.append((defending_type, "No Super Effective"))
                elif super_effective_count <= 2:
                    limited_coverage.append((defending_type, super_effective_count))

            # Sort risks
            limited_coverage.sort(key=lambda x: x[1])

            # Team move summary
            move_type_summary = []
            for move_type, moves_list in all_team_moves.items():
                move_type_summary.append({
                    "type": move_type,
                    "count": len(moves_list),
                    "members_with_type": len(set(pokemon for pokemon, move in moves_list))
                })

            move_type_summary.sort(key=lambda x: x["count"], reverse=True)

            return {
                "team_members": team_members,
                "all_team_moves": all_team_moves,
                "coverage_analysis": coverage_analysis,
                "coverage_risks": coverage_risks[:8],
                "limited_coverage": limited_coverage[:10],
                "move_type_summary": move_type_summary[:12],
                "team_size": len([m for m in party if m]),
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team offensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}


# Global cache manager instance
_cache_manager = BackgroundCacheManager()


def warm_team_analysis_cache(api: PokerogueAPI, slot: int, username: str = None) -> Future:
    """
    Public function to start background cache warming for team analysis.
    Call this from main GUI when user logs in or changes slots.

    Args:
        api: PokerogueAPI instance
        slot: Slot number (1-5)
        username: Username for cache key (optional)

    Returns:
        Future that completes when caching is done
    """
    return _cache_manager.warm_team_analysis_cache(api, slot, username)


def invalidate_team_analysis_cache(username: str = None, slot: int = None):
    """
    Public function to invalidate team analysis cache.
    Call this when team data changes.

    Args:
        username: Username for cache key (optional, clears all if None)
        slot: Slot number (optional, clears all if None)
    """
    _cache_manager.invalidate_cache(username, slot)


def _get_species_id(mon: dict) -> Optional[int]:
    for k in ("species", "dexId", "speciesId", "pokemonId"):
        v = mon.get(k)
        if isinstance(v, int):
            return v
        try:
            return int(v)
        except Exception:
            continue
    return None


def _get(mon: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in mon:
            return mon.get(k)
    return None


def _set(mon: dict, keys: tuple[str, ...], value: Any) -> None:
    for k in keys:
        if k in mon:
            mon[k] = value
            return
    # Default to the first
    if keys:
        mon[keys[0]] = value


def _calc_stats(level: int, base: List[int], ivs: List[int], nature_mults: List[float], booster_mults: Optional[List[float]] = None) -> List[int]:
    # Order: HP, Atk, Def, SpA, SpD, Spe
    out: List[int] = [0] * 6
    for i in range(6):
        b = int(base[i])
        iv = int(ivs[i]) if 0 <= i < len(ivs) else 0
        if i == 0:
            val = math.floor(((2 * b + iv) * level) / 100) + level + 10
        else:
            val = math.floor(((2 * b + iv) * level) / 100) + 5
            n = nature_mults[i] if 0 <= i < len(nature_mults) else 1.0
            val = math.floor(val * n)
        if booster_mults and 0 <= i < len(booster_mults):
            val = math.floor(val * booster_mults[i])
        out[i] = int(val)
    return out


def _booster_multipliers_for_mon(slot_data: dict, mon_id: int) -> Tuple[List[float], List[bool], List[int]]:
    # Returns (multipliers[6], boosted_flags[6], boost_counts[6]) for BASE_STAT_BOOSTER modifiers
    mults = [1.0] * 6
    boosted = [False] * 6
    counts = [0] * 6
    # Aggregate stacks by stat index first to avoid compounding factors across separate entries
    by_idx: dict[int, int] = {}
    mods = (slot_data.get("modifiers") if isinstance(slot_data, dict) else None) or []
    for m in mods:
        if not isinstance(m, dict):
            continue
        if str(m.get("typeId") or "").upper() != "BASE_STAT_BOOSTER":
            continue
        args = m.get("args") or []
        if not (isinstance(args, list) and args):
            continue
        if not isinstance(args[0], int) or args[0] != mon_id:
            continue
        stat_id = None
        if len(args) >= 2 and isinstance(args[1], int):
            stat_id = args[1]
        # Fallback to typePregenArgs when args[1] missing
        if stat_id is None:
            tpa = m.get("typePregenArgs") or []
            if isinstance(tpa, list) and tpa and isinstance(tpa[0], int):
                stat_id = tpa[0]
        stacks = int(m.get("stackCount") or 1)
        # Map stat_id (from catalog) to index 0..5; prefer direct id mapping (stats.json aligns ids)
        idx = None
        if isinstance(stat_id, int) and 0 <= stat_id <= 5:
            idx = stat_id
        else:
            try:
                _, stat_i2n = load_stat_catalog()
                name = stat_i2n.get(int(stat_id)) if isinstance(stat_id, int) else None
                name_key = str(name or "").strip().lower().replace(" ", "_")
                name_to_idx = {
                    "hp": 0,
                    "atk": 1,
                    "attack": 1,
                    "def": 2,
                    "defense": 2,
                    "spatk": 3,
                    "sp_atk": 3,
                    "spdef": 4,
                    "sp_def": 4,
                    "spd": 5,
                    "speed": 5,
                }
                idx = name_to_idx.get(name_key)
            except Exception:
                idx = None
        if idx is None:
            continue
        by_idx[idx] = by_idx.get(idx, 0) + max(0, stacks)
    for idx, total in by_idx.items():
        factor = 1.0 + 0.10 * total  # +10% per stack
        mults[idx] = factor
        boosted[idx] = True
        counts[idx] = total
    return mults, boosted, counts


class TeamManagerDialog(tk.Toplevel):
    def __init__(self, master, api: PokerogueAPI, editor: Editor, slot: int):
        print(f"[TRACE] TeamManagerDialog.__init__ ENTRY - slot {slot}")
        debug_log(f"__init__ started for slot {slot}")
        print(f"[TRACE] About to call super().__init__()")
        super().__init__(master)
        print(f"[TRACE] super().__init__() completed")
        try:
            s = int(slot)
        except Exception:
            s = 1
        s = 1 if s < 1 else (5 if s > 5 else s)
        debug_log("Setting title and geometry")
        self.title(f"Rogue Manager GUI - Team Manager (Slot {s})")
        # Make Team Manager larger than main window to show all content
        default_geometry = "1200x900"
        self.geometry(default_geometry)
        self.minsize(1000, 700)
        self.api = api
        self.editor = editor
        self.slot = s

        debug_log(f" Loading window geometry")
        # Load saved window size if available
        self._load_window_geometry(default_geometry)

        debug_log(f" Initializing performance caches")
        # Initialize enhanced caching system
        self._init_performance_caches()

        # Track whether backup has been created for party reordering in this session
        self._party_reorder_backup_created = False

        # Background cache integration
        self._background_cache_future: Optional[Future] = None
        self._cached_analysis_data: Optional[Dict[str, Any]] = None

        # Enhanced Pokemon switching optimization with deeper caching
        self._pokemon_data_cache: Dict[int, Dict] = {}  # species_id -> cached data
        self._pokemon_analysis_cache: Dict[str, Dict] = {}  # pokemon_key -> analysis data
        self._party_member_cache: Dict[int, Dict] = {}  # party_index -> full member data
        self._current_pokemon_index: Optional[int] = None

        # Snapshot (defer heavy operations to avoid blocking UI)
        self.data: Dict[str, Any] = {}
        self.party: List[dict] = []
        # Dirty flags (slot)
        self._dirty_local = False
        
        # Will load data after UI is built
        self._dirty_server = False
        # Trainer snapshot + flags (team editor focuses on slot/session only)
        self._trainer_data: Optional[Dict[str, Any]] = None
        self._trainer_dirty_local: bool = False
        self._trainer_dirty_server: bool = False

        debug_log(f" Loading Pokemon catalog synchronously")
        print(f"[TRACE] About to import load_pokemon_catalog")
        # Load Pokemon catalog synchronously (needed for _refresh_party)
        try:
            print(f"[TRACE] Importing catalog module...")
            from rogueeditor.catalog import load_pokemon_catalog
            print(f"[TRACE] Import successful, calling load_pokemon_catalog()")
            self._pokemon_catalog_cache = load_pokemon_catalog() or {}
            print(f"[TRACE] Pokemon catalog loaded successfully")
        except Exception as e:
            print(f"[TRACE] Exception loading pokemon catalog: {e}")
            self._pokemon_catalog_cache = {}

        print(f"[TRACE] About to load Pokemon index")
        # Load Pokemon index synchronously (needed for _refresh_party)
        try:
            print(f"[TRACE] Calling load_pokemon_index()...")
            self._pokemon_index_cache = load_pokemon_index() or {}
            print(f"[TRACE] Pokemon index loaded successfully")
        except Exception as e:
            print(f"[TRACE] Exception loading pokemon index: {e}")
            self._pokemon_index_cache = {}
        
        debug_log(f" Initializing empty catalogs")
        print(f"[TRACE] Initializing empty catalogs...")
        # Initialize other catalogs as empty to prevent errors
        self.move_n2i, self.move_i2n = {}, {}
        self.abil_n2i, self.abil_i2n = {}, {}
        self.nat_n2i, self.nat_i2n = {}, {}
        self.nature_mults_by_id = {}
        print(f"[TRACE] Empty catalogs initialized")

        debug_log(f" Building UI")
        print(f"[TRACE] About to call _build()...")
        # Build UI first
        self._build()
        print(f"[TRACE] _build() completed successfully")

        debug_log(f" Loading catalogs synchronously")
        print(f"[TRACE] About to call _load_catalogs_sync()...")
        # Load catalogs synchronously for reliability
        self._load_catalogs_sync()
        print(f"[TRACE] _load_catalogs_sync() completed")

        debug_log(f" Loading data synchronously")
        print(f"[TRACE] About to call _load_data_sync()...")
        # Load data after UI is built so we can refresh it
        self._load_data_sync()
        print(f"[TRACE] _load_data_sync() completed")

        debug_log(f" Installing context menus")
        # Install context menus for text widgets (right-click: cut/copy/paste/select-all)
        try:
            self._install_context_menus()
        except Exception:
            pass

        debug_log(f" Setting up window close handler")
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_window_closing)
        except Exception:
            pass

        debug_log(f" Modalizing window")
        try:
            master._modalize(self)
        except Exception:
            pass
        debug_log(f" TeamManagerDialog.__init__ completed successfully")


    def _load_catalogs_sync(self):
        """Load catalogs synchronously for reliability."""
        debug_log("Loading catalogs synchronously...")
        try:
            # Load essential catalogs directly for simplicity
            debug_log("Loading move catalogs...")
            try:
                self.move_n2i, self.move_i2n = build_move_label_catalog()
                if not self.move_n2i or not self.move_i2n:
                    self.move_n2i, self.move_i2n = load_move_catalog()
            except Exception:
                self.move_n2i, self.move_i2n = load_move_catalog()

            debug_log("Loading ability catalog...")
            self.abil_n2i, self.abil_i2n = load_ability_catalog()

            debug_log("Loading nature catalog...")
            self.nat_n2i, self.nat_i2n = load_nature_catalog()
            self.nature_mults_by_id = nature_multipliers_by_id()

            debug_log("Catalogs loaded successfully")
        except Exception as e:
            debug_log(f"Error loading catalogs: {e}")
            # Set empty catalogs as fallback
            self.move_n2i, self.move_i2n = {}, {}
            self.abil_n2i, self.abil_i2n = {}, {}
            self.nat_n2i, self.nat_i2n = {}, {}
            self.nature_mults_by_id = {}

    def _load_data_sync(self):
        """Load slot data synchronously."""
        debug_log(f"Loading data for slot {self.slot}...")
        try:
            # Ensure clientSessionId is available
            if not getattr(self.api, 'client_session_id', None):
                debug_log("Missing clientSessionId, using empty data")
                self.data = {}
                self.party = []
            else:
                # Load slot data directly
                self.data = self.api.get_slot(self.slot)
                self.party = self.data.get("party") or []
                debug_log(f"Data loaded: {len(self.party)} party members")

        except Exception as e:
            debug_log(f"Error loading data for slot {self.slot}: {e}")
            # Use empty data as fallback
            self.data = {}
            self.party = []

        # Refresh UI with loaded data (now using safe _refresh_party method)
        debug_log("Refreshing UI with loaded data...")
        try:
            if hasattr(self, 'target_var'):
                self._refresh_party()
                debug_log("Party refreshed in UI using safe method")
            else:
                debug_log("UI not ready yet, will refresh later")
        except Exception as e:
            debug_log(f"Error refreshing UI: {e}")
        debug_log("_load_data_sync completed")

    def _on_catalogs_loaded(self, move_n2i, move_i2n, abil_n2i, abil_i2n, nat_n2i, nat_i2n, nature_mults_by_id, type_matrix=None, type_colors=None, type_n2i=None, type_i2n=None):
        """Handle successful catalog loading on main thread."""
        try:
            print("_on_catalogs_loaded: Starting to process catalogs...")
            self.move_n2i, self.move_i2n = move_n2i, move_i2n
            print("_on_catalogs_loaded: Move catalogs set")
            self.abil_n2i, self.abil_i2n = abil_n2i, abil_i2n
            print("_on_catalogs_loaded: Ability catalogs set")
            self.nat_n2i, self.nat_i2n = nat_n2i, nat_i2n
            print("_on_catalogs_loaded: Nature catalogs set")
            self.nature_mults_by_id = nature_mults_by_id
            print("_on_catalogs_loaded: Nature multipliers set")
            
            # Set additional catalogs if provided
            if type_matrix is not None:
                self._type_matrix = type_matrix
                print("_on_catalogs_loaded: Type matrix set")
            if type_colors is not None:
                self._type_colors = type_colors
                print("_on_catalogs_loaded: Type colors set")
            if type_n2i is not None and type_i2n is not None:
                self._type_n2i, self._type_i2n = type_n2i, type_i2n
                print("_on_catalogs_loaded: Type catalogs set")

            print("Catalogs loaded successfully - all done!")
        except Exception as e:
            print(f"Error handling loaded catalogs: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_catalogs_load_error(self, error: Exception):
        """Handle catalog loading error on main thread."""
        print(f"Error loading catalogs: {error}")
        # Keep empty catalogs to prevent further errors

    def _load_data_async(self):
        """Load slot data asynchronously to prevent UI freezing."""
        import threading
        
        def _load_data_background():
            """Load data in background thread."""
            try:
                print(f"Loading data for slot {self.slot}...")
                data = self.api.get_slot(self.slot)
                party = data.get("party") or []
                
                # Schedule UI update on main thread
                self.after(0, lambda: self._on_data_loaded(data, party))
                
            except Exception as e:
                print(f"Error loading data for slot {self.slot}: {e}")
                # Schedule error handling on main thread
                self.after(0, lambda: self._on_data_load_error(e))
        
        # Start background thread
        thread = threading.Thread(target=_load_data_background, daemon=True)
        thread.start()

    def _on_data_loaded(self, data: Dict[str, Any], party: List[dict]):
        """Handle successful data loading on main thread."""
        try:
            print(f"Data loaded successfully for slot {self.slot}")
            self.data = data
            self.party = party

            # Check if we have empty data due to missing clientSessionId
            if not data and not party:
                debug_log("Data loaded: Empty data detected, likely due to missing clientSessionId")
                self._show_session_warning()

            # Refresh UI with loaded data (only if UI is built)
            if hasattr(self, 'target_var'):
                print("Refreshing party...")
                self._refresh_party()
                print("Party refreshed")
                
                # Start background cache warming after data is loaded
                print("Starting background cache warming...")
                self._start_background_cache_warming()
                print("Background cache warming started")
                
                # Skip progressive loading for now to avoid freezing
                # TODO: Re-implement trainer mode analysis with simpler approach
                debug_log("Skipping trainer mode progressive loading to prevent freezing")
            
            print(f"Data loading completed for slot {self.slot}")
        except Exception as e:
            print(f"Error handling loaded data: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_data_load_error(self, error: Exception):
        """Handle data loading error on main thread."""
        debug_log(f"Data load error: {error}")
        # Set empty data to prevent further errors
        self.data = {}
        self.party = []

    def _show_session_warning(self):
        """Show warning about missing session data."""
        try:
            import tkinter.messagebox as msgbox
            msgbox.showwarning(
                "Session Required",
                "Team data could not be loaded because no active session was found.\n\n"
                "Please ensure you're logged in and try refreshing your session from the main window.\n\n"
                "You can still view and edit team configurations, but they won't be saved to the server."
            )
        except Exception:
            debug_log("Could not show session warning dialog")

    # --- Helpers: Nature labeling ---
    def _nature_change_suffix(self, nid: int) -> str:
        mults = self.nature_mults_by_id.get(int(nid)) or []
        if not mults:
            return "(neutral)"
        up = None
        down = None
        # Index mapping: 1..5 correspond to Atk, Def, SpA, SpD, Spd
        idx_to_abbr = {1: "Atk", 2: "Def", 3: "SpA", 4: "SpD", 5: "Spd"}
        for i in range(1, 6):
            try:
                if mults[i] > 1.0:
                    up = idx_to_abbr.get(i)
                elif mults[i] < 1.0:
                    down = idx_to_abbr.get(i)
            except Exception:
                pass
        if not up and not down:
            return "(neutral)"
        parts = []
        if up:
            parts.append(f"{up}+")
        if down:
            parts.append(f"{down}-")
        return f"({', '.join(parts)})"

    def _format_nature_name(self, raw: str) -> str:
        s = str(raw or "").strip().replace("_", " ")
        return s[:1].upper() + s[1:].lower()

    def _nature_label_for_id(self, nid: int) -> str:
        name = self.nat_i2n.get(int(nid), str(nid))
        disp = self._format_nature_name(name)
        return f"{disp} {self._nature_change_suffix(int(nid))}"

    def _nature_select_map(self) -> dict[str, int]:
        # Build a display map: "Name (Atk+, SpD-)" -> id
        out: dict[str, int] = {}
        for nid, name in sorted(self.nat_i2n.items(), key=lambda kv: kv[0]):
            label = self._nature_label_for_id(int(nid))
            out[label] = int(nid)
        return out

    # --- UI Assembly ---
    def _build(self):
        debug_log("Starting UI build")
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)
        debug_log("Root frame created and packed")
        # Left
        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)
        ttk.Label(left, text="Target:").pack(anchor=tk.W)
        self.target_var = tk.StringVar(value="Party")
        self._last_target = "Party"  # Track target changes for unsaved changes warning
        trow = ttk.Frame(left)
        trow.pack(anchor=tk.W)
        ttk.Radiobutton(trow, text="Trainer", variable=self.target_var, value="Trainer", command=self._on_target_changed).pack(side=tk.LEFT)
        ttk.Radiobutton(trow, text="Party", variable=self.target_var, value="Party", command=self._on_target_changed).pack(side=tk.LEFT, padx=8)
        ttk.Label(left, text="Party:").pack(anchor=tk.W, pady=(6, 0))
        self.party_list = tk.Listbox(left, height=12, exportselection=False, selectmode=tk.SINGLE)
        # Horizontal scrollbar for long labels
        try:
            self.party_hscroll = ttk.Scrollbar(left, orient="horizontal", command=self.party_list.xview)
            self.party_list.configure(xscrollcommand=self.party_hscroll.set)
            self.party_list.pack(fill=tk.Y, expand=False)
            self.party_hscroll.pack(fill=tk.X, padx=0, pady=(0, 4))
        except Exception:
            # Fallback without scrollbar
            self.party_list.pack(fill=tk.Y, expand=False)
        # Helper text to clarify selection-only and where to reorder
        #try:
        #    ttk.Label(left,
        #             text="Select a Pokémon;\nuse Party Reordern \nbelow to rearrange.",
        #             foreground='gray').pack(anchor=tk.W, pady=(4, 0))
        #except Exception:
        #    pass
        # Mouse-based selection: lock selection on click, disable drag-to-select to prevent drift
        try:
            self.party_list.bind("<Button-1>", lambda e: self._on_party_click(e))
            self.party_list.bind("<B1-Motion>", lambda e: "break")  # prevent drag selection
        except Exception:
            pass
        # Keyboard or programmatic selection fallback
        self.party_list.bind("<<ListboxSelect>>", lambda e: self._on_party_list_select_event())

        # Right
        right = ttk.Frame(root)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Header with slot info and buttons
        header = ttk.Frame(right)
        header.pack(fill=tk.X, pady=(0, 6))

        # Target slot label (left)
        ttk.Label(header, text=f"Target Slot: {self.slot}",
                 font=('TkDefaultFont', 10, 'bold')).pack(side=tk.LEFT)

        # Save/Upload buttons (right)
        buttons_frame = ttk.Frame(header)
        buttons_frame.pack(side=tk.RIGHT)
        self.btn_save = ttk.Button(buttons_frame, text="Save to file", command=self._save, state=tk.DISABLED)
        self.btn_upload = ttk.Button(buttons_frame, text="Upload", command=self._upload, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_upload.pack(side=tk.LEFT)
        
        # Add tooltips to clarify the workflow
        self._create_tooltip(self.btn_save, 
            "Save to file: Writes all changes to the local save file on disk.\n"
            "This includes Pokémon data, trainer data, and party order changes.\n"
            "Changes are automatically applied to memory as you edit.")
        self._create_tooltip(self.btn_upload, 
            "Upload: Syncs all changes to the server.\n"
            "This uploads the current save data to the online game.\n"
            "Make sure to 'Save to file' first to persist changes locally.")

        # Tabs below header
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        # Keep a reference to right pane for overlays
        try:
            self._content_root = right
        except Exception:
            pass
        # Pokemon tabs (Basics, Stats, Moves)
        self.tab_poke_basics = ttk.Frame(self.tabs)
        self._build_basics(self.tab_poke_basics)
        self.tab_poke_stats = ttk.Frame(self.tabs)
        self._build_stats(self.tab_poke_stats)
        self.tab_poke_moves = ttk.Frame(self.tabs)
        self._build_moves(self.tab_poke_moves)
        # Defensive Matchups tab
        self.tab_poke_matchups = ttk.Frame(self.tabs)
        self._build_matchups(self.tab_poke_matchups)
        # Offensive Matchups tab
        self.tab_poke_coverage = ttk.Frame(self.tabs)
        self._build_offensive_coverage(self.tab_poke_coverage)
        # Pokemon tab: Form & Visuals
        self.tab_poke_form = ttk.Frame(self.tabs)
        self._build_form_visuals(self.tab_poke_form)
        # Trainer tabs (Basics)
        self.tab_trainer_basics = ttk.Frame(self.tabs)
        self._build_trainer_basics(self.tab_trainer_basics)

        # Team Defensive Analysis (standalone tab) - with skeleton loading
        self.tab_team_defensive = ttk.Frame(self.tabs)
        self._defensive_skeleton = self._create_skeleton_frame(self.tab_team_defensive,
                                                             "Loading team defensive analysis...")

        # Team Offensive Analysis (standalone tab) - with skeleton loading
        self.tab_team_offensive = ttk.Frame(self.tabs)
        self._offensive_skeleton = self._create_skeleton_frame(self.tab_team_offensive,
                                                             "Loading team offensive analysis...")

        # Set up tab change binding for deferred updates
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # Initialize tab persistence
        self._last_selected_tab = None

        # Initial view
        self._apply_target_visibility()

        # Bind all fields for automatic updates
        self._bind_all_fields_auto_update()

        # Center the window relative to parent
        self._center_relative_to_parent()


    def _center_relative_to_parent(self):
        """Center this window relative to its parent window."""
        try:
            self.update_idletasks()

            # Get parent window geometry
            parent = self.master
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()

            # Get this window size
            child_width = self.winfo_reqwidth()
            child_height = self.winfo_reqheight()

            # Calculate center position
            x = parent_x + (parent_width - child_width) // 2
            y = parent_y + (parent_height - child_height) // 2

            # Ensure window stays on screen
            x = max(0, x)
            y = max(0, y)

            # Set window position
            self.geometry(f"{child_width}x{child_height}+{x}+{y}")
        except Exception:
            # Fallback to default positioning if centering fails
            pass

    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget."""
        try:
            def on_enter(event):
                tooltip = tk.Toplevel()
                tooltip.wm_overrideredirect(True)
                tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                label = tk.Label(tooltip, text=text, justify=tk.LEFT, 
                               background="lightyellow", relief=tk.SOLID, borderwidth=1,
                               font=("TkDefaultFont", 9))
                label.pack(ipadx=4, ipady=2)
                widget._tooltip = tooltip
            
            def on_leave(event):
                if hasattr(widget, '_tooltip'):
                    widget._tooltip.destroy()
                    del widget._tooltip
            
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
        except Exception as e:
            debug_log(f"Error creating tooltip: {e}")

    def _on_money_change(self):
        """Handle money field changes and update data automatically."""
        try:
            # Update money in data immediately
            money_str = (self.var_money.get() or "").strip()
            if money_str:
                try:
                    money = int(money_str)
                    if money < 0:
                        money = 0
                    self.data["money"] = money
                except ValueError:
                    # Invalid number, don't update data
                    pass
            else:
                self.data["money"] = 0
            
            # Mark as dirty and update buttons
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
        except Exception as e:
            debug_log(f"Error handling money change: {e}")

    def _on_weather_change(self):
        """Handle weather field changes and update data automatically."""
        try:
            # Update weather in data immediately
            weather_text = (self.var_weather.get() or "").strip()
            if weather_text and hasattr(self, '_weather_n2i'):
                # Extract weather ID from formatted text
                weather_id = None
                for name, wid in self._weather_n2i.items():
                    if f"{name} ({wid})" == weather_text:
                        weather_id = wid
                        break
                
                if weather_id is not None:
                    self.data[self._weather_key()] = weather_id
                else:
                    # Clear weather if not found
                    if self._weather_key() in self.data:
                        del self.data[self._weather_key()]
            else:
                # Clear weather if empty
                if self._weather_key() in self.data:
                    del self.data[self._weather_key()]
            
            # Mark as dirty and update buttons
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
        except Exception as e:
            debug_log(f"Error handling weather change: {e}")

    def _bind_all_fields_auto_update(self):
        """Bind all form fields to automatically update data when changed."""
        try:
            # Basics tab fields
            if hasattr(self, 'var_name'):
                self.var_name.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_hp'):
                self.var_hp.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_level'):
                self.var_level.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_exp'):
                self.var_exp.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_friend'):
                self.var_friend.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_status'):
                self.var_status.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_ability'):
                self.var_ability.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_passive'):
                self.var_passive.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_pokerus'):
                self.var_pokerus.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            # Stats tab fields
            if hasattr(self, 'var_nature'):
                self.var_nature.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            # Form & Visuals tab fields
            if hasattr(self, 'var_tera'):
                self.var_tera.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_shiny'):
                self.var_shiny.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_luck'):
                self.var_luck.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_pause_evo'):
                self.var_pause_evo.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_gender'):
                self.var_gender.trace_add("write", lambda *args: self._on_pokemon_field_change())
            if hasattr(self, 'var_ball'):
                self.var_ball.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            # IV fields (if they exist)
            if hasattr(self, 'iv_vars') and isinstance(self.iv_vars, list):
                for iv_var in self.iv_vars:
                    if iv_var:
                        iv_var.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            # Move fields (if they exist)
            if hasattr(self, 'move_vars') and isinstance(self.move_vars, list):
                for move_var in self.move_vars:
                    if move_var:
                        move_var.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            if hasattr(self, 'move_ppup_vars') and isinstance(self.move_ppup_vars, list):
                for ppup_var in self.move_ppup_vars:
                    if ppup_var:
                        ppup_var.trace_add("write", lambda *args: self._on_pokemon_field_change())
            
            if hasattr(self, 'move_ppused_vars') and isinstance(self.move_ppused_vars, list):
                for ppused_var in self.move_ppused_vars:
                    if ppused_var:
                        ppused_var.trace_add("write", lambda *args: self._on_pokemon_field_change())
                    
        except Exception as e:
            debug_log(f"Error binding fields for auto-update: {e}")

    def _on_pokemon_field_change(self):
        """Handle any Pokémon field change and apply changes to data immediately."""
        try:
            # Skip if we're currently loading data to prevent conflicts
            if getattr(self, '_loading_data', False):
                return
                
            mon = self._current_mon()
            if not mon:
                return
            
            # Apply changes to the current Pokémon data
            self._apply_pokemon_changes_to_data(mon)
            
            # Mark as dirty and update buttons
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
        except Exception as e:
            debug_log(f"Error handling Pokémon field change: {e}")

    def _apply_pokemon_changes_to_data(self, mon: dict):
        """Apply all current field values to the Pokémon data with special case handling."""
        try:
            # Set sync guard to prevent recursion during EXP/level synchronization
            self._sync_guard = True
            
            # Basics tab fields
            if hasattr(self, 'var_name'):
                mon['nickname'] = (self.var_name.get() or "").strip()
            
            if hasattr(self, 'var_hp'):
                try:
                    hp = int((self.var_hp.get() or "0").strip() or "0")
                    if hp < 0:
                        hp = 0
                    mon['currentHp'] = hp
                except Exception:
                    pass
            
            # Special case: EXP/Level synchronization
            # Handle EXP and Level changes with proper synchronization
            if hasattr(self, 'var_exp') and hasattr(self, 'var_level'):
                try:
                    exp = int((self.var_exp.get() or "0").strip() or "0")
                    level = int((self.var_level.get() or "1").strip() or "1")
                    
                    if exp < 0:
                        exp = 0
                    if level < 1:
                        level = 1
                    
                    # Apply both values to data
                    mon['exp'] = exp
                    mon['level'] = level
                    
                    # Synchronize: if EXP changed, update level; if level changed, update EXP
                    gidx = self._growth_index_for_mon(mon)
                    
                    # Calculate what level this EXP should give
                    calculated_level = level_from_exp(gidx, exp)
                    if calculated_level < 1:
                        calculated_level = 1
                    
                    # Calculate what EXP this level should give
                    calculated_exp = exp_for_level(gidx, level)
                    
                    # Update the UI to reflect the calculated values (without triggering recursion)
                    if calculated_level != level:
                        self.var_level.set(str(calculated_level))
                        mon['level'] = calculated_level
                    
                    if calculated_exp != exp:
                        self.var_exp.set(str(calculated_exp))
                        mon['exp'] = calculated_exp
                        
                except Exception as e:
                    debug_log(f"Error in EXP/Level synchronization: {e}")
            else:
                # Fallback: handle EXP and Level separately if only one exists
                if hasattr(self, 'var_level'):
                    try:
                        level = int((self.var_level.get() or "1").strip() or "1")
                        if level < 1:
                            level = 1
                        mon['level'] = level
                        if hasattr(self, 'var_exp'):
                            gidx = self._growth_index_for_mon(mon)
                            exp = exp_for_level(gidx, level)
                            mon['exp'] = exp
                    except Exception:
                        pass
                
                if hasattr(self, 'var_exp'):
                    try:
                        exp = int((self.var_exp.get() or "0").strip() or "0")
                        if exp < 0:
                            exp = 0
                        mon['exp'] = exp
                        gidx = self._growth_index_for_mon(mon)
                        level = level_from_exp(gidx, exp)
                        if level < 1:
                            level = 1
                        mon['level'] = level
                    except Exception:
                        pass
            
            if hasattr(self, 'var_friend'):
                try:
                    friendship = int((self.var_friend.get() or "0").strip() or "0")
                    if friendship < 0:
                        friendship = 0
                    mon['friendship'] = friendship
                except Exception:
                    pass
            
            if hasattr(self, 'var_status'):
                status = (self.var_status.get() or "").strip()
                if status and status != "none":
                    mon['status'] = status
                    # Update status fields visibility and summary
                    self._update_status_fields_visibility()
                    self._update_status_summary()
                else:
                    mon.pop('status', None)
                    # Clear status fields when status is removed
                    self._update_status_fields_visibility()
                    self._update_status_summary()
            
            if hasattr(self, 'var_ability'):
                ability_text = self.var_ability.get()
                if ability_text and hasattr(self, 'ability_n2i'):
                    ability_id = self._parse_id_from_combo(ability_text, self.ability_n2i)
                    if isinstance(ability_id, int):
                        mon['abilityId'] = ability_id
            
            if hasattr(self, 'var_passive'):
                mon['passive'] = bool(self.var_passive.get())
            
            if hasattr(self, 'var_pokerus'):
                mon['pokerus'] = bool(self.var_pokerus.get())
            
            # Stats tab fields
            if hasattr(self, 'var_nature'):
                nature_text = self.var_nature.get()
                if nature_text and hasattr(self, 'nat_n2i'):
                    nature_id = self._parse_id_from_combo(nature_text, self.nat_n2i)
                    if isinstance(nature_id, int):
                        mon['nature'] = nature_id
                        # Update nature hint display
                        self._update_nature_hint()
            
            # Apply IVs if they exist
            if hasattr(self, 'iv_vars'):
                ivs = []
                for v in self.iv_vars:
                    try:
                        x = int((v.get() or "0").strip())
                        if x < 0:
                            x = 0
                        if x > 31:
                            x = 31
                        ivs.append(x)
                    except Exception:
                        ivs.append(0)
                mon["ivs"] = ivs
            
            # Form & Visuals tab fields
            if hasattr(self, 'var_tera'):
                tera_text = self.var_tera.get()
                if tera_text and hasattr(self, '_type_n2i'):
                    tera_id = self._parse_id_from_combo(tera_text, self._type_n2i)
                    if isinstance(tera_id, int):
                        mon['teraType'] = tera_id
            
            if hasattr(self, 'var_shiny'):
                shiny = bool(self.var_shiny.get())
                mon['shiny'] = shiny
                # Reset luck if not shiny
                if not shiny and hasattr(self, 'var_luck'):
                    mon['luck'] = 0
                    # Update UI to reflect luck reset
                    self.var_luck.set('0')
            
            if hasattr(self, 'var_luck'):
                try:
                    luck = int((self.var_luck.get() or '0').strip() or '0')
                    if luck < 0:
                        luck = 0
                    mon['luck'] = luck
                except Exception:
                    mon['luck'] = 0
            
            if hasattr(self, 'var_pause_evo'):
                mon['pauseEvolutions'] = bool(self.var_pause_evo.get())
            
            if hasattr(self, 'var_gender'):
                gender_text = self.var_gender.get()
                if gender_text and hasattr(self, '_gender_n2i'):
                    gender_id = self._parse_id_from_combo(gender_text, self._gender_n2i)
                    if isinstance(gender_id, int):
                        mon['gender'] = gender_id
            
            if hasattr(self, 'var_ball'):
                ball_text = self.var_ball.get()
                if ball_text and hasattr(self, '_ball_n2i'):
                    ball_id = self._parse_id_from_combo(ball_text, self._ball_n2i)
                    if isinstance(ball_id, int):
                        mon['ball'] = ball_id
            
            # Apply moves if they exist
            if hasattr(self, 'move_vars') and hasattr(self, 'move_n2i'):
                self._apply_moves_to_data(mon)
            
            # Recalculate stats after changes
            self._recalc_stats_safe()
            
        except Exception as e:
            debug_log(f"Error applying Pokémon changes to data: {e}")
        finally:
            # Always clear the sync guard
            self._sync_guard = False

    def _apply_moves_to_data(self, mon: dict):
        """Apply move changes to Pokémon data."""
        try:
            if not hasattr(self, 'move_vars') or not hasattr(self, 'move_n2i'):
                return
            
            # Ensure we have a key and shapes from last bind; if not, derive again
            key, shapes, current = self._derive_moves(mon)
            lst = mon.get(key)
            if not isinstance(lst, list):
                lst = []
            
            # Build new list preserving shapes and any extra dict fields
            out = list(lst)  # copy
            for i in range(4):
                mid = self._parse_id_from_combo(self.move_vars[i].get(), self.move_n2i)
                mid_i = int(mid or 0)
                shape = shapes[i] if i < len(shapes) else "int"
                
                if i < len(out):
                    cur = out[i]
                else:
                    cur = None
                
                if shape == "id":
                    if isinstance(cur, dict):
                        cur["id"] = mid_i
                    else:
                        out[i] = {"id": mid_i}
                else:
                    out[i] = mid_i
                
                # Apply PP Up and PP Used if they exist
                if hasattr(self, 'move_ppup_vars') and i < len(self.move_ppup_vars):
                    try:
                        ppup = int((self.move_ppup_vars[i].get() or "0").strip())
                        if ppup < 0:
                            ppup = 0
                        if ppup > 3:
                            ppup = 3
                        if isinstance(out[i], dict):
                            out[i]["ppUp"] = ppup
                    except Exception:
                        pass
                
                if hasattr(self, 'move_ppused_vars') and i < len(self.move_ppused_vars):
                    try:
                        ppused = int((self.move_ppused_vars[i].get() or "0").strip())
                        if ppused < 0:
                            ppused = 0
                        if isinstance(out[i], dict):
                            out[i]["ppUsed"] = ppused
                    except Exception:
                        pass
            
            mon[key] = out
            
            # Invalidate offensive matchups cache for this specific Pokémon since moves affect offensive analysis
            self._invalidate_pokemon_offensive_cache(mon)
            
        except Exception as e:
            debug_log(f"Error applying moves to data: {e}")

    def _build_basics(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Species + types header
        hdr = ttk.Frame(frm)
        hdr.grid(row=0, column=0, columnspan=6, sticky=tk.W, pady=(2, 8))
        ttk.Label(hdr, text="Species:").pack(side=tk.LEFT)
        self.lbl_species_name = ttk.Label(hdr, text="-")
        self.lbl_species_name.pack(side=tk.LEFT, padx=(4, 12))
        # Types area (label + chips inside a dedicated frame to keep order)
        self.types_frame = ttk.Frame(hdr)
        self.types_frame.pack(side=tk.LEFT)
        ttk.Label(self.types_frame, text="Types:").pack(side=tk.LEFT)
        # Type chips (packed dynamically in _on_party_selected)
        self.type_chip1 = tk.Label(self.types_frame, text="", bd=1, relief=tk.SOLID, padx=6)
        self.type_chip1.pack(side=tk.LEFT, padx=3)
        self.type_chip2 = tk.Label(self.types_frame, text="", bd=1, relief=tk.SOLID, padx=6)
        self.type_chip2.pack(side=tk.LEFT, padx=3)
        # Spacer to keep Server Stats to the right of type chips, wide enough for two longest type labels + 4 chars
        try:
            _mat = load_type_matchup_matrix()
            _max_label = max((len(k.title()) for k in _mat.keys()), default=8)
        except Exception:
            _max_label = 8
        # Reduced spacing now that types occupy a dedicated frame
        _spacer_chars = max(0, _max_label + 6)
        self._hdr_spacer = tk.Label(hdr, text="", width=_spacer_chars)
        self._hdr_spacer.pack(side=tk.LEFT)
        # Server stats (header row, after types)
        ttk.Label(hdr, text="Server Stats:").pack(side=tk.LEFT, padx=(12, 4))
        self.server_stats_var = tk.StringVar(value="-")
        ttk.Label(hdr, textvariable=self.server_stats_var).pack(side=tk.LEFT)
        # Basics box (compact square): Nickname, Current HP, Level, EXP, Growth Rate, Friendship, EXP note
        basics_box = ttk.LabelFrame(frm, text="Basics")
        basics_box.grid(row=1, column=0, columnspan=3, sticky=tk.EW, padx=4, pady=(4, 6))
        # Nickname
        ttk.Label(basics_box, text="Nickname:").grid(row=0, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_name = tk.StringVar(value="")
        ttk.Entry(basics_box, textvariable=self.var_name, width=18).grid(row=0, column=1, sticky=tk.W)
        # Current HP
        ttk.Label(basics_box, text="Current HP:").grid(row=0, column=2, sticky=tk.E, padx=8, pady=3)
        self.var_hp = tk.StringVar(value="")
        ttk.Entry(basics_box, textvariable=self.var_hp, width=8).grid(row=0, column=3, sticky=tk.W)
        # Level
        ttk.Label(basics_box, text="Level:").grid(row=1, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_level = tk.StringVar(value="")
        self.ent_level = ttk.Entry(basics_box, textvariable=self.var_level, width=8)
        self.ent_level.grid(row=1, column=1, sticky=tk.W)
        # EXP
        ttk.Label(basics_box, text="EXP:").grid(row=1, column=2, sticky=tk.E, padx=8, pady=3)
        self.var_exp = tk.StringVar(value="")
        self.ent_exp = ttk.Entry(basics_box, textvariable=self.var_exp, width=12)
        self.ent_exp.grid(row=1, column=3, sticky=tk.W)
        # Growth Rate
        ttk.Label(basics_box, text="Growth Rate:").grid(row=2, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_growth = tk.StringVar(value="-")
        ttk.Label(basics_box, textvariable=self.var_growth).grid(row=2, column=1, sticky=tk.W)
        # Friendship inside basics
        ttk.Label(basics_box, text="Friendship:").grid(row=2, column=2, sticky=tk.E, padx=8, pady=3)
        self.var_friend = tk.StringVar(value="")
        ttk.Entry(basics_box, textvariable=self.var_friend, width=8).grid(row=2, column=3, sticky=tk.W)
        # Note: EXP and Level changes are handled by the comprehensive field binding system
        # EXP note inside basics
        self.exp_note = ttk.Label(basics_box, text="Note: Levels beyond 100 use last EXP step (supports 200+)", foreground="gray")
        self.exp_note.grid(row=3, column=0, columnspan=4, sticky=tk.W, padx=4, pady=(2,0))

        # Actions box next to basics: Held items and Full Restore
        actions_box = ttk.LabelFrame(frm, text="Actions")
        actions_box.grid(row=1, column=3, sticky=tk.NW, padx=(0,4), pady=(4,6))
        ttk.Button(actions_box, text="Manage Held Items…", command=self._open_item_mgr).grid(row=0, column=0, padx=6, pady=(6,4), sticky=tk.EW)
        ttk.Button(actions_box, text="Full Restore", command=self._full_restore_current).grid(row=1, column=0, padx=6, pady=(0,6), sticky=tk.EW)
        try:
            actions_box.grid_columnconfigure(0, weight=1)
        except Exception:
            pass

        # Continue with remaining fields below
        r = 2

        # Status and Ability sections side-by-side under basics/actions
        row2 = ttk.Frame(frm)
        row2.grid(row=2, column=0, columnspan=4, sticky=tk.EW, padx=4, pady=2)
        try:
            row2.grid_columnconfigure(0, weight=1)
            row2.grid_columnconfigure(1, weight=1)
        except Exception:
            pass
        statf = ttk.LabelFrame(row2, text="Status")
        statf.grid(row=0, column=0, sticky=tk.NSEW, padx=(0,4))
        ttk.Label(statf, text="Primary:").grid(row=0, column=0, sticky=tk.E, padx=4, pady=2)
        self.var_status = tk.StringVar(value="")
        self.cb_status = ttk.Combobox(statf, textvariable=self.var_status, values=["none", "psn", "tox", "brn", "par", "slp", "frz"], width=10, state="readonly")
        self.cb_status.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(statf, text="Clear", command=lambda: self.cb_status.set("none")).grid(row=0, column=2, padx=4)
        # Status-specific single field (label changes by status)
        self.status_detail_label = ttk.Label(statf, text="")
        self.status_detail_label.grid(row=1, column=0, sticky=tk.E, padx=4)
        self.status_detail_var = tk.StringVar(value="")
        self.status_detail_entry = ttk.Entry(statf, textvariable=self.status_detail_var, width=10)
        self.status_detail_entry.grid(row=1, column=1, sticky=tk.W)
        # Summary label
        self.status_summary = ttk.Label(statf, text="Status: None", foreground="green")
        self.status_summary.grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=4, pady=(2, 4))
        # Volatile statuses hidden (battle-only, not persisted)

        # Ability + passives
        af = ttk.LabelFrame(row2, text="Ability & Passives")
        af.grid(row=0, column=1, sticky=tk.NSEW, padx=(4,0))
        # Keep controls clustered; avoid stretching column 1 that causes gaps between radios
        # If needed, allow right side to expand from a higher column
        af.grid_columnconfigure(4, weight=1)
        # Keep backing variable for potential future use, but do not show UI
        self.var_ability = tk.StringVar(value="")
        # Passive enabled checkbox (visible)
        self.var_passive = tk.BooleanVar(value=False)
        ttk.Checkbutton(af, text="Passive enabled", variable=self.var_passive).grid(row=0, column=0, sticky=tk.W, padx=4)
        # Ability slot radio (1/2/Hidden)
        ttk.Label(af, text="Ability slot:").grid(row=1, column=0, sticky=tk.E, padx=4)
        self.ability_slot_var = tk.StringVar(value="")
        def _slot_radio(val):
            return ttk.Radiobutton(af, text=val, value=val, variable=self.ability_slot_var, command=self._on_ability_slot_change)
        _slot_radio("1").grid(row=1, column=1, sticky=tk.W)
        _slot_radio("2").grid(row=1, column=2, sticky=tk.W)
        _slot_radio("Hidden").grid(row=1, column=3, sticky=tk.W)
        self.ability_warn = ttk.Label(af, text="", foreground="red")
        self.ability_warn.grid(row=2, column=1, columnspan=3, sticky=tk.W)

        # Pokérus toggle moved to Actions box
        self.var_pokerus = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions_box, text="Pokérus: Infected", variable=self.var_pokerus).grid(row=2, column=0, padx=6, pady=(0,6), sticky=tk.W)

        # Note: Changes are automatically applied to memory as you edit
        # Use "Save to file" to persist changes to disk
        # Heal helpers (moved Full Restore to Actions box)
        heal_bar = ttk.Frame(frm)
        heal_bar.grid(row=8, column=2, columnspan=2, sticky=tk.W)
        # Note: Status changes are handled by the comprehensive field binding system

    def _update_status_fields_visibility(self):
        st = (self.var_status.get() or 'none').strip().lower()
        def show(widget, visible):
            try:
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()
            except Exception:
                pass
        if st == 'slp':
            self.status_detail_label.configure(text="Sleep turns remaining:")
            show(self.status_detail_label, True)
            show(self.status_detail_entry, True)
        elif st == 'tox':
            self.status_detail_label.configure(text="Toxic turns:")
            show(self.status_detail_label, True)
            show(self.status_detail_entry, True)
        else:
            show(self.status_detail_label, False)
            show(self.status_detail_entry, False)

    def _update_status_summary(self):
        st = (self.var_status.get() or 'none').strip().lower()
        if st == 'none' or not st:
            try:
                self.status_summary.configure(text='Status: None', foreground='green')
            except Exception:
                pass
            return
        label_map = {
            'psn': 'Poisoned', 'tox': 'Badly Poisoned', 'brn': 'Burned', 'par': 'Paralyzed', 'slp': 'Asleep', 'frz': 'Frozen'
        }
        parts = ['Status:', label_map.get(st, st.upper())]
        try:
            if st in ('slp','tox'):
                parts.append(f"({(self.status_detail_var.get() or '0').strip()} turns)")
        except Exception:
            pass
        try:
            self.status_summary.configure(text=' '.join(parts), foreground='')
        except Exception:
            pass

        # Pokemon Reordering Section (moved to party list context menu elsewhere)

    def _move_pokemon_up(self):
        """Move currently selected Pokemon up one position in the party."""
        try:
            current_idx = int(self.party_list.curselection()[0])
            if current_idx > 0 and self.party:
                # Swap with previous Pokemon
                self.party[current_idx], self.party[current_idx - 1] = self.party[current_idx - 1], self.party[current_idx]
                self._refresh_party()
                # Maintain selection on the moved Pokemon
                self._set_party_selection(current_idx - 1, render=True)
        except Exception:
            pass

    def _move_pokemon_down(self):
        """Move currently selected Pokemon down one position in the party."""
        try:
            current_idx = int(self.party_list.curselection()[0])
            if current_idx < len(self.party) - 1 and self.party:
                # Swap with next Pokemon
                self.party[current_idx], self.party[current_idx + 1] = self.party[current_idx + 1], self.party[current_idx]
                self._refresh_party()
                # Maintain selection on the moved Pokemon
                self._set_party_selection(current_idx + 1, render=True)
        except Exception:
            pass

    def _move_pokemon_to_start(self):
        """Move currently selected Pokemon to the beginning of the party."""
        try:
            current_idx = int(self.party_list.curselection()[0])
            if current_idx > 0 and self.party:
                # Move Pokemon to start
                pokemon = self.party.pop(current_idx)
                self.party.insert(0, pokemon)
                self._refresh_party()
                # Maintain selection on the moved Pokemon
                self._set_party_selection(0, render=True)
        except Exception:
            pass

    def _move_pokemon_to_end(self):
        """Move currently selected Pokemon to the end of the party."""
        try:
            current_idx = int(self.party_list.curselection()[0])
            if current_idx < len(self.party) - 1 and self.party:
                # Move Pokemon to end
                pokemon = self.party.pop(current_idx)
                self.party.append(pokemon)
                self._refresh_party()
                # Maintain selection on the moved Pokemon
                new_idx = len(self.party) - 1
                self._set_party_selection(new_idx, render=True)
        except Exception:
            pass

    def _build_party_reorder_section(self, parent: ttk.Frame):
        """Build party reordering section with immediate UI feedback."""
        reorder_frame = ttk.LabelFrame(parent, text="Party Order")
        reorder_frame.grid(row=0, column=0, columnspan=4, sticky=tk.EW, padx=6, pady=(4, 8))

        # Instructions and Apply button header
        header_frame = ttk.Frame(reorder_frame)
        header_frame.pack(fill=tk.X, padx=6, pady=(4, 2))

        info_label = ttk.Label(header_frame,
                              text="Reorder party members by clicking arrows. Changes are automatically applied to memory.",
                              foreground="gray")
        info_label.pack(side=tk.LEFT, anchor=tk.W)

        # Status indicator
        self.party_status_label = ttk.Label(header_frame, text="", foreground="orange")
        self.party_status_label.pack(side=tk.RIGHT, padx=(0, 10))

        # Party member list with reorder controls
        self.party_reorder_frame = ttk.Frame(reorder_frame)
        self.party_reorder_frame.pack(fill=tk.X, padx=6, pady=(2, 6))

        # Track original party order for comparison
        self._original_party_order = None
        self._pending_party_changes = False

        # Create skeleton loading for party order section
        self._create_party_order_skeleton()

        # Defer initial population to avoid blocking UI
        self.after_idle(self._refresh_party_order_section_safe)

    def _create_party_order_skeleton(self):
        """Create skeleton loading placeholders for party order section."""
        try:
            # Clear any existing content
            for widget in self.party_reorder_frame.winfo_children():
                widget.destroy()
            
            # Create skeleton entries for up to 6 party members
            for i in range(6):
                skeleton_frame = ttk.Frame(self.party_reorder_frame)
                skeleton_frame.pack(fill=tk.X, pady=2)
                
                # Position indicator skeleton
                pos_skeleton = ttk.Label(skeleton_frame, text=f"{i+1}.", width=3, 
                                       font=("TkDefaultFont", 9, "bold"), 
                                       foreground="gray")
                pos_skeleton.pack(side=tk.LEFT)
                
                # Pokemon info skeleton
                info_skeleton = ttk.Label(skeleton_frame, text="Loading Pokemon data...", 
                                        foreground="gray", font=("TkDefaultFont", 9))
                info_skeleton.pack(side=tk.LEFT, padx=(4, 0))
                
                # Store reference for replacement
                setattr(skeleton_frame, '_is_skeleton', True)
                
        except Exception as e:
            debug_log(f"Error creating party order skeleton: {e}")

    def _refresh_party_order_section_safe(self):
        """Safe, non-blocking version of party order section refresh."""
        try:
            # Show loading indicator
            self._show_loading_indicator("Loading party order...")
            
            # Defer the heavy work
            self.after_idle(self._do_refresh_party_order_section)
            
        except Exception as e:
            debug_log(f"Error in safe party order refresh: {e}")
            self._hide_loading_indicator()

    def _do_refresh_party_order_section(self):
        """Perform the actual party order section refresh work."""
        try:
            # Store original order if not already stored
            if self._original_party_order is None and hasattr(self, 'party') and self.party:
                self._original_party_order = [mon.copy() if mon else None for mon in self.party]

            # Clear existing widgets (including skeletons)
            for widget in self.party_reorder_frame.winfo_children():
                widget.destroy()

            if not hasattr(self, 'party') or not self.party:
                ttk.Label(self.party_reorder_frame, text="No party data loaded",
                         foreground="gray").pack(anchor=tk.W)
                self._hide_loading_indicator()
                return

            # Create a row for each party member
            for i, mon in enumerate(self.party):
                if not mon:  # Skip empty slots
                    continue

                row_frame = ttk.Frame(self.party_reorder_frame)
                row_frame.pack(fill=tk.X, pady=2)

                # Position indicator with better styling
                pos_label = ttk.Label(row_frame, text=f"{i+1}.", width=3, font=("TkDefaultFont", 9, "bold"))
                pos_label.pack(side=tk.LEFT)

                # Pokemon detailed info
                species_id = mon.get("species", 0)
                species_name = self._get_species_name(species_id)
                level = mon.get("level", 1)
                nickname = mon.get("nickname", "").strip()

                # Create detailed display with Pokemon name and level
                if nickname:
                    display_text = f"{nickname} ({species_name}) - Lv.{level}"
                else:
                    display_text = f"{species_name} - Lv.{level}"

                # Pokemon info with better formatting
                info_frame = ttk.Frame(row_frame)
                info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

                name_label = ttk.Label(info_frame, text=display_text, anchor=tk.W,
                                      font=("TkDefaultFont", 9))
                name_label.pack(anchor=tk.W)

                # Show type information if available
                try:
                    types = self._get_cached_species_types(species_id, self._detect_form_slug(mon))
                    if types and types[0]:
                        type_text = types[0]
                        if types[1]:
                            type_text += f" / {types[1]}"
                        type_label = ttk.Label(info_frame, text=type_text, 
                                             foreground="gray", font=("TkDefaultFont", 8))
                        type_label.pack(anchor=tk.W)
                except Exception:
                    pass

                # Reorder controls
                controls_frame = ttk.Frame(row_frame)
                controls_frame.pack(side=tk.RIGHT, padx=(4, 0))

                # Up button
                up_btn = ttk.Button(controls_frame, text="↑", width=3,
                                  command=lambda idx=i: self._move_party_member_up(idx))
                up_btn.pack(side=tk.LEFT, padx=(0, 2))

                # Down button
                down_btn = ttk.Button(controls_frame, text="↓", width=3,
                                    command=lambda idx=i: self._move_party_member_down(idx))
                down_btn.pack(side=tk.LEFT)

            # Hide loading indicator
            self._hide_loading_indicator()
            
        except Exception as e:
            debug_log(f"Error in party order refresh work: {e}")
            self._hide_loading_indicator()

    def _refresh_party_order_section(self):
        """Refresh the party reordering section with current party data."""
        # Store original order if not already stored
        if self._original_party_order is None and hasattr(self, 'party') and self.party:
            self._original_party_order = [mon.copy() if mon else None for mon in self.party]

        # Clear existing widgets
        for widget in self.party_reorder_frame.winfo_children():
            widget.destroy()

        if not hasattr(self, 'party') or not self.party:
            ttk.Label(self.party_reorder_frame, text="No party data loaded",
                     foreground="gray").pack(anchor=tk.W)
            return

        # Create a row for each party member
        for i, mon in enumerate(self.party):
            if not mon:  # Skip empty slots
                continue

            row_frame = ttk.Frame(self.party_reorder_frame)
            row_frame.pack(fill=tk.X, pady=2)

            # Position indicator with better styling
            pos_label = ttk.Label(row_frame, text=f"{i+1}.", width=3, font=("TkDefaultFont", 9, "bold"))
            pos_label.pack(side=tk.LEFT)

            # Pokemon detailed info
            species_id = mon.get("species", 0)
            species_name = self._get_species_name(species_id)
            level = mon.get("level", 1)
            nickname = mon.get("nickname", "").strip()

            # Create detailed display with Pokemon name and level
            if nickname:
                display_text = f"{nickname} ({species_name}) - Lv.{level}"
            else:
                display_text = f"{species_name} - Lv.{level}"

            # Pokemon info with better formatting
            info_frame = ttk.Frame(row_frame)
            info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

            name_label = ttk.Label(info_frame, text=display_text, anchor=tk.W,
                                  font=("TkDefaultFont", 9))
            name_label.pack(anchor=tk.W)

            # Show type information if available
            try:
                catalog = self._get_cached_pokemon_catalog() or {}
                entry = catalog.get("by_dex", {}).get(str(species_id), {})
                types = entry.get("types", {})
                type1 = types.get("type1", "").title()
                type2 = types.get("type2", "").title()
                type_text = type1
                if type2 and type2 != type1:
                    type_text += f"/{type2}"
                if type_text:
                    type_label = ttk.Label(info_frame, text=f"Type: {type_text}",
                                          foreground="gray", font=("TkDefaultFont", 8))
                    type_label.pack(anchor=tk.W)
            except Exception:
                pass

            # Reorder buttons with better spacing
            button_frame = ttk.Frame(row_frame)
            button_frame.pack(side=tk.RIGHT, padx=(10, 0))

            # Up button (disabled for first item)
            up_btn = ttk.Button(button_frame, text="↑", width=3,
                               command=lambda idx=i: self._move_party_member_up(idx))
            if i == 0:
                up_btn.configure(state=tk.DISABLED)
            up_btn.pack(side=tk.LEFT, padx=1)

            # Down button (disabled for last item)
            down_btn = ttk.Button(button_frame, text="↓", width=3,
                                 command=lambda idx=i: self._move_party_member_down(idx))
            if i == len([m for m in self.party if m]) - 1:
                down_btn.configure(state=tk.DISABLED)
            down_btn.pack(side=tk.LEFT, padx=1)

            # To start button
            start_btn = ttk.Button(button_frame, text="⇈", width=3,
                                  command=lambda idx=i: self._move_party_member_to_start(idx))
            if i == 0:
                start_btn.configure(state=tk.DISABLED)
            start_btn.pack(side=tk.LEFT, padx=1)

            # To end button
            end_btn = ttk.Button(button_frame, text="⇊", width=3,
                                command=lambda idx=i: self._move_party_member_to_end(idx))
            if i == len([m for m in self.party if m]) - 1:
                end_btn.configure(state=tk.DISABLED)
            end_btn.pack(side=tk.LEFT, padx=1)

        # Update apply button state
        self._update_party_apply_button_state()

    def _get_species_name(self, species_id: int) -> str:
        """Get species name from catalog."""
        try:
            catalog = self._get_cached_pokemon_catalog() or {}
            entry = (catalog.get("by_dex") or {}).get(str(species_id), {})
            return entry.get("name", f"Species#{species_id}")
        except Exception:
            return f"Species#{species_id}"

    def _move_party_member_up(self, index: int):
        """Move party member up one position."""
        if index <= 0:
            return
        self._swap_party_members(index, index - 1)

    def _move_party_member_down(self, index: int):
        """Move party member down one position."""
        valid_members = [i for i, m in enumerate(self.party) if m]
        if index >= len(valid_members) - 1:
            return
        self._swap_party_members(index, index + 1)

    def _move_party_member_to_start(self, index: int):
        """Move party member to first position."""
        if index <= 0:
            return

        member = self.party[index]
        self.party.pop(index)
        self.party.insert(0, member)
        self._after_party_reorder()

    def _move_party_member_to_end(self, index: int):
        """Move party member to last position."""
        valid_members = [i for i, m in enumerate(self.party) if m]
        if index >= len(valid_members) - 1:
            return

        member = self.party[index]
        self.party.pop(index)
        # Find the last valid position
        last_valid_idx = max(valid_members)
        self.party.insert(last_valid_idx, member)
        self._after_party_reorder()

    def _swap_party_members(self, idx1: int, idx2: int):
        """Swap two party members."""
        if idx1 < 0 or idx2 < 0 or idx1 >= len(self.party) or idx2 >= len(self.party):
            return

        self.party[idx1], self.party[idx2] = self.party[idx2], self.party[idx1]
        self._after_party_reorder()

    def _create_party_reorder_backup(self):
        """Create automatic backup before party reordering."""
        try:
            from rogueeditor.enhanced_backup import create_enhanced_backup_manager
            from rogueeditor.utils import user_save_dir
            import os

            # Get current username (from API if available)
            username = getattr(self.api, 'username', 'default')

            # Create backup manager
            backup_manager = create_enhanced_backup_manager(username)

            # Files to backup (slot data)
            save_dir = user_save_dir(username)
            slot_file = os.path.join(save_dir, f"slot {self.slot}.json")

            files_to_backup = []
            if os.path.exists(slot_file):
                files_to_backup.append(slot_file)

            if files_to_backup:
                # Create backup with descriptive operation type
                backup_id = backup_manager.create_operation_backup(
                    operation_type="party_reorder",
                    description=f"Automatic backup before party reordering in slot {self.slot}",
                    files_to_backup=files_to_backup,
                    session_info={"slot": self.slot, "party_size": len([m for m in self.party if m])}
                )
                return backup_id
            return None
        except Exception as e:
            # Log error but don't stop the operation
            print(f"Warning: Could not create backup before party reordering: {e}")
            return None

    def _after_party_reorder(self):
        """Handle actions after party reordering (immediate UI update only)."""
        # Mark pending changes
        self._pending_party_changes = True

        # Refresh the reorder section (immediate visual feedback)
        self._refresh_party_order_section()

        # Refresh the party list (immediate visual feedback)
        self._refresh_party()

        # Update status
        self.party_status_label.configure(text="Unsaved changes", foreground="orange")

    def _update_party_apply_button_state(self):
        """Update apply button state based on whether changes exist."""
        if hasattr(self, 'party_apply_btn') and hasattr(self, '_original_party_order'):
            if self._party_order_changed():
                self.party_apply_btn.configure(state=tk.NORMAL)
                self.party_status_label.configure(text="Unsaved changes", foreground="orange")
            else:
                self.party_apply_btn.configure(state=tk.DISABLED)
                self.party_status_label.configure(text="", foreground="gray")

    def _party_order_changed(self) -> bool:
        """Check if party order has changed from original."""
        if not self._original_party_order or not hasattr(self, 'party'):
            return False

        # Compare current party with original
        if len(self.party) != len(self._original_party_order):
            return True

        for i, (current, original) in enumerate(zip(self.party, self._original_party_order)):
            if not current and not original:
                continue
            if not current or not original:
                return True
            # Compare species ID as the primary identifier
            if current.get("species") != original.get("species"):
                return True

        return False

    def _apply_party_reorder_changes(self):
        """Apply party reorder changes with backup and cache invalidation."""
        if not self._pending_party_changes:
            return

        try:
            # Create backup before first reordering operation in this session
            if not self._party_reorder_backup_created:
                backup_id = self._create_party_reorder_backup()
                if backup_id:
                    self._party_reorder_backup_created = True
                    print(f"Created backup {backup_id} before party reordering")

            # Mark as dirty for save
            self.needs_save = True

            # Reset tracking variables
            self._pending_party_changes = False
            self._original_party_order = [mon.copy() if mon else None for mon in self.party]

            # Update UI status
            self.party_status_label.configure(text="Changes applied", foreground="green")
            self.party_apply_btn.configure(state=tk.DISABLED)

            # Invalidate cache for this user/slot
            try:
                username = getattr(self.api, 'username', 'default')
                invalidate_team_analysis_cache(username, self.slot)
                print(f"Invalidated team analysis cache for {username}, slot {self.slot}")
            except Exception as e:
                print(f"Warning: Could not invalidate cache: {e}")

            # Show success feedback
            try:
                import tkinter.messagebox as messagebox
                messagebox.showinfo("Party Reordered",
                                  "Party order changes applied to local data. Remember to save and upload to sync with server.")
            except Exception:
                pass

        except Exception as e:
            print(f"Error applying party reorder changes: {e}")
            self.party_status_label.configure(text="Error applying changes", foreground="red")

    def _build_stats(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Base stats + IVs
        self.base_labels: List[ttk.Label] = []
        self.calc_labels: List[ttk.Label] = []
        self.item_labels: List[ttk.Label] = []
        labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
        self.iv_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(6)]
        ttk.Label(frm, text="Base").grid(row=0, column=1)
        ttk.Label(frm, text="IV").grid(row=0, column=2)
        ttk.Label(frm, text="Calc").grid(row=0, column=3)
        ttk.Label(frm, text="Item Boost").grid(row=0, column=4)
        # Note about base stats source
        self.base_source_note = ttk.Label(frm, text="Base stats: catalog", foreground="gray")
        self.base_source_note.grid(row=0, column=5, sticky=tk.W)
        for i, name in enumerate(labels, start=1):
            ttk.Label(frm, text=name + ":").grid(row=i, column=0, sticky=tk.E, padx=4, pady=2)
            bl = ttk.Label(frm, text="-")
            bl.grid(row=i, column=1)
            self.base_labels.append(bl)
            ent = ttk.Entry(frm, textvariable=self.iv_vars[i - 1], width=6)
            ent.grid(row=i, column=2)
            cl = ttk.Label(frm, text="-")
            cl.grid(row=i, column=3)
            self.calc_labels.append(cl)
            il = ttk.Label(frm, text="")
            il.grid(row=i, column=4)
            self.item_labels.append(il)

        ttk.Label(frm, text="Nature:").grid(row=7, column=0, sticky=tk.E, padx=4, pady=6)
        self.var_nature = tk.StringVar(value="")
        self.ent_nature = ttk.Entry(frm, textvariable=self.var_nature, width=18)
        self.ent_nature.grid(row=7, column=1, sticky=tk.W)
        ttk.Button(frm, text="Pick…", command=self._pick_nature).grid(row=7, column=2, sticky=tk.W, padx=4)
        # Note: Changes are automatically applied to memory as you edit
        # Nature hint (neutral or +/- targets)
        self.nature_hint = ttk.Label(frm, text="", foreground="gray")
        self.nature_hint.grid(row=8, column=1, columnspan=3, sticky=tk.W)
        # Bind live recalc on changes
        # Note: Stats recalculation is handled by the comprehensive field binding system

    def _build_moves(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Header row
        headers = [
            ("#", 0), ("Type", 1), ("Cat.", 2), ("Move", 3), ("Max PP", 5),
            ("PP Up", 6), ("PP Used", 7), ("Acc.", 8), ("Effect", 9)
        ]
        for text, col in headers:
            ttk.Label(frm, text=text).grid(row=0, column=col, sticky=tk.W, padx=4, pady=(2, 6))

        self.move_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(4)]
        self.move_ppup_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(4)]
        self.move_ppused_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(4)]
        # Per-row visuals: type chip, category icon, max pp, acc, effect
        self._move_type_labels: List[tk.Label] = []
        self._move_cat_labels: List[tk.Label] = []
        self._move_maxpp_labels: List[tk.Label] = []
        self._move_acc_labels: List[tk.Label] = []
        self._move_effect_labels: List[tk.Label] = []
        self._move_cat_images: List[object] = [None, None, None, None]
        for i in range(4):
            r = i + 1
            # Index
            ttk.Label(frm, text=str(i+1)).grid(row=r, column=0, sticky=tk.W, padx=6)
            # Type chip
            type_lbl = tk.Label(frm, text="", bg="#DDDDDD", bd=1, relief=tk.SOLID, padx=6, pady=2)
            type_lbl.grid(row=r, column=1, sticky=tk.W, padx=(4, 2))
            self._move_type_labels.append(type_lbl)
            # Category icon
            cat_lbl = tk.Label(frm, text="", bd=0)
            cat_lbl.grid(row=r, column=2, sticky=tk.W, padx=(2, 2))
            self._move_cat_labels.append(cat_lbl)
            # Move entry + pick
            ent = ttk.Entry(frm, textvariable=self.move_vars[i], width=24)
            ent.grid(row=r, column=3, sticky=tk.W)
            ttk.Button(frm, text="Pick…", width=6, command=lambda idx=i: self._pick_move(idx)).grid(row=r, column=4, sticky=tk.W, padx=(4, 4))
            # Max PP label
            maxpp = ttk.Label(frm, text="-")
            maxpp.grid(row=r, column=5, sticky=tk.W, padx=(6, 2))
            self._move_maxpp_labels.append(maxpp)
            # PP Up (editable)
            up_entry = ttk.Entry(frm, textvariable=self.move_ppup_vars[i], width=5)
            up_entry.grid(row=r, column=6, sticky=tk.W)
            # PP Used (editable)
            used_entry = ttk.Entry(frm, textvariable=self.move_ppused_vars[i], width=6)
            used_entry.grid(row=r, column=7, sticky=tk.W)
            # Accuracy label
            accl = ttk.Label(frm, text="-")
            accl.grid(row=r, column=8, sticky=tk.W, padx=(6, 2))
            self._move_acc_labels.append(accl)
            # Effect label
            effl = ttk.Label(frm, text="", foreground="gray")
            effl.grid(row=r, column=9, sticky=tk.W, padx=(6, 0))
            self._move_effect_labels.append(effl)
            # Validate PP fields on focus-out only (allow free typing/blank while focused)
            def _bind_pp_validation(idx: int, widget: tk.Widget):
                try:
                    widget.bind('<FocusOut>', lambda e: self._validate_pp_fields(idx))
                except Exception:
                    pass
            _bind_pp_validation(i, up_entry)
            _bind_pp_validation(i, used_entry)
            # Live preview traces (no clamping) to refresh Max PP display while typing
            def _make_live(idx: int):
                return lambda *args: self._update_move_row_visuals(idx, self._parse_id_from_combo(self.move_vars[idx].get(), self.move_n2i) or 0)
            try:
                self.move_ppup_vars[i].trace_add('write', _make_live(i))
                self.move_ppused_vars[i].trace_add('write', _make_live(i))
            except Exception:
                pass
        # Note for PP fields
        ttk.Label(frm, text="PP Up max: 3 per 5 base PP; PP Used clamped to max.", foreground="gray").grid(row=6, column=0, columnspan=10, sticky=tk.W, padx=4, pady=(8,0))
        # Note: Changes are automatically applied to memory as you edit

    def _update_move_row_visuals(self, row_index: int, move_id: int) -> None:
        try:
            if not (0 <= row_index < 4):
                return
            # Type chip
            tname = get_move_type_name(move_id) or ""
            chip = self._move_type_labels[row_index]
            if tname:
                chip.configure(text=str(tname).title(), bg=self._color_for_type(str(tname)))
            else:
                chip.configure(text="", bg="#DDDDDD")
            # Category icon
            entry = get_move_entry(move_id) or {}
            cat = str(entry.get("move_category") or "").strip().lower()
            icon_path = None
            if cat == "physical":
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-physical.png")
            elif cat == "special":
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-special.png")
            elif cat == "status":
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-status.png")
            elif cat == "z-move" or cat == "z-move".replace('-', '_'):
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-zmove.png")
            elif cat == "dynamax" or cat == "max" or "max" in cat:
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-dynamax.png")
            # G-Max keyword in label
            if not icon_path and ("g-max" in (entry.get("ui_label") or "").lower() or "gmax" in (entry.get("ui_label") or "").lower()):
                icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "thumbnails", "Moves", "move-gmax.png")
            try:
                if icon_path and os.path.exists(icon_path):
                    img = tk.PhotoImage(file=icon_path)
                    self._move_cat_images[row_index] = img
                    self._move_cat_labels[row_index].configure(image=img, text="")
                else:
                    self._move_cat_labels[row_index].configure(image="", text="")
            except Exception:
                self._move_cat_labels[row_index].configure(image="", text="")
            # Details / columns
            base_pp = get_move_base_pp(move_id)
            max_extra, max_total = compute_ppup_bounds(base_pp)
            acc = entry.get("accuracy")
            acc_txt = "—" if acc is None else f"{int(acc)}%"
            effect_txt = str(entry.get("effect") or "").strip()
            sec_chance = entry.get("secondary_effect_chance")
            if effect_txt:
                if isinstance(sec_chance, (int, float)):
                    effect_txt = f"{effect_txt} ({int(sec_chance)}%)"
            # Current max with PP Up entered
            # Read PP Up (do not clamp here during typing; clamp in focus-out validator)
            try:
                pp_up_in = int((self.move_ppup_vars[row_index].get() or '0').strip() or '0')
            except Exception:
                pp_up_in = 0
            # Compute current max
            if base_pp is not None:
                cur_max = max(0, (base_pp or 0) + (pp_up_in or 0))
            else:
                cur_max = 0
            # Read PP Used (no clamp during typing)
            try:
                pp_used_in = int((self.move_ppused_vars[row_index].get() or '0').strip() or '0')
            except Exception:
                pp_used_in = 0
            # Compute available = cur_max - used
            if base_pp is not None:
                available = cur_max - pp_used_in
                if available < 0:
                    available = 0
                if available > cur_max:
                    available = cur_max
                pp_txt = f"{available}/{cur_max}"
            else:
                pp_txt = "—"
            # Assign to dedicated columns
            try:
                self._move_maxpp_labels[row_index].configure(text=pp_txt)
            except Exception:
                pass
            try:
                self._move_acc_labels[row_index].configure(text=acc_txt)
            except Exception:
                pass
            try:
                self._move_effect_labels[row_index].configure(text=effect_txt)
            except Exception:
                pass
        except Exception:
            pass

    def _validate_pp_fields(self, row_index: int) -> None:
        try:
            if not (0 <= row_index < 4):
                return
            # Resolve move id
            mid = self._parse_id_from_combo(self.move_vars[row_index].get(), self.move_n2i) or 0
            base_pp = get_move_base_pp(int(mid))
            max_extra, _ = compute_ppup_bounds(base_pp)
            # Validate PP Up
            try:
                raw_up = (self.move_ppup_vars[row_index].get() or '').strip()
                pp_up_in = int(raw_up) if raw_up != '' else 0
            except Exception:
                pp_up_in = 0
            if pp_up_in < 0:
                pp_up_in = 0
            if base_pp is not None and pp_up_in > max_extra:
                pp_up_in = max_extra
            self.move_ppup_vars[row_index].set(str(pp_up_in))
            # Compute max with clamped PP Up
            cur_max = (base_pp or 0) + (pp_up_in or 0) if base_pp is not None else 0
            # Validate PP Used
            try:
                raw_used = (self.move_ppused_vars[row_index].get() or '').strip()
                pp_used_in = int(raw_used) if raw_used != '' else 0
            except Exception:
                pp_used_in = 0
            if pp_used_in < 0:
                pp_used_in = 0
            if base_pp is not None and pp_used_in > cur_max:
                pp_used_in = cur_max
            self.move_ppused_vars[row_index].set(str(pp_used_in))
            # Refresh visuals to update Max PP column
            self._update_move_row_visuals(row_index, int(mid))
        except Exception:
            pass

    def _build_matchups(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Note about scope
        ttk.Label(frm, text="Defensive matchup. Ignores abilities, passives, held items, and special forms like Mega/Tera.", foreground="gray").grid(row=0, column=0, sticky=tk.W, padx=6, pady=(4,2))
        # Initialize caches (will be loaded asynchronously)
        self._type_matrix = {}
        self._type_colors = {}
        self._matchup_cache = {}

        # Sections for bins (vertically stacked)
        sections = [
            ("Immune (x0)", "immune"),
            ("x0.25", "x0_25"),
            ("x0.5", "x0_5"),
            ("x1", "x1"),
            ("x2", "x2"),
            ("x4", "x4"),
        ]
        self._matchup_bins = {}
        self._matchup_section_frames = {}
        for i, (title, key) in enumerate(sections):
            lf = ttk.LabelFrame(frm, text=title)
            lf.grid(row=i+1, column=0, sticky=tk.NSEW, padx=6, pady=6)
            inner = ttk.Frame(lf)
            inner.pack(fill=tk.BOTH, expand=True)
            self._matchup_bins[key] = inner
            self._matchup_section_frames[key] = lf
        frm.grid_columnconfigure(0, weight=1)

    def _set_matchup_sections_for_mon(self, mon: dict):
        try:
            # Determine if mon has dual types
            species_id = _get_species_id(mon)
            t1, t2 = self._get_cached_species_types(species_id, self._detect_form_slug(mon))
            dual = bool(t2)
            # If single-type, hide 0.25 and 4x sections entirely
            for key in ("x0_25", "x4"):
                lf = self._matchup_section_frames.get(key)
                if not lf:
                    continue
                if dual:
                    try:
                        lf.grid()  # ensure visible
                    except Exception:
                        pass
                else:
                    try:
                        lf.grid_remove()
                    except Exception:
                        pass
        except Exception:
            pass

    def _build_offensive_coverage(self, parent: ttk.Frame):
        """Build the offensive Matchups analysis tab."""
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Description
        desc_frame = ttk.Frame(frm)
        desc_frame.pack(fill=tk.X, pady=(0, 10))
        # Tips (left) + Recalculate (right) on same row
        tips = ttk.Frame(desc_frame)
        tips.pack(fill=tk.X)
        tips_left = ttk.Frame(tips)
        tips_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(tips_left, text="Offensive type coverage analysis based on damaging moves.", foreground="gray").pack(anchor=tk.W)
        ttk.Label(tips_left, text="Coverage refreshes automatically when moves change.", foreground="gray").pack(anchor=tk.W)
        ttk.Label(tips_left, text="Note: Mega Rayquaza's Delta Stream ability neutralizes Flying-type weaknesses.", foreground="orange").pack(anchor=tk.W)
        tips_right = ttk.Frame(tips)
        tips_right.pack(side=tk.RIGHT)
        ttk.Button(tips_right, text="Recalculate", command=self._force_recalc_coverage).pack(side=tk.RIGHT)

        # Local coverage cache: mon_key -> { 'sig': tuple(move_ids), 'coverage': dict }
        self._mon_coverage_cache: dict = {}

        # Current moves section (compact, non-scrollable)
        moves_frame = ttk.LabelFrame(frm, text="Current Damaging Moves")
        moves_frame.pack(fill=tk.X, pady=(0, 8))
        self.coverage_moves_frame = ttk.Frame(moves_frame)
        self.coverage_moves_frame.pack(fill=tk.X)

        # Side-by-side layout for effectiveness + bosses
        self._offense_side = ttk.Frame(frm)
        self._offense_side.pack(fill=tk.BOTH, expand=True)
        coverage_frame = ttk.LabelFrame(self._offense_side, text="Type Effectiveness Overview")
        coverage_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(0, 10), padx=(0, 5))
        # Limit height with a scrollable inner frame
        cov_canvas = tk.Canvas(coverage_frame, height=220, width=360)
        cov_scroll = ttk.Scrollbar(coverage_frame, orient="vertical", command=cov_canvas.yview)
        cov_inner = ttk.Frame(cov_canvas)
        cov_canvas.configure(yscrollcommand=cov_scroll.set)
        cov_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cov_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        cov_canvas.create_window((0, 0), window=cov_inner, anchor="nw")
        cov_inner.bind("<Configure>", lambda e: cov_canvas.configure(scrollregion=cov_canvas.bbox("all")))
        self._coverage_inner = cov_inner

        # Create effectiveness sections (single-type vs single-type only: 2x, 1x, 0.5x, 0x)
        effectiveness_sections = [
            ("Super Effective (2x)", "super_effective", "#4CAF50"),  # Green
            ("Neutral (1x)", "neutral", "#FFC107"),                   # Amber
            ("Resisted (0.5x)", "resisted", "#FF9800"),              # Orange
            ("No Effect (0x)", "no_effect", "#F44336")               # Red
        ]

        self.coverage_sections = {}
        for i, (title, key, color) in enumerate(effectiveness_sections):
            section = ttk.LabelFrame(self._coverage_inner, text=title)
            section.pack(fill=tk.X, padx=5, pady=2)

            # Frame for type chips
            chips_frame = ttk.Frame(section)
            chips_frame.pack(fill=tk.X, padx=5, pady=5)
            self.coverage_sections[key] = chips_frame

        # Boss analysis section (right pane) - compact, non-scrollable
        boss_frame = ttk.LabelFrame(self._offense_side, text="Boss Pokemon Analysis")
        boss_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, pady=(0, 10), padx=(5, 0))

        self.boss_labels = {}
        boss_pokemon = [
            ("Eternatus", "eternatus"),
            ("Rayquaza", "rayquaza"),
            ("Mega Rayquaza", "mega_rayquaza")
        ]

        for i, (name, key) in enumerate(boss_pokemon):
            # Bound each boss in its own subsection for resilience
            boss_box = ttk.LabelFrame(boss_frame, text=name)
            boss_box.pack(fill=tk.X, padx=5, pady=4)
            top_row = ttk.Frame(boss_box)
            top_row.pack(fill=tk.X, padx=5, pady=2)

            # Boss type chips
            from rogueeditor.coverage_calculator import BOSS_POKEMON
            boss_data = BOSS_POKEMON.get(key, {})
            boss_types = boss_data.get('types', [])

            if boss_types:
                type_frame = ttk.Frame(top_row)
                type_frame.pack(side=tk.LEFT, padx=(5, 10))

                for boss_type in boss_types:
                    type_chip = tk.Label(type_frame, text=boss_type.title(),
                                       bg=self._color_for_type(boss_type),
                                       bd=1, relief=tk.SOLID, padx=4, pady=1)
                    type_chip.pack(side=tk.LEFT, padx=1)

            # Status + per-boss dynamic container
            status_label = ttk.Label(top_row, text="Analyzing...", foreground="gray")
            status_label.pack(side=tk.LEFT, padx=(10, 0))
            # Container to render move-type effectiveness chips (flow, 4 per row)
            dyn = ttk.Frame(boss_box)
            dyn.pack(fill=tk.X, padx=10, pady=2)
            self.boss_labels[key] = status_label
            setattr(self, f"_boss_dyn_{key}", dyn)

        # Walls section (below side-by-side) - dynamically sized
        self._walls_frame = ttk.LabelFrame(frm, text="Type Combos That Wall This Pokemon")
        self._walls_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(4, 6))
        # Make walls section scrollable and extensible with dynamic height
        walls_canvas = tk.Canvas(self._walls_frame, highlightthickness=0)
        walls_scroll = ttk.Scrollbar(self._walls_frame, orient="vertical", command=walls_canvas.yview)
        self._walls_inner = ttk.Frame(walls_canvas)
        walls_canvas.configure(yscrollcommand=walls_scroll.set)
        walls_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        walls_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        walls_canvas.create_window((0, 0), window=self._walls_inner, anchor="nw")

        def _update_walls_scroll_region(event=None):
            walls_canvas.configure(scrollregion=walls_canvas.bbox("all"))
            # Update canvas height based on content, with min/max bounds
            content_height = self._walls_inner.winfo_reqheight()
            canvas_height = min(max(content_height, 80), 300)  # Min 80px, max 300px
            walls_canvas.configure(height=canvas_height)

        self._walls_inner.bind("<Configure>", _update_walls_scroll_region)

        # Initialize coverage display
        self._refresh_offensive_coverage()

    def _refresh_offensive_coverage(self):
        """Refresh the offensive Matchups analysis display."""
        self._show_loading_indicator("Analyzing Pokemon coverage...")
        try:
            mon = self._current_mon()
            if not mon:
                self._clear_coverage_display()
                return

            # Extract move IDs (works without calculator)
            moves = mon.get("moveset", []) or mon.get("moves", [])
            move_ids = []
            for move in moves:
                if isinstance(move, dict):
                    mid = move.get("moveId")
                    if isinstance(mid, int):
                        move_ids.append(mid)
                elif isinstance(move, int):
                    move_ids.append(move)

            # Stage 1: skip interim numeric preview to avoid extra render; final names/types will render in stages

            if not move_ids:
                self._hide_loading_indicator()
                return

            # Progressive staged computation in background with single-flight guard
            selection_token = getattr(self, '_selection_token', 0)
            try:
                self._offense_gen = int(getattr(self, '_offense_gen', 0)) + 1
            except Exception:
                self._offense_gen = 1
            current_gen = int(self._offense_gen)
            # cancel previously scheduled stage callbacks if any
            try:
                if hasattr(self, '_offense_after_ids') and isinstance(self._offense_after_ids, list):
                    for aid in self._offense_after_ids:
                        try:
                            self.after_cancel(aid)
                        except Exception:
                            pass
            except Exception:
                pass
            self._offense_after_ids = []
            import threading
            def worker(ids_local, token_local):
                try:
                    from rogueeditor.coverage_calculator import get_coverage_for_pokemon, invalidate_coverage_cache
                    try:
                        mon_key = str(mon.get('id')) if isinstance(mon.get('id'), int) else str(self.party.index(mon))
                    except Exception:
                        mon_key = 'current'
                    move_sig = tuple(sorted(ids_local))
                    cached = self._mon_coverage_cache.get(mon_key)
                    if cached and cached.get('sig') == move_sig:
                        coverage = cached.get('coverage') or {}
                    else:
                        try:
                            invalidate_coverage_cache(mon_key)
                        except Exception:
                            pass
                        coverage = get_coverage_for_pokemon(ids_local, mon_key)
                        self._mon_coverage_cache[mon_key] = {'sig': move_sig, 'coverage': coverage}

                    # Stage 2: type overview
                    try:
                        aid = self.after(0, lambda g=current_gen, cov=coverage, tok=token_local: (
                            self._update_coverage_types_guarded(tok, cov) if g == getattr(self, '_offense_gen', 0) else None
                        ))
                        self._offense_after_ids.append(aid)
                    except Exception:
                        pass
                    # Stage 3: bosses
                    try:
                        aid = self.after(50, lambda g=current_gen, cov=coverage, tok=token_local: (
                            self._update_coverage_bosses_guarded(tok, cov) if g == getattr(self, '_offense_gen', 0) else None
                        ))
                        self._offense_after_ids.append(aid)
                    except Exception:
                        pass
                    # Stage 4: walls
                    try:
                        aid = self.after(100, lambda g=current_gen, cov=coverage, tok=token_local: (
                            self._update_coverage_walls_guarded(tok, cov) if g == getattr(self, '_offense_gen', 0) else None
                        ))
                        self._offense_after_ids.append(aid)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"Coverage worker error: {e}")
                    self.after(0, self._hide_loading_indicator)

            threading.Thread(target=worker, args=(move_ids.copy(), selection_token), daemon=True).start()

        except Exception as e:
            print(f"Error refreshing offensive Matchups: {e}")
            self._clear_coverage_display()
            self._hide_loading_indicator()

    def _clear_coverage_display(self):
        """Clear the coverage display when no data is available."""
        try:
            # Clear moves display
            for widget in self.coverage_moves_frame.winfo_children():
                widget.destroy()

            ttk.Label(self.coverage_moves_frame, text="No damaging moves found",
                     foreground="gray").pack(anchor=tk.W, padx=5, pady=5)

            # Clear coverage sections
            for section_frame in self.coverage_sections.values():
                for widget in section_frame.winfo_children():
                    widget.destroy()
                ttk.Label(section_frame, text="No coverage data",
                         foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            # Clear boss analysis
            for label in self.boss_labels.values():
                label.config(text="No moves", foreground="gray")
            for key in ("eternatus", "rayquaza", "mega_rayquaza"):
                try:
                    dyn = getattr(self, f"_boss_dyn_{key}")
                    for w in dyn.winfo_children():
                        w.destroy()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error clearing coverage display: {e}")

    def _force_recalc_coverage(self):
        """User-triggered coverage recalculation (e.g., after manual edits)."""
        try:
            debug_log("Force recalc coverage called - clearing all caches")
            
            # Clear local cache for current mon
            mon = self._current_mon()
            try:
                mon_key = str(mon.get('id')) if (mon and isinstance(mon.get('id'), int)) else str(self.party.index(mon))
            except Exception:
                mon_key = 'current'
            
            debug_log(f"Clearing cache for mon_key: {mon_key}")
            
            # Clear local mon coverage cache
            if isinstance(getattr(self, '_mon_coverage_cache', None), dict):
                old_size = len(self._mon_coverage_cache)
                self._mon_coverage_cache.pop(mon_key, None)
                debug_log(f"Cleared mon coverage cache: {old_size} -> {len(self._mon_coverage_cache)}")
            
            # Clear any other relevant caches
            if hasattr(self, '_pokemon_analysis_cache'):
                self._pokemon_analysis_cache.clear()
                debug_log("Cleared pokemon analysis cache")
            
            # Clear team analysis cache as well
            if hasattr(self, '_team_analysis_cache'):
                old_team_size = len(self._team_analysis_cache)
                self._team_analysis_cache.clear()
                debug_log(f"Cleared team analysis cache: {old_team_size} -> {len(self._team_analysis_cache)}")
            
            # Invalidate calculator cache for this mon
            try:
                from rogueeditor.coverage_calculator import invalidate_coverage_cache
                invalidate_coverage_cache(mon_key)
                debug_log(f"Invalidated coverage calculator cache for {mon_key}")
            except Exception as e:
                debug_log(f"Failed to invalidate coverage calculator cache: {e}")
                
        except Exception as e:
            debug_log(f"Error in force recalc coverage: {e}")
            
        # Refresh UI
        try:
            debug_log("Refreshing offensive coverage UI")
            self._refresh_offensive_coverage()
        except Exception as e:
            debug_log(f"Error refreshing offensive coverage: {e}")

    def _update_coverage_display(self, coverage: dict):
        """Update the coverage display with calculated coverage data."""
        try:
            # Clear existing widgets safely
            self._safe_destroy_widgets(self.coverage_moves_frame)

            # Display damaging moves in two side-by-side stacks (up to 2 per column)
            damaging_moves = coverage.get("damaging_moves", [])
            if damaging_moves:
                grid = ttk.Frame(self.coverage_moves_frame)
                grid.pack(fill=tk.X, padx=5, pady=(2, 4))
                left = ttk.Frame(grid)
                left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
                right = ttk.Frame(grid)
                right.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
                def render_table(container, rows):
                    header = ttk.Frame(container)
                    header.pack(fill=tk.X)
                    ttk.Label(header, text="#", width=3).pack(side=tk.LEFT)
                    ttk.Label(header, text="Type", width=10).pack(side=tk.LEFT)
                    ttk.Label(header, text="Name", width=20).pack(side=tk.LEFT)
                    ttk.Label(header, text="Pow", width=6).pack(side=tk.LEFT)
                    ttk.Label(header, text="Acc", width=6).pack(side=tk.LEFT)
                    for num, move in rows:
                        row = ttk.Frame(container)
                        row.pack(fill=tk.X, pady=1)
                        ttk.Label(row, text=str(num), width=3).pack(side=tk.LEFT)
                        mtype = str(move.get("type", "unknown")).strip().lower()
                        chip = tk.Label(row, text=mtype.title(), bg=self._color_for_type(mtype), bd=1, relief=tk.SOLID, padx=6, pady=2, width=8)
                        chip.pack(side=tk.LEFT, padx=(0, 6))
                        ttk.Label(row, text=str(move.get("name", "Unknown")), width=20).pack(side=tk.LEFT)
                        pwr = move.get("power")
                        ttk.Label(row, text=("—" if pwr in (None, 0) else str(pwr)), width=6).pack(side=tk.LEFT)
                        acc = move.get("accuracy")
                        ttk.Label(row, text=("—" if acc is None else f"{int(acc)}%"), width=6).pack(side=tk.LEFT)
                # Prepare row-major then split into two tables with two rows each
                numbered = list(enumerate(damaging_moves[:4], start=1))
                left_rows = [(n, m) for (n, m) in numbered if n in (1, 3)]
                right_rows = [(n, m) for (n, m) in numbered if n in (2, 4)]
                if left_rows:
                    render_table(left, left_rows)
                if right_rows:
                    render_table(right, right_rows)
            else:
                ttk.Label(self.coverage_moves_frame, text="No damaging moves found",
                         foreground="gray").pack(anchor=tk.W, padx=5, pady=5)

            # Update coverage sections by testing each defender against all move types and binning top effectiveness
            coverage_summary = coverage.get("coverage_summary", {})
            # Derive user move types reliably from coverage.damaging_moves; fallback to summary
            try:
                dm = coverage.get("damaging_moves", [])
                derived = [str(m.get("type", "")).strip().lower() for m in dm if isinstance(m, dict) and m.get("type") is not None]
                move_types = set([t for t in derived if t])
            except Exception:
                move_types = set()
            if not move_types:
                move_types = set([str(t).strip().lower() for t in coverage_summary.get("move_types", []) if t])
            # Build bins fresh (single-type vs single-type only: 2x, 1x, 0.5x, 0x)
            bins = {
                "super_effective": [],  # ==2
                "neutral": [],          # ==1
                "resisted": [],         # ==0.5
                "no_effect": [],        # ==0
            }
            # Use matrix to recompute best effectiveness per defender
            from rogueeditor.catalog import load_type_matchup_matrix
            raw_mat = getattr(self, "_type_matrix", None) or load_type_matchup_matrix()
            mat = self._ensure_defense_matrix(raw_mat)
            # Derive list of type names from matrix keys
            defenders = sorted([k for k in mat.keys() if isinstance(mat.get(k), dict)])
            for def_t in defenders:
                best = 0.0
                for att in move_types:
                    eff = 1.0
                    try:
                        # offense-oriented lookup: how effective attacking type is against defending type
                        # Matrix structure: mat[attacking_type][defending_type] = effectiveness
                        row = mat.get(att) or {}
                        if def_t in row:
                            eff = float(row.get(def_t) or 1.0)
                        else:
                            # Fallback: try reverse lookup
                            row2 = mat.get(def_t) or {}
                            if att in row2:
                                eff = float(row2.get(att) or 1.0)
                            else:
                                # Default to neutral if no data found
                                eff = 1.0
                    except Exception:
                        eff = 1.0
                    if eff > best:
                        best = eff
                # Bin once per defender by best effectiveness (single-type only: 2x, 1x, 0.5x, 0x)
                if best == 0.0:
                    bins["no_effect"].append(def_t)
                elif best == 0.5:
                    bins["resisted"].append(def_t)
                elif best == 1.0:
                    bins["neutral"].append(def_t)
                elif best == 2.0:
                    bins["super_effective"].append(def_t)

            # Render bins top to bottom; types appear only in their highest-qualifying bin
            for section_key in ("super_effective", "neutral", "resisted", "no_effect"):
                section_frame = self.coverage_sections[section_key]
                self._safe_destroy_widgets(section_frame)
                tlist = bins.get(section_key) or []
                if tlist:
                    labels = [t.title() for t in tlist]
                    colors = [self._color_for_type(t) for t in tlist]
                    # Wrap at 7 chips per row for better readability
                    self._render_type_chips(section_frame, labels, colors, per_row=7)
                else:
                    ttk.Label(section_frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            # Type-combo walls: show dual type combos split by resistance level (0x, 0.25x, 0.5x)
            try:
                debug_log("Starting wall analysis in _update_coverage_display")
                target_inner = getattr(self, '_walls_inner', None)
                parent_to_clear = target_inner if target_inner is not None else self._walls_frame
                for w in parent_to_clear.winfo_children():
                    w.destroy()

                # Create 3 vertical sections with fixed width based on content
                container = getattr(self, '_walls_inner', None) or self._walls_frame
                walls_sections_frame = ttk.Frame(container)
                walls_sections_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                
                # Calculate optimal width based on longest type name
                all_types = sorted([k for k in mat.keys() if isinstance(mat.get(k), dict)])
                max_type_length = max([len(t) for t in all_types]) if all_types else 8
                # Width calculation: 4 types + brackets + slash + comma + space + padding
                # Format: [Type1/Type2], [Type3/Type4] (2 combinations per row)
                char_width = (max_type_length * 4) + 4 + 2 + 1 + 8  # brackets(4) + slash(1) + comma(1) + space(1) + padding(8)
                optimal_width = max(char_width * 6, 200)  # 6 characters per pixel, minimum 200px
                
                # Debug: Log the calculated width
                debug_log(f"Calculated optimal width: {optimal_width}px (max_type_length: {max_type_length})")
                
                # Debug flag for detailed effectiveness calculations (set to False to reduce log noise)
                DEBUG_EFFECTIVENESS_CALCULATIONS = False

                # Section 1: Immune (0x) - with proper scrolling
                immune_frame = ttk.LabelFrame(walls_sections_frame, text="Immune (0x)")
                immune_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3), pady=0)
                immune_frame.configure(width=optimal_width)
                
                # Create canvas and scrollbar for proper scrolling
                immune_canvas = tk.Canvas(immune_frame, width=220, height=150)
                immune_scrollbar = ttk.Scrollbar(immune_frame, orient="vertical", command=immune_canvas.yview)
                immune_scrollable_frame = ttk.Frame(immune_canvas)
                
                # Configure canvas
                immune_canvas.create_window((0, 0), window=immune_scrollable_frame, anchor="nw")
                immune_canvas.configure(yscrollcommand=immune_scrollbar.set)
                immune_scrollable_frame.bind("<Configure>", lambda e: immune_canvas.configure(scrollregion=immune_canvas.bbox("all")))
                
                # Count label on top (must be created before packing canvas to appear above chips)
                immune_count_var = tk.StringVar(value="")
                ttk.Label(immune_frame, textvariable=immune_count_var, foreground="gray").pack(anchor=tk.W, padx=6, pady=(2,0))

                # Pack canvas and scrollbar
                immune_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
                immune_scrollbar.pack(side="right", fill="y")
                
                # Add mousewheel scrolling support
                def _on_immune_mousewheel(event):
                    immune_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                
                immune_canvas.bind('<Enter>', lambda e: immune_canvas.bind_all("<MouseWheel>", _on_immune_mousewheel))
                immune_canvas.bind('<Leave>', lambda e: immune_canvas.unbind_all("<MouseWheel>"))
                
                walls_immune = immune_scrollable_frame
                
                debug_log(f"  Created simplified immune_frame with width {optimal_width}")

                # Section 2: Highly Resisted (0.25x) - with proper scrolling
                quarter_frame = ttk.LabelFrame(walls_sections_frame, text="Highly Resisted (0.25x)")
                quarter_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(3, 3), pady=0)
                quarter_frame.configure(width=optimal_width)
                
                # Create canvas and scrollbar for proper scrolling
                quarter_canvas = tk.Canvas(quarter_frame, width=220, height=150)
                quarter_scrollbar = ttk.Scrollbar(quarter_frame, orient="vertical", command=quarter_canvas.yview)
                quarter_scrollable_frame = ttk.Frame(quarter_canvas)
                
                # Configure canvas
                quarter_canvas.create_window((0, 0), window=quarter_scrollable_frame, anchor="nw")
                quarter_canvas.configure(yscrollcommand=quarter_scrollbar.set)
                quarter_scrollable_frame.bind("<Configure>", lambda e: quarter_canvas.configure(scrollregion=quarter_canvas.bbox("all")))
                
                # Count label on top (before packing canvas)
                quarter_count_var = tk.StringVar(value="")
                ttk.Label(quarter_frame, textvariable=quarter_count_var, foreground="gray").pack(anchor=tk.W, padx=6, pady=(2,0))

                # Pack canvas and scrollbar
                quarter_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
                quarter_scrollbar.pack(side="right", fill="y")
                
                # Add mousewheel scrolling support
                def _on_quarter_mousewheel(event):
                    quarter_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                
                quarter_canvas.bind('<Enter>', lambda e: quarter_canvas.bind_all("<MouseWheel>", _on_quarter_mousewheel))
                quarter_canvas.bind('<Leave>', lambda e: quarter_canvas.unbind_all("<MouseWheel>"))
                
                walls_quarter = quarter_scrollable_frame

                # Section 3: Resisted (0.5x) - with proper scrolling
                half_frame = ttk.LabelFrame(walls_sections_frame, text="Resisted (0.5x)")
                half_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(3, 0), pady=0)
                half_frame.configure(width=optimal_width)
                
                # Create canvas and scrollbar for proper scrolling
                half_canvas = tk.Canvas(half_frame, width=220, height=150)
                half_scrollbar = ttk.Scrollbar(half_frame, orient="vertical", command=half_canvas.yview)
                half_scrollable_frame = ttk.Frame(half_canvas)
                
                # Configure canvas
                half_canvas.create_window((0, 0), window=half_scrollable_frame, anchor="nw")
                half_canvas.configure(yscrollcommand=half_scrollbar.set)
                half_scrollable_frame.bind("<Configure>", lambda e: half_canvas.configure(scrollregion=half_canvas.bbox("all")))
                
                # Count label on top (before packing canvas)
                half_count_var = tk.StringVar(value="")
                ttk.Label(half_frame, textvariable=half_count_var, foreground="gray").pack(anchor=tk.W, padx=6, pady=(2,0))

                # Pack canvas and scrollbar
                half_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
                half_scrollbar.pack(side="right", fill="y")
                
                # Add mousewheel scrolling support
                def _on_half_mousewheel(event):
                    half_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                
                half_canvas.bind('<Enter>', lambda e: half_canvas.bind_all("<MouseWheel>", _on_half_mousewheel))
                half_canvas.bind('<Leave>', lambda e: half_canvas.unbind_all("<MouseWheel>"))
                
                walls_half = half_scrollable_frame

                # Debug: Ensure all three sections are created
                debug_log(f"Created walls sections: immune={walls_immune}, quarter={walls_quarter}, half={walls_half}")
                
                # Calculate dual type combinations and categorize by resistance level
                # Normalize matrix to defensive orientation and normalize keys
                # Ensure type matrices are cached and normalized
                try:
                    self._ensure_type_matrices_cached()
                except Exception:
                    pass
                # Normalize move types to lowercase strings
                move_types_list = sorted(set([str(mt).strip().lower() for mt in (list(move_types) or [])]))
                
                # Debug: Check if we have move types to analyze
                debug_log(f"Move types for wall analysis: {move_types_list}")
                debug_log(f"Number of move types: {len(move_types_list) if move_types_list else 0}")

                if move_types_list:
                    debug_log(f"Starting wall analysis with {len(move_types_list)} move types")
                    
                    # WALL ANALYSIS: Identify defensive threats that resist the user's offensive moves
                    # 
                    # Purpose: Find type combinations that can "wall" the user's team by resisting
                    # even their best offensive moves. This helps identify coverage gaps and
                    # defensive threats the user should be aware of.
                    #
                    # Methodology:
                    # 1. Test every possible dual-type combination against the user's move types
                    # 2. Calculate the BEST effectiveness the user can achieve against each combo
                    # 3. Categorize combos based on how well they resist the user's moves:
                    #    - Immune (0x): User has no moves that can hit this combo
                    #    - Highly Resisted (0.25x): User's best move is 4x resisted  
                    #    - Resisted (0.5x): User's best move is 2x resisted
                    # 4. Only show combos where the user's BEST move is resisted (true walls)
                    #
                    # Note: For dual-types, effectiveness is multiplicative (e.g., 2x vs type1 * 0.5x vs type2 = 1x overall)
                    
                    # Lists to store type combinations that wall the user's moves
                    immunity_duals = []      # Type combos the user cannot hit at all (0x effectiveness)
                    quarter_duals = []       # Type combos that highly resist user's moves (0.25x effectiveness)  
                    half_duals = []          # Type combos that resist user's moves (0.5x effectiveness)

                    # Snap to canonical effectiveness buckets
                    def _snap_bucket(x: float) -> float:
                        try:
                            x = float(x)
                        except Exception:
                            return 1.0
                        eps = 1e-6
                        for val in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
                            if abs(x - val) <= eps:
                                return val
                        return x

                    # WALL ANALYSIS: Find type combinations that resist the user's best offensive moves
                    # A "wall" is a type combo where even the user's BEST move is resisted or immune
                    # This helps identify defensive threats the user's team struggles against
                    
                    self._ensure_type_matrices_cached()
                    all_defending_types = sorted(self._tm_def.keys())
                    
                    # Test every possible dual-type combination against the user's moves
                    for i, defending_type1 in enumerate(all_defending_types):
                        for defending_type2 in all_defending_types[i+1:]:  # Avoid duplicates like (fire, water) and (water, fire)
                            
                            # Find the BEST effectiveness the user can achieve against this defending type combo
                            if DEBUG_EFFECTIVENESS_CALCULATIONS:
                                debug_log(f"  Testing user moves vs defending [{defending_type1}/{defending_type2}]: {move_types_list}")
                            
                            try:
                                # For debugging: manually calculate effectiveness for known problematic pairs
                                if (defending_type1, defending_type2) in (('bug','psychic'), ('dragon','normal')) or (defending_type2, defending_type1) in (('bug','psychic'), ('dragon','normal')):
                                    effectiveness_values = []
                                    for move_type in move_types_list:
                                        effectiveness_vs_type1 = self._tm_att_mult(move_type, defending_type1)
                                        effectiveness_vs_type2 = self._tm_att_mult(move_type, defending_type2)
                                        combined_effectiveness = float(effectiveness_vs_type1) * float(effectiveness_vs_type2)
                                        debug_log(f"    TRACE [{defending_type1}/{defending_type2}] {move_type}: {effectiveness_vs_type1} * {effectiveness_vs_type2} = {combined_effectiveness}")
                                        effectiveness_values.append(combined_effectiveness)
                                    best_effectiveness_against_combo = float(max(effectiveness_values) if effectiveness_values else 1.0)
                                else:
                                    # Use the optimized method for all other type combinations
                                    best_effectiveness_against_combo = float(self._tm_best_offense_vs_dual(move_types_list, defending_type1, defending_type2))
                            except Exception:
                                best_effectiveness_against_combo = 1.0

                            # Categorize this defending type combo based on how well it resists the user's moves
                            # Only include combos where the user's BEST move is resisted/immune (true walls)
                            if DEBUG_EFFECTIVENESS_CALCULATIONS:
                                debug_log(f"  Best effectiveness against [{defending_type1}/{defending_type2}]: {best_effectiveness_against_combo}")
                            
                            # Snap to standard effectiveness buckets for consistent categorization
                            best_effectiveness_against_combo = _snap_bucket(best_effectiveness_against_combo)

                            # Categorize the defending type combo based on resistance level
                            if best_effectiveness_against_combo <= 0.0:
                                # Complete immunity: user has no moves that can hit this type combo
                                immunity_duals.append((defending_type1, defending_type2))
                                if DEBUG_EFFECTIVENESS_CALCULATIONS:
                                    debug_log(f"    -> Added to IMMUNE (0x) - user has no moves that can hit this combo")
                            elif best_effectiveness_against_combo <= 0.25:
                                # Highly resisted: user's best move is only 0.25x effective (4x resistance)
                                quarter_duals.append((defending_type1, defending_type2))
                                if DEBUG_EFFECTIVENESS_CALCULATIONS:
                                    debug_log(f"    -> Added to HIGHLY RESISTED (0.25x) - user's best move is 4x resisted")
                            elif best_effectiveness_against_combo <= 0.5:
                                # Resisted: user's best move is only 0.5x effective (2x resistance)
                                half_duals.append((defending_type1, defending_type2))
                                if DEBUG_EFFECTIVENESS_CALCULATIONS:
                                    debug_log(f"    -> Added to RESISTED (0.5x) - user's best move is 2x resisted")
                            elif DEBUG_EFFECTIVENESS_CALCULATIONS:
                                debug_log(f"    -> Not a wall (effectiveness > 0.5x)")

                    # Log summary of wall analysis results
                    debug_log(f"Wall analysis complete:")
                    debug_log(f"  Immune (0x): {len(immunity_duals)} combinations")
                    debug_log(f"  Highly Resisted (0.25x): {len(quarter_duals)} combinations") 
                    debug_log(f"  Resisted (0.5x): {len(half_duals)} combinations")
                    
                    # Render each section with dual type combinations in rows of 2
                    def render_dual_types(frame, duals):
                        debug_log(f"render_dual_types called with {len(duals)} duals: {duals[:3] if duals else 'None'}")
                        # Clear any existing content first
                        for widget in frame.winfo_children():
                            widget.destroy()
                            
                        if duals:
                            # No limit needed since we have scrolling
                            displayed_duals = duals
                            
                            # Group into pairs for display
                            for i in range(0, len(displayed_duals), 2):
                                row_frame = ttk.Frame(frame)
                                row_frame.pack(fill=tk.X, anchor=tk.W, pady=2)
                                
                                # First combo in the row
                                if i < len(displayed_duals):
                                    type1, type2 = displayed_duals[i]
                                    combo_frame = ttk.Frame(row_frame)
                                    combo_frame.pack(side=tk.LEFT, padx=(0, 8))
                                    
                                    # Create type chips for the combination with brackets
                                    tk.Label(combo_frame, text="[", bd=0, padx=0).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text=type1.title(), bg=self._color_for_type(type1),
                                            bd=1, relief=tk.SOLID, padx=3, pady=1).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text="/", bd=0, padx=2).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text=type2.title(), bg=self._color_for_type(type2),
                                            bd=1, relief=tk.SOLID, padx=3, pady=1).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text="]", bd=0, padx=0).pack(side=tk.LEFT)
                                
                                # Second combo in the row (if exists)
                                if i + 1 < len(displayed_duals):
                                    type1, type2 = displayed_duals[i + 1]
                                    combo_frame = ttk.Frame(row_frame)
                                    combo_frame.pack(side=tk.LEFT, padx=(0, 8))
                                    
                                    # Add comma separator for the second combo
                                    tk.Label(combo_frame, text=", ", bd=0, padx=0).pack(side=tk.LEFT)
                                    
                                    # Create type chips for the combination with brackets
                                    tk.Label(combo_frame, text="[", bd=0, padx=0).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text=type1.title(), bg=self._color_for_type(type1),
                                            bd=1, relief=tk.SOLID, padx=3, pady=1).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text="/", bd=0, padx=2).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text=type2.title(), bg=self._color_for_type(type2),
                                            bd=1, relief=tk.SOLID, padx=3, pady=1).pack(side=tk.LEFT)
                                    tk.Label(combo_frame, text="]", bd=0, padx=0).pack(side=tk.LEFT)

                            # Show count of results
                            if len(duals) > 0:
                                ttk.Label(frame, text=f"Found {len(duals)} type combinations", 
                                         foreground="gray", font=("TkDefaultFont", 8)).pack(anchor=tk.W, pady=(4, 0))
                        else:
                            ttk.Label(frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

                    # Debug section removed to avoid confusion with orientation
                    
                    # Debug: Log the counts before rendering
                    debug_log(f"Rendering walls: immune={len(immunity_duals)}, quarter={len(quarter_duals)}, half={len(half_duals)}")
                    debug_log(f"Move types: {move_types_list}")
                    if immunity_duals:
                        debug_log(f"Sample immunity dual: {immunity_duals[0]} (user's best effectiveness = 0.0)")
                    if quarter_duals:
                        debug_log(f"Sample quarter dual: {quarter_duals[0]} (user's best effectiveness = 0.25)")
                    if half_duals:
                        debug_log(f"Sample half dual: {half_duals[0]} (user's best effectiveness = 0.5)")
                    
                    # Update counts on top
                    try:
                        immune_count_var.set(f"Found {len(immunity_duals)} type combinations")
                        quarter_count_var.set(f"Found {len(quarter_duals)} type combinations")
                        half_count_var.set(f"Found {len(half_duals)} type combinations")
                    except Exception:
                        pass
                    render_dual_types(walls_immune, immunity_duals)
                    render_dual_types(walls_quarter, quarter_duals)
                    render_dual_types(walls_half, half_duals)
                    
                    # Force canvas updates to ensure content is visible
                    try:
                        # Update scroll regions for all canvases
                        canvases = [
                            ('immune', immune_canvas),
                            ('quarter', quarter_canvas),
                            ('half', half_canvas)
                        ]
                        
                        for name, canvas in canvases:
                            if canvas:
                                canvas.update_idletasks()
                                canvas.configure(scrollregion=canvas.bbox("all"))
                                debug_log(f"  Updated scroll region for {name}_canvas: {canvas.bbox('all')}")
                            else:
                                debug_log(f"  {name}_canvas not found")
                    except Exception as e:
                        debug_log(f"  Error updating canvas scroll regions: {e}")
                    
                    # Ensure all sections have content (debug)
                    debug_log(f"After rendering: immune children={len(walls_immune.winfo_children())}, quarter children={len(walls_quarter.winfo_children())}, half children={len(walls_half.winfo_children())}")
                else:
                    # No move types found
                    debug_log("No move types found for wall analysis - this should not happen!")
                    for frame in [walls_immune, walls_quarter, walls_half]:
                        ttk.Label(frame, text="No moves", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            except Exception as e:
                debug_log(f"Error rendering wall sections: {e}")
                pass

            # Boss analysis is rendered exclusively by _update_coverage_bosses_guarded
            # to avoid duplicate/competing renders that cause flicker.

        except Exception as e:
            print(f"Error updating coverage display: {e}")

    def _render_moves_preview(self, move_ids: list[int]):
        try:
            # Clear area; final render will populate with names/chips in next stages
            for widget in self.coverage_moves_frame.winfo_children():
                widget.destroy()
            if not move_ids:
                ttk.Label(self.coverage_moves_frame, text="No damaging moves found",
                         foreground="gray").pack(anchor=tk.W, padx=5, pady=5)
                return
        except Exception:
            pass

    def _update_coverage_types_guarded(self, expected_token: int, coverage: dict):
        try:
            # Since we removed the token system, just update the display
            # Reuse full display updater but only for type sections
            coverage_summary = coverage.get("coverage_summary", {})
            move_types = set(coverage_summary.get("move_types", []))
            bins_frames = self.coverage_sections
            for section_frame in bins_frames.values():
                for widget in section_frame.winfo_children():
                    widget.destroy()
            from rogueeditor.catalog import load_type_matchup_matrix
            # Use normalized helpers backed by type_matrix_v2
            self._ensure_type_matrices_cached()
            type_names = list(self._tm_def.keys())
            def best_eff_vs_type(def_type):
                return self._tm_best_offense_vs_type(list(move_types), def_type)
            sorted_def_types = sorted(type_names)
            buckets = {"excellent_4x": [], "good_2x": [], "neutral": [], "not_very_effective": [], "no_effect": []}
            for t in sorted_def_types:
                eff = best_eff_vs_type(t)
                if eff == 0:
                    buckets["no_effect"].append(t)
                elif eff < 1:
                    buckets["not_very_effective"].append(t)
                elif eff == 1:
                    buckets["neutral"].append(t)
                elif eff == 2:
                    buckets["good_2x"].append(t)
                elif eff > 2:
                    buckets["excellent_4x"].append(t)
            for key, types in buckets.items():
                frame = bins_frames.get(key)
                if not frame:
                    continue
                if types:
                    for t in types:
                        chip = tk.Label(frame, text=t.title(), bg=self._color_for_type(t), bd=1, relief=tk.SOLID, padx=6, pady=2)
                        chip.pack(side=tk.LEFT, padx=2, pady=2)
                else:
                    ttk.Label(frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)
        except Exception:
            pass

    def _update_coverage_bosses_guarded(self, expected_token: int, coverage: dict):
        try:
            # Sole renderer for boss analysis to avoid flicker/duplication
            from rogueeditor.coverage_calculator import BOSS_POKEMON
            from rogueeditor.catalog import load_type_matchup_matrix
            damaging_moves = coverage.get("damaging_moves", [])
            for key in ("eternatus", "rayquaza", "mega_rayquaza"):
                try:
                    dyn = getattr(self, f"_boss_dyn_{key}")
                    for w in dyn.winfo_children():
                        w.destroy()
                except Exception:
                    continue
                boss = BOSS_POKEMON.get(key, {})
                btypes = boss.get('types', [])
                # Use matrix directly so we can apply Delta Stream only to the Flying component
                mat = getattr(self, "_type_matrix", None) or load_type_matchup_matrix()
                # Use unique move types only (no move names) for stable chips
                move_types = sorted(set([
                    str(m.get("type", "unknown")).strip().lower()
                    for m in damaging_moves if isinstance(m, dict)
                ]))

                # Compute max effectiveness descriptor across available move types
                max_eff = 0.0
                def _eff_vs_types(move_type: str, def_types: list) -> float:
                    try:
                        move_type = (move_type or "").strip().lower()
                        if not def_types:
                            return 1.0
                        vals = []
                        for t in def_types:
                            dt = str(t).strip().lower()
                            # Base effectiveness from defensive matrix: mat[def][att]
                            base = float(mat.get(dt, {}).get(move_type, 1.0))
                            # Delta Stream: only neutralize Flying weaknesses (not resistances), and only the Flying component
                            if key == 'mega_rayquaza' and dt == 'flying' and move_type in ('electric','ice','rock') and base > 1.0:
                                base = 1.0
                            vals.append(base)
                        out = 1.0
                        for v in vals:
                            out *= v
                        return float(out)
                    except Exception:
                        return 1.0

                for mtype in move_types:
                    eff = _eff_vs_types(mtype, btypes)
                    max_eff = eff if eff > max_eff else max_eff
                    chip = tk.Label(dyn, text=f"{mtype.title()} (x{float(eff):g})", bg=self._color_for_type(mtype), bd=1, relief=tk.SOLID, padx=6, pady=2)
                    chip.pack(side=tk.LEFT, padx=2, pady=2)

                # Map effectiveness to descriptor and color
                def _bucket(e: float) -> tuple[str, str]:
                    try:
                        # Snap to known buckets
                        if e <= 0.0:
                            return ("Immune (x0)", "#9e9e9e")
                        if e <= 0.25 + 1e-9:
                            return ("Heavily Resisted (x0.25)", "#ff9800")
                        if e <= 0.5 + 1e-9:
                            return ("Resisted (x0.5)", "#ffb74d")
                        if abs(e - 1.0) < 1e-9:
                            return ("Neutral (x1)", "#9e9e9e")
                        if e >= 4.0 - 1e-9:
                            return ("Extremely Effective (x4)", "#2e7d32")
                        if e >= 2.0 - 1e-9:
                            return ("Super Effective (x2)", "#43a047")
                        # Fallback
                        return (f"Best: x{e:g}", "#9e9e9e")
                    except Exception:
                        return ("Neutral (x1)", "#9e9e9e")

                if key in self.boss_labels:
                    desc, color = _bucket(float(max_eff))
                    self.boss_labels[key].config(text=desc, foreground=color)
        except Exception:
            pass

    def _update_coverage_walls_guarded(self, expected_token: int, coverage: dict):
        try:
            # Since we removed the token system, just update the display
            debug_log("_update_coverage_walls_guarded called - updating wall analysis")
            # Reuse existing walls rendering path by calling full updater at the end
            self._update_coverage_display(coverage)
            self._hide_loading_indicator()
        except Exception:
            self._hide_loading_indicator()
    def _detect_form_slug(self, mon: dict) -> Optional[str]:
        # Try explicit fields
        for k in ("form", "forme", "formName", "form_label", "formSlug", "subspecies", "variant"):
            v = mon.get(k)
            if isinstance(v, str) and v.strip():
                s = v.strip().lower()
                if s in ("alolan", "alola"): return "alola"
                if s in ("galarian", "galar"): return "galar"
                if s in ("hisuian", "hisui"): return "hisui"
                if s in ("paldean", "paldea"): return "paldea"
                if s.startswith("mega"):
                    if "x" in s: return "mega-x"
                    if "y" in s: return "mega-y"
                    return "mega"
                s = re.sub(r"[^a-z0-9]+", "-", s)
                return s
        # Boolean hints
        if mon.get("isAlolan"): return "alola"
        if mon.get("isGalarian"): return "galar"
        if mon.get("isHisuian"): return "hisui"
        if mon.get("gmax") or mon.get("isGmax"): return "gmax"
        if mon.get("mega") or mon.get("isMega"):
            m = str(mon.get("megaForm") or "").strip().lower()
            if m == "x": return "mega-x"
            if m == "y": return "mega-y"
            return "mega"
        # From name/nickname parentheses
        name = str(mon.get("nickname") or mon.get("name") or "").strip()
        if "(" in name and name.endswith(")"):
            tag = name.rsplit("(", 1)[1][:-1].strip().lower()
            if tag in ("alolan", "alola"): return "alola"
            if tag in ("galarian", "galar"): return "galar"
            if tag in ("hisuian", "hisui"): return "hisui"
            if tag.startswith("mega"):
                if "x" in tag: return "mega-x"
                if "y" in tag: return "mega-y"
                return "mega"
            tag = re.sub(r"[^a-z0-9]+", "-", tag)
            return tag
        return None

    def _safe_destroy_widgets(self, parent):
        """Safely destroy widgets with existence check."""
        try:
            if parent and parent.winfo_exists():
                for widget in parent.winfo_children():
                    try:
                        if widget.winfo_exists():
                            widget.destroy()
                    except tk.TclError:
                        pass  # Widget already destroyed
        except tk.TclError:
            pass  # Parent doesn't exist

    def _render_type_chips(self, parent: ttk.Frame | tk.Frame, labels: list[str], bgs: list[str], per_row: int = 9):
        # Render chips in rows of at most per_row to avoid overly wide layouts
        rowf = None
        count = 0
        # If no chips, render a small spacer to enforce min height
        if not labels:
            rowf = ttk.Frame(parent)
            rowf.pack(fill=tk.X, anchor=tk.W)
            tk.Label(rowf, text=" ", bd=0, padx=6, pady=8).pack(side=tk.LEFT, padx=3, pady=3)
            return
        for i, lbl in enumerate(labels):
            if count % per_row == 0:
                rowf = ttk.Frame(parent)
                rowf.pack(fill=tk.X, anchor=tk.W)
            bg = bgs[i] if i < len(bgs) else "#DDDDDD"
            tk.Label(rowf, text=lbl, bg=bg, bd=1, relief=tk.SOLID, padx=6, pady=2).pack(side=tk.LEFT, padx=3, pady=3)
            count += 1

    def _friendly_form_name(self, fslug: Optional[str], entry: dict) -> Optional[str]:
        if not fslug:
            return None
        # Prefer display_name from catalog
        try:
            disp = ((entry.get("forms") or {}).get(fslug) or {}).get("display_name")
            if isinstance(disp, str) and disp.strip():
                return disp.strip()
        except Exception:
            pass
        # Fallback: prettify slug
        s = str(fslug).strip().lower()
        mapping = {
            "alola": "Alola",
            "galar": "Galar",
            "hisui": "Hisui",
            "paldea": "Paldea",
            "gmax": "Gigantamax",
            "mega": "Mega",
            "mega-x": "Mega X",
            "mega-y": "Mega Y",
            "attack-forme": "Attack Forme",
            "defense-forme": "Defense Forme",
            "speed-forme": "Speed Forme",
            "normal-forme": "Normal Forme",
            "plant-cloak": "Plant Cloak",
            "sandy-cloak": "Sandy Cloak",
            "trash-cloak": "Trash Cloak",
        }
        if s in mapping:
            return mapping[s]
        return re.sub(r"[-_]+", " ", s).title()

    # --- Context menus (cut/copy/paste/select-all) ---
    def _install_context_menus(self):
        # Bind right-click for common text-like widgets
        for cls in ("Entry", "Text", "TEntry", "TCombobox"):  # cover ttk
            try:
                self.bind_class(cls, "<Button-3>", self._show_ctx_menu, add="+")
            except Exception:
                pass

    def _widget_readonly(self, w) -> bool:
        # Try to detect read-only state across tk/ttk widgets
        try:
            st = str(w.cget('state'))
            if st.lower() in ("disabled", "readonly"):
                return True
        except Exception:
            pass
        try:
            # ttk widgets expose state() API
            stt = " ".join(getattr(w, 'state')() or [])
            if 'disabled' in stt or 'readonly' in stt:
                return True
        except Exception:
            pass
        return False

    def _do_copy(self, w):
        try:
            w.event_generate('<<Copy>>')
        except Exception:
            pass

    def _do_cut(self, w):
        try:
            if not self._widget_readonly(w):
                w.event_generate('<<Cut>>')
        except Exception:
            pass

    def _do_paste(self, w):
        try:
            if not self._widget_readonly(w):
                w.event_generate('<<Paste>>')
        except Exception:
            pass

    def _do_delete(self, w):
        try:
            if not self._widget_readonly(w):
                # Try selection delete
                if isinstance(w, tk.Text):
                    w.delete('sel.first', 'sel.last')
                else:
                    w.delete('sel.first', 'sel.last')
        except Exception:
            pass

    def _do_select_all(self, w):
        try:
            if isinstance(w, tk.Text):
                w.tag_add('sel', '1.0', 'end')
            else:
                w.select_range(0, 'end')
                w.icursor('end')
        except Exception:
            pass

    def _show_ctx_menu(self, event):
        # Guard against race: dialog may be destroyed by the time this fires
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        w = event.widget
        # Attach menu to the app root rather than this dialog to avoid bad window path after destroy
        try:
            root = self.winfo_toplevel()
        except Exception:
            root = self
        menu = tk.Menu(root, tearoff=0)
        readonly = self._widget_readonly(w)
        try:
            menu.add_command(label="Cut", command=lambda: self._do_cut(w), state=(tk.DISABLED if readonly else tk.NORMAL))
            menu.add_command(label="Copy", command=lambda: self._do_copy(w))
            menu.add_command(label="Paste", command=lambda: self._do_paste(w), state=(tk.DISABLED if readonly else tk.NORMAL))
            menu.add_command(label="Delete", command=lambda: self._do_delete(w), state=(tk.DISABLED if readonly else tk.NORMAL))
            menu.add_separator()
            menu.add_command(label="Select All", command=lambda: self._do_select_all(w))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            except Exception:
                pass
        finally:
            try:
                if menu.winfo_exists():
                    menu.grab_release()
            except Exception:
                pass

    # --- Heal helpers ---
    def _max_hp_for_mon(self, mon: dict) -> int:
        try:
            # Level
            try:
                level = int(_get(mon, ("level", "lvl")) or 1)
            except Exception:
                level = 1
            # Nature multipliers
            nat = _get(mon, ("natureId", "nature"))
            mults = self.nature_mults_by_id.get(int(nat)) if isinstance(nat, int) else [1.0] * 6
            # Base stats (prefer catalog)
            species_id = _get_species_id(mon)
            base_raw = None
            try:
                cat = self._get_cached_pokemon_catalog() or {}
                by_dex = cat.get("by_dex") or {}
                entry = by_dex.get(str(species_id or -1)) or {}
                st = entry.get("stats")
                if isinstance(st, dict):
                    base_raw = [
                        int(st.get("hp") or 0),
                        int(st.get("attack") or 0),
                        int(st.get("defense") or 0),
                        int(st.get("sp_atk") or 0),
                        int(st.get("sp_def") or 0),
                        int(st.get("speed") or 0),
                    ]
            except Exception:
                base_raw = None
            if base_raw is None:
                from rogueeditor.base_stats import get_base_stats_by_species_id
                base_raw = get_base_stats_by_species_id(species_id or -1) or [0,0,0,0,0,0]
            # IVs
            ivs = mon.get("ivs") if isinstance(mon.get("ivs"), list) and len(mon.get("ivs")) == 6 else [0,0,0,0,0,0]
            # Booster multipliers
            mon_id = int(mon.get("id") or -1)
            booster_mults, _, _ = _booster_multipliers_for_mon(self.data, mon_id)
            calc = _calc_stats(level, base_raw, ivs, mults or [1.0]*6, booster_mults)
            return int(calc[0] if calc and isinstance(calc[0], int) else 0)
        except Exception:
            return 0

    def _clear_status(self, mon: dict) -> None:
        try:
            mon['status'] = None
            for k in ('sleepTurns','statusTurns','toxicTurns'):
                if k in mon:
                    mon.pop(k, None)
        except Exception:
            pass

    def _full_pp_restore_for_mon(self, mon: dict) -> None:
        try:
            key, shapes, _ = self._derive_moves(mon)
            lst = mon.get(key) or []
            for i in range(min(4, len(lst))):
                cur = lst[i]
                if isinstance(cur, dict):
                    # Reset PP used; keep ppUp unchanged
                    cur['ppUsed'] = 0
                    lst[i] = cur
            mon[key] = lst
        except Exception:
            pass

    def _server_max_hp_for_mon(self, mon: dict) -> int:
        """Return max HP from server stats if available; else fallback to calculated max HP."""
        try:
            stats = mon.get('stats')
            if isinstance(stats, list) and len(stats) >= 1:
                v = int(stats[0])
                if v > 0:
                    return v
        except Exception:
            pass
        return self._max_hp_for_mon(mon)

    def _full_restore_current(self):
        mon = self._current_mon()
        if not mon:
            return
        try:
            # Use server max HP from file if available
            maxhp = self._server_max_hp_for_mon(mon)
            if maxhp > 0:
                _set(mon, ("currentHp","hp"), maxhp)
            self._clear_status(mon)
            self._full_pp_restore_for_mon(mon)
            self._mark_dirty()
            self._recalc_stats_safe()
            messagebox.showinfo("Full Restore", "Applied full restore to current Pokémon (local only). Upload to sync to server.")
        except Exception as e:
            messagebox.showwarning("Full Restore", f"Failed: {e}")

    # Full PP Restore handled as part of Full Restore and Full Team Heal; no separate action.

    def _full_team_heal(self):
        try:
            for mon in (self.party or []):
                maxhp = self._max_hp_for_mon(mon)
                if maxhp > 0:
                    _set(mon, ("currentHp","hp"), maxhp)
                self._clear_status(mon)
                self._full_pp_restore_for_mon(mon)
            self._mark_dirty()
            self._recompute_team_summary()
            messagebox.showinfo("Full Team Heal", "Applied Pokécenter heal to entire team (local only). Upload to sync to server.")
        except Exception as e:
            messagebox.showwarning("Full Team Heal", f"Failed: {e}")

    def _color_for_type(self, tname: str) -> str:
        # Normalize and map abbreviations to full names
        colors = getattr(self, "_type_colors", None) or load_type_colors()
        key = str(tname or "").strip().lower()
        # strip non-alnum for robust matching
        key_stripped = re.sub(r"[^a-z0-9]+", "", key)
        alias = {
            'nor': 'normal', 'fir': 'fire', 'wat': 'water', 'ele': 'electric', 'gra': 'grass', 'ice': 'ice',
            'fig': 'fighting', 'poi': 'poison', 'gro': 'ground', 'fly': 'flying', 'psy': 'psychic', 'bug': 'bug',
            'roc': 'rock', 'gho': 'ghost', 'dra': 'dragon', 'dar': 'dark', 'ste': 'steel', 'fai': 'fairy'
        }
        if key in colors:
            return colors[key]
        if key_stripped in alias:
            full = alias[key_stripped]
            return colors.get(full, "#DDDDDD")
        # try full known names stripped
        for full in colors.keys():
            if re.sub(r"[^a-z0-9]+", "", full) == key_stripped:
                return colors.get(full, "#DDDDDD")
        return "#DDDDDD"

    def _update_matchups_for_mon(self, mon: dict):
        try:
            # Build cached vector of multipliers
            key = self.party.index(mon) if mon in self.party else id(mon)
            if key in self._matchup_cache:
                mults = self._matchup_cache[key]
            else:
                mat = getattr(self, "_type_matrix", None) or load_type_matchup_matrix()
                # Resolve defending types
                cat = self._get_cached_pokemon_catalog() or {}
                by_dex = cat.get("by_dex") or {}
                dex = _get_species_id(mon) or -1
                entry = by_dex.get(str(dex)) or {}
                # Form-aware: detect form slug from mon, prefer form typings
                fslug = self._detect_form_slug(mon)
                if fslug and (entry.get("forms") or {}).get(fslug):
                    tp = (entry.get("forms") or {}).get(fslug, {}).get("types") or {}
                else:
                    tp = entry.get("types") or {}
                t1 = tp.get("type1")
                t2 = tp.get("type2")
                t1k = str(t1 or "unknown").strip().lower()
                t2k = str(t2 or "").strip().lower() if t2 else None
                mults = {}
                for atk in sorted(mat.keys()):
                    v1 = float((mat.get(t1k) or {}).get(atk, 1.0))
                    v2 = float((mat.get(t2k) or {}).get(atk, 1.0)) if t2k else 1.0
                    mults[atk] = v1 * v2
                self._matchup_cache[key] = mults
            # Distribute into bins
            bins = {"immune": [], "x0_25": [], "x0_5": [], "x1": [], "x2": [], "x4": []}
            for atk, eff in mults.items():
                if eff == 0:
                    bins["immune"].append(atk)
                elif eff == 0.25:
                    bins["x0_25"].append(atk)
                elif eff == 0.5:
                    bins["x0_5"].append(atk)
                elif eff == 1:
                    bins["x1"].append(atk)
                elif eff == 2:
                    bins["x2"].append(atk)
                elif eff == 4:
                    bins["x4"].append(atk)
                else:
                    # Round unexpected values to nearest bin
                    if eff < 0.5:
                        bins["x0_25"].append(atk)
                    elif eff < 1:
                        bins["x0_5"].append(atk)
                    elif eff < 2:
                        bins["x1"].append(atk)
                    else:
                        bins["x2"].append(atk)
            # Render type chips in each bin
            for k, frame in self._matchup_bins.items():
                for w in list(frame.winfo_children()):
                    w.destroy()
                labels = [atk.title() for atk in bins[k]]
                bgs = [self._color_for_type(atk) for atk in bins[k]]
                self._render_type_chips(frame, labels, bgs)
        except Exception:
            pass

    def _build_form_visuals(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Initialize type catalogs (will be loaded asynchronously)
        self._type_n2i, self._type_i2n = ({}, {})
        try:
            # Lazy-load types catalog safely
            self._type_n2i, self._type_i2n = load_types_catalog()
        except Exception:
            self._type_n2i, self._type_i2n = ({}, {})
        ttk.Label(frm, text="Tera Type:").grid(row=0, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_tera = tk.StringVar(value="")
        self.cb_tera = ttk.Combobox(
            frm,
            textvariable=self.var_tera,
            values=[f"{name} ({iid})" for name, iid in sorted(self._type_n2i.items(), key=lambda kv: kv[0])],
            width=22,
            state="readonly",
        )
        self.cb_tera.grid(row=0, column=1, sticky=tk.W)

        self.var_shiny = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Shiny", variable=self.var_shiny, command=self._on_shiny_toggle).grid(row=0, column=2, sticky=tk.W, padx=6)
        ttk.Label(frm, text="Luck:").grid(row=0, column=3, sticky=tk.E)
        self.var_luck = tk.StringVar(value="0")
        self.entry_luck = ttk.Entry(frm, textvariable=self.var_luck, width=5)
        self.entry_luck.grid(row=0, column=4, sticky=tk.W)

        self.var_pause_evo = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Pause Evolutions", variable=self.var_pause_evo).grid(row=1, column=1, sticky=tk.W, padx=6)

        ttk.Label(frm, text="Gender:").grid(row=1, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_gender = tk.StringVar(value="")
        self.cb_gender = ttk.Combobox(
            frm,
            textvariable=self.var_gender,
            values=["male (0)", "female (1)", "unknown (-1)"],
            width=22,
            state="readonly",
        )
        self.cb_gender.grid(row=1, column=1, sticky=tk.W)

        try:
            self._ball_n2i, self._ball_i2n = load_pokeball_catalog()
        except Exception:
            self._ball_n2i, self._ball_i2n = ({}, {})
        ttk.Label(frm, text="Poké Ball:").grid(row=2, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_ball = tk.StringVar(value="")
        self.cb_ball = ttk.Combobox(
            frm,
            textvariable=self.var_ball,
            values=[f"{name} ({iid})" for name, iid in sorted(self._ball_n2i.items(), key=lambda kv: kv[0])],
            width=22,
            state="readonly",
        )
        self.cb_ball.grid(row=2, column=1, sticky=tk.W)

        # Note: Changes are automatically applied to memory as you edit

    def _build_trainer_basics(self, parent: ttk.Frame):
        debug_log("_build_trainer_basics called - using safe approach")
        parent.grid_columnconfigure(1, weight=1)
        # Add bottom spacer to expand vertically like other tabs
        parent.grid_rowconfigure(99, weight=1)

        # Party reordering section (team management)
        self._build_party_reorder_section(parent)

        ttk.Label(parent, text="Money:").grid(row=4, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_money = tk.StringVar(value="")
        ent = ttk.Entry(parent, textvariable=self.var_money, width=12)
        ent.grid(row=4, column=1, sticky=tk.W)
        # Bind money changes to automatically update data
        self.var_money.trace_add("write", lambda *args: self._on_money_change())
        ent.bind("<KeyRelease>", lambda e: self._on_money_change())

        # Defer weather catalog initialization to avoid blocking UI
        debug_log("Deferring weather catalog initialization...")
        self.after_idle(self._init_weather_catalog_safe)

        ttk.Label(parent, text="Weather:").grid(row=5, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_weather = tk.StringVar(value="")
        self.cb_weather = ttk.Combobox(
            parent,
            textvariable=self.var_weather,
            values=[],  # Will be populated safely later
            width=24,
            state="readonly",
        )
        self.cb_weather.grid(row=5, column=1, sticky=tk.W)
        # Bind weather changes to automatically update data
        self.var_weather.trace_add("write", lambda *args: self._on_weather_change())
        self.cb_weather.bind("<<ComboboxSelected>>", lambda e: self._on_weather_change())
        ttk.Button(parent, text="Full Team Heal (Local)", command=self._full_team_heal).grid(row=5, column=3, sticky=tk.W, padx=6)
        # Quick open items/modifiers manager
        ttk.Button(parent, text="Open Modifiers / Items…", command=self._open_item_mgr_trainer).grid(row=6, column=1, sticky=tk.W, pady=(8, 0))
        # Display-only Play Time and Game Mode (combined on same row)
        ttk.Label(parent, text="Play Time:").grid(row=7, column=0, sticky=tk.E, padx=6)
        self.lbl_playtime = ttk.Label(parent, text="-")
        self.lbl_playtime.grid(row=7, column=1, sticky=tk.W)
        # Keep Game Mode on the same visual row as its label by using an inner frame
        gm_row = ttk.Frame(parent)
        gm_row.grid(row=7, column=2, columnspan=2, sticky=tk.W, padx=6)
        ttk.Label(gm_row, text="Game Mode:").pack(side=tk.LEFT)
        self.lbl_gamemode = ttk.Label(gm_row, text="-")
        self.lbl_gamemode.pack(side=tk.LEFT, padx=(4, 0))

        # Spacer to expand vertically like other tabs
        ttk.Label(parent, text="").grid(row=99, column=0, sticky=tk.EW)
        
        # Defer trainer data loading to avoid blocking UI
        self.after_idle(self._load_trainer_snapshot_safe)
        
        debug_log("_build_trainer_basics completed safely")

    def _init_weather_catalog_safe(self):
        """Safely initialize weather catalog with caching to avoid blocking UI."""
        try:
            # Check if already cached
            if hasattr(self, '_weather_n2i') and hasattr(self, '_weather_i2n'):
                return

            debug_log("Loading weather catalog safely...")
            # Use cached loading approach
            if hasattr(self, '_weather_catalog_cache'):
                self._weather_n2i, self._weather_i2n = self._weather_catalog_cache
            else:
                from rogueeditor.catalog import load_weather_catalog
                try:
                    self._weather_n2i, self._weather_i2n = load_weather_catalog()
                    # Cache the result
                    self._weather_catalog_cache = (self._weather_n2i, self._weather_i2n)
                except Exception:
                    self._weather_n2i, self._weather_i2n = ({}, {})
                    self._weather_catalog_cache = ({}, {})

            # Update combobox values safely using after_idle
            if hasattr(self, 'cb_weather'):
                values = [f"{name} ({iid})" for name, iid in sorted(self._weather_n2i.items(), key=lambda kv: kv[0])]
                self.after_idle(lambda: self._update_weather_combobox_safe(values))

            debug_log("Weather catalog initialized safely")
        except Exception as e:
            debug_log(f"Error in safe weather catalog init: {e}")
            self._weather_n2i, self._weather_i2n = ({}, {})

    def _update_weather_combobox_safe(self, values):
        """Safely update weather combobox values without blocking UI."""
        try:
            if hasattr(self, 'cb_weather'):
                self.cb_weather['values'] = values
        except Exception as e:
            debug_log(f"Error updating weather combobox: {e}")

    def _build_defensive_analysis(self, parent: ttk.Frame):
        """Build the defensive analysis section."""
        # Control button at top
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill=tk.X, padx=6, pady=(6, 0))
        ttk.Button(control_frame, text="Recompute Analysis", command=self._recompute_team_summary).pack(side=tk.LEFT)

        # Main content area
        content_frame = ttk.Frame(parent)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=6)
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=4)

        # Note about scope
        ttk.Label(content_frame, text="Team defensive analysis. Shows how incoming attacks affect the team. Ignores abilities, passives, held items, and special forms like Mega/Tera.", foreground="gray").grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=6, pady=(4,2))

        # Team members (left)
        members_lf = ttk.LabelFrame(content_frame, text="Team Members")
        members_lf.grid(row=1, column=0, rowspan=7, sticky=tk.NSEW, padx=6, pady=6)
        self._team_members_frame = ttk.Frame(members_lf)
        self._team_members_frame.pack(fill=tk.BOTH, expand=True)
        # Defensive summary bins (right, vertically stacked)
        sections = [("Immune (x0)", "immune"), ("x0.25", "x0_25"), ("x0.5", "x0_5"), ("x1", "x1"), ("x2", "x2"), ("x4", "x4")]
        self._team_bins = {}
        for i, (title, key) in enumerate(sections):
            lf = ttk.LabelFrame(content_frame, text=title)
            lf.grid(row=i+1, column=1, sticky=tk.NSEW, padx=6, pady=2)
            inner = ttk.Frame(lf)
            inner.pack(fill=tk.BOTH, expand=True)
            self._team_bins[key] = inner

        # Defensive risks (bottom spanning)
        risks_lf = ttk.LabelFrame(content_frame, text="Defensive Weaknesses & Risks")
        risks_lf.grid(row=7, column=0, columnspan=2, sticky=tk.EW, padx=6, pady=(0,6))
        self._team_risks_frame = ttk.Frame(risks_lf)
        self._team_risks_frame.pack(fill=tk.X, anchor=tk.W, padx=6, pady=4)

    def _build_offensive_analysis(self, parent: ttk.Frame):
        """Build the offensive analysis section."""
        # Control button at top
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill=tk.X, padx=6, pady=(6, 0))
        ttk.Button(control_frame, text="Recompute Analysis", command=self._compute_team_offensive_coverage).pack(side=tk.LEFT)

        # Note about scope
        ttk.Label(parent, text="Team offensive analysis. Shows type coverage based on damaging moves across all team members.", foreground="gray").pack(anchor=tk.W, padx=6, pady=(4,2))

        # Create main content frame (no scrolling needed with current layout)
        self._team_offense_frame = ttk.Frame(parent)
        self._team_offense_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Create top row with moves and coverage side by side
        top_row = ttk.Frame(self._team_offense_frame)
        top_row.pack(fill=tk.X, padx=6, pady=6)
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=1)

        # 1. Damaging Moves per Team Member (left column)
        moves_lf = ttk.LabelFrame(top_row, text="Damaging Moves by Team Member")
        moves_lf.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6), pady=0)
        self._team_moves_frame = ttk.Frame(moves_lf)
        self._team_moves_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # 2. Team Type Coverage Analysis (right column)
        coverage_lf = ttk.LabelFrame(top_row, text="Team Type Coverage")
        coverage_lf.grid(row=0, column=1, sticky=tk.NSEW, padx=(6, 0), pady=0)
        self._team_coverage_frame = ttk.Frame(coverage_lf)
        self._team_coverage_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Create coverage bins (similar to individual Pokemon but with multipliers)
        self._team_coverage_bins = {}
        coverage_sections = [
            ("Super Effective (x2+)", "super_effective", "green"),
            ("Neutral (x1)", "neutral", "gray"),
            ("Not Very Effective (x0.5)", "not_very_effective", "orange"),
            ("No Effect (x0)", "no_effect", "red")
        ]

        for title, key, color in coverage_sections:
            section_frame = ttk.LabelFrame(self._team_coverage_frame, text=title)
            section_frame.pack(fill=tk.X, pady=2)
            inner_frame = ttk.Frame(section_frame)
            inner_frame.pack(fill=tk.X, padx=6, pady=4)
            self._team_coverage_bins[key] = inner_frame

        # Create second row with boss analysis and walls side by side
        bottom_row = ttk.Frame(self._team_offense_frame)
        bottom_row.pack(fill=tk.X, padx=6, pady=(8, 6))
        bottom_row.grid_columnconfigure(0, weight=1)
        bottom_row.grid_columnconfigure(1, weight=1)

        # 3. Boss Coverage Analysis (left column) - constrained height
        boss_lf = ttk.LabelFrame(bottom_row, text="Boss Coverage Analysis")
        boss_lf.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6), pady=0)
        boss_lf.grid_rowconfigure(0, weight=0)  # Don't expand vertically
        self._team_boss_frame = ttk.Frame(boss_lf)
        self._team_boss_frame.pack(fill=tk.X, padx=6, pady=6)

        # 4. Team Walls Analysis (right column) - constrained height with scrolling
        walls_lf = ttk.LabelFrame(bottom_row, text="Type Combinations that Wall the Team")
        walls_lf.grid(row=0, column=1, sticky=tk.NSEW, padx=(6, 0), pady=0)
        walls_lf.grid_rowconfigure(0, weight=0)  # Don't expand vertically

        # Create scrollable container for walls analysis with dynamic height
        walls_canvas = tk.Canvas(walls_lf, highlightthickness=0)
        walls_scrollbar = ttk.Scrollbar(walls_lf, orient="vertical", command=walls_canvas.yview)
        self._team_walls_frame = ttk.Frame(walls_canvas)

        def _update_team_walls_scroll_region(event=None):
            walls_canvas.configure(scrollregion=walls_canvas.bbox("all"))
            # Update canvas height based on content, with min/max bounds
            content_height = self._team_walls_frame.winfo_reqheight()
            canvas_height = min(max(content_height, 100), 400)  # Min 100px, max 400px
            walls_canvas.configure(height=canvas_height)

        self._team_walls_frame.bind("<Configure>", _update_team_walls_scroll_region)

        walls_canvas.create_window((0, 0), window=self._team_walls_frame, anchor="nw")
        walls_canvas.configure(yscrollcommand=walls_scrollbar.set)

        walls_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        walls_scrollbar.pack(side="right", fill="y", pady=6)

        # 5. Legend (full width at bottom)
        legend_frame = ttk.Frame(self._team_offense_frame)
        legend_frame.pack(fill=tk.X, padx=6, pady=(6, 6))

        legend_text = ("Legend: ❌ = No coverage  •  ⚠️ = Risk (one team member only)  •  "
                      "CRITICAL = No effect or resisted  •  CONCERN = Neutral at best  •  "
                      "RISK = Single member coverage  •  (fire×2) = 2 team members have fire moves")
        ttk.Label(legend_frame, text=legend_text, foreground="gray",
                 font=('TkDefaultFont', 8), wraplength=800).pack(anchor=tk.W, padx=6, pady=4)

    def _show_loading_indicator(self, message: str = "Computing analysis..."):
        """Show enhanced loading indicator during heavy calculations."""
        try:
            # Create or update loading frame with better styling
            if not hasattr(self, '_loading_frame'):
                # Create main loading overlay
                self._loading_frame = ttk.Frame(self)
                self._loading_frame.place(relx=0.5, rely=0.5, anchor='center')

                # Enhanced background with better visual appeal
                bg_frame = ttk.Frame(self._loading_frame, relief='ridge', borderwidth=2)
                bg_frame.pack(padx=25, pady=20)

                # Loading icon/spinner area
                icon_frame = ttk.Frame(bg_frame)
                icon_frame.pack(pady=(15, 5))

                self._loading_label = ttk.Label(bg_frame, text=message,
                                               font=('TkDefaultFont', 10, 'bold'))
                self._loading_label.pack(padx=20, pady=(5, 10))

                # Enhanced progress bar with better styling
                self._progress_bar = ttk.Progressbar(bg_frame, mode='indeterminate',
                                                   length=250, style="TProgressbar")
                self._progress_bar.pack(padx=20, pady=(0, 15))

                # Status label for detailed feedback
                self._status_label = ttk.Label(bg_frame, text="Initializing...",
                                             font=('TkDefaultFont', 8), foreground='gray')
                self._status_label.pack(padx=20, pady=(0, 10))

                # Cancel button for long operations (if needed)
                # self._cancel_button = ttk.Button(bg_frame, text="Cancel",
                #                                command=self._cancel_operation)
                # self._cancel_button.pack(pady=(0, 10))
            else:
                self._loading_label.configure(text=message)
                if hasattr(self, '_status_label'):
                    self._status_label.configure(text="Processing...")

            # Bring to front and start animation
            self._loading_frame.lift()
            self._progress_bar.start(8)  # Slightly smoother animation
            self.update_idletasks()

            # Track start time for progress feedback
            self._loading_start_time = time.time()

        except Exception:
            pass  # Fail silently for loading indicators

    def _hide_loading_indicator(self):
        """Hide loading indicator with completion feedback."""
        try:
            if hasattr(self, '_loading_frame'):
                # Show completion feedback briefly before hiding
                if hasattr(self, '_status_label') and hasattr(self, '_loading_start_time'):
                    duration = time.time() - self._loading_start_time
                    if duration > 0.5:  # Only show timing for operations > 0.5s
                        self._status_label.configure(text=f"Completed in {duration:.1f}s")
                        self._loading_label.configure(text="Complete!")
                        self.update_idletasks()
                        # Brief pause to show completion
                        self.after(300, self._actually_hide_loading)
                    else:
                        self._actually_hide_loading()
                else:
                    self._actually_hide_loading()
        except Exception:
            pass

    def _actually_hide_loading(self):
        """Actually hide the loading indicator."""
        try:
            if hasattr(self, '_loading_frame'):
                self._progress_bar.stop()
                self._loading_frame.place_forget()
        except Exception:
            pass

    def _update_loading_status(self, status: str):
        """Update the loading status message for better user feedback."""
        try:
            if hasattr(self, '_status_label'):
                self._status_label.configure(text=status)
                self.update_idletasks()
        except Exception:
            pass

    def _recompute_team_summary(self):
        """Recompute team summary with loading feedback."""
        self._show_loading_indicator("Computing team defensive analysis...")
        try:
            # Small delay to ensure loading indicator shows
            self.after_idle(self._do_recompute_team_summary)
        except Exception as e:
            self._hide_loading_indicator()
            print(f"Error starting team summary computation: {e}")

    def _do_recompute_team_summary(self):
        try:
            # Check for background cache first
            cached_data = self._get_cached_analysis_data()
            if cached_data and not cached_data.get("error"):
                print("Using background cache for team summary")
                self._apply_cached_team_analysis_from_background(cached_data)
                self._hide_loading_indicator()
                return

            # Use cached resources and smart invalidation
            self._invalidate_caches_if_needed()

            # Check for cached team analysis
            team_hash = self._compute_team_hash()
            if team_hash in self._team_analysis_cache:
                cached_analysis = self._team_analysis_cache[team_hash]
                self._apply_cached_team_analysis(cached_analysis)
                self._hide_loading_indicator()
                return

            mat = self._get_cached_type_matrix()
            types = sorted(mat.keys())
            # Build per-attack-type counts in exact bins
            bins_counts = {k: {t: 0 for t in types} for k in ("immune","x0_25","x0_5","x1","x2","x4")}
            cat = self._get_cached_pokemon_catalog()
            by_dex = cat.get("by_dex") or {}
            for mon in self.party:
                # use cached vector if available
                key = self.party.index(mon) if mon in self.party else id(mon)
                if key in getattr(self, "_matchup_cache", {}):
                    mults = self._matchup_cache[key]
                else:
                    entry = by_dex.get(str(_get_species_id(mon) or -1)) or {}
                    fslug = self._detect_form_slug(mon)
                    if fslug and (entry.get("forms") or {}).get(fslug):
                        tp = (entry.get("forms") or {}).get(fslug, {}).get("types") or {}
                    else:
                        tp = entry.get("types") or {}
                    t1k = str(tp.get("type1") or "unknown").strip().lower()
                    t2v = tp.get("type2")
                    t2k = str(t2v or "").strip().lower() if t2v else None
                    mults = {}
                    for atk in types:
                        v1 = float((mat.get(t1k) or {}).get(atk, 1.0))
                        v2 = float((mat.get(t2k) or {}).get(atk, 1.0)) if t2k else 1.0
                        mults[atk] = v1 * v2
                    self._matchup_cache[key] = mults
                for atk, eff in mults.items():
                    if eff == 0:
                        bins_counts["immune"][atk] += 1
                    elif eff == 0.25 or eff == 0.125:
                        bins_counts["x0_25"][atk] += 1
                    elif eff == 0.5:
                        bins_counts["x0_5"][atk] += 1
                    elif eff == 1:
                        bins_counts["x1"][atk] += 1
                    elif eff == 2:
                        bins_counts["x2"][atk] += 1
                    elif eff >= 4:
                        bins_counts["x4"][atk] += 1
            # Render chips
            for key, frame in self._team_bins.items():
                for w in list(frame.winfo_children()):
                    w.destroy()
                # Build chips with wrapping rows
                labels = []
                bgs = []
                for atk in types:
                    c = bins_counts[key][atk]
                    if c <= 0:
                        continue
                    labels.append(f"{atk.title()} ×{c}")
                    bgs.append(self._color_for_type(atk))
                self._render_type_chips(frame, labels, bgs, per_row=6)
            # Top risks summary: qualify if (2x >=3) OR (4x >=1 and 2x >=1). Render chips with counts.
            risks = []
            for atk in types:
                c4 = bins_counts["x4"][atk]
                c2 = bins_counts["x2"][atk]
                if (c2 >= 3) or (c4 >= 1 and c2 >= 1):
                    risks.append((c4, c2, atk))
            # Clear previous
            for w in list(self._team_risks_frame.winfo_children()):
                w.destroy()
            if risks:
                risks.sort(key=lambda t: (t[0], t[1]), reverse=True)
                labels = []
                bgs = []
                for c4, c2, atk in risks:
                    segs = []
                    if c4:
                        segs.append(f"(4x{c4})")
                    if c2:
                        segs.append(f"(2x{c2})")
                    label = f"{atk.title()}" + "".join(segs)
                    labels.append(label)
                    bgs.append(self._color_for_type(atk))
                self._render_type_chips(self._team_risks_frame, labels, bgs, per_row=6)
            else:
                ttk.Label(self._team_risks_frame, text="No major overlapping weaknesses detected.").pack(anchor=tk.W)
            # Render team members list with their own type chips
            for w in list(self._team_members_frame.winfo_children()):
                w.destroy()
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            for idx, mon in enumerate(self.party, start=1):
                try:
                    block = ttk.Frame(self._team_members_frame)
                    block.pack(fill=tk.X, padx=6, pady=4)
                    # First line: index, DEX, Species
                    top = ttk.Frame(block)
                    top.pack(fill=tk.X)
                    did = int(_get_species_id(mon) or -1)
                    entry = by_dex.get(str(did)) or {}
                    name = entry.get("name") or str(did)
                    fslug = self._detect_form_slug(mon)
                    ttk.Label(top, text=f"{idx}. {did:04d} {name}").pack(side=tk.LEFT)
                    # type chips on same line
                    tp = (entry.get("forms") or {}).get(fslug, {}).get("types") if fslug and (entry.get("forms") or {}).get(fslug) else (entry.get("types") or {})
                    t1 = str((tp or {}).get("type1") or "").lower()
                    t2 = str((tp or {}).get("type2") or "").lower() if (tp or {}).get("type2") else ""
                    chip_frame = ttk.Frame(top)
                    chip_frame.pack(side=tk.LEFT, padx=8)
                    labels = [x.title() for x in [t1, t2] if x]
                    bgs = [self._color_for_type(x) for x in [t1, t2] if x]
                    self._render_type_chips(chip_frame, labels, bgs, per_row=6)
                    # Optional second line for special forms
                    if fslug:
                        form_line = ttk.Frame(block)
                        form_line.pack(fill=tk.X)
                        friendly = self._friendly_form_name(fslug, entry) or fslug.title()
                        ttk.Label(form_line, text=f"Form: {friendly}", foreground="gray").pack(side=tk.LEFT, padx=24)
                except Exception:
                    continue

            # Compute team offensive matchups
            self._compute_team_offensive_coverage()
        except Exception:
            pass
        finally:
            # Always hide loading indicator
            self._hide_loading_indicator()

    def _compute_team_offensive_coverage(self):
        """Compute and display team-wide offensive matchups."""
        self._show_loading_indicator("Computing team offensive coverage...")
        try:
            # Clear existing sections
            for widget in self._team_moves_frame.winfo_children():
                widget.destroy()
            for bin_frame in self._team_coverage_bins.values():
                for widget in bin_frame.winfo_children():
                    widget.destroy()
            for widget in self._team_boss_frame.winfo_children():
                widget.destroy()
            for widget in self._team_walls_frame.winfo_children():
                widget.destroy()

            if not self.party:
                ttk.Label(self._team_moves_frame, text="No Pokemon in party",
                         foreground="gray").pack(anchor=tk.W)
                return

            # Import coverage calculator and catalog
            from rogueeditor.coverage_calculator import (
                OffensiveCoverageCalculator, get_coverage_for_team,
                find_type_combo_walls, load_type_matrix_v2
            )
            from rogueeditor.catalog import load_pokemon_catalog

            calculator = OffensiveCoverageCalculator()
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}

            # 1. DAMAGING MOVES PER TEAM MEMBER (Two-column layout for compactness)
            has_moves = False
            pokemon_data = []

            # Collect all Pokemon with their moves first
            for i, mon in enumerate(self.party, 1):
                # Extract moves from Pokemon
                moves = mon.get("moveset", []) or mon.get("moves", [])
                move_ids = []
                for move in moves:
                    if isinstance(move, dict):
                        move_id = move.get("moveId")
                        if move_id is not None:
                            move_ids.append(move_id)
                    elif isinstance(move, int):
                        move_ids.append(move)

                if not move_ids:
                    continue

                # Get Pokemon coverage to find damaging moves
                coverage = calculator.get_pokemon_coverage(move_ids, str(mon.get("id", f"pokemon_{i}")))
                damaging_moves = coverage.get("damaging_moves", [])

                if not damaging_moves:
                    continue

                has_moves = True

                # Get species name
                species_id = _get_species_id(mon)
                entry = by_dex.get(str(species_id or -1)) or {}
                species_name = entry.get("name", f"Species_{species_id}")

                pokemon_data.append((i, species_name, damaging_moves[:4]))

            if has_moves:
                # Display Pokemon with names above and moves below horizontally
                moves_container = ttk.Frame(self._team_moves_frame)
                moves_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

                for pokemon_num, species_name, damaging_moves in pokemon_data:
                    mon_frame = ttk.Frame(moves_container)
                    mon_frame.pack(fill=tk.X, pady=4)

                    # Pokemon name on its own line
                    ttk.Label(mon_frame, text=f"{pokemon_num}. {species_name}",
                             font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W)

                    # Moves as horizontal chips below the name
                    moves_row = ttk.Frame(mon_frame)
                    moves_row.pack(fill=tk.X, padx=12, pady=(2, 0))

                    for move in damaging_moves:
                        move_name = move.get("name", "Unknown")
                        move_type = move.get("type", "unknown")

                        # Use move name in chip instead of type name
                        move_chip = tk.Label(moves_row, text=move_name,
                                           bg=self._color_for_type(move_type),
                                           bd=1, relief=tk.SOLID, padx=3, pady=1,
                                           font=('TkDefaultFont', 8))
                        move_chip.pack(side=tk.LEFT, padx=(0, 2), pady=1)
            else:
                ttk.Label(self._team_moves_frame, text="No damaging moves found in team",
                         foreground="gray").pack(anchor=tk.W, padx=6, pady=6)

            # 2. TEAM TYPE COVERAGE ANALYSIS WITH MULTIPLIERS
            team_coverage = get_coverage_for_team(self.party)
            coverage_summary = team_coverage.get("coverage_summary", {})

            # Count how many Pokemon have each attacking type
            all_team_move_types = {}  # type_name -> count
            for mon in self.party:
                moves = mon.get("moveset", []) or mon.get("moves", [])
                move_ids = []
                for move in moves:
                    if isinstance(move, dict) and move.get("moveId") is not None:
                        move_ids.append(move.get("moveId"))
                    elif isinstance(move, int):
                        move_ids.append(move)

                if move_ids:
                    coverage = calculator.get_pokemon_coverage(move_ids)
                    move_types = coverage.get("coverage_summary", {}).get("move_types", [])
                    for move_type in move_types:
                        all_team_move_types[move_type] = all_team_move_types.get(move_type, 0) + 1

            # Get all defensive types from type matrix to analyze coverage properly
            type_matrix = self._get_cached_type_matrix()
            all_defensive_types = sorted([k for k in type_matrix.keys() if isinstance(type_matrix.get(k), dict)])

            # Calculate team coverage properly by finding best effectiveness for each defending type
            team_coverage_by_defender = {}
            team_coverage_contributors = {}  # Track which attacking types contribute to each defender

            for defending_type in all_defensive_types:
                best_effectiveness = 0.0
                contributing_types = []

                for att_type, count in all_team_move_types.items():
                    from rogueeditor.coverage_calculator import get_type_effectiveness
                    eff = get_type_effectiveness(att_type, [defending_type], type_matrix)
                    if eff > best_effectiveness:
                        best_effectiveness = eff

                    # Track all contributing types with their counts
                    if eff >= 1.0:  # Neutral or better
                        contributing_types.append((att_type, count, eff))

                team_coverage_by_defender[defending_type] = best_effectiveness
                team_coverage_contributors[defending_type] = contributing_types

            # Categorize defending types by effectiveness
            coverage_bins = {
                "super_effective": [],
                "neutral": [],
                "not_very_effective": [],
                "no_effect": []
            }

            risk_types = []  # Types covered by only one team member

            for defending_type, best_eff in team_coverage_by_defender.items():
                # Count unique team members that can hit this type effectively
                contributors = team_coverage_contributors[defending_type]
                total_contributors = sum(count for _, count, eff in contributors if eff >= 1.0)

                # Risk detection: only one team member can handle this type
                if total_contributors == 1:
                    risk_types.append(defending_type)

                # Categorize by effectiveness
                if best_eff >= 2.0:
                    coverage_bins["super_effective"].append(defending_type)
                elif best_eff == 1.0:
                    coverage_bins["neutral"].append(defending_type)
                elif best_eff > 0.0:
                    coverage_bins["not_very_effective"].append(defending_type)
                else:
                    coverage_bins["no_effect"].append(defending_type)

            # Render coverage bins with proper attacking type information
            for bin_key, types_list in coverage_bins.items():
                bin_frame = self._team_coverage_bins[bin_key]
                if types_list:
                    labels = []
                    colors = []

                    for type_name in types_list:
                        # Get contributors for this defending type in this effectiveness category
                        contributors = team_coverage_contributors.get(type_name, [])
                        relevant_contributors = []

                        for att_type, count, eff in contributors:
                            if bin_key == "super_effective" and eff >= 2.0:
                                relevant_contributors.append(f"{att_type}×{count}")
                            elif bin_key == "neutral" and eff == 1.0:
                                relevant_contributors.append(f"{att_type}×{count}")
                            elif bin_key == "not_very_effective" and 0.0 < eff < 1.0:
                                relevant_contributors.append(f"{att_type}×{count}")

                        # Build label with risk indicator
                        risk_indicator = " ⚠" if type_name in risk_types else ""
                        if relevant_contributors:
                            label = f"{type_name.title()} ({', '.join(relevant_contributors[:2])}){risk_indicator}"
                        else:
                            label = f"{type_name.title()}{risk_indicator}"

                        labels.append(label)
                        colors.append(self._color_for_type(type_name))

                    if labels:
                        self._render_type_chips(bin_frame, labels, colors, per_row=3)  # 3 per row as requested
                    else:
                        ttk.Label(bin_frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            # 3. BOSS ANALYSIS WITH TYPE CHIPS
            team_boss_analysis = team_coverage.get("team_boss_analysis", {})
            if team_boss_analysis:
                for boss_key, analysis in team_boss_analysis.items():
                    boss_row = ttk.Frame(self._team_boss_frame)
                    boss_row.pack(fill=tk.X, padx=5, pady=3)

                    boss_name = analysis.get("name", boss_key.title())
                    status = analysis.get("status", "unknown")
                    effectiveness = analysis.get("best_effectiveness", 0)
                    best_pokemon = analysis.get("best_pokemon", -1)
    
                    # Boss name and evaluation
                    name_label = ttk.Label(boss_row, text=f"{boss_name}:",
                                         font=('TkDefaultFont', 9, 'bold'))
                    name_label.pack(side=tk.LEFT, padx=(0, 8))
    
                    # Boss type chips
                    boss_types = analysis.get("types", [])
                    if boss_types:
                        type_frame = ttk.Frame(boss_row)
                        type_frame.pack(side=tk.LEFT, padx=(0, 8))
    
                        for boss_type in boss_types:
                            type_chip = tk.Label(type_frame, text=boss_type.title(),
                                               bg=self._color_for_type(boss_type),
                                               bd=1, relief=tk.SOLID, padx=4, pady=1)
                            type_chip.pack(side=tk.LEFT, padx=1)
    
                    # Status and effectiveness
                    status_colors = {
                        "excellent": "green", "good": "blue", "ok": "#FFC107",
                        "poor": "orange", "none": "red"
                    }
                    color = status_colors.get(status, "gray")
    
                    # Build a comma-separated list of team member names that achieve the best effectiveness
                    contributors = []
                    try:
                        cov_list = analysis.get("pokemon_coverages", []) or []
                        # small epsilon for float compare
                        eps = 1e-6
                        from rogueeditor.catalog import load_pokemon_index
                        by_dex = load_pokemon_index()
                        for cov in cov_list:
                            try:
                                idx = int(cov.get("pokemon_index", -1))
                                peff = float(cov.get("best_effectiveness", 0.0))
                            except Exception:
                                continue
                            if idx < 0 or idx >= len(self.party):
                                continue
                            if abs(peff - float(effectiveness)) > eps:
                                continue
                            mon = self.party[idx]
                            species_id = _get_species_id(mon)
                            entry = by_dex.get(str(species_id or -1)) or {}
                            name = entry.get("name") or f"Species_{species_id}"
                            contributors.append(str(name))
                    except Exception:
                        contributors = []
    
                    suffix = f" ({', '.join(contributors)})" if contributors else ""
                    status_text = f"{status.title()}: x{effectiveness:.1f}{suffix}"
                    ttk.Label(boss_row, text=status_text, foreground=color).pack(side=tk.LEFT)
            else:
                ttk.Label(self._team_boss_frame, text="No boss analysis available",
                         foreground="gray").pack(anchor=tk.W, padx=5, pady=5)

            # 4. ENHANCED TEAM WALLS ANALYSIS WITH COVERAGE DETAILS
            if all_team_move_types:
                type_matrix = self._get_cached_type_matrix()
                move_types_list = list(all_team_move_types.keys())

                # Analyze coverage for critical types
                types_with_no_se = []  # No super effective coverage
                types_with_one_se = []  # Only one team member has super effective coverage
                types_neutral_at_best = []  # Best we can do is neutral (1.0x)
                types_resisted_at_best = []  # Best we can do is resisted (<1.0x) - WORST CASE

                for defending_type in all_defensive_types:
                    super_effective_count = 0
                    se_contributors = []
                    best_effectiveness = 0.0

                    for att_type, count in all_team_move_types.items():
                        from rogueeditor.coverage_calculator import get_type_effectiveness
                        eff = get_type_effectiveness(att_type, [defending_type], type_matrix)
                        if eff >= 2.0:
                            super_effective_count += count
                            se_contributors.append((att_type, count))
                        if eff > best_effectiveness:
                            best_effectiveness = eff

                    if super_effective_count == 0:
                        # No super effective coverage, categorize by best available
                        if best_effectiveness == 0.0:
                            types_with_no_se.append(defending_type)  # No effect at all
                        elif best_effectiveness < 1.0:
                            types_resisted_at_best.append(defending_type)  # Resisted at best
                        elif best_effectiveness == 1.0:
                            types_neutral_at_best.append(defending_type)  # Neutral at best
                    elif super_effective_count == 1:
                        types_with_one_se.append((defending_type, se_contributors[0]))

                # Show critical coverage gaps first (most severe to least severe)

                # 1. No effect at all (most critical)
                if types_with_no_se:
                    no_se_frame = ttk.Frame(self._team_walls_frame)
                    no_se_frame.pack(fill=tk.X, padx=5, pady=5)
                    ttk.Label(no_se_frame, text="❌ CRITICAL: No effect at all against:",
                             font=('TkDefaultFont', 9, 'bold'), foreground="red").pack(anchor=tk.W)

                    labels = [t.title() for t in types_with_no_se]  # Show all
                    colors = [self._color_for_type(t) for t in types_with_no_se]
                    chips_frame = ttk.Frame(no_se_frame)
                    chips_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
                    self._render_type_chips(chips_frame, labels, colors, per_row=6)

                # 2. Resisted at best (second most critical)
                if types_resisted_at_best:
                    resisted_frame = ttk.Frame(self._team_walls_frame)
                    resisted_frame.pack(fill=tk.X, padx=5, pady=5)
                    ttk.Label(resisted_frame, text="⚠️ CRITICAL: Best coverage is resisted against:",
                             font=('TkDefaultFont', 9, 'bold'), foreground="red").pack(anchor=tk.W)

                    labels = [t.title() for t in types_resisted_at_best]  # Show all
                    colors = [self._color_for_type(t) for t in types_resisted_at_best]
                    chips_frame = ttk.Frame(resisted_frame)
                    chips_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
                    self._render_type_chips(chips_frame, labels, colors, per_row=6)

                # 3. Neutral at best (concerning but not critical)
                if types_neutral_at_best:
                    neutral_frame = ttk.Frame(self._team_walls_frame)
                    neutral_frame.pack(fill=tk.X, padx=5, pady=5)
                    ttk.Label(neutral_frame, text="⚠️ CONCERN: Best coverage is neutral against:",
                             font=('TkDefaultFont', 9, 'bold'), foreground="orange").pack(anchor=tk.W)

                    labels = [t.title() for t in types_neutral_at_best]  # Show all
                    colors = [self._color_for_type(t) for t in types_neutral_at_best]
                    chips_frame = ttk.Frame(neutral_frame)
                    chips_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
                    self._render_type_chips(chips_frame, labels, colors, per_row=6)

                # 4. Only one member has super effective coverage (risk)
                if types_with_one_se:
                    one_se_frame = ttk.Frame(self._team_walls_frame)
                    one_se_frame.pack(fill=tk.X, padx=5, pady=5)
                    ttk.Label(one_se_frame, text="⚠️ RISK: Only one team member has super effective coverage:",
                             font=('TkDefaultFont', 9, 'bold'), foreground="orange").pack(anchor=tk.W)

                    labels = []
                    colors = []
                    for defending_type, (att_type, count) in types_with_one_se:  # Show all
                        label = f"{defending_type.title()} ({att_type}×{count})"
                        labels.append(label)
                        colors.append(self._color_for_type(defending_type))

                    chips_frame = ttk.Frame(one_se_frame)
                    chips_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
                    self._render_type_chips(chips_frame, labels, colors, per_row=3)

                # Traditional walls analysis (types that resist most moves)
                walls = find_type_combo_walls(move_types_list, type_matrix)
                dual_walls = walls.get("dual", [])
                single_walls = walls.get("single", [])

                if dual_walls or single_walls:
                    # Add separator if we showed critical types
                    if types_with_no_se or types_with_one_se:
                        separator = ttk.Separator(self._team_walls_frame, orient='horizontal')
                        separator.pack(fill=tk.X, padx=5, pady=10)
    
                    if dual_walls:
                        dual_frame = ttk.Frame(self._team_walls_frame)
                        dual_frame.pack(fill=tk.X, padx=5, pady=5)
                        ttk.Label(dual_frame, text="Type combinations that resist most team moves:",
                                 font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W)

                        # Analyze coverage for each dual type combination
                        dual_analysis = []
                        for type1, type2 in dual_walls:  # Show all dual type combinations
                            # Find what team moves can hit this combo effectively (>= 1.0)
                            effective_moves = []
                            for att_type, count in all_team_move_types.items():
                                from rogueeditor.coverage_calculator import get_type_effectiveness
                                eff = get_type_effectiveness(att_type, [type1, type2], type_matrix)
                                if eff >= 1.0:
                                    effective_moves.append((att_type, count, eff))

                            coverage_info = ""
                            if not effective_moves:
                                coverage_info = " ❌"  # No coverage
                            elif len(effective_moves) == 1 and effective_moves[0][1] == 1:
                                att_type, _, eff = effective_moves[0]
                                coverage_info = f" ⚠️{att_type}×1"  # Only one member
                            elif len(effective_moves) <= 2:
                                # Show up to 2 effective types
                                moves_str = ",".join([f"{att}×{cnt}" for att, cnt, _ in effective_moves[:2]])
                                coverage_info = f" ({moves_str})"

                            dual_analysis.append((type1, type2, coverage_info))

                        # Render dual type combinations with coverage info
                        combo_row = ttk.Frame(dual_frame)
                        combo_row.pack(fill=tk.X, padx=10, pady=(2, 0))

                        for type1, type2, coverage_info in dual_analysis:
                            combo_frame = ttk.Frame(combo_row)
                            combo_frame.pack(side=tk.LEFT, padx=3, pady=1)

                            container = ttk.Frame(combo_frame)
                            container.pack()

                            types_frame = ttk.Frame(container)
                            types_frame.pack(side=tk.LEFT)

                            tk.Label(types_frame, text="[", bd=0, font=('TkDefaultFont', 8)).pack(side=tk.LEFT)
                            tk.Label(types_frame, text=type1.title(),
                                   bg=self._color_for_type(type1),
                                   bd=1, relief=tk.SOLID, padx=2, pady=1,
                                   font=('TkDefaultFont', 8)).pack(side=tk.LEFT)
                            tk.Label(types_frame, text="/", bd=0, font=('TkDefaultFont', 8)).pack(side=tk.LEFT)
                            tk.Label(types_frame, text=type2.title(),
                                   bg=self._color_for_type(type2),
                                   bd=1, relief=tk.SOLID, padx=2, pady=1,
                                   font=('TkDefaultFont', 8)).pack(side=tk.LEFT)
                            tk.Label(types_frame, text="]", bd=0, font=('TkDefaultFont', 8)).pack(side=tk.LEFT)

                            if coverage_info:
                                tk.Label(container, text=coverage_info, font=('TkDefaultFont', 7),
                                       foreground="red" if "❌" in coverage_info else "orange" if "⚠️" in coverage_info else "gray").pack(side=tk.LEFT)
    
                if not (types_with_no_se or types_resisted_at_best or types_neutral_at_best or types_with_one_se or dual_walls or single_walls):
                    ttk.Label(self._team_walls_frame, text="🎯 Excellent type coverage - no major walls or gaps found!",
                             foreground="green", font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, padx=5, pady=5)
                else:
                    ttk.Label(self._team_walls_frame, text="No attacking moves found in team",
                             foreground="gray").pack(anchor=tk.W, padx=5, pady=5)

        except Exception as e:
            print(f"Error computing team offensive matchups: {e}")
            ttk.Label(self._team_moves_frame, text="Error computing coverage",
                     foreground="red").pack(anchor=tk.W)
        finally:
            # Always hide loading indicator
            self._hide_loading_indicator()

    # --- Data binding / refresh ---
    def _refresh_party(self):
        """Safe version of _refresh_party that avoids blocking operations."""
        debug_log("_refresh_party called - using safe version")

        # Only refresh if UI is built
        if not hasattr(self, 'party_list'):
            debug_log("No party_list found, skipping refresh")
            return

        try:
            # Capture generation to avoid restoring stale selections
            start_gen = int(getattr(self, '_selection_gen', 0))
            # Get previous selection safely
            try:
                # Prefer remembered index if available
                prev = int(getattr(self, '_last_selected_index', None))
                if prev is None:
                    prev = int(self.party_list.curselection()[0])
            except Exception:
                prev = 0

            # Clear and reset party list
            self.party_list.delete(0, tk.END)

            # Invalidate matchup cache on refresh
            try:
                self._matchup_cache = {}
            except Exception:
                pass

            # Use cached catalog data (avoid repeated I/O)
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            inv = invert_dex_map(self._pokemon_index_cache) if hasattr(self, '_pokemon_index_cache') else {}

            # Populate party list with minimal processing
            for i, mon in enumerate(self.party, start=1):
                try:
                    # Basic species info
                    did = str(_get(mon, ("species", "dexId", "speciesId", "pokemonId")) or "?")
                    entry = by_dex.get(did) or {}
                    name = entry.get("name") or inv.get(did, did)

                    # Simplified form detection (avoid complex processing)
                    try:
                        fslug = self._detect_form_slug(mon)
                        form_disp = None
                        if fslug:
                            forms = entry.get("forms") or {}
                            form_info = forms.get(fslug) or {}
                            fdn = form_info.get("display_name")
                            if isinstance(fdn, str) and fdn.strip():
                                form_disp = fdn
                    except Exception:
                        form_disp = None

                    # Build label: Name#0000 Level X (Form if applicable)
                    lvl = _get(mon, ("level", "lvl")) or "?"
                    base_name = name
                    if form_disp:
                        base_name = f"{name} ({form_disp})"
                    label = f"{base_name}#{int(did):04d} Level {lvl}"
                    self.party_list.insert(tk.END, label)

                except Exception as e:
                    debug_log(f"Error processing party member {i}: {e}")
                    # Add fallback entry
                    self.party_list.insert(tk.END, f"{i}. Pokemon #{i}")

            # Restore selection deterministically using helper
            if start_gen == int(getattr(self, '_selection_gen', 0)):
                target_idx = prev if prev < self.party_list.size() else 0
                self._set_party_selection(target_idx, render=not bool(self.party_list.curselection()))

            # Refresh party reordering section if it exists (simplified)
            try:
                if hasattr(self, 'party_reorder_frame'):
                    self._refresh_party_order_section()
            except Exception as e:
                debug_log(f"Error refreshing party reorder section: {e}")

            debug_log("_refresh_party completed successfully")

        except Exception as e:
            debug_log(f"Critical error in _refresh_party: {e}")
            # Ensure UI remains responsive even on error

    def _get_cached_pokemon_data(self, species_id: int, mon: Dict) -> Dict:
        """Get cached Pokemon data for faster switching."""
        if species_id in self._pokemon_data_cache:
            return self._pokemon_data_cache[species_id]
        
        # Load and cache data
        species_name = self._get_species_name(species_id)
        cached_data = {
            "species_name": species_name,
            "species_id": species_id,
            "level": mon.get("level", 1),
            "nickname": mon.get("nickname", "").strip()
        }
        
        self._pokemon_data_cache[species_id] = cached_data
        return cached_data

    def _select_pokemon_optimized(self, index: int):
        """Optimized Pokemon selection with caching."""
        if index == self._current_pokemon_index:
            return  # Already selected, no need to refresh
        
        self._current_pokemon_index = index
        self._select_pokemon(index)

    def _set_party_selection(self, index: int, render: bool = True, bump_gen: bool = True):
        """Unified selection setter with event suppression and state updates.
        When render=True and bump_gen=True, increments the selection generation to cancel stale renders.
        """
        try:
            if index is None:
                return
            total = self.party_list.size() if hasattr(self, 'party_list') else 0
            if total <= 0:
                return
            if index < 0:
                index = 0
            if index >= total:
                index = total - 1

            # Suppress event and set selection
            self._suppress_list_event = True
            self.party_list.selection_clear(0, tk.END)
            self.party_list.selection_set(index)
            self.party_list.activate(index)
            self.party_list.see(index)
            self._suppress_list_event = False

            # Update tracked indices
            try:
                self._last_selected_index = index
                self._current_pokemon_index = index
            except Exception:
                pass

            # Render current selection if requested
            if render:
                if bump_gen:
                    try:
                        self._selection_gen = int(getattr(self, '_selection_gen', 0)) + 1
                    except Exception:
                        self._selection_gen = 1
                self._on_party_selected()
        except Exception:
            try:
                self._suppress_list_event = False
            except Exception:
                pass

    def _current_mon(self) -> Optional[dict]:
        if not hasattr(self, 'party_list'):
            return None
        # Prefer last known selected index, then current listbox selection, else 0
        idx: Optional[int] = None
        try:
            idx = int(getattr(self, '_last_selected_index', None))
        except Exception:
            idx = None
        if idx is None:
            try:
                sel = self.party_list.curselection()
                idx = int(sel[0]) if sel else None
            except Exception:
                idx = None
        if idx is None:
            try:
                idx = int(getattr(self, '_current_pokemon_index', 0) or 0)
            except Exception:
                idx = 0
        try:
            total = len(self.party or [])
            if total <= 0:
                return None
            if idx < 0:
                idx = 0
            if idx >= total:
                idx = total - 1
            return (self.party or [])[idx]
        except Exception:
            return None

    def _on_target_changed(self):
        """Handle target change (Trainer vs Party) with unsaved changes protection."""
        current_target = self.target_var.get()

        # Check for unsaved changes before switching
        if hasattr(self, '_last_target') and self._last_target != current_target:
            if not self._confirm_discard_changes(f"switch to {current_target}"):
                # User canceled, revert the target selection
                self.target_var.set(self._last_target)
                return

        # Remember the new target
        self._last_target = current_target

        # Apply the target change
        self._apply_target_visibility()

    def _apply_target_visibility(self):
        tgt = self.target_var.get()
        # Clear all tabs
        try:
            for tab_id in list(self.tabs.tabs()):
                self.tabs.forget(tab_id)
        except Exception:
            pass

        # Configure party listbox state based on target
        self._configure_party_selector_for_target(tgt)

        # Add tabs based on target
        if tgt == "Trainer":
            try:
                self.tabs.add(self.tab_trainer_basics, text="Basics")
                self.tabs.add(self.tab_team_defensive, text="Team Defensive Analysis")
                self.tabs.add(self.tab_team_offensive, text="Team Offensive Analysis")
            except Exception:
                pass
            # Load trainer snapshot with enhanced progressive loading and performance optimizations
            try:
                debug_log("Loading trainer snapshot with enhanced performance...")
                self._load_trainer_snapshot_safe()

                # Show loading overlay for trainer tabs (same pattern as party tabs)
                self._show_trainer_loading_overlay()

                # Enhanced progressive loading with caching and optimization
                debug_log("Starting enhanced trainer analysis loading...")

                # Use the same optimization patterns as party tabs
                try:
                    self.after_idle(lambda: self._load_trainer_analysis_enhanced())
                except Exception as e:
                    debug_log(f"Error loading trainer analysis: {e}")
                    self._hide_trainer_loading_overlay()

            except Exception as e:
                debug_log(f"Error in trainer mode enhanced loading: {e}")
                self._hide_trainer_loading_overlay()
                import traceback
                traceback.print_exc()
        else:
            try:
                self.tabs.add(self.tab_poke_basics, text="Basics")
                self.tabs.add(self.tab_poke_stats, text="Stats")
                self.tabs.add(self.tab_poke_moves, text="Moves")
                self.tabs.add(self.tab_poke_form, text="Form & Visuals")
                self.tabs.add(self.tab_poke_matchups, text="Defensive Matchups")
                self.tabs.add(self.tab_poke_coverage, text="Offensive Matchups")
            except Exception:
                pass

    def _configure_party_selector_for_target(self, target: str):
        """Configure party selector state based on target context."""
        try:
            if target == "Trainer":
                # Make party selector read-only for trainer tabs
                debug_log("Setting party selector to read-only for Trainer context")

                # Disable selection events temporarily
                self.party_list.bind("<Button-1>", lambda e: "break")
                self.party_list.bind("<B1-Motion>", lambda e: "break")
                self.party_list.bind("<<ListboxSelect>>", lambda e: "break")

                # Visual indication it's read-only
                try:
                    self.party_list.configure(selectbackground="#f0f0f0", selectforeground="#888888")
                except Exception:
                    pass

                debug_log("Party selector configured as read-only")
            else:
                # Enable party selector for party tabs
                debug_log("Setting party selector to active for Party context")

                # Re-enable selection events
                self.party_list.bind("<Button-1>", lambda e: self._on_party_click(e))
                self.party_list.bind("<B1-Motion>", lambda e: "break")  # Still prevent drag selection
                self.party_list.bind("<<ListboxSelect>>", self._on_party_selected)

                # Restore normal selection colors
                try:
                    self.party_list.configure(selectbackground="SystemHighlight", selectforeground="SystemHighlightText")
                except Exception:
                    pass

                debug_log("Party selector configured as active")
        except Exception as e:
            debug_log(f"Error configuring party selector: {e}")

    def _show_trainer_loading_overlay(self):
        """Show loading overlay for trainer tabs with same pattern as party tabs."""
        try:
            # Show loading overlay on trainer tabs
            for tab_widget in [self.tab_team_defensive, self.tab_team_offensive]:
                if hasattr(self, tab_widget._name if hasattr(tab_widget, '_name') else 'tab_team_defensive'):
                    try:
                        # Create or show loading overlay
                        overlay_name = f"trainer_loading_overlay_{tab_widget._name if hasattr(tab_widget, '_name') else 'defensive'}"
                        if not hasattr(self, overlay_name):
                            overlay = tk.Frame(tab_widget, bg="white")
                            overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

                            # Loading message
                            loading_label = tk.Label(overlay, text="Loading trainer analysis...",
                                                   bg="white", fg="#666", font=("Arial", 12))
                            loading_label.place(relx=0.5, rely=0.4, anchor="center")

                            # Animated dots
                            dots_label = tk.Label(overlay, text="", bg="white", fg="#666", font=("Arial", 16))
                            dots_label.place(relx=0.5, rely=0.6, anchor="center")

                            setattr(self, overlay_name, overlay)
                            setattr(self, f"{overlay_name}_dots", dots_label)

                            # Start animation
                            self._animate_trainer_loading_dots(dots_label)
                        else:
                            # Show existing overlay
                            overlay = getattr(self, overlay_name)
                            overlay.lift()
                    except Exception as e:
                        debug_log(f"Error showing trainer loading overlay: {e}")
            debug_log("Trainer loading overlays shown")
        except Exception as e:
            debug_log(f"Error in _show_trainer_loading_overlay: {e}")

    def _hide_trainer_loading_overlay(self):
        """Hide loading overlay for trainer tabs."""
        try:
            # Hide loading overlays on trainer tabs
            for overlay_name in ['trainer_loading_overlay_defensive', 'trainer_loading_overlay_offensive']:
                if hasattr(self, overlay_name):
                    overlay = getattr(self, overlay_name)
                    try:
                        overlay.destroy()
                        delattr(self, overlay_name)
                        if hasattr(self, f"{overlay_name}_dots"):
                            delattr(self, f"{overlay_name}_dots")
                    except Exception:
                        pass
            debug_log("Trainer loading overlays hidden")
        except Exception as e:
            debug_log(f"Error in _hide_trainer_loading_overlay: {e}")

    def _animate_trainer_loading_dots(self, dots_label):
        """Animate loading dots for trainer tabs."""
        try:
            if not hasattr(self, '_trainer_dots_count'):
                self._trainer_dots_count = 0

            dots = "." * (self._trainer_dots_count % 4)
            if hasattr(dots_label, 'winfo_exists') and dots_label.winfo_exists():
                dots_label.configure(text=dots)
                self._trainer_dots_count += 1
                self.after(500, lambda: self._animate_trainer_loading_dots(dots_label))
        except Exception:
            pass

    def _compute_team_defensive_analysis_from_party_matchups(self, party_matchups: List[Dict]) -> Dict[str, Any]:
        """Compute comprehensive team-wide defensive analysis."""
        if not party_matchups:
            return {}

        try:
            # Enhanced team member data with names and types
            team_members = []
            effectiveness_grid = {}  # attacking_type -> {x4: count, x2: count, x1: count, x0.5: count, x0.25: count, x0: count}

            # All possible attacking types for comprehensive analysis
            all_types = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]

            # Initialize effectiveness grid
            for attack_type in all_types:
                effectiveness_grid[attack_type] = {"x4": 0, "x2": 0, "x1": 0, "x0.5": 0, "x0.25": 0, "x0": 0}

            # Process each team member
            for member in party_matchups:
                matchups = member.get("matchups", {})
                pokemon_name = member.get("pokemon_name", "Unknown")
                level = member.get("level", "?")
                types = member.get("types", [])

                team_members.append({
                    "name": pokemon_name,
                    "level": level,
                    "types": types,
                    "defensive_types": "/".join(types) if types else "Unknown"
                })

                # Count effectiveness for each attacking type
                for attack_type in all_types:
                    found_effectiveness = False
                    for effectiveness, type_list in matchups.items():
                        if attack_type in type_list:
                            effectiveness_grid[attack_type][effectiveness] += 1
                            found_effectiveness = True
                            break

                    # If not found in any category, assume neutral (x1)
                    if not found_effectiveness:
                        effectiveness_grid[attack_type]["x1"] += 1

            # Risk analysis - identify critical and major weaknesses
            critical_weaknesses = []  # Types that hit 4+ members super effectively
            major_weaknesses = []     # Types that hit 2-3 members super effectively
            team_resistances = []     # Types the team resists well

            team_size = len(party_matchups)

            for attack_type, effectiveness in effectiveness_grid.items():
                super_effective_count = effectiveness["x4"] + effectiveness["x2"]
                resistant_count = effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"]

                if super_effective_count >= max(4, team_size * 0.67):  # 67% or 4+ members
                    critical_weaknesses.append((attack_type, super_effective_count, effectiveness))
                elif super_effective_count >= 2:
                    major_weaknesses.append((attack_type, super_effective_count, effectiveness))

                if resistant_count >= max(3, team_size * 0.5):  # 50% or 3+ members resist
                    team_resistances.append((attack_type, resistant_count, effectiveness))

            # Sort by severity
            critical_weaknesses.sort(key=lambda x: x[1], reverse=True)
            major_weaknesses.sort(key=lambda x: x[1], reverse=True)
            team_resistances.sort(key=lambda x: x[1], reverse=True)

            # Coverage gaps - types with no resistance
            coverage_gaps = []
            for attack_type, effectiveness in effectiveness_grid.items():
                if effectiveness["x0.5"] + effectiveness["x0.25"] + effectiveness["x0"] == 0:
                    super_effective = effectiveness["x4"] + effectiveness["x2"]
                    if super_effective > 0:
                        coverage_gaps.append((attack_type, super_effective))

            coverage_gaps.sort(key=lambda x: x[1], reverse=True)

            return {
                "team_members": team_members,
                "effectiveness_grid": effectiveness_grid,
                "critical_weaknesses": critical_weaknesses[:5],
                "major_weaknesses": major_weaknesses[:8],
                "team_resistances": team_resistances[:10],
                "coverage_gaps": coverage_gaps[:8],
                "team_size": team_size,
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team defensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}

    def _compute_team_offensive_analysis_from_party(self, party: List[Dict], pokemon_catalog: Dict, type_matrix: Dict) -> Dict[str, Any]:
        """Compute comprehensive team-wide offensive analysis."""
        if not party:
            return {}

        try:
            from rogueeditor.catalog import load_type_matrix_v2

            type_matrix = load_type_matrix_v2()
            if not type_matrix:
                return {"error": "Type matrix not available"}

            # Team members with their moves organized by type
            team_members = []
            all_team_moves = {}  # type -> list of (pokemon_name, move_name)

            # All possible defending types for analysis
            all_types = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
                        "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]

            # Process each team member
            for member_data in party:
                if not member_data:
                    continue

                pokemon_name = member_data.get("species", "Unknown")
                level = member_data.get("level", "?")
                moves = member_data.get("moveset", [])

                # Organize moves by type
                member_moves_by_type = {}
                for move_data in moves:
                    if not move_data:
                        continue
                    move_name = move_data.get("moveId", "Unknown Move")
                    move_type = move_data.get("type", "Normal")

                    if move_type not in member_moves_by_type:
                        member_moves_by_type[move_type] = []
                    member_moves_by_type[move_type].append(move_name)

                    # Add to team-wide move tracking
                    if move_type not in all_team_moves:
                        all_team_moves[move_type] = []
                    all_team_moves[move_type].append((pokemon_name, move_name))

                team_members.append({
                    "name": pokemon_name,
                    "level": level,
                    "moves_by_type": member_moves_by_type,
                    "total_moves": len([m for m in moves if m])
                })

            # Coverage analysis against all defending types
            coverage_analysis = {}
            for defending_type in all_types:
                coverage_analysis[defending_type] = {
                    "super_effective": {"count": 0, "types": []},      # 2x effectiveness
                    "neutral": {"count": 0, "types": []},              # 1x effectiveness
                    "not_very_effective": {"count": 0, "types": []},   # 0.5x effectiveness
                    "no_effect": {"count": 0, "types": []},            # 0x effectiveness
                    "best_coverage": None
                }

            # Analyze coverage for each defending type
            for defending_type in all_types:
                best_effectiveness = 0
                best_move_types = []

                for attacking_type, moves_list in all_team_moves.items():
                    if not moves_list:
                        continue

                    # Get effectiveness from type matrix
                    effectiveness = 1.0
                    if defending_type in type_matrix.get(attacking_type, {}):
                        effectiveness = type_matrix[attacking_type][defending_type]

                    # Categorize effectiveness
                    if effectiveness >= 2.0:
                        coverage_analysis[defending_type]["super_effective"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["super_effective"]["types"].append(attacking_type)
                        if effectiveness > best_effectiveness:
                            best_effectiveness = effectiveness
                            best_move_types = [attacking_type]
                        elif effectiveness == best_effectiveness:
                            best_move_types.append(attacking_type)
                    elif effectiveness == 1.0:
                        coverage_analysis[defending_type]["neutral"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["neutral"]["types"].append(attacking_type)
                    elif effectiveness > 0:
                        coverage_analysis[defending_type]["not_very_effective"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["not_very_effective"]["types"].append(attacking_type)
                    else:
                        coverage_analysis[defending_type]["no_effect"]["count"] += len(moves_list)
                        coverage_analysis[defending_type]["no_effect"]["types"].append(attacking_type)

                coverage_analysis[defending_type]["best_coverage"] = {
                    "effectiveness": best_effectiveness,
                    "types": best_move_types
                }

            # Risk analysis - find defending types we struggle against
            coverage_risks = []      # Types we have no super effective coverage against
            limited_coverage = []    # Types we have limited options against

            for defending_type, analysis in coverage_analysis.items():
                super_effective_count = analysis["super_effective"]["count"]
                total_coverage = (analysis["super_effective"]["count"] +
                                analysis["neutral"]["count"])

                if super_effective_count == 0:
                    if total_coverage == 0:
                        coverage_risks.append((defending_type, "No Coverage"))
                    else:
                        coverage_risks.append((defending_type, "No Super Effective"))
                elif super_effective_count <= 2:
                    limited_coverage.append((defending_type, super_effective_count))

            # Sort risks
            limited_coverage.sort(key=lambda x: x[1])

            # Team move summary
            move_type_summary = []
            for move_type, moves_list in all_team_moves.items():
                move_type_summary.append({
                    "type": move_type,
                    "count": len(moves_list),
                    "members_with_type": len(set(pokemon for pokemon, move in moves_list))
                })

            move_type_summary.sort(key=lambda x: x["count"], reverse=True)

            return {
                "team_members": team_members,
                "all_team_moves": all_team_moves,
                "coverage_analysis": coverage_analysis,
                "coverage_risks": coverage_risks[:8],
                "limited_coverage": limited_coverage[:10],
                "move_type_summary": move_type_summary[:12],
                "team_size": len([m for m in party if m]),
                "analysis_complete": True
            }

        except Exception as e:
            print(f"Error in team offensive analysis: {e}")
            return {"error": str(e), "analysis_complete": False}

    def _compute_team_offensive_analysis_optimized(self, party: List[Dict], pokemon_catalog: Dict, type_matrix: Dict) -> Dict[str, Any]:
        """Optimized team-wide offensive analysis."""
        try:
            # This would compute offensive coverage analysis with pre-loaded data
            # For now, return placeholder data
            return {
                "coverage_computed": True,
                "party_size": len([m for m in party if m]),
                "optimized": True
            }
        except Exception as e:
            print(f"Error computing optimized offensive analysis: {e}")
            return {"error": str(e)}

    def _load_trainer_analysis_enhanced(self):
        """Enhanced trainer analysis loading with same optimizations as party tabs."""
        try:
            debug_log("Loading trainer analysis with enhanced performance...")

            # Use background cache manager like party tabs
            cache_manager = BackgroundCacheManager()
            username = getattr(self.api, 'username', 'default')

            # Check for cached trainer analysis
            trainer_cache_key = f"trainer_analysis_{username}_{self.slot}"
            cached_data = cache_manager.get_cached_data(trainer_cache_key)

            if cached_data and not cached_data.get("error"):
                debug_log("Using cached trainer analysis data")
                self._apply_cached_trainer_analysis(cached_data)
                self._hide_trainer_loading_overlay()
                return

            # Load data with same pattern as party loading
            debug_log("Computing trainer analysis with caching...")

            # Defer computation to avoid blocking
            self.after_idle(lambda: self._compute_trainer_analysis_safe())

        except Exception as e:
            debug_log(f"Error in enhanced trainer analysis loading: {e}")
            self._hide_trainer_loading_overlay()

    def _compute_trainer_analysis_safe(self):
        """Safely compute trainer analysis without blocking UI."""
        try:
            # Defensive analysis
            if hasattr(self, 'tab_team_defensive'):
                debug_log("Loading defensive analysis...")
                try:
                    # Use existing optimized method but with enhanced error handling
                    self._load_defensive_analysis_progressive()
                except Exception as e:
                    debug_log(f"Error in defensive analysis: {e}")

            # Offensive analysis with slight delay
            self.after(50, self._load_offensive_analysis_safe)

        except Exception as e:
            debug_log(f"Error in safe trainer analysis computation: {e}")
            self._hide_trainer_loading_overlay()

    def _load_offensive_analysis_safe(self):
        """Safely load offensive analysis."""
        try:
            if hasattr(self, 'tab_team_offensive'):
                debug_log("Loading offensive analysis...")
                self._load_offensive_analysis_progressive()

                # Hide loading overlay after both analyses complete
                self.after(200, self._hide_trainer_loading_overlay)
        except Exception as e:
            debug_log(f"Error in safe offensive analysis loading: {e}")
            self._hide_trainer_loading_overlay()

    def _apply_cached_trainer_analysis(self, cached_data: Dict[str, Any]):
        """Apply cached trainer analysis data to UI."""
        try:
            debug_log("Applying cached trainer analysis to UI...")

            # Apply defensive analysis if available
            if "defensive_analysis" in cached_data:
                self._apply_cached_defensive_to_ui(cached_data["defensive_analysis"])

            # Apply offensive analysis if available
            if "offensive_analysis" in cached_data:
                self._apply_cached_offensive_to_ui(cached_data["offensive_analysis"])

            debug_log("Cached trainer analysis applied successfully")
        except Exception as e:
            debug_log(f"Error applying cached trainer analysis: {e}")

    def _apply_cached_defensive_to_ui(self, defensive_data: Dict[str, Any]):
        """Apply cached defensive analysis to defensive tab."""
        try:
            if hasattr(self, 'tab_team_defensive'):
                # Clear existing content
                for widget in self.tab_team_defensive.winfo_children():
                    widget.destroy()

                # Build from cached data (similar to party tab pattern)
                self._build_cached_defensive_analysis(self.tab_team_defensive, defensive_data)
        except Exception as e:
            debug_log(f"Error applying cached defensive analysis: {e}")

    def _apply_cached_offensive_to_ui(self, offensive_data: Dict[str, Any]):
        """Apply cached offensive analysis to offensive tab."""
        try:
            if hasattr(self, 'tab_team_offensive'):
                # Clear existing content
                for widget in self.tab_team_offensive.winfo_children():
                    widget.destroy()

                # Build from cached data (similar to party tab pattern)
                self._build_cached_offensive_analysis(self.tab_team_offensive, offensive_data)
        except Exception as e:
            debug_log(f"Error applying cached offensive analysis: {e}")

    def _on_party_selected(self):
        """Simple, reliable party selection handler with generation guard."""
        try:
            # Prevent re-entrancy
            if getattr(self, '_handling_selection', False):
                return
            self._handling_selection = True
            
            # Get current Pokemon
            mon = self._current_mon()
            if not mon:
                self._handling_selection = False
                return

            # Get current selection index (pin target to avoid drift)
            try:
                current_idx = int(self.party_list.curselection()[0])
            except Exception:
                current_idx = 0
            pinned_idx = current_idx

            # Update tracking variables
            self._current_pokemon_index = current_idx

            # Show loading indicator
            try:
                self._set_tabs_enabled(False)
                self._show_loading_indicator("Loading selection…")
            except Exception:
                pass

            # Hide/show matchup sections based on single vs dual-type
            try:
                self._set_matchup_sections_for_mon(mon)
            except Exception:
                pass

            # Capture generation to guard async updates
            current_gen = int(getattr(self, '_selection_gen', 0))

            # Simple caching approach
            species_id = mon.get("species") or mon.get("dexId") or mon.get("speciesId") or -1
            
            # Try party member cache first
            cached_party_data = self._get_cached_party_member_data(current_idx)
            if cached_party_data:
                # Use cached data
                cached_data = cached_party_data["full_data"]
                self._apply_pokemon_data_fast(mon, cached_data)
                debug_log(f"Used party member cache for index {current_idx}")
            else:
                # Compute fresh data
                cached_data = self._compute_full_pokemon_data(mon, species_id)
                self._apply_pokemon_data_fast(mon, cached_data)
                # Cache for party member
                self._cache_party_member_data(current_idx, mon, cached_data)
                debug_log(f"Computed fresh data and cached for party member {current_idx}")

            # Apply secondary data (moves, matchups, etc.) guarded by generation
            try:
                gen_at_call = current_gen
                self.after_idle(lambda g=gen_at_call, m=mon, cd=cached_data: (
                    self._apply_secondary_data(m, cd) if g == getattr(self, '_selection_gen', 0) else None
                ))
            except Exception as e:
                debug_log(f"Error applying secondary data: {e}")

            debug_log(f"Party selection completed for Pokemon {species_id}")

        except Exception as e:
            debug_log(f"Exception in _on_party_selected: {e}")
            # Simple fallback
            try:
                self._apply_minimal_fallback(mon if 'mon' in locals() else None)
            except Exception:
                pass
        finally:
            try:
                # Always hide loading indicator and re-enable UI
                self._hide_loading_indicator()
                self._set_tabs_enabled(True)
                # Re-pin visual selection to the intended index without re-rendering
                try:
                    self._set_party_selection(pinned_idx, render=False, bump_gen=False)
                except Exception:
                    pass
                self._handling_selection = False
            except Exception:
                pass

    def _on_party_list_select_event(self):
        """Selection event handler with generation guard to prevent flicker."""
        try:
            # Ignore programmatic selection changes
            if bool(getattr(self, '_suppress_list_event', False)):
                return
            selection = self.party_list.curselection()
            if not selection:
                return
            selected_index = int(selection[0])
            # Use unified setter which updates indices and renders
            try:
                self._selection_gen = int(getattr(self, '_selection_gen', 0)) + 1
            except Exception:
                self._selection_gen = 1
            self._set_party_selection(selected_index, render=True)
        except Exception as e:
            debug_log(f"Error in _on_party_list_select_event: {e}")
            try:
                self._on_party_selected()
            except Exception:
                pass

    def _on_party_click(self, event):
        """Mouse click selection: compute index at click location and lock it.
        Prevents drag/hover-induced selection drift while content loads.
        """
        try:
            # Identify clicked index
            idx = self.party_list.nearest(event.y)
            if idx is None:
                return "break"
            # Apply selection deterministically and render; consume event
            self._set_party_selection(int(idx), render=True)
            return "break"
        except Exception:
            return "break"

    def _select_party_member(self, index: int):
        """Programmatic selection routed through unified setter."""
        try:
            self._set_party_selection(index, render=True)
        except Exception as e:
            debug_log(f"Error in _select_party_member: {e}")

    def _compute_full_pokemon_data(self, mon: dict, species_id: int) -> dict:
        """Compute complete Pokemon data for maximum caching."""
        try:
            # Combine display data with individual mon data
            display_data = self._compute_pokemon_display_data(mon, species_id)

            # Add individual Pokemon data that changes per mon
            return {
                **display_data,
                "exp": int(mon.get('exp', 0)),
                "friendship": str(mon.get("friendship") or mon.get("happiness") or ""),
                "hp": str(mon.get("currentHp") or mon.get("hp") or ""),
                "nickname": str(mon.get("nickname") or mon.get("name") or ""),
                "level": mon.get("level", 1),
                "passive": bool(mon.get("passive") or mon.get("passiveEnabled") or False),
                "ability_id": mon.get("abilityId") or mon.get("ability"),
                "ability_index": mon.get('abilityIndex'),
                "stats": mon.get('stats'),
                "status": mon.get("status"),
                "potentials": mon.get('potentials'),
                "summon_data": mon.get('summonData')
            }
        except Exception:
            return {"name": f"#{species_id}", "exp": 0, "friendship": "", "hp": "", "nickname": ""}

    def _apply_pokemon_data_fast(self, mon: dict, cached_data: dict):
        """Ultra-fast UI application using fully cached data."""
        try:
            # Set loading guard to prevent field change handlers from interfering
            self._loading_data = True
            
            # Prepare per-tab skeletons before applying any content
            try:
                if hasattr(self, 'tab_poke_basics'):
                    for w in self.tab_poke_basics.winfo_children():
                        w.destroy()
                    self._basics_skeleton = self._create_skeleton_frame(self.tab_poke_basics, "Loading basics…")
                if hasattr(self, 'tab_poke_stats'):
                    for w in self.tab_poke_stats.winfo_children():
                        w.destroy()
                    self._stats_skeleton = self._create_skeleton_frame(self.tab_poke_stats, "Loading stats…")
                if hasattr(self, 'tab_poke_moves'):
                    for w in self.tab_poke_moves.winfo_children():
                        w.destroy()
                    self._moves_skeleton = self._create_skeleton_frame(self.tab_poke_moves, "Loading moves…")
                if hasattr(self, 'tab_poke_matchups'):
                    for w in self.tab_poke_matchups.winfo_children():
                        w.destroy()
                    self._defensive_skeleton = self._create_skeleton_frame(self.tab_poke_matchups, "Loading defensive matchups…")
                if hasattr(self, 'tab_poke_coverage'):
                    for w in self.tab_poke_coverage.winfo_children():
                        w.destroy()
                    self._offensive_skeleton = self._create_skeleton_frame(self.tab_poke_coverage, "Loading offensive matchups…")
            except Exception:
                pass

            # Basic fields (immediate)
            self.var_exp.set(str(cached_data.get("exp", 0)))
            self.var_friend.set(cached_data.get("friendship", ""))
            self.var_hp.set(cached_data.get("hp", ""))
            self.var_name.set(cached_data.get("nickname", ""))

            # Species and types (cached)
            self.lbl_species_name.configure(text=cached_data.get("name", "Unknown"))
            self._update_type_chips_safe(
                cached_data.get("type1", ""), cached_data.get("type2", ""),
                cached_data.get("type1_color"), cached_data.get("type2_color")
            )

            # Show ability immediately (important for basics tab)
            self._update_ability_display(mon)

            # Defer expensive operations to avoid blocking
            self.after_idle(lambda: self._apply_secondary_data(mon, cached_data))

            # Rebuild destroyed tabs (immediate priority for stats tab)
            self.after_idle(lambda: self._rebuild_destroyed_tabs(mon))

            # Preserve selected tab after updating
            self.after_idle(self._preserve_selected_tab)

        except Exception as e:
            debug_log(f"Error in fast data application: {e}")
        finally:
            # Clear loading guard after a short delay to allow all UI updates to complete
            self.after(100, lambda: setattr(self, '_loading_data', False))

    def _rebuild_destroyed_tabs(self, mon: dict):
        """Rebuild tabs that were destroyed during party selection."""
        try:
            debug_log("Rebuilding destroyed tabs...")

            # Rebuild stats tab first (most important for user report)
            if hasattr(self, '_stats_skeleton'):
                try:
                    # Remove skeleton
                    if hasattr(self, '_stats_skeleton'):
                        self._stats_skeleton.destroy()
                        delattr(self, '_stats_skeleton')

                    # Rebuild stats tab immediately
                    self._build_stats(self.tab_poke_stats)

                    # Force stats calculation (bypass visibility check)
                    self._recalc_stats_optimized()

                    debug_log("Stats tab rebuilt successfully")
                except Exception as e:
                    debug_log(f"Error rebuilding stats tab: {e}")

            # Rebuild other tabs as needed
            if hasattr(self, '_basics_skeleton'):
                try:
                    self._basics_skeleton.destroy()
                    delattr(self, '_basics_skeleton')
                    self._build_basics(self.tab_poke_basics)
                    debug_log("Basics tab rebuilt")
                except Exception as e:
                    debug_log(f"Error rebuilding basics tab: {e}")

            if hasattr(self, '_moves_skeleton'):
                try:
                    self._moves_skeleton.destroy()
                    delattr(self, '_moves_skeleton')
                    self._build_moves(self.tab_poke_moves)
                    debug_log("Moves tab rebuilt")
                except Exception as e:
                    debug_log(f"Error rebuilding moves tab: {e}")

        except Exception as e:
            debug_log(f"Error in _rebuild_destroyed_tabs: {e}")

    def _update_ability_display(self, mon: dict):
        """Update ability display immediately for basics tab."""
        try:
            if hasattr(self, 'var_ability'):
                abil = mon.get("abilityId") or mon.get("ability")
                if isinstance(abil, int):
                    # Convert ability ID to name using cached catalog
                    ability_name = self.abil_i2n.get(int(abil), f"Ability #{abil}")
                    self.var_ability.set(ability_name)
                else:
                    self.var_ability.set(str(abil or ""))

            # Update ability slot radio buttons
            if hasattr(self, 'ability_slot_var'):
                try:
                    aidx = mon.get('abilityIndex')
                    if isinstance(aidx, int):
                        if aidx == 0:
                            self.ability_slot_var.set('1')
                        elif aidx == 1:
                            self.ability_slot_var.set('2')
                        elif aidx == 2:
                            self.ability_slot_var.set('Hidden')
                        else:
                            self.ability_slot_var.set('')
                    else:
                        self.ability_slot_var.set('')
                    # Trigger ability slot change handler
                    self._on_ability_slot_change()
                except Exception:
                    self.ability_slot_var.set('')

        except Exception as e:
            debug_log(f"Error updating ability display: {e}")

    def _apply_secondary_data(self, mon: dict, cached_data: dict):
        """Apply secondary data in idle time to avoid blocking."""
        try:
            # Set loading guard to prevent field change handlers from interfering
            self._loading_data = True
            
            # Capture generation to guard async updates
            current_gen = int(getattr(self, '_selection_gen', 0))
            # Passive, ability, stats (medium priority)
            if hasattr(self, 'var_passive'):
                self.var_passive.set(cached_data.get("passive", False))

            if hasattr(self, 'var_ability') and cached_data.get("ability_id"):
                abil = cached_data["ability_id"]
                if isinstance(abil, int):
                    self.var_ability.set(str(self.abil_i2n.get(int(abil), abil)))
                else:
                    self.var_ability.set(str(abil or ""))

            # Server stats
            if hasattr(self, 'server_stats_var'):
                stats = cached_data.get("stats")
                if isinstance(stats, list) and len(stats) == 6:
                    self.server_stats_var.set(f"[{stats[0]}, {stats[1]}, {stats[2]}, {stats[3]}, {stats[4]}, {stats[5]}]")
                else:
                    self.server_stats_var.set('-')

            # Populate IVs safely from mon - check multiple possible field names
            try:
                if hasattr(self, 'iv_vars'):
                    # Try different possible field names for IVs
                    ivs = None
                    for field_name in ['ivs', 'potentials', 'stats']:
                        field_value = mon.get(field_name)
                        if isinstance(field_value, list) and len(field_value) == 6:
                            ivs = field_value
                            break

                    # If no IVs found, try to extract from potentials
                    if ivs is None:
                        potentials = cached_data.get("potentials") or mon.get("potentials")
                        if isinstance(potentials, list) and len(potentials) == 6:
                            ivs = potentials

                    # Apply IVs to UI
                    if ivs:
                        for i in range(6):
                            try:
                                val = str(int(ivs[i])) if i < len(ivs) else ''
                                self.iv_vars[i].set(val)
                            except Exception:
                                self.iv_vars[i].set('0')
                    else:
                        # No IVs found - set defaults
                        for i in range(6):
                            self.iv_vars[i].set('0')

                    debug_log(f"Applied IVs: {ivs}")
            except Exception as e:
                debug_log(f"Error applying IVs: {e}")
                # Fallback to zeros
                try:
                    for i in range(6):
                        self.iv_vars[i].set('0')
                except Exception:
                    pass

            # Populate Nature display and hint
            try:
                if hasattr(self, 'var_nature'):
                    nid = mon.get('natureId') if isinstance(mon.get('natureId'), int) else mon.get('nature')
                    if isinstance(nid, int):
                        label = self._nature_label_for_id(int(nid))
                        self.var_nature.set(f"{label} ({nid})")
                        try:
                            if hasattr(self, 'nature_hint'):
                                self.nature_hint.configure(text=self._nature_change_suffix(int(nid)))
                        except Exception:
                            pass
                    else:
                        self.var_nature.set("")
            except Exception:
                pass

            # Populate Pokérus toggle strictly from canonical key
            try:
                if hasattr(self, 'var_pokerus'):
                    self.var_pokerus.set(bool(mon.get('pokerus', False)))
            except Exception:
                pass

            # Populate Form & Visuals (tera, shiny/luck, pause evo, gender, poké ball)
            try:
                # Tera Type
                if hasattr(self, 'var_tera'):
                    t_id = mon.get('teraType')
                    if isinstance(t_id, int):
                        try:
                            name = self._type_i2n.get(int(t_id)) if hasattr(self, '_type_i2n') else None
                            if isinstance(name, str) and name:
                                self.var_tera.set(f"{name} ({int(t_id)})")
                            else:
                                self.var_tera.set(str(int(t_id)))
                        except Exception:
                            self.var_tera.set(str(int(t_id)))
                    else:
                        self.var_tera.set("")

                # Shiny & Luck
                if hasattr(self, 'var_shiny'):
                    self.var_shiny.set(bool(mon.get('shiny') or False))
                if hasattr(self, 'var_luck'):
                    try:
                        self.var_luck.set(str(int(mon.get('luck') or 0)))
                    except Exception:
                        self.var_luck.set('0')

                # Pause Evolutions
                if hasattr(self, 'var_pause_evo'):
                    self.var_pause_evo.set(bool(mon.get('pauseEvolutions') or False))

                # Gender
                if hasattr(self, 'var_gender'):
                    g = mon.get('gender')
                    if g in (0, 1, -1):
                        gmap = {0: 'male', 1: 'female', -1: 'unknown'}
                        self.var_gender.set(f"{gmap.get(g, 'unknown')} ({g})")
                    else:
                        self.var_gender.set("")

                # Poké Ball
                if hasattr(self, 'var_ball'):
                    b = mon.get('pokeball')
                    if isinstance(b, int):
                        name = None
                        try:
                            if hasattr(self, '_ball_i2n'):
                                name = self._ball_i2n.get(int(b))
                        except Exception:
                            name = None
                        if isinstance(name, str) and name:
                            self.var_ball.set(f"{name} ({int(b)})")
                        else:
                            self.var_ball.set(str(int(b)))
                    else:
                        self.var_ball.set("")
            except Exception:
                pass

            # Replace skeletons with real content where appropriate
            try:
                # Basics
                if hasattr(self, '_basics_skeleton') and self._basics_skeleton.winfo_exists():
                    self._replace_skeleton_with_content(
                        self.tab_poke_basics,
                        self._basics_skeleton,
                        lambda parent=self.tab_poke_basics: self._build_basics(parent)
                    )
                # Stats
                if hasattr(self, '_stats_skeleton') and self._stats_skeleton.winfo_exists():
                    self._replace_skeleton_with_content(
                        self.tab_poke_stats,
                        self._stats_skeleton,
                        lambda parent=self.tab_poke_stats: self._build_stats(parent)
                    )
                # Moves
                if hasattr(self, '_moves_skeleton') and self._moves_skeleton.winfo_exists():
                    self._replace_skeleton_with_content(
                        self.tab_poke_moves,
                        self._moves_skeleton,
                        lambda parent=self.tab_poke_moves: self._build_moves(parent)
                    )
                # Defensive matchups (per-Pokemon)
                if hasattr(self, '_defensive_skeleton') and self._defensive_skeleton.winfo_exists():
                    self._replace_skeleton_with_content(
                        self.tab_poke_matchups,
                        self._defensive_skeleton,
                        lambda parent=self.tab_poke_matchups: self._build_matchups(parent)
                    )
                # Offensive coverage (per-Pokemon)
                if hasattr(self, '_offensive_skeleton') and self._offensive_skeleton.winfo_exists():
                    self._replace_skeleton_with_content(
                        self.tab_poke_coverage,
                        self._offensive_skeleton,
                        lambda parent=self.tab_poke_coverage: self._build_offensive_coverage(parent)
                    )
            except Exception:
                pass

            # Populate stats fields (IVs/Nature) and re-apply current mon data
            try:
                self._populate_stats_fields(mon)
            except Exception:
                pass
            try:
                self._apply_pokemon_data(mon, cached_data)
            except Exception:
                pass

            # Defer heavy operations even further (guarded by generation)
            self.after_idle(lambda g=current_gen, m=mon, cd=cached_data: (
                self._apply_heavy_data_guarded(0, m, cd) if g == getattr(self, '_selection_gen', 0) else None
            ))

        except Exception as e:
            debug_log(f"Error applying secondary data: {e}")
        finally:
            # Clear loading guard after a short delay to allow all UI updates to complete
            self.after(100, lambda: setattr(self, '_loading_data', False))

    def _populate_stats_fields(self, mon: dict):
        """Populate IV inputs and Nature selector from current mon safely."""
        try:
            # IVs
            if hasattr(self, 'iv_vars') and isinstance(self.iv_vars, list) and len(self.iv_vars) == 6:
                ivs = mon.get('ivs') if isinstance(mon.get('ivs'), list) and len(mon.get('ivs')) == 6 else None
                for i in range(6):
                    val = str(int(ivs[i])) if ivs is not None else ''
                    try:
                        self.iv_vars[i].set(val)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            # Nature
            if hasattr(self, 'var_nature'):
                nid = mon.get('natureId') if isinstance(mon.get('natureId'), int) else mon.get('nature')
                if isinstance(nid, int):
                    label = self._nature_label_for_id(int(nid))
                    self.var_nature.set(f"{label} ({nid})")
                else:
                    self.var_nature.set("")
        except Exception:
            pass

    def _apply_secondary_data_guarded(self, expected_token: int, mon: dict, cached_data: dict):
        try:
            if expected_token != getattr(self, '_selection_token', None):
                return
            self._apply_secondary_data(mon, cached_data)
        except Exception as e:
            debug_log(f"Error in guarded secondary data: {e}")

    def _apply_heavy_data(self, mon: dict, cached_data: dict):
        """Apply heavy computations in background."""
        try:
            # Status, moves, matchups (low priority, expensive)
            self._update_status_condition(mon)
            self._bind_moves_from_mon(mon)
            self._recalc_stats_safe()

            # Defer matchups to very end (most expensive)
            self.after_idle(lambda: self._update_deferred_matchups(mon))
            
            # Refresh offensive coverage
            self.after_idle(lambda: self._refresh_offensive_coverage())

        except Exception as e:
            debug_log(f"Error applying heavy data: {e}")

    def _apply_heavy_data_guarded(self, expected_token: int, mon: dict, cached_data: dict):
        try:
            # Since we removed the token system, just apply the data directly
            self._apply_heavy_data(mon, cached_data)
        finally:
            try:
                # Always hide loading indicator and re-enable UI
                self._hide_loading_indicator()
                self._set_tabs_enabled(True)
            except Exception:
                pass

    def _prefetch_neighbor_pokemon(self, current_index: int):
        try:
            import threading
            indices = []
            try:
                total = len(self.party or [])
            except Exception:
                total = 0
            if current_index - 1 >= 0:
                indices.append(current_index - 1)
            if current_index + 1 < total:
                indices.append(current_index + 1)

            def worker(idx: int):
                try:
                    mon = (self.party or [])[idx]
                    if not isinstance(mon, dict):
                        return
                    species_id = mon.get("species") or mon.get("dexId") or mon.get("speciesId") or -1
                    mon_id = mon.get("id", f"temp_{species_id}")
                    cache_key = f"{mon_id}_{species_id}"
                    if hasattr(self, '_full_pokemon_cache') and cache_key in self._full_pokemon_cache:
                        return
                    data = self._compute_full_pokemon_data(mon, species_id)
                    if not hasattr(self, '_full_pokemon_cache'):
                        self._full_pokemon_cache = {}
                    self._full_pokemon_cache[cache_key] = data
                except Exception:
                    pass

            for i in indices:
                threading.Thread(target=worker, args=(i,), daemon=True).start()
        except Exception:
            pass

    def _set_tabs_enabled(self, enabled: bool):
        try:
            # Enable/disable tabs
            if hasattr(self, 'tabs'):
                if enabled:
                    self.tabs.state(["!disabled"])
                else:
                    self.tabs.state(["disabled"])
            
            # Handle party list - preserve selection highlighting when disabled
            if hasattr(self, 'party_list'):
                if enabled:
                    self.party_list.configure(state="normal", cursor="")
                    # Re-enable selection events
                    self.party_list.bind("<<ListboxSelect>>", lambda e: self._on_party_list_select_event())
                else:
                    # Instead of disabling, make it read-only by unbinding events
                    # This preserves the selection highlighting
                    self.party_list.unbind("<<ListboxSelect>>")
                    # Change cursor to show it's not interactive
                    self.party_list.configure(cursor="wait")
                    
        except Exception:
            pass

    def prefetch_all_party_members(self):
        """Prefetch compute/cached data for all party members sequentially (6 max)."""
        try:
            party = self.party or []
            for idx, mon in enumerate(party):
                try:
                    if not isinstance(mon, dict):
                        continue
                    species_id = mon.get("species") or mon.get("dexId") or mon.get("speciesId") or -1
                    mon_id = mon.get("id", f"temp_{species_id}")
                    cache_key = f"{mon_id}_{species_id}"
                    if hasattr(self, '_full_pokemon_cache') and cache_key in self._full_pokemon_cache:
                        continue
                    data = self._compute_full_pokemon_data(mon, species_id)
                    if not hasattr(self, '_full_pokemon_cache'):
                        self._full_pokemon_cache = {}
                    self._full_pokemon_cache[cache_key] = data
                except Exception:
                    continue
        except Exception:
            pass

    def _update_deferred_matchups(self, mon: dict):
        """Update matchups in the background to avoid blocking."""
        try:
            self._update_matchups_for_mon(mon)
            self._refresh_offensive_coverage()
        except Exception as e:
            debug_log(f"Error updating deferred matchups: {e}")

    def _apply_minimal_fallback(self, mon: dict):
        """Absolute minimal fallback for error cases."""
        try:
            if mon:
                self.var_exp.set(str(int(mon.get('exp', 0))))
                self.lbl_species_name.configure(text=str(mon.get("species", "Unknown")))
                self.var_friend.set(str(mon.get("friendship", "")))
                self.var_hp.set(str(mon.get("currentHp", "")))
        except Exception:
            pass

    def _compute_pokemon_display_data(self, mon: dict, species_id: int) -> dict:
        """Compute Pokemon display data once and cache it."""
        try:
            # Get Pokemon catalog data
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            entry = by_dex.get(str(species_id)) or {}

            # Species name with form
            name = str(entry.get("name") or f"#{species_id}")
            fslug = self._detect_form_slug(mon)
            if fslug and (entry.get("forms") or {}).get(fslug):
                fdn = (entry.get("forms") or {}).get(fslug, {}).get("display_name")
                if isinstance(fdn, str) and fdn.strip():
                    name = f"{name} ({fdn})"

            # Get types safely
            types = entry.get("types") or {}
            type1 = str(types.get("type1") or "").lower()
            type2 = str(types.get("type2") or "").lower() if types.get("type2") else ""

            # Get cached type colors (ensure they're loaded)
            if not hasattr(self, '_type_colors_cache'):
                try:
                    from rogueeditor.catalog import load_type_colors
                    self._type_colors_cache = load_type_colors() or {}
                except Exception:
                    self._type_colors_cache = {}

            return {
                "name": name,
                "type1": type1,
                "type2": type2,
                "type1_color": self._color_for_type(type1) if type1 else None,
                "type2_color": self._color_for_type(type2) if type2 else None
            }
        except Exception:
            return {"name": f"#{species_id}", "type1": "", "type2": "", "type1_color": None, "type2_color": None}

    def _apply_pokemon_data(self, mon: dict, cached_data: dict):
        """Apply cached Pokemon data to UI quickly with complete first tab functionality."""
        try:
            # Basic stats
            self.var_exp.set(str(int(mon.get('exp', 0))))
            self.var_friend.set(str(mon.get("friendship") or mon.get("happiness") or ""))
            self.var_hp.set(str(mon.get("currentHp") or mon.get("hp") or ""))
            self.var_name.set(str(mon.get("nickname") or mon.get("name") or ""))

            # Species name
            self.lbl_species_name.configure(text=cached_data["name"])

            # Type chips (safe implementation)
            self._update_type_chips_safe(cached_data["type1"], cached_data["type2"],
                                       cached_data["type1_color"], cached_data["type2_color"])

            # Level calculation
            try:
                gidx = self._growth_index_for_mon(mon)
                if hasattr(self, 'var_level'):
                    lvl = None
                    try:
                        from rogueeditor.growth import level_from_exp
                        e = int(self.var_exp.get() or '0')
                        lvl = level_from_exp(gidx, e)
                    except Exception:
                        pass
                    self.var_level.set(str(lvl if isinstance(lvl, int) and lvl > 0 else (mon.get("level") or "")))
                if hasattr(self, 'var_growth'):
                    self.var_growth.set(self._growth_name_display(gidx))
            except Exception:
                pass

            # Passive state
            try:
                if hasattr(self, 'var_passive'):
                    self.var_passive.set(bool(mon.get("passive") or mon.get("passiveEnabled") or False))
            except Exception:
                pass

            # Ability (with ability slot handling)
            try:
                abil = mon.get("abilityId") or mon.get("ability")
                if hasattr(self, 'var_ability'):
                    if isinstance(abil, int):
                        self.var_ability.set(str(self.abil_i2n.get(int(abil), abil)))
                    else:
                        self.var_ability.set(str(abil or ""))

                # Ability slot radio from abilityIndex
                if hasattr(self, 'ability_slot_var'):
                    try:
                        aidx = mon.get('abilityIndex')
                        if isinstance(aidx, int):
                            if aidx == 0:
                                self.ability_slot_var.set('1')
                            elif aidx == 1:
                                self.ability_slot_var.set('2')
                            elif aidx == 2:
                                self.ability_slot_var.set('Hidden')
                            else:
                                self.ability_slot_var.set('')
                        else:
                            self.ability_slot_var.set('')
                        self._on_ability_slot_change()
                    except Exception:
                        self.ability_slot_var.set('')
            except Exception:
                pass

            # Server stats array display
            try:
                if hasattr(self, 'server_stats_var'):
                    stats = mon.get('stats')
                    if isinstance(stats, list) and len(stats) == 6:
                        self.server_stats_var.set(
                            f"[{stats[0]}, {stats[1]}, {stats[2]}, {stats[3]}, {stats[4]}, {stats[5]}]"
                        )
                    else:
                        self.server_stats_var.set('-')
            except Exception:
                if hasattr(self, 'server_stats_var'):
                    self.server_stats_var.set('-')

            # Status condition (comprehensive status handling)
            try:
                self._update_status_condition(mon)
            except Exception:
                pass

            # Bind moves from current mon
            try:
                self._bind_moves_from_mon(mon)
            except Exception:
                pass

            # Stats recalc and display (safe version)
            try:
                self._recalc_stats_safe()
            except Exception:
                pass

            # Update matchups view for this Pokemon
            try:
                self._update_matchups_for_mon(mon)
            except Exception:
                pass

            # Refresh offensive matchups when Pokemon selection changes
            try:
                self._refresh_offensive_coverage()
            except Exception:
                pass

        except Exception as e:
            debug_log(f"Error applying Pokemon data: {e}")

    def _update_status_condition(self, mon: dict):
        """Update status condition display safely."""
        try:
            # Status condition mapping (heuristic)
            st_sel = 'none'
            s_obj = mon.get("status")

            if isinstance(s_obj, dict):
                if 'sleepTurnsRemaining' in s_obj:
                    st_sel = 'slp'
                elif 'paralysisChance' in s_obj or 'paralysed' in s_obj:
                    st_sel = 'par'
                elif 'poisoned' in s_obj or 'poisonTurns' in s_obj:
                    st_sel = 'psn'
                elif 'badly_poisoned' in s_obj or 'badlyPoisoned' in s_obj:
                    st_sel = 'badpsn'
                elif 'burn' in s_obj or 'burned' in s_obj:
                    st_sel = 'brn'
                elif 'frozen' in s_obj or 'freeze' in s_obj:
                    st_sel = 'frz'
                elif 'fainted' in s_obj or 'faint' in s_obj:
                    st_sel = 'fnt'

            if hasattr(self, 'var_status'):
                self.var_status.set(st_sel)
                self._update_status_fields_visibility()
                self._update_status_summary()

            # Status-specific fields (turns remaining, damage, etc.)
            try:
                if s_obj and isinstance(s_obj, dict):
                    if st_sel == 'slp' and hasattr(self, 'var_slp_turns'):
                        self.var_slp_turns.set(str(s_obj.get('sleepTurnsRemaining', '')))
                    elif st_sel == 'frz' and hasattr(self, 'var_frz_turns'):
                        self.var_frz_turns.set(str(s_obj.get('freezeTurnsRemaining', '')))
                    elif st_sel in ('psn', 'badpsn'):
                        if hasattr(self, 'var_psn_turns'):
                            self.var_psn_turns.set(str(s_obj.get('poisonTurns', '')))
                        if hasattr(self, 'var_psn_damage'):
                            self.var_psn_damage.set(str(s_obj.get('poisonDamage', '')))
            except Exception:
                pass

            # IVs/Potentials
            try:
                potentials = mon.get('potentials')
                if isinstance(potentials, list) and len(potentials) == 6 and hasattr(self, 'iv_widgets'):
                    for i, widget in enumerate(self.iv_widgets):
                        widget.set(str(potentials[i] if i < len(potentials) else ''))
                elif hasattr(self, 'iv_widgets'):
                    for widget in self.iv_widgets:
                        widget.set('')
            except Exception:
                pass

            # Custom summon data
            try:
                if mon.get('summonData'):
                    sdata = mon['summonData']
                    if hasattr(self, 'var_sum_mon'):
                        self.var_sum_mon.set(sdata.get('speciesId', ''))
                    if hasattr(self, 'var_sum_move'):
                        self.var_sum_move.set(sdata.get('moveId', ''))
                    if hasattr(self, 'var_sum_stats'):
                        self.var_sum_stats.set(sdata.get('stats', ''))
                else:
                    if hasattr(self, 'var_sum_mon'):
                        self.var_sum_mon.set('')
                    if hasattr(self, 'var_sum_move'):
                        self.var_sum_move.set('')
                    if hasattr(self, 'var_sum_stats'):
                        self.var_sum_stats.set('')
            except Exception:
                pass

        except Exception as e:
            debug_log(f"Error updating status condition: {e}")

    def _update_type_chips_safe(self, type1: str, type2: str, color1: str, color2: str):
        """Safely update type chips without blocking operations."""
        try:
            # Type chip 1
            if type1 and hasattr(self, 'type_chip1'):
                self.type_chip1.configure(text=type1.title(), bg=color1 or "#DDDDDD")
                if not getattr(self, '_type_chip1_visible', False):
                    try:
                        self.type_chip1.pack_forget()
                        self.type_chip1.pack(side=tk.LEFT, padx=3)
                        self._type_chip1_visible = True
                    except Exception:
                        pass
            elif hasattr(self, 'type_chip1'):
                try:
                    self.type_chip1.pack_forget()
                    self._type_chip1_visible = False
                except Exception:
                    pass

            # Type chip 2
            if type2 and hasattr(self, 'type_chip2'):
                self.type_chip2.configure(text=type2.title(), bg=color2 or "#DDDDDD")
                if not getattr(self, '_type_chip2_visible', False):
                    try:
                        self.type_chip2.pack_forget()
                        self.type_chip2.pack(side=tk.LEFT, padx=3)
                        self._type_chip2_visible = True
                    except Exception:
                        pass
            elif hasattr(self, 'type_chip2'):
                try:
                    self.type_chip2.pack_forget()
                    self._type_chip2_visible = False
                except Exception:
                    pass
        except Exception as e:
            debug_log(f"Error updating type chips: {e}")
    # --- Actions ---
    def _open_item_mgr(self):
        mon = self._current_mon()
        mon_id = int(mon.get("id")) if mon and isinstance(mon.get("id"), int) else None
        dlg = ItemManagerDialog(self.master, self.api, self.editor, self.slot, preselect_mon_id=mon_id)
        # When the manager closes, refresh snapshot and recalc stats (booster stacks may change)
        try:
            self.master.wait_window(dlg)
        except Exception:
            pass
        try:
            # Refresh data from server to get latest held items and modifiers
            self.data = self.api.get_slot(self.slot)
            self.party = self.data.get("party") or []
            # Apply any pending changes to the refreshed data
            current_mon = self._current_mon()
            if current_mon:
                self._apply_pokemon_changes_to_data(current_mon)
            self._recalc_stats_safe()
            self._mark_dirty()
        except Exception:
            pass

    def _pick_ability(self):
        res = CatalogSelectDialog.select(self, self.abil_n2i, title="Select Ability")
        if res is not None:
            self.var_ability.set(f"{self.abil_i2n.get(int(res), res)} ({res})")

    def _pick_nature(self):
        # Create a human-friendly mapping for the dialog
        # Display names like "Adamant" but map to correct nature IDs
        friendly_map = {}
        for nid, name in self.nat_i2n.items():
            # Convert "ADAMANT" to "Adamant" for display
            friendly_name = self._format_nature_name(name)
            friendly_map[friendly_name] = int(nid)
        
        res = CatalogSelectDialog.select(self, friendly_map, title="Select Nature")
        if res is not None:
            self.var_nature.set(f"{self._nature_label_for_id(int(res))} ({res})")

    def _pick_move(self, idx: int):
        res = CatalogSelectDialog.select(self, self.move_n2i, title=f"Select Move {idx+1}")
        if res is not None:
            try:
                rid = int(res)
            except Exception:
                rid = None
            if isinstance(rid, int):
                label = get_move_label(rid) or self.move_i2n.get(int(res), res)
                self.move_vars[idx].set(f"{label} ({res})")
                # Update visuals for this row
                try:
                    self._update_move_row_visuals(idx, rid)
                except Exception:
                    pass
            else:
                self.move_vars[idx].set(f"{self.move_i2n.get(int(res), res)} ({res})")

    def _parse_id_from_combo(self, text: str, fallback_map: dict[str, int]) -> Optional[int]:
        t = text.strip()
        if not t:
            return None
        if t.endswith(")") and "(" in t:
            try:
                return int(t.rsplit("(", 1)[1].rstrip(")"))
            except Exception:
                pass
        key = t.strip().lower().replace(" ", "_")
        return fallback_map.get(key)

    def _on_shiny_toggle(self):
        try:
            shiny = bool(self.var_shiny.get())
            cur = int((self.var_luck.get() or '0').strip() or '0')
        except Exception:
            shiny = bool(self.var_shiny.get())
            cur = 0
        if not shiny:
            self.var_luck.set('0')
        else:
            if cur == 0:
                self.var_luck.set('1')
        # mark dirty when toggled to reflect intended change on apply
        try:
            self._mark_dirty()
        except Exception:
            pass

    def _on_ability_slot_change(self):
        # Show warning when selecting slot 2 (some species do not have a second ability)
        try:
            sel = (self.ability_slot_var.get() or '').strip()
            if sel == '2':
                self.ability_warn.configure(text='Warning: Some Pokémon do not have a second ability.')
            else:
                self.ability_warn.configure(text='')
        except Exception:
            pass

    def _apply_basics(self):
        mon = self._current_mon()
        if not mon:
            return
        # EXP and derived Level
        try:
            gidx = self._growth_index_for_mon(mon)
        except Exception:
            gidx = 0
        try:
            exp_in = int((self.var_exp.get() or "0").strip() or '0')
            if exp_in < 0:
                exp_in = 0
        except Exception:
            exp_in = 0
        mon['exp'] = exp_in
        # Compute Level floor from EXP
        try:
            lvl = level_from_exp(gidx, exp_in)
            if lvl < 1:
                lvl = 1
            _set(mon, ("level", "lvl"), int(lvl))
            self.var_level.set(str(lvl))
        except Exception:
            pass
        # Friendship
        try:
            fr = int((self.var_friend.get() or "").strip())
            fr = max(0, fr)
            _set(mon, ("friendship", "happiness"), fr)
        except Exception:
            pass
        # HP
        try:
            hp = int((self.var_hp.get() or "").strip())
            hp = max(0, hp)
            _set(mon, ("currentHp", "hp"), hp)
        except Exception:
            pass
        # Pokérus flag (canonical key only)
        try:
            pr = bool(self.var_pokerus.get()) if hasattr(self, 'var_pokerus') else False
            mon['pokerus'] = pr
        except Exception:
            pass
        # Nickname
        name = (self.var_name.get() or "").strip()
        if name:
            _set(mon, ("nickname", "name"), name)
        # Ability
        ab_text = self.var_ability.get()
        aid = self._parse_id_from_combo(ab_text, self.abil_n2i)
        if isinstance(aid, int):
            _set(mon, ("abilityId", "ability"), int(aid))
        # Ability slot radio → abilityIndex
        try:
            slot = (self.ability_slot_var.get() or '').strip()
            if slot == '1':
                mon['abilityIndex'] = 0
            elif slot == '2':
                mon['abilityIndex'] = 1
            elif slot.lower() == 'hidden':
                mon['abilityIndex'] = 2
        except Exception:
            pass
        # Passives
        if self.var_passive.get():
            mon["passive"] = True
        else:
            mon.pop("passive", None)
        # Status
        st = (self.var_status.get() or "none").strip().lower()
        # If existing status is a dict, update counters there; else, fall back
        s_obj = mon.get('status')
        if isinstance(s_obj, dict):
            if st == 'none' or not st:
                mon['status'] = None
            else:
                if st == 'slp':
                    try:
                        sv = int((self.status_detail_var.get() or '0').strip() or '0')
                    except Exception:
                        sv = 0
                    s_obj['sleepTurnsRemaining'] = max(0, sv)
                    # leave toxic counter as-is
                elif st == 'tox':
                    try:
                        tv = int((self.status_detail_var.get() or '0').strip() or '0')
                    except Exception:
                        tv = 0
                    s_obj['toxicTurnCount'] = max(0, tv)
                mon['status'] = s_obj
        else:
            # Legacy model: string + top-level counters (best-effort)
            mon['status'] = None if st == 'none' else st
            try:
                if st == 'slp':
                    sv = int((self.status_detail_var.get() or '0').strip() or '0')
                    if 'sleepTurns' in mon:
                        mon['sleepTurns'] = max(0, sv)
                    else:
                        mon['statusTurns'] = max(0, sv)
                else:
                    for k in ('sleepTurns', 'statusTurns'):
                        if k in mon:
                            mon.pop(k, None)
                if st == 'tox':
                    tv = int((self.status_detail_var.get() or '0').strip() or '0')
                    mon['toxicTurns'] = max(0, tv)
                else:
                    if 'toxicTurns' in mon:
                        mon.pop('toxicTurns', None)
            except Exception:
                pass
        # Do not edit volatile/battle-only statuses from the file editor
        self._mark_dirty()
        # Recalc stats using new level
        self._recalc_stats_safe()

    def _on_exp_change(self):
        # Live update Level display when EXP changes
        mon = self._current_mon()
        if not mon:
            return
        # recursion guard
        if getattr(self, '_sync_guard', False):
            return
        try:
            gidx = self._growth_index_for_mon(mon)
            e = int((self.var_exp.get() or '0').strip() or '0')
            lvl = max(1, level_from_exp(gidx, e))
            self._sync_guard = True
            try:
                self.var_level.set(str(lvl))
            finally:
                self._sync_guard = False
            # Also update stats preview
            self._recalc_stats_safe()
        except Exception:
            pass

    def _on_level_change(self):
        # Live update EXP when Level changes
        mon = self._current_mon()
        if not mon:
            return
        if getattr(self, '_sync_guard', False):
            return
        try:
            gidx = self._growth_index_for_mon(mon)
            lvl_in = int((self.var_level.get() or '1').strip() or '1')
            # clamp to table length if available
            if lvl_in < 1:
                lvl_in = 1
            exp_bp = exp_for_level(gidx, lvl_in)
            self._sync_guard = True
            try:
                self.var_exp.set(str(exp_bp))
            finally:
                self._sync_guard = False
            self._recalc_stats_safe()
        except Exception:
            pass

    def _growth_index_for_mon(self, mon: dict) -> int:
        # Resolve growth index using species id and CSV mapping; default to MEDIUM_FAST if unknown
        try:
            did = _get_species_id(mon) or -1
            gmap = getattr(self, '_growth_map_cache', None)
            if not isinstance(gmap, dict):
                gmap = load_growth_group_map()
                self._growth_map_cache = gmap
            if isinstance(did, int) and did in gmap:
                return int(gmap[did])
        except Exception:
            pass
        # default: MEDIUM_FAST
        try:
            from rogueeditor.catalog import load_exp_tables
            data = load_exp_tables()
            names = [str(n).strip().upper() for n in (data.get('growth_names') or [])]
            if 'MEDIUM_FAST' in names:
                return names.index('MEDIUM_FAST')
        except Exception:
            pass
        return 0

    def _growth_name_display(self, idx: int) -> str:
        try:
            from rogueeditor.catalog import load_exp_tables
            data = load_exp_tables()
            names = data.get('growth_names') or []
            if 0 <= idx < len(names):
                return str(names[idx]).replace('_', ' ').title()
        except Exception:
            pass
        return '-'

    def _apply_form_visuals(self):
        mon = self._current_mon()
        if not mon:
            return
        # Tera Type
        try:
            t_id = self._parse_id_from_combo(self.var_tera.get(), getattr(self, '_type_n2i', {}))
            if isinstance(t_id, int):
                mon['teraType'] = int(t_id)
        except Exception:
            pass
        # Shiny and Luck
        shiny = bool(self.var_shiny.get())
        mon['shiny'] = shiny
        try:
            luck = int((self.var_luck.get() or '0').strip() or '0')
        except Exception:
            luck = 0
        if not shiny:
            luck = 0
        else:
            if luck < 1:
                luck = 1
            if luck > 3:
                luck = 3
        mon['luck'] = luck
        # Pause Evolutions
        mon['pauseEvolutions'] = bool(self.var_pause_evo.get())
        # Gender
        try:
            g_id = self._parse_id_from_combo(self.var_gender.get(), {'male': 0, 'female': 1, 'unknown': -1})
            if isinstance(g_id, int):
                mon['gender'] = g_id
        except Exception:
            pass
        # Poké Ball
        try:
            b_id = self._parse_id_from_combo(self.var_ball.get(), getattr(self, '_ball_n2i', {}))
            if isinstance(b_id, int):
                mon['pokeball'] = int(b_id)
        except Exception:
            pass
        self._mark_dirty()

    def _open_item_mgr_trainer(self):
        # Open item manager targeting Trainer; refresh on close
        dlg = ItemManagerDialog(self.master, self.api, self.editor, self.slot)
        try:
            # Force Trainer target if possible
            if hasattr(dlg, 'target_var'):
                dlg.target_var.set('Trainer')
                if hasattr(dlg, '_on_target_change'):
                    dlg._on_target_change()
            self.master.wait_window(dlg)
        except Exception:
            pass
        try:
            # Refresh data from server to get latest trainer data
            self.data = self.api.get_slot(self.slot)
            self.party = self.data.get("party") or []
            # Apply any pending changes to the refreshed data
            current_mon = self._current_mon()
            if current_mon:
                self._apply_pokemon_changes_to_data(current_mon)
            self._recalc_stats_safe()
            self._mark_dirty()
            self._load_trainer_snapshot()
        except Exception:
            pass

    def _apply_stats(self):
        mon = self._current_mon()
        if not mon:
            return
        # IVs
        ivs: List[int] = []
        for v in self.iv_vars:
            try:
                x = int((v.get() or "0").strip())
            except Exception:
                x = 0
            if x < 0:
                x = 0
            if x > 31:
                x = 31
            ivs.append(x)
        mon["ivs"] = ivs
        # Nature
        nat_text = self.var_nature.get()
        nid = self._parse_id_from_combo(nat_text, self.nat_n2i)
        if isinstance(nid, int):
            _set(mon, ("natureId", "nature"), int(nid))
        self._mark_dirty()
        self._recalc_stats()

    def _apply_moves(self):
        mon = self._current_mon()
        if not mon:
            return
        # Ensure we have a key and shapes from last bind; if not, derive again
        key, shapes, current = self._derive_moves(mon)
        lst = mon.get(key)
        if not isinstance(lst, list):
            lst = []
        # Build new list preserving shapes and any extra dict fields
        out: List[Any] = list(lst)  # copy
        for i in range(4):
            mid = self._parse_id_from_combo(self.move_vars[i].get(), self.move_n2i)
            mid_i = int(mid or 0)
            shape = shapes[i] if i < len(shapes) else "int"
            if i < len(out):
                cur = out[i]
            else:
                cur = None
            if shape == "id":
                if isinstance(cur, dict):
                    cur["id"] = mid_i
                    out[i] = cur
                else:
                    out.append({"id": mid_i})
            elif shape == "moveId":
                if isinstance(cur, dict):
                    cur["moveId"] = mid_i
                    out[i] = cur
                else:
                    out.append({"moveId": mid_i})
            else:
                # int shape
                if i < len(out):
                    out[i] = mid_i
                else:
                    out.append(mid_i)
            # Clamp and apply PP fields if dict shape
            try:
                base_pp = get_move_base_pp(mid_i)
                max_extra, max_total = compute_ppup_bounds(base_pp)
                # Parse user inputs
                try:
                    pp_up_in = int((self.move_ppup_vars[i].get() or '').strip() or '0')
                except Exception:
                    pp_up_in = 0
                if pp_up_in < 0:
                    pp_up_in = 0
                if base_pp is not None:
                    # In unified rule, ppUp represents extra PP (not count of items)
                    if pp_up_in > max_extra:
                        pp_up_in = max_extra
                else:
                    pp_up_in = 0
                try:
                    pp_used_in = int((self.move_ppused_vars[i].get() or '').strip() or '0')
                except Exception:
                    pp_used_in = 0
                if pp_used_in < 0:
                    pp_used_in = 0
                if base_pp is not None:
                    max_pp_now = (base_pp or 0) + (pp_up_in or 0)
                    if pp_used_in > max_pp_now:
                        pp_used_in = max_pp_now
                else:
                    pp_used_in = 0
                # Apply only if dict shape (moveset objects)
                target = out[i] if i < len(out) else None
                if isinstance(target, dict):
                    target['ppUp'] = pp_up_in
                    target['ppUsed'] = pp_used_in
                    out[i] = target
            except Exception:
                pass
        # Truncate to 4 entries
        out = out[:4]
        mon[key] = out
        self._mark_dirty()

        # Refresh offensive matchups when moves change
        try:
            self._refresh_offensive_coverage()
        except Exception as e:
            print(f"Error refreshing coverage after move change: {e}")

    def _recalc_stats(self):
        mon = self._current_mon()
        if not mon:
            return
        # Level and nature
        try:
            level = int(_get(mon, ("level", "lvl")) or 1)
        except Exception:
            level = 1
        nat = _get(mon, ("natureId", "nature"))
        if isinstance(nat, int):
            mults = self.nature_mults_by_id.get(int(nat)) or [1.0] * 6
        else:
            mults = [1.0] * 6
        # Base stats (prefer pokemon_catalog.json, then fallback)
        species_id = _get_species_id(mon)
        base_raw = None
        try:
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            entry = by_dex.get(str(species_id or -1)) or {}
            st = entry.get("stats")
            if isinstance(st, dict):
                base_raw = [
                    int(st.get("hp") or 0),
                    int(st.get("attack") or 0),
                    int(st.get("defense") or 0),
                    int(st.get("sp_atk") or 0),
                    int(st.get("sp_def") or 0),
                    int(st.get("speed") or 0),
                ]
                self.base_source_note.configure(text="Base stats: catalog (pokemon_catalog)")
        except Exception:
            base_raw = None
        if base_raw is None:
            base_raw = get_base_stats_by_species_id(species_id or -1)
        # Fallback by species name if dex lookup missing
        if base_raw is None:
            try:
                inv = invert_dex_map(load_pokemon_index())
                nm = inv.get(str(int(species_id))) if species_id is not None else None
                if nm:
                    from rogueeditor.base_stats import get_base_stats_by_name
                    base_raw = get_base_stats_by_name(nm)
                    if base_raw is not None:
                        self.base_source_note.configure(text="Base stats: catalog (by name)")
                        try:
                            self.master._log(f"[base-stats] Fallback by name matched for dex={species_id} name={nm}")
                        except Exception:
                            pass
            except Exception:
                pass
        base = base_raw or [0, 0, 0, 0, 0, 0]
        for i, v in enumerate(base):
            self.base_labels[i].configure(text=str(v))
        # Update base stats source note
        try:
            if base_raw is None:
                self.base_source_note.configure(text="Base stats: missing (catalog)")
                try:
                    nm = None
                    try:
                        inv = invert_dex_map(load_pokemon_index())
                        nm = inv.get(str(int(species_id))) if species_id is not None else None
                    except Exception:
                        pass
                    self.master._log(f"[base-stats] Missing for dex={species_id} name={nm}")
                except Exception:
                    pass
            else:
                # keep text from fallback if set
                if self.base_source_note.cget('text').startswith('Base stats: catalog (by name)'):
                    pass
                else:
                    self.base_source_note.configure(text="Base stats: catalog (by dex)")
        except Exception:
            pass
        # IVs
        ivs = mon.get("ivs") if isinstance(mon.get("ivs"), list) and len(mon.get("ivs")) == 6 else [0, 0, 0, 0, 0, 0]
        # Boosters
        mon_id = int(mon.get("id") or -1)
        booster_mults, boosted_flags, boost_counts = _booster_multipliers_for_mon(self.data, mon_id)
        # Calculated (use live entry values instead of mon fields where possible)
        # Level (live)
        try:
            level = int((self.var_level.get() or "").strip())
        except Exception:
            level = level
        # IVs (live)
        ivs_live: List[int] = []
        for v in self.iv_vars:
            try:
                x = int((v.get() or "0").strip())
            except Exception:
                x = 0
            x = 0 if x < 0 else (31 if x > 31 else x)
            ivs_live.append(x)
        # Nature (live)
        nid = self._parse_id_from_combo(self.var_nature.get() or "", self.nat_n2i)
        nat_mults = None
        if isinstance(nid, int):
            nat_mults = self.nature_mults_by_id.get(int(nid))
        if nat_mults:
            mults = nat_mults
        calc = _calc_stats(level, base, ivs_live, mults, booster_mults)
        # Determine nature up/down for hinting and per-stat labels
        idx_to_name = ["hp", "attack", "defense", "sp_attack", "sp_defense", "speed"]
        nat_up_idx = None
        nat_down_idx = None
        if nat_mults:
            for i in range(1, 6):  # non-HP
                if nat_mults[i] > 1.0:
                    nat_up_idx = i
                elif nat_mults[i] < 1.0:
                    nat_down_idx = i
        for i, v in enumerate(calc):
            # Color calculated labels by nature effect
            if i == nat_up_idx:
                self.calc_labels[i].configure(text=str(v), foreground="green")
            elif i == nat_down_idx:
                self.calc_labels[i].configure(text=str(v), foreground="red")
            else:
                # reset to theme default
                try:
                    self.calc_labels[i].configure(text=str(v), foreground="")
                except Exception:
                    self.calc_labels[i].configure(text=str(v))
            # Item boosters column shows stacks and percent
            if boosted_flags[i]:
                stacks = boost_counts[i]
                pct = stacks * 10
                self.item_labels[i].configure(text=f"{stacks} (+{pct}%)")
            else:
                self.item_labels[i].configure(text="")
        # Nature hint label
        try:
            if nat_up_idx is None or nat_down_idx is None:
                self.nature_hint.configure(text="Nature: neutral")
            else:
                up_name = idx_to_name[nat_up_idx].replace('_', ' ').title()
                down_name = idx_to_name[nat_down_idx].replace('_', ' ').title()
                self.nature_hint.configure(text=f"Nature: +{up_name}, -{down_name}")
        except Exception:
            pass

    def _recalc_stats_safe(self):
        """Optimized stats calculation with caching and deferred updates."""
        try:
            # Only recalc if stats tab is visible (defer expensive operations)
            if not self._is_stats_tab_visible():
                self._stats_needs_update = True
                return

            # Use cached stats calculation
            self._recalc_stats_optimized()
        except Exception as e:
            debug_log(f"Error in stats calculation: {e}")

    def _is_stats_tab_visible(self) -> bool:
        """Check if stats tab is currently visible."""
        try:
            if hasattr(self, 'tabs'):
                selected_tab = self.tabs.select()
                stats_tab_id = str(self.tab_poke_stats)  # Fixed reference
                return selected_tab.endswith(stats_tab_id.split('.')[-1])
        except Exception:
            pass
        return True  # Default to visible if we can't determine

    def _recalc_stats_optimized(self):
        """Optimized stats calculation with base stats caching."""
        mon = self._current_mon()
        if not mon:
            return

        # Get cached species data
        species_id = _get_species_id(mon)
        if not species_id:
            return

        # Use cached base stats
        base_stats = self._get_cached_base_stats(species_id)
        if not base_stats:
            return

        # Get other values
        level = int(_get(mon, ("level", "lvl")) or 1)
        nat = _get(mon, ("natureId", "nature"))

        # Get nature multipliers (cached)
        if isinstance(nat, int):
            mults = self.nature_mults_by_id.get(int(nat)) or [1.0] * 6
        else:
            mults = [1.0] * 6

        # Get IVs
        ivs = []
        for i in range(6):
            try:
                ivs.append(int(self.iv_vars[i].get() or 0))
            except Exception:
                ivs.append(0)

        # Calculate stats efficiently
        self._update_stats_display(base_stats, level, ivs, mults, mon)

    def _get_cached_base_stats(self, species_id: int) -> Optional[List[int]]:
        """Get base stats with caching to avoid repeated lookups."""
        if not hasattr(self, '_base_stats_cache'):
            self._base_stats_cache = {}
        if not hasattr(self, '_base_stats_cache_from'):
            self._base_stats_cache_from = {}

        if species_id in self._base_stats_cache:
            return self._base_stats_cache[species_id]

        # Try catalog first (fastest)
        try:
            cat = self._get_cached_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            entry = by_dex.get(str(species_id)) or {}
            st = entry.get("stats")
            if isinstance(st, dict):
                base_stats = [
                    int(st.get("hp") or 0),
                    int(st.get("attack") or 0),
                    int(st.get("defense") or 0),
                    int(st.get("sp_atk") or 0),
                    int(st.get("sp_def") or 0),
                    int(st.get("speed") or 0),
                ]
                self._base_stats_cache[species_id] = base_stats
                try:
                    self._base_stats_cache_from[species_id] = "catalog (by dex)"
                except Exception:
                    pass
                return base_stats
        except Exception:
            pass

        # Fallback methods (cached)
        try:
            from rogueeditor.base_stats import get_base_stats_by_species_id
            base_stats = get_base_stats_by_species_id(species_id)
            if base_stats:
                self._base_stats_cache[species_id] = base_stats
                try:
                    self._base_stats_cache_from[species_id] = "fallback"
                except Exception:
                    pass
                return base_stats
        except Exception:
            pass

        return None

    # --- Type matrix normalization helpers ---
    def _ensure_defense_matrix(self, matrix: dict) -> dict:
        """Ensure matrix is in defensive orientation: mat[def_type][att_type] = multiplier.
        If matrix looks like attack_vs (mat[att][def]), invert it once.
        """
        try:
            if not isinstance(matrix, dict):
                return {}
            # Heuristic: if matrix has 'fire' key and inside has 'grass', check which way maps
            probe_att, probe_def = 'fire', 'grass'
            inner = matrix.get(probe_att)
            if isinstance(inner, dict) and probe_def in inner:
                # This is attack_vs; invert
                inverted: dict[str, dict[str, float]] = {}
                for att, row in matrix.items():
                    if not isinstance(row, dict):
                        continue
                    for de, val in row.items():
                        try:
                            inverted.setdefault(str(de), {})[str(att)] = float(val)
                        except Exception:
                            pass
                return inverted or matrix
            return matrix
        except Exception:
            return matrix

    def _ensure_attack_matrix(self, matrix: dict) -> dict:
        """Return matrix in attack orientation: mat[att_type][def_type] = multiplier.
        If given defensive orientation, invert it once.
        """
        try:
            if not isinstance(matrix, dict):
                return {}
            probe_att, probe_def = 'fire', 'grass'
            # If matrix already looks like attack_vs
            inner = matrix.get(probe_att)
            if isinstance(inner, dict) and probe_def in inner:
                return matrix
            # Else defensive → invert to attack
            att: dict[str, dict[str, float]] = {}
            for de, row in matrix.items():
                if not isinstance(row, dict):
                    continue
                for at, val in row.items():
                    try:
                        att.setdefault(str(at), {})[str(de)] = float(val)
                    except Exception:
                        pass
            return att or matrix
        except Exception:
            return matrix

    def _ensure_type_matrices_cached(self):
        """Load and cache both defensive and offensive matrices from type_matrix_v2.
        
        IMPORTANT: Matrix orientation matters for correct type effectiveness calculations!
        - self._tm_def: defense_from semantics mat[defending_type][attacking_type] = multiplier
        - self._tm_att: attack_vs semantics mat[attacking_type][defending_type] = multiplier
        
        Keys are normalized to lowercased strings for consistent lookups.
        
        Note: We use load_type_matrix_v2() directly instead of load_type_matchup_matrix()
        because the latter returns defensive orientation only, but we need both orientations.
        
        CRITICAL FIX: Previously used load_type_matchup_matrix() which returned defensive
        orientation (mat[def_type][att_type]), but wall analysis needs offensive orientation
        (mat[att_type][def_type]) to correctly calculate how user's moves affect defending types.
        """
        try:
            from rogueeditor.catalog import load_type_matrix_v2
            base = load_type_matrix_v2() or {}
            
            # Load defensive matrix: how well defending types resist attacking types
            def_mat = {}
            if isinstance(base.get('defense_from'), dict):
                def_mat = base['defense_from']
            elif isinstance(base, dict):
                def_mat = self._ensure_defense_matrix(base)
                
            # Load offensive matrix: how effective attacking types are against defending types  
            att_mat = {}
            if isinstance(base.get('attack_vs'), dict):
                att_mat = base['attack_vs']
            elif isinstance(base, dict):
                att_mat = self._ensure_attack_matrix(base)
            # Normalize keys to lower-case strings
            def _norm_dict(d):
                out = {}
                for k, row in (d or {}).items():
                    if not isinstance(row, dict):
                        continue
                    ko = str(k).strip().lower()
                    inner = {}
                    for kk, vv in row.items():
                        inner[str(kk).strip().lower()] = float(vv)
                    out[ko] = inner
                return out
            self._tm_def = _norm_dict(def_mat)
            self._tm_att = _norm_dict(att_mat)
        except Exception:
            self._tm_def, self._tm_att = {}, {}

    def _tm_def_mult(self, defending_type: str, attacking_type: str) -> float:
        """Get type effectiveness using defensive matrix orientation.
        
        Args:
            defending_type: The type being defended against (e.g., "fire")
            attacking_type: The type doing the attacking (e.g., "water")
            
        Returns:
            Effectiveness multiplier (0.0, 0.25, 0.5, 1.0, 2.0, or 4.0)
            
        Example:
            _tm_def_mult("fire", "water") returns 2.0 (water is 2x effective against fire)
        """
        try:
            self._ensure_type_matrices_cached()
            defending_type_key = str(defending_type).strip().lower()
            attacking_type_key = str(attacking_type).strip().lower()
            return float((self._tm_def.get(defending_type_key) or {}).get(attacking_type_key, 1.0))
        except Exception:
            return 1.0

    def _tm_att_mult(self, attacking_type: str, defending_type: str) -> float:
        """Get type effectiveness using offensive matrix orientation.
        
        Args:
            attacking_type: The type doing the attacking (e.g., "water")
            defending_type: The type being defended against (e.g., "fire")
            
        Returns:
            Effectiveness multiplier (0.0, 0.25, 0.5, 1.0, 2.0, or 4.0)
            
        Example:
            _tm_att_mult("water", "fire") returns 2.0 (water is 2x effective against fire)
        """
        try:
            self._ensure_type_matrices_cached()
            attacking_type_key = str(attacking_type).strip().lower()
            defending_type_key = str(defending_type).strip().lower()
            return float((self._tm_att.get(attacking_type_key) or {}).get(defending_type_key, 1.0))
        except Exception:
            return 1.0

    def _tm_best_offense_vs_type(self, move_types: list[str], def_type: str) -> float:
        """Best multiplier any of our move types achieves against a single defending type."""
        best = 0.0
        for mt in move_types:
            eff = self._tm_def_mult(def_type, mt)
            if eff > best:
                best = eff
        return float(best)

    def _tm_best_offense_vs_dual(self, move_types: list[str], def1: str, def2: str) -> float:
        """Find the best effectiveness any move achieves against a dual-type [def1/def2].
        
        For dual-type Pokémon, effectiveness is multiplicative:
        - If move is 2x vs type1 and 1x vs type2, final effectiveness = 2.0 * 1.0 = 2.0
        - If move is 0.5x vs type1 and 0.5x vs type2, final effectiveness = 0.5 * 0.5 = 0.25
        
        Args:
            move_types: List of move types the user has available
            def1: First defending type
            def2: Second defending type
            
        Returns:
            Best effectiveness multiplier (0.0 to 4.0) any move achieves against this dual-type
        """
        best_effectiveness = 0.0
        for move_type in move_types:
            # Calculate effectiveness against each defending type separately
            effectiveness_vs_type1 = self._tm_att_mult(move_type, def1)
            effectiveness_vs_type2 = self._tm_att_mult(move_type, def2)
            
            # For dual-types, multiply the effectivenesses together
            combined_effectiveness = effectiveness_vs_type1 * effectiveness_vs_type2
            
            if combined_effectiveness > best_effectiveness:
                best_effectiveness = combined_effectiveness
                
        return float(best_effectiveness)
    def _update_stats_display(self, base_stats: List[int], level: int, ivs: List[int], nature_mults: List[float], mon: dict):
        """Update stats display efficiently."""
        try:
            # Update base stats labels
            for i, base in enumerate(base_stats):
                if i < len(self.base_labels):
                    self.base_labels[i].configure(text=str(base))

            # Update base stats source note
            try:
                species_id = _get_species_id(mon)
                src = None
                if hasattr(self, '_base_stats_cache_from') and isinstance(self._base_stats_cache_from, dict):
                    src = self._base_stats_cache_from.get(int(species_id))
                if hasattr(self, 'base_source_note'):
                    if src:
                        self.base_source_note.configure(text=f"Base stats: {src}")
                    else:
                        self.base_source_note.configure(text="Base stats: catalog")
            except Exception:
                pass

            # Calculate final stats
            # Use local optimized stats calculator

            # Get booster multipliers (if any)
            booster_mults = None
            try:
                if hasattr(self, 'data') and self.data:
                    mon_id = int(mon.get("id", 0))
                    booster_mults, _, _ = _booster_multipliers_for_mon(self.data, mon_id)
            except Exception:
                pass

            # Adjust nature multipliers for SOUL_DEW stacks (amplifies nature effect)
            try:
                amp = self._nature_weight_multiplier_for_mon(mon)
                # Multiply deviation from 1 by amp for non-HP stats (index 1..5)
                if isinstance(amp, (int, float)) and amp > 1:
                    adj = list(nature_mults)
                    for i in range(1, min(len(adj), 6)):
                        delta = adj[i] - 1.0
                        adj[i] = 1.0 + delta * amp
                    nature_mults = adj
            except Exception:
                pass

            # Calculate final stats
            calc_stats = _calc_stats(level, base_stats, ivs, nature_mults, booster_mults)

            # Update calculated stats labels
            # Determine nature up/down indices based on adjusted multipliers
            nat_up_idx = None
            nat_down_idx = None
            try:
                for i in range(1, min(6, len(nature_mults))):
                    if nature_mults[i] > 1.0:
                        nat_up_idx = i
                    elif nature_mults[i] < 1.0:
                        nat_down_idx = i
            except Exception:
                pass

            for i, calc in enumerate(calc_stats):
                if i < len(self.calc_labels):
                    suffix = ''
                    color = ''
                    if i == nat_up_idx:
                        suffix = ' +'
                        color = 'green'
                    elif i == nat_down_idx:
                        suffix = ' -'
                        color = 'red'
                    try:
                        self.calc_labels[i].configure(text=f"{calc}{suffix}", foreground=color)
                    except Exception:
                        self.calc_labels[i].configure(text=f"{calc}{suffix}")

            # Update item boost labels
            if booster_mults:
                for i, mult in enumerate(booster_mults):
                    if i < len(self.item_labels) and mult != 1.0:
                        boost_text = f"×{mult:.2f}" if mult != int(mult) else f"×{int(mult)}"
                        self.item_labels[i].configure(text=boost_text)
                    elif i < len(self.item_labels):
                        self.item_labels[i].configure(text="")

            # Update nature hint
            try:
                nat_id = _get(mon, ("natureId", "nature"))
                if isinstance(nat_id, int):
                    hint = self._nature_change_suffix(nat_id)
                    self.nature_hint.configure(text=hint)
            except Exception:
                pass

        except Exception as e:
            debug_log(f"Error updating stats display: {e}")

    def _nature_weight_multiplier_for_mon(self, mon: dict) -> float:
        """Return amplification factor for nature effect due to SOUL_DEW stacks on this mon.
        1 stack doubles (x2), 2 triples (x3), etc. Returns 1.0 when none.
        """
        try:
            data = getattr(self, 'data', None)
            mon_id = int(mon.get('id', 0))
            if not data or not isinstance(data, dict):
                return 1.0
            mods = data.get('modifiers') or []
            stacks = 0
            for m in mods:
                try:
                    if not isinstance(m, dict):
                        continue
                    if m.get('typeId') != 'SOUL_DEW':
                        continue
                    args = m.get('args') or []
                    # Expect [mon_id, ...] shape
                    if args and int(args[0]) == mon_id:
                        stacks += int(m.get('stackCount') or 1)
                except Exception:
                    continue
            return max(1.0, 1.0 + float(stacks))
        except Exception:
            return 1.0

    def _on_tab_change(self, event=None):
        """Handle tab changes to trigger deferred updates and save tab preference."""
        try:
            # Save the currently selected tab for persistence
            self._last_selected_tab = self.tabs.select()

            # Trigger deferred updates based on which tab became visible
            if self._is_stats_tab_visible() and getattr(self, '_stats_needs_update', False):
                self._stats_needs_update = False
                self.after_idle(self._recalc_stats_optimized)

            # Add other tab-specific optimizations here
            elif self._is_moves_tab_visible() and getattr(self, '_moves_needs_update', False):
                self._moves_needs_update = False
                self.after_idle(self._update_moves_deferred)

            elif self._is_matchups_tab_visible() and getattr(self, '_matchups_needs_update', False):
                self._matchups_needs_update = False
                self.after_idle(self._update_matchups_deferred)

            elif self._is_trainer_tab_visible() and getattr(self, '_trainer_needs_update', False):
                self._trainer_needs_update = False
                self.after_idle(self._update_trainer_deferred)

        except Exception as e:
            debug_log(f"Error in tab change handler: {e}")

    def _preserve_selected_tab(self):
        """Restore the last selected tab when switching Pokemon."""
        try:
            if self._last_selected_tab and hasattr(self, 'tabs'):
                # Only restore if the tab still exists and is valid
                try:
                    current_tabs = self.tabs.tabs()
                    if self._last_selected_tab in current_tabs:
                        self.tabs.select(self._last_selected_tab)
                except Exception:
                    pass  # Tab no longer exists, that's fine
        except Exception:
            pass

    def _is_moves_tab_visible(self) -> bool:
        """Check if moves tab is currently visible."""
        try:
            if hasattr(self, 'tabs'):
                selected_tab = self.tabs.select()
                moves_tab_id = str(self.tab_poke_moves)
                return selected_tab.endswith(moves_tab_id.split('.')[-1])
        except Exception:
            pass
        return False

    def _is_matchups_tab_visible(self) -> bool:
        """Check if matchups tab is currently visible."""
        try:
            if hasattr(self, 'tabs'):
                selected_tab = self.tabs.select()
                matchups_tab_id = str(self.tab_poke_matchups)
                return selected_tab.endswith(matchups_tab_id.split('.')[-1])
        except Exception:
            pass
        return False

    def _is_trainer_tab_visible(self) -> bool:
        """Check if trainer tab is currently visible."""
        try:
            if hasattr(self, 'tabs'):
                selected_tab = self.tabs.select()
                trainer_tab_id = str(self.tab_trainer_basics)
                return selected_tab.endswith(trainer_tab_id.split('.')[-1])
        except Exception:
            pass
        return False

    def _update_trainer_deferred(self):
        """Update trainer tab display in deferred manner."""
        try:
            # Refresh party order section safely
            self.after_idle(self._refresh_party_order_section_safe)
            
            # Load trainer snapshot data safely
            self.after_idle(self._load_trainer_snapshot_safe)
            
        except Exception as e:
            debug_log(f"Error in deferred trainer update: {e}")

    def _update_moves_deferred(self):
        """Update moves display in deferred manner."""
        try:
            mon = self._current_mon()
            if mon:
                self._bind_moves_from_mon(mon)
        except Exception as e:
            debug_log(f"Error updating moves deferred: {e}")

    def _update_matchups_deferred(self):
        """Update matchups display in deferred manner."""
        try:
            mon = self._current_mon()
            if mon:
                self._update_matchups_for_mon(mon)
                self._refresh_offensive_coverage()
        except Exception as e:
            debug_log(f"Error updating matchups deferred: {e}")

    # --- Moves helpers ---
    def _derive_moves(self, mon: dict) -> Tuple[str, List[str], List[int]]:
        # Determine key and shapes, and current move ids
        key = None
        for k in ("moves", "moveIds", "moveset"):
            if isinstance(mon.get(k), list):
                key = k
                break
        if not key:
            key = "moves"
            mon[key] = mon.get(key) or []
        lst = mon.get(key) or []
        shapes: List[str] = []
        ids: List[int] = []
        for i in range(4):
            cur = lst[i] if i < len(lst) else 0
            if isinstance(cur, dict):
                if "id" in cur and isinstance(cur["id"], int):
                    shapes.append("id")
                    ids.append(int(cur["id"]))
                elif "moveId" in cur and isinstance(cur["moveId"], int):
                    shapes.append("moveId")
                    ids.append(int(cur["moveId"]))
                else:
                    shapes.append("int")
                    ids.append(0)
            elif isinstance(cur, int):
                shapes.append("int")
                ids.append(cur)
            else:
                shapes.append("int")
                ids.append(0)
        return key, shapes, ids

    def _bind_moves_from_mon(self, mon: dict) -> None:
        key, shapes, ids = self._derive_moves(mon)
        # Store for later if needed
        self._moves_key = key
        self._moves_shapes = shapes
        lst = mon.get(key) or []
        for i in range(4):
            mid = ids[i] if i < len(ids) else 0
            if isinstance(mid, int) and mid > 0:
                label = get_move_label(mid) or self.move_i2n.get(mid, mid)
                self.move_vars[i].set(f"{label} ({mid})")
                try:
                    self._update_move_row_visuals(i, mid)
                except Exception:
                    pass
            else:
                self.move_vars[i].set("")
                try:
                    self._update_move_row_visuals(i, 0)
                except Exception:
                    pass
            # Populate PP fields if present
            try:
                cur = lst[i] if i < len(lst) else None
                if isinstance(cur, dict):
                    ppup = cur.get('ppUp')
                    ppused = cur.get('ppUsed')
                    self.move_ppup_vars[i].set(str(ppup if ppup is not None else ''))
                    self.move_ppused_vars[i].set(str(ppused if ppused is not None else ''))
                else:
                    self.move_ppup_vars[i].set('')
                    self.move_ppused_vars[i].set('')
            except Exception:
                self.move_ppup_vars[i].set('')
                self.move_ppused_vars[i].set('')

    def _mark_dirty(self):
        self._dirty_local = True
        self._dirty_server = True
        try:
            self.btn_save.configure(state=tk.NORMAL)
            self.btn_upload.configure(state=tk.NORMAL)
        except Exception:
            pass

        # Invalidate party member caches when data changes
        try:
            current_idx = self._current_pokemon_index
            if current_idx is not None:
                self._invalidate_party_member_caches(current_idx)
            else:
                # If we don't know which Pokemon was modified, invalidate all caches
                self._invalidate_party_member_caches()
        except Exception as e:
            debug_log(f"Error invalidating caches in _mark_dirty: {e}")

    def _has_unsaved_changes(self) -> bool:
        """Check if there are unsaved changes that would be lost."""
        return getattr(self, '_dirty_local', False) or getattr(self, '_dirty_server', False)

    def _confirm_discard_changes(self, action_description: str = "continue") -> bool:
        """
        Show confirmation dialog for discarding unsaved changes.
        Returns True if user confirms they want to proceed and lose changes.
        """
        if not self._has_unsaved_changes():
            return True  # No changes to lose

        response = messagebox.askyesno(
            "Unsaved Changes",
            f"You have unsaved changes that will be lost if you {action_description}.\n\n"
            "Do you want to proceed anyway?",
            icon="warning"
        )
        return response

    def _on_window_closing(self):
        """Handle window closing with unsaved changes protection."""
        if self._confirm_discard_changes("close the window"):
            self.destroy()
        # If user cancels, window stays open

    # --- Persistence ---
    def _save(self):
        # Save slot if changed using safe save system
        p = slot_save_path(self.api.username, self.slot)
        if self._dirty_local or not os.path.exists(p):
            try:
                # Use safe save system with corruption prevention
                from rogueeditor.utils import safe_dump_json
                success = safe_dump_json(p, self.data, f"team_editor_save_slot_{self.slot}")

                if success:
                    self._dirty_local = False
                    messagebox.showinfo("Saved", f"Safely wrote {p}\nBackup created for safety.")
                else:
                    messagebox.showwarning("Save Warning", "Save completed with warnings. Check logs for details.")

            except Exception as e:
                messagebox.showerror("Save Failed", f"Failed to save: {e}\nFalling back to basic save.")
                # Emergency fallback to basic save
                dump_json(p, self.data)
                self._dirty_local = False
                messagebox.showinfo("Saved", f"Emergency save to {p}")

        try:
            self.btn_save.configure(state=(tk.NORMAL if self._dirty_server else tk.DISABLED))
        except Exception:
            pass

    def _upload(self):
        if not messagebox.askyesno("Confirm Upload", f"Upload changes for slot {self.slot} to the server?"):
            return
        try:
            # Upload slot changes only (team editor focuses on slot/session)
            if self._dirty_server:
                p = slot_save_path(self.api.username, self.slot)
                payload = load_json(p) if os.path.exists(p) else self.data
                self.api.update_slot(self.slot, payload)
                # Refresh snapshot and clear server dirty flag
                try:
                    self.data = self.api.get_slot(self.slot)
                    self.party = self.data.get("party") or []
                    self._dirty_server = False
                    self._refresh_party()
                except Exception:
                    pass
            # Update buttons
            try:
                self.btn_upload.configure(state=tk.DISABLED)
                if not self._dirty_local:
                    self.btn_save.configure(state=tk.DISABLED)
            except Exception:
                pass
            messagebox.showinfo("Uploaded", "Server updated successfully")
        except Exception as e:
            messagebox.showerror("Upload failed", str(e))

    # --- Trainer operations ---
    def _apply_trainer_changes(self):
        # Apply Money and Weather to slot/session data
        # Money
        try:
            m = int((self.var_money.get() or "").strip() or '0')
            if m < 0:
                m = 0
            self.data['money'] = m
            self._dirty_local = True
            self._dirty_server = True
        except Exception:
            messagebox.showwarning("Invalid", "Money must be an integer >= 0")
        # Weather
        try:
            text = (self.var_weather.get() or "").strip()
            wid = None
            if text.endswith(")") and "(" in text:
                try:
                    wid = int(text.rsplit("(", 1)[1].rstrip(")"))
                except Exception:
                    wid = None
            if wid is None:
                key = text.strip().lower().replace(" ", "_")
                wid = self._weather_n2i.get(key)
            if isinstance(wid, int):
                wkey = self._weather_key()
                if wkey:
                    self.data[wkey] = wid
                    self._dirty_local = True
                    self._dirty_server = True
        except Exception:
            pass
        try:
            self.btn_save.configure(state=tk.NORMAL)
            self.btn_upload.configure(state=tk.NORMAL)
        except Exception:
            pass

    def _load_trainer_snapshot_safe(self):
        """Safe version of trainer snapshot loading that avoids blocking operations."""
        debug_log("_load_trainer_snapshot_safe called")
        try:
            # Show loading animation for trainer data
            self._show_loading_indicator("Loading trainer data...")

            # Money (immediate, no heavy operations)
            val = None
            try:
                val = self.data.get('money') if isinstance(self.data, dict) else None
            except Exception:
                val = None
            if hasattr(self, 'var_money'):
                self.var_money.set(str(val if val is not None else ""))

            # Weather (defer heavy operations with progress updates)
            self.after_idle(self._load_weather_data_safe)

            # Display-only play time, game mode (defer)
            self.after_idle(self._load_playtime_gamemode_safe)

            # Hide loading indicator after a short delay to show completion
            self.after(500, self._hide_loading_indicator)

            debug_log("_load_trainer_snapshot_safe completed basic data")
        except Exception as e:
            debug_log(f"Error in safe trainer snapshot loading: {e}")
            self._hide_loading_indicator()

    def _load_weather_data_safe(self):
        """Safely load weather data without blocking UI."""
        try:
            if not hasattr(self, 'var_weather'):
                return

            # Update loading indicator with progress
            self._update_loading_status("Loading weather data...")
            if hasattr(self, '_loading_label'):
                self._loading_label.configure(text="Loading weather data...")

            # Ensure weather catalog is initialized
            self._init_weather_catalog_safe()

            wkey = self._weather_key()
            cur = self.data.get(wkey) if (wkey and isinstance(self.data, dict)) else None
            if isinstance(cur, int) and hasattr(self, '_weather_i2n') and self._weather_i2n:
                name = self._weather_i2n.get(int(cur), str(cur))
                self.var_weather.set(f"{name} ({cur})")
            else:
                self.var_weather.set("")

            debug_log("Weather data loaded successfully")
        except Exception as e:
            debug_log(f"Error loading weather data safely: {e}")

    def _load_playtime_gamemode_safe(self):
        """Safely load play time and game mode without blocking UI."""
        try:
            # Update loading indicator with progress
            self._update_loading_status("Loading playtime & game mode...")
            if hasattr(self, '_loading_label'):
                self._loading_label.configure(text="Loading playtime & game mode...")

            # Display-only play time, game mode
            try:
                pt = int(self.data.get('playTime')) if isinstance(self.data, dict) and 'playTime' in self.data else None
            except Exception:
                pt = None
            if hasattr(self, 'lbl_playtime'):
                if isinstance(pt, int):
                    hours = pt // 3600
                    minutes = (pt % 3600) // 60
                    seconds = pt % 60
                    self.lbl_playtime.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                else:
                    self.lbl_playtime.configure(text='-')

            if hasattr(self, 'lbl_gamemode'):
                gm = self.data.get('gameMode') if isinstance(self.data, dict) else None
                if gm is not None:
                    self.lbl_gamemode.configure(text=str(gm))
                else:
                    self.lbl_gamemode.configure(text='-')

            # Update to completion message
            if hasattr(self, '_loading_label'):
                self._loading_label.configure(text="Trainer data loaded!")

            debug_log("Playtime and gamemode loaded successfully")
        except Exception as e:
            debug_log(f"Error loading playtime/gamemode safely: {e}")

    def _load_defensive_analysis_progressive(self):
        """Load defensive analysis progressively without blocking UI - TRULY NON-BLOCKING."""
        try:
            debug_log("Loading defensive analysis with non-blocking approach...")

            # Only trigger if the defensive tab exists and we have data
            if not hasattr(self, 'tab_team_defensive') or not hasattr(self, 'party') or not self.party:
                debug_log("No defensive tab or party data, skipping")
                return

            # Check cache first (immediate return if cached)
            team_hash = self._compute_team_hash_safe()
            if hasattr(self, '_team_analysis_cache') and team_hash in self._team_analysis_cache:
                debug_log("Using cached defensive analysis data")
                cached_analysis = self._team_analysis_cache[team_hash]
                self._apply_cached_team_analysis(cached_analysis)
                return

            # Show immediate skeleton/loading state
            self._show_defensive_skeleton()

            # Start truly chunked, non-blocking computation
            debug_log("Starting chunked defensive analysis computation...")
            self.after_idle(lambda: self._start_chunked_defensive_analysis())

        except Exception as e:
            debug_log(f"Error in non-blocking defensive analysis loading: {e}")

    def _recompute_team_summary_safe(self):
        """Safe version of team summary computation that doesn't block UI."""
        try:
            debug_log("Starting safe team summary computation...")
            # Check if we actually need to recompute (avoid unnecessary work)
            if not hasattr(self, 'party') or not self.party:
                debug_log("No party data, skipping team summary")
                return

            # Use cached data if available
            team_hash = self._compute_team_hash_safe()
            if hasattr(self, '_team_analysis_cache') and team_hash in self._team_analysis_cache:
                debug_log("Using cached team analysis")
                cached_analysis = self._team_analysis_cache[team_hash]
                self._apply_cached_team_analysis(cached_analysis)
                return

            # Show loading state but don't block
            self._show_loading_indicator("Computing team analysis...")

            # Defer the actual computation
            self.after_idle(lambda: self._do_recompute_team_summary_safe(team_hash))

        except Exception as e:
            debug_log(f"Error in safe team summary computation: {e}")

    def _compute_team_hash_safe(self):
        """Safely compute team hash for caching."""
        try:
            # Simple hash based on party composition (species, levels, forms)
            party_info = []
            for mon in self.party[:6]:  # Limit to 6 to avoid huge hashes
                species_id = _get_species_id(mon) or 0
                level = _get(mon, ("level", "lvl")) or 1
                form_slug = self._detect_form_slug(mon) or ""
                party_info.append(f"{species_id}-{level}-{form_slug}")
            return hash("-".join(party_info))
        except Exception:
            return hash("default")

    def _do_recompute_team_summary_safe(self, team_hash):
        """Safely perform the actual team summary computation."""
        try:
            debug_log("Performing safe team summary computation...")
            # TODO: Implement safe computation here if needed
            # For now, just hide loading indicator
            self._hide_loading_indicator()
            debug_log("Safe team summary computation completed")
        except Exception as e:
            debug_log(f"Error in safe team summary computation: {e}")
            self._hide_loading_indicator()

    def _load_offensive_analysis_progressive(self):
        """Load offensive analysis progressively without blocking UI - TRULY NON-BLOCKING."""
        try:
            debug_log("Loading offensive analysis with non-blocking approach...")
            # Only trigger if the offensive tab exists and we have data
            if not hasattr(self, 'tab_team_offensive') or not hasattr(self, 'party') or not self.party:
                debug_log("No offensive tab or party data, skipping")
                return

            # Check cache first (immediate return if cached)
            team_hash = self._compute_team_hash_safe()
            if hasattr(self, '_team_offensive_cache') and team_hash in self._team_offensive_cache:
                debug_log("Using cached offensive analysis data")
                cached_analysis = self._team_offensive_cache[team_hash]
                self._apply_cached_offensive_analysis(cached_analysis)
                return

            # Show immediate skeleton/loading state
            self._show_offensive_skeleton()

            # Start truly chunked, non-blocking computation
            debug_log("Starting chunked offensive analysis computation...")
            self.after_idle(lambda: self._start_chunked_offensive_analysis())
        except Exception as e:
            debug_log(f"Error in non-blocking offensive analysis loading: {e}")

    def _show_defensive_skeleton(self):
        """Show immediate skeleton UI for defensive analysis while loading."""
        try:
            if hasattr(self, 'tab_team_defensive'):
                # Clear existing content and show loading skeleton
                for widget in self.tab_team_defensive.winfo_children():
                    widget.destroy()

                skeleton_frame = ttk.Frame(self.tab_team_defensive)
                skeleton_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

                ttk.Label(skeleton_frame, text="Loading defensive analysis...",
                         font=('TkDefaultFont', 10)).pack(pady=20)

                # Add progress indicator
                progress = ttk.Progressbar(skeleton_frame, mode='indeterminate')
                progress.pack(pady=10, fill=tk.X, padx=50)
                progress.start()

                debug_log("Defensive skeleton UI displayed")
        except Exception as e:
            debug_log(f"Error showing defensive skeleton: {e}")

    def _show_offensive_skeleton(self):
        """Show immediate skeleton UI for offensive analysis while loading."""
        try:
            if hasattr(self, 'tab_team_offensive'):
                # Clear existing content and show loading skeleton
                for widget in self.tab_team_offensive.winfo_children():
                    widget.destroy()

                skeleton_frame = ttk.Frame(self.tab_team_offensive)
                skeleton_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

                ttk.Label(skeleton_frame, text="Loading offensive analysis...",
                         font=('TkDefaultFont', 10)).pack(pady=20)

                # Add progress indicator
                progress = ttk.Progressbar(skeleton_frame, mode='indeterminate')
                progress.pack(pady=10, fill=tk.X, padx=50)
                progress.start()

                debug_log("Offensive skeleton UI displayed")
        except Exception as e:
            debug_log(f"Error showing offensive skeleton: {e}")

    def _start_chunked_defensive_analysis(self):
        """Start chunked defensive analysis computation without blocking."""
        try:
            debug_log("Starting chunked defensive analysis...")
            # Initialize chunked processing state
            if not hasattr(self, '_defensive_chunk_state'):
                self._defensive_chunk_state = {
                    'step': 0,
                    'total_steps': 3,  # Basic setup, compute analysis, render UI
                    'data': {}
                }

            # Process one chunk at a time with UI updates between
            self._process_defensive_chunk()
        except Exception as e:
            debug_log(f"Error starting chunked defensive analysis: {e}")

    def _process_defensive_chunk(self):
        """Process one chunk of defensive analysis."""
        try:
            state = self._defensive_chunk_state
            step = state['step']

            if step == 0:
                # Step 1: Basic setup and validation
                debug_log("Defensive chunk 0: Basic setup")
                if not self.party:
                    debug_log("No party data for defensive analysis")
                    return
                state['party_data'] = self.party.copy()
                state['step'] = 1
                self.after_idle(self._process_defensive_chunk)

            elif step == 1:
                # Step 2: Compute defensive matchups
                debug_log("Defensive chunk 1: Computing matchups")
                try:
                    # Compute party matchups first (needed for defensive analysis)
                    from rogueeditor.catalog import load_pokemon_catalog, load_type_matrix_v2
                    cat = self._get_cached_pokemon_catalog() or load_pokemon_catalog()
                    type_matrix = load_type_matrix_v2()

                    # Basic matchup calculation
                    party_matchups = []
                    for i, mon in enumerate(state['party_data']):
                        if not mon:
                            continue
                        # Simplified matchup calculation for chunked processing
                        species_id = mon.get("species", 0)
                        entry = cat.get("by_dex", {}).get(str(species_id), {})
                        species_name = entry.get("name", f"Species#{species_id}")
                        types = entry.get("types", {})

                        party_matchups.append({
                            "index": i,
                            "species_id": species_id,
                            "species_name": species_name,
                            "types": types,
                            "matchups": {"x4": [], "x2": [], "x1": [], "x0.5": [], "x0.25": [], "x0": []}  # Simplified for now
                        })

                    state['party_matchups'] = party_matchups
                    state['step'] = 2
                    self.after_idle(self._process_defensive_chunk)
                except Exception as e:
                    debug_log(f"Error computing defensive matchups: {e}")
                    state['data']['error'] = str(e)
                    state['step'] = 2
                    self.after_idle(self._process_defensive_chunk)

            elif step == 2:
                # Step 3: Compute actual defensive analysis
                debug_log("Defensive chunk 2: Computing defensive analysis")
                try:
                    if 'party_matchups' in state and not state['data'].get('error'):
                        # Use the real defensive analysis method
                        defensive_analysis = self._compute_team_defensive_analysis_from_party_matchups(state['party_matchups'])
                        # Merge the analysis data directly into state['data'] for UI compatibility
                        state['data'].update(defensive_analysis)
                    state['step'] = 3
                    self.after_idle(self._process_defensive_chunk)
                except Exception as e:
                    debug_log(f"Error computing defensive analysis: {e}")
                    state['data']['error'] = str(e)
                    state['step'] = 3
                    self.after_idle(self._process_defensive_chunk)

            elif step == 3:
                # Step 4: Render the UI
                debug_log("Defensive chunk 3: Rendering UI")
                self._render_defensive_analysis_ui(state['data'])
                # Cache the results
                team_hash = self._compute_team_hash_safe()
                if not hasattr(self, '_team_analysis_cache'):
                    self._team_analysis_cache = {}
                self._team_analysis_cache[team_hash] = state['data']
                # Clean up
                delattr(self, '_defensive_chunk_state')
                debug_log("Chunked defensive analysis completed")

        except Exception as e:
            debug_log(f"Error processing defensive chunk: {e}")

    def _start_chunked_offensive_analysis(self):
        """Start chunked offensive analysis computation without blocking."""
        try:
            debug_log("Starting chunked offensive analysis...")
            # Initialize chunked processing state
            if not hasattr(self, '_offensive_chunk_state'):
                self._offensive_chunk_state = {
                    'step': 0,
                    'total_steps': 3,  # Basic setup, compute analysis, render UI
                    'data': {}
                }

            # Process one chunk at a time with UI updates between
            self._process_offensive_chunk()
        except Exception as e:
            debug_log(f"Error starting chunked offensive analysis: {e}")

    def _process_offensive_chunk(self):
        """Process one chunk of offensive analysis."""
        try:
            state = self._offensive_chunk_state
            step = state['step']

            if step == 0:
                # Step 1: Basic setup and validation
                debug_log("Offensive chunk 0: Basic setup")
                if not self.party:
                    debug_log("No party data for offensive analysis")
                    return
                state['party_data'] = self.party.copy()
                state['step'] = 1
                self.after_idle(self._process_offensive_chunk)

            elif step == 1:
                # Step 2: Compute offensive coverage data using enhanced method
                debug_log("Offensive chunk 1: Computing offensive coverage")
                try:
                    # Use the new comprehensive team offensive analysis method
                    if 'party_data' in state:
                        pokemon_catalog = getattr(self, 'pokemon_catalog', {})
                        base_matrix = load_type_matchup_matrix() or {}
                        type_matrix = base_matrix.get('attack_vs') if isinstance(base_matrix.get('attack_vs'), dict) else base_matrix
                        offensive_analysis = self._compute_team_offensive_analysis_from_party(state['party_data'], pokemon_catalog, type_matrix)
                        # Merge the analysis data directly into state['data'] for UI compatibility
                        state['data'].update(offensive_analysis)
                    state['step'] = 2
                    self.after_idle(self._process_offensive_chunk)
                except Exception as e:
                    debug_log(f"Error computing offensive coverage: {e}")
                    state['data']['error'] = str(e)
                    state['step'] = 2
                    self.after_idle(self._process_offensive_chunk)

            elif step == 2:
                # Step 3: Render the UI
                debug_log("Offensive chunk 2: Rendering UI")
                self._render_offensive_analysis_ui(state['data'])
                # Cache the results
                team_hash = self._compute_team_hash_safe()
                if not hasattr(self, '_team_offensive_cache'):
                    self._team_offensive_cache = {}
                self._team_offensive_cache[team_hash] = state['data']
                # Clean up
                delattr(self, '_offensive_chunk_state')
                debug_log("Chunked offensive analysis completed")

        except Exception as e:
            debug_log(f"Error processing offensive chunk: {e}")

    def _render_defensive_analysis_ui(self, data):
        """Render the comprehensive team defensive analysis UI."""
        try:
            if not hasattr(self, 'tab_team_defensive'):
                return

            # Clear existing content
            for widget in self.tab_team_defensive.winfo_children():
                widget.destroy()

            # Create scrollable content frame
            canvas = tk.Canvas(self.tab_team_defensive)
            scrollbar = ttk.Scrollbar(self.tab_team_defensive, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Main content frame
            content_frame = ttk.Frame(scrollable_frame)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # Title and refresh button frame
            title_frame = ttk.Frame(content_frame)
            title_frame.pack(fill=tk.X, pady=(0, 15))

            ttk.Label(title_frame, text="Team Defensive Analysis",
                     font=('TkDefaultFont', 14, 'bold')).pack(side=tk.LEFT)

            # Refresh button
            refresh_button = ttk.Button(title_frame, text="🔄 Refresh",
                                      command=self._force_refresh_team_analysis)
            refresh_button.pack(side=tk.RIGHT)

            # Check for errors first
            if data.get('error'):
                ttk.Label(content_frame, text=f"Error: {data['error']}",
                         foreground="red").pack()
                return

            if not data.get('analysis_complete'):
                ttk.Label(content_frame, text="Analysis not complete").pack()
                return

            # 1. Team Overview Section
            overview_frame = ttk.LabelFrame(content_frame, text="Team Overview", padding=10)
            overview_frame.pack(fill=tk.X, pady=(0, 10))

            team_members = data.get('team_members', [])
            team_size = data.get('team_size', 0)

            ttk.Label(overview_frame, text=f"Team Size: {team_size} Pokemon").pack(anchor=tk.W)

            if team_members:
                members_text = "Team Members: "
                member_strs = []
                for member in team_members:
                    name = member.get('name', 'Unknown')
                    level = member.get('level', '?')
                    types = member.get('defensive_types', 'Unknown')
                    member_strs.append(f"{name} L{level} ({types})")

                ttk.Label(overview_frame, text=members_text).pack(anchor=tk.W, pady=(5, 0))
                for i, member_str in enumerate(member_strs[:6]):  # Limit display
                    ttk.Label(overview_frame, text=f"  • {member_str}").pack(anchor=tk.W)

                if len(member_strs) > 6:
                    ttk.Label(overview_frame, text=f"  ... and {len(member_strs) - 6} more").pack(anchor=tk.W)

            # 2. Critical Weaknesses Section
            critical_weaknesses = data.get('critical_weaknesses', [])
            if critical_weaknesses:
                critical_frame = ttk.LabelFrame(content_frame, text="⚠️ Critical Weaknesses", padding=10)
                critical_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(critical_frame, text="Types that hit 67% or more of your team super effectively:",
                         foreground="#8B0000").pack(anchor=tk.W)

                for type_name, count, effectiveness_details in critical_weaknesses:
                    x4_count = effectiveness_details.get("x4", 0)
                    x2_count = effectiveness_details.get("x2", 0)

                    weakness_text = f"• {type_name}: {count}/{team_size} members vulnerable"
                    if x4_count > 0:
                        weakness_text += f" ({x4_count} take 4x damage!)"

                    label = ttk.Label(critical_frame, text=weakness_text, foreground="#8B0000")
                    label.pack(anchor=tk.W, padx=10)

            # 3. Major Weaknesses Section
            major_weaknesses = data.get('major_weaknesses', [])
            if major_weaknesses:
                major_frame = ttk.LabelFrame(content_frame, text="⚡ Major Weaknesses", padding=10)
                major_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(major_frame, text="Types that hit 2-3 team members super effectively:",
                         foreground="#FF4500").pack(anchor=tk.W)

                for type_name, count, effectiveness_details in major_weaknesses:
                    x4_count = effectiveness_details.get("x4", 0)
                    x2_count = effectiveness_details.get("x2", 0)

                    weakness_text = f"• {type_name}: {count}/{team_size} members vulnerable"
                    if x4_count > 0:
                        weakness_text += f" ({x4_count} take 4x damage)"

                    label = ttk.Label(major_frame, text=weakness_text, foreground="#FF4500")
                    label.pack(anchor=tk.W, padx=10)

            # 4. Team Strengths Section
            team_resistances = data.get('team_resistances', [])
            if team_resistances:
                strengths_frame = ttk.LabelFrame(content_frame, text="🛡️ Team Strengths", padding=10)
                strengths_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(strengths_frame, text="Types your team resists well:",
                         foreground="#008000").pack(anchor=tk.W)

                for type_name, count, effectiveness_details in team_resistances[:6]:  # Top 6
                    x0_count = effectiveness_details.get("x0", 0)
                    x025_count = effectiveness_details.get("x0.25", 0)
                    x05_count = effectiveness_details.get("x0.5", 0)

                    resist_text = f"• {type_name}: {count}/{team_size} members resist"
                    if x0_count > 0:
                        resist_text += f" ({x0_count} immune!)"
                    elif x025_count > 0:
                        resist_text += f" ({x025_count} quarter damage)"

                    label = ttk.Label(strengths_frame, text=resist_text, foreground="#008000")
                    label.pack(anchor=tk.W, padx=10)

            # 5. Coverage Gaps Section
            coverage_gaps = data.get('coverage_gaps', [])
            if coverage_gaps:
                gaps_frame = ttk.LabelFrame(content_frame, text="🚨 Coverage Gaps", padding=10)
                gaps_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(gaps_frame, text="Types with no resistances on your team:",
                         foreground="#8B0000").pack(anchor=tk.W)

                for type_name, super_effective_count in coverage_gaps:
                    gap_text = f"• {type_name}: {super_effective_count}/{team_size} members take super effective damage, none resist"
                    label = ttk.Label(gaps_frame, text=gap_text, foreground="#8B0000")
                    label.pack(anchor=tk.W, padx=10)

            # 6. Effectiveness Grid Summary
            effectiveness_grid = data.get('effectiveness_grid', {})
            if effectiveness_grid:
                grid_frame = ttk.LabelFrame(content_frame, text="📊 Type Effectiveness Overview", padding=10)
                grid_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(grid_frame, text="How attacking types perform against your team:").pack(anchor=tk.W)

                # Create summary of most dangerous types
                dangerous_types = []
                for attack_type, effectiveness in effectiveness_grid.items():
                    total_super_effective = effectiveness.get("x4", 0) + effectiveness.get("x2", 0)
                    if total_super_effective >= 2:  # Hits 2+ members super effectively
                        dangerous_types.append((attack_type, total_super_effective, effectiveness))

                dangerous_types.sort(key=lambda x: x[1], reverse=True)

                if dangerous_types:
                    ttk.Label(grid_frame, text="\nMost Dangerous Attack Types:", font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, pady=(5, 0))
                    for attack_type, count, details in dangerous_types[:8]:  # Top 8
                        x4 = details.get("x4", 0)
                        x2 = details.get("x2", 0)
                        summary = f"• {attack_type}: hits {count} members super effectively"
                        if x4 > 0:
                            summary += f" ({x4} for 4x damage)"
                        ttk.Label(grid_frame, text=summary, foreground="#8B0000").pack(anchor=tk.W, padx=10)

            ttk.Label(content_frame, text="Analysis Complete",
                     foreground="green", font=('TkDefaultFont', 9, 'italic')).pack(pady=(20, 0))

            debug_log("Enhanced team defensive analysis UI rendered successfully")

        except Exception as e:
            debug_log(f"Error rendering enhanced defensive analysis UI: {e}")
            if hasattr(self, 'tab_team_defensive'):
                # Fallback simple display
                for widget in self.tab_team_defensive.winfo_children():
                    widget.destroy()
                ttk.Label(self.tab_team_defensive, text=f"Error rendering analysis: {e}",
                         foreground="red").pack(pady=20)

    def _render_offensive_analysis_ui(self, data):
        """Render the comprehensive team offensive analysis UI."""
        try:
            if not hasattr(self, 'tab_team_offensive'):
                return

            # Clear existing content
            for widget in self.tab_team_offensive.winfo_children():
                widget.destroy()

            # Create scrollable content frame
            canvas = tk.Canvas(self.tab_team_offensive)
            scrollbar = ttk.Scrollbar(self.tab_team_offensive, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            # Main content frame
            content_frame = ttk.Frame(scrollable_frame)
            content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # Title and refresh button frame
            title_frame = ttk.Frame(content_frame)
            title_frame.pack(fill=tk.X, pady=(0, 15))

            ttk.Label(title_frame, text="Team Offensive Analysis",
                     font=('TkDefaultFont', 14, 'bold')).pack(side=tk.LEFT)

            # Refresh button
            refresh_button = ttk.Button(title_frame, text="🔄 Refresh",
                                      command=self._force_refresh_team_analysis)
            refresh_button.pack(side=tk.RIGHT)

            # Check for errors first
            if data.get('error'):
                ttk.Label(content_frame, text=f"Error: {data['error']}",
                         foreground="red").pack()
                return

            if not data.get('analysis_complete'):
                ttk.Label(content_frame, text="Analysis not complete").pack()
                return

            # 1. Team Members and Moves Section
            team_members = data.get('team_members', [])
            if team_members:
                members_frame = ttk.LabelFrame(content_frame, text="🗡️ Team Members & Moves", padding=10)
                members_frame.pack(fill=tk.X, pady=(0, 10))

                for member in team_members:
                    member_name = member.get('name', 'Unknown')
                    member_level = member.get('level', '?')
                    moves_by_type = member.get('moves_by_type', {})
                    total_moves = member.get('total_moves', 0)

                    # Member header
                    member_header = f"{member_name} L{member_level} ({total_moves} moves)"
                    ttk.Label(members_frame, text=member_header, font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))

                    # Display moves by type in compact format
                    if moves_by_type:
                        moves_text = ""
                        for move_type, move_list in moves_by_type.items():
                            moves_text += f"  {move_type}: {', '.join(str(move) for move in move_list[:3])}"  # Show first 3 moves per type
                            if len(move_list) > 3:
                                moves_text += f" (+{len(move_list)-3} more)"
                            moves_text += "\n"

                        moves_label = ttk.Label(members_frame, text=moves_text.strip(), foreground="#4169E1")
                        moves_label.pack(anchor=tk.W, padx=15)
                    else:
                        ttk.Label(members_frame, text="  No moves available", foreground="gray").pack(anchor=tk.W, padx=15)

            # 2. Move Type Coverage Summary with type chips
            move_type_summary = data.get('move_type_summary', [])
            if move_type_summary:
                summary_frame = ttk.LabelFrame(content_frame, text="📊 Move Type Coverage Summary", padding=10)
                summary_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(summary_frame, text="Types available to your team:",
                         font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, pady=(0, 5))

                # Create type chips for all move types
                move_types = [type_info.get('type', 'Unknown') for type_info in move_type_summary]
                move_colors = [self._color_for_type(t) for t in move_types]

                chips_frame = ttk.Frame(summary_frame)
                chips_frame.pack(fill=tk.X, pady=(5, 10))
                self._render_type_chips(chips_frame, move_types, move_colors, per_row=6)

                # Details for each move type
                for type_info in move_type_summary:
                    detail_frame = ttk.Frame(summary_frame)
                    detail_frame.pack(fill=tk.X, padx=10, pady=2)

                    move_type = type_info.get('type', 'Unknown')
                    count = type_info.get('count', 0)
                    members_with_type = type_info.get('members_with_type', 0)

                    summary_text = f"• {move_type}: {count} moves across {members_with_type} members"
                    ttk.Label(detail_frame, text=summary_text, foreground="#006400").pack(side=tk.LEFT)

            # 3. Coverage Risks Section
            coverage_risks = data.get('coverage_risks', [])
            if coverage_risks:
                risks_frame = ttk.LabelFrame(content_frame, text="🚨 Coverage Risks", padding=10)
                risks_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(risks_frame, text="Defending types your team struggles against:",
                         foreground="#8B0000", font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, pady=(0, 5))

                # Create type chips for coverage risks
                risk_types = [risk[0] for risk in coverage_risks]
                risk_colors = [self._color_for_type(t) for t in risk_types]

                chips_frame = ttk.Frame(risks_frame)
                chips_frame.pack(fill=tk.X, pady=(5, 10))
                self._render_type_chips(chips_frame, risk_types, risk_colors, per_row=6)

                # Details for each risk
                for defending_type, risk_type in coverage_risks:
                    detail_frame = ttk.Frame(risks_frame)
                    detail_frame.pack(fill=tk.X, padx=10, pady=2)

                    if risk_type == "No Coverage":
                        risk_text = f"• {defending_type}: No coverage at all!"
                        color = "#8B0000"
                    else:  # "No Super Effective"
                        risk_text = f"• {defending_type}: No super effective moves"
                        color = "#FF4500"

                    ttk.Label(detail_frame, text=risk_text, foreground=color).pack(side=tk.LEFT)

            # 4. Limited Coverage Section
            limited_coverage = data.get('limited_coverage', [])
            if limited_coverage:
                limited_frame = ttk.LabelFrame(content_frame, text="⚡ Limited Coverage", padding=10)
                limited_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(limited_frame, text="Types with only 1-2 super effective moves:",
                         foreground="#FF8C00").pack(anchor=tk.W)

                for defending_type, super_count in limited_coverage:
                    limited_text = f"• {defending_type}: Only {super_count} super effective moves"
                    ttk.Label(limited_frame, text=limited_text, foreground="#FF8C00").pack(anchor=tk.W, padx=10)

            # 5. Coverage Analysis Overview
            coverage_analysis = data.get('coverage_analysis', {})
            if coverage_analysis:
                analysis_frame = ttk.LabelFrame(content_frame, text="🎯 Coverage Analysis Overview", padding=10)
                analysis_frame.pack(fill=tk.X, pady=(0, 10))

                ttk.Label(analysis_frame, text="Your team's best coverage against each type:").pack(anchor=tk.W)

                # Show coverage for types with good coverage
                good_coverage_types = []
                for defending_type, analysis in coverage_analysis.items():
                    best_coverage = analysis.get('best_coverage', {})
                    effectiveness = best_coverage.get('effectiveness', 0)
                    types = best_coverage.get('types', [])

                    if effectiveness >= 2.0 and types:  # Has super effective coverage
                        good_coverage_types.append((defending_type, effectiveness, types))

                good_coverage_types.sort(key=lambda x: x[1], reverse=True)

                if good_coverage_types:
                    ttk.Label(analysis_frame, text="\nBest Coverage:", font=('TkDefaultFont', 9, 'bold')).pack(anchor=tk.W, pady=(5, 0))
                    for defending_type, effectiveness, types in good_coverage_types[:10]:  # Top 10
                        eff_text = "4x" if effectiveness >= 4.0 else "2x"
                        type_list = ", ".join(types[:3])  # Show first 3 attack types
                        if len(types) > 3:
                            type_list += f" (+{len(types)-3} more)"

                        coverage_text = f"• vs {defending_type}: {eff_text} damage with {type_list}"
                        ttk.Label(analysis_frame, text=coverage_text, foreground="#008000").pack(anchor=tk.W, padx=10)

                # Show neutral coverage count
                neutral_count = sum(1 for defending_type, analysis in coverage_analysis.items()
                                   if analysis.get('best_coverage', {}).get('effectiveness', 0) == 1.0)
                if neutral_count > 0:
                    ttk.Label(analysis_frame, text=f"\nNeutral coverage against {neutral_count} types",
                             foreground="#4169E1").pack(anchor=tk.W, pady=(5, 0))

            ttk.Label(content_frame, text="Analysis Complete",
                     foreground="green", font=('TkDefaultFont', 9, 'italic')).pack(pady=(20, 0))

            debug_log("Enhanced team offensive analysis UI rendered successfully")

        except Exception as e:
            debug_log(f"Error rendering enhanced offensive analysis UI: {e}")
            if hasattr(self, 'tab_team_offensive'):
                # Fallback simple display
                for widget in self.tab_team_offensive.winfo_children():
                    widget.destroy()
                ttk.Label(self.tab_team_offensive, text=f"Error rendering analysis: {e}",
                         foreground="red").pack(pady=20)

    def _apply_cached_team_analysis(self, cached_data):
        """Apply cached team analysis data to defensive UI."""
        try:
            debug_log("Applying cached team analysis")
            self._render_defensive_analysis_ui(cached_data)
        except Exception as e:
            debug_log(f"Error applying cached team analysis: {e}")

    def _apply_cached_offensive_analysis(self, cached_data):
        """Apply cached offensive analysis data to UI."""
        try:
            debug_log("Applying cached offensive analysis")
            self._render_offensive_analysis_ui(cached_data)
        except Exception as e:
            debug_log(f"Error applying cached offensive analysis: {e}")

    def _compute_team_offensive_coverage_safe(self):
        """Safe version of team offensive coverage computation that doesn't block UI."""
        try:
            debug_log("Starting safe offensive coverage computation...")
            # Check if we actually need to recompute (avoid unnecessary work)
            if not hasattr(self, 'party') or not self.party:
                debug_log("No party data, skipping offensive coverage")
                return

            # Show loading state but don't block
            self._show_loading_indicator("Computing offensive coverage...")

            # Defer the actual computation
            self.after_idle(lambda: self._do_compute_offensive_coverage_safe())

        except Exception as e:
            debug_log(f"Error in safe offensive coverage computation: {e}")

    def _do_compute_offensive_coverage_safe(self):
        """Safely perform the actual offensive coverage computation."""
        try:
            debug_log("Performing safe offensive coverage computation...")
            # TODO: Implement safe computation here if needed
            # For now, just hide loading indicator
            self._hide_loading_indicator()
            debug_log("Safe offensive coverage computation completed")
        except Exception as e:
            debug_log(f"Error in safe offensive coverage computation: {e}")
            self._hide_loading_indicator()

    def _get_party_member_cache_key(self, party_index: int, mon: dict) -> str:
        """Generate a cache key for a party member's analysis data."""
        try:
            species_id = _get_species_id(mon) or 0
            level = _get(mon, ("level", "lvl")) or 1
            form_slug = self._detect_form_slug(mon) or ""
            mon_id = mon.get("id", "unknown")
            return f"party_{party_index}_{species_id}_{level}_{form_slug}_{mon_id}"
        except Exception:
            return f"party_{party_index}_fallback"

    def _cache_party_member_analysis(self, party_index: int, mon: dict, analysis_data: dict):
        """Cache analysis data for a specific party member."""
        try:
            cache_key = self._get_party_member_cache_key(party_index, mon)
            self._pokemon_analysis_cache[cache_key] = {
                **analysis_data,
                "cached_at": time.time(),
                "party_index": party_index
            }
            debug_log(f"Cached analysis for party member {party_index}")
        except Exception as e:
            debug_log(f"Error caching party member analysis: {e}")

    def _get_cached_party_member_analysis(self, party_index: int, mon: dict) -> Optional[dict]:
        """Get cached analysis data for a specific party member."""
        try:
            cache_key = self._get_party_member_cache_key(party_index, mon)
            if cache_key in self._pokemon_analysis_cache:
                cached_data = self._pokemon_analysis_cache[cache_key]
                # Check if cache is still fresh (within 5 minutes)
                cache_age = time.time() - cached_data.get("cached_at", 0)
                if cache_age < 300:  # 5 minutes
                    debug_log(f"Using cached analysis for party member {party_index}")
                    return cached_data
                else:
                    # Remove stale cache
                    del self._pokemon_analysis_cache[cache_key]
            return None
        except Exception as e:
            debug_log(f"Error getting cached party member analysis: {e}")
            return None

    def _cache_party_member_data(self, party_index: int, mon: dict, full_data: dict):
        """Cache full data for a party member to speed up switching."""
        try:
            self._party_member_cache[party_index] = {
                "mon_data": mon.copy() if isinstance(mon, dict) else {},
                "full_data": full_data.copy() if isinstance(full_data, dict) else {},
                "cached_at": time.time()
            }
            debug_log(f"Cached full data for party member {party_index}")
        except Exception as e:
            debug_log(f"Error caching party member data: {e}")

    def _get_cached_party_member_data(self, party_index: int) -> Optional[dict]:
        """Get cached full data for a party member."""
        try:
            if party_index in self._party_member_cache:
                cached_data = self._party_member_cache[party_index]
                # Check if cache is still fresh (within 10 minutes)
                cache_age = time.time() - cached_data.get("cached_at", 0)
                if cache_age < 600:  # 10 minutes
                    debug_log(f"Using cached data for party member {party_index}")
                    return cached_data
                else:
                    # Remove stale cache
                    del self._party_member_cache[party_index]
            return None
        except Exception as e:
            debug_log(f"Error getting cached party member data: {e}")
            return None

    def _invalidate_party_member_caches(self, party_index: Optional[int] = None):
        """Invalidate party member caches when data changes."""
        try:
            if party_index is not None:
                # Invalidate specific party member
                if party_index in self._party_member_cache:
                    del self._party_member_cache[party_index]
                # Invalidate analysis cache for this member
                keys_to_remove = [k for k in self._pokemon_analysis_cache.keys()
                                 if k.startswith(f"party_{party_index}_")]
                for key in keys_to_remove:
                    del self._pokemon_analysis_cache[key]
                debug_log(f"Invalidated cache for party member {party_index}")
            else:
                # Invalidate all party member caches
                self._party_member_cache.clear()
                self._pokemon_analysis_cache.clear()
                debug_log("Invalidated all party member caches")

            # Always invalidate team analysis caches when any party member changes
            self._invalidate_team_analysis_caches()
        except Exception as e:
            debug_log(f"Error invalidating party member caches: {e}")

    def _invalidate_team_analysis_caches(self):
        """Invalidate team analysis caches when team data changes."""
        try:
            # Invalidate team analysis caches
            if hasattr(self, '_team_analysis_cache'):
                self._team_analysis_cache.clear()
            if hasattr(self, '_team_defensive_cache'):
                self._team_defensive_cache.clear()
            if hasattr(self, '_team_offensive_cache'):
                self._team_offensive_cache.clear()

            # Clear background cache manager team analysis cache
            cache_manager = BackgroundCacheManager()
            username = getattr(self.api, 'username', 'default')
            cache_manager.invalidate_cache(username, self.slot)

            debug_log("Invalidated team analysis caches")

            # Auto-refresh team analysis if trainer is currently selected
            if hasattr(self, 'target_var') and self.target_var.get() == "trainer":
                self.after(100, self._refresh_team_analysis_if_visible)

        except Exception as e:
            debug_log(f"Error invalidating team analysis caches: {e}")

    def _invalidate_pokemon_offensive_cache(self, mon: dict):
        """Invalidate offensive analysis caches for a specific Pokémon when its moves change."""
        try:
            if not mon:
                return
                
            # Generate cache key for this specific Pokémon
            mon_key = self._get_pokemon_cache_key(mon)
            if not mon_key:
                return
            
            # Invalidate only this Pokémon's coverage cache
            if hasattr(self, '_mon_coverage_cache'):
                old_size = len(self._mon_coverage_cache)
                self._mon_coverage_cache.pop(mon_key, None)
                debug_log(f"Invalidated offensive cache for Pokémon {mon_key}: {old_size} -> {len(self._mon_coverage_cache)}")
            
            # Invalidate team offensive cache since this Pokémon's moves affect team analysis
            if hasattr(self, '_team_offensive_cache'):
                self._team_offensive_cache.clear()
                debug_log("Invalidated team offensive cache due to move changes")
            
            # Also invalidate general team analysis cache since offensive analysis is part of it
            if hasattr(self, '_team_analysis_cache'):
                self._team_analysis_cache.clear()
                debug_log("Invalidated team analysis cache due to move changes")
            
        except Exception as e:
            debug_log(f"Error invalidating Pokémon offensive cache: {e}")

    def _get_pokemon_cache_key(self, mon: dict) -> str:
        """Generate a cache key for a specific Pokémon."""
        try:
            if not mon:
                return None
            species_id = mon.get('species', 0)
            form_id = mon.get('form', 0)
            return f"{species_id}_{form_id}"
        except Exception:
            return None

    def _refresh_team_analysis_if_visible(self):
        """Refresh team analysis if analysis tabs are currently visible."""
        try:
            if (hasattr(self, 'tabs') and hasattr(self, 'tab_team_defensive')
                and hasattr(self, 'tab_team_offensive')):
                # Check if trainer is selected and analysis tabs exist
                if hasattr(self, 'target_var') and self.target_var.get() == "trainer":
                    debug_log("Auto-refreshing team analysis after data change")
                    self._load_trainer_analysis_enhanced()
        except Exception as e:
            debug_log(f"Error in auto-refresh team analysis: {e}")

    def _force_refresh_team_analysis(self):
        """Force refresh team analysis by clearing caches and reloading."""
        try:
            debug_log("Force refreshing team analysis")

            # Show loading state immediately
            self._show_team_analysis_loading()

            # Clear all caches
            self._invalidate_team_analysis_caches()

            # Force reload after a brief delay to show loading animation
            self.after(150, self._load_trainer_analysis_enhanced)

        except Exception as e:
            debug_log(f"Error in force refresh team analysis: {e}")

    def _show_team_analysis_loading(self):
        """Show loading animations on both analysis tabs."""
        try:
            # Show loading on defensive tab
            if hasattr(self, 'tab_team_defensive'):
                for widget in self.tab_team_defensive.winfo_children():
                    widget.destroy()
                loading_frame = ttk.Frame(self.tab_team_defensive)
                loading_frame.pack(fill=tk.BOTH, expand=True)
                ttk.Label(loading_frame, text="🔄 Refreshing Team Analysis...",
                         font=('TkDefaultFont', 12)).pack(expand=True)

            # Show loading on offensive tab
            if hasattr(self, 'tab_team_offensive'):
                for widget in self.tab_team_offensive.winfo_children():
                    widget.destroy()
                loading_frame = ttk.Frame(self.tab_team_offensive)
                loading_frame.pack(fill=tk.BOTH, expand=True)
                ttk.Label(loading_frame, text="🔄 Refreshing Team Analysis...",
                         font=('TkDefaultFont', 12)).pack(expand=True)

        except Exception as e:
            debug_log(f"Error showing team analysis loading: {e}")

    def _load_trainer_snapshot(self):
        # Populate trainer tab from slot/session data (Team Editor focuses on slot)
        try:
            # Money
            val = None
            try:
                val = self.data.get('money') if isinstance(self.data, dict) else None
            except Exception:
                val = None
            self.var_money.set(str(val if val is not None else ""))
            # Weather
            wkey = self._weather_key()
            cur = self.data.get(wkey) if (wkey and isinstance(self.data, dict)) else None
            if isinstance(cur, int) and self._weather_i2n:
                name = self._weather_i2n.get(int(cur), str(cur))
                self.var_weather.set(f"{name} ({cur})")
            else:
                self.var_weather.set("")
            # Display-only play time, game mode
            pt = self.data.get('playTime') if isinstance(self.data, dict) else None
            if isinstance(pt, int):
                hours = pt // 3600
                minutes = (pt % 3600) // 60
                seconds = pt % 60
                self.lbl_playtime.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            else:
                self.lbl_playtime.configure(text='-')
            gm = self.data.get('gameMode') if isinstance(self.data, dict) else None
            if gm is not None:
                self.lbl_gamemode.configure(text=str(gm))
            else:
                self.lbl_gamemode.configure(text='-')
        except Exception:
            pass

    def _weather_key(self) -> Optional[str]:
        for k in ("weather", "weatherType", "currentWeather"):
            if isinstance(self.data, dict) and k in self.data:
                return k
        return "weather"

    def _build_defensive_analysis_scrollable(self, parent: ttk.Frame):
        """Build the defensive analysis section with scrolling."""
        # Create canvas and scrollbar for scrolling
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content_frame = ttk.Frame(canvas)

        # Configure scrolling
        content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Add mousewheel support
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        canvas.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))

        # Build the actual content in the scrollable frame
        self._build_defensive_analysis(content_frame)

    def _build_offensive_analysis_scrollable(self, parent: ttk.Frame):
        """Build the offensive analysis section with scrolling."""
        # Create canvas and scrollbar for scrolling
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content_frame = ttk.Frame(canvas)

        # Configure scrolling
        content_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Add mousewheel support
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        canvas.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))

        # Build the actual content in the scrollable frame
        self._build_offensive_analysis(content_frame)

    def _init_performance_caches(self):
        """Initialize enhanced caching system for better performance."""
        # Existing caches (enhanced)
        self._matchup_cache = {}  # Pokemon -> type matchup multipliers
        self._mon_coverage_cache = {}  # Pokemon -> coverage analysis

        # New performance caches
        self._type_matrix_cache = None  # Cached type effectiveness matrix
        self._pokemon_catalog_cache = None  # Cached Pokemon catalog
        self._base_stats_cache = {}  # Species ID -> base stats
        self._species_types_cache = {}  # Species ID -> types
        self._team_hash_cache = None  # Current team composition hash
        self._team_analysis_cache = {}  # Team hash -> analysis results

        # Cache invalidation tracking
        self._cache_version = 1

    def _start_background_cache_warming(self):
        """Start background cache warming for team analysis."""
        try:
            # Only start background cache if we have a valid party
            if not self.party or not any(self.party):
                print("Skipping background cache warming - no party data")
                return
                
            username = getattr(self.api, 'username', 'default')
            self._background_cache_future = warm_team_analysis_cache(self.api, self.slot, username)
            print(f"Started background cache warming for {username}, slot {self.slot}")
        except Exception as e:
            print(f"Error starting background cache warming: {e}")
            # Set to None to prevent hanging
            self._background_cache_future = None

    def _get_cached_analysis_data(self) -> Optional[Dict[str, Any]]:
        """Get cached analysis data from background cache manager."""
        if self._cached_analysis_data:
            return self._cached_analysis_data

        username = getattr(self.api, 'username', 'default')
        cached_data = _cache_manager.get_cached_data(f"team_analysis_{username}_{self.slot}")
        if cached_data:
            self._cached_analysis_data = cached_data
            print("Using pre-computed background cache data")
        return cached_data

    def _use_cached_data_if_available(self, builder_func, parent_frame, cache_key: str):
        """Use cached data for building UI if available, otherwise build normally."""
        cached_data = self._get_cached_analysis_data()

        if cached_data and not cached_data.get("error"):
            print(f"Building {cache_key} from cached data (computed in {cached_data.get('computation_time', 0):.2f}s)")
            try:
                if cache_key == "defensive":
                    self._build_cached_defensive_analysis(parent_frame, cached_data)
                elif cache_key == "offensive":
                    self._build_cached_offensive_analysis(parent_frame, cached_data)
                return True
            except Exception as e:
                print(f"Error using cached data for {cache_key}: {e}")
                # Fall back to normal building

        # Check if background cache is still running and wait briefly
        if hasattr(self, '_background_cache_future') and self._background_cache_future and not self._background_cache_future.done():
            print(f"Background cache still running for {cache_key}, building normally to avoid hanging")
            # Don't wait for background cache to avoid UI freezing
            builder_func(parent_frame)
            return False

        # Build normally if no cache or cache failed
        print(f"Building {cache_key} analysis normally (no cache or cache failed)")
        builder_func(parent_frame)
        return False

    def _build_cached_defensive_analysis(self, parent: ttk.Frame, cached_data: Dict[str, Any]):
        """Build defensive analysis using cached data."""
        # Create scrollable frame
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_frame)
        scrollbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        # Build content using cached data
        content_frame = ttk.Frame(scrollable_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Header
        ttk.Label(content_frame, text="Team defensive analysis (from cache)",
                 foreground="green").pack(anchor=tk.W, pady=(0, 4))

        # Team members section
        party_matchups = cached_data.get("party_matchups", [])
        if party_matchups:
            members_lf = ttk.LabelFrame(content_frame, text="Team Members")
            members_lf.pack(fill=tk.X, pady=(0, 6))

            for member in party_matchups:
                member_frame = ttk.Frame(members_lf)
                member_frame.pack(fill=tk.X, padx=6, pady=2)

                species_name = member.get("species_name", "Unknown")
                ttk.Label(member_frame, text=f"{member['index']+1}. {species_name}").pack(side=tk.LEFT)

        # Team risks section
        team_data = cached_data.get("team_defensive", {})
        common_weaknesses = team_data.get("common_weaknesses", [])
        if common_weaknesses:
            risks_lf = ttk.LabelFrame(content_frame, text="Common Team Weaknesses")
            risks_lf.pack(fill=tk.X, pady=(0, 6))

            for weakness_type, count in common_weaknesses[:5]:  # Top 5
                risk_frame = ttk.Frame(risks_lf)
                risk_frame.pack(fill=tk.X, padx=6, pady=1)

                ttk.Label(risk_frame, text=f"{weakness_type.title()}: {count} members weak").pack(side=tk.LEFT)

        # Configure scrolling
        def _configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas_width = event.width
            canvas.itemconfig(canvas_frame, width=canvas_width)

        canvas.bind('<Configure>', _configure_scroll)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _build_cached_offensive_analysis(self, parent: ttk.Frame, cached_data: Dict[str, Any]):
        """Build offensive analysis using cached data."""
        # Create scrollable frame
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        content_frame = ttk.Frame(scroll_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Header
        ttk.Label(content_frame, text="Team offensive analysis (from cache)",
                 foreground="green").pack(anchor=tk.W, pady=(0, 4))

        # Placeholder for offensive analysis content
        team_data = cached_data.get("team_offensive", {})
        party_size = team_data.get("party_size", 0)

        info_frame = ttk.Frame(content_frame)
        info_frame.pack(fill=tk.X, pady=6)

        ttk.Label(info_frame, text=f"Offensive coverage analysis for {party_size} party members").pack(anchor=tk.W)
        self._last_party_size = 0

    def _invalidate_caches_if_needed(self):
        """Smart cache invalidation based on party changes."""
        try:
            current_party_size = len(self.party)
            current_team_hash = self._compute_team_hash()

            # Check if team composition changed
            if (current_party_size != self._last_party_size or
                current_team_hash != self._team_hash_cache):

                # Invalidate team-level caches only
                self._team_analysis_cache.clear()
                self._team_hash_cache = current_team_hash
                self._last_party_size = current_party_size

                # Keep individual Pokemon caches unless Pokemon removed
                if current_party_size < self._last_party_size:
                    self._matchup_cache.clear()
                    self._mon_coverage_cache.clear()

        except Exception:
            pass  # Fail silently for cache management

    def _compute_team_hash(self) -> str:
        """Compute a hash of current team composition for cache invalidation."""
        try:
            # Create hash based on Pokemon IDs and species
            team_data = []
            for mon in self.party:
                pokemon_id = mon.get('id', 0)
                species_id = _get_species_id(mon) or 0
                team_data.append(f"{pokemon_id}:{species_id}")
            return hash(tuple(sorted(team_data)))
        except Exception:
            return "unknown"

    def _get_cached_type_matrix(self):
        """Get cached type effectiveness matrix."""
        if self._type_matrix_cache is None:
            self._type_matrix_cache = load_type_matchup_matrix()
        return self._type_matrix_cache

    def _get_cached_pokemon_catalog(self):
        """Get cached Pokemon catalog."""
        if self._pokemon_catalog_cache is None:
            self._pokemon_catalog_cache = load_pokemon_catalog() or {}
        return self._pokemon_catalog_cache

    def _get_cached_species_types(self, species_id: int, form_slug: str = None) -> tuple:
        """Get cached Pokemon types with form support."""
        cache_key = f"{species_id}:{form_slug or 'base'}"

        if cache_key not in self._species_types_cache:
            try:
                cat = self._get_cached_pokemon_catalog()
                by_dex = cat.get("by_dex") or {}
                entry = by_dex.get(str(species_id)) or {}

                if form_slug and (entry.get("forms") or {}).get(form_slug):
                    tp = (entry.get("forms") or {}).get(form_slug, {}).get("types") or {}
                else:
                    tp = entry.get("types") or {}

                t1 = str(tp.get("type1") or "unknown").strip().lower()
                t2 = str(tp.get("type2") or "").strip().lower() if tp.get("type2") else None

                self._species_types_cache[cache_key] = (t1, t2)
            except Exception:
                self._species_types_cache[cache_key] = ("unknown", None)

        return self._species_types_cache[cache_key]

    def _apply_cached_team_analysis(self, cached_analysis: dict):
        """Apply previously computed team analysis from cache."""
        try:
            # Apply cached bins
            bins_counts = cached_analysis.get('bins_counts', {})
            for bin_name, bin_data in bins_counts.items():
                if bin_name in self._team_bins:
                    bin_frame = self._team_bins[bin_name]
                    # Clear existing content
                    for widget in bin_frame.winfo_children():
                        widget.destroy()

                    # Apply cached results
                    types_in_bin = [t for t, count in bin_data.items() if count > 0]
                    if types_in_bin:
                        labels = [t.title() for t in types_in_bin]
                        colors = [self._color_for_type(t) for t in types_in_bin]
                        self._render_type_chips(bin_frame, labels, colors, per_row=6)
                    else:
                        ttk.Label(bin_frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            # Apply cached team members display
            team_members_data = cached_analysis.get('team_members', [])
            for widget in self._team_members_frame.winfo_children():
                widget.destroy()

            for member_data in team_members_data:
                block = ttk.Frame(self._team_members_frame)
                block.pack(fill=tk.X, padx=6, pady=4)

                # Recreate member display from cached data
                top = ttk.Frame(block)
                top.pack(fill=tk.X)
                ttk.Label(top, text=member_data['label']).pack(side=tk.LEFT)

                chip_frame = ttk.Frame(top)
                chip_frame.pack(side=tk.LEFT, padx=8)
                if member_data['type_labels']:
                    self._render_type_chips(chip_frame, member_data['type_labels'],
                                          member_data['type_colors'], per_row=6)

                # Form info if present
                if member_data.get('form_info'):
                    form_line = ttk.Frame(block)
                    form_line.pack(fill=tk.X)
                    ttk.Label(form_line, text=member_data['form_info'],
                             foreground="gray").pack(side=tk.LEFT, padx=24)

            # Apply cached risks
            risks = cached_analysis.get('risks', [])
            for widget in self._team_risks_frame.winfo_children():
                widget.destroy()

            if risks:
                labels = [r['label'] for r in risks]
                colors = [r['color'] for r in risks]
                self._render_type_chips(self._team_risks_frame, labels, colors, per_row=6)
            else:
                ttk.Label(self._team_risks_frame, text="No major overlapping weaknesses detected.").pack(anchor=tk.W)

        except Exception as e:
            print(f"Error applying cached team analysis: {e}")
            # Fall back to full recomputation
            self._team_analysis_cache.pop(self._compute_team_hash(), None)

    def _apply_cached_team_analysis_from_background(self, cached_data: Dict[str, Any]):
        """Apply team analysis from background cache to UI."""
        try:
            # Apply defensive analysis from background cache
            if "team_defensive" in cached_data:
                self._apply_cached_defensive_analysis(cached_data["team_defensive"])
            
            # Apply offensive analysis from background cache
            if "team_offensive" in cached_data:
                self._apply_cached_offensive_analysis(cached_data["team_offensive"])
                
            print(f"Applied team analysis from background cache (computed in {cached_data.get('computation_time', 0):.2f}s)")
                
        except Exception as e:
            print(f"Error applying background cached team analysis: {e}")

    def _cache_team_analysis(self, bins_counts: dict, team_members_data: list, risks: list):
        """Cache the computed team analysis for future use."""
        try:
            team_hash = self._compute_team_hash()
            self._team_analysis_cache[team_hash] = {
                'bins_counts': bins_counts,
                'team_members': team_members_data,
                'risks': risks,
                'timestamp': hash(str(time.time()))  # For potential cache expiry
            }
        except Exception:
            pass  # Fail silently for caching

    def _create_skeleton_frame(self, parent, text: str = "Loading...") -> ttk.Frame:
        """Create a skeleton UI frame for loading states."""
        skeleton = ttk.Frame(parent)
        skeleton.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Loading message
        loading_label = ttk.Label(skeleton, text=text, foreground="gray",
                                 font=('TkDefaultFont', 10, 'italic'))
        loading_label.pack(pady=10)

        # Skeleton content - placeholder boxes
        for i in range(3):
            placeholder = ttk.Frame(skeleton, relief='ridge', borderwidth=1)
            placeholder.pack(fill=tk.X, padx=20, pady=2)

            # Add some fake content to show structure
            placeholder_label = ttk.Label(placeholder, text="█" * (20 - i * 2),
                                        foreground="lightgray")
            placeholder_label.pack(padx=5, pady=2)

        return skeleton

    def _replace_skeleton_with_content(self, parent, skeleton, builder_func):
        """Replace skeleton UI with actual content."""
        try:
            # Destroy skeleton
            skeleton.destroy()

            # Build actual content
            builder_func(parent)
        except Exception as e:
            # If content building fails, show error
            error_frame = ttk.Frame(parent)
            error_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

            ttk.Label(error_frame, text=f"Error loading content: {e}",
                     foreground="red").pack(pady=10)

    def _load_window_geometry(self, default_geometry: str):
        """Load saved window geometry from persistence or use default."""
        try:
            from rogueeditor.persistence import persistence_manager
            username = getattr(self.master, 'username', None)
            if username:
                saved_geometry = persistence_manager.get_user_value(username, 'team_manager_geometry')
                if saved_geometry:
                    self.geometry(saved_geometry)
                    debug_log(f"Restored window geometry: {saved_geometry}")
                    return

            # Fall back to default
            self.geometry(default_geometry)
            debug_log(f"Using default window geometry: {default_geometry}")
        except Exception as e:
            debug_log(f"Error loading window geometry: {e}, using default")
            self.geometry(default_geometry)

    def _on_window_configure(self, event=None):
        """Save window geometry when window is resized or moved."""
        # Only save if the event is for the main window (not child widgets)
        if event and event.widget != self:
            return
        try:
            from rogueeditor.persistence import persistence_manager
            username = getattr(self.master, 'username', None)
            if username:
                geometry = self.geometry()
                persistence_manager.set_user_value(username, 'team_manager_geometry', geometry)
        except Exception:
            pass
