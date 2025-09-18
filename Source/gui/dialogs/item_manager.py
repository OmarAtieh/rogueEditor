from __future__ import annotations

import os
import re
import json as _json
import tkinter as tk
from tkinter import ttk, messagebox

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.catalog import DATA_TYPES_JSON, load_nature_catalog


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
            right, textvariable=self.cat_var, values=cat_opts, state="readonly", width=24
        )
        self.cat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda e: (self._on_cat_change(), self._update_button_states()))
        row += 1

        # Common one-arg items
        self.common_var = tk.StringVar()
        self.common_cb = ttk.Combobox(
            right, textvariable=self.common_var, values=sorted(list(self._common_items())), width=28
        )
        self.lbl_common = ttk.Label(right, text="Common:")
        self.lbl_common.grid(row=row, column=0, sticky=tk.W)
        self.common_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.common_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Accuracy items with boost (permanent pickers area)
        self.acc_var = tk.StringVar()
        self.acc_cb = ttk.Combobox(
            right, textvariable=self.acc_var, values=["WIDE_LENS", "MULTI_LENS"], width=28
        )
        self.lbl_acc_item = ttk.Label(right, text="Accuracy item:")
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
            values=sorted([f"{k} ({v})" for k, v in berry_n2i.items()]),
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
            values=sorted([f"{k} ({v})" for k, v in stat_n2i.items()]),
            width=28,
        )
        self.lbl_stat = ttk.Label(right, text="Base stat:")
        self.lbl_stat.grid(row=row, column=0, sticky=tk.W)
        self.stat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.stat_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        # Hint about stat boosters per stack
        try:
            self.stat_hint = ttk.Label(right, text="")
            self.stat_hint.grid(row=row, column=2, columnspan=2, sticky=tk.W)
        except Exception:
            pass
        row += 1

        # Type Booster (Attack Type Booster)
        self.type_var = tk.StringVar()
        try:
            with open(DATA_TYPES_JSON, "r", encoding="utf-8") as _tf:
                _types = _json.load(_tf) or {}
            _n2i = {str(k).lower(): int(v) for k, v in (_types.get("name_to_id") or {}).items()}
            self._type_name_to_id = _n2i
            type_values = [f"{k.upper()} ({v})" for k, v in sorted(_n2i.items(), key=lambda kv: kv[1])]
        except Exception:
            self._type_name_to_id = {}
            type_values = []
        self.type_cb = ttk.Combobox(right, textvariable=self.type_var, values=type_values, width=28)
        self.lbl_type = ttk.Label(right, text="Type:")
        self.lbl_type.grid(row=row, column=0, sticky=tk.W)
        self.type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.type_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Mint (Nature change)
        _nat_n2i, _nat_i2n = load_nature_catalog()
        self.nature_var = tk.StringVar()
        nat_values = [f"{name.title().replace('_',' ')} ({nid})" for nid, name in sorted(_nat_i2n.items(), key=lambda kv: kv[0])]
        self.nature_cb = ttk.Combobox(right, textvariable=self.nature_var, values=nat_values, width=28)
        self.lbl_nature = ttk.Label(right, text="Nature:")
        self.lbl_nature.grid(row=row, column=0, sticky=tk.W)
        self.nature_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.nature_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Temp Battle Modifiers (X-items, DIRE_HIT, LUREs)
        self.temp_battle_var = tk.StringVar()
        temp_battle_values = [
            "X Attack (1)",
            "X Defense (2)",
            "X Sp. Atk (3)",
            "X Sp. Def (4)",
            "X Speed (5)",
            "X Accuracy (6)",
            "DIRE_HIT",
            "LURE",
            "SUPER_LURE",
            "MAX_LURE"
        ]
        self.temp_battle_cb = ttk.Combobox(right, textvariable=self.temp_battle_var, values=temp_battle_values, width=28)
        self.lbl_temp_battle = ttk.Label(right, text="Temp Battle Modifier:")
        self.lbl_temp_battle.grid(row=row, column=0, sticky=tk.W)
        self.temp_battle_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.temp_battle_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Observed types are merged into Common values; no separate UI row
        self._observed_types: set[str] = set()

        # Trainer modifiers
        self.lbl_player_type = ttk.Label(right, text="Trainer mod typeId:")
        self.lbl_player_type.grid(row=row, column=0, sticky=tk.W)
        self.player_type_var = tk.StringVar()
        self.player_type_cb = ttk.Combobox(
            right,
            textvariable=self.player_type_var,
            values=[
                "EXP_CHARM",
                "SUPER_EXP_CHARM",
                "EXP_SHARE",
                "MAP",
                "IV_SCANNER",
                "GOLDEN_POKEBALL",
                # Curated player items
                "LURE",
                "SUPER_LURE",
                "MAX_LURE",
                "AMULET_COIN",
                "MEGA_BRACELET",
                "TERA_ORB",
                "DYNAMAX_BAND",
                # Quality-of-life trainer items
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
                "VOUCHER",
                "VOUCHER_PLUS",
                "VOUCHER_PREMIUM",
            ],
            width=28,
        )
        self.player_type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.player_type_cb.bind(
            "<<ComboboxSelected>>",
            lambda e: (self._maybe_preset_player_args(), self._apply_visibility(), self._update_button_states()),
        )
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
            self._player_type_all_values = list(self.player_type_cb["values"])
        except Exception:
            pass
        # Generic args (rarely used). Kept for compatibility; positioned in options rows
        self.lbl_player_args = ttk.Label(right, text="Args (auto-filled, customizable):")
        self.player_args_var = tk.StringVar()
        self.player_args_entry = ttk.Entry(right, textvariable=self.player_args_var, width=18)
        row += 1

        # Options (dynamic controls placed below): accuracy boost, stacks, args
        # Accuracy boost (for WIDE_LENS)
        self.lbl_acc_boost = ttk.Label(right, text="Boost:")
        self.acc_boost = ttk.Entry(right, width=6)
        self.acc_boost.insert(0, "5")
        self.acc_boost.bind("<KeyRelease>", lambda e: self._update_button_states())
        # Stacks
        self.lbl_stacks = ttk.Label(right, text="Stacks:")
        self.stack_var = tk.StringVar(value="1")
        self.stack_entry = ttk.Entry(right, textvariable=self.stack_var, width=6)
        self.stack_entry.bind("<KeyRelease>", lambda e: self._update_button_states())
        # Grid options in two rows: row (acc boost + stacks), row+1 (args)
        self.lbl_acc_boost.grid(row=row, column=0, sticky=tk.E)
        self.acc_boost.grid(row=row, column=1, sticky=tk.W)
        self.lbl_stacks.grid(row=row, column=2, sticky=tk.E)
        self.stack_entry.grid(row=row, column=3, sticky=tk.W)
        # Player args on next row
        self.lbl_player_args.grid(row=row+1, column=0, sticky=tk.E)
        self.player_args_entry.grid(row=row+1, column=1, sticky=tk.W)
        row += 2
        self.btn_add = ttk.Button(right, text="Add", command=self._add, state=tk.DISABLED)
        self.btn_add.grid(row=row, column=1, sticky=tk.W, padx=4, pady=6)
        self.btn_save = ttk.Button(right, text="Save to file", command=self._save, state=tk.DISABLED)
        self.btn_save.grid(row=row, column=2, sticky=tk.W, padx=4, pady=6)
        self.btn_upload = ttk.Button(right, text="Upload", command=self._upload, state=tk.DISABLED)
        self.btn_upload.grid(row=row, column=3, sticky=tk.W, padx=4, pady=6)

        # Trainer properties panel (only visible for Trainer target)
        row += 1
        self.trainer_frame = ttk.LabelFrame(right, text="Trainer Properties")
        self.trainer_frame.grid(row=row, column=0, columnspan=4, sticky=tk.EW, padx=2, pady=(8, 4))
        self.trainer_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(self.trainer_frame, text="Money:").grid(row=0, column=0, sticky=tk.E, padx=4, pady=2)
        self.money_var = tk.StringVar(value="")
        self.money_entry = ttk.Entry(self.trainer_frame, textvariable=self.money_var, width=12)
        self.money_entry.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)
        self.btn_apply_trainer = ttk.Button(self.trainer_frame, text="Apply Trainer Changes", command=self._apply_trainer_changes)
        self.btn_apply_trainer.grid(row=0, column=2, sticky=tk.W, padx=6, pady=2)

        # Initial visibility/state
        self._apply_visibility()
        self._update_button_states()

    def _common_items(self) -> set[str]:
        return {
            "FOCUS_BAND",
            "MYSTICAL_ROCK",
            "SOOTHE_BELL",
            "SCOPE_LENS",
            "LEEK",
            "EVIOLITE",
            "SOUL_DEW",
            "GOLDEN_PUNCH",
            "GRIP_CLAW",
            "QUICK_CLAW",
            "KINGS_ROCK",
            "LEFTOVERS",
            "SHELL_BELL",
            "TOXIC_ORB",
            "FLAME_ORB",
            "BATON",
        }

    def _on_cat_change(self):
        # Adjust available categories and hint text when switching contexts
        try:
            if hasattr(self, "stat_hint"):
                self.stat_hint.configure(text="")
        except Exception:
            pass
        # When target changes, restrict categories accordingly
        tgt = self.target_var.get()
        if tgt == "Trainer":
            vals = ["Temp Battle Modifiers", "Trainer EXP Charms", "Trainer"]
        else:
            vals = ["Common", "Accuracy", "Berries", "Vitamins", "Type Booster", "Mint"]
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
            name = entry.get("name") or inv.get(did, did)
            # Try to reflect form like Team Editor
            fslug = self._detect_form_slug(mon)
            form_disp = None
            if fslug and (entry.get("forms") or {}).get(fslug):
                fdn = (entry.get("forms") or {}).get(fslug, {}).get("display_name")
                if isinstance(fdn, str) and fdn.strip():
                    form_disp = fdn
            if form_disp:
                label = f"{i}. {int(did):04d} {name} ({form_disp})"
            else:
                try:
                    label = f"{i}. {int(did):04d} {name}"
                except Exception:
                    label = f"{i}. {did} {name}"
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
            t = (self.player_type_var.get() or "").strip().upper()
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
            "VOUCHER",
            "VOUCHER_PLUS",
            "VOUCHER_PREMIUM",
        }
        obs |= self._common_items()
        self._observed_types = obs
        try:
            cur = set(self._common_items())
            allowed = (self._observed_types - reserved - trainer_only) | cur
            self.common_cb["values"] = sorted(list(allowed))
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
                    self.mod_list.insert(
                        tk.END,
                        f"[{i}] {m.get('typeId')} args={m.get('args')} stack={m.get('stackCount')}",
                    )
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
                    self.mod_list.insert(
                        tk.END,
                        f"[{i}] {m.get('typeId')} args={m.get('args')} stack={m.get('stackCount')}",
                    )
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
        trainer_catchall = (cat == "Trainer")
        # Player stat selector visible for trainer stat boosters
        player_needs_stat = is_trainer_stat
        # Player args are hidden in grouped categories (exp/stat); only in catch-all for rare items
        player_args_visible = (trainer_catchall and (self.player_type_var.get() or "").strip().upper() in {"EXP_CHARM", "SUPER_EXP_CHARM"})
        # Pokemon-only categories
        common_v = (tgt == "Pokemon" and cat == "Common")
        acc_v = (tgt == "Pokemon" and cat == "Accuracy")
        berry_v = (tgt == "Pokemon" and cat == "Berries")
        stat_v = (tgt == "Pokemon" and cat == "Vitamins")
        typeb_v = (tgt == "Pokemon" and cat == "Type Booster")
        mint_v = (tgt == "Pokemon" and cat == "Mint")
        # No separate Observed category; merged into Common
        # Toggle
        # Configure player type values per category
        if is_trainer_exp:
            try:
                self.player_type_cb["values"] = ["EXP_CHARM", "SUPER_EXP_CHARM"]
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
        # Temp battle modifiers
        for w in (self.lbl_temp_battle, self.temp_battle_cb):
            show(w, is_temp_battle)
        # Options visibility: accuracy boost only when accuracy category selected
        show(self.lbl_acc_boost, acc_v)
        show(self.acc_boost, acc_v)
        # Stacks are broadly applicable (vitamins, accuracy items, common helds, and trainer groups)
        stacks_visible = (
            common_v or acc_v or berry_v or stat_v or typeb_v or mint_v or is_trainer_stat or is_trainer_exp or is_temp_battle or trainer_catchall
        )
        show(self.lbl_stacks, stacks_visible)
        show(self.stack_entry, stacks_visible)
        try:
            show(self.stat_hint, stat_v or player_needs_stat)
            if stat_v:
                self.stat_hint.configure(text="Hint: Each stack applies a percentage effect per stack.")
            elif player_needs_stat:
                self.stat_hint.configure(text="Choose which battle stat to boost temporarily.")
        except Exception:
            pass
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
                self.stat_cb["values"] = self._vitamin_stat_values()
                _select_id(sid)
            elif player_needs_stat:
                sid = _preserve_by_id()
                self.stat_cb["values"] = self._xitem_stat_values()
                _select_id(sid)
        except Exception:
            pass
        # Trainer properties panel visibility
        show(self.trainer_frame, tgt == "Trainer")

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
                psel = (self.player_type_var.get() or "").strip().upper()
                valid = psel in {"EXP_CHARM", "SUPER_EXP_CHARM"}
            else:
                psel = (self.player_type_var.get() or "").strip().upper()
                valid = bool(psel)
        else:
            # Need a selected mon
            valid_mon = self._current_mon() is not None
            if cat == "Common":
                valid = valid_mon and bool((self.common_var.get() or "").strip())
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

    def _apply_trainer_changes(self):
        # Write trainer-related fields (e.g., money) into local snapshot and gate save/upload
        try:
            m = int((self.money_var.get() or "").strip())
            if m < 0:
                m = 0
            self.data["money"] = m
            self._dirty_local = True
            self._dirty_server = True
            self._update_button_states()
            messagebox.showinfo("Applied", "Trainer properties updated locally. Save/Upload to persist.")
        except Exception:
            messagebox.showwarning("Invalid", "Money must be an integer >= 0")

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
            "VOUCHER",
            "VOUCHER_PLUS",
            "VOUCHER_PREMIUM",
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

                    # If both have Pokemon ID as first arg, check if same Pokemon
                    if (new_args and mod_args and
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
                    result = messagebox.askyesnocancel(
                        "Existing Modifier Found",
                        f"{type_id} already exists with {existing_stacks} stacks.\n\n"
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

            if sel == "DIRE_HIT":
                # DIRE_HIT: critical hit booster, args=[5, 5] pattern from save analysis
                entry = {"args": [5, 5], "player": True, "stackCount": stacks, "typeId": "DIRE_HIT", "className": "TempCritBoosterModifier"}
            elif sel.startswith("X ") and "(" in sel:
                # X-items: extract stat ID and create TEMP_STAT_STAGE_BOOSTER
                try:
                    sid = int(sel.rsplit("(", 1)[1].rstrip(")"))
                    # TEMP_STAT_STAGE_BOOSTER: args=[stat_id, 5, 5], typePregenArgs=[stat_id] - using 5,5 pattern
                    entry = {"args": [sid, 5, 5], "player": True, "stackCount": stacks, "typeId": "TEMP_STAT_STAGE_BOOSTER", "typePregenArgs": [sid], "className": "TempStatStageBoosterModifier"}
                except Exception:
                    messagebox.showwarning("Invalid", "Could not parse stat ID from selection")
                    return
            elif sel in {"LURE", "SUPER_LURE", "MAX_LURE"}:
                # LUREs: args=[duration, waves_remaining] pattern
                if sel == "LURE":
                    duration = 10
                elif sel == "SUPER_LURE":
                    duration = 15
                else:  # MAX_LURE
                    duration = 30
                entry = {"args": [duration, duration], "player": True, "stackCount": stacks, "typeId": sel, "className": "DoubleBattleChanceBoosterModifier"}
            else:
                messagebox.showwarning("Invalid", f"Unknown temp battle modifier: {sel}")
                return
        elif cat == "Trainer EXP Charms":
            t = (self.player_type_var.get() or "").strip().upper()
            if t not in {"EXP_CHARM", "SUPER_EXP_CHARM"}:
                messagebox.showwarning("Invalid", "Select EXP_CHARM or SUPER_EXP_CHARM")
                return
            amt = 25 if t == "EXP_CHARM" else 60
            entry = {"args": [amt], "player": True, "stackCount": stacks, "typeId": t, "className": "ExpBoosterModifier"}
        elif cat == "Trainer" or target == "Trainer":
            t = (self.player_type_var.get() or "").strip().upper()
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
                "VOUCHER": "AddVoucherModifier",
                "VOUCHER_PLUS": "AddVoucherModifier",
                "VOUCHER_PREMIUM": "AddVoucherModifier",
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
                elif t == "DIRE_HIT":
                    # DIRE_HIT: args=[5, 5] from save analysis
                    entry["args"] = [5, 5]
                elif t == "HEALING_CHARM" and not args:
                    # HEALING_CHARM: args=[multiplier] - 10% boost
                    entry["args"] = [1.1]
                elif t in {"MAP", "AMULET_COIN", "GOLDEN_POKEBALL", "MEGA_BRACELET", "TERA_ORB", "DYNAMAX_BAND", "EXP_SHARE", "IV_SCANNER", "SHINY_CHARM", "ABILITY_CHARM", "CATCHING_CHARM", "NUGGET", "BIG_NUGGET", "RELIC_GOLD", "COIN_CASE", "LOCK_CAPSULE", "BERRY_POUCH", "CANDY_JAR", "VOUCHER", "VOUCHER_PLUS", "VOUCHER_PREMIUM"}:
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
            t = (self.common_var.get() or "").strip().upper()
            if not t:
                return
            # Handle special arg patterns for complex modifiers
            if t == "RARE_FORM_CHANGE_ITEM":
                # RARE_FORM_CHANGE_ITEM: args=[pokemon_id, form_id, activate] from save analysis
                # Get Pokemon species to determine correct form_id
                form_id = self._get_form_id_for_pokemon(mon_id)
                entry = {"args": [mon_id, form_id, True], "typePregenArgs": [form_id], "player": True, "stackCount": stacks, "typeId": t}
            elif t == "LUCKY_EGG":
                # LUCKY_EGG: args=[pokemon_id, exp_boost] from save analysis
                entry = {"args": [mon_id, 40], "player": True, "stackCount": stacks, "typeId": t}
            elif t == "GOLDEN_EGG":
                # GOLDEN_EGG: args=[pokemon_id, exp_boost] - higher boost than LUCKY_EGG
                entry = {"args": [mon_id, 100], "player": True, "stackCount": stacks, "typeId": t}
            elif t == "SCOPE_LENS":
                # SCOPE_LENS: args=[pokemon_id, crit_boost] - critical hit booster
                entry = {"args": [mon_id, 1], "player": True, "stackCount": stacks, "typeId": t}
            elif t == "LEEK":
                # LEEK: args=[pokemon_id, crit_boost, species_array] - species-specific crit booster
                entry = {"args": [mon_id, 2], "player": True, "stackCount": stacks, "typeId": t}
            elif t == "WIDE_LENS":
                # WIDE_LENS gets special handling in Accuracy section, default here
                entry = {"args": [mon_id, 5], "player": True, "stackCount": stacks, "typeId": t}
            else:
                entry = {"args": [mon_id], "player": True, "stackCount": stacks, "typeId": t}
            # Known held-item class names from server sources
            common_class_map = {
                # Existing Pokemon held items
                "FOCUS_BAND": "SurviveDamageModifier",
                "LEFTOVERS": "TurnHealModifier",
                "SHELL_BELL": "HitHealModifier",
                "QUICK_CLAW": "BypassSpeedChanceModifier",
                "KINGS_ROCK": "FlinchChanceModifier",
                "TOXIC_ORB": "TurnStatusEffectModifier",
                "FLAME_ORB": "TurnStatusEffectModifier",
                "BATON": "SwitchEffectTransferModifier",
                "GOLDEN_PUNCH": "DamageMoneyRewardModifier",
                "WIDE_LENS": "PokemonMoveAccuracyBoosterModifier",
                # New Pokemon held items from modifier-type.ts
                "SCOPE_LENS": "CritBoosterModifier",
                "LEEK": "SpeciesCritBoosterModifier",
                "MULTI_LENS": "PokemonMultiHitModifier",
                "LUCKY_EGG": "PokemonExpBoosterModifier",
                "GOLDEN_EGG": "PokemonExpBoosterModifier",
                "SOOTHE_BELL": "PokemonFriendshipBoosterModifier",
                "RARE_FORM_CHANGE_ITEM": "PokemonFormChangeItemModifier",
                # Leave others unmapped if unknown
            }
            cname = common_class_map.get(t)
            if cname:
                entry["className"] = cname
        elif cat == "Accuracy":
            t = (self.acc_var.get() or "").strip().upper()
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

            # Create detailed description based on modifier type
            if type_id == "BERRY":
                if len(args) > 1:
                    berry_id = args[1]
                    return f"[{index}] Berry (ID: {berry_id}) x{stack_count}"
                return f"[{index}] Berry x{stack_count}"

            elif type_id == "BASE_STAT_BOOSTER":
                if len(args) > 1:
                    stat_id = args[1]
                    stat_names = ["HP", "Attack", "Defense", "Sp. Attack", "Sp. Defense", "Speed"]
                    stat_name = stat_names[stat_id] if 0 <= stat_id < len(stat_names) else f"Stat {stat_id}"
                    return f"[{index}] {stat_name} Vitamin x{stack_count}"
                return f"[{index}] Stat Vitamin x{stack_count}"

            elif type_id == "ATTACK_TYPE_BOOSTER":
                if len(args) > 1:
                    type_id_arg = args[1]
                    # Common type names
                    type_names = {
                        0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison", 4: "Ground", 5: "Rock",
                        6: "Bug", 7: "Ghost", 8: "Steel", 9: "Fire", 10: "Water", 11: "Grass",
                        12: "Electric", 13: "Psychic", 14: "Ice", 15: "Dragon", 16: "Dark", 17: "Fairy"
                    }
                    type_name = type_names.get(type_id_arg, f"Type {type_id_arg}")
                    return f"[{index}] {type_name} Type Booster x{stack_count}"
                return f"[{index}] Type Booster x{stack_count}"

            elif type_id == "TEMP_STAT_STAGE_BOOSTER":
                if type_pregen_args:
                    stat_id = type_pregen_args[0]
                    stat_names = ["HP", "Attack", "Defense", "Sp. Attack", "Sp. Defense", "Speed"]
                    stat_name = stat_names[stat_id] if 0 <= stat_id < len(stat_names) else f"Stat {stat_id}"
                    return f"[{index}] X {stat_name} (Trainer) x{stack_count}"
                return f"[{index}] X Stat Booster (Trainer) x{stack_count}"

            elif type_id == "DIRE_HIT":
                return f"[{index}] Dire Hit (Critical+) x{stack_count}"

            elif type_id == "EXP_CHARM":
                exp_amount = args[0] if args else 25
                total_boost = exp_amount * stack_count
                return f"[{index}] Exp Charm (+{total_boost}% total) x{stack_count}"

            elif type_id == "SUPER_EXP_CHARM":
                exp_amount = args[0] if args else 60
                total_boost = exp_amount * stack_count
                return f"[{index}] Super Exp Charm (+{total_boost}% total) x{stack_count}"

            elif type_id == "LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index}] Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index}] Lure (10 turns) x{stack_count}"

            elif type_id == "SUPER_LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index}] Super Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index}] Super Lure (15 turns) x{stack_count}"

            elif type_id == "MAX_LURE":
                if len(args) >= 2:
                    max_turns, remaining = args[0], args[1]
                    return f"[{index}] Max Lure ({remaining}/{max_turns} turns) x{stack_count}"
                return f"[{index}] Max Lure (30 turns) x{stack_count}"

            elif type_id == "WIDE_LENS":
                if len(args) > 1:
                    accuracy_boost = args[1]
                    return f"[{index}] Wide Lens (+{accuracy_boost} Accuracy) x{stack_count}"
                return f"[{index}] Wide Lens (Accuracy+) x{stack_count}"

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
                        return f"[{index}] {pokemon_name} Form Change (Form {form_id}) x{stack_count}"
                    else:
                        return f"[{index}] {form_name} Form Change x{stack_count}"
                return f"[{index}] Form Change Item x{stack_count}"

            elif type_id == "LUCKY_EGG":
                if len(args) > 1:
                    exp_boost = args[1]
                    return f"[{index}] Lucky Egg (+{exp_boost}% Pokemon Exp) x{stack_count}"
                return f"[{index}] Lucky Egg (Pokemon Exp+) x{stack_count}"

            elif type_id == "LEFTOVERS":
                return f"[{index}] Leftovers (Turn Heal) x{stack_count}"

            elif type_id == "FOCUS_BAND":
                return f"[{index}] Focus Band (Survive Fatal) x{stack_count}"

            elif type_id == "EXP_SHARE":
                return f"[{index}] Exp Share (Party Exp) x{stack_count}"

            elif type_id == "IV_SCANNER":
                return f"[{index}] IV Scanner x{stack_count}"

            elif type_id == "MEGA_BRACELET":
                return f"[{index}] Mega Bracelet x{stack_count}"

            elif type_id == "GOLDEN_EGG":
                if len(args) > 1:
                    exp_boost = args[1]
                    return f"[{index}] Golden Egg (+{exp_boost}% Pokemon Exp) x{stack_count}"
                return f"[{index}] Golden Egg (Pokemon Exp++) x{stack_count}"

            elif type_id == "SCOPE_LENS":
                return f"[{index}] Scope Lens (Critical Hit+) x{stack_count}"

            elif type_id == "LEEK":
                return f"[{index}] Leek (Species Crit+) x{stack_count}"

            elif type_id == "MULTI_LENS":
                return f"[{index}] Multi Lens (Multi-Hit) x{stack_count}"

            elif type_id == "SOOTHE_BELL":
                return f"[{index}] Soothe Bell (Friendship+) x{stack_count}"

            elif type_id == "CANDY_JAR":
                return f"[{index}] Candy Jar (Level Boost+) x{stack_count}"

            elif type_id == "BERRY_POUCH":
                return f"[{index}] Berry Pouch (Preserve Berries) x{stack_count}"

            elif type_id == "HEALING_CHARM":
                return f"[{index}] Healing Charm (Healing Boost) x{stack_count}"

            elif type_id == "SHINY_CHARM":
                return f"[{index}] Shiny Charm (Shiny Rate+) x{stack_count}"

            elif type_id == "OVAL_CHARM":
                return f"[{index}] Oval Charm (Multi-Pokemon Exp) x{stack_count}"

            elif type_id == "CATCHING_CHARM":
                return f"[{index}] Catching Charm (Critical Catch+) x{stack_count}"

            elif type_id == "AMULET_COIN":
                return f"[{index}] Amulet Coin (Money Multiplier) x{stack_count}"

            elif type_id == "LOCK_CAPSULE":
                return f"[{index}] Lock Capsule (Lock Tiers) x{stack_count}"

            elif type_id == "TERA_ORB":
                return f"[{index}] Tera Orb (Terastallize Access) x{stack_count}"

            elif type_id == "DYNAMAX_BAND":
                return f"[{index}] Dynamax Band (Gigantamax Access) x{stack_count}"

            elif type_id == "MAP":
                return f"[{index}] Map (Area Info) x{stack_count}"

            elif type_id.startswith("VOUCHER"):
                if type_id == "VOUCHER_PLUS":
                    return f"[{index}] Voucher Plus x{stack_count}"
                elif type_id == "VOUCHER_PREMIUM":
                    return f"[{index}] Voucher Premium x{stack_count}"
                else:
                    return f"[{index}] Voucher x{stack_count}"

            elif type_id == "GOLDEN_POKEBALL":
                return f"[{index}] Golden Pokeball x{stack_count}"

            else:
                # Fallback to informative format
                args_display = str(args) if args else "None"
                return f"[{index}] {type_id} (args: {args_display}) x{stack_count}"

        except Exception:
            # Fallback to safe format on any error
            return f"[{index}] {modifier.get('typeId', 'UNKNOWN')} x{modifier.get('stackCount', 1)}"

    def _get_form_id_for_pokemon(self, pokemon_id: int) -> int:
        """Get the appropriate form_id for a Pokemon based on its species from save analysis."""
        try:
            # Get Pokemon species from the pokemon_id
            species = self._get_pokemon_species(pokemon_id)

            # Species-to-form mapping based on real save data analysis
            # Format: species_id: form_id
            species_to_form = {
                3: 48,    # Venusaur (Mega Venusaur - confirmed from save data)
                9: 56,    # Blastoise (Mega Blastoise - confirmed from save data)
                130: 22,  # Gyarados (Mega Gyarados - confirmed from save data)
                # Add more species as they are discovered in saves
                # Common mega evolutions (estimated form IDs):
                6: 6,     # Charizard X/Y
                15: 15,   # Beedrill
                18: 18,   # Pidgeot
                65: 65,   # Alakazam
                80: 80,   # Slowbro
                94: 94,   # Gengar
                115: 115, # Kangaskhan
                127: 127, # Pinsir
                142: 142, # Aerodactyl
                150: 150, # Mewtwo X/Y
                181: 181, # Ampharos
                208: 208, # Steelix
                212: 212, # Scizor
                229: 229, # Houndoom
                248: 248, # Tyranitar
                254: 254, # Sceptile
                257: 257, # Blaziken
                260: 260, # Swampert
                282: 282, # Gardevoir
                302: 302, # Sableye
                303: 303, # Mawile
                306: 306, # Aggron
                308: 308, # Medicham
                310: 310, # Manectric
                319: 319, # Sharpedo
                323: 323, # Camerupt
                334: 334, # Altaria
                354: 354, # Banette
                359: 359, # Absol
                362: 362, # Glalie
                373: 373, # Salamence
                376: 376, # Metagross
                384: 384, # Rayquaza
                428: 428, # Lopunny
                445: 445, # Garchomp
                448: 448, # Lucario
                460: 460, # Abomasnow
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
