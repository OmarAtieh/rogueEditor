"""Data validation system for team editor.

This module provides post-change validation that allows free editing but validates
before save operations. It clamps numeric values to logical ranges and reverts
invalid data types to original values from the file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

import logging


class ValidationResult(Enum):
    """Validation result types."""
    VALID = "valid"
    CLAMPED = "clamped"
    REVERTED = "reverted"
    ERROR = "error"


@dataclass
class ValidationIssue:
    """Represents a validation issue."""
    field_path: str
    original_value: Any
    corrected_value: Any
    issue_type: str
    message: str
    result: ValidationResult


class DataValidator:
    """Validates and corrects data before save operations."""
    
    def __init__(self):
        # Field validation rules
        self._field_rules = {
            # Numeric fields with ranges
            'level': {'type': int, 'min': 1, 'max': 100, 'default': 1},
            'friendship': {'type': int, 'min': 0, 'max': 255, 'default': 0},
            'hp': {'type': int, 'min': 1, 'max': 999, 'default': 1},
            'exp': {'type': int, 'min': 0, 'max': 999999, 'default': 0},
            'money': {'type': int, 'min': 0, 'max': 999999999, 'default': 0},
            'luck': {'type': int, 'min': 0, 'max': 3, 'default': 0},
            'sleepTurns': {'type': int, 'min': 0, 'max': 7, 'default': 0},
            'freezeTurns': {'type': int, 'min': 0, 'max': 7, 'default': 0},
            'poisonTurns': {'type': int, 'min': 0, 'max': 7, 'default': 0},
            'poisonDamage': {'type': int, 'min': 0, 'max': 999, 'default': 0},
            'ppUsed': {'type': int, 'min': 0, 'max': 999, 'default': 0},
            
            # IV fields (0-31)
            'ivs': {'type': list, 'item_type': int, 'item_min': 0, 'item_max': 31, 'length': 6, 'default': [0, 0, 0, 0, 0, 0]},
            
            # Boolean fields
            'shiny': {'type': bool, 'default': False},
            'passive': {'type': bool, 'default': False},
            'pokerus': {'type': bool, 'default': False},
            'pauseEvolutions': {'type': bool, 'default': False},
            
            # ID fields (must be valid IDs from catalogs)
            'species': {'type': int, 'min': 1, 'max': 1010, 'default': 1},
            'abilityId': {'type': int, 'min': 0, 'max': 999, 'default': 0},
            'nature': {'type': int, 'min': 0, 'max': 24, 'default': 0},
            'teraType': {'type': int, 'min': 0, 'max': 18, 'default': 0},
            'gender': {'type': int, 'min': -1, 'max': 1, 'default': -1},
            'pokeball': {'type': int, 'min': 0, 'max': 99, 'default': 0},
            'weather': {'type': int, 'min': 0, 'max': 9, 'default': 0},
            
            # String fields with validation
            'nickname': {'type': str, 'max_length': 20, 'default': ''},
            'status': {'type': str, 'allowed_values': ['none', 'burn', 'freeze', 'paralysis', 'poison', 'sleep', 'confusion'], 'default': 'none'},
            
            # Move fields (must be valid move IDs)
            'moves': {'type': list, 'item_type': int, 'item_min': 1, 'item_max': 999, 'length': 4, 'default': [0, 0, 0, 0]},
            'ppUps': {'type': list, 'item_type': int, 'item_min': 0, 'item_max': 3, 'length': 4, 'default': [0, 0, 0, 0]},
        }
        
        # Store original data for reversion
        self._original_data: Optional[Dict] = None
        self._original_file_path: Optional[str] = None
    
    def set_original_data(self, data: Dict, file_path: str):
        """Set the original data from file for reversion purposes."""
        self._original_data = data.copy()
        self._original_file_path = file_path
        logging.getLogger(__name__).debug(f"DataValidator: Set original data from {file_path}")
    
    def validate_pokemon_data(self, mon: Dict, mon_index: int) -> List[ValidationIssue]:
        """Validate and correct a single Pokemon's data."""
        issues = []
        
        try:
            # Validate each field
            for field_name, rules in self._field_rules.items():
                if field_name in mon:
                    issue = self._validate_field(mon, field_name, rules, f"party[{mon_index}]")
                    if issue:
                        issues.append(issue)
            
            # Special validation for Pokemon-specific fields
            self._validate_pokemon_specific_fields(mon, mon_index, issues)
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Error validating Pokemon {mon_index}: {e}")
            issues.append(ValidationIssue(
                field_path=f"party[{mon_index}]",
                original_value=mon,
                corrected_value=mon,
                issue_type="validation_error",
                message=f"Validation failed: {e}",
                result=ValidationResult.ERROR
            ))
        
        return issues
    
    def validate_trainer_data(self, data: Dict) -> List[ValidationIssue]:
        """Validate trainer-level data."""
        issues = []
        
        try:
            # Validate trainer fields
            trainer_fields = ['money', 'weather']
            for field_name in trainer_fields:
                if field_name in data and field_name in self._field_rules:
                    issue = self._validate_field(data, field_name, self._field_rules[field_name], "trainer")
                    if issue:
                        issues.append(issue)
            
            # Validate party structure
            if 'party' in data:
                party = data['party']
                if not isinstance(party, list):
                    issues.append(ValidationIssue(
                        field_path="party",
                        original_value=party,
                        corrected_value=[],
                        issue_type="type_error",
                        message="Party must be a list",
                        result=ValidationResult.REVERTED
                    ))
                    data['party'] = []
                else:
                    # Ensure party has exactly 6 slots
                    while len(party) < 6:
                        party.append(None)
                    if len(party) > 6:
                        party[:] = party[:6]
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Error validating trainer data: {e}")
            issues.append(ValidationIssue(
                field_path="trainer",
                original_value=data,
                corrected_value=data,
                issue_type="validation_error",
                message=f"Trainer validation failed: {e}",
                result=ValidationResult.ERROR
            ))
        
        return issues
    
    def _validate_field(self, data: Dict, field_name: str, rules: Dict, context: str) -> Optional[ValidationIssue]:
        """Validate a single field and correct if necessary."""
        try:
            original_value = data[field_name]
            corrected_value = original_value
            
            # Type validation and conversion
            if 'type' in rules:
                expected_type = rules['type']
                
                if expected_type == int:
                    corrected_value = self._validate_int_field(original_value, rules, context, field_name)
                elif expected_type == bool:
                    corrected_value = self._validate_bool_field(original_value, rules, context, field_name)
                elif expected_type == str:
                    corrected_value = self._validate_str_field(original_value, rules, context, field_name)
                elif expected_type == list:
                    corrected_value = self._validate_list_field(original_value, rules, context, field_name)
            
            # Apply the correction if needed
            if corrected_value != original_value:
                data[field_name] = corrected_value
                return ValidationIssue(
                    field_path=f"{context}.{field_name}",
                    original_value=original_value,
                    corrected_value=corrected_value,
                    issue_type="validation_correction",
                    message=f"Corrected {field_name} from {original_value} to {corrected_value}",
                    result=ValidationResult.CLAMPED if isinstance(corrected_value, (int, float)) else ValidationResult.REVERTED
                )
            
            return None
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Error validating field {field_name}: {e}")
            return ValidationIssue(
                field_path=f"{context}.{field_name}",
                original_value=data.get(field_name),
                corrected_value=data.get(field_name),
                issue_type="validation_error",
                message=f"Field validation failed: {e}",
                result=ValidationResult.ERROR
            )
    
    def _validate_int_field(self, value: Any, rules: Dict, context: str, field_name: str) -> int:
        """Validate and correct an integer field."""
        try:
            # Try to convert to int
            if isinstance(value, str):
                # Handle empty string
                if not value.strip():
                    return rules.get('default', 0)
                # Try to parse
                int_value = int(value.strip())
            elif isinstance(value, (int, float)):
                int_value = int(value)
            else:
                # Invalid type - revert to original or default
                return self._revert_to_original_or_default(field_name, rules.get('default', 0))
            
            # Apply min/max clamping
            if 'min' in rules and int_value < rules['min']:
                int_value = rules['min']
            if 'max' in rules and int_value > rules['max']:
                int_value = rules['max']
            
            return int_value
            
        except (ValueError, TypeError):
            # Conversion failed - revert to original or default
            return self._revert_to_original_or_default(field_name, rules.get('default', 0))
    
    def _validate_bool_field(self, value: Any, rules: Dict, context: str, field_name: str) -> bool:
        """Validate and correct a boolean field."""
        try:
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                # Handle string representations
                lower_val = value.lower().strip()
                if lower_val in ('true', '1', 'yes', 'on'):
                    return True
                elif lower_val in ('false', '0', 'no', 'off', ''):
                    return False
                else:
                    # Invalid string - revert to original or default
                    return self._revert_to_original_or_default(field_name, rules.get('default', False))
            elif isinstance(value, (int, float)):
                return bool(value)
            else:
                # Invalid type - revert to original or default
                return self._revert_to_original_or_default(field_name, rules.get('default', False))
                
        except Exception:
            return self._revert_to_original_or_default(field_name, rules.get('default', False))
    
    def _validate_str_field(self, value: Any, rules: Dict, context: str, field_name: str) -> str:
        """Validate and correct a string field."""
        try:
            if isinstance(value, str):
                str_value = value
            else:
                # Convert to string
                str_value = str(value)
            
            # Apply length limits
            if 'max_length' in rules and len(str_value) > rules['max_length']:
                str_value = str_value[:rules['max_length']]
            
            # Check allowed values
            if 'allowed_values' in rules and str_value not in rules['allowed_values']:
                # Invalid value - revert to original or default
                return self._revert_to_original_or_default(field_name, rules.get('default', ''))
            
            return str_value
            
        except Exception:
            return self._revert_to_original_or_default(field_name, rules.get('default', ''))
    
    def _validate_list_field(self, value: Any, rules: Dict, context: str, field_name: str) -> List:
        """Validate and correct a list field."""
        try:
            if not isinstance(value, list):
                # Try to convert to list
                if isinstance(value, (str, int, float)):
                    # Single value - create list
                    value = [value]
                else:
                    # Invalid type - revert to original or default
                    return self._revert_to_original_or_default(field_name, rules.get('default', []))
            
            # Validate list length
            if 'length' in rules:
                expected_length = rules['length']
                if len(value) != expected_length:
                    # Adjust length
                    if len(value) < expected_length:
                        # Pad with default values
                        default_item = rules.get('default_item', 0)
                        value.extend([default_item] * (expected_length - len(value)))
                    else:
                        # Truncate
                        value = value[:expected_length]
            
            # Validate list items
            if 'item_type' in rules:
                item_type = rules['item_type']
                for i, item in enumerate(value):
                    if item_type == int:
                        try:
                            if isinstance(item, str):
                                item_val = int(item.strip()) if item.strip() else 0
                            else:
                                item_val = int(item)
                            
                            # Apply item min/max
                            if 'item_min' in rules and item_val < rules['item_min']:
                                item_val = rules['item_min']
                            if 'item_max' in rules and item_val > rules['item_max']:
                                item_val = rules['item_max']
                            
                            value[i] = item_val
                        except (ValueError, TypeError):
                            # Invalid item - use default
                            value[i] = rules.get('default_item', 0)
            
            return value
            
        except Exception:
            return self._revert_to_original_or_default(field_name, rules.get('default', []))
    
    def _validate_pokemon_specific_fields(self, mon: Dict, mon_index: int, issues: List[ValidationIssue]):
        """Validate Pokemon-specific business logic."""
        try:
            # Luck validation: if not shiny, luck must be 0
            if mon.get('shiny', False) is False and mon.get('luck', 0) > 0:
                mon['luck'] = 0
                issues.append(ValidationIssue(
                    field_path=f"party[{mon_index}].luck",
                    original_value=mon.get('luck', 0),
                    corrected_value=0,
                    issue_type="business_logic",
                    message="Luck reset to 0 because Pokemon is not shiny",
                    result=ValidationResult.CLAMPED
                ))
            
            # Status validation: if status is 'none', remove status field
            if mon.get('status') == 'none':
                mon.pop('status', None)
            
            # Move validation: ensure moves are valid IDs
            if 'moves' in mon and isinstance(mon['moves'], list):
                for i, move_id in enumerate(mon['moves']):
                    if not isinstance(move_id, int) or move_id < 0 or move_id > 999:
                        mon['moves'][i] = 0
                        issues.append(ValidationIssue(
                            field_path=f"party[{mon_index}].moves[{i}]",
                            original_value=move_id,
                            corrected_value=0,
                            issue_type="invalid_move_id",
                            message=f"Invalid move ID {move_id}, reset to 0",
                            result=ValidationResult.REVERTED
                        ))
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Error in Pokemon-specific validation: {e}")
    
    def _revert_to_original_or_default(self, field_name: str, default_value: Any) -> Any:
        """Revert to original value from file or use default."""
        try:
            # Try to get original value from file
            if self._original_data and field_name in self._original_data:
                original_value = self._original_data[field_name]
                logging.getLogger(__name__).debug(f"Reverted {field_name} to original value: {original_value}")
                return original_value
            else:
                # Use default value
                logging.getLogger(__name__).debug(f"Using default value for {field_name}: {default_value}")
                return default_value
        except Exception as e:
            logging.getLogger(__name__).error(f"Error reverting {field_name}: {e}")
            return default_value
    
    def validate_complete_data(self, data: Dict) -> Tuple[bool, List[ValidationIssue]]:
        """Validate complete data structure and return validation results."""
        all_issues = []
        
        try:
            # Create a deep copy of the data to avoid modifying the original
            import copy
            data_copy = copy.deepcopy(data)
            
            # Validate trainer data
            trainer_issues = self.validate_trainer_data(data_copy)
            all_issues.extend(trainer_issues)
            
            # Validate each Pokemon
            if 'party' in data_copy and isinstance(data_copy['party'], list):
                for i, mon in enumerate(data_copy['party']):
                    if mon is not None:
                        pokemon_issues = self.validate_pokemon_data(mon, i)
                        all_issues.extend(pokemon_issues)
            
            # Check if validation was successful
            has_errors = any(issue.result == ValidationResult.ERROR for issue in all_issues)
            is_valid = not has_errors
            
            logging.getLogger(__name__).info(f"Data validation completed: {len(all_issues)} issues found, valid={is_valid}")
            
            return is_valid, all_issues
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Critical error in data validation: {e}")
            return False, [ValidationIssue(
                field_path="data",
                original_value=data,
                corrected_value=data,
                issue_type="critical_error",
                message=f"Critical validation error: {e}",
                result=ValidationResult.ERROR
            )]


    def apply_validation_corrections(self, data: Dict, issues: List[ValidationIssue]) -> Dict:
        """Apply validation corrections to data and return the corrected version."""
        try:
            # Create a deep copy of the data
            import copy
            corrected_data = copy.deepcopy(data)
            
            # Apply corrections based on validation issues
            for issue in issues:
                if issue.result in [ValidationResult.CLAMPED, ValidationResult.REVERTED]:
                    # Parse the field path to apply the correction
                    field_path = issue.field_path
                    if field_path.startswith("party["):
                        # Extract party index and field name
                        try:
                            # Parse "party[0].field_name" format
                            import re
                            match = re.match(r"party\[(\d+)\]\.(.+)", field_path)
                            if match:
                                party_idx = int(match.group(1))
                                field_name = match.group(2)
                                
                                if 'party' in corrected_data and isinstance(corrected_data['party'], list):
                                    if 0 <= party_idx < len(corrected_data['party']):
                                        if corrected_data['party'][party_idx] is not None:
                                            corrected_data['party'][party_idx][field_name] = issue.corrected_value
                        except Exception:
                            pass
                    elif field_path.startswith("trainer."):
                        # Extract trainer field name
                        field_name = field_path.split(".", 1)[1]
                        corrected_data[field_name] = issue.corrected_value
            
            return corrected_data
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Error applying validation corrections: {e}")
            return data


def create_data_validator() -> DataValidator:
    """Create a new data validator instance."""
    return DataValidator()
