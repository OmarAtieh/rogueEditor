from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk, messagebox

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from gui.common.widgets import AutoCompleteEntry
from gui.common.catalog_select import CatalogSelectDialog


# Extracted from Source/gui.py (Phase 2). See debug/docs/GUI_MIGRATION_PLAN.md.
class TeamEditorDialog(tk.Toplevel):
    def __init__(self, master: "App", api: PokerogueAPI, editor: Editor, slot: int):
        super().__init__(master)
        self.title(f"Team Editor - Slot {slot}")
        self.geometry("900x500")
        self.api = api
        self.editor = editor
        self.slot = slot
        self.data = self.api.get_slot(slot)
        self.party = self.data.get("party") or []
        self._build()
        # Make dialog modal relative to the main window to avoid focus switching issues
        try:
            master._modalize(self)
        except Exception:
            try:
                self.transient(master)
                self.grab_set()
                self.focus_set()
            except Exception:
                pass

    def _build(self):
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True)
        # Left: team list
        left = ttk.Frame(frame)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=6)
        self.team_list = tk.Listbox(left, height=10, exportselection=False)
        self.team_list.pack(fill=tk.Y)
        self.team_list.bind('<<ListboxSelect>>', self._on_select)
        # Populate
        from rogueeditor.utils import load_pokemon_index, invert_dex_map
        inv = invert_dex_map(load_pokemon_index())
        for i, mon in enumerate(self.party, start=1):
            did = str(mon.get("species") or mon.get("dexId") or mon.get("speciesId") or "?")
            name = inv.get(did, did)
            lvl = mon.get("level") or mon.get("lvl")
            self.team_list.insert(tk.END, f"{i}. {name} (Lv {lvl})")
        # Right: editor
        right = ttk.Frame(frame)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._build_editor(right)

    def _build_editor(self, parent):
        from rogueeditor.catalog import (
            load_move_catalog,
            load_ability_catalog,
            load_nature_catalog,
            load_item_catalog,
            nature_multipliers_by_id,
        )
        move_name_to_id, move_id_to_name = load_move_catalog()
        abil_name_to_id, abil_id_to_name = load_ability_catalog()
        nat_name_to_id, nat_id_to_name = load_nature_catalog()
        # Store move catalogs for labels
        self.move_name_to_id = move_name_to_id
        self.move_id_to_name = move_id_to_name
        self.ability_id_to_name = abil_id_to_name

        # --- Section: Core (level, HP, friendship, ability, passive, held items) ---
        ttk.Label(parent, text="Level:").grid(row=0, column=0, sticky=tk.W)
        self.level_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.level_var, width=6).grid(row=0, column=1, sticky=tk.W)
        # Current HP and Max HP label
        ttk.Label(parent, text="HP:").grid(row=0, column=2, sticky=tk.W, padx=(8,0))
        self.hp_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.hp_var, width=6).grid(row=0, column=3, sticky=tk.W)
        self.hp_max_label = ttk.Label(parent, text="/ -")
        self.hp_max_label.grid(row=0, column=4, sticky=tk.W, padx=(4,0))
        # Friendship (0-255)
        ttk.Label(parent, text="Friendship:").grid(row=0, column=5, sticky=tk.W, padx=(12,0))
        self.friendship_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.friendship_var, width=6).grid(row=0, column=6, sticky=tk.W)
        # Recalculate stats when level changes
        def _on_level_change(*args):
            try:
                _ = int(self.level_var.get().strip() or '0')
            except Exception:
                pass
            self._update_calculated_stats()
        try:
            self.level_var.trace_remove('write', getattr(self.level_var, '_lvl_trace', None))
        except Exception:
            pass
        self.level_var._lvl_trace = self.level_var.trace_add('write', _on_level_change)

        ttk.Label(parent, text="Ability:").grid(row=1, column=0, sticky=tk.W)
        self.ability_ac = AutoCompleteEntry(parent, abil_name_to_id)
        self.ability_ac.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(parent, text="Pick", command=lambda: self._pick_from_catalog(self.ability_ac, abil_name_to_id, 'Select Ability')).grid(row=1, column=2, sticky=tk.W)
        self.ability_label = ttk.Label(parent, text="", width=28)
        self.ability_label.grid(row=1, column=5, sticky=tk.W, padx=6)
        self.ability_active_label = ttk.Label(parent, text="", foreground='gray50')
        self.ability_active_label.grid(row=1, column=6, sticky=tk.W, padx=(6,0))
        try:
            self.ability_ac.bind('<KeyRelease>', lambda e: self._update_ability_label())
            self.ability_ac.bind('<FocusOut>', lambda e: self._update_ability_label())
        except Exception:
            pass
        self.passive_var = tk.IntVar(value=0)
        ttk.Checkbutton(parent, text="Passive", variable=self.passive_var).grid(row=1, column=3, sticky=tk.W, padx=6)
        # Held items via manager
        ttk.Button(parent, text="Manage Items...", command=self._open_items_for_current).grid(row=1, column=4, sticky=tk.W, padx=(8,0))

        ttk.Label(parent, text="Nature:").grid(row=2, column=0, sticky=tk.W)
        # Nature combobox with effect hints (e.g., Adamant +Atk/-SpA)
        mults_map = nature_multipliers_by_id()
        def _pretty(s: str) -> str:
            return s.replace('_', ' ').title()
        def _effect_text(nid: int) -> str:
            arr = mults_map.get(int(nid), [1.0]*6)
            labs = ["HP","Atk","Def","SpA","SpD","Spe"]
            up = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-1.1)<1e-6), None)
            dn = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-0.9)<1e-6), None)
            if not up or not dn or up == dn:
                return "neutral"
            return f"+{up}/-{dn}"
        nature_items = []
        for nid, raw_name in sorted(nat_id_to_name.items(), key=lambda kv: kv[0]):
            effect = _effect_text(nid)
            disp = f"{_pretty(raw_name)} ({effect}) ({nid})"
            nature_items.append(disp)
        self.nature_cb = ttk.Combobox(parent, values=nature_items, width=28, state='readonly')
        self.nature_cb.grid(row=2, column=1, sticky=tk.W)
        self.nature_cb.bind('<<ComboboxSelected>>', lambda e: self._on_nature_change())
        # Nature effect hint label
        self.nature_hint = ttk.Label(parent, text="")
        self.nature_hint.grid(row=2, column=5, sticky=tk.W)

        # Held Item
        ttk.Label(parent, text="Held Item:").grid(row=2, column=2, sticky=tk.W)
        try:
            item_name_to_id, item_id_to_name = load_item_catalog()
        except Exception:
            item_name_to_id = {}
            item_id_to_name = {}
        if item_name_to_id:
            self.held_item_ac = AutoCompleteEntry(parent, item_name_to_id, width=20)
            self.held_item_ac.grid(row=2, column=3, sticky=tk.W)
            ttk.Button(parent, text="Pick", command=lambda: self._pick_from_catalog(self.held_item_ac, item_name_to_id, 'Select Item')).grid(row=2, column=4, sticky=tk.W)
            self.held_item_var = None
        else:
            self.held_item_var = tk.StringVar()
            ttk.Entry(parent, textvariable=self.held_item_var, width=8).grid(row=2, column=3, sticky=tk.W)

        # IVs
        ttk.Label(parent, text="IVs:").grid(row=3, column=0, sticky=tk.NW)
        self.iv_vars = [tk.StringVar() for _ in range(6)]
        iv_labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
        iv_frame = ttk.Frame(parent)
        iv_frame.grid(row=3, column=1, columnspan=3, sticky=tk.W)
        for i, lab in enumerate(iv_labels[:3]):
            ttk.Label(iv_frame, text=lab+":").grid(row=i, column=0, sticky=tk.E, padx=2, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[i], width=4).grid(row=i, column=1, sticky=tk.W)
        for j, lab in enumerate(iv_labels[3:], start=3):
            ttk.Label(iv_frame, text=lab+":").grid(row=j-3, column=2, sticky=tk.E, padx=8, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[j], width=4).grid(row=j-3, column=3, sticky=tk.W)

        # --- Section: Stats ---
        ttk.Label(parent, text="Calculated Stats:").grid(row=4, column=0, sticky=tk.NW)
        stats_frame = ttk.Frame(parent)
        stats_frame.grid(row=4, column=1, columnspan=3, sticky=tk.W)
        self.stat_lbls = []
        for i, lab in enumerate(["HP", "Atk", "Def", "SpA", "SpD", "Spe"]):
            ttk.Label(stats_frame, text=lab+":").grid(row=i//3, column=(i%3)*2, sticky=tk.W, padx=(0, 4))
            val = ttk.Label(stats_frame, text="-")
            val.grid(row=i//3, column=(i%3)*2+1, sticky=tk.W, padx=(0, 12))
            self.stat_lbls.append(val)

        ttk.Label(parent, text="Moves:").grid(row=5, column=0, sticky=tk.W)
        self.move_acs = []
        self.move_lbls = []
        for i in range(4):
            ac = AutoCompleteEntry(parent, move_name_to_id, width=30)
            ac.grid(row=5+i, column=1, sticky=tk.W, pady=1)
            ac.bind('<KeyRelease>', lambda e, j=i: self._on_move_ac_change(j))
            ac.bind('<FocusOut>', lambda e, j=i: self._on_move_ac_change(j))
            ttk.Button(parent, text="Pick", command=lambda j=i: self._pick_from_catalog(self.move_acs[j], move_name_to_id, f'Select Move {j+1}')).grid(row=5+i, column=2, sticky=tk.W)
            lbl = ttk.Label(parent, text="", width=28)
            lbl.grid(row=5+i, column=3, sticky=tk.W, padx=6)
            self.move_lbls.append(lbl)
            self.move_acs.append(ac)

        # --- Section: Status (placed above actions) ---
        ttk.Label(parent, text="Status:").grid(row=10, column=0, sticky=tk.W)
        self.status_effect_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.status_effect_var, width=6).grid(row=10, column=1, sticky=tk.W)
        # Dropdown for convenience
        self.status_choice = tk.StringVar()
        self.status_combo = ttk.Combobox(parent, textvariable=self.status_choice, width=20, state='readonly',
                                         values=[
                                             'No Status', 'Burn (1)', 'Freeze (2)', 'Paralysis (3)', 'Poison (4)', 'Sleep (5)', 'Toxic (6)'
                                         ])
        self.status_combo.grid(row=10, column=2, sticky=tk.W, padx=4)
        self.status_name_label = ttk.Label(parent, text="")
        self.status_name_label.grid(row=10, column=3, columnspan=2, sticky=tk.W)
        ttk.Label(parent, text="sleepTurnsRemaining:").grid(row=11, column=0, sticky=tk.E)
        self.status_sleep_var = tk.StringVar(value="0")
        self.sleep_entry = ttk.Entry(parent, textvariable=self.status_sleep_var, width=6)
        self.sleep_entry.grid(row=11, column=1, sticky=tk.W)
        ttk.Label(parent, text="toxicTurnCount:").grid(row=11, column=2, sticky=tk.E)
        self.status_toxic_var = tk.StringVar(value="0")
        self.toxic_entry = ttk.Entry(parent, textvariable=self.status_toxic_var, width=6)
        self.toxic_entry.grid(row=11, column=3, sticky=tk.W)
        # Actions
        ttk.Button(parent, text="Save to file", command=self._save).grid(row=12, column=0, pady=8)
        ttk.Button(parent, text="Upload", command=self._upload).grid(row=12, column=1, pady=8)
        # Bind status dropdown
        try:
            self.status_combo.bind('<<ComboboxSelected>>', lambda e: self._on_status_choice())
        except Exception:
            pass

    def _on_select(self, event=None):
        if not self.team_list.curselection():
            return
        idx = self.team_list.curselection()[0]
        mon = self.party[idx]
        # Level
        lvl = mon.get('level') or mon.get('lvl') or ''
        self.level_var.set(str(lvl))
        # Friendship
        try:
            fr = mon.get('friendship')
            self.friendship_var.set(str(int(fr)) if fr is not None else '')
        except Exception:
            self.friendship_var.set('')
        # Ability
        aid = mon.get('abilityId') or mon.get('ability')
        if aid is not None:
            self.ability_ac.set_value(str(aid))
        try:
            self._update_ability_label()
        except Exception:
            pass
        try:
            self.passive_var.set(1 if bool(mon.get('passive')) else 0)
        except Exception:
            self.passive_var.set(0)
        # Nature
        nid = mon.get('natureId') or mon.get('nature')
        if isinstance(nid, int):
            self.nature_cb.set(str(nid))
        # Moves
        moves = mon.get('moveset') or mon.get('moveIds') or mon.get('moves') or []
        ids = []
        if isinstance(moves, list):
            for m in moves:
                try:
                    mid = m.get('moveId') if isinstance(m, dict) else int(m)
                except Exception:
                    continue
                ids.append(mid)
        for i in range(4):
            val = str(ids[i]) if i < len(ids) and ids[i] is not None else ''
            try:
                self.move_acs[i].set_value(val)
                self._update_move_label(i)
            except Exception:
                pass
        # IVs
        ivs = mon.get("ivs")
        if isinstance(ivs, list) and len(ivs) == 6:
            for i in range(6):
                self.iv_vars[i].set(str(ivs[i]))
        else:
            for i in range(6):
                self.iv_vars[i].set("")
        # Attach IV change listeners and initialize base + calculated stats
        for v in self.iv_vars:
            try:
                v.trace_remove('write', getattr(v, '_calc_trace', None))
            except Exception:
                pass
            def _cb(*args, sv=v):
                self._update_calculated_stats()
            v._calc_trace = v.trace_add('write', _cb)
        self._init_base_and_update()
        # Status load
        try:
            st = mon.get('status')
            if st is None:
                self.status_effect_var.set("")
                self.status_sleep_var.set("0")
                self.status_toxic_var.set("0")
            elif isinstance(st, dict):
                eff = st.get('effect')
                self.status_effect_var.set(str(eff) if eff is not None else "")
                self.status_sleep_var.set(str(st.get('sleepTurnsRemaining') or 0))
                self.status_toxic_var.set(str(st.get('toxicTurnCount') or 0))
            else:
                # Unexpected shape
                self.status_effect_var.set("")
                self.status_sleep_var.set("0")
                self.status_toxic_var.set("0")
        except Exception:
            self.status_effect_var.set("")
            self.status_sleep_var.set("0")
            self.status_toxic_var.set("0")
        # Also refresh hint/labels based on current nature
        try:
            from rogueeditor.catalog import nature_multipliers_by_id
            nid = self._get_nature_id()
            arr = nature_multipliers_by_id().get(nid or -1, [1.0]*6)
        except Exception:
            arr = [1.0]*6
        self._update_nature_hint(arr)

    def _apply_form_changes(self) -> bool:
        # Applies UI fields to current mon in self.data; returns True if applied
        if not self.team_list.curselection():
            return False
        idx = self.team_list.curselection()[0]
        mon = self.party[idx]
        # Level
        lv = self.level_var.get().strip()
        if lv.isdigit():
            if "level" in mon:
                mon["level"] = int(lv)
            elif "lvl" in mon:
                mon["lvl"] = int(lv)
        # Friendship (0-255)
        try:
            fr = int((self.friendship_var.get() or '').strip())
            if fr < 0:
                fr = 0
            if fr > 255:
                fr = 255
            mon['friendship'] = fr
        except Exception:
            pass
        # Ability
        aid = self.ability_ac.get_id()
        if aid is not None:
            if "abilityId" in mon:
                mon["abilityId"] = aid
            elif "ability" in mon:
                mon["ability"] = aid
        try:
            mon["passive"] = bool(self.passive_var.get())
        except Exception:
            pass
        # Nature
        ndisp = self.nature_cb.get().strip()
        nid = None
        if ndisp.endswith(')') and '(' in ndisp:
            try:
                nid = int(ndisp.rsplit('(',1)[1].rstrip(')'))
            except Exception:
                nid = None
        if nid is not None:
            if "natureId" in mon:
                mon["natureId"] = nid
            elif "nature" in mon:
                mon["nature"] = nid
        # IVs
        new_ivs = []
        valid_iv = True
        for v in self.iv_vars:
            s = v.get().strip()
            if not s:
                valid_iv = False
                break
            try:
                val = int(s)
                if val < 0:
                    val = 0
                if val > 31:
                    val = 31
                new_ivs.append(val)
            except ValueError:
                valid_iv = False
                break
        if valid_iv and len(new_ivs) == 6:
            mon["ivs"] = new_ivs
            # Update mon stat fields if present
            try:
                base = getattr(self, '_base_stats', None)
                if base and len(base) == 6:
                    lvl = self._get_level()
                    calc = self._compute_stats(base, lvl, new_ivs)
                    key_pairs = [("maxHp", "hp"), ("attack", "atk"), ("defense", "def"), ("spAttack", "spAtk"), ("spDefense", "spDef"), ("speed", "spd")]
                    for i, (k1, k2) in enumerate(key_pairs):
                        for k in (k1, k2):
                            if k in mon:
                                mon[k] = calc[i]
            except Exception:
                pass
        # Moves
        moves = []
        for ac in self.move_acs:
            mid = ac.get_id()
            if mid is not None:
                moves.append({"moveId": mid, "ppUp": 0, "ppUsed": 0})
        if moves:
            if "moveset" in mon:
                mon["moveset"] = moves
            elif "moveIds" in mon:
                mon["moveIds"] = [m["moveId"] for m in moves]
            elif "moves" in mon:
                mon["moves"] = [m["moveId"] for m in moves]
        # Held item
        if hasattr(self, 'held_item_ac') and self.held_item_ac:
            iid = self.held_item_ac.get_id()
            if iid is not None:
                if "heldItemId" in mon:
                    mon["heldItemId"] = iid
                elif "heldItem" in mon:
                    mon["heldItem"] = iid
                elif "item" in mon:
                    mon["item"] = iid
        else:
            hv = self.held_item_var.get().strip()
            if hv.isdigit():
                hid = int(hv)
                if "heldItemId" in mon:
                    mon["heldItemId"] = hid
                elif "heldItem" in mon:
                    mon["heldItem"] = hid
                elif "item" in mon:
                    mon["item"] = hid
        # Status
        try:
            raw = (self.status_effect_var.get() or '').strip()
            if not raw:
                mon['status'] = None
            else:
                eff = int(raw)
                st = {
                    'effect': eff,
                    'sleepTurnsRemaining': int((self.status_sleep_var.get() or '0')),
                    'toxicTurnCount': int((self.status_toxic_var.get() or '0')),
                }
                mon['status'] = st
        except Exception:
            # Leave status unchanged on parse failure
            pass
        return True

    def _save(self):
        from rogueeditor.utils import slot_save_path, dump_json
        if not self._apply_form_changes():
            messagebox.showwarning("No selection", "Select a team member first")
            return
        save_path = slot_save_path(self.api.username, self.slot)
        dump_json(save_path, self.data)
        messagebox.showinfo("Saved", f"Wrote {save_path}")

    def _upload(self):
        if not messagebox.askyesno("Confirm Upload", "This will overwrite server slot data. Proceed?"):
            return
        try:
            # Apply UI changes, write to file, then upload that file
            from rogueeditor.utils import slot_save_path, dump_json, load_json
            p = slot_save_path(self.api.username, self.slot)
            self._apply_form_changes()
            dump_json(p, self.data)
            # Then read back and upload exactly that file
            payload = load_json(p)
            self.api.update_slot(self.slot, payload)
            messagebox.showinfo("Uploaded", "Server updated successfully")
            # Offer verification: compare 'party' only
            try:
                if messagebox.askyesno("Verify", "Verify that server party matches local changes?"):
                    remote = self.api.get_slot(self.slot)
                    l = (payload.get('party') if isinstance(payload, dict) else None)
                    r = (remote.get('party') if isinstance(remote, dict) else None)
                    if l == r:
                        messagebox.showinfo("Verify", "Party matches server.")
                    else:
                        import json as _json
                        msg = []
                        msg.append("Local party:\n" + _json.dumps(l, ensure_ascii=False, indent=2))
                        msg.append("\nServer party:\n" + _json.dumps(r, ensure_ascii=False, indent=2))
                        self.master._show_text_dialog("Verify Party", "\n".join(msg))
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Upload failed", str(e))

    # --- IV/stat helpers ---
    def _get_level(self) -> int:
        try:
            return int(self.level_var.get().strip())
        except Exception:
            try:
                sel = self.team_list.curselection()[0]
                mon = self.party[sel]
                return int(mon.get('level') or mon.get('lvl') or 1)
            except Exception:
                return 1

    def _parse_ivs(self) -> list[int] | None:
        vals: list[int] = []
        for v in self.iv_vars:
            s = v.get().strip()
            if not s or not s.isdigit():
                return None
            try:
                iv = int(s)
                if iv < 0:
                    iv = 0
                if iv > 31:
                    iv = 31
                vals.append(iv)
            except ValueError:
                return None
        return vals if len(vals) == 6 else None

    def _extract_actual_stats(self, mon: dict) -> list[int] | None:
        """Extract actual current stats from the slot data.

        Preferred named fields: maxHp/hp, attack/atk, defense/def, spAttack/spAtk, spDefense/spDef, speed/spd.
        Fallback: when those are absent, use packed arrays present in saves:
          - mon["stats"] is typically [ATK, DEF, SPATK, SPDEF, SPD, ACC] (TEMP_BATTLE_STATS order).
            We map the first five to ATK..SPD and read HP from mon["hp"].
        """
        pairs = [("maxHp", "hp"), ("attack", "atk"), ("defense", "def"), ("spAttack", "spAtk"), ("spDefense", "spDef"), ("speed", "spd")]
        out: list[int] = []
        # Try named fields first
        named_ok = True
        for k1, k2 in pairs:
            val = mon.get(k1)
            if val is None:
                val = mon.get(k2)
            if val is None:
                named_ok = False
                break
            try:
                out.append(int(val))
            except Exception:
                named_ok = False
                break
        if named_ok and len(out) == 6:
            return out
        # Fallback: mon["stats"] carries ATK,DEF,SPATK,SPDEF,SPD,(ACC)
        try:
            arr = mon.get("stats")
            if isinstance(arr, list) and len(arr) >= 5:
                hp_val = mon.get("hp") or mon.get("maxHp")
                if hp_val is None:
                    return None
                atk = int(arr[0])
                deff = int(arr[1])
                spa = int(arr[2])
                spd = int(arr[3])
                spe = int(arr[4])
                return [int(hp_val), atk, deff, spa, spd, spe]
        except Exception:
            return None
        return None

    def _infer_base_stats(self, level: int, ivs: list[int], actual: list[int]) -> list[int]:
        def ev_effective(E: int) -> int:
            return math.floor(math.ceil(math.sqrt(E)) / 4)
        try:
            from rogueeditor.catalog import nature_multipliers_by_id
            nid = self._get_nature_id()
            mults = nature_multipliers_by_id().get(nid or -1, [1.0] * 6)
        except Exception:
            mults = [1.0] * 6
        base: list[int] = []
        # HP (no nature)
        hp = actual[0]
        hp_inner = ((hp - level - 10) * 100) / max(1, level)
        two_b_plus_two_i = max(0, math.ceil(hp_inner) - ev_effective(0))
        base.append(max(1, round((two_b_plus_two_i - 2 * ivs[0]) / 2)))
        # Other stats: reverse nature first
        for i in range(1, 6):
            stat = actual[i]
            m = mults[i] if i < len(mults) else 1.0
            if m and m != 1.0:
                stat = round(stat / m)
            inner = ((stat - 5) * 100) / max(1, level)
            two_b_plus_two_i = max(0, math.ceil(inner) - ev_effective(0))
            base.append(max(1, round((two_b_plus_two_i - 2 * ivs[i]) / 2)))
        return base

    def _compute_stats(self, base: list[int], level: int, ivs: list[int]) -> list[int]:
        def ev_effective(E: int) -> int:
            return math.floor(math.ceil(math.sqrt(E)) / 4)
        try:
            from rogueeditor.catalog import nature_multipliers_by_id
            nid = self._get_nature_id()
            mults = nature_multipliers_by_id().get(nid or -1, [1.0] * 6)
        except Exception:
            mults = [1.0] * 6
        hp = math.floor((((2 * (base[0] + ivs[0])) + ev_effective(0)) * level) / 100) + level + 10
        out = [hp]
        for i in range(1, 6):
            val = math.floor((((2 * (base[i] + ivs[i])) + ev_effective(0)) * level) / 100) + 5
            m = mults[i] if i < len(mults) else 1.0
            val = math.floor(val * m + 1e-6)
            out.append(val)
        # Apply item multipliers (forward)
        try:
            sel = self.team_list.curselection()[0]
            mon = self.party[sel]
            item_mults = self._item_stat_multipliers(mon)
            out = [math.floor(out[i] * item_mults[i] + 1e-6) for i in range(6)]
        except Exception:
            pass
        return out

    def _init_base_and_update(self):
        try:
            sel = self.team_list.curselection()[0]
            mon = self.party[sel]
        except Exception:
            return
        ivs = self._parse_ivs()
        if not ivs:
            return
        lvl = self._get_level()
        # Prefer catalog base stats if available
        base_from_catalog = None
        try:
            did = mon.get('species') or mon.get('dexId') or mon.get('speciesId')
            if did is not None:
                from rogueeditor.base_stats import get_base_stats_by_species_id
                base_from_catalog = get_base_stats_by_species_id(int(did))
        except Exception:
            base_from_catalog = None
        if base_from_catalog and len(base_from_catalog) == 6:
            self._base_stats = base_from_catalog
        else:
            actual = self._extract_actual_stats(mon)
            if actual:
                self._base_stats = self._infer_base_stats(lvl, ivs, actual)
            else:
                self._base_stats = [50, 50, 50, 50, 50, 50]
        self._update_calculated_stats()

    def _update_calculated_stats(self):
        ivs = self._parse_ivs()
        base = getattr(self, '_base_stats', None)
        if not ivs or not base or len(base) != 6:
            for lbl in getattr(self, 'stat_lbls', []):
                lbl.configure(text='-')
            return
        lvl = self._get_level()
        vals = self._compute_stats(base, lvl, ivs)
        # Show +/- markers for nature effects on non-HP stats
        try:
            from rogueeditor.catalog import nature_multipliers_by_id
            arr = nature_multipliers_by_id().get(self._get_nature_id() or -1, [1.0]*6)
        except Exception:
            arr = [1.0]*6
        for i, lbl in enumerate(self.stat_lbls):
            suffix = ""
            if i > 0:
                if abs(arr[i]-1.1) < 1e-6:
                    suffix = " (+)"
                elif abs(arr[i]-0.9) < 1e-6:
                    suffix = " (-)"
            lbl.configure(text=f"{vals[i]}{suffix}")

    def _on_nature_change(self):
        # Recalc displays when nature changes
        self._update_calculated_stats()
        try:
            from rogueeditor.catalog import nature_multipliers_by_id
            arr = nature_multipliers_by_id().get(self._get_nature_id() or -1, [1.0]*6)
        except Exception:
            arr = [1.0]*6
        self._update_nature_hint(arr)

    def _update_nature_hint(self, arr: list[float]):
        labs = ["HP","Atk","Def","SpA","SpD","Spe"]
        up = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-1.1)<1e-6), None)
        dn = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-0.9)<1e-6), None)
        if not up or not dn or up == dn:
            self.nature_hint.configure(text="neutral")
        else:
            self.nature_hint.configure(text=f"+{up} / -{dn}")

    def _get_nature_id(self) -> int | None:
        raw = self.nature_cb.get().strip()
        if not raw:
            return None
        if raw.endswith(')') and '(' in raw:
            try:
                return int(raw.rsplit('(', 1)[1].rstrip(')'))
            except Exception:
                pass
        try:
            from rogueeditor.catalog import load_nature_catalog
            name_to_id, _ = load_nature_catalog()
            key = raw.strip().lower().replace(' ', '_')
            return int(name_to_id.get(key)) if key in name_to_id else None
        except Exception:
            return None

    def _on_move_ac_change(self, idx: int):
        self._update_move_label(idx)

    def _update_move_label(self, idx: int):
        if 0 <= idx < len(self.move_acs):
            ac = self.move_acs[idx]
            text = ac.get().strip()
            mid = None
            if text.isdigit():
                mid = int(text)
            else:
                if text.endswith(')') and '(' in text:
                    try:
                        mid = int(text.rsplit('(',1)[1].rstrip(')'))
                    except Exception:
                        mid = None
                if mid is None:
                    key = text.lower().replace(' ', '_')
                    mid = self.move_name_to_id.get(key)
            label = ''
            if isinstance(mid, int):
                name = self.move_id_to_name.get(mid, str(mid))
                label = f"{name} (#{mid})"
            self.move_lbls[idx].configure(text=label)

    def _update_ability_label(self):
        try:
            raw = (self.ability_ac.get() or '').strip()
            aid = None
            if raw.isdigit():
                aid = int(raw)
            else:
                if raw.endswith(')') and '(' in raw:
                    try:
                        aid = int(raw.rsplit('(',1)[1].rstrip(')'))
                    except Exception:
                        aid = None
            label = ''
            if isinstance(aid, int):
                name = (getattr(self, 'ability_id_to_name', {}) or {}).get(aid) or ''
                label = f"{name} (#{aid})" if name else f"#{aid}"
            self.ability_label.configure(text=label)
        except Exception:
            try:
                self.ability_label.configure(text="")
            except Exception:
                pass

    def _pick_from_catalog(self, ac: AutoCompleteEntry, name_to_id: dict[str, int], title: str):
        sel = CatalogSelectDialog.select(self, name_to_id, title)
        if sel is not None:
            # Always set the numeric id into the field; update label next to it
            ac.set_value(str(sel))
            try:
                # If this is a move field, refresh its label
                if hasattr(self, 'move_acs') and ac in getattr(self, 'move_acs', []):
                    idx = self.move_acs.index(ac)
                    self._update_move_label(idx)
                if hasattr(self, 'ability_ac') and ac is self.ability_ac:
                    self._update_ability_label()
            except Exception:
                pass
    def _item_stat_multipliers(self, mon: dict) -> list[float]:
        out = [1.0] * 6
        try:
            mon_id = mon.get('id')
            mods = self.data.get('modifiers') or []
            type_to_indices = {
                'CHOICE_BAND': [1],
                'MUSCLE_BAND': [1],
                'CHOICE_SPECS': [3],
                'WISE_GLASSES': [3],
                'CHOICE_SCARF': [5],
                'EVIOLITE': [2, 4],
            }
            from rogueeditor.catalog import load_stat_catalog
            _, stat_id_to_name = load_stat_catalog()
            name_to_idx = {'hp': 0, 'attack': 1, 'defense': 2, 'sp_attack': 3, 'sp_defense': 4, 'speed': 5}
            for m in mods:
                if not isinstance(m, dict):
                    continue
                args = m.get('args') or []
                if not (args and isinstance(args, list) and isinstance(args[0], int) and args[0] == mon_id):
                    continue
                tid = str(m.get('typeId') or '').upper()
                try:
                    stacks = int(m.get('stackCount') or 0)
                except Exception:
                    stacks = 0
                if stacks <= 0:
                    continue
                indices = []
                if tid == 'BASE_STAT_BOOSTER':
                    sid = None
                    if len(args) >= 2 and isinstance(args[1], int):
                        sid = args[1]
                    elif m.get('typePregenArgs') and isinstance(m.get('typePregenArgs'), list):
                        try:
                            sid = int(m.get('typePregenArgs')[0])
                        except Exception:
                            sid = None
                    if isinstance(sid, int):
                        name = (stat_id_to_name.get(int(sid), '') or '').strip().lower().replace(' ', '_')
                        if name in name_to_idx:
                            indices = [name_to_idx[name]]
                else:
                    indices = type_to_indices.get(tid, [])
                if not indices:
                    continue
                factor = (1.1) ** stacks
                for i in indices:
                    if 0 <= i < 6:
                        out[i] *= factor
        except Exception:
            return [1.0] * 6
        return out
