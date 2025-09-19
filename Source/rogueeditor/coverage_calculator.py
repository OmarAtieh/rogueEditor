"""
Offensive matchups calculator for Pokemon teams.
Analyzes type effectiveness and identifies coverage gaps.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from .catalog import (
    load_pokemon_catalog,
    get_move_type_name,
    is_move_offensive,
    get_move_label,
    get_move_entry,
)
from .utils import repo_path


# Boss Pokemon data for special analysis
BOSS_POKEMON = {
    "eternatus": {
        "species_id": 890,
        "types": ["poison", "dragon"],
        "abilities": ["pressure"],
        "resistances": ["fighting", "water", "electric", "grass", "fire", "bug", "steel"],
        "weaknesses": ["ice", "dragon", "psychic", "ground"],
        "name": "Eternatus"
    },
    "rayquaza": {
        "species_id": 384,
        "types": ["dragon", "flying"],
        "abilities": ["air_lock"],
        "resistances": ["fighting", "ground", "bug", "grass"],
        "weaknesses": ["ice", "dragon", "fairy", "rock", "electric"],
        "name": "Rayquaza"
    },
    "mega_rayquaza": {
        "species_id": 384,
        "form": "mega",
        "types": ["dragon", "flying"],
        "abilities": ["delta_stream"],
        "resistances": ["fighting", "ground", "bug", "grass"],
        "weaknesses": ["ice", "dragon", "fairy"],  # Delta Stream negates Electric/Rock weakness
        "special_notes": "Delta Stream negates Flying weaknesses but not resistances/immunities",
        "name": "Mega Rayquaza"
    }
}


def load_type_matrix() -> Dict:
    """Load the type effectiveness matrix."""
    try:
        data_path = repo_path("data", "type_matrix.json")
        with open(data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading type matrix: {e}")
        return {}


def load_moves_enhanced() -> Dict:
    """Deprecated shim (kept for compatibility). No-op with unified data."""
    return {}


def load_moves_basic() -> Dict:
    """Deprecated shim (kept for compatibility). No-op with unified data."""
    return {}


def get_type_effectiveness(attacking_type: str, defending_types: List[str], type_matrix: Dict) -> float:
    """
    Calculate type effectiveness multiplier.

    Args:
        attacking_type: The type of the attacking move
        defending_types: List of defending Pokemon types (1 or 2 types)
        type_matrix: Type effectiveness matrix (defensive perspective)

    Returns:
        Effectiveness multiplier (4.0, 2.0, 1.0, 0.5, 0.25, 0.0)
    """
    if not attacking_type or not defending_types:
        return 1.0

    total_effectiveness = 1.0

    # Handle both orientations of the matrix robustly.
    # Preferred: defensive rows with attacking columns → matrix[def][att]
    # Fallback: attacking rows with defensive columns → matrix[att][def]
    for defending_type in defending_types:
        eff = None
        # Try defensive perspective first
        row = type_matrix.get(defending_type) or {}
        if isinstance(row, dict) and attacking_type in row:
            eff = row.get(attacking_type)
        # If missing, try attacking perspective
        if eff is None:
            row2 = type_matrix.get(attacking_type) or {}
            if isinstance(row2, dict) and defending_type in row2:
                eff = row2.get(defending_type)
        try:
            val = float(eff) if eff is not None else 1.0
        except Exception:
            val = 1.0
        total_effectiveness *= val

    return total_effectiveness


def find_type_combo_walls(move_types: List[str], type_matrix: Dict) -> Dict[str, List[Tuple[str, ...]]]:
    """Identify single and dual type combinations that wall all given attacking move types.

    A wall means effectiveness <= 0.5 for all attacking types (resist or immune).
    Returns dict with keys 'single' and 'dual' listing type tuples.
    """
    # Collect all type names from matrix
    types: List[str] = sorted({str(k).strip().lower() for k in type_matrix.keys()})
    single: List[Tuple[str, ...]] = []
    dual: List[Tuple[str, ...]] = []

    def walls(def_types: List[str]) -> bool:
        for att in move_types:
            eff = get_type_effectiveness(att, def_types, type_matrix)
            if eff > 0.5:
                return False
        return True

    # Single types
    for t in types:
        if walls([t]):
            single.append((t,))

    # Dual types
    for i in range(len(types)):
        for j in range(i + 1, len(types)):
            a, b = types[i], types[j]
            if walls([a, b]):
                dual.append((a, b))

    return {"single": single, "dual": dual}


def get_move_type(move_id: int, enhanced_moves: Dict, basic_moves: Dict) -> Optional[str]:
    """Get the type of a move by ID using unified moves_data.json."""
    return get_move_type_name(move_id)


def is_move_damaging(move_id: int, enhanced_moves: Dict, basic_moves: Dict) -> bool:
    """Check if a move is damaging using unified moves_data.json flag."""
    val = is_move_offensive(move_id)
    return bool(val) if val is not None else True


def calculate_pokemon_coverage(pokemon_moves: List[int], type_matrix: Dict,
                             enhanced_moves: Dict, basic_moves: Dict) -> Dict:
    """
    Calculate offensive type coverage for a single Pokemon.

    Args:
        pokemon_moves: List of move IDs
        type_matrix: Type effectiveness matrix
        enhanced_moves: Enhanced moves database
        basic_moves: Basic moves database

    Returns:
        Coverage analysis dictionary
    """
    if not pokemon_moves:
        return {"damaging_moves": [], "type_coverage": {}, "coverage_summary": {}}

    damaging_moves = []
    move_types = set()

    # Analyze each move
    for move_id in pokemon_moves:
        if is_move_damaging(move_id, enhanced_moves, basic_moves):
            move_type = get_move_type(move_id, enhanced_moves, basic_moves)
            if move_type:
                entry = get_move_entry(move_id) or {}
                damaging_moves.append({
                    "id": move_id,
                    "type": move_type,
                    "name": get_move_label(move_id) or basic_moves.get("id_to_name", {}).get(str(move_id), f"Move_{move_id}"),
                    "power": entry.get("power"),
                    "accuracy": entry.get("accuracy"),
                })
                move_types.add(move_type)

    # Calculate coverage against all types
    # Derive type list from matrix keys to avoid orientation/header issues
    all_types_set: Set[str] = set()
    for k, v in (type_matrix or {}).items():
        try:
            key = str(k).strip().lower()
            if key and "attack" not in key:
                all_types_set.add(key)
            if isinstance(v, dict):
                for k2 in v.keys():
                    key2 = str(k2).strip().lower()
                    if key2 and "attack" not in key2:
                        all_types_set.add(key2)
        except Exception:
            continue
    all_types = sorted(all_types_set) or [
        "normal","fighting","flying","poison","ground","rock","bug",
        "ghost","steel","fire","water","grass","electric","psychic",
        "ice","dragon","dark","fairy"
    ]

    type_coverage = {}

    for defending_type in all_types:
        best_effectiveness = 0.0
        best_move_type = None

        for attacking_type in move_types:
            effectiveness = get_type_effectiveness(attacking_type, [defending_type], type_matrix)
            if effectiveness > best_effectiveness:
                best_effectiveness = effectiveness
                best_move_type = attacking_type

        type_coverage[defending_type] = {
            "effectiveness": best_effectiveness,
            "best_move_type": best_move_type
        }

    # Summarize coverage
    super_effective = []  # x2 or better
    not_very_effective = []  # x0.5 or worse
    neutral = []  # x1
    no_effect = []  # x0

    for defending_type, coverage in type_coverage.items():
        effectiveness = coverage["effectiveness"]
        if effectiveness >= 2.0:
            super_effective.append(defending_type)
        elif effectiveness == 0.0:
            no_effect.append(defending_type)
        elif effectiveness <= 0.5:
            not_very_effective.append(defending_type)
        else:
            neutral.append(defending_type)

    coverage_summary = {
        "super_effective": super_effective,
        "neutral": neutral,
        "not_very_effective": not_very_effective,
        "no_effect": no_effect,
        "move_types": list(move_types)
    }

    return {
        "damaging_moves": damaging_moves,
        "type_coverage": type_coverage,
        "coverage_summary": coverage_summary
    }


def analyze_boss_coverage(pokemon_coverage: Dict, type_matrix: Dict) -> Dict:
    """Analyze coverage against boss Pokemon."""
    boss_analysis = {}

    for boss_name, boss_data in BOSS_POKEMON.items():
        boss_types = boss_data["types"]
        boss_resistances = boss_data.get("resistances", [])
        boss_weaknesses = boss_data.get("weaknesses", [])

        # Find best move type against this boss
        best_effectiveness = 0.0
        best_move_type = None
        effective_moves = []

        move_types = pokemon_coverage.get("coverage_summary", {}).get("move_types") or []
        if move_types:
            for move_type in move_types:
                # Compute effectiveness with boss-specific adjustments
                effectiveness = _effectiveness_vs_boss(move_type, boss_name, boss_types, boss_data, type_matrix)

                if effectiveness > best_effectiveness:
                    best_effectiveness = effectiveness
                    best_move_type = move_type

                # Update effective moves list with corrected effectiveness
                if effectiveness >= 1.0:  # Neutral or better
                    effective_moves.append({
                        "type": move_type,
                        "effectiveness": effectiveness
                    })

        # Determine coverage status
        if best_effectiveness >= 2.0:
            status = "excellent"
        elif best_effectiveness >= 1.0:
            status = "good"
        elif best_effectiveness > 0.0:
            status = "poor"
        else:
            status = "none"

        boss_analysis[boss_name] = {
            "name": boss_data["name"],
            "types": boss_types,
            "best_effectiveness": best_effectiveness,
            "best_move_type": best_move_type,
            "effective_moves": effective_moves,
            "status": status,
            "special_notes": boss_data.get("special_notes", "")
        }

    return boss_analysis


def _effectiveness_vs_boss(move_type: str, boss_name: str, boss_types: List[str], boss_data: Dict, type_matrix: Dict) -> float:
    """Compute effectiveness of a move type vs a boss, applying special rules.

    - Enforce explicit boss resistances (<=0.5) and weaknesses (>=2.0)
    - Delta Stream (Mega Rayquaza): neutralize Flying-type weaknesses while preserving other type contributions
    """
    # Base effectiveness against combined types
    effectiveness = get_type_effectiveness(move_type, boss_types, type_matrix)

    # Delta Stream for Mega Rayquaza: neutralize Flying weaknesses (Ice, Rock, Electric become neutral regarding the Flying half).
    if boss_name == "mega_rayquaza" and "delta_stream" in (boss_data.get("abilities", []) or []):
        if "flying" in boss_types:
            # Compute contributions separately: neutralize flying weaknesses to 1.0, keep flying resistances/immunities
            fly_only = get_type_effectiveness(move_type, ["flying"], type_matrix)
            # Replace flying-only contribution: if weakness (>1), treat as 1.0; if resistance (<1) or immunity (0), keep it
            if fly_only > 1.0:
                fly_contrib = 1.0
            else:
                fly_contrib = fly_only
            other_types = [t for t in boss_types if t != "flying"]
            other_contrib = get_type_effectiveness(move_type, other_types, type_matrix) if other_types else 1.0
            effectiveness = float(fly_contrib) * float(other_contrib)
        # For Mega Rayquaza, do not additionally clamp by generic resist/weak lists; delta stream already adjusted
        return float(effectiveness)

    # Apply explicit resist/weak lists as caps/floors (for non-Delta Stream cases)
    boss_resistances = boss_data.get("resistances", [])
    boss_weaknesses = boss_data.get("weaknesses", [])
    if move_type in boss_resistances:
        effectiveness = min(effectiveness, 0.5)
    if move_type in boss_weaknesses:
        effectiveness = max(effectiveness, 2.0)

    return float(effectiveness)


def calculate_team_coverage(team_coverages: List[Dict], type_matrix: Dict) -> Dict:
    """
    Calculate team-wide offensive matchups.

    Args:
        team_coverages: List of individual Pokemon coverage analyses
        type_matrix: Type effectiveness matrix

    Returns:
        Team coverage analysis
    """
    if not team_coverages:
        return {"total_coverage": {}, "coverage_gaps": [], "team_boss_analysis": {}}

    all_types = ["normal", "fighting", "flying", "poison", "ground", "rock", "bug",
                 "ghost", "steel", "fire", "water", "grass", "electric", "psychic",
                 "ice", "dragon", "dark", "fairy"]

    # Aggregate coverage from all team members
    team_type_coverage = {}
    all_move_types = set()

    for defending_type in all_types:
        best_effectiveness = 0.0
        best_pokemon_idx = -1
        best_move_type = None

        for i, pokemon_coverage in enumerate(team_coverages):
            type_coverage = pokemon_coverage.get("type_coverage", {})
            if defending_type in type_coverage:
                effectiveness = type_coverage[defending_type]["effectiveness"]
                if effectiveness > best_effectiveness:
                    best_effectiveness = effectiveness
                    best_pokemon_idx = i
                    best_move_type = type_coverage[defending_type]["best_move_type"]

        team_type_coverage[defending_type] = {
            "effectiveness": best_effectiveness,
            "best_pokemon": best_pokemon_idx,
            "best_move_type": best_move_type
        }

    # Collect all move types in the team
    for pokemon_coverage in team_coverages:
        move_types = pokemon_coverage.get("coverage_summary", {}).get("move_types", [])
        all_move_types.update(move_types)

    # Identify coverage bins by best effectiveness per defender across team move types
    excellent_coverage = []  # >2
    good_coverage = []       # (1,2]
    neutral_coverage = []    # ==1
    poor_coverage = []       # (0,1)
    no_coverage = []         # ==0

    for defending_type, coverage in team_type_coverage.items():
        effectiveness = coverage["effectiveness"]
        if effectiveness == 0.0:
            no_coverage.append(defending_type)
        elif 0.0 < effectiveness < 1.0:
            poor_coverage.append(defending_type)
        elif effectiveness == 1.0:
            neutral_coverage.append(defending_type)
        elif 1.0 < effectiveness <= 2.0:
            good_coverage.append(defending_type)
        elif effectiveness > 2.0:
            excellent_coverage.append(defending_type)

    # Team boss analysis
    team_boss_analysis = {}
    for boss_name, boss_data in BOSS_POKEMON.items():
        boss_types = boss_data["types"]

        best_effectiveness = 0.0
        best_pokemon_idx = -1
        best_move_type = None
        pokemon_coverages = []

        for i, pokemon_coverage in enumerate(team_coverages):
            move_types = pokemon_coverage.get("coverage_summary", {}).get("move_types", [])
            pokemon_best = 0.0
            pokemon_best_type = None

            for move_type in move_types:
                effectiveness = _effectiveness_vs_boss(move_type, boss_name, boss_types, boss_data, type_matrix)
                if effectiveness > pokemon_best:
                    pokemon_best = effectiveness
                    pokemon_best_type = move_type

            pokemon_coverages.append({
                "pokemon_index": i,
                "best_effectiveness": pokemon_best,
                "best_move_type": pokemon_best_type
            })

            if pokemon_best > best_effectiveness:
                best_effectiveness = pokemon_best
                best_pokemon_idx = i
                best_move_type = pokemon_best_type

        # Determine team status against this boss (custom thresholds)
        if best_effectiveness > 2.0:
            status = "excellent"
        elif 1.0 < best_effectiveness <= 2.0:
            status = "good"
        elif best_effectiveness == 1.0:
            status = "ok"
        elif 0.0 < best_effectiveness < 1.0:
            status = "poor"
        else:
            status = "none"

        team_boss_analysis[boss_name] = {
            "name": boss_data["name"],
            "types": boss_types,
            "best_effectiveness": best_effectiveness,
            "best_pokemon": best_pokemon_idx,
            "best_move_type": best_move_type,
            "status": status,
            "pokemon_coverages": pokemon_coverages,
            "special_notes": boss_data.get("special_notes", "")
        }

    return {
        "total_coverage": team_type_coverage,
        "coverage_summary": {
            "excellent": excellent_coverage,
            "good": good_coverage,
            "neutral": neutral_coverage,
            "poor": poor_coverage,
            "none": no_coverage,
            "all_move_types": list(all_move_types)
        },
        "team_boss_analysis": team_boss_analysis
    }


class OffensiveCoverageCalculator:
    """Main class for calculating offensive matchups analysis."""

    def __init__(self):
        from .catalog import load_type_matrix_v2
        self.type_matrix = load_type_matrix_v2()
        self.enhanced_moves = load_moves_enhanced()
        self.basic_moves = load_moves_basic()
        self._cache = {}

    def clear_cache(self):
        """Clear the coverage cache."""
        self._cache.clear()

    def get_pokemon_coverage(self, pokemon_moves: List[int], pokemon_id: Optional[str] = None) -> Dict:
        """
        Get offensive matchups for a single Pokemon.

        Args:
            pokemon_moves: List of move IDs
            pokemon_id: Optional Pokemon ID for caching

        Returns:
            Coverage analysis dictionary
        """
        # Create cache key
        cache_key = f"pokemon_{pokemon_id}_{hash(tuple(sorted(pokemon_moves)))}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        coverage = calculate_pokemon_coverage(
            pokemon_moves, self.type_matrix, self.enhanced_moves, self.basic_moves
        )

        # Add boss analysis
        coverage["boss_analysis"] = analyze_boss_coverage(coverage, self.type_matrix)

        # Cache the result
        self._cache[cache_key] = coverage
        return coverage

    def get_team_coverage(self, team_pokemon: List[Dict]) -> Dict:
        """
        Get offensive matchups for an entire team.

        Args:
            team_pokemon: List of Pokemon dictionaries with 'moves' key

        Returns:
            Team coverage analysis dictionary
        """
        team_coverages = []

        for i, pokemon in enumerate(team_pokemon):
            # Try both 'moveset' (actual save format) and 'moves' (team editor format)
            moves = pokemon.get("moveset", []) or pokemon.get("moves", [])
            if isinstance(moves, list) and moves:
                # Extract move IDs from move data
                move_ids = []
                for move in moves:
                    if isinstance(move, dict):
                        move_id = move.get("moveId")
                        if move_id is not None:
                            move_ids.append(move_id)
                    elif isinstance(move, int):
                        move_ids.append(move)

                pokemon_coverage = self.get_pokemon_coverage(
                    move_ids,
                    pokemon_id=f"team_pokemon_{i}"
                )
                team_coverages.append(pokemon_coverage)

        return calculate_team_coverage(team_coverages, self.type_matrix)

    def invalidate_pokemon_cache(self, pokemon_id: Optional[str] = None):
        """Invalidate cache for specific Pokemon or all if pokemon_id is None."""
        if pokemon_id is None:
            self.clear_cache()
        else:
            # Remove all cache entries for this Pokemon
            keys_to_remove = [key for key in self._cache.keys() if key.startswith(f"pokemon_{pokemon_id}_")]
            for key in keys_to_remove:
                del self._cache[key]


# Global instance for easy access
coverage_calculator = OffensiveCoverageCalculator()


def get_coverage_for_pokemon(pokemon_moves: List[int], pokemon_id: Optional[str] = None) -> Dict:
    """Convenience function to get Pokemon coverage."""
    return coverage_calculator.get_pokemon_coverage(pokemon_moves, pokemon_id)


def get_coverage_for_team(team_pokemon: List[Dict]) -> Dict:
    """Convenience function to get team coverage."""
    return coverage_calculator.get_team_coverage(team_pokemon)


def invalidate_coverage_cache(pokemon_id: Optional[str] = None):
    """Convenience function to invalidate coverage cache."""
    coverage_calculator.invalidate_pokemon_cache(pokemon_id)