from __future__ import annotations

import os
import re
import json as _json
import tkinter as tk
from tkinter import ttk, messagebox

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.catalog import DATA_TYPES_JSON, load_nature_catalog, load_berry_catalog, load_types_catalog
from rogueeditor.form_persistence import get_pokemon_display_name


def _format_item_name(item_id: str) -> str:
    """Convert item ID to human-friendly name."""
    # Handle special cases
    special_cases = {
        "FOCUS_BAND": "Focus Band",
        "MYSTICAL_ROCK": "Mystical Rock", 
        "SOOTHE_BELL": "Soothe Bell",
        "SCOPE_LENS": "Scope Lens",
        "LEEK": "Leek",
        "EVIOLITE": "Eviolite",
        "SOUL_DEW": "Soul Dew",
        "GOLDEN_PUNCH": "Golden Punch",
        "GRIP_CLAW": "Grip Claw",
        "QUICK_CLAW": "Quick Claw",
        "KINGS_ROCK": "King's Rock",
        "LEFTOVERS": "Leftovers",
        "SHELL_BELL": "Shell Bell",
        "TOXIC_ORB": "Toxic Orb",
        "FLAME_ORB": "Flame Orb",
        "BATON": "Baton",
        "WIDE_LENS": "Wide Lens",
        "MULTI_LENS": "Multi Lens",
        "EXP_CHARM": "Exp Charm",
        "SUPER_EXP_CHARM": "Super Exp Charm",
        "EXP_SHARE": "Exp Share",
        "MAP": "Map",
        "IV_SCANNER": "IV Scanner",
        "GOLDEN_POKEBALL": "Golden Pokéball",
        "LURE": "Lure",
        "SUPER_LURE": "Super Lure",
        "MAX_LURE": "Max Lure",
        "AMULET_COIN": "Amulet Coin",
        "MEGA_BRACELET": "Mega Bracelet",
        "TERA_ORB": "Tera Orb",
        "DYNAMAX_BAND": "Dynamax Band",
        "SHINY_CHARM": "Shiny Charm",
        "ABILITY_CHARM": "Ability Charm",
        "CATCHING_CHARM": "Catching Charm",
        "NUGGET": "Nugget",
        "BIG_NUGGET": "Big Nugget",
        "RELIC_GOLD": "Relic Gold",
        "COIN_CASE": "Coin Case",
        "LOCK_CAPSULE": "Lock Capsule",
        "BERRY_POUCH": "Berry Pouch",
        "HEALING_CHARM": "Healing Charm",
        "CANDY_JAR": "Candy Jar",
        "LUCKY_EGG": "Lucky Egg",
        "GOLDEN_EGG": "Golden Egg",
        "RARE_FORM_CHANGE_ITEM": "Rare Form Change Item",
        "GENERIC_FORM_CHANGE_ITEM": "Generic Form Change Item",
        "DIRE_HIT": "Dire Hit",
        
        # Arceus Plates
        "FLAME_PLATE": "Flame Plate",
        "SPLASH_PLATE": "Splash Plate", 
        "ZAP_PLATE": "Zap Plate",
        "MEADOW_PLATE": "Meadow Plate",
        "ICICLE_PLATE": "Icicle Plate",
        "FIST_PLATE": "Fist Plate",
        "TOXIC_PLATE": "Toxic Plate",
        "EARTH_PLATE": "Earth Plate",
        "SKY_PLATE": "Sky Plate",
        "MIND_PLATE": "Mind Plate",
        "INSECT_PLATE": "Insect Plate",
        "STONE_PLATE": "Stone Plate",
        "SPOOKY_PLATE": "Spooky Plate",
        "DRACO_PLATE": "Draco Plate",
        "DREAD_PLATE": "Dread Plate",
        "IRON_PLATE": "Iron Plate",
        "PIXIE_PLATE": "Pixie Plate",
        
        # Type: Null Memory Discs
        "FIRE_MEMORY": "Fire Memory",
        "WATER_MEMORY": "Water Memory",
        "ELECTRIC_MEMORY": "Electric Memory",
        "GRASS_MEMORY": "Grass Memory",
        "ICE_MEMORY": "Ice Memory",
        "FIGHTING_MEMORY": "Fighting Memory",
        "POISON_MEMORY": "Poison Memory",
        "GROUND_MEMORY": "Ground Memory",
        "FLYING_MEMORY": "Flying Memory",
        "PSYCHIC_MEMORY": "Psychic Memory",
        "BUG_MEMORY": "Bug Memory",
        "ROCK_MEMORY": "Rock Memory",
        "GHOST_MEMORY": "Ghost Memory",
        "DRAGON_MEMORY": "Dragon Memory",
        "DARK_MEMORY": "Dark Memory",
        "STEEL_MEMORY": "Steel Memory",
        "FAIRY_MEMORY": "Fairy Memory",
    }
    
    if item_id in special_cases:
        return special_cases[item_id]
    
    # Default formatting: convert underscores to spaces and title case
    return item_id.replace("_", " ").title()


def _format_stat_name(stat_id: str) -> str:
    """Convert stat ID to human-friendly name."""
    stat_names = {
        "hp": "HP",
        "atk": "Attack", 
        "def": "Defense",
        "spa": "Sp. Attack",
        "spd": "Sp. Defense", 
        "spe": "Speed"
    }
    return stat_names.get(stat_id.lower(), stat_id.upper())


def _format_type_name(type_id: str) -> str:
    """Convert type ID to human-friendly name."""
    return type_id.replace("_", " ").title()


def _format_nature_name(nature_id: str) -> str:
    """Convert nature ID to human-friendly name."""
    return nature_id.replace("_", " ").title()


def _extract_id_from_formatted_string(formatted_string: str) -> str:
    """Extract the ID from a formatted string like 'Display Name (ID)'."""
    if not formatted_string:
        return ""
    
    if formatted_string.endswith(")") and "(" in formatted_string:
        try:
            return formatted_string.rsplit("(", 1)[1].rstrip(")")
        except Exception:
            pass
    
    # Fallback: return the string as-is (for backward compatibility)
    return formatted_string


