"""Per-slot form persistence system for managing user-specified alternative forms."""

import json
import os
from typing import Dict, Optional, Any
from .utils import repo_path

class SlotFormPersistence:
    """Manages per-slot form preferences that persist locally."""

    def __init__(self, username: str, slot: int):
        self.username = username
        self.slot = slot
        self.forms_dir = repo_path("saves", username, "forms")
        self.forms_file = os.path.join(self.forms_dir, f"slot_{slot}_forms.json")
        self._forms_data: Optional[Dict] = None

    def _ensure_forms_dir(self):
        """Ensure the forms directory exists."""
        os.makedirs(self.forms_dir, exist_ok=True)

    def _load_forms_data(self) -> Dict:
        """Load forms data from file."""
        if self._forms_data is not None:
            return self._forms_data

        if not os.path.exists(self.forms_file):
            self._forms_data = {"pokemon_forms": {}, "auto_detect": True}
            return self._forms_data

        try:
            with open(self.forms_file, "r", encoding="utf-8") as f:
                self._forms_data = json.load(f)
        except Exception:
            self._forms_data = {"pokemon_forms": {}, "auto_detect": True}

        return self._forms_data

    def _save_forms_data(self):
        """Save forms data to file."""
        if self._forms_data is None:
            return

        self._ensure_forms_dir()
        try:
            with open(self.forms_file, "w", encoding="utf-8") as f:
                json.dump(self._forms_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving forms data: {e}")

    def set_pokemon_form(self, pokemon_id: int, form_key: str, form_name: str):
        """Set the preferred form for a specific Pokemon."""
        data = self._load_forms_data()
        data["pokemon_forms"][str(pokemon_id)] = {
            "form_key": form_key,
            "form_name": form_name,
            "user_specified": True
        }
        self._save_forms_data()

    def get_pokemon_form(self, pokemon_id: int) -> Optional[Dict]:
        """Get the preferred form for a specific Pokemon."""
        data = self._load_forms_data()
        return data["pokemon_forms"].get(str(pokemon_id))

    def clear_pokemon_form(self, pokemon_id: int):
        """Clear the preferred form for a specific Pokemon."""
        data = self._load_forms_data()
        data["pokemon_forms"].pop(str(pokemon_id), None)
        self._save_forms_data()

    def set_auto_detect(self, enabled: bool):
        """Enable/disable automatic form detection."""
        data = self._load_forms_data()
        data["auto_detect"] = enabled
        self._save_forms_data()

    def get_auto_detect(self) -> bool:
        """Check if auto detection is enabled."""
        data = self._load_forms_data()
        return data.get("auto_detect", True)

    def set_pokemon_auto_detect(self, pokemon_id: int, enabled: bool):
        """Set auto-detect preference for a specific Pokemon."""
        data = self._load_forms_data()
        pokemon_data = data["pokemon_forms"].get(str(pokemon_id), {})
        pokemon_data["auto_detect"] = enabled
        data["pokemon_forms"][str(pokemon_id)] = pokemon_data
        self._save_forms_data()

    def get_pokemon_auto_detect(self, pokemon_id: int) -> Optional[bool]:
        """Get auto-detect preference for a specific Pokemon. Returns None if not set."""
        data = self._load_forms_data()
        pokemon_data = data["pokemon_forms"].get(str(pokemon_id), {})
        return pokemon_data.get("auto_detect")

    def get_effective_auto_detect(self, pokemon_id: int) -> bool:
        """Get effective auto-detect setting, considering Pokemon-specific and global settings."""
        # Check Pokemon-specific setting first
        pokemon_specific = self.get_pokemon_auto_detect(pokemon_id)
        if pokemon_specific is not None:
            return pokemon_specific

        # Fall back to global slot setting
        return self.get_auto_detect()

    def get_all_forms(self) -> Dict:
        """Get all stored form preferences."""
        data = self._load_forms_data()
        return data.get("pokemon_forms", {})

    def clear_all_forms(self):
        """Clear all form preferences."""
        data = self._load_forms_data()
        data["pokemon_forms"] = {}
        self._save_forms_data()


def get_effective_pokemon_form(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> Optional[Dict]:
    """
    Get the effective form for a Pokemon considering:
    1. User-specified form preferences
    2. Auto-detected forms from items/form_index
    3. Base form (None if no alternative form)
    """
    from .catalog import get_pokemon_alternative_forms, get_form_for_pokemon_with_items

    if not isinstance(pokemon_data, dict):
        return None

    pokemon_id = pokemon_data.get("id")
    species_id = pokemon_data.get("species")
    form_index = pokemon_data.get("formIndex", 0)

    if not pokemon_id or not species_id:
        return None

    # Check user-specified form first
    persistence = SlotFormPersistence(username, slot)
    user_form = persistence.get_pokemon_form(pokemon_id)

    if user_form and user_form.get("user_specified"):
        # Find the form data from catalog
        alt_forms = get_pokemon_alternative_forms(species_id)
        if alt_forms:
            for form in alt_forms.get("forms", []):
                if form.get("form_key") == user_form.get("form_key"):
                    return form

    # Auto-detect if enabled (per-Pokemon setting with global fallback)
    if persistence.get_effective_auto_detect(pokemon_id):
        modifiers = slot_data.get("modifiers", [])
        detected_form = get_form_for_pokemon_with_items(species_id, modifiers, form_index)
        if detected_form:
            return detected_form

    return None


def get_pokemon_display_name(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> str:
    """Get the display name for a Pokemon considering its current form."""
    from .catalog import load_pokemon_catalog

    species_id = pokemon_data.get("species")
    if not species_id:
        return "Unknown"

    # Get effective form
    effective_form = get_effective_pokemon_form(pokemon_data, slot_data, username, slot)

    if effective_form:
        return effective_form.get("form_name", f"Species#{species_id}")

    # Fallback to base species name
    pokemon_catalog = load_pokemon_catalog()
    catalog_entry = pokemon_catalog.get("by_dex", {}).get(str(species_id), {})
    return catalog_entry.get("name", f"Species#{species_id}")


def get_pokemon_effective_stats(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> Optional[Dict]:
    """Get the effective stats for a Pokemon considering its current form."""
    effective_form = get_effective_pokemon_form(pokemon_data, slot_data, username, slot)

    if effective_form:
        return effective_form.get("stats")

    return None


def get_pokemon_effective_types(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> Optional[Dict]:
    """Get the effective types for a Pokemon considering its current form."""
    effective_form = get_effective_pokemon_form(pokemon_data, slot_data, username, slot)

    if effective_form:
        return effective_form.get("types")

    return None


def get_pokemon_effective_ability(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> Optional[str]:
    """Get the effective ability for a Pokemon considering its current form."""
    effective_form = get_effective_pokemon_form(pokemon_data, slot_data, username, slot)

    if effective_form:
        return effective_form.get("ability")

    return None


def enrich_pokemon_with_form_data(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> Dict:
    """
    Enrich Pokemon data with form information at the fundamental data level.
    This is the primary way Pokemon data should be loaded throughout the application.

    Returns an enriched copy of pokemon_data with form information integrated.
    """
    if not isinstance(pokemon_data, dict):
        return pokemon_data

    # Create a copy to avoid modifying original data
    enriched_data = pokemon_data.copy()

    # Get the effective form for this Pokemon
    effective_form = get_effective_pokemon_form(pokemon_data, slot_data, username, slot)

    if effective_form:
        # Add form metadata to the enriched data
        enriched_data["_form_data"] = {
            "form_name": effective_form.get("form_name"),
            "form_key": effective_form.get("form_key"),
            "is_alternative_form": True,
            "source": "form_detection"
        }

        # Optionally override stats, types, and abilities if form provides them
        form_stats = effective_form.get("stats")
        if form_stats:
            enriched_data["_form_stats"] = form_stats

        form_types = effective_form.get("types")
        if form_types:
            enriched_data["_form_types"] = form_types

        form_ability = effective_form.get("ability")
        if form_ability:
            enriched_data["_form_ability"] = form_ability
    else:
        # Mark as base form
        enriched_data["_form_data"] = {
            "form_name": "Base Form",
            "form_key": "base",
            "is_alternative_form": False,
            "source": "base"
        }

    return enriched_data


def determine_default_form_selection(pokemon_data: Dict, slot_data: Dict, username: str, slot: int) -> str:
    """
    Determine which form should be selected by default using the intelligent logic:
    1. If rare form change item detected and we have data -> use that form
    2. If only one alternative form exists -> use that form
    3. If multiple forms exist -> use first alternative form but show hint
    4. Otherwise -> use base form
    """
    from .catalog import get_pokemon_alternative_forms, get_form_for_pokemon_with_items

    if not isinstance(pokemon_data, dict):
        return "Base Form"

    species_id = pokemon_data.get("species")
    if not species_id:
        return "Base Form"

    # Get available alternative forms
    alt_forms = get_pokemon_alternative_forms(species_id)
    if not alt_forms or not alt_forms.get("forms"):
        return "Base Form"

    available_forms = alt_forms.get("forms", [])
    form_names = [form.get("form_name") for form in available_forms if form.get("form_name")]

    if not form_names:
        return "Base Form"

    # Check for form change items first
    modifiers = slot_data.get("modifiers", [])
    detected_form = get_form_for_pokemon_with_items(species_id, modifiers, pokemon_data.get("formIndex", 0))

    if detected_form:
        # Rare form change item detected and we have data for it
        form_name = detected_form.get("form_name")
        if form_name and form_name in form_names:
            return form_name

    # Check user's previous selection
    persistence = SlotFormPersistence(username, slot)
    user_form = persistence.get_pokemon_form(pokemon_data.get("id"))
    if user_form and user_form.get("user_specified"):
        user_form_name = user_form.get("form_name")
        if user_form_name and user_form_name in ["Base Form"] + form_names:
            return user_form_name

    # Do not auto-select forms solely based on availability; require item or user choice
    return "Base Form"
