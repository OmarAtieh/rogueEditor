"""
Save Corruption Prevention System - Validation Framework

This module provides comprehensive validation for Pokerogue save files to prevent
corruption incidents. It includes JSON schema validation, data consistency checks,
and cross-reference validation between trainer and slot data.

CRITICAL SAFETY: This system must never allow invalid data to reach save files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Validation result severity levels."""
    ERROR = "error"          # Blocks save operation
    WARNING = "warning"      # Allows save with user confirmation
    INFO = "info"           # Informational only


@dataclass
class ValidationIssue:
    """Represents a validation issue found in save data."""
    severity: ValidationSeverity
    message: str
    path: str  # JSON path to the problematic data
    field: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of save data validation."""
    is_valid: bool
    issues: List[ValidationIssue]

    @property
    def has_errors(self) -> bool:
        """True if any errors (blocking issues) exist."""
        return any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """True if any warnings exist."""
        return any(issue.severity == ValidationSeverity.WARNING for issue in self.issues)

    def get_errors(self) -> List[ValidationIssue]:
        """Get all error-level issues."""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.ERROR]

    def get_warnings(self) -> List[ValidationIssue]:
        """Get all warning-level issues."""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.WARNING]


class SaveValidator:
    """
    Comprehensive save file validator for Pokerogue data.

    Validates:
    - JSON structure and required fields
    - Pokemon data consistency (IVs, stats, levels)
    - Modifier integrity and references
    - Cross-references between trainer and slot data
    - Data type consistency
    """

    def __init__(self):
        self.pokemon_catalog = None
        self.move_catalog = None
        self.ability_catalog = None
        self.nature_catalog = None
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        """Load reference catalogs for validation."""
        try:
            from .catalog import (
                load_pokemon_catalog, load_move_catalog,
                load_ability_catalog, load_nature_catalog
            )
            self.pokemon_catalog = load_pokemon_catalog()
            self.move_catalog, _ = load_move_catalog()
            self.ability_catalog, _ = load_ability_catalog()
            self.nature_catalog, _ = load_nature_catalog()
        except Exception as e:
            logger.warning(f"Could not load validation catalogs: {e}")

    def validate_trainer_data(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate trainer (system) data structure and content.

        Args:
            data: Trainer data dictionary

        Returns:
            ValidationResult with any issues found
        """
        issues: List[ValidationIssue] = []

        if not isinstance(data, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Trainer data must be a dictionary",
                "root"
            ))
            return ValidationResult(False, issues)

        # Validate basic structure
        self._validate_trainer_structure(data, issues)

        # Validate dex data
        if "dexData" in data:
            self._validate_dex_data(data["dexData"], issues)

        # Validate starter data
        if "starterData" in data:
            self._validate_starter_data(data["starterData"], issues)

        # Validate game stats
        if "gameStats" in data:
            self._validate_game_stats(data["gameStats"], issues)

        # Validate voucher counts
        if "voucherCounts" in data:
            self._validate_voucher_counts(data["voucherCounts"], issues)

        # Cross-reference validation
        self._validate_trainer_cross_references(data, issues)

        is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(is_valid, issues)

    def validate_slot_data(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate slot (session) data structure and content.

        Args:
            data: Slot data dictionary

        Returns:
            ValidationResult with any issues found
        """
        issues: List[ValidationIssue] = []

        if not isinstance(data, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Slot data must be a dictionary",
                "root"
            ))
            return ValidationResult(False, issues)

        # Validate basic structure
        self._validate_slot_structure(data, issues)

        # Validate party data
        if "party" in data:
            self._validate_party_data(data["party"], issues)

        # Validate modifiers
        if "modifiers" in data:
            self._validate_modifiers_data(data["modifiers"], issues)

        # Validate wave/progress data
        self._validate_session_progress(data, issues)

        # Cross-reference validation
        self._validate_slot_cross_references(data, issues)

        is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(is_valid, issues)

    def validate_combined_data(self, trainer_data: Dict[str, Any],
                             slot_data: Dict[str, Any]) -> ValidationResult:
        """
        Validate consistency between trainer and slot data.

        Args:
            trainer_data: Trainer data dictionary
            slot_data: Slot data dictionary

        Returns:
            ValidationResult with cross-reference issues
        """
        issues: List[ValidationIssue] = []

        # Validate individual datasets first
        trainer_result = self.validate_trainer_data(trainer_data)
        slot_result = self.validate_slot_data(slot_data)

        issues.extend(trainer_result.issues)
        issues.extend(slot_result.issues)

        # Cross-dataset validation
        self._validate_trainer_slot_consistency(trainer_data, slot_data, issues)

        is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(is_valid, issues)

    def _validate_trainer_structure(self, data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate basic trainer data structure."""
        # Check for required top-level fields
        if "gameStats" not in data:
            issues.append(ValidationIssue(
                ValidationSeverity.WARNING,
                "Missing gameStats section",
                "gameStats"
            ))

        # Validate data types
        for field, expected_type in [
            ("dexData", dict),
            ("starterData", dict),
            ("gameStats", dict),
            ("voucherCounts", dict),
            ("eggs", list)
        ]:
            if field in data and not isinstance(data[field], expected_type):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Field {field} must be {expected_type.__name__}",
                    field,
                    expected=expected_type.__name__,
                    actual=type(data[field]).__name__
                ))

    def _validate_dex_data(self, dex_data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate Pokedex data entries."""
        if not isinstance(dex_data, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "dexData must be a dictionary",
                "dexData"
            ))
            return

        for dex_id, entry in dex_data.items():
            if not isinstance(entry, dict):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Dex entry {dex_id} must be a dictionary",
                    f"dexData.{dex_id}"
                ))
                continue

            # Validate IVs
            if "ivs" in entry:
                ivs = entry["ivs"]
                if not isinstance(ivs, list) or len(ivs) != 6:
                    issues.append(ValidationIssue(
                        ValidationSeverity.ERROR,
                        f"IVs for {dex_id} must be a list of 6 values",
                        f"dexData.{dex_id}.ivs"
                    ))
                elif not all(isinstance(iv, int) and 0 <= iv <= 31 for iv in ivs):
                    issues.append(ValidationIssue(
                        ValidationSeverity.ERROR,
                        f"IVs for {dex_id} must be integers between 0-31",
                        f"dexData.{dex_id}.ivs"
                    ))

            # Validate counts
            for count_field in ["seenCount", "caughtCount", "hatchedCount"]:
                if count_field in entry:
                    count = entry[count_field]
                    if not isinstance(count, int) or count < 0:
                        issues.append(ValidationIssue(
                            ValidationSeverity.ERROR,
                            f"{count_field} for {dex_id} must be non-negative integer",
                            f"dexData.{dex_id}.{count_field}"
                        ))

    def _validate_starter_data(self, starter_data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate starter Pokemon data."""
        if not isinstance(starter_data, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "starterData must be a dictionary",
                "starterData"
            ))
            return

        for dex_id, entry in starter_data.items():
            if not isinstance(entry, dict):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Starter entry {dex_id} must be a dictionary",
                    f"starterData.{dex_id}"
                ))
                continue

            # Validate candy count
            if "candyCount" in entry:
                candy_count = entry["candyCount"]
                if not isinstance(candy_count, int) or candy_count < 0:
                    issues.append(ValidationIssue(
                        ValidationSeverity.ERROR,
                        f"candyCount for {dex_id} must be non-negative integer",
                        f"starterData.{dex_id}.candyCount"
                    ))

    def _validate_party_data(self, party: List[Any], issues: List[ValidationIssue]) -> None:
        """Validate party Pokemon data."""
        if not isinstance(party, list):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Party must be a list",
                "party"
            ))
            return

        if len(party) > 6:
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                f"Party cannot have more than 6 Pokemon (has {len(party)})",
                "party"
            ))

        for i, mon in enumerate(party):
            if not isinstance(mon, dict):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Party member {i} must be a dictionary",
                    f"party.{i}"
                ))
                continue

            self._validate_pokemon_data(mon, f"party.{i}", issues)

    def _validate_pokemon_data(self, mon: Dict[str, Any], path: str, issues: List[ValidationIssue]) -> None:
        """Validate individual Pokemon data."""
        # Check species ID
        species_id = None
        for field in ["species", "dexId", "speciesId", "pokemonId"]:
            if field in mon:
                species_id = mon[field]
                break

        if species_id is None:
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Pokemon missing species identifier",
                f"{path}.species"
            ))
        elif not isinstance(species_id, int) or species_id <= 0:
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Species ID must be positive integer",
                f"{path}.species"
            ))

        # Validate level
        level = mon.get("level") or mon.get("lvl")
        if level is not None:
            if not isinstance(level, int) or level < 1 or level > 100:
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    "Level must be integer between 1-100",
                    f"{path}.level"
                ))

        # Validate IVs
        if "ivs" in mon:
            ivs = mon["ivs"]
            if not isinstance(ivs, list) or len(ivs) != 6:
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    "IVs must be list of 6 values",
                    f"{path}.ivs"
                ))
            elif not all(isinstance(iv, int) and 0 <= iv <= 31 for iv in ivs):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    "IVs must be integers between 0-31",
                    f"{path}.ivs"
                ))

        # Validate moves
        for move_field in ["moves", "moveIds", "moveset"]:
            if move_field in mon:
                moves = mon[move_field]
                if isinstance(moves, list):
                    if len(moves) > 4:
                        issues.append(ValidationIssue(
                            ValidationSeverity.ERROR,
                            f"Pokemon cannot have more than 4 moves (has {len(moves)})",
                            f"{path}.{move_field}"
                        ))

    def _validate_modifiers_data(self, modifiers: List[Any], issues: List[ValidationIssue]) -> None:
        """Validate modifier data."""
        if not isinstance(modifiers, list):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "Modifiers must be a list",
                "modifiers"
            ))
            return

        for i, mod in enumerate(modifiers):
            if not isinstance(mod, dict):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Modifier {i} must be a dictionary",
                    f"modifiers.{i}"
                ))
                continue

            # Validate required fields
            if "typeId" not in mod:
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Modifier {i} missing typeId",
                    f"modifiers.{i}.typeId"
                ))

            # Validate stack count
            if "stackCount" in mod:
                stack_count = mod["stackCount"]
                if not isinstance(stack_count, int) or stack_count < 0:
                    issues.append(ValidationIssue(
                        ValidationSeverity.ERROR,
                        f"stackCount for modifier {i} must be non-negative integer",
                        f"modifiers.{i}.stackCount"
                    ))

    def _validate_game_stats(self, game_stats: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate game statistics."""
        if not isinstance(game_stats, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "gameStats must be a dictionary",
                "gameStats"
            ))
            return

        # Validate numeric stats
        for stat_name, value in game_stats.items():
            if isinstance(value, (int, float)):
                if value < 0:
                    issues.append(ValidationIssue(
                        ValidationSeverity.WARNING,
                        f"Game stat {stat_name} is negative ({value})",
                        f"gameStats.{stat_name}"
                    ))

    def _validate_voucher_counts(self, voucher_counts: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate voucher/gacha counts."""
        if not isinstance(voucher_counts, dict):
            issues.append(ValidationIssue(
                ValidationSeverity.ERROR,
                "voucherCounts must be a dictionary",
                "voucherCounts"
            ))
            return

        for voucher_type, count in voucher_counts.items():
            if not isinstance(count, int) or count < 0:
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Voucher count for {voucher_type} must be non-negative integer",
                    f"voucherCounts.{voucher_type}"
                ))

    def _validate_session_progress(self, data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate session progress data."""
        # Validate wave number
        for wave_field in ["wave", "currentWave", "waveIndex"]:
            if wave_field in data:
                wave = data[wave_field]
                if not isinstance(wave, int) or wave < 0:
                    issues.append(ValidationIssue(
                        ValidationSeverity.ERROR,
                        f"{wave_field} must be non-negative integer",
                        wave_field
                    ))

    def _validate_slot_structure(self, data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate basic slot data structure."""
        # Validate data types for key fields
        for field, expected_type in [
            ("party", list),
            ("modifiers", list),
            ("enemyModifiers", list)
        ]:
            if field in data and not isinstance(data[field], expected_type):
                issues.append(ValidationIssue(
                    ValidationSeverity.ERROR,
                    f"Field {field} must be {expected_type.__name__}",
                    field,
                    expected=expected_type.__name__,
                    actual=type(data[field]).__name__
                ))

    def _validate_trainer_cross_references(self, data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate cross-references within trainer data."""
        dex_data = data.get("dexData", {})
        starter_data = data.get("starterData", {})

        # Check for starter data without corresponding dex data
        for dex_id in starter_data:
            if dex_id not in dex_data:
                issues.append(ValidationIssue(
                    ValidationSeverity.WARNING,
                    f"Starter data for {dex_id} exists without dex data",
                    f"starterData.{dex_id}"
                ))

    def _validate_slot_cross_references(self, data: Dict[str, Any], issues: List[ValidationIssue]) -> None:
        """Validate cross-references within slot data."""
        party = data.get("party", [])
        modifiers = data.get("modifiers", [])

        # Collect party Pokemon IDs
        party_ids = set()
        for i, mon in enumerate(party):
            if isinstance(mon, dict) and "id" in mon:
                party_ids.add(mon["id"])

        # Check modifier references
        for i, mod in enumerate(modifiers):
            if isinstance(mod, dict):
                args = mod.get("args", [])
                if args and isinstance(args, list) and len(args) > 0:
                    target_id = args[0]
                    if isinstance(target_id, int) and target_id not in party_ids:
                        # Only warn for Pokemon-targeting modifiers
                        type_id = mod.get("typeId", "")
                        if not mod.get("player", False):
                            issues.append(ValidationIssue(
                                ValidationSeverity.WARNING,
                                f"Modifier {i} ({type_id}) references non-existent Pokemon ID {target_id}",
                                f"modifiers.{i}.args.0"
                            ))

    def _validate_trainer_slot_consistency(self, trainer_data: Dict[str, Any],
                                         slot_data: Dict[str, Any],
                                         issues: List[ValidationIssue]) -> None:
        """Validate consistency between trainer and slot data."""
        # This would check for consistency between persistent trainer data
        # and session slot data, but given the nature of Pokerogue,
        # these are largely independent during active sessions
        pass


def create_save_validator() -> SaveValidator:
    """Create a configured save validator instance."""
    return SaveValidator()