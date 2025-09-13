from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor


# Extracted from Source/gui.py (Phase 3). See debug/docs/GUI_MIGRATION_PLAN.md.
class ItemManagerDialog(tk.Toplevel):
    def __init__(self, master: "App", api: PokerogueAPI, editor: Editor, slot: int, preselect_mon_id: int | None = None):
        super().__init__(master)
        self.title(f"Modifiers & Items Manager - Slot {slot}")
        self.geometry("900x520")
        self.api = api
        self.editor = editor
        self.slot = slot
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
        self.lbl_cat = ttk.Label(right, text="Category:")
        self.lbl_cat.grid(row=row, column=0, sticky=tk.W)
        self.cat_var = tk.StringVar(value="Common")
        cat_opts = [
            "Common",
            "Accuracy",
            "Berries",
            "Base Stat Booster",
            "Observed",
            "Player (Trainer)",
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

        # Accuracy items with boost
        self.acc_var = tk.StringVar()
        self.acc_cb = ttk.Combobox(
            right, textvariable=self.acc_var, values=["WIDE_LENS", "MULTI_LENS"], width=28
        )
        self.lbl_acc_item = ttk.Label(right, text="Accuracy item:")
        self.lbl_acc_item.grid(row=row, column=0, sticky=tk.W)
        self.acc_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.acc_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        self.lbl_acc_boost = ttk.Label(right, text="Boost:")
        self.lbl_acc_boost.grid(row=row, column=2, sticky=tk.E)
        self.acc_boost = ttk.Entry(right, width=6)
        self.acc_boost.insert(0, "5")
        self.acc_boost.grid(row=row, column=3, sticky=tk.W)
        self.acc_boost.bind("<KeyRelease>", lambda e: self._update_button_states())
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

        # Observed from dumps
        self.obs_var = tk.StringVar()
        self.obs_cb = ttk.Combobox(right, textvariable=self.obs_var, values=[], width=28)
        self.lbl_obs = ttk.Label(right, text="Observed typeId:")
        self.lbl_obs.grid(row=row, column=0, sticky=tk.W)
        self.obs_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.obs_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        row += 1

        # Player (trainer) modifiers
        self.lbl_player_type = ttk.Label(right, text="Player mod typeId:")
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
            ],
            width=28,
        )
        self.player_type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.player_type_cb.bind("<<ComboboxSelected>>", lambda e: self._update_button_states())
        # Optionally augment from TmpServerFiles if present
        try:
            extras = self._augment_player_types_from_tmp()
            if extras:
                vals = list(self.player_type_cb["values"])
                for v in extras:
                    if v not in vals:
                        vals.append(v)
                self.player_type_cb["values"] = vals
        except Exception:
            pass
        self.lbl_player_args = ttk.Label(right, text="Args (ints, comma-separated):")
        self.lbl_player_args.grid(row=row, column=2, sticky=tk.E)
        self.player_args_var = tk.StringVar()
        self.player_args_entry = ttk.Entry(right, textvariable=self.player_args_var, width=18)
        self.player_args_entry.grid(row=row, column=3, sticky=tk.W)
        self.player_args_entry.bind("<KeyRelease>", lambda e: self._update_button_states())
        row += 1

        self.lbl_stacks = ttk.Label(right, text="Stacks:")
        self.lbl_stacks.grid(row=row, column=2, sticky=tk.E)
        self.stack_var = tk.StringVar(value="1")
        self.stack_entry = ttk.Entry(right, textvariable=self.stack_var, width=6)
        self.stack_entry.grid(row=row, column=3, sticky=tk.W)
        self.stack_entry.bind("<KeyRelease>", lambda e: self._update_button_states())
        row += 1
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
            vals = ["Player (Trainer)"]
        else:
            vals = ["Common", "Accuracy", "Berries", "Base Stat Booster", "Observed"]
        try:
            self.cat_cb["values"] = vals
            if self.cat_var.get() not in vals:
                self.cat_var.set(vals[0])
        except Exception:
            pass
        # Visibility by category
        self._apply_visibility()

    def _refresh(self):
        # Populate party list and preserve selection
        try:
            prev = self.party_list.curselection()[0]
        except Exception:
            prev = None
        self.party_list.delete(0, tk.END)
        from rogueeditor.utils import invert_dex_map, load_pokemon_index

        inv = invert_dex_map(load_pokemon_index())
        for i, mon in enumerate(self.party, start=1):
            did = str(mon.get("species") or mon.get("dexId") or mon.get("speciesId") or "?")
            name = inv.get(did, did)
            mid = mon.get("id")
            self.party_list.insert(tk.END, f"{i}. {name} (id {mid})")
        # Observed modifiers
        self._reload_observed()
        # Restore selection
        try:
            if prev is not None:
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
        # Merge with curated sets
        obs |= self._common_items() | {"WIDE_LENS", "MULTI_LENS", "BERRY", "BASE_STAT_BOOSTER"}
        self.obs_cb["values"] = sorted(list(obs))

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
        player_visible = (tgt == "Trainer" or cat == "Player (Trainer)")
        # Pokemon-only categories
        common_v = (tgt == "Pokemon" and cat == "Common")
        acc_v = (tgt == "Pokemon" and cat == "Accuracy")
        berry_v = (tgt == "Pokemon" and cat == "Berries")
        stat_v = (tgt == "Pokemon" and cat == "Base Stat Booster")
        obs_v = (tgt == "Pokemon" and cat == "Observed")
        # Toggle
        for w in (self.lbl_player_type, self.player_type_cb, self.lbl_player_args, self.player_args_entry):
            show(w, player_visible)
        for w in (self.lbl_common, self.common_cb):
            show(w, common_v)
        for w in (self.lbl_acc_item, self.acc_cb, self.lbl_acc_boost, self.acc_boost):
            show(w, acc_v)
        for w in (self.lbl_berry, self.berry_cb):
            show(w, berry_v)
        for w in (self.lbl_stat, self.stat_cb):
            show(w, stat_v)
        try:
            show(self.stat_hint, stat_v)
            if stat_v:
                self.stat_hint.configure(text="Hint: Each stack applies a percentage effect per stack.")
        except Exception:
            pass
        for w in (self.lbl_obs, self.obs_cb):
            show(w, obs_v)
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
        if tgt == "Trainer" or cat == "Player (Trainer)":
            valid = bool((self.player_type_var.get() or "").strip())
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
            elif cat == "Base Stat Booster":
                valid = valid_mon and bool((self.stat_var.get() or "").strip())
            elif cat == "Observed":
                valid = valid_mon and bool((self.obs_var.get() or "").strip())
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

    def _augment_player_types_from_tmp(self) -> list[str]:
        # Try to discover requested player item types from TmpServerFiles/GameData/modifier-type.ts
        wanted = {
            "LURE",
            "SUPER_LURE",
            "MAX_LURE",
            "AMULET_COIN",
            "MEGA_BRACELET",
            "TERA_ORB",
            "DYNAMAX_BAND",
        }
        paths = [
            os.path.normpath(os.path.join(os.getcwd(), "TmpServerFiles", "GameData", "modifier-type.ts")),
            os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, "TmpServerFiles", "GameData", "modifier-type.ts")),
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
        if cat == "Player (Trainer)" or target == "Trainer":
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
                "EXP_CHARM": "ExpBoosterModifier",
                "SUPER_EXP_CHARM": "ExpBoosterModifier",
                "EXP_SHARE": "ExpShareModifier",
                "IV_SCANNER": "IvScannerModifier",
                "MAP": "MapModifier",
                "GOLDEN_POKEBALL": "ExtraModifierModifier",
            }
            cname = class_map.get(t)
            if cname:
                entry["className"] = cname
        elif cat == "Common":
            t = (self.common_var.get() or "").strip().upper()
            if not t:
                return
            entry = {"args": [mon_id], "player": True, "stackCount": stacks, "typeId": t}
        elif cat == "Accuracy":
            t = (self.acc_var.get() or "").strip().upper()
            if not t:
                return
            try:
                boost = int(self.acc_boost.get().strip() or "5")
            except ValueError:
                boost = 5
            entry = {"args": [mon_id, boost], "player": True, "stackCount": stacks, "typeId": t, "className": "PokemonMoveAccuracyBoosterModifier"}
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
        elif cat == "Base Stat Booster":
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
        else:  # Observed
            t = (self.obs_var.get() or "").strip().upper()
            if not t:
                return
            # Best effort: attach with one arg (mon id)
            entry = {"args": [mon_id], "player": True, "stackCount": stacks, "typeId": t}
        if not entry:
            return
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
        from rogueeditor.utils import slot_save_path, dump_json

        p = slot_save_path(self.api.username, self.slot)
        dump_json(p, self.data)
        try:
            self._dirty_local = False
            self.btn_save.configure(state=(tk.NORMAL if self._dirty_server else tk.DISABLED))
        except Exception:
            pass
        messagebox.showinfo("Saved", f"Wrote {p}")

    def _upload(self):
        if not messagebox.askyesno(
            "Confirm Upload", "Upload item changes for this slot to the server?"
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
                from rogueeditor.utils import slot_save_path, dump_json, load_json

                p = slot_save_path(self.api.username, self.slot)
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
