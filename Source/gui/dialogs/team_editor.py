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
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Dict, List, Optional, Tuple

from rogueeditor import PokerogueAPI
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
)
from rogueeditor.base_stats import get_base_stats_by_species_id
from gui.common.catalog_select import CatalogSelectDialog
from .item_manager import ItemManagerDialog


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
        super().__init__(master)
        try:
            s = int(slot)
        except Exception:
            s = 1
        s = 1 if s < 1 else (5 if s > 5 else s)
        self.title(f"Team Manager - Slot {s}")
        self.geometry("1000x760")
        self.api = api
        self.editor = editor
        self.slot = s
        # Snapshot
        self.data: Dict[str, Any] = self.api.get_slot(self.slot)
        self.party: List[dict] = self.data.get("party") or []
        # Dirty flags (slot)
        self._dirty_local = False
        self._dirty_server = False
        # Trainer snapshot + flags (team editor focuses on slot/session only)
        self._trainer_data: Optional[Dict[str, Any]] = None
        self._trainer_dirty_local: bool = False
        self._trainer_dirty_server: bool = False
        # Catalogs
        # Prefer unified move labels from moves_data.json
        try:
            self.move_n2i, self.move_i2n = build_move_label_catalog()
            if not self.move_n2i or not self.move_i2n:
                self.move_n2i, self.move_i2n = load_move_catalog()
        except Exception:
            self.move_n2i, self.move_i2n = load_move_catalog()
        self.abil_n2i, self.abil_i2n = load_ability_catalog()
        self.nat_n2i, self.nat_i2n = load_nature_catalog()
        self.nature_mults_by_id = nature_multipliers_by_id()
        # Build UI
        self._build()
        self._refresh_party()
        # Install context menus for text widgets (right-click: cut/copy/paste/select-all)
        try:
            self._install_context_menus()
        except Exception:
            pass
        try:
            master._modalize(self)
        except Exception:
            pass

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
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)
        # Left
        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)
        ttk.Label(left, text="Target:").pack(anchor=tk.W)
        self.target_var = tk.StringVar(value="Party")
        trow = ttk.Frame(left)
        trow.pack(anchor=tk.W)
        ttk.Radiobutton(trow, text="Trainer", variable=self.target_var, value="Trainer", command=self._on_target_changed).pack(side=tk.LEFT)
        ttk.Radiobutton(trow, text="Party", variable=self.target_var, value="Party", command=self._on_target_changed).pack(side=tk.LEFT, padx=8)
        ttk.Label(left, text="Party:").pack(anchor=tk.W, pady=(6, 0))
        self.party_list = tk.Listbox(left, height=12, exportselection=False)
        self.party_list.pack(fill=tk.Y, expand=False)
        self.party_list.bind("<<ListboxSelect>>", lambda e: self._on_party_selected())

        # Right
        right = ttk.Frame(root)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill=tk.BOTH, expand=True)
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

        # Team Defensive Analysis (standalone tab)
        self.tab_team_defensive = ttk.Frame(self.tabs)
        self._build_defensive_analysis(self.tab_team_defensive)

        # Team Offensive Analysis (standalone tab)
        self.tab_team_offensive = ttk.Frame(self.tabs)
        self._build_offensive_analysis(self.tab_team_offensive)

        # Save/Upload bar
        bar = ttk.Frame(right)
        bar.pack(fill=tk.X, pady=(6, 0))
        self.btn_save = ttk.Button(bar, text="Save to file", command=self._save, state=tk.DISABLED)
        self.btn_upload = ttk.Button(bar, text="Upload", command=self._upload, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT)
        self.btn_upload.pack(side=tk.LEFT, padx=6)
        try:
            ttk.Label(bar, text=f"Target Slot: {self.slot}", foreground='gray').pack(side=tk.RIGHT)
        except Exception:
            pass
        # Initial view
        self._apply_target_visibility()

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
        # Left column labels/entries
        r = 1
        ttk.Label(frm, text="Level:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_level = tk.StringVar(value="")
        self.ent_level = ttk.Entry(frm, textvariable=self.var_level, width=8)
        self.ent_level.grid(row=r, column=1, sticky=tk.W)
        r += 1
        ttk.Label(frm, text="EXP:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_exp = tk.StringVar(value="")
        self.ent_exp = ttk.Entry(frm, textvariable=self.var_exp, width=12)
        self.ent_exp.grid(row=r, column=1, sticky=tk.W)
        # Live recompute Level on EXP change
        try:
            self.var_exp.trace_add('write', lambda *args: self._on_exp_change())
            self.var_level.trace_add('write', lambda *args: self._on_level_change())
        except Exception:
            pass
        r += 1
        ttk.Label(frm, text="Growth Rate:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_growth = tk.StringVar(value="-")
        ttk.Label(frm, textvariable=self.var_growth).grid(row=r, column=1, sticky=tk.W)
        r += 1
        # EXP note about >100 assumption
        self.exp_note = ttk.Label(frm, text="Note: Levels beyond 100 use last EXP step (supports 200+)", foreground="gray")
        self.exp_note.grid(row=r, column=0, columnspan=4, sticky=tk.W, padx=4)
        r += 1
        ttk.Label(frm, text="Friendship:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_friend = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.var_friend, width=8).grid(row=r, column=1, sticky=tk.W)
        r += 1
        ttk.Label(frm, text="Current HP:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_hp = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.var_hp, width=8).grid(row=r, column=1, sticky=tk.W)
        r += 1
        ttk.Label(frm, text="Nickname:").grid(row=r, column=0, sticky=tk.E, padx=4, pady=3)
        self.var_name = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.var_name, width=18).grid(row=r, column=1, sticky=tk.W)
        # Held items button (pushed down below species row)
        ttk.Button(frm, text="Manage Held Items…", command=self._open_item_mgr).grid(row=1, column=3, padx=8, pady=3, sticky=tk.W)

        # Status section (pushed down below species row)
        r = 1
        statf = ttk.LabelFrame(frm, text="Status")
        statf.grid(row=1, column=2, rowspan=4, sticky=tk.NW, padx=4, pady=2)
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
        af = ttk.LabelFrame(frm, text="Ability & Passives")
        af.grid(row=4, column=0, columnspan=4, sticky=tk.EW, padx=4, pady=(8, 6))
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

        # Apply button (push down to avoid overlapping controls)
        ttk.Button(frm, text="Apply Basics to Local", command=self._apply_basics).grid(row=8, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(10, 6))
        # Heal helpers
        heal_bar = ttk.Frame(frm)
        heal_bar.grid(row=8, column=2, columnspan=2, sticky=tk.W)
        ttk.Button(heal_bar, text="Full Restore", command=self._full_restore_current).pack(side=tk.LEFT, padx=(0,6))
        # Bind status changes to update visibility + summary
        try:
            self.var_status.trace_add('write', lambda *args: (self._update_status_fields_visibility(), self._update_status_summary()))
        except Exception:
            pass

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
                self.party_list.selection_set(current_idx - 1)
                self.party_list.activate(current_idx - 1)
                self._on_party_selected()
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
                self.party_list.selection_set(current_idx + 1)
                self.party_list.activate(current_idx + 1)
                self._on_party_selected()
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
                self.party_list.selection_set(0)
                self.party_list.activate(0)
                self._on_party_selected()
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
                self.party_list.selection_set(new_idx)
                self.party_list.activate(new_idx)
                self._on_party_selected()
        except Exception:
            pass

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
        # Live recalculation; no explicit button
        ttk.Button(frm, text="Apply Stats to Local", command=self._apply_stats).grid(row=7, column=4, sticky=tk.W)
        # Nature hint (neutral or +/- targets)
        self.nature_hint = ttk.Label(frm, text="", foreground="gray")
        self.nature_hint.grid(row=8, column=1, columnspan=3, sticky=tk.W)
        # Bind live recalc on changes
        try:
            # Level from Basics tab
            self.var_level.trace_add('write', lambda *args: self._recalc_stats_safe())
            # Nature
            self.var_nature.trace_add('write', lambda *args: self._recalc_stats_safe())
            # IVs
            for v in self.iv_vars:
                v.trace_add('write', lambda *args: self._recalc_stats_safe())
        except Exception:
            pass

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
        ttk.Button(frm, text="Apply Moves to Local", command=self._apply_moves).grid(row=7, column=0, columnspan=3, sticky=tk.W, padx=4, pady=(8, 4))

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
        # Lazy-load catalogs
        self._type_matrix = load_type_matchup_matrix()
        self._type_colors = load_type_colors()
        self._matchup_cache = {}
        # Sections for bins (vertically stacked)
        sections = [
            ("Immune (x0)", 0.0, "immune"),
            ("x0.25", 0.25, "x0_25"),
            ("x0.5", 0.5, "x0_5"),
            ("x1", 1.0, "x1"),
            ("x2", 2.0, "x2"),
            ("x4", 4.0, "x4"),
        ]
        self._matchup_bins = {}
        for i, (title, _val, key) in enumerate(sections):
            lf = ttk.LabelFrame(frm, text=title)
            lf.grid(row=i+1, column=0, sticky=tk.NSEW, padx=6, pady=6)
            inner = ttk.Frame(lf)
            inner.pack(fill=tk.BOTH, expand=True)
            self._matchup_bins[key] = inner
        frm.grid_columnconfigure(0, weight=1)
        # Hook tab
        self.tabs.add(parent, text="Type Matchups")

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

        # Create effectiveness sections (split 2x vs 4x)
        effectiveness_sections = [
            ("Excellent (4x)", "excellent_4x", "#2E7D32"),            # Darker green
            ("Good (2x)", "good_2x", "#4CAF50"),                     # Green
            ("Neutral (1x)", "neutral", "#FFC107"),                   # Amber
            ("Not Very Effective (0 < x < 1)", "not_very_effective", "#FF9800"),  # Orange
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

        # Walls section (below side-by-side)
        self._walls_frame = ttk.LabelFrame(frm, text="Type Combos That Wall This Pokemon")
        self._walls_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(4, 6))
        # Make walls section scrollable and extensible
        walls_canvas = tk.Canvas(self._walls_frame, height=100)
        walls_scroll = ttk.Scrollbar(self._walls_frame, orient="vertical", command=walls_canvas.yview)
        walls_inner = ttk.Frame(walls_canvas)
        walls_canvas.configure(yscrollcommand=walls_scroll.set)
        walls_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        walls_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        walls_canvas.create_window((0, 0), window=walls_inner, anchor="nw")
        walls_inner.bind("<Configure>", lambda e: walls_canvas.configure(scrollregion=walls_canvas.bbox("all")))
        self._walls_inner = walls_inner

        # Initialize coverage display
        self._refresh_offensive_coverage()

    def _refresh_offensive_coverage(self):
        """Refresh the offensive Matchups analysis display."""
        try:
            mon = self._current_mon()
            if not mon:
                self._clear_coverage_display()
                return

            # Import coverage calculator
            from rogueeditor.coverage_calculator import get_coverage_for_pokemon

            # Extract move IDs from current Pokemon
            # Try both 'moveset' (actual save format) and 'moves' (team editor format)
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
                self._clear_coverage_display()
                return

            # Calculate coverage with caching per-mon and move signature
            from rogueeditor.coverage_calculator import invalidate_coverage_cache
            try:
                mon_key = str(mon.get('id')) if isinstance(mon.get('id'), int) else str(self.party.index(mon))
            except Exception:
                mon_key = 'current'
            move_sig = tuple(sorted(move_ids))
            cached = self._mon_coverage_cache.get(mon_key)
            if cached and cached.get('sig') == move_sig:
                coverage = cached.get('coverage') or {}
            else:
                try:
                    invalidate_coverage_cache(mon_key)
                except Exception:
                    pass
                coverage = get_coverage_for_pokemon(move_ids, mon_key)
                self._mon_coverage_cache[mon_key] = {'sig': move_sig, 'coverage': coverage}

            # Update display
            self._update_coverage_display(coverage)

        except Exception as e:
            print(f"Error refreshing offensive Matchups: {e}")
            # Clear display on error
            self._clear_coverage_display()

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
            # Clear local cache for current mon
            mon = self._current_mon()
            try:
                mon_key = str(mon.get('id')) if (mon and isinstance(mon.get('id'), int)) else str(self.party.index(mon))
            except Exception:
                mon_key = 'current'
            if isinstance(getattr(self, '_mon_coverage_cache', None), dict):
                self._mon_coverage_cache.pop(mon_key, None)
            # Invalidate calculator cache for this mon
            try:
                from rogueeditor.coverage_calculator import invalidate_coverage_cache
                invalidate_coverage_cache(mon_key)
            except Exception:
                pass
        except Exception:
            pass
        # Refresh UI
        try:
            self._refresh_offensive_coverage()
        except Exception:
            pass

    def _update_coverage_display(self, coverage: dict):
        """Update the coverage display with calculated coverage data."""
        try:
            # Clear existing widgets
            for widget in self.coverage_moves_frame.winfo_children():
                widget.destroy()

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
            move_types = set(coverage_summary.get("move_types", []))
            # Build bins fresh (custom thresholds split 2x vs 4x)
            bins = {
                "excellent_4x": [],     # >2
                "good_2x": [],          # ==2
                "neutral": [],          # ==1
                "not_very_effective": [], # (0,1)
                "no_effect": [],        # ==0
            }
            # Use matrix to recompute best effectiveness per defender
            from rogueeditor.catalog import load_type_matchup_matrix
            mat = getattr(self, "_type_matrix", None) or load_type_matchup_matrix()
            # Derive list of type names from matrix keys
            defenders = sorted([k for k in mat.keys() if isinstance(mat.get(k), dict)])
            for def_t in defenders:
                best = 0.0
                for att in move_types:
                    eff = 1.0
                    try:
                        # defense-oriented lookup
                        row = mat.get(def_t) or {}
                        if att in row:
                            eff = float(row.get(att) or 1.0)
                        else:
                            row2 = mat.get(att) or {}
                            if def_t in row2:
                                eff = float(row2.get(def_t) or 1.0)
                    except Exception:
                        eff = 1.0
                    if eff > best:
                        best = eff
                # Bin once per defender by best effectiveness (custom thresholds)
                if best == 0.0:
                    bins["no_effect"].append(def_t)
                elif 0.0 < best < 1.0:
                    bins["not_very_effective"].append(def_t)
                elif best == 1.0:
                    bins["neutral"].append(def_t)
                elif best == 2.0:
                    bins["good_2x"].append(def_t)
                elif best > 2.0:
                    bins["excellent_4x"].append(def_t)

            # Render bins top to bottom; types appear only in their highest-qualifying bin
            for section_key in ("excellent_4x", "good_2x", "neutral", "not_very_effective", "no_effect"):
                section_frame = self.coverage_sections[section_key]
                for widget in section_frame.winfo_children():
                    widget.destroy()
                tlist = bins.get(section_key) or []
                if tlist:
                    labels = [t.title() for t in tlist]
                    colors = [self._color_for_type(t) for t in tlist]
                    # Allow up to 9 chips per row to use more horizontal space
                    self._render_type_chips(section_frame, labels, colors, per_row=9)
                else:
                    ttk.Label(section_frame, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)

            # Type-combo walls: show dual type combos that wall all move types (render below side-by-side area)
            try:
                target_inner = getattr(self, '_walls_inner', None)
                parent_to_clear = target_inner if target_inner is not None else self._walls_frame
                for w in parent_to_clear.winfo_children():
                    w.destroy()
                from rogueeditor.coverage_calculator import find_type_combo_walls
                move_types_list = list(move_types)
                walls = find_type_combo_walls(move_types_list, mat) if move_types_list else {"single": [], "dual": []}
                duals = [(a, b) for (a, b) in (walls.get("dual") or [])]
                if duals:
                    container = getattr(self, '_walls_inner', None) or self._walls_frame
                    # Render only colored bracketed chips; they wrap every 6 combos (12 chips)
                    chips = ttk.Frame(container)
                    chips.pack(fill=tk.X, padx=5, pady=(0,2))
                    rowf = None
                    count = 0
                    for (a, b) in duals:
                        if count % 6 == 0:
                            rowf = ttk.Frame(chips)
                            rowf.pack(fill=tk.X, anchor=tk.W)
                        tk.Label(rowf, text="[", bd=0).pack(side=tk.LEFT)
                        tk.Label(rowf, text=a.title(), bg=self._color_for_type(a), bd=1, relief=tk.SOLID, padx=4, pady=1).pack(side=tk.LEFT, padx=(0,2))
                        tk.Label(rowf, text=", ", bd=0).pack(side=tk.LEFT)
                        tk.Label(rowf, text=b.title(), bg=self._color_for_type(b), bd=1, relief=tk.SOLID, padx=4, pady=1).pack(side=tk.LEFT, padx=(0,2))
                        tk.Label(rowf, text="]", bd=0).pack(side=tk.LEFT)
                        if (a, b) != duals[-1]:
                            tk.Label(rowf, text=", ", bd=0).pack(side=tk.LEFT, padx=(2,2))
                        count += 1
                    # No text wrapping label used; chips wrap by row chunking
                else:
                    container = getattr(self, '_walls_inner', None) or self._walls_frame
                    ttk.Label(container, text="None", foreground="gray").pack(anchor=tk.W, padx=5, pady=2)
            except Exception:
                pass

            # Update boss analysis (three subsections; two rows each)
            boss_analysis = coverage.get("boss_analysis", {})
            for boss_key, boss_label in self.boss_labels.items():
                if boss_key in boss_analysis:
                    analysis = boss_analysis[boss_key]
                    status = analysis.get("status", "unknown")
                    effectiveness = analysis.get("best_effectiveness", 0)
                    move_type = str(analysis.get("best_move_type", "none")).strip().lower()

                    status_colors = {
                        "excellent": "green",
                        "good": "blue",
                        "poor": "orange",
                        "none": "red"
                    }

                    # Map 'ok' to neutral coloring
                    if status == "neutral":
                        color = "#FFC107"
                    else:
                        color = status_colors.get(status, "gray")
                    # First row: boss name is static label before boss_label; boss_label shows overall evaluation
                    def _fmt_eff(e: float) -> str:
                        try:
                            if e in (0.0, 0, 0.25, 0.5, 1.0, 2.0, 4.0):
                                if e == 1.0:
                                    return "x1"
                                if e == 0.0:
                                    return "x0"
                                if e == 2.0:
                                    return "x2"
                                if e == 4.0:
                                    return "x4"
                                if e == 0.5:
                                    return "x0.5"
                                if e == 0.25:
                                    return "x0.25"
                            return f"x{e:.1f}"
                        except Exception:
                            return "x1"
                    boss_label.config(text=f"Evaluation: {status.title()} ({_fmt_eff(float(effectiveness))})", foreground=color)
                    # Second row: per-move-type chips labeled with effectiveness only (no words)
                    try:
                        dyn = getattr(self, f"_boss_dyn_{boss_key}")
                        for w in dyn.winfo_children():
                            w.destroy()
                        # Build list of move types and their effectiveness vs boss types
                        mt = (coverage.get("coverage_summary", {}) or {}).get("move_types", [])
                        from rogueeditor.coverage_calculator import get_type_effectiveness, BOSS_POKEMON, _effectiveness_vs_boss
                        boss_def = (BOSS_POKEMON.get(boss_key, {}) or {})
                        boss_types = boss_def.get("types", [])
                        types_sorted = sorted(set(mt))
                        if types_sorted:
                            rowf = None
                            for i, t in enumerate(types_sorted):
                                if i % 4 == 0:
                                    rowf = ttk.Frame(dyn)
                                    rowf.pack(fill=tk.X, anchor=tk.W)
                                # Use boss-aware effectiveness (handles Delta Stream etc.)
                                eff = _effectiveness_vs_boss(t, boss_key, boss_types, boss_def, getattr(self, "_type_matrix", None) or load_type_matchup_matrix())
                                chip = tk.Label(rowf, text=str(t).title(), bg=self._color_for_type(t), bd=1, relief=tk.SOLID, padx=6, pady=2)
                                chip.pack(side=tk.LEFT, padx=3, pady=3)
                                ttk.Label(rowf, text=_fmt_eff(float(eff))).pack(side=tk.LEFT, padx=(4, 12))
                        else:
                            ttk.Label(dyn, text="No damaging move types", foreground="gray").pack(anchor=tk.W)
                    except Exception:
                        pass
                else:
                    boss_label.config(text="No data", foreground="gray")

        except Exception as e:
            print(f"Error updating coverage display: {e}")

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
                cat = load_pokemon_catalog() or {}
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
                cat = load_pokemon_catalog() or {}
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
        from rogueeditor.catalog import load_types_catalog, load_pokeball_catalog
        try:
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

        ttk.Button(frm, text="Apply Form & Visuals", command=self._apply_form_visuals).grid(row=3, column=1, sticky=tk.W, padx=6, pady=(8, 2))

    def _build_trainer_basics(self, parent: ttk.Frame):
        parent.grid_columnconfigure(1, weight=1)
        # Add bottom spacer to expand vertically like other tabs
        parent.grid_rowconfigure(99, weight=1)
        
        ttk.Label(parent, text="Money:").grid(row=0, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_money = tk.StringVar(value="")
        ent = ttk.Entry(parent, textvariable=self.var_money, width=12)
        ent.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(parent, text="Apply", command=self._apply_trainer_changes).grid(row=0, column=2, sticky=tk.W, padx=6)
        # Weather editor (slot/session field)
        from rogueeditor.catalog import load_weather_catalog
        try:
            self._weather_n2i, self._weather_i2n = load_weather_catalog()
        except Exception:
            self._weather_n2i, self._weather_i2n = ({}, {})
        ttk.Label(parent, text="Weather:").grid(row=1, column=0, sticky=tk.E, padx=6, pady=6)
        self.var_weather = tk.StringVar(value="")
        self.cb_weather = ttk.Combobox(
            parent,
            textvariable=self.var_weather,
            values=[f"{name} ({iid})" for name, iid in sorted(self._weather_n2i.items(), key=lambda kv: kv[0])],
            width=24,
            state="readonly",
        )
        self.cb_weather.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(parent, text="Apply", command=self._apply_trainer_changes).grid(row=1, column=2, sticky=tk.W, padx=6)
        ttk.Button(parent, text="Full Team Heal (Local)", command=self._full_team_heal).grid(row=1, column=3, sticky=tk.W, padx=6)
        # Quick open items/modifiers manager
        ttk.Button(parent, text="Open Modifiers / Items…", command=self._open_item_mgr_trainer).grid(row=2, column=1, sticky=tk.W, pady=(8, 0))
        # Display-only Play Time and Game Mode (combined on same row)
        ttk.Label(parent, text="Play Time:").grid(row=3, column=0, sticky=tk.E, padx=6)
        self.lbl_playtime = ttk.Label(parent, text="-")
        self.lbl_playtime.grid(row=3, column=1, sticky=tk.W)
        ttk.Label(parent, text="Game Mode:").grid(row=3, column=2, sticky=tk.E, padx=6)
        self.lbl_gamemode = ttk.Label(parent, text="-")
        self.lbl_gamemode.grid(row=3, column=3, sticky=tk.W)

        # Spacer to expand vertically like other tabs
        ttk.Label(parent, text="").grid(row=99, column=0, sticky=tk.EW)


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

        # 3. Boss Coverage Analysis (left column)
        boss_lf = ttk.LabelFrame(bottom_row, text="Boss Coverage Analysis")
        boss_lf.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6), pady=0)
        self._team_boss_frame = ttk.Frame(boss_lf)
        self._team_boss_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # 4. Team Walls Analysis (right column) - Scrollable
        walls_lf = ttk.LabelFrame(bottom_row, text="Type Combinations that Wall the Team")
        walls_lf.grid(row=0, column=1, sticky=tk.NSEW, padx=(6, 0), pady=0)

        # Create scrollable container for walls analysis
        walls_canvas = tk.Canvas(walls_lf, highlightthickness=0)
        walls_scrollbar = ttk.Scrollbar(walls_lf, orient="vertical", command=walls_canvas.yview)
        self._team_walls_frame = ttk.Frame(walls_canvas)

        self._team_walls_frame.bind("<Configure>",
                                   lambda e: walls_canvas.configure(scrollregion=walls_canvas.bbox("all")))

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

    def _recompute_team_summary(self):
        try:
            mat = getattr(self, "_type_matrix", None) or load_type_matchup_matrix()
            types = sorted(mat.keys())
            # Build per-attack-type counts in exact bins
            bins_counts = {k: {t: 0 for t in types} for k in ("immune","x0_25","x0_5","x1","x2","x4")}
            cat = load_pokemon_catalog() or {}
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
            cat = load_pokemon_catalog() or {}
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

    def _compute_team_offensive_coverage(self):
        """Compute and display team-wide offensive matchups."""
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
                find_type_combo_walls, load_type_matrix
            )
            from rogueeditor.catalog import load_pokemon_catalog

            calculator = OffensiveCoverageCalculator()
            cat = load_pokemon_catalog() or {}
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
            type_matrix = load_type_matrix()
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

                    if best_pokemon >= 0 and best_pokemon < len(self.party):
                        pokemon_info = f" (Pokemon #{best_pokemon + 1})"
                    else:
                        pokemon_info = ""

                    status_text = f"{status.title()}: x{effectiveness:.1f}{pokemon_info}"
                    ttk.Label(boss_row, text=status_text, foreground=color).pack(side=tk.LEFT)
            else:
                ttk.Label(self._team_boss_frame, text="No boss analysis available",
                         foreground="gray").pack(anchor=tk.W, padx=5, pady=5)

            # 4. ENHANCED TEAM WALLS ANALYSIS WITH COVERAGE DETAILS
            if all_team_move_types:
                type_matrix = load_type_matrix()
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
                    self._render_type_chips(chips_frame, labels, colors, per_row=4)

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

    # --- Data binding / refresh ---
    def _refresh_party(self):
        try:
            prev = self.party_list.curselection()[0]
        except Exception:
            prev = 0
        self.party_list.delete(0, tk.END)
        # Invalidate matchup cache on refresh
        try:
            self._matchup_cache = {}
        except Exception:
            pass
        cat = load_pokemon_catalog() or {}
        by_dex = cat.get("by_dex") or {}
        inv = invert_dex_map(load_pokemon_index())
        for i, mon in enumerate(self.party, start=1):
            did = str(_get(mon, ("species", "dexId", "speciesId", "pokemonId")) or "?")
            entry = by_dex.get(did) or {}
            name = entry.get("name") or inv.get(did, did)
            # brief mon descriptor with form
            fslug = self._detect_form_slug(mon)
            form_disp = None
            if fslug and (entry.get("forms") or {}).get(fslug):
                fdn = (entry.get("forms") or {}).get(fslug, {}).get("display_name")
                if isinstance(fdn, str) and fdn.strip():
                    form_disp = fdn
            if form_disp:
                label = f"{i}. {int(did):04d} {name} ({form_disp})"
            else:
                label = f"{i}. {int(did):04d} {name}"
            mid = mon.get("id")
            lvl = _get(mon, ("level", "lvl")) or "?"
            self.party_list.insert(tk.END, f"{label} • id {mid} • Lv {lvl}")
        try:
            self.party_list.selection_set(prev)
            self.party_list.activate(prev)
        except Exception:
            pass
        self._on_party_selected()

    def _current_mon(self) -> Optional[dict]:
        try:
            idx = int(self.party_list.curselection()[0])
            return self.party[idx]
        except Exception:
            return None

    def _on_target_changed(self):
        self._apply_target_visibility()

    def _apply_target_visibility(self):
        tgt = self.target_var.get()
        # Clear all tabs
        try:
            for tab_id in list(self.tabs.tabs()):
                self.tabs.forget(tab_id)
        except Exception:
            pass
        # Add tabs based on target
        if tgt == "Trainer":
            try:
                self.tabs.add(self.tab_trainer_basics, text="Basics")
                self.tabs.add(self.tab_team_defensive, text="Team Defensive")
                self.tabs.add(self.tab_team_offensive, text="Team Offensive")
            except Exception:
                pass
            # Load trainer snapshot on switch
            try:
                self._load_trainer_snapshot()
                self._recompute_team_summary()
            except Exception:
                pass
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

    def _on_party_selected(self):
        mon = self._current_mon()
        if not mon:
            return
        # Basics fields
        # EXP and Level binding using growth curves
        try:
            exp_val = mon.get('exp')
            self.var_exp.set(str(int(exp_val)))
        except Exception:
            self.var_exp.set("")
        # Species + types chips from pokemon catalog
        try:
            cat = load_pokemon_catalog() or {}
            by_dex = cat.get("by_dex") or {}
            dex = _get_species_id(mon) or -1
            entry = by_dex.get(str(dex)) or {}
            # Species + form display name
            name = str(entry.get("name") or "-")
            fslug = self._detect_form_slug(mon)
            if fslug and (entry.get("forms") or {}).get(fslug):
                fdn = (entry.get("forms") or {}).get(fslug, {}).get("display_name")
                if isinstance(fdn, str) and fdn.strip():
                    name = f"{name} ({fdn})"
            self.lbl_species_name.configure(text=name)
            tp = entry.get("types") or {}
            colors = getattr(self, "_type_colors", None) or load_type_colors()
            t1 = str(tp.get("type1") or "").lower()
            t2 = str(tp.get("type2") or "").lower() if tp.get("type2") else ""
            # Primary type chip
            if t1:
                self.type_chip1.configure(text=t1.title(), bg=self._color_for_type(t1))
                if not getattr(self, '_type_chip1_packed', False):
                    try:
                        self.type_chip1.pack_forget()
                        self.type_chip1.pack(side=tk.LEFT, padx=3)
                    except Exception:
                        pass
                    self._type_chip1_packed = True
            else:
                try:
                    self.type_chip1.pack_forget()
                except Exception:
                    pass
                self._type_chip1_packed = False
            # Secondary type chip (show only if present)
            if t2:
                self.type_chip2.configure(text=t2.title(), bg=self._color_for_type(t2))
                if not getattr(self, '_type_chip2_packed', False):
                    try:
                        self.type_chip2.pack_forget()
                        self.type_chip2.pack(side=tk.LEFT, padx=3)
                    except Exception:
                        pass
                    self._type_chip2_packed = True
            else:
                try:
                    self.type_chip2.pack_forget()
                except Exception:
                    pass
                self._type_chip2_packed = False
        except Exception:
            pass
        try:
            gidx = self._growth_index_for_mon(mon)
            # compute level from EXP if present; else show existing level
            lvl = None
            try:
                e = int(self.var_exp.get() or '0')
                lvl = level_from_exp(gidx, e)
            except Exception:
                lvl = None
            self.var_level.set(str(lvl if isinstance(lvl, int) and lvl > 0 else (_get(mon, ("level", "lvl")) or "")))
            # Growth rate display
            self.var_growth.set(self._growth_name_display(gidx))
        except Exception:
            self.var_level.set(str(_get(mon, ("level", "lvl")) or ""))
            try:
                self.var_growth.set(self._growth_name_display(self._growth_index_for_mon(mon)))
            except Exception:
                self.var_growth.set('-')
        self.var_friend.set(str(_get(mon, ("friendship", "happiness")) or ""))
        self.var_hp.set(str(_get(mon, ("currentHp", "hp")) or ""))
        self.var_name.set(str(_get(mon, ("nickname", "name")) or ""))
        # Server stats array display
        try:
            stats = mon.get('stats')
            if isinstance(stats, list) and len(stats) == 6:
                self.server_stats_var.set(
                    f"[{stats[0]}, {stats[1]}, {stats[2]}, {stats[3]}, {stats[4]}, {stats[5]}]"
                )
            else:
                self.server_stats_var.set('-')
        except Exception:
            self.server_stats_var.set('-')
        abil = _get(mon, ("abilityId", "ability"))
        if isinstance(abil, int):
            self.var_ability.set(str(self.abil_i2n.get(int(abil), abil)))
        else:
            self.var_ability.set(str(abil or ""))
        # Ability slot radio from abilityIndex
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
        # Passives (heuristic key)
        self.var_passive.set(bool(mon.get("passive") or mon.get("passiveEnabled") or False))
        # Update matchups view
        try:
            self._update_matchups_for_mon(mon)
        except Exception:
            pass
        # Status (heuristic mapping)
        st_sel = 'none'
        s_obj = mon.get("status")
        if isinstance(s_obj, dict):
            if 'sleepTurnsRemaining' in s_obj:
                st_sel = 'slp'
            elif 'toxicTurnCount' in s_obj:
                st_sel = 'tox'
            else:
                st_sel = 'none'
        else:
            st_sel = str(s_obj or 'none')
        self.cb_status.set(st_sel)
        # Volatile statuses are battle-only; not shown or edited here
        # Populate status-specific fields
        try:
            st = self.cb_status.get().strip().lower()
            if isinstance(s_obj, dict):
                if st == 'slp':
                    val = s_obj.get('sleepTurnsRemaining')
                    self.status_detail_var.set(str(val if val is not None else ""))
                elif st == 'tox':
                    val = s_obj.get('toxicTurnCount')
                    self.status_detail_var.set(str(val if val is not None else ""))
                else:
                    self.status_detail_var.set("")
            else:
                # fall back to legacy top-level fields if present
                if st == 'slp':
                    val = mon.get('sleepTurns') or mon.get('statusTurns') or ''
                    self.status_detail_var.set(str(val))
                elif st == 'tox':
                    val = mon.get('toxicTurns') or mon.get('statusTurns') or ''
                    self.status_detail_var.set(str(val))
                else:
                    self.status_detail_var.set("")
        except Exception:
            pass
        self._update_status_fields_visibility()
        self._update_status_summary()
        # If trainer tab has team summary, recompute
        try:
            self._recompute_team_summary()
        except Exception:
            pass
        # Stats tab
        ivs = mon.get("ivs") if isinstance(mon.get("ivs"), list) and len(mon.get("ivs")) == 6 else [0, 0, 0, 0, 0, 0]
        for i in range(6):
            self.iv_vars[i].set(str(ivs[i]))
        nat = _get(mon, ("natureId", "nature"))
        # Prefer integer id to construct decorated display
        nid_val: Optional[int] = None
        if isinstance(nat, int):
            nid_val = int(nat)
        elif isinstance(nat, str):
            key = nat.strip().lower().replace(" ", "_")
            nid_val = self.nat_n2i.get(key)
        if isinstance(nid_val, int):
            label = self._nature_label_for_id(nid_val)
            self.var_nature.set(f"{label} ({nid_val})")
        else:
            self.var_nature.set(str(nat or ""))
        # Base + calc
        self._recalc_stats()
        # Moves tab: show original structure faithfully and preserve on edit
        self._bind_moves_from_mon(mon)
        # Form & Visuals: bind fields
        try:
            # Tera type
            tval = mon.get('teraType')
            if isinstance(tval, int) and hasattr(self, '_type_i2n'):
                tname = self._type_i2n.get(int(tval), str(tval))
                self.var_tera.set(f"{tname} ({tval})")
            else:
                self.var_tera.set("")
            # Shiny and Luck
            self.var_shiny.set(bool(mon.get('shiny') or False))
            lval = mon.get('luck')
            try:
                self.var_luck.set(str(int(lval)))
            except Exception:
                self.var_luck.set("0")
            # Pause evolutions
            self.var_pause_evo.set(bool(mon.get('pauseEvolutions') or False))
            # Gender
            g = mon.get('gender')
            gdisp = None
            if isinstance(g, int):
                gdisp = 'male (0)' if g == 0 else ('female (1)' if g == 1 else 'unknown (-1)')
            self.var_gender.set(gdisp or '')
            # Poké ball
            b = mon.get('pokeball')
            if isinstance(b, int) and hasattr(self, '_ball_i2n'):
                self.var_ball.set(f"{self._ball_i2n.get(int(b), str(b))} ({b})")
            else:
                self.var_ball.set("")
        except Exception:
            pass

        # Refresh offensive matchups when Pokemon selection changes
        try:
            self._refresh_offensive_coverage()
        except Exception as e:
            print(f"Error refreshing coverage after party selection: {e}")

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
            self.data = self.api.get_slot(self.slot)
            self.party = self.data.get("party") or []
            self._recalc_stats_safe()
        except Exception:
            pass

    def _pick_ability(self):
        res = CatalogSelectDialog.select(self, self.abil_n2i, title="Select Ability")
        if res is not None:
            self.var_ability.set(f"{self.abil_i2n.get(int(res), res)} ({res})")

    def _pick_nature(self):
        # Use decorated names that include boost/reduce info
        decorated = self._nature_select_map()
        res = CatalogSelectDialog.select(self, decorated, title="Select Nature")
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
            self.data = self.api.get_slot(self.slot)
            self.party = self.data.get("party") or []
            self._recalc_stats_safe()
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
            cat = load_pokemon_catalog() or {}
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
        try:
            self._recalc_stats()
        except Exception:
            pass

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
            try:
                pt = int(self.data.get('playTime')) if isinstance(self.data, dict) and 'playTime' in self.data else None
            except Exception:
                pt = None
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
