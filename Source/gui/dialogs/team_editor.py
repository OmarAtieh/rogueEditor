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
    load_ability_catalog,
    load_nature_catalog,
    nature_multipliers_by_id,
    load_stat_catalog,
    load_growth_group_map,
    exp_for_level,
    level_from_exp,
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
        stacks = int(m.get("stackCount") or 1)
        # Map stat_id (from catalog) to index 1..5; assume stat ids align to catalog mapping in data/stats.json
        # We only know index mapping for names via nature effects; lacking reverse map, apply to all non-HP when unknown
        idx = None
        # Robust mapping: use stat id -> name catalog, then name -> index
        try:
            _, stat_i2n = load_stat_catalog()
            name = stat_i2n.get(int(stat_id)) if isinstance(stat_id, int) else None
            name_key = str(name or "").strip().lower().replace(" ", "_")
            name_to_idx = {
                "attack": 1,
                "defense": 2,
                "sp_attack": 3,
                "sp_defense": 4,
                "speed": 5,
            }
            idx = name_to_idx.get(name_key)
        except Exception:
            idx = None
        stacks = max(0, stacks)
        factor = 1.0 + 0.10 * stacks  # +10% per stack
        if idx is not None:
            mults[idx] *= factor
            boosted[idx] = True
            counts[idx] += stacks
        else:
            # Fallback: mark as boosted unknown (no-op or spread minimal effect)
            pass
    return mults, boosted, counts