# Extracted from Source/gui.py (Phase 3). See debug/docs/GUI_MIGRATION_PLAN.md.
class ItemManagerDialog(tk.Toplevel):
    def __init__(self, master: "App", api: PokerogueAPI, editor: Editor, slot: int, preselect_mon_id: int | None = None):
        super().__init__(master)
        try:
            s = int(slot)
        except Exception:
            s = 1
        s = 1 if s < 1 else (5 if s > 5 else s)
        self.title(f"Rogue Manager GUI - Modifiers & Items Manager (Slot {s})")
        self.geometry("900x520")
        self.api = api
        self.editor = editor
        self.slot = s
        self._preselect_mon_id = preselect_mon_id
        # Load slot data once
        self.data = self.api.get_slot(slot)
        self.party = self.data.get("party") or []
        # Dirty state flags
        self._dirty_local = False
        self._dirty_server = False
        
        # Initialize Pokémon-specific form change items first
        self._init_pokemon_specific_forms()
        
        # Initialize cache for formatted item lists
        self._item_list_cache = {}
        
        # Define tooltip method before building UI
        self._create_tooltip = self._create_tooltip_method
        
        self._build()
        self._refresh()
        self._preselect_party()
        try:
            master._modalize(self)
        except Exception:
            pass

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

    def _detect_form_slug(self, mon: dict) -> str | None:
        # Heuristic mirror of Team Editor's detection
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
        if mon.get("isAlolan"): return "alola"
        if mon.get("isGalarian"): return "galar"
        if mon.get("isHisuian"): return "hisui"
        if mon.get("gmax") or mon.get("isGmax"): return "gmax"
        if mon.get("mega") or mon.get("isMega"):
            m = str(mon.get("megaForm") or "").strip().lower()
            if m == "x": return "mega-x"
            if m == "y": return "mega-y"
            return "mega"
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

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # Left: target selector, party list, and current modifiers
        left = ttk.LabelFrame(top, text="Target")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Label(left, text="Apply to:").pack(anchor=tk.W, padx=4, pady=(2, 0))
        self.target_var = tk.StringVar(value="Pokemon")
        target_row = ttk.Frame(left)
        target_row.pack(fill=tk.X, padx=4, pady=2)
        ttk.Radiobutton(
            target_row,
            text="Pokemon",
            variable=self.target_var,
            value="Pokemon",
            command=self._on_target_change,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            target_row,
            text="Trainer",
            variable=self.target_var,
            value="Trainer",
            command=self._on_target_change,
        ).pack(side=tk.LEFT, padx=8)
        
        # Cache invalidation button
        self.btn_refresh_cache = ttk.Button(
            target_row,
            text="🔄 Refresh Lists",
            command=self._invalidate_item_cache,
            width=16
        )
        self.btn_refresh_cache.pack(side=tk.RIGHT, padx=(8, 0))
        
        # Add tooltip for the refresh button
        try:
            from tkinter import messagebox
            def show_refresh_tooltip():
                messagebox.showinfo("Refresh Lists", "This button refreshes all item lists by clearing the cache and reloading data from catalogs. Use this if you notice outdated or missing items.")
            self.btn_refresh_cache.bind("<Button-3>", lambda e: show_refresh_tooltip())  # Right-click for tooltip
        except Exception:
            pass
        
        ttk.Label(left, text="Party:").pack(anchor=tk.W, padx=4)
        self.party_list = tk.Listbox(left, height=10, exportselection=False)
        self.party_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.party_list.bind("<<ListboxSelect>>", lambda e: (self._refresh_mods(), self._update_button_states()))
        self.mod_list = tk.Listbox(left, height=10, exportselection=False)
        self.mod_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.mod_list.bind("<Double-Button-1>", lambda e: self._show_selected_detail())
        btns = ttk.Frame(left)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Edit Stacks...", command=self._edit_selected_stacks).pack(
            side=tk.LEFT, padx=4, pady=4
        )
        ttk.Button(btns, text="Remove Selected", command=self._remove_selected).pack(
            side=tk.LEFT, padx=4, pady=4
        )
        ttk.Button(btns, text="Refresh", command=self._refresh_mods).pack(side=tk.LEFT, padx=4, pady=4)

        # Right: pickers to add items/modifiers
        right = ttk.LabelFrame(top, text="Add Item / Modifier")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        
        # Configure grid for stable button positioning
        right.grid_columnconfigure(1, weight=1)  # Allow column 1 to expand
        right.grid_rowconfigure(100, weight=1)   # Allow row 100 to expand (buttons row)
        
        row = 0
        try:
            ttk.Label(right, text=f"Target Slot: {self.slot}", foreground='gray').grid(row=row, column=0, columnspan=4, sticky=tk.W)
            row += 1
        except Exception:
            pass
        self.lbl_cat = ttk.Label(right, text="Category:")
        self.lbl_cat.grid(row=row, column=0, sticky=tk.W)
        self.cat_var = tk.StringVar(value="Common")
        cat_opts = [
            "Common",
            "Accuracy",
            "Berries",
            "Vitamins",
            "Type Booster",
            "Mint",
            "Temp Battle Modifiers",
            "Trainer EXP Charms",
            "Trainer",
        ]
        self.cat_cb = ttk.Combobox(
            right, textvariable=self.cat_var, values=cat_opts, state="readonly", width=28
        )
        self.cat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda e: (self._on_cat_change(), self._update_button_states()))
        row += 1

        # Common one-arg items
        self.common_var = tk.StringVar()
        self.common_cb = ttk.Combobox(
            right, textvariable=self.common_var, values=self._common_items_formatted(), width=28
        )
        self.lbl_common = ttk.Label(right, text="Common:")
        self.lbl_common.grid(row=row, column=0, sticky=tk.W)
        self.common_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.common_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Accuracy items with boost (permanent pickers area)
        self.acc_var = tk.StringVar()
        self.acc_cb = ttk.Combobox(
            right, textvariable=self.acc_var, values=self._accuracy_items_formatted(), width=28
        )
        self.lbl_acc_item = ttk.Label(right, text="Accuracy:")
        self.lbl_acc_item.grid(row=row, column=0, sticky=tk.W)
        self.acc_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.acc_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Berries
        from rogueeditor.catalog import load_berry_catalog

        berry_n2i, berry_i2n = load_berry_catalog()
        self.berry_var = tk.StringVar()
        self.berry_cb = ttk.Combobox(
            right,
            textvariable=self.berry_var,
            values=self._berry_items_formatted(),
            width=28,
        )
        self.lbl_berry = ttk.Label(right, text="Berry:")
        self.lbl_berry.grid(row=row, column=0, sticky=tk.W)
        self.berry_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.berry_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Base Stat Booster
        from rogueeditor.catalog import load_stat_catalog

        stat_n2i, stat_i2n = load_stat_catalog()
        # Keep mapping for contextual relabeling (vitamins/X-items)
        self._stat_name_to_id = stat_n2i
        self.stat_var = tk.StringVar()
        self.stat_cb = ttk.Combobox(
            right,
            textvariable=self.stat_var,
            values=self._vitamin_items_formatted(),
            width=28,
        )
        self.lbl_stat = ttk.Label(right, text="Vitamin:")
        self.lbl_stat.grid(row=row, column=0, sticky=tk.W)
        self.stat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.stat_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Type Booster (Attack Type Booster)
        self.type_var = tk.StringVar()
        try:
            with open(DATA_TYPES_JSON, "r", encoding="utf-8") as _tf:
                _types = _json.load(_tf) or {}
            _n2i = {str(k).lower(): int(v) for k, v in (_types.get("name_to_id") or {}).items()}
            self._type_name_to_id = _n2i
        except Exception:
            self._type_name_to_id = {}
        self.type_cb = ttk.Combobox(right, textvariable=self.type_var, values=self._type_booster_items_formatted(), width=28)
        self.lbl_type = ttk.Label(right, text="Type Booster:")
        self.lbl_type.grid(row=row, column=0, sticky=tk.W)
        self.type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.type_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Mint (Nature change)
        _nat_n2i, _nat_i2n = load_nature_catalog()
        self.nature_var = tk.StringVar()
        self.nature_cb = ttk.Combobox(right, textvariable=self.nature_var, values=self._mint_items_formatted(), width=28)
        self.lbl_nature = ttk.Label(right, text="Mint:")
        self.lbl_nature.grid(row=row, column=0, sticky=tk.W)
        self.nature_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.nature_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Temp Battle Modifiers (X-items, DIRE_HIT, LUREs)
        self.temp_battle_var = tk.StringVar()
        temp_battle_items = [
            ("X Attack", "1"),
            ("X Defense", "2"), 
            ("X Sp. Attack", "3"),
            ("X Sp. Defense", "4"),
            ("X Speed", "5"),
            ("X Accuracy", "6"),
            ("Lure", "LURE"),
            ("Super Lure", "SUPER_LURE"),
            ("Max Lure", "MAX_LURE")
        ]
        self.temp_battle_cb = ttk.Combobox(right, textvariable=self.temp_battle_var, values=self._temp_battle_items_formatted(), width=28)
        self.lbl_temp_battle = ttk.Label(right, text="Temp Battle:")
        self.lbl_temp_battle.grid(row=row, column=0, sticky=tk.W)
        self.temp_battle_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.temp_battle_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Experience items
        self.exp_var = tk.StringVar()
        self.exp_cb = ttk.Combobox(right, textvariable=self.exp_var, values=self._experience_items_formatted(), width=28)
        self.lbl_exp_item = ttk.Label(right, text="Experience:")
        self.lbl_exp_item.grid(row=row, column=0, sticky=tk.W)
        self.exp_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.exp_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Observed types are merged into Common values; no separate UI row
        self._observed_types: set[str] = set()

        # Trainer modifiers
        self.lbl_player_type = ttk.Label(right, text="Trainer Item:")
        self.lbl_player_type.grid(row=row, column=0, sticky=tk.W)
        self.player_type_var = tk.StringVar()
        # Organize trainer items by category and remove duplicates
        trainer_items = [
            # Experience and progression
            ("Exp Charm", "EXP_CHARM"),
            ("Super Exp Charm", "SUPER_EXP_CHARM"),
            ("Exp Share", "EXP_SHARE"),
            ("Map", "MAP"),
            ("IV Scanner", "IV_SCANNER"),
            ("Golden Pokéball", "GOLDEN_POKEBALL"),
            
            # Battle and encounter modifiers
            ("Amulet Coin", "AMULET_COIN"),
            ("Mega Bracelet", "MEGA_BRACELET"),
            ("Tera Orb", "TERA_ORB"),
            ("Dynamax Band", "DYNAMAX_BAND"),
            
            # Charms and quality of life
            ("Shiny Charm", "SHINY_CHARM"),
            ("Ability Charm", "ABILITY_CHARM"),
            ("Catching Charm", "CATCHING_CHARM"),
            ("Healing Charm", "HEALING_CHARM"),
            
            # Battle modifiers
            ("Dire Hit", "DIRE_HIT"),
            
            # Currency and items
            ("Nugget", "NUGGET"),
            ("Big Nugget", "BIG_NUGGET"),
            ("Relic Gold", "RELIC_GOLD"),
            ("Coin Case", "COIN_CASE"),
            ("Lock Capsule", "LOCK_CAPSULE"),
            ("Berry Pouch", "BERRY_POUCH"),
            ("Candy Jar", "CANDY_JAR"),
        ]
        
        self.player_type_cb = ttk.Combobox(
            right,
            textvariable=self.player_type_var,
            values=self._trainer_items_formatted(),
            width=28,
        )
        self.player_type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.player_type_cb.bind(
            "<<ComboboxSelected>>",
            lambda e: (self._maybe_preset_player_args(), self._apply_visibility(), self._update_button_states()),
        )
        row += 1  # Move to next row after trainer dropdown
        
        # Optionally augment from TmpServerFiles if present
        try:
            extras = self._augment_player_types_from_tmp()
            if extras:
                vals = list(self.player_type_cb["values"])
                for v in extras:
                    if v not in vals:
                        vals.append(v)
                self.player_type_cb["values"] = vals
            # Store the full list for later category-specific filtering
            self._player_type_all_values = self._trainer_items_formatted()
        except Exception:
            pass
        # Generic args (rarely used). Kept for compatibility; positioned in dynamic frame
        self.player_args_var = tk.StringVar()

        # Options (dynamic controls placed below): accuracy boost, stacks, args
        # Hints row - shows contextual hints for the selected category
        self.hint_label = ttk.Label(right, text="", foreground="blue", font=("TkDefaultFont", 8))
        self.hint_label.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=4, pady=2)
        row += 1
        
        # Dynamic fields row - shows relevant input fields based on selection
        self.dynamic_frame = ttk.Frame(right)
        self.dynamic_frame.grid(row=row, column=0, columnspan=4, sticky=tk.EW, padx=4, pady=2)
        self.dynamic_frame.grid_columnconfigure(1, weight=1)
        self.dynamic_frame.grid_columnconfigure(3, weight=1)
        
        # Accuracy boost (for WIDE_LENS)
        self.lbl_acc_boost = ttk.Label(self.dynamic_frame, text="Boost:")
        self.acc_boost = ttk.Entry(self.dynamic_frame, width=6)
        self.acc_boost.insert(0, "5")
        self.acc_boost.bind("<KeyRelease>", lambda e: self._update_button_states())
        
        # Stacks
        self.lbl_stacks = ttk.Label(self.dynamic_frame, text="Stacks:")
        self.stack_var = tk.StringVar(value="1")
        self.stack_entry = ttk.Entry(self.dynamic_frame, textvariable=self.stack_var, width=6)
        self.stack_entry.bind("<KeyRelease>", lambda e: self._update_button_states())
        
        # Player args
        self.lbl_player_args = ttk.Label(self.dynamic_frame, text="Args (auto-filled, customizable):")
        self.player_args_entry = ttk.Entry(self.dynamic_frame, textvariable=self.player_args_var, width=18)
        self.player_args_entry.bind("<KeyRelease>", lambda e: self._update_button_states())
        
        # Position dynamic fields
        self.lbl_acc_boost.grid(row=0, column=0, sticky=tk.E, padx=(0, 4))
        self.acc_boost.grid(row=0, column=1, sticky=tk.W, padx=(0, 8))
        self.lbl_stacks.grid(row=0, column=2, sticky=tk.E, padx=(0, 4))
        self.stack_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 8))
        self.lbl_player_args.grid(row=1, column=0, sticky=tk.E, padx=(0, 4))
        self.player_args_entry.grid(row=1, column=1, sticky=tk.W, padx=(0, 8))
        

        # Trainer properties panel (only visible for Trainer target)
        row += 1
        self.trainer_frame = ttk.LabelFrame(right, text="Trainer Properties")
        self.trainer_frame.grid(row=row, column=0, columnspan=4, sticky=tk.EW, padx=2, pady=(8, 4))
        self.trainer_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(self.trainer_frame, text="Money:").grid(row=0, column=0, sticky=tk.E, padx=4, pady=2)
        self.money_var = tk.StringVar(value="")
        self.money_entry = ttk.Entry(self.trainer_frame, textvariable=self.money_var, width=12)
        self.money_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)
        # Bind money field changes to automatically update data
        self.money_var.trace_add("write", lambda *args: self._on_money_change())
        self.money_entry.bind("<KeyRelease>", lambda e: self._on_money_change())

        # Pokéball management section
        row += 1
        self.pokeball_frame = ttk.LabelFrame(right, text="Pokéball Inventory")
        self.pokeball_frame.grid(row=row, column=0, columnspan=4, sticky=tk.EW, padx=2, pady=(8, 4))
        self.pokeball_frame.grid_columnconfigure(1, weight=1)
        self.pokeball_frame.grid_columnconfigure(3, weight=1)
        self.pokeball_frame.grid_columnconfigure(5, weight=1)
        
        # Pokéball types and their variables
        self.pokeball_types = [
            ("Poké Ball", "pokeball"),      # ID 0
            ("Great Ball", "greatball"),    # ID 1
            ("Ultra Ball", "ultraball"),    # ID 2
            ("Rogue Ball", "rogueball"),    # ID 3
            ("Master Ball", "masterball")   # ID 4
        ]
        
        self.pokeball_vars = {}
        for i, (name, key) in enumerate(self.pokeball_types):
            row_idx = i // 3
            col_idx = (i % 3) * 2
            
            ttk.Label(self.pokeball_frame, text=f"{name}:").grid(row=row_idx, column=col_idx, sticky=tk.E, padx=4, pady=2)
            var = tk.StringVar(value="0")
            self.pokeball_vars[key] = var
            # Bind to variable changes as well as key releases
            var.trace_add("write", lambda *args: self._on_pokeball_change())
            entry = ttk.Entry(self.pokeball_frame, textvariable=var, width=8)
            entry.grid(row=row_idx, column=col_idx + 1, sticky=tk.W, padx=4, pady=2)
            entry.bind("<KeyRelease>", lambda e: self._on_pokeball_change())

        # Load Pokéball data
        self._load_pokeball_data()

        # Button layout - Add on bottom left, Save/Upload on bottom right
        # Position buttons at the very bottom for stable layout
        self.btn_add = ttk.Button(right, text="Add", command=self._add, state=tk.DISABLED)
        self.btn_add.grid(row=100, column=0, sticky=tk.W, padx=4, pady=6)
        
        self.btn_save = ttk.Button(right, text="Save to file", command=self._save, state=tk.DISABLED)
        self.btn_save.grid(row=100, column=2, sticky=tk.E, padx=4, pady=6)
        # Add tooltip to clarify the difference
        self._create_tooltip(self.btn_save, 
            "Save to file: Writes all changes to the local save file on disk.\n"
            "This includes Pokémon modifiers, trainer data, and Pokéball inventory.\n"
            "Changes are automatically applied to memory as you type.")
        self.btn_upload = ttk.Button(right, text="Upload", command=self._upload, state=tk.DISABLED)
        self.btn_upload.grid(row=100, column=3, sticky=tk.E, padx=4, pady=6)
        # Add tooltip to clarify the difference
        self._create_tooltip(self.btn_upload, 
            "Upload: Syncs all changes to the server.\n"
            "This uploads the current save data to the online game.\n"
            "Changes are automatically applied to memory as you type.")

        # Initial visibility/state
        self._apply_visibility()
        self._update_button_states()

    def _common_items(self) -> set[str]:
        """Get common items as a set for internal use."""
        # Core held items (not duplicated in other categories)
        # Removed items that are better placed in other categories:
        # - SCOPE_LENS, WIDE_LENS, MULTI_LENS -> Accuracy category
        # - LURE, SUPER_LURE, MAX_LURE -> Temp Battle Modifiers
        # - EXP_SHARE, IV_SCANNER, MAP, AMULET_COIN, MEGA_BRACELET, TERA_ORB, DYNAMAX_BAND -> Trainer items
        # - DIRE_HIT -> Trainer items
        # - LUCKY_EGG, GOLDEN_EGG -> Should be in a separate "Experience" category
        return {
            # Core held items that don't fit other categories
            "FOCUS_BAND",      # Survive fatal damage
            "MYSTICAL_ROCK",   # Extend weather/terrain
            "SOOTHE_BELL",     # Friendship boost
            "LEEK",            # Crit boost for specific species
            "EVIOLITE",        # Pre-evolution stat boost
            "SOUL_DEW",        # Nature effect boost
            "GOLDEN_PUNCH",    # Money reward on hit
            "GRIP_CLAW",       # Trap effect
            "QUICK_CLAW",      # Speed priority chance
            "KINGS_ROCK",      # Flinch chance
            "LEFTOVERS",       # Turn heal
            "SHELL_BELL",      # Hit heal
            "TOXIC_ORB",       # Toxic status
            "FLAME_ORB",       # Burn status
            "BATON",           # Switch item
            "MULTI_LENS",      # Multi-hit conversion
            # Form change items (Pokémon-specific)
            "RARE_FORM_CHANGE_ITEM",
        }
    
    def _invalidate_item_cache(self):
        """Invalidate the item list cache and recalculate all formatted lists."""
        # Clear the cache
        self._item_list_cache.clear()
        print(f"Cache invalidated. Cache keys: {list(self._item_list_cache.keys())}")
        
        # Refresh all dropdowns that depend on cached data
        self._refresh_all_dropdowns()
    
    def _refresh_all_dropdowns(self):
        """Refresh all dropdowns with fresh cached data."""
        try:
            # Refresh common items
            self.common_cb["values"] = self._common_items_formatted()
            
            # Refresh other dropdowns based on current selection
            tgt = self.target_var.get()
            cat = self.cat_var.get()
            
            if tgt == "Pokemon":
                if cat == "Accuracy":
                    self.acc_cb["values"] = self._accuracy_items_formatted()
                elif cat == "Berries":
                    self.berry_cb["values"] = self._berry_items_formatted()
                elif cat == "Vitamins":
                    self.stat_cb["values"] = self._vitamin_items_formatted()
                elif cat == "Type Booster":
                    self.type_cb["values"] = self._type_booster_items_formatted()
                elif cat == "Mint":
                    self.nature_cb["values"] = self._mint_items_formatted()
                elif cat == "Experience":
                    self.exp_cb["values"] = self._experience_items_formatted()
            elif tgt == "Trainer":
                if cat == "Temp Battle Modifiers":
                    self.temp_battle_cb["values"] = self._temp_battle_items_formatted()
                elif cat == "Trainer EXP Charms":
                    self.player_type_cb["values"] = self._trainer_exp_charm_items_formatted()
                elif cat == "Trainer":
                    self.player_type_cb["values"] = self._trainer_items_formatted()
        except Exception:
            pass

    def _common_items_formatted(self) -> list[str]:
        """Get common items with human-friendly formatting for display."""
        cache_key = "common_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        items = sorted(self._common_items())
        
        # Add Pokémon-specific form change items if a Pokémon is selected
        if hasattr(self, 'preselect_mon_id') and self.preselect_mon_id:
            try:
                # Get the Pokémon's species ID
                pokemon_data = self.data.get("party", {}).get(str(self.preselect_mon_id), {})
                species_id = pokemon_data.get("species", 0)
                
                # Add all form change items available for this Pokémon
                form_change_items = self._get_form_change_items_for_pokemon(species_id)
                items.extend(form_change_items)
                
                items = sorted(items)  # Re-sort with new items
            except Exception:
                pass
        
        # Format items with emojis and descriptions like other lists
        formatted_items = []
        for item in items:
            if self._is_pokemon_specific_form_item(item):
                # Pokémon-specific form items get special formatting
                pokemon_id = self._get_pokemon_for_form_item(item)
                if pokemon_id in self.pokemon_specific_forms:
                    data = self.pokemon_specific_forms[pokemon_id]
                    emoji = data["emoji"]
                    category = data["category_name"]
                    formatted_items.append(f"{emoji} {_format_item_name(item)} - {category} ({item})")
                else:
                    formatted_items.append(f"🔄 {_format_item_name(item)} - Form Change ({item})")
            elif item == "RARE_FORM_CHANGE_ITEM" and hasattr(self, 'preselect_mon_id') and self.preselect_mon_id:
                # Show specific form information for RARE_FORM_CHANGE_ITEM
                try:
                    pokemon_data = self.data.get("party", {}).get(str(self.preselect_mon_id), {})
                    species_id = pokemon_data.get("species", 0)
                    alternative_forms = self._get_alternative_forms_for_pokemon(species_id)
                    
                    if alternative_forms:
                        # Show all available forms for this Pokémon
                        form_descriptions = []
                        for form_type, form_data in alternative_forms.items():
                            form_descriptions.append(f"{form_data['name']} ({form_type.upper()})")
                        
                        form_info = " | ".join(form_descriptions)
                        formatted_items.append(f"🔄 {_format_item_name(item)} - {form_info} ({item})")
                    else:
                        formatted_items.append(f"🔄 {_format_item_name(item)} - Form Change ({item})")
                except Exception:
                    formatted_items.append(f"🔄 {_format_item_name(item)} - Form Change ({item})")
            else:
                # Regular common items get standard formatting with emojis
                emoji = self._get_item_emoji(item)
                description = self._get_item_description(item)
                formatted_items.append(f"{emoji} {_format_item_name(item)} - {description} ({item})")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _accuracy_items_formatted(self) -> list[str]:
        """Get accuracy items with human-friendly formatting for display."""
        cache_key = "accuracy_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        items = ["WIDE_LENS", "SCOPE_LENS"]
        formatted_items = []
        for item in items:
            emoji = self._get_item_emoji(item)
            description = self._get_item_description(item)
            formatted_items.append(f"{emoji} {_format_item_name(item)} ({item}) - {description}")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _experience_items_formatted(self) -> list[str]:
        """Get experience items with human-friendly formatting for display."""
        cache_key = "experience_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        items = ["LUCKY_EGG", "GOLDEN_EGG"]
        formatted_items = []
        for item in items:
            emoji = self._get_item_emoji(item)
            description = self._get_item_description(item)
            formatted_items.append(f"{emoji} {_format_item_name(item)} ({item}) - {description}")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _berry_items_formatted(self) -> list[str]:
        """Get berry items with human-friendly formatting for display."""
        cache_key = "berry_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        try:
            from rogueeditor.catalog import load_berry_catalog
            berry_n2i, berry_i2n = load_berry_catalog()
            
            formatted_items = []
            for name, berry_id in sorted(berry_n2i.items(), key=lambda kv: kv[1]):
                formatted_name = name.replace("_", " ").title()  # Convert to Title Case
                emoji = "🍓"  # Default berry emoji
                description = "Berry"
                formatted_items.append(f"{emoji} {formatted_name} ({name}) - {description}")
            
            # Cache the result
            self._item_list_cache[cache_key] = formatted_items
            return formatted_items
        except Exception:
            return []

    def _vitamin_items_formatted(self) -> list[str]:
        """Get vitamin items with human-friendly formatting for display."""
        cache_key = "vitamin_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        # Traditional vitamins only (exclude accuracy and evasion)
        vitamin_stats = {
            "hp": "HP Up",
            "atk": "Protein", 
            "def": "Iron",
            "spatk": "Calcium",
            "spdef": "Zinc",
            "spd": "Carbos"
        }
        
        formatted_items = []
        for stat_name, vitamin_name in vitamin_stats.items():
            emoji = "💊"  # Default vitamin emoji
            description = "Vitamin"
            formatted_items.append(f"{emoji} {vitamin_name} ({stat_name}) - {description}")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _type_booster_items_formatted(self) -> list[str]:
        """Get type booster items with human-friendly formatting for display."""
        cache_key = "type_booster_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        try:
            from rogueeditor.catalog import load_types_catalog
            type_n2i, type_i2n = load_types_catalog()
            
            formatted_items = []
            for name, type_id in sorted(type_n2i.items(), key=lambda kv: kv[1]):
                formatted_name = _format_type_name(name)
                emoji = "⚔️"  # Default type booster emoji
                description = "Type Booster"
                formatted_items.append(f"{emoji} {formatted_name} ({name}) - {description}")
            
            # Cache the result
            self._item_list_cache[cache_key] = formatted_items
            return formatted_items
        except Exception:
            return []

    def _mint_items_formatted(self) -> list[str]:
        """Get mint items with human-friendly formatting for display."""
        cache_key = "mint_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        try:
            from rogueeditor.catalog import load_nature_catalog
            nature_n2i, nature_i2n = load_nature_catalog()
            
            formatted_items = []
            for nid, name in sorted(nature_i2n.items(), key=lambda kv: kv[0]):
                formatted_name = _format_nature_name(name)
                emoji = "🌿"  # Default mint emoji
                description = "Mint"
                formatted_items.append(f"{emoji} {formatted_name} ({nid}) - {description}")
            
            # Cache the result
            self._item_list_cache[cache_key] = formatted_items
            return formatted_items
        except Exception:
            return []

    def _temp_battle_items_formatted(self) -> list[str]:
        """Get temp battle items with human-friendly formatting for display."""
        cache_key = "temp_battle_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        temp_battle_items = [
            ("X Attack", "X_ATTACK", "5 waves"),
            ("X Defense", "X_DEFENSE", "5 waves"),
            ("X Sp. Attack", "X_SP_ATTACK", "5 waves"),
            ("X Sp. Defense", "X_SP_DEFENSE", "5 waves"),
            ("X Speed", "X_SPEED", "5 waves"),
            ("X Accuracy", "X_ACCURACY", "5 waves"),
            ("Dire Hit", "DIRE_HIT", "5 waves"),
            ("Lure", "LURE", "10 turns"),
            ("Super Lure", "SUPER_LURE", "15 turns"),
            ("Max Lure", "MAX_LURE", "30 turns")
        ]
        formatted_items = []
        for name, item_id, duration in temp_battle_items:
            emoji = self._get_item_emoji(item_id)
            description = self._get_item_description(item_id)
            formatted_items.append(f"{emoji} {name} - {duration} - {description} ({item_id})")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _trainer_exp_charm_items_formatted(self) -> list[str]:
        """Get trainer EXP charm items with human-friendly formatting for display."""
        cache_key = "trainer_exp_charm_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        exp_charm_items = [
            ("Exp Charm", "EXP_CHARM"),
            ("Super Exp Charm", "SUPER_EXP_CHARM")
        ]
        formatted_items = []
        for name, item_id in exp_charm_items:
            emoji = self._get_item_emoji(item_id)
            description = self._get_item_description(item_id)
            formatted_items.append(f"{emoji} {name} ({item_id}) - {description}")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _trainer_items_formatted(self) -> list[str]:
        """Get trainer items with human-friendly formatting for display."""
        cache_key = "trainer_items"
        if cache_key in self._item_list_cache:
            return self._item_list_cache[cache_key]
        
        trainer_items = [
            ("Exp Share", "EXP_SHARE"),
            ("IV Scanner", "IV_SCANNER"),
            ("Map", "MAP"),
            ("Amulet Coin", "AMULET_COIN"),
            ("Golden Pokéball", "GOLDEN_POKEBALL"),
            ("Mega Bracelet", "MEGA_BRACELET"),
            ("Tera Orb", "TERA_ORB"),
            ("Dynamax Band", "DYNAMAX_BAND"),
            ("Shiny Charm", "SHINY_CHARM"),
            ("Ability Charm", "ABILITY_CHARM"),
            ("Catching Charm", "CATCHING_CHARM"),
            ("Nugget", "NUGGET"),
            ("Big Nugget", "BIG_NUGGET"),
            ("Relic Gold", "RELIC_GOLD"),
            ("Coin Case", "COIN_CASE"),
            ("Lock Capsule", "LOCK_CAPSULE"),
            ("Berry Pouch", "BERRY_POUCH"),
            ("Healing Charm", "HEALING_CHARM"),
            ("Candy Jar", "CANDY_JAR"),
        ]
        formatted_items = []
        for name, item_id in trainer_items:
            emoji = self._get_item_emoji(item_id)
            description = self._get_item_description(item_id)
            formatted_items.append(f"{emoji} {name} ({item_id}) - {description}")
        
        # Cache the result
        self._item_list_cache[cache_key] = formatted_items
        return formatted_items

    def _on_cat_change(self):
        # Adjust available categories and hint text when switching contexts
        # When target changes, restrict categories accordingly
        tgt = self.target_var.get()
        if tgt == "Trainer":
            vals = ["Temp Battle Modifiers", "Trainer EXP Charms", "Trainer"]
        else:
            vals = ["Common", "Experience", "Accuracy", "Berries", "Vitamins", "Type Booster", "Mint"]
        try:
            self.cat_cb["values"] = vals
            if self.cat_var.get() not in vals:
                self.cat_var.set(vals[0])
        except Exception:
            pass
        # Visibility by category
        self._apply_visibility()

    def _refresh(self):
        # Populate party list and preserve selection, mirroring Team Editor labels
        try:
            prev = self.party_list.curselection()[0]
        except Exception:
            prev = 0
        self.party_list.delete(0, tk.END)
        from rogueeditor.utils import invert_dex_map, load_pokemon_index
        from rogueeditor.catalog import load_pokemon_catalog

        inv = invert_dex_map(load_pokemon_index())
        cat = load_pokemon_catalog() or {}
        by_dex = cat.get("by_dex") or {}
        for i, mon in enumerate(self.party, start=1):
            did = str(
                mon.get("species")
                or mon.get("dexId")
                or mon.get("speciesId")
                or mon.get("pokemonId")
                or "?"
            )
            entry = by_dex.get(did) or {}
            base_name = entry.get("name") or inv.get(did, did)

            # Use form-aware display name from the comprehensive form persistence system
            try:
                form_aware_name = get_pokemon_display_name(mon, self.data, self.api.username, self.slot)
                display_name = form_aware_name if form_aware_name and form_aware_name != "Unknown" else base_name
            except Exception:
                # Fallback to the old form detection method if the new system fails
                fslug = self._detect_form_slug(mon)
                form_disp = None
                if fslug and (entry.get("forms") or {}).get(fslug):
                    fdn = (entry.get("forms") or {}).get(fslug, {}).get("display_name")
                    if isinstance(fdn, str) and fdn.strip():
                        form_disp = fdn
                if form_disp:
                    display_name = f"{base_name} ({form_disp})"
                else:
                    display_name = base_name

            try:
                label = f"{i}. {int(did):04d} {display_name}"
            except Exception:
                label = f"{i}. {did} {display_name}"
            mid = mon.get("id")
            lvl = mon.get("level") or mon.get("lvl") or "?"
            self.party_list.insert(tk.END, f"{label} • id {mid} • Lv {lvl}")
        # Observed modifiers
        self._reload_observed()
        # Restore selection
        try:
            self.party_list.selection_set(prev)
            self.party_list.activate(prev)
            self.party_list.see(prev)
        except Exception:
            pass
        self._refresh_mods()
        self._update_button_states()
        # Populate trainer properties (money)
        try:
            m = self.data.get("money")
            self.money_var.set(str(int(m)))
        except Exception:
            try:
                self.money_var.set(str(self.data.get("money") or ""))
            except Exception:
                pass
        
        # Reload Pokéball data when refreshing
        self._load_pokeball_data()

    def _preselect_party(self):
        try:
            if not isinstance(self._preselect_mon_id, int):
                return
            # Find index in party by mon id
            for idx, mon in enumerate(self.party):
                try:
                    if int(mon.get("id")) == int(self._preselect_mon_id):
                        self.party_list.selection_clear(0, tk.END)
                        self.party_list.selection_set(idx)
                        self.party_list.activate(idx)
                        self.party_list.see(idx)
                        self._refresh_mods()
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def _maybe_preset_player_args(self):
        # Pre-populate args for known trainer items that use fixed values
        try:
            sel = (self.player_type_var.get() or "").strip()
            if not sel:
                return
            # Extract ID from formatted string
            t = _extract_id_from_formatted_string(sel).upper()
            if not t:
                return
            # Prefill known values for modifiers with established patterns
            if t == "EXP_CHARM" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("25")
            elif t == "SUPER_EXP_CHARM" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("60")
            elif t == "LURE" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("10, 10")  # duration, waves_remaining
            elif t == "SUPER_LURE" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("15, 15")  # duration, waves_remaining
            elif t == "MAX_LURE" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("30, 30")  # duration, waves_remaining
            elif t == "HEALING_CHARM" and not (self.player_args_var.get() or "").strip():
                self.player_args_var.set("1.1")     # 10% healing boost
            else:
                # Clear args for no-arg items
                if t in {"EXP_SHARE", "IV_SCANNER", "MAP", "AMULET_COIN", "GOLDEN_POKEBALL", "MEGA_BRACELET", "TERA_ORB", "DYNAMAX_BAND", "SHINY_CHARM", "CATCHING_CHARM", "OVAL_CHARM", "BERRY_POUCH", "LOCK_CAPSULE", "CANDY_JAR"}:
                    self.player_args_var.set("")
        except Exception:
            pass

    def _reload_observed(self):
        # Collect typeIds from this slot and local dumps
        obs: set[str] = set()
        mods = self.data.get("modifiers") or []
        for m in mods:
            if isinstance(m, dict) and m.get("typeId"):
                obs.add(str(m.get("typeId")))
        try:
            from rogueeditor.utils import user_save_dir, load_json

            base = user_save_dir(self.api.username)
            for fname in os.listdir(base):
                if not fname.endswith(".json"):
                    continue
                try:
                    d = load_json(os.path.join(base, fname))
                    for m in d.get("modifiers") or []:
                        if isinstance(m, dict) and m.get("typeId"):
                            obs.add(str(m.get("typeId")))
                except Exception:
                    continue
        except Exception:
            pass
        # Merge with curated sets and update Common picker
        # Exclude types that require specialized pickers (to avoid wrong args): use dedicated categories instead
        reserved = {
            "WIDE_LENS",
            "MULTI_LENS",
            "BERRY",
            "BASE_STAT_BOOSTER",
            "ATTACK_TYPE_BOOSTER",
            "MINT",
        }
        # Exclude trainer-only items from Common observed list
        trainer_only = {
            "EXP_CHARM",
            "SUPER_EXP_CHARM",
            "EXP_SHARE",
            "IV_SCANNER",
            "MAP",
            "AMULET_COIN",
            "GOLDEN_POKEBALL",
            "MEGA_BRACELET",
            "TERA_ORB",
            "DYNAMAX_BAND",
            "SHINY_CHARM",
            "ABILITY_CHARM",
            "CATCHING_CHARM",
            "NUGGET",
            "BIG_NUGGET",
            "RELIC_GOLD",
            "COIN_CASE",
            "LOCK_CAPSULE",
            "BERRY_POUCH",
            "HEALING_CHARM",
            "CANDY_JAR",
        }
        obs |= self._common_items()
        self._observed_types = obs
        try:
            cur = set(self._common_items())
            allowed = (self._observed_types - reserved - trainer_only) | cur
            # Use formatted items for display, but keep raw IDs for internal logic
            self.common_cb["values"] = self._common_items_formatted()
        except Exception:
            pass

    def _current_mon(self):
        try:
            idx = self.party_list.curselection()[0]
            return self.party[idx]
        except Exception:
            return None

    def _refresh_mods(self):
        self.mod_list.delete(0, tk.END)
        target = self.target_var.get()
        mods = self.data.get("modifiers") or []
        if target == "Trainer":
            # Show player-level mods
            party_ids = set(int((p.get("id"))) for p in self.party if isinstance(p.get("id"), int))
            for i, m in enumerate(mods):
                if not isinstance(m, dict):
                    continue
                args = m.get("args") or []
                first = args[0] if (isinstance(args, list) and args) else None
                if not (isinstance(first, int) and first in party_ids):
                    # Use formatted display for better readability
                    display_text = self._format_modifier_display(m, i, True)
                    self.mod_list.insert(tk.END, display_text)
        else:
            mon = self._current_mon()
            if not mon:
                return
            mon_id = mon.get("id")
            for i, m in enumerate(mods):
                if not isinstance(m, dict):
                    continue
                args = m.get("args") or []
                if args and isinstance(args, list) and isinstance(args[0], int) and args[0] == mon_id:
                    # Use formatted display for better readability
                    display_text = self._format_modifier_display(m, i, False)
                    self.mod_list.insert(tk.END, display_text)
        # Adjust category and button states after refresh
        try:
            self._on_cat_change()
        except Exception:
            pass
        self._update_button_states()

    def _apply_visibility(self):
        # Helper to show/hide widgets by selected category/target
        cat = self.cat_var.get()
        tgt = self.target_var.get()
        def show(w, visible):
            try:
                if visible:
                    w.grid()
                else:
                    w.grid_remove()
            except Exception:
                pass
        # Player-only fields
        player_visible = (tgt == "Trainer" or cat in ("Trainer", "Trainer EXP Charms"))
        # Category flags
        is_trainer_stat = (cat == "Trainer Stat Stage Boosters")  # Legacy - no longer used
        is_trainer_exp = (cat == "Trainer EXP Charms")
        is_temp_battle = (cat == "Temp Battle Modifiers")
        is_exp = (cat == "Experience")
        trainer_catchall = (cat == "Trainer")
        # Player stat selector visible for trainer stat boosters
        player_needs_stat = is_trainer_stat
        # Player args are hidden in grouped categories (exp/stat); only in catch-all for rare items
        player_args_visible = (trainer_catchall and _extract_id_from_formatted_string(self.player_type_var.get() or "").upper() in {"EXP_CHARM", "SUPER_EXP_CHARM"})
        # Pokemon-only categories
        common_v = (tgt == "Pokemon" and cat == "Common")
        acc_v = (tgt == "Pokemon" and cat == "Accuracy")
        berry_v = (tgt == "Pokemon" and cat == "Berries")
        stat_v = (tgt == "Pokemon" and cat == "Vitamins")
        typeb_v = (tgt == "Pokemon" and cat == "Type Booster")
        mint_v = (tgt == "Pokemon" and cat == "Mint")
        exp_v = (tgt == "Pokemon" and cat == "Experience")
        # No separate Observed category; merged into Common
        # Toggle
        # Configure player type values per category
        if is_trainer_exp:
            try:
                self.player_type_cb["values"] = self._trainer_exp_charm_items_formatted()
            except Exception:
                pass
        elif trainer_catchall:
            try:
                self.player_type_cb["values"] = getattr(self, "_player_type_all_values", list(self.player_type_cb["values"]))
            except Exception:
                pass
        show(self.lbl_player_type, (is_trainer_exp or trainer_catchall))
        show(self.player_type_cb, (is_trainer_exp or trainer_catchall))
        show(self.lbl_player_args, player_args_visible)
        show(self.player_args_entry, player_args_visible)
        # Reuse stat selector for temp stat stage booster
        for w in (self.lbl_stat, self.stat_cb):
            show(w, (tgt == "Pokemon" and cat == "Vitamins") or player_needs_stat)
        for w in (self.lbl_common, self.common_cb):
            show(w, common_v)
        for w in (self.lbl_acc_item, self.acc_cb):
            show(w, acc_v)
        for w in (self.lbl_berry, self.berry_cb):
            show(w, berry_v)
        for w in (self.lbl_type, self.type_cb):
            show(w, typeb_v)
        for w in (self.lbl_nature, self.nature_cb):
            show(w, mint_v)
        for w in (self.lbl_exp_item, self.exp_cb):
            show(w, exp_v)
        # Temp battle modifiers
        for w in (self.lbl_temp_battle, self.temp_battle_cb):
            show(w, is_temp_battle)
        # Update hint text based on category
        try:
            hint_text = ""
            if stat_v:
                hint_text = "Hint: Each stack applies a percentage effect per stack."
            elif player_needs_stat:
                hint_text = "Choose which battle stat to boost temporarily."
            elif acc_v:
                hint_text = "Hint: Set accuracy boost percentage (default: 5)."
            elif mint_v:
                hint_text = "Hint: Mints change the Pokémon's nature permanently."
            elif common_v:
                hint_text = "Hint: Most common items don't need stacks, but some do."
            elif exp_v:
                hint_text = "Hint: Experience items boost EXP gain for Pokémon."
            elif is_temp_battle:
                hint_text = "Hint: Temp battle modifiers affect the next few battles."
            elif is_trainer_exp:
                hint_text = "Hint: EXP charms boost experience gain."
            elif trainer_catchall:
                hint_text = "Hint: Trainer items provide various benefits."
            
            self.hint_label.configure(text=hint_text)
            show(self.hint_label, True)  # Always show hint label to reserve the row
        except Exception:
            pass
        
        # Options visibility: accuracy boost only when accuracy category selected
        show(self.lbl_acc_boost, acc_v)
        show(self.acc_boost, acc_v)
        
        # Stacks visibility - exclude items that don't make sense to stack
        stacks_visible = (
            acc_v or berry_v or stat_v or typeb_v or is_trainer_stat or is_trainer_exp or is_temp_battle or trainer_catchall
        )
        # Exclude mints and certain common items that don't stack
        if common_v:
            try:
                # Check if selected common item should have stacks
                selected_common = _extract_id_from_formatted_string(self.common_var.get() or "")
                # Items that don't make sense to stack: orbs, form change items, etc.
                non_stackable_common = {
                    "TOXIC_ORB", "FLAME_ORB", "RARE_FORM_CHANGE_ITEM", "GENERIC_FORM_CHANGE_ITEM",
                    "BATON", "LEFTOVERS", "SHELL_BELL", "FOCUS_BAND",
                    "LUCKY_EGG", "GOLDEN_EGG"
                }
                
                # Add Pokémon-specific form items to non-stackable list
                if hasattr(self, 'preselect_mon_id') and self.preselect_mon_id:
                    pokemon_data = self.data.get("party", {}).get(str(self.preselect_mon_id), {})
                    species_id = pokemon_data.get("species", 0)
                    pokemon_specific_items = self._get_pokemon_specific_form_items(species_id)
                    non_stackable_common.update(pokemon_specific_items)
                
                if selected_common not in non_stackable_common:
                    stacks_visible = True
            except Exception:
                pass
        
        show(self.lbl_stacks, stacks_visible)
        show(self.stack_entry, stacks_visible)
        
        # Show/hide the entire dynamic frame based on whether any fields are visible
        dynamic_visible = acc_v or stacks_visible or player_args_visible
        show(self.dynamic_frame, True)  # Always show dynamic frame to reserve the row
        # Contextual relabeling of the stat selector values
        try:
            def _preserve_by_id():
                raw = (self.stat_var.get() or "").strip()
                sel_id = None
                if raw.endswith(")") and "(" in raw:
                    try:
                        sel_id = int(raw.rsplit("(", 1)[1].rstrip(")"))
                    except Exception:
                        sel_id = None
                return sel_id
            def _select_id(sid):
                if sid is None:
                    return
                vals = list(self.stat_cb["values"]) or []
                for v in vals:
                    if v.endswith(f"({sid})"):
                        self.stat_var.set(v)
                        break
            if (tgt == "Pokemon" and cat == "Vitamins"):
                sid = _preserve_by_id()
                self.stat_cb["values"] = self._vitamin_items_formatted()
                _select_id(sid)
            elif player_needs_stat:
                sid = _preserve_by_id()
                self.stat_cb["values"] = self._xitem_stat_values()
                _select_id(sid)
        except Exception:
            pass
        # Trainer properties panel visibility
        show(self.trainer_frame, tgt == "Trainer")
        # Pokéball inventory visibility (only for trainer target)
        show(self.pokeball_frame, tgt == "Trainer")

    def _update_button_states(self):
        # Save/Upload gating
        try:
            self.btn_save.configure(
                state=(tk.NORMAL if getattr(self, "_dirty_local", False) or getattr(self, "_dirty_server", False) else tk.DISABLED)
            )
            self.btn_upload.configure(state=(tk.NORMAL if getattr(self, "_dirty_server", False) else tk.DISABLED))
        except Exception:
            pass
        # Add button gating per target/category
        tgt = self.target_var.get()
        cat = self.cat_var.get()
        valid = False
        if tgt == "Trainer" or cat in ("Trainer", "Trainer EXP Charms", "Temp Battle Modifiers"):
            if cat == "Temp Battle Modifiers":
                # Temp battle modifiers (X-items, DIRE_HIT, LUREs) need selection
                valid = bool((self.temp_battle_var.get() or "").strip())
            elif cat == "Trainer EXP Charms":
                psel = _extract_id_from_formatted_string(self.player_type_var.get() or "").upper()
                valid = psel in {"EXP_CHARM", "SUPER_EXP_CHARM"}
            else:
                psel = _extract_id_from_formatted_string(self.player_type_var.get() or "").upper()
                valid = bool(psel)
        else:
            # Need a selected mon
            valid_mon = self._current_mon() is not None
            if cat == "Common":
                valid = valid_mon and bool((self.common_var.get() or "").strip())
            elif cat == "Experience":
                valid = valid_mon and bool((self.exp_var.get() or "").strip())
            elif cat == "Accuracy":
                t_ok = bool((self.acc_var.get() or "").strip())
                try:
                    int(self.acc_boost.get().strip() or "5")
                    b_ok = True
                except Exception:
                    b_ok = False
                valid = valid_mon and t_ok and b_ok
            elif cat == "Berries":
                valid = valid_mon and bool((self.berry_var.get() or "").strip())
            elif cat == "Vitamins":
                valid = valid_mon and bool((self.stat_var.get() or "").strip())
            elif cat == "Type Booster":
                valid = valid_mon and bool((self.type_var.get() or "").strip())
            elif cat == "Mint":
                valid = valid_mon and bool((self.nature_var.get() or "").strip())
            # No separate 'Observed' category
        try:
            self.btn_add.configure(state=(tk.NORMAL if valid else tk.DISABLED))
        except Exception:
            pass


    def _load_pokeball_data(self):
        """Load Pokéball data from the save file."""
        try:
            # Load Pokéball catalog for ID mapping
            from rogueeditor.catalog import load_pokeball_catalog
            ball_n2i, ball_i2n = load_pokeball_catalog()
            
            # Get pokeballCounts from save file (correct structure)
            pokeball_counts = self.data.get("pokeballCounts", {})
            
            # Map numeric IDs to our UI keys (only available types)
            id_to_key = {
                "0": "pokeball",      # POKEBALL
                "1": "greatball",     # GREAT_BALL  
                "2": "ultraball",     # ULTRA_BALL
                "3": "rogueball",     # ROGUE_BALL
                "4": "masterball"     # MASTER_BALL
            }
            
            # Load counts from save file
            for name, key in self.pokeball_types:
                # Find the numeric ID for this Pokéball type
                ball_id = None
                for num_id, ball_key in id_to_key.items():
                    if ball_key == key:
                        ball_id = num_id
                        break
                
                if ball_id is not None:
                    count = pokeball_counts.get(ball_id, 0)
                    self.pokeball_vars[key].set(str(count))
                else:
                    self.pokeball_vars[key].set("0")
                    
        except Exception as e:
            print(f"Error loading Pokéball data: {e}")
            # Set defaults on error
            for name, key in self.pokeball_types:
                self.pokeball_vars[key].set("0")

    def _on_money_change(self):
        """Handle money field changes and update data automatically."""
        try:
            # Update money in data immediately
            money_str = (self.money_var.get() or "").strip()
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
            print(f"Error handling money change: {e}")

    def _on_pokeball_change(self):
        """Handle Pokéball field changes and update data automatically."""
        try:
            # Update Pokéball data immediately
            self._save_pokeball_data()
            
            # Mark as dirty and update buttons
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
        except Exception as e:
            print(f"Error handling Pokéball change: {e}")

    def _create_tooltip_method(self, widget, text):
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
            print(f"Error creating tooltip: {e}")

    def _save_pokeball_data(self):
        """Save Pokéball data to the save file."""
        try:
            # Initialize pokeballCounts if not present
            if "pokeballCounts" not in self.data:
                self.data["pokeballCounts"] = {}
            
            # Map UI keys to numeric IDs (only available types)
            key_to_id = {
                "pokeball": "0",      # POKEBALL
                "greatball": "1",     # GREAT_BALL  
                "ultraball": "2",     # ULTRA_BALL
                "rogueball": "3",     # ROGUE_BALL
                "masterball": "4"     # MASTER_BALL
            }
            
            # Update Pokéball data from UI (only available types 0-4)
            for name, key in self.pokeball_types:
                try:
                    count = int(self.pokeball_vars[key].get() or "0")
                    if count < 0:
                        count = 0
                    
                    # Map to numeric ID for server compatibility
                    ball_id = key_to_id.get(key)
                    if ball_id is not None:
                        self.data["pokeballCounts"][ball_id] = count
                except ValueError:
                    ball_id = key_to_id.get(key)
                    if ball_id is not None:
                        self.data["pokeballCounts"][ball_id] = 0
            
            # Remove any unavailable types (like type 5) from the data
            available_ids = set(key_to_id.values())
            pokeball_counts = self.data.get("pokeballCounts", {})
            for ball_id in list(pokeball_counts.keys()):
                if ball_id not in available_ids:
                    del self.data["pokeballCounts"][ball_id]
            
            # Remove the incorrect "pokeballs" structure if it exists
            if "pokeballs" in self.data:
                del self.data["pokeballs"]
            
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
        except Exception as e:
            print(f"Error saving Pokéball data: {e}")

    def _init_pokemon_specific_forms(self):
        """Initialize Pokémon-specific form change items mapping."""
        # Map Pokémon species IDs to their specific form change items
        self.pokemon_specific_forms = {
            # Arceus (species ID 493) - Plates
            493: {
                "items": ["FLAME_PLATE", "SPLASH_PLATE", "ZAP_PLATE", "MEADOW_PLATE", "ICICLE_PLATE", "FIST_PLATE",
                         "TOXIC_PLATE", "EARTH_PLATE", "SKY_PLATE", "MIND_PLATE", "INSECT_PLATE", "STONE_PLATE",
                         "SPOOKY_PLATE", "DRACO_PLATE", "DREAD_PLATE", "IRON_PLATE", "PIXIE_PLATE"],
                "category_name": "Arceus Plates",
                "emoji": "🏺"
            },
            # Type: Null/Silvally (species ID 772) - Memory Discs
            772: {
                "items": ["FIRE_MEMORY", "WATER_MEMORY", "ELECTRIC_MEMORY", "GRASS_MEMORY", "ICE_MEMORY", "FIGHTING_MEMORY",
                         "POISON_MEMORY", "GROUND_MEMORY", "FLYING_MEMORY", "PSYCHIC_MEMORY", "BUG_MEMORY", "ROCK_MEMORY",
                         "GHOST_MEMORY", "DRAGON_MEMORY", "DARK_MEMORY", "STEEL_MEMORY", "FAIRY_MEMORY"],
                "category_name": "Silvally Memories",
                "emoji": "💾"
            },
            # Add more Pokémon-specific rare form change items as discovered
            # Example: Mega Rayquaza (species ID 384) - could have specific items
            # 384: {
            #     "items": ["MEGA_RAYQUAZA_ITEM"],
            #     "category_name": "Mega Rayquaza Items",
            #     "emoji": "🐉"
            # }
        }
        
        # Create reverse mapping for quick lookup
        self.form_item_to_pokemon = {}
        for pokemon_id, data in self.pokemon_specific_forms.items():
            for item in data["items"]:
                self.form_item_to_pokemon[item] = pokemon_id

    def _get_pokemon_specific_form_items(self, pokemon_id: int) -> list[str]:
        """Get form change items specific to a Pokémon species."""
        if pokemon_id in self.pokemon_specific_forms:
            return self.pokemon_specific_forms[pokemon_id]["items"]
        return []

    def _get_pokemon_specific_rare_form_items(self, pokemon_id: int) -> list[str]:
        """Get rare form change items specific to a Pokémon species."""
        # This method can be extended to return Pokémon-specific rare form change items
        # For now, return empty list, but this is where we'd add items like:
        # - Mega Rayquaza specific items
        # - Primal Groudon/Kyogre items
        # - Other legendary-specific form change items
        return []

    def _should_show_rare_form_change_item(self, pokemon_id: int) -> bool:
        """Check if RARE_FORM_CHANGE_ITEM should be shown for a specific Pokémon."""
        # Show RARE_FORM_CHANGE_ITEM for Pokémon that have specific rare form change items
        # or for Pokémon that are known to have alternative forms
        return (
            pokemon_id in self.pokemon_specific_forms or
            len(self._get_pokemon_specific_rare_form_items(pokemon_id)) > 0 or
            # Add more conditions for Pokémon with alternative forms
            pokemon_id in [3, 9, 130, 384, 428, 445, 448, 460]  # Known Mega/G-Max Pokémon
        )

    def _get_alternative_forms_for_pokemon(self, pokemon_id: int) -> dict:
        """Get all alternative forms available for a specific Pokémon."""
        try:
            species = self._get_pokemon_species(pokemon_id)
            
            # Define alternative forms by type
            alternative_forms = {
                # Mega Evolutions
                "mega": {
                    3: {"form_id": 48, "name": "Mega Venusaur", "description": "Mega Evolution"},
                    130: {"form_id": 22, "name": "Mega Gyarados", "description": "Mega Evolution"},
                    # Add more Mega forms as discovered
                },
                # G-Max Forms
                "gmax": {
                    9: {"form_id": 56, "name": "G-Max Blastoise", "description": "Gigantamax Form"},
                    # Add more G-Max forms as discovered
                },
                # Other special forms (Deoxys, Kyurem, etc.)
                "special": {
                    # Add special forms as discovered
                }
            }
            
            # Return forms available for this Pokémon
            available_forms = {}
            for form_type, forms in alternative_forms.items():
                if species in forms:
                    available_forms[form_type] = forms[species]
            
            return available_forms
        except Exception:
            return {}

    def _get_form_change_items_for_pokemon(self, pokemon_id: int) -> list[str]:
        """Get all form change items available for a specific Pokémon."""
        try:
            species = self._get_pokemon_species(pokemon_id)
            form_items = []
            
            # Get Pokémon-specific form items (Arceus Plates, Silvally Memories, etc.)
            pokemon_specific = self._get_pokemon_specific_form_items(species)
            form_items.extend(pokemon_specific)
            
            # Get alternative forms for this Pokémon
            alternative_forms = self._get_alternative_forms_for_pokemon(species)
            
            # Add RARE_FORM_CHANGE_ITEM if this Pokémon has alternative forms
            if alternative_forms:
                form_items.append("RARE_FORM_CHANGE_ITEM")
            
            # Always add generic form change item as fallback for any Pokémon
            form_items.append("GENERIC_FORM_CHANGE_ITEM")
            
            return form_items
        except Exception:
            return ["GENERIC_FORM_CHANGE_ITEM"]  # Fallback to generic item

    def _is_pokemon_specific_form_item(self, item_id: str) -> bool:
        """Check if an item is a Pokémon-specific form change item."""
        return item_id in self.form_item_to_pokemon

    def _get_pokemon_for_form_item(self, item_id: str) -> int:
        """Get the Pokémon species ID for a specific form change item."""
        return self.form_item_to_pokemon.get(item_id, None)

    def _get_item_emoji(self, item_id: str) -> str:
        """Get emoji for a common item."""
        emoji_map = {
            "FOCUS_BAND": "🎗",
            "MYSTICAL_ROCK": "🪨",
            "SOOTHE_BELL": "🔔",
            "LEEK": "🥬",
            "EVIOLITE": "💎",
            "SOUL_DEW": "💎",
            "GOLDEN_PUNCH": "👊",
            "GRIP_CLAW": "🦀",
            "QUICK_CLAW": "⚡",
            "KINGS_ROCK": "👑",
            "LEFTOVERS": "🍖",
            "SHELL_BELL": "🐚",
            "TOXIC_ORB": "☠️",
            "FLAME_ORB": "🔥",
            "BATON": "🏃",
            "LUCKY_EGG": "🥚",
            "GOLDEN_EGG": "🥚",
            "RARE_FORM_CHANGE_ITEM": "🔄",
            "GENERIC_FORM_CHANGE_ITEM": "⚙️",
            "MULTI_LENS": "🔀",
            "MAP": "🗺",
            "WIDE_LENS": "🎯",
            "SCOPE_LENS": "🔍",
            # Temp Battle Items
            "X_ATTACK": "⚔️",
            "X_DEFENSE": "🛡",
            "X_SP_ATTACK": "💫",
            "X_SP_DEFENSE": "🔮",
            "X_SPEED": "💨",
            "X_ACCURACY": "🎯",
            "DIRE_HIT": "💥",
            "LURE": "🎣",
            "SUPER_LURE": "🎣",
            "MAX_LURE": "🎣",
            # Trainer Items
            "EXP_CHARM": "⭐",
            "SUPER_EXP_CHARM": "⭐",
            "EXP_SHARE": "⭐",
            "IV_SCANNER": "🔍",
            "AMULET_COIN": "💰",
            "GOLDEN_POKEBALL": "⚪",
            "MEGA_BRACELET": "💎",
            "TERA_ORB": "💎",
            "DYNAMAX_BAND": "💎",
            "SHINY_CHARM": "✨",
            "ABILITY_CHARM": "🔮",
            "CATCHING_CHARM": "🎣",
            "NUGGET": "💰",
            "BIG_NUGGET": "💰",
            "RELIC_GOLD": "💰",
            "COIN_CASE": "💰",
            "LOCK_CAPSULE": "🔒",
            "BERRY_POUCH": "🍓",
            "HEALING_CHARM": "❤️",
            "CANDY_JAR": "🍬",
        }
        return emoji_map.get(item_id, "📦")

    def _get_item_description(self, item_id: str) -> str:
        """Get description for a common item."""
        description_map = {
            "FOCUS_BAND": "Survive Fatal",
            "MYSTICAL_ROCK": "Weather Extend",
            "SOOTHE_BELL": "Friendship Boost",
            "LEEK": "Crit Boost",
            "EVIOLITE": "Pre-Evo Boost",
            "SOUL_DEW": "Nature Boost",
            "GOLDEN_PUNCH": "Money Reward",
            "GRIP_CLAW": "Trap Effect",
            "QUICK_CLAW": "Speed Priority",
            "KINGS_ROCK": "Flinch Chance",
            "LEFTOVERS": "Turn Heal",
            "SHELL_BELL": "Hit Heal",
            "TOXIC_ORB": "Toxic Status",
            "FLAME_ORB": "Burn Status",
            "BATON": "Switch Item",
            "LUCKY_EGG": "Exp Boost",
            "GOLDEN_EGG": "Super Exp Boost",
            "RARE_FORM_CHANGE_ITEM": "Form Change",
            "GENERIC_FORM_CHANGE_ITEM": "Custom Form",
            "MULTI_LENS": "Multi-Hit",
            "MAP": "Choose Next Destinations",
            "WIDE_LENS": "Accuracy Boost",
            "SCOPE_LENS": "Critical Hit",
            # Temp Battle Items
            "X_ATTACK": "Attack Boost",
            "X_DEFENSE": "Defense Boost",
            "X_SP_ATTACK": "Sp. Attack Boost",
            "X_SP_DEFENSE": "Sp. Defense Boost",
            "X_SPEED": "Speed Boost",
            "X_ACCURACY": "Accuracy Boost",
            "DIRE_HIT": "Critical Hit",
            "LURE": "Encounter Rate",
            "SUPER_LURE": "Super Encounter",
            "MAX_LURE": "Max Encounter",
            # Trainer Items
            "EXP_CHARM": "Exp Boost",
            "SUPER_EXP_CHARM": "Super Exp Boost",
            "EXP_SHARE": "20% Exp per Party Member (Max 100%)",
            "IV_SCANNER": "IV Scanner",
            "AMULET_COIN": "Money Multiplier",
            "GOLDEN_POKEBALL": "Golden Pokéball",
            "MEGA_BRACELET": "Mega Evolution",
            "TERA_ORB": "Terastallize",
            "DYNAMAX_BAND": "Gigantamax",
            "SHINY_CHARM": "Shiny Rate",
            "ABILITY_CHARM": "Ability Rate",
            "CATCHING_CHARM": "Catch Rate",
            "NUGGET": "Money Value",
            "BIG_NUGGET": "Big Money",
            "RELIC_GOLD": "Relic Gold",
            "COIN_CASE": "Coin Storage",
            "LOCK_CAPSULE": "Lock Capsule",
            "BERRY_POUCH": "Berry Storage",
            "HEALING_CHARM": "Healing Boost",
            "CANDY_JAR": "Candy Storage",
        }
        return description_map.get(item_id, "Held Item")

    def _vitamin_stat_values(self) -> list[str]:
        # Map stat ids to mainstream vitamin names
        # ids: 0 HP, 1 Atk, 2 Def, 3 SpAtk, 4 SpDef, 5 Spd
        names = {
            0: "HP Up",
            1: "Protein",
            2: "Iron",
            3: "Calcium",
            4: "Zinc",
            5: "Carbos",
        }
        stat_labels = {
            0: "HP",
            1: "Atk",
            2: "Def",
            3: "Sp. Atk",
            4: "Sp. Def",
            5: "Spd",
        }
        out = []
        for n, sid in sorted((getattr(self, '_stat_name_to_id', {}) or {}).items(), key=lambda kv: kv[1]):
            if sid in names:
                stat_lbl = stat_labels.get(sid, str(sid))
                out.append(f"{names[sid]} [{stat_lbl}] ({sid})")
        return out

    def _xitem_stat_values(self) -> list[str]:
        # Map temp battle stats to X-items; include ACC
        # ids: 1 Atk, 2 Def, 3 SpAtk, 4 SpDef, 5 Spd, 6 Acc
        names = {
            1: "X Attack",
            2: "X Defense",
            3: "X Sp. Atk",
            4: "X Sp. Def",
            5: "X Speed",
            6: "X Accuracy",
        }
        out = []
        for n, sid in sorted((getattr(self, '_stat_name_to_id', {}) or {}).items(), key=lambda kv: kv[1]):
            if sid in names:
                out.append(f"{names[sid]} ({sid})")
        return out

    def _augment_player_types_from_tmp(self) -> list[str]:
        # Try to discover requested player item types from TmpServerFiles/GameData/modifier-type.ts
        wanted = {
            # Existing modifiers
            "LURE",
            "SUPER_LURE",
            "MAX_LURE",
            "AMULET_COIN",
            "MEGA_BRACELET",
            "TERA_ORB",
            "DYNAMAX_BAND",
            # New trainer-level modifiers from modifier-type.ts
            "CANDY_JAR",
            "BERRY_POUCH",
            "EXP_SHARE",
            "HEALING_CHARM",
            "SHINY_CHARM",
            "OVAL_CHARM",
            "CATCHING_CHARM",
            "IV_SCANNER",
            "MAP",
            "LOCK_CAPSULE",
            "GOLDEN_POKEBALL",
        }
        paths = [
            os.path.normpath(os.path.join(os.getcwd(), "TmpServerFiles", "GameData", "1", "modifier-type.ts")),
            os.path.normpath(os.path.join(os.getcwd(), "TmpServerFiles", "GameData", "modifier-type.ts")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "TmpServerFiles", "GameData", "1", "modifier-type.ts")),
        ]
        found: set[str] = set()
        for p in paths:
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        txt = f.read()
                    for name in list(wanted):
                        if (name + ":") in txt or ("ModifierType." + name) in txt:
                            found.add(name)
            except Exception:
                continue
        return sorted(list(found))

    def _handle_duplicate_modifier(self, new_entry: dict) -> bool:
        """Check for duplicate modifiers and handle appropriately. Returns True if should proceed."""
        try:
            mods = self.data.get("modifiers", [])
            type_id = new_entry.get("typeId")
            if not type_id:
                return True

            # Define non-stackable modifier types (only one instance allowed)
            non_stackable_types = {
                # Core non-stackable items
                "IV_SCANNER", "MAP", "MEGA_BRACELET", "TERA_ORB", "DYNAMAX_BAND",
                "EXP_SHARE", "CANDY_JAR", "LOCK_CAPSULE",
                # New non-stackable items from modifier-type.ts
                "BERRY_POUCH", "HEALING_CHARM", "SHINY_CHARM", "OVAL_CHARM",
                "CATCHING_CHARM", "GOLDEN_POKEBALL"
            }

            # Check for existing modifiers of the same type
            existing_idx = None
            for i, mod in enumerate(mods):
                if not isinstance(mod, dict):
                    continue
                if mod.get("typeId") == type_id:
                    # For Pokemon-specific modifiers, check if same Pokemon
                    new_args = new_entry.get("args", [])
                    mod_args = mod.get("args", [])

                    # Special handling for BASE_STAT_BOOSTER - check both Pokemon ID and stat ID
                    if type_id == "BASE_STAT_BOOSTER":
                        if (new_args and mod_args and len(new_args) >= 2 and len(mod_args) >= 2 and
                            isinstance(new_args[0], int) and isinstance(mod_args[0], int) and
                            isinstance(new_args[1], int) and isinstance(mod_args[1], int) and
                            new_args[0] > 1000000 and mod_args[0] > 1000000):  # Pokemon IDs are large
                            if new_args[0] == mod_args[0] and new_args[1] == mod_args[1]:  # Same Pokemon AND same stat
                                existing_idx = i
                                break
                    # Special handling for BERRY - check both Pokemon ID and berry ID
                    elif type_id == "BERRY":
                        if (new_args and mod_args and len(new_args) >= 2 and len(mod_args) >= 2 and
                            isinstance(new_args[0], int) and isinstance(mod_args[0], int) and
                            isinstance(new_args[1], int) and isinstance(mod_args[1], int) and
                            new_args[0] > 1000000 and mod_args[0] > 1000000):  # Pokemon IDs are large
                            if new_args[0] == mod_args[0] and new_args[1] == mod_args[1]:  # Same Pokemon AND same berry
                                existing_idx = i
                                break
                    # For other Pokemon-specific modifiers, check if same Pokemon
                    elif (new_args and mod_args and
                        isinstance(new_args[0], int) and isinstance(mod_args[0], int) and
                        new_args[0] > 1000000 and mod_args[0] > 1000000):  # Pokemon IDs are large
                        if new_args[0] == mod_args[0]:  # Same Pokemon
                            existing_idx = i
                            break
                    elif type_id in non_stackable_types:  # Trainer-wide non-stackable
                        existing_idx = i
                        break
                    elif not new_args and not mod_args:  # Both are trainer modifiers with no args
                        existing_idx = i
                        break

            if existing_idx is not None:
                existing_mod = mods[existing_idx]
                existing_stacks = existing_mod.get("stackCount", 1)
                new_stacks = new_entry.get("stackCount", 1)

                if type_id in non_stackable_types:
                    messagebox.showwarning(
                        "Duplicate Modifier",
                        f"{type_id} can only have one instance. The existing one will be replaced."
                    )
                    # Replace the existing modifier
                    mods[existing_idx] = new_entry
                    return False  # Don't append, we replaced
                else:
                    # Ask user if they want to stack or replace
                    if type_id == "BASE_STAT_BOOSTER" and len(new_args) >= 2:
                        # More specific message for stat boosters using vitamin names
                        vitamin_names = {
                            0: "HP Up", 1: "Protein", 2: "Iron", 3: "Calcium", 4: "Zinc", 5: "Carbos"
                        }
                        vitamin_name = vitamin_names.get(new_args[1], f"Vitamin {new_args[1]}")
                        message = f"{vitamin_name} already exists with {existing_stacks} stacks.\n\n"
                    else:
                        message = f"{type_id} already exists with {existing_stacks} stacks.\n\n"
                    
                    result = messagebox.askyesnocancel(
                        "Existing Modifier Found",
                        message +
                        f"Yes: Add {new_stacks} more stacks (total: {existing_stacks + new_stacks})\n"
                        f"No: Replace with {new_stacks} stacks\n"
                        f"Cancel: Keep existing unchanged"
                    )

                    if result is None:  # Cancel
                        return False
                    elif result:  # Yes - stack
                        mods[existing_idx]["stackCount"] = existing_stacks + new_stacks
                        return False  # Don't append, we modified existing
                    else:  # No - replace
                        mods[existing_idx] = new_entry
                        return False  # Don't append, we replaced

            return True  # No duplicates, proceed normally

        except Exception as e:
            print(f"Error checking duplicates: {e}")
            return True  # On error, proceed normally

    def _remove_selected(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith("["):
            return
        try:
            idx = int(sel.split("]", 1)[0][1:])
        except Exception:
            return
        if messagebox.askyesno("Confirm", f"Remove modifier index {idx}?"):
            ok = self.editor.remove_modifier_by_index(self.slot, idx)
            if ok:
                # Reflect removal locally and mark dirty
                mods = self.data.get("modifiers") or []
                if 0 <= idx < len(mods):
                    del mods[idx]
                    self.data["modifiers"] = mods
                self._dirty_server = True
                self._update_button_states()
                self._refresh_mods()
            else:
                messagebox.showwarning("Failed", "Unable to remove modifier")

    def _show_selected_detail(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith("["):
            return
        try:
            idx = int(sel.split("]", 1)[0][1:])
        except Exception:
            return
        mods = self.data.get("modifiers") or []
        if 0 <= idx < len(mods):
            import json as _json

            content = _json.dumps(mods[idx], ensure_ascii=False, indent=2)
            self.master._show_text_dialog(f"Modifier Detail [{idx}]", content)

    def _add(self):
        target = self.target_var.get()
        mon = self._current_mon()
        mon_id = mon.get("id") if mon else None
        cat = self.cat_var.get()
        entry: dict | None = None
        try:
            stacks = int((self.stack_var.get() or "1").strip())
            if stacks < 0:
                stacks = 0
        except Exception:
            stacks = 1
        if cat == "Temp Battle Modifiers":
            # Handle X-items, DIRE_HIT, and LUREs with [5, 5] pattern (max duration, waves remaining)
            sel = (self.temp_battle_var.get() or "").strip()
            if not sel:
                messagebox.showwarning("Invalid", "Select a temp battle modifier")
                return

            # Extract ID from formatted string "Display Name (ID)"
            item_id = None
            if sel.endswith(")") and "(" in sel:
                try:
                    item_id = sel.rsplit("(", 1)[1].rstrip(")")
                except Exception:
                    pass
            
            if not item_id:
                messagebox.showwarning("Invalid", "Invalid temp battle modifier format")
                return

            if item_id.isdigit():
                # X-items: extract stat ID and create TEMP_STAT_STAGE_BOOSTER
                try:
                    sid = int(item_id)
                    # TEMP_STAT_STAGE_BOOSTER: args=[stat_id, 5, 5], typePregenArgs=[stat_id] - using 5,5 pattern
                    entry = {"args": [sid, 5, 5], "player": True, "stackCount": stacks, "typeId": "TEMP_STAT_STAGE_BOOSTER", "typePregenArgs": [sid], "className": "TempStatStageBoosterModifier"}
                except Exception:
                    messagebox.showwarning("Invalid", "Could not parse stat ID from selection")
                    return
            elif item_id in {"LURE", "SUPER_LURE", "MAX_LURE"}:
                # LUREs: args=[duration, waves_remaining] pattern
                if item_id == "LURE":
                    duration = 10
                elif item_id == "SUPER_LURE":
                    duration = 15
                else:  # MAX_LURE
                    duration = 30
                entry = {"args": [duration, duration], "player": True, "stackCount": stacks, "typeId": item_id, "className": "DoubleBattleChanceBoosterModifier"}
            elif item_id == "DIRE_HIT":
                # DIRE_HIT: args=[max_duration, remaining_waves] pattern
                entry = {"args": [5, 5], "player": True, "stackCount": stacks, "typeId": item_id, "className": "TempStatStageBoosterModifier"}
            else:
                messagebox.showwarning("Invalid", f"Unknown temp battle modifier: {sel}")
                return
        elif cat == "Trainer EXP Charms":
            sel = (self.player_type_var.get() or "").strip()
            t = _extract_id_from_formatted_string(sel).upper()
            if t not in {"EXP_CHARM", "SUPER_EXP_CHARM"}:
                messagebox.showwarning("Invalid", "Select EXP_CHARM or SUPER_EXP_CHARM")
                return
            amt = 25 if t == "EXP_CHARM" else 60
            entry = {"args": [amt], "player": True, "stackCount": stacks, "typeId": t, "className": "ExpBoosterModifier"}
        elif cat == "Trainer" or target == "Trainer":
            sel = (self.player_type_var.get() or "").strip()
            t = _extract_id_from_formatted_string(sel).upper()
            if not t:
                return
            # Parse args as comma separated ints
            s = (self.player_args_var.get() or "").strip()
            args = None
            if s:
                try:
                    args = [int(x.strip()) for x in s.split(",") if x.strip()]
                except Exception:
                    args = None
            entry = {"args": args, "player": True, "stackCount": stacks, "typeId": t}
            # Optional className mapping for known trainer modifiers
            class_map = {
                # EXP & session-wide tools
                "EXP_CHARM": "ExpBoosterModifier",
                "SUPER_EXP_CHARM": "ExpBoosterModifier",
                "EXP_SHARE": "ExpShareModifier",
                "IV_SCANNER": "IvScannerModifier",
                "MAP": "MapModifier",
                # Encounters & currencies
                "AMULET_COIN": "MoneyMultiplierModifier",
                "GOLDEN_POKEBALL": "ExtraModifierModifier",
                "SHINY_CHARM": "ShinyRateBoosterModifier",
                "ABILITY_CHARM": "HiddenAbilityRateBoosterModifier",
                "CATCHING_CHARM": "CriticalCatchChanceBoosterModifier",
                "NUGGET": "MoneyRewardModifier",
                "BIG_NUGGET": "MoneyRewardModifier",
                "RELIC_GOLD": "MoneyRewardModifier",
                "COIN_CASE": "MoneyInterestModifier",
                "LOCK_CAPSULE": "LockModifierTiersModifier",
                "BERRY_POUCH": "PreserveBerryModifier",
                "HEALING_CHARM": "HealingBoosterModifier",
                "CANDY_JAR": "LevelIncrementBoosterModifier",
                # Access items
                "MEGA_BRACELET": "MegaEvolutionAccessModifier",
                "TERA_ORB": "TerastallizeAccessModifier",
                "DYNAMAX_BAND": "GigantamaxAccessModifier",
                # Lures (no args expected)
                "LURE": "DoubleBattleChanceBoosterModifier",
                "SUPER_LURE": "DoubleBattleChanceBoosterModifier",
                "MAX_LURE": "DoubleBattleChanceBoosterModifier",
                # Player temporary stat booster
                "TEMP_STAT_STAGE_BOOSTER": "TempStatStageBoosterModifier",
            }
            cname = class_map.get(t)
            if cname:
                entry["className"] = cname
                # Ensure args are omitted for items that do not expect them
                # Handle items with specific arg patterns - use user-provided args if available
                if t in {"LURE", "SUPER_LURE", "MAX_LURE"} and not args:
                    # Default LURE args if user didn't provide custom ones
                    if t == "LURE":
                        entry["args"] = [10, 10]  # max_turns, remaining_turns
                    elif t == "SUPER_LURE":
                        entry["args"] = [15, 15]
                    elif t == "MAX_LURE":
                        entry["args"] = [30, 30]
                elif t == "DIRE_HIT" and not args:
                    # DIRE_HIT: critical hit booster, args=[5, 5] pattern from save analysis
                    entry["args"] = [5, 5]
                elif t == "HEALING_CHARM" and not args:
                    # HEALING_CHARM: args=[multiplier] - 10% boost
                    entry["args"] = [1.1]
                elif t in {"MAP", "AMULET_COIN", "GOLDEN_POKEBALL", "MEGA_BRACELET", "TERA_ORB", "DYNAMAX_BAND", "EXP_SHARE", "IV_SCANNER", "SHINY_CHARM", "ABILITY_CHARM", "CATCHING_CHARM", "NUGGET", "BIG_NUGGET", "RELIC_GOLD", "COIN_CASE", "LOCK_CAPSULE", "BERRY_POUCH", "CANDY_JAR"}:
                    entry["args"] = None
                # EXP charms need numeric amounts if not provided
                if t in {"EXP_CHARM", "SUPER_EXP_CHARM"}:
                    if not isinstance(entry.get("args"), list) or not entry["args"]:
                        entry["args"] = [25 if t == "EXP_CHARM" else 60]
                # Temp stat stage booster requires stat via typePregenArgs
                if t == "TEMP_STAT_STAGE_BOOSTER":
                    # Read stat selection (can be like "Attack (1)")
                    sel = (self.stat_var.get() or "").strip()
                    sid = None
                    if sel.endswith(")") and "(" in sel:
                        try:
                            sid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                        except Exception:
                            sid = None
                    if not isinstance(sid, int):
                        try:
                            from rogueeditor.catalog import load_stat_catalog
                            n2i, _ = load_stat_catalog()
                            key = sel.lower().replace(" ", "_")
                            sid = n2i.get(key)
                        except Exception:
                            sid = None
                    if isinstance(sid, int):
                        entry["typePregenArgs"] = [sid]
                        # Pattern from save analysis: args=[stat_id, 5, 3]
                        entry["args"] = [sid, 5, 3]
        elif cat == "Common":
            sel = (self.common_var.get() or "").strip()
            if not sel:
                return
            # Extract item ID from formatted string "Display Name (ID)"
            t = None
        elif cat == "Experience":
            sel = (self.exp_var.get() or "").strip()
            if not sel:
                return
            # Extract item ID from formatted string "Display Name (ID)"
            t = None
            if sel.endswith(")") and "(" in sel:
                try:
                    t = sel.rsplit("(", 1)[1].rstrip(")").upper()
                except Exception:
                    pass
            if not t:
                return
            # Experience items are simple - just the item ID
            entry = {"args": [mon_id], "typePregenArgs": [], "player": True, "stackCount": stacks, "typeId": t}
            # Map to appropriate class
            exp_class_map = {
                "LUCKY_EGG": "PokemonExpBoosterModifier",
                "GOLDEN_EGG": "PokemonExpBoosterModifier",
            }
            cname = exp_class_map.get(t)
            if cname:
                entry["className"] = cname
        elif cat == "Accuracy":
            sel = (self.acc_var.get() or "").strip()
            if not sel:
                return
            # Extract item ID from formatted string "Display Name (ID)"
            t = None
            if sel.endswith(")") and "(" in sel:
                try:
                    t = sel.rsplit("(", 1)[1].rstrip(")").upper()
                except Exception:
                    pass
            if not t:
                return
            if t == "WIDE_LENS":
                try:
                    boost = int(self.acc_boost.get().strip() or "5")
                except ValueError:
                    boost = 5
                entry = {
                    "args": [mon_id, boost],
                    "player": True,
                    "stackCount": stacks,
                    "typeId": t,
                    "className": "PokemonMoveAccuracyBoosterModifier",
                }
            elif t == "MULTI_LENS":
                entry = {
                    "args": [mon_id],
                    "player": True,
                    "stackCount": stacks,
                    "typeId": t,
                    "className": "PokemonMultiHitModifier",
                }
            else:
                # Unknown accuracy type; fallback to mon-only arg
                entry = {"args": [mon_id], "player": True, "stackCount": stacks, "typeId": t}
        elif cat == "Berries":
            sel = (self.berry_var.get() or "").strip()
            bid = None
            if sel.endswith(")") and "(" in sel:
                try:
                    bid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                except Exception:
                    bid = None
            if bid is None:
                from rogueeditor.catalog import load_berry_catalog

                n2i, _ = load_berry_catalog()
                key = sel.lower().replace(" ", "_")
                bid = n2i.get(key)
            if not isinstance(bid, int):
                messagebox.showwarning("Invalid", "Select a berry")
                return
            entry = {
                "args": [mon_id, bid],
                "player": True,
                "stackCount": stacks,
                "typeId": "BERRY",
                "typePregenArgs": [bid],
                "className": "BerryModifier",
            }
        elif cat == "Vitamins":
            sel = (self.stat_var.get() or "").strip()
            sid = None
            if sel.endswith(")") and "(" in sel:
                try:
                    sid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                except Exception:
                    sid = None
            if not isinstance(sid, int):
                from rogueeditor.catalog import load_stat_catalog

                n2i, _ = load_stat_catalog()
                key = sel.lower().replace(" ", "_")
                sid = n2i.get(key)
            if not isinstance(sid, int):
                messagebox.showwarning("Invalid", "Select a stat")
                return
            entry = {
                "args": [mon_id, sid],
                "player": True,
                "stackCount": stacks,
                "typeId": "BASE_STAT_BOOSTER",
                "typePregenArgs": [sid],
                "className": "BaseStatModifier",
            }
        elif cat == "Type Booster":
            # Attack Type Booster for a mon; requires type pregen arg
            sel = (self.type_var.get() or "").strip()
            tid = None
            if sel.endswith(")") and "(" in sel:
                try:
                    tid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                except Exception:
                    tid = None
            if not isinstance(tid, int):
                key = sel.lower().strip()
                tid = self._type_name_to_id.get(key)
            if not isinstance(tid, int):
                messagebox.showwarning("Invalid", "Select a type")
                return
            entry = {
                "args": [mon_id],
                "player": True,
                "stackCount": stacks,
                "typeId": "ATTACK_TYPE_BOOSTER",
                "typePregenArgs": [tid],
                "className": "AttackTypeBoosterModifier",
            }
        elif cat == "Mint":
            # Nature change for a mon; requires nature pregen arg
            sel = (self.nature_var.get() or "").strip()
            nid = None
            if sel.endswith(")") and "(" in sel:
                try:
                    nid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                except Exception:
                    nid = None
            if not isinstance(nid, int):
                try:
                    _n2i, _ = load_nature_catalog()
                    key = sel.lower().replace(" ", "_")
                    nid = _n2i.get(key)
                except Exception:
                    nid = None
            if not isinstance(nid, int):
                messagebox.showwarning("Invalid", "Select a nature")
                return
            entry = {
                "args": [mon_id],
                "player": True,
                "stackCount": stacks,
                "typeId": "MINT",
                "typePregenArgs": [nid],
                "className": "PokemonNatureChangeModifier",
            }
        else:
            # No other categories
            return
        if not entry:
            return

        # Check for duplicates and handle appropriately
        if not self._handle_duplicate_modifier(entry):
            return  # User cancelled or duplicate prevented

        mods = self.data.setdefault("modifiers", [])
        mods.append(entry)
        # Mark dirty and update UI (single add per submission)
        try:
            self._dirty_local = True
            self._dirty_server = True
        except Exception:
            pass
        self._refresh_mods()
        try:
            self.btn_save.configure(state=tk.NORMAL)
            self.btn_upload.configure(state=tk.NORMAL)
        except Exception:
            pass

    def _save(self):
        from rogueeditor.utils import slot_save_path, dump_json, safe_dump_json

        # Save Pokéball data before saving
        self._save_pokeball_data()

        p = slot_save_path(self.api.username, self.slot)

        try:
            # Use safe save system with corruption prevention
            success = safe_dump_json(p, self.data, f"item_manager_save_slot_{self.slot}")

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
        if not messagebox.askyesno(
            "Confirm Upload", f"Upload item changes for slot {self.slot} to the server?"
        ):
            return
        try:
            from rogueeditor.utils import slot_save_path, load_json

            p = slot_save_path(self.api.username, self.slot)
            data = load_json(p) if os.path.exists(p) else self.data
            self.api.update_slot(self.slot, data)
            messagebox.showinfo("Uploaded", "Server updated successfully")
            # Refresh snapshot and clear server dirty flag
            try:
                self.data = self.api.get_slot(self.slot)
                self.party = self.data.get("party") or []
                self._dirty_server = False
                self.btn_upload.configure(state=tk.DISABLED)
                if not self._dirty_local:
                    self.btn_save.configure(state=tk.DISABLED)
                self._refresh_mods()
            except Exception:
                pass
            # Optional verification: compare modifiers only
            try:
                if messagebox.askyesno("Verify", "Verify that server modifiers match local changes?"):
                    remote = self.api.get_slot(self.slot)
                    local_mods = (data.get('modifiers') if isinstance(data, dict) else None) or []
                    remote_mods = (remote.get('modifiers') if isinstance(remote, dict) else None) or []
                    ok = (local_mods == remote_mods)
                    if ok:
                        messagebox.showinfo("Verify", "Modifiers match server.")
                    else:
                        import json as _json
                        diff = []
                        diff.append("Local modifiers:\n" + _json.dumps(local_mods, ensure_ascii=False, indent=2))
                        diff.append("\nServer modifiers:\n" + _json.dumps(remote_mods, ensure_ascii=False, indent=2))
                        self.master._show_text_dialog("Verify Modifiers", "\n".join(diff))
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Upload failed", str(e))

    def _edit_selected_stacks(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith("["):
            return
        try:
            idx = int(sel.split("]", 1)[0][1:])
        except Exception:
            return
        top = tk.Toplevel(self)
        top.title(f"Edit Stacks [{idx}]")
        ttk.Label(top, text="stackCount:").grid(row=0, column=0, padx=6, pady=6, sticky=tk.E)
        var = tk.StringVar(value="1")
        ttk.Entry(top, textvariable=var, width=8).grid(row=0, column=1, sticky=tk.W)

        def apply():
            try:
                sc = int(var.get().strip())
            except Exception:
                sc = 1
            if sc < 0:
                sc = 0
            mods = self.data.get("modifiers") or []
            if 0 <= idx < len(mods):
                mods[idx]["stackCount"] = sc
                from rogueeditor.utils import slot_save_path, dump_json, load_json, safe_dump_json

                p = slot_save_path(self.api.username, self.slot)

                # Use safe save system
                try:
                    success = safe_dump_json(p, self.data, f"item_manager_edit_stacks_slot_{self.slot}")
                    if not success:
                        messagebox.showwarning("Save Warning", "Save completed with warnings.")
                except Exception as e:
                    messagebox.showerror("Save Failed", f"Failed to save: {e}\nUsing basic save.")
                    dump_json(p, self.data)

                if messagebox.askyesno("Upload", "Upload changes to server now?"):
                    try:
                        payload = load_json(p)
                        self.api.update_slot(self.slot, payload)
                        messagebox.showinfo("Uploaded", "Server updated.")
                        self._dirty_server = False
                    except Exception as e:
                        messagebox.showerror("Upload failed", str(e))
                        self._dirty_server = True
                else:
                    self._dirty_server = True
                self._refresh_mods()
                self._update_button_states()
            top.destroy()

        ttk.Button(top, text="Apply", command=apply).grid(row=1, column=0, columnspan=2, pady=8)

    def _on_target_change(self):
        # Refresh lists and adjust categories when switching target
        try:
            self._refresh_mods()
            self._on_cat_change()
            # Reload Pokéball data when switching to trainer target
            if self.target_var.get() == "Trainer":
                self._load_pokeball_data()
            self._update_button_states()
        except Exception:
            pass

    def _format_modifier_display(self, modifier: dict, index: int, is_trainer: bool) -> str:
        """Format modifier for clear display in the list."""
        try:
            type_id = modifier.get("typeId", "UNKNOWN")
            args = modifier.get("args", [])
            stack_count = modifier.get("stackCount", 1)
            type_pregen_args = modifier.get("typePregenArgs", [])

            # Load catalogs for better display names
            try:
                berry_n2i, berry_i2n = load_berry_catalog()
                type_n2i, type_i2n = load_types_catalog()
            except Exception:
                berry_n2i, berry_i2n = {}, {}
                type_n2i, type_i2n = {}, {}

            # Create detailed description based on modifier type
            # Normalize index to 3-digit format for cleaner display
            index_str = f"{index:03d}"
            
            if type_id == "BERRY":
                if len(args) > 1:
                    berry_id = args[1]
                    berry_name_raw = berry_i2n.get(berry_id, f"BERRY_{berry_id}")
                    # Format to Title Case for consistency with dropdown
                    berry_name = berry_name_raw.replace("_", " ").title()
                    # Use consistent berry emoji for all berries
                    return f"[{index_str}] 🍓 {berry_name} x{stack_count}"
                return f"[{index_str}] 🍓 Berry x{stack_count}"

            elif type_id == "BASE_STAT_BOOSTER":
                if len(args) > 1:
                    stat_id = args[1]
                    # Use the same vitamin names as the dropdown
                    vitamin_names = {
                        0: "HP Up",
                        1: "Protein", 
                        2: "Iron",
                        3: "Calcium",
                        4: "Zinc",
                        5: "Carbos",
                    }
                    stat_labels = {
                        0: "HP+",
                        1: "Atk+", 
                        2: "Def+",
                        3: "SpA+",
                        4: "SpD+",
                        5: "Spd+",
                    }
                    vitamin_name = vitamin_names.get(stat_id, f"Vitamin {stat_id}")
                    stat_label = stat_labels.get(stat_id, f"Stat+ {stat_id}")
                    # Use consistent pill emoji for all vitamins
                    return f"[{index_str}] 💊 {vitamin_name} ({stat_label})({stat_id}) x{stack_count}"
                return f"[{index_str}] 💊 Stat Vitamin x{stack_count}"

            elif type_id == "ATTACK_TYPE_BOOSTER":
                if len(args) > 1:
                    type_id_arg = args[1]
                    # Use the existing _format_type_name function for consistent formatting
                    type_name = _format_type_name(type_i2n.get(type_id_arg, f"TYPE_{type_id_arg}"))
                    return f"[{index_str}] ⚔️ {type_name} Type Booster x{stack_count}"
                return f"[{index_str}] ⚔️ Type Booster x{stack_count}"

            elif type_id == "TEMP_STAT_STAGE_BOOSTER":
                if type_pregen_args:
                    stat_id = type_pregen_args[0]
                    stat_names = ["HP", "Attack", "Defense", "Sp. Attack", "Sp. Defense", "Speed"]
                    stat_name = stat_names[stat_id] if 0 <= stat_id < len(stat_names) else f"Stat {stat_id}"
                    
                    # Show duration if args are available (max_duration, remaining_waves)
                    if len(args) >= 3:
                        max_duration, remaining_waves = args[1], args[2]
                        return f"[{index_str}] ⏰ X {stat_name} ({remaining_waves}/{max_duration} waves) x{stack_count}"
                    else:
                        return f"[{index_str}] ⏰ X {stat_name} (Temporary) x{stack_count}"
                return f"[{index_str}] ⏰ X Stat Booster (Temporary) x{stack_count}"

            elif type_id == "DIRE_HIT":
                # Show duration if args are available (max_duration, remaining_waves)
                if len(args) >= 2:
                    max_duration, remaining_waves = args[0], args[1]
                    return f"[{index_str}] 🎯 Dire Hit ({remaining_waves}/{max_duration} waves) x{stack_count}"
                else:
                    return f"[{index_str}] 🎯 Dire Hit (Critical+) x{stack_count}"

            elif type_id == "EXP_CHARM":
                exp_amount = args[0] if args else 25
                total_boost = exp_amount * stack_count
                return f"[{index_str}] ⭐ Exp Charm (+{total_boost}% total) x{stack_count}"

            elif type_id == "SUPER_EXP_CHARM":
                exp_amount = args[0] if args else 60
                total_boost = exp_amount * stack_count
                return f"[{index_str}] ⭐⭐ Super Exp Charm (+{total_boost}% total) x{stack_count}"

            elif type_id == "LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index_str}] 🎣 Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index_str}] 🎣 Lure (10 turns) x{stack_count}"

            elif type_id == "SUPER_LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index_str}] 🎣 Super Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index_str}] 🎣 Super Lure (15 turns) x{stack_count}"

            elif type_id == "MAX_LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index_str}] 🎣 Max Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index_str}] 🎣 Max Lure (30 turns) x{stack_count}"

            elif type_id == "WIDE_LENS":
                if len(args) > 1:
                    accuracy_boost = args[1]
                    return f"[{index_str}] 🎯 Wide Lens (+{accuracy_boost} Accuracy) x{stack_count}"
                return f"[{index_str}] 🎯 Wide Lens (Accuracy+) x{stack_count}"

            elif type_id == "RARE_FORM_CHANGE_ITEM":
                if len(args) > 1:
                    form_id = args[1]
                    # Map form IDs to Pokemon names based on save analysis
                    form_names = {
                        48: "Venusaur",  # Mega Venusaur
                        56: "Blastoise", # Mega Blastoise
                        22: "Gyarados",  # Mega Gyarados
                        # Add more as discovered
                    }
                    form_name = form_names.get(form_id, f"Form {form_id}")

                    # Also show the Pokemon if we can determine it from the first arg
                    pokemon_name = ""
                    if len(args) > 0:
                        try:
                            pokemon_id = args[0]
                            species = self._get_pokemon_species(pokemon_id)
                            pokemon_names = {9: "Blastoise", 130: "Gyarados"}
                            pokemon_name = pokemon_names.get(species, f"Pokemon {species}")
                        except Exception:
                            pass

                    if pokemon_name:
                        return f"[{index_str}] 🔄 {pokemon_name} Form Change (Form {form_id}) x{stack_count}"
                    else:
                        return f"[{index_str}] 🔄 {form_name} Form Change x{stack_count}"
                return f"[{index_str}] 🔄 Form Change Item x{stack_count}"

            elif type_id == "GENERIC_FORM_CHANGE_ITEM":
                if len(args) > 1:
                    form_id = args[1]
                    return f"[{index_str}] ⚙️ Generic Form Change (Form {form_id}) x{stack_count}"
                return f"[{index_str}] ⚙️ Generic Form Change x{stack_count}"

            elif type_id in ["FLAME_PLATE", "SPLASH_PLATE", "ZAP_PLATE", "MEADOW_PLATE", "ICICLE_PLATE", "FIST_PLATE",
                            "TOXIC_PLATE", "EARTH_PLATE", "SKY_PLATE", "MIND_PLATE", "INSECT_PLATE", "STONE_PLATE",
                            "SPOOKY_PLATE", "DRACO_PLATE", "DREAD_PLATE", "IRON_PLATE", "PIXIE_PLATE"]:
                # Arceus Plates - show the plate name and type
                plate_name = _format_item_name(type_id)
                return f"[{index_str}] 🏺 {plate_name} (Arceus Form) x{stack_count}"

            elif type_id in ["FIRE_MEMORY", "WATER_MEMORY", "ELECTRIC_MEMORY", "GRASS_MEMORY", "ICE_MEMORY", "FIGHTING_MEMORY",
                            "POISON_MEMORY", "GROUND_MEMORY", "FLYING_MEMORY", "PSYCHIC_MEMORY", "BUG_MEMORY", "ROCK_MEMORY",
                            "GHOST_MEMORY", "DRAGON_MEMORY", "DARK_MEMORY", "STEEL_MEMORY", "FAIRY_MEMORY"]:
                # Type: Null Memory Discs - show the memory name and type
                memory_name = _format_item_name(type_id)
                return f"[{index_str}] 💾 {memory_name} (Silvally Form) x{stack_count}"

            elif type_id == "LUCKY_EGG":
                if len(args) > 1:
                    exp_boost = args[1]
                    return f"[{index_str}] 🥚 Lucky Egg (+{exp_boost}% Pokemon Exp) x{stack_count}"
                return f"[{index_str}] 🥚 Lucky Egg (Pokemon Exp+) x{stack_count}"

            elif type_id == "LEFTOVERS":
                return f"[{index_str}] 🍖 Leftovers (Turn Heal) x{stack_count}"

            elif type_id == "FOCUS_BAND":
                return f"[{index_str}] 🎗 Focus Band (Survive Fatal) x{stack_count}"

            elif type_id == "EXP_SHARE":
                # EXP_SHARE: 20% per party member, max 100% at 5 stacks
                exp_per_stack = 20
                clamped_stacks = min(stack_count, 5)  # Clamp at max 5 stacks
                total_boost = exp_per_stack * clamped_stacks
                return f"[{index_str}] ⭐ Exp Share (+{total_boost}% Party Exp) x{stack_count}"

            elif type_id == "IV_SCANNER":
                return f"[{index_str}] 🔍 IV Scanner x{stack_count}"

            elif type_id == "MEGA_BRACELET":
                return f"[{index_str}] 💎 Mega Bracelet x{stack_count}"

            elif type_id == "GOLDEN_EGG":
                if len(args) > 1:
                    exp_boost = args[1]
                    return f"[{index_str}] 🥚 Golden Egg (+{exp_boost}% Pokemon Exp) x{stack_count}"
                return f"[{index_str}] 🥚 Golden Egg (Pokemon Exp++) x{stack_count}"

            elif type_id == "SCOPE_LENS":
                return f"[{index_str}] 🎯 Scope Lens (Critical Hit+) x{stack_count}"

            elif type_id == "LEEK":
                return f"[{index_str}] 🥬 Leek (Species Crit+) x{stack_count}"

            elif type_id == "MULTI_LENS":
                return f"[{index_str}] 🔀 Multi Lens (Multi-Hit) x{stack_count}"

            elif type_id == "SOOTHE_BELL":
                return f"[{index_str}] 🔔 Soothe Bell (Friendship+) x{stack_count}"

            elif type_id == "CANDY_JAR":
                return f"[{index_str}] 🍬 Candy Jar (Level Boost+) x{stack_count}"

            elif type_id == "BERRY_POUCH":
                return f"[{index_str}] 🎒 Berry Pouch (Preserve Berries) x{stack_count}"

            elif type_id == "HEALING_CHARM":
                return f"[{index_str}] ✨ Healing Charm (Healing Boost) x{stack_count}"

            elif type_id == "SHINY_CHARM":
                return f"[{index_str}] ✨ Shiny Charm (Shiny Rate+) x{stack_count}"

            elif type_id == "OVAL_CHARM":
                return f"[{index_str}] ⭐ Oval Charm (Multi-Pokemon Exp) x{stack_count}"

            elif type_id == "CATCHING_CHARM":
                return f"[{index_str}] 🎯 Catching Charm (Critical Catch+) x{stack_count}"

            elif type_id == "AMULET_COIN":
                return f"[{index_str}] 💰 Amulet Coin (Money Multiplier) x{stack_count}"

            elif type_id == "LOCK_CAPSULE":
                return f"[{index_str}] 🔒 Lock Capsule (Lock Tiers) x{stack_count}"

            elif type_id == "TERA_ORB":
                return f"[{index_str}] 💎 Tera Orb (Terastallize Access) x{stack_count}"

            elif type_id == "DYNAMAX_BAND":
                return f"[{index_str}] 💎 Dynamax Band (Gigantamax Access) x{stack_count}"

            elif type_id == "MAP":
                return f"[{index_str}] 🗺 Map (Choose Next Destinations) x{stack_count}"


            elif type_id == "GOLDEN_POKEBALL":
                return f"[{index_str}] ⚪ Golden Pokeball x{stack_count}"

            # Additional common items that were missing emojis
            elif type_id == "KINGS_ROCK":
                return f"[{index_str}] 👑 King's Rock (Flinch Chance) x{stack_count}"

            elif type_id == "GOLDEN_PUNCH":
                return f"[{index_str}] 👊 Golden Punch (Money Reward) x{stack_count}"

            elif type_id == "MYSTICAL_ROCK":
                return f"[{index_str}] 🪨 Mystical Rock x{stack_count}"

            elif type_id == "EVIOLITE":
                return f"[{index_str}] 💎 Eviolite (Defense Boost) x{stack_count}"

            elif type_id == "SOUL_DEW":
                return f"[{index_str}] 💎 Soul Dew (Nature Boost) x{stack_count}"

            elif type_id == "GRIP_CLAW":
                return f"[{index_str}] 🦀 Grip Claw (Trap Effect) x{stack_count}"

            elif type_id == "QUICK_CLAW":
                return f"[{index_str}] ⚡ Quick Claw (Speed Priority) x{stack_count}"

            elif type_id == "SHELL_BELL":
                return f"[{index_str}] 🐚 Shell Bell (Hit Heal) x{stack_count}"

            elif type_id == "TOXIC_ORB":
                return f"[{index_str}] ☠️ Toxic Orb (Poison Status) x{stack_count}"

            elif type_id == "FLAME_ORB":
                return f"[{index_str}] 🔥 Flame Orb (Burn Status) x{stack_count}"

            elif type_id == "BATON":
                return f"[{index_str}] 🏃 Baton (Switch Effect) x{stack_count}"

            else:
                # Fallback to informative format
                args_display = str(args) if args else "None"
                return f"[{index_str}] {type_id} (args: {args_display}) x{stack_count}"

        except Exception:
            # Fallback to safe format on any error
            return f"[{index_str}] {modifier.get('typeId', 'UNKNOWN')} x{modifier.get('stackCount', 1)}"

    def _get_form_id_for_pokemon(self, pokemon_id: int) -> int:
        """Get the appropriate form_id for a Pokemon based on its species from save analysis."""
        try:
            # Get Pokemon species from the pokemon_id
            species = self._get_pokemon_species(pokemon_id)

            # Species-to-form mapping based on real save data analysis
            # Format: species_id: form_id
            species_to_form = {
                # Confirmed from save data analysis
                3: 48,    # Venusaur (Mega Venusaur - confirmed from save data)
                9: 56,    # Blastoise (G-Max Blastoise - confirmed from save data)
                130: 22,  # Gyarados (Mega Gyarados - confirmed from save data)
                
                # Add more species as they are discovered in saves
                # Includes: Mega, G-Max, Calyrex forms, Deoxys forms, Kyurem forms, 
                # Zacian/Zamazenta items, and other special forms
            }

            return species_to_form.get(species, species)  # Default to species ID as form ID
        except Exception:
            return 56  # Safe fallback to Blastoise form

    def _get_pokemon_species(self, pokemon_id: int) -> int:
        """Extract Pokemon species from Pokemon ID using catalog lookup."""
        try:
            # Look through exp_level_relationships in high_level_pokemon_data.json to find species
            # Format: [level, exp, species, pokemon_id]
            import json
            import os

            high_level_data_path = os.path.join(os.getcwd(), "high_level_pokemon_data.json")
            if os.path.exists(high_level_data_path):
                with open(high_level_data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                exp_relationships = data.get("exp_level_relationships", [])
                for entry in exp_relationships:
                    if len(entry) >= 4 and entry[3] == pokemon_id:
                        return entry[2]  # Return species

            # Fallback: try to extract from Pokemon catalog if available
            catalog_path = os.path.join(os.path.dirname(__file__), os.pardir, "data", "pokemon_catalog.json")
            if os.path.exists(catalog_path):
                # This is a more complex lookup - for now just return a default
                pass

            return 9  # Default to Blastoise species
        except Exception:
            return 9  # Safe fallback to Blastoise species