class TeamEditorDialog(tk.Toplevel):
    def __init__(self, master: "App", api: PokerogueAPI, editor: Editor, slot: int):
        super().__init__(master)
        self.title(f"Team Editor - Slot {slot}")
        self.geometry("1000x640")
        self.api = api
        self.editor = editor
        self.slot = int(slot)
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
        self.move_n2i, self.move_i2n = load_move_catalog()
        self.abil_n2i, self.abil_i2n = load_ability_catalog()
        self.nat_n2i, self.nat_i2n = load_nature_catalog()
        self.nature_mults_by_id = nature_multipliers_by_id()
        # Build UI
        self._build()
        self._refresh_party()
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
        # Pokemon tab: Form & Visuals
        self.tab_poke_form = ttk.Frame(self.tabs)
        self._build_form_visuals(self.tab_poke_form)
        # Trainer tabs (Basics)
        self.tab_trainer_basics = ttk.Frame(self.tabs)
        self._build_trainer_basics(self.tab_trainer_basics)

        # Save/Upload bar
        bar = ttk.Frame(right)
        bar.pack(fill=tk.X, pady=(6, 0))
        self.btn_save = ttk.Button(bar, text="Save to file", command=self._save, state=tk.DISABLED)
        self.btn_upload = ttk.Button(bar, text="Upload", command=self._upload, state=tk.DISABLED)
        self.btn_save.pack(side=tk.LEFT)
        self.btn_upload.pack(side=tk.LEFT, padx=6)
        # Initial view
        self._apply_target_visibility()

    def _build_basics(self, parent: ttk.Frame):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True)
        # Left column labels/entries
        r = 0
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

        # Held items button
        ttk.Button(frm, text="Manage Held Items…", command=self._open_item_mgr).grid(row=0, column=3, padx=8, pady=3, sticky=tk.W)

        # Status section
        r = 0
        statf = ttk.LabelFrame(frm, text="Status")
        statf.grid(row=0, column=2, rowspan=4, sticky=tk.NW, padx=4, pady=2)
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
        af.grid_columnconfigure(1, weight=1)
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
        ttk.Button(frm, text="Apply Basics to Local", command=self._apply_basics).grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(10, 6))
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
        self.move_vars: List[tk.StringVar] = [tk.StringVar(value="") for _ in range(4)]
        for i in range(4):
            ttk.Label(frm, text=f"Move {i+1}:").grid(row=i, column=0, sticky=tk.E, padx=4, pady=3)
            ent = ttk.Entry(frm, textvariable=self.move_vars[i], width=24)
            ent.grid(row=i, column=1, sticky=tk.W)
            ttk.Button(frm, text="Pick…", command=lambda idx=i: self._pick_move(idx)).grid(row=i, column=2, padx=4)
        ttk.Button(frm, text="Apply Moves to Local", command=self._apply_moves).grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(8, 4))

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
        # Quick open items/modifiers manager
        ttk.Button(parent, text="Open Modifiers / Items…", command=self._open_item_mgr_trainer).grid(row=2, column=1, sticky=tk.W, pady=(8, 0))
        # Display-only Play Time and Game Mode
        ttk.Label(parent, text="Play Time:").grid(row=3, column=0, sticky=tk.E, padx=6)
        self.lbl_playtime = ttk.Label(parent, text="-")
        self.lbl_playtime.grid(row=3, column=1, sticky=tk.W)
        ttk.Label(parent, text="Game Mode:").grid(row=4, column=0, sticky=tk.E, padx=6)
        self.lbl_gamemode = ttk.Label(parent, text="-")
        self.lbl_gamemode.grid(row=4, column=1, sticky=tk.W)

    # --- Data binding / refresh ---
    def _refresh_party(self):
        try:
            prev = self.party_list.curselection()[0]
        except Exception:
            prev = 0
        self.party_list.delete(0, tk.END)
        inv = invert_dex_map(load_pokemon_index())
        for i, mon in enumerate(self.party, start=1):
            did = str(_get(mon, ("species", "dexId", "speciesId", "pokemonId")) or "?")
            name = inv.get(did, did)
            mid = mon.get("id")
            lvl = _get(mon, ("level", "lvl")) or "?"
            self.party_list.insert(tk.END, f"{i}. {name} (id {mid}) lvl={lvl}")
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
            except Exception:
                pass
            # Load trainer snapshot on switch
            try:
                self._load_trainer_snapshot()
            except Exception:
                pass
        else:
            try:
                self.tabs.add(self.tab_poke_basics, text="Basics")
                self.tabs.add(self.tab_poke_stats, text="Stats")
                self.tabs.add(self.tab_poke_moves, text="Moves")
                self.tabs.add(self.tab_poke_form, text="Form & Visuals")
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
            from rogueeditor.catalog import load_exp_tables
            data = load_exp_tables()
            tables = data.get('tables') or []
            if 0 <= gidx < len(tables) and isinstance(tables[gidx], list) and tables[gidx]:
                max_lvl = len(tables[gidx])
                if lvl_in < 1:
                    lvl_in = 1
                if lvl_in > max_lvl:
                    lvl_in = max_lvl
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
        # Truncate to 4 entries
        out = out[:4]
        mon[key] = out
        self._mark_dirty()

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
        # Base stats
        species_id = _get_species_id(mon)
        base = get_base_stats_by_species_id(species_id or -1) or [0, 0, 0, 0, 0, 0]
        for i, v in enumerate(base):
            self.base_labels[i].configure(text=str(v))
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
        for i in range(4):
            mid = ids[i] if i < len(ids) else 0
            if isinstance(mid, int) and mid > 0:
                self.move_vars[i].set(f"{self.move_i2n.get(mid, mid)} ({mid})")
            else:
                self.move_vars[i].set("")

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
        # Save slot if changed
        p = slot_save_path(self.api.username, self.slot)
        if self._dirty_local or not os.path.exists(p):
            dump_json(p, self.data)
            self._dirty_local = False
        try:
            self.btn_save.configure(state=(tk.NORMAL if self._dirty_server else tk.DISABLED))
        except Exception:
            pass
        messagebox.showinfo("Saved", f"Wrote {p}")

    def _upload(self):
        if not messagebox.askyesno("Confirm Upload", "Upload changes to the server?"):
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
