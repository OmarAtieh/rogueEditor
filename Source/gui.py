from __future__ import annotations

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import math

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.utils import (
    list_usernames,
    sanitize_username,
    save_client_session_id,
    load_client_session_id,
    set_user_csid,
    trainer_save_path,
    slot_save_path,
)
from rogueeditor.catalog import (
    load_move_catalog,
    load_ability_catalog,
    load_nature_catalog,
    load_ability_attr_mask,
    load_item_catalog,
)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("rogueEditor GUI")
        self.geometry("900x600")
        self.minsize(700, 480)
        self.api: PokerogueAPI | None = None
        self.editor: Editor | None = None
        self.username: str | None = None

        self._build_login()
        self._build_actions()
        self._build_console()

    # --- UI builders ---
    def _build_login(self):
        frm = ttk.LabelFrame(self, text="Login")
        frm.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(frm, text="User:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.user_combo = ttk.Combobox(frm, values=list_usernames(), state="readonly")
        self.user_combo.grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Button(frm, text="New User", command=self._new_user_dialog).grid(row=0, column=2, padx=4)

        ttk.Label(frm, text="Password:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
        self.pass_entry = ttk.Entry(frm, show="*")
        self.pass_entry.grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(frm, text="clientSessionId (optional):").grid(row=2, column=0, sticky=tk.W, padx=4, pady=4)
        self.csid_entry = ttk.Entry(frm, width=50)
        self.csid_entry.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=4, pady=4)

        ttk.Button(frm, text="Login", command=self._login).grid(row=3, column=1, pady=6)

        self.status_var = tk.StringVar(value="Status: Not logged in")
        ttk.Label(frm, textvariable=self.status_var).grid(row=4, column=0, columnspan=3, sticky=tk.W, padx=4, pady=4)
        # Quick Actions toolbar (prominent backup/restore)
        qa = ttk.Frame(frm)
        qa.grid(row=5, column=0, columnspan=3, sticky=tk.W, padx=4, pady=4)
        self.btn_backup = ttk.Button(qa, text="Backup All", command=self._safe(self._backup), state=tk.DISABLED)
        self.btn_backup.pack(side=tk.LEFT, padx=4)
        self.btn_restore = ttk.Button(qa, text="Restore Backup", command=self._safe(self._restore_dialog2), state=tk.DISABLED)
        self.btn_restore.pack(side=tk.LEFT, padx=4)
        self.backup_status_var = tk.StringVar(value="Last backup: none")
        ttk.Label(qa, textvariable=self.backup_status_var).pack(side=tk.LEFT, padx=8)

    def _build_actions(self):
        # Scrollable container for actions
        container = ttk.LabelFrame(self, text="Actions")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        self.actions_frame = inner

        # Data IO
        box1 = ttk.LabelFrame(inner, text="Data IO")
        box1.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(box1, text="Verify System Session", command=self._safe(self._verify)).grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Button(box1, text="Dump Trainer", command=self._safe(self._dump_trainer)).grid(row=0, column=1, padx=4, pady=4, sticky=tk.W)
        # Slot selection dropdown for dump/update
        ttk.Label(box1, text="Slot:").grid(row=0, column=2, sticky=tk.E)
        self.slot_var = tk.StringVar(value="1")
        self.slot_combo = ttk.Combobox(box1, textvariable=self.slot_var, values=["1","2","3","4","5"], width=4, state="readonly")
        self.slot_combo.grid(row=0, column=3, sticky=tk.W)
        ttk.Button(box1, text="Dump Slot", command=self._safe(self._dump_slot_selected)).grid(row=0, column=4, padx=4, pady=4, sticky=tk.W)
        # Upload actions
        ttk.Button(box1, text="Upload Trainer (trainer.json)", command=self._safe(self._update_trainer)).grid(row=1, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Button(box1, text="Upload Slot (slot N.json)", command=self._safe(self._update_slot_selected)).grid(row=1, column=1, padx=4, pady=4, sticky=tk.W)
        ttk.Button(box1, text="Restore from Backup", command=self._safe(self._restore_dialog2)).grid(row=1, column=2, padx=4, pady=4, sticky=tk.W)
        # Tools
        ttk.Button(box1, text="Upload Local Changes...", command=self._safe(self._upload_local_dialog)).grid(row=2, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Button(box1, text="Open Local Dump...", command=self._safe(self._open_local_dump_dialog)).grid(row=2, column=1, padx=4, pady=4, sticky=tk.W)

        # Slots summary
        boxS = ttk.LabelFrame(inner, text="Slots")
        boxS.pack(fill=tk.BOTH, padx=6, pady=6)
        cols = ("slot", "party", "playtime", "local")
        self.slot_tree = ttk.Treeview(boxS, columns=cols, show="headings", height=6)
        for c, w in (("slot", 60), ("party", 80), ("playtime", 120), ("local", 220)):
            self.slot_tree.heading(c, text=c.capitalize())
            self.slot_tree.column(c, width=w, anchor=tk.W)
        self.slot_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(boxS, orient="vertical", command=self.slot_tree.yview)
        self.slot_tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.slot_tree.tag_configure('empty', foreground='grey')
        self.slot_tree.bind('<<TreeviewSelect>>', self._on_slot_select)
        ttk.Button(boxS, text="Refresh Slots", command=self._safe(self._refresh_slots)).pack(anchor=tk.W, padx=4, pady=4)

        # Team
        box2 = ttk.LabelFrame(inner, text="Active Run Team")
        box2.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(box2, text="Analyze Team", command=self._analyze_team_dialog).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Edit Team", command=self._safe(self._edit_team_dialog)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Analyze Run Conditions", command=self._analyze_run_conditions).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Edit Run Weather", command=self._safe(self._edit_run_weather)).pack(side=tk.LEFT, padx=4, pady=4)

        # Modifiers
        box3 = ttk.LabelFrame(inner, text="Modifiers / Items")
        box3.pack(fill=tk.BOTH, padx=6, pady=6)
        # Modifiers manager
        mod_btns = ttk.Frame(box3)
        mod_btns.pack(fill=tk.X)
        ttk.Button(mod_btns, text="Open Modifiers Manager", command=self._safe(self._open_mod_mgr)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(mod_btns, text="List Modifiers", command=self._list_mods_dialog).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(mod_btns, text="Analyze Modifiers", command=self._analyze_mods_dialog).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(mod_btns, text="Add Item to Mon", command=self._safe(self._add_item_dialog)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(mod_btns, text="Remove Item from Mon", command=self._safe(self._remove_item_dialog)).pack(side=tk.LEFT, padx=4, pady=4)

        # Starters
        box4 = ttk.LabelFrame(inner, text="Starters")
        box4.pack(fill=tk.X, padx=6, pady=6)
        # Pokemon selector
        from rogueeditor.utils import load_pokemon_index
        dex = (load_pokemon_index().get("dex") or {})
        # Map name->id (int), keys lower
        name_to_id = {k.lower(): int(v) for k, v in dex.items()}
        self._starter_name_to_id = name_to_id
        ttk.Label(box4, text="Pokemon:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_ac = AutoCompleteEntry(box4, name_to_id, width=30)
        self.starter_ac.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Button(box4, text="Pick...", command=self._pick_starter_from_catalog).grid(row=0, column=2, sticky=tk.W, padx=4, pady=2)
        # Attributes
        ttk.Label(box4, text="abilityAttr:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        # abilityAttr presets via checkboxes
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        self.aa1 = tk.IntVar(value=1)
        self.aa2 = tk.IntVar(value=1)
        self.aah = tk.IntVar(value=1)
        ttk.Checkbutton(box4, text="Ability 1", variable=self.aa1).grid(row=1, column=1, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Ability 2", variable=self.aa2).grid(row=1, column=2, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Hidden", variable=self.aah).grid(row=1, column=3, sticky=tk.W, padx=4)

        ttk.Label(box4, text="passiveAttr:").grid(row=2, column=0, sticky=tk.W, padx=4, pady=2)
        # Passive presets (UNLOCKED=1, ENABLED=2)
        self.p_unlocked = tk.IntVar(value=1)
        self.p_enabled = tk.IntVar(value=0)
        ttk.Checkbutton(box4, text="Unlocked", variable=self.p_unlocked).grid(row=2, column=1, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Enabled", variable=self.p_enabled).grid(row=2, column=2, sticky=tk.W, padx=4)

        ttk.Label(box4, text="valueReduction:").grid(row=3, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_value_reduction = ttk.Entry(box4, width=8)
        self.starter_value_reduction.insert(0, "0")
        self.starter_value_reduction.grid(row=3, column=1, sticky=tk.W, padx=4, pady=2)

        ttk.Button(box4, text="Apply Starter Attributes", command=self._safe(self._apply_starter_attrs)).grid(row=4, column=1, sticky=tk.W, padx=4, pady=4)
        ttk.Button(box4, text="Unlock All Starters", command=self._safe(self._unlock_all_starters)).grid(row=4, column=2, sticky=tk.W, padx=4, pady=4)
        ttk.Button(box4, text="Unlock Starter...", command=self._safe(self._unlock_starter_dialog)).grid(row=4, column=3, sticky=tk.W, padx=4, pady=4)

        # Candies increment
        ttk.Label(box4, text="Candies Δ:").grid(row=5, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_candy_delta = ttk.Entry(box4, width=8)
        self.starter_candy_delta.insert(0, "0")
        self.starter_candy_delta.grid(row=5, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Button(box4, text="Increment Candies", command=self._safe(self._inc_starter_candies)).grid(row=5, column=2, sticky=tk.W, padx=4, pady=2)

        # Gacha tickets increment
        ttk.Label(box4, text="Gacha Δ C/R/E/L:").grid(row=6, column=0, sticky=tk.W, padx=4, pady=2)
        self.gacha_d0 = ttk.Entry(box4, width=5); self.gacha_d0.insert(0, "0"); self.gacha_d0.grid(row=6, column=1, sticky=tk.W, padx=2)
        self.gacha_d1 = ttk.Entry(box4, width=5); self.gacha_d1.insert(0, "0"); self.gacha_d1.grid(row=6, column=1, sticky=tk.W, padx=2, columnspan=1)
        self.gacha_d1.place(x=self.gacha_d0.winfo_x()+60, y=self.gacha_d0.winfo_y())
        self.gacha_d2 = ttk.Entry(box4, width=5); self.gacha_d2.insert(0, "0")
        self.gacha_d3 = ttk.Entry(box4, width=5); self.gacha_d3.insert(0, "0")
        # Simpler layout vertically
        ttk.Label(box4, text="Common Δ:").grid(row=7, column=0, sticky=tk.W, padx=4)
        self.gacha_d0.grid(row=7, column=1, sticky=tk.W)
        ttk.Label(box4, text="Rare Δ:").grid(row=8, column=0, sticky=tk.W, padx=4)
        self.gacha_d1.grid(row=8, column=1, sticky=tk.W)
        ttk.Label(box4, text="Epic Δ:").grid(row=9, column=0, sticky=tk.W, padx=4)
        self.gacha_d2.grid(row=9, column=1, sticky=tk.W)
        ttk.Label(box4, text="Legendary Δ:").grid(row=10, column=0, sticky=tk.W, padx=4)
        self.gacha_d3.grid(row=10, column=1, sticky=tk.W)
        ttk.Button(box4, text="Apply Gacha Δ", command=self._safe(self._apply_gacha_delta)).grid(row=11, column=1, sticky=tk.W, padx=4, pady=4)
        # Passives unlock + Pokedex list
        ttk.Button(box4, text="Unlock All Passives (mask=7)", command=self._safe(self._unlock_all_passives)).grid(row=11, column=2, sticky=tk.W, padx=4, pady=4)
        ttk.Button(box4, text="Show Pokedex (names→IDs)", command=self._safe(self._pokedex_list)).grid(row=11, column=3, sticky=tk.W, padx=4, pady=4)
        # Eggs
        ttk.Button(box4, text="Hatch All Eggs After Next Fight", command=self._safe(self._hatch_eggs)).grid(row=12, column=1, sticky=tk.W, padx=4, pady=4)

    def _build_console(self):
        frm = ttk.LabelFrame(self, text="Console")
        frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.console = tk.Text(frm, height=12)
        self.console.pack(fill=tk.BOTH, expand=True)
        # Busy progress bar
        self.progress = ttk.Progressbar(frm, mode='indeterminate')
        self.progress.pack(fill=tk.X, padx=4, pady=4)
        self._busy_count = 0
        # Enable mouse wheel scrolling on canvas and trees
        def _on_mousewheel(event):
            try:
                delta = int(event.delta / 120)
            except Exception:
                delta = 1 if event.num == 4 else -1
            widgets = [w for w in (self.actions_frame.master, self.slot_tree) if w.winfo_ismapped()]
            for w in widgets:
                if hasattr(w, 'yview_scroll'):
                    w.yview_scroll(-delta, 'units')
        self.bind_all('<MouseWheel>', _on_mousewheel)
        self.bind_all('<Button-4>', _on_mousewheel)
        self.bind_all('<Button-5>', _on_mousewheel)

    # --- Helpers ---
    def _log(self, text: str):
        def append():
            self.console.insert(tk.END, text + "\n")
            self.console.see(tk.END)
        self.after(0, append)

    def _show_busy(self):
        self._busy_count += 1
        if self._busy_count == 1:
            self.progress.start(10)

    def _hide_busy(self):
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            self.progress.stop()

    def _run_async(self, desc: str, work, on_done=None):
        self._show_busy()
        self._log(desc)
        def runner():
            err = None
            try:
                work()
            except Exception as e:
                err = e
            def finish():
                self._hide_busy()
                if err:
                    messagebox.showerror("Error", str(err))
                    self._log(f"[ERROR] {err}")
                elif on_done:
                    on_done()
            self.after(0, finish)
        threading.Thread(target=runner, daemon=True).start()

    def _safe(self, fn):
        def wrapper():
            if not self.editor:
                messagebox.showwarning("Not logged in", "Please login first")
                return
            self._run_async("Working...", fn)
        return wrapper

    def _show_text_dialog(self, title: str, content: str):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry('600x400')
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(frm, wrap='word')
        sb = ttk.Scrollbar(frm, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.insert(tk.END, content)
        txt.config(state='disabled')
        ttk.Button(top, text='Close', command=top.destroy).pack(pady=6)

    def _run_and_show_output(self, title: str, func):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        def work():
            with redirect_stdout(buf):
                func()
        def done():
            out = buf.getvalue().strip() or '(no output)'
            self._show_text_dialog(title, out)
        self._run_async(title, work, done)

    def _pick_starter_from_catalog(self):
        # Build pretty display mapping using current dex mapping
        try:
            name_to_id = getattr(self, '_starter_name_to_id', {}) or {}
            if not name_to_id:
                from rogueeditor.utils import load_pokemon_index
                dex = (load_pokemon_index().get('dex') or {})
                name_to_id = {k.lower(): int(v) for k, v in dex.items()}
        except Exception:
            name_to_id = {}
        # Convert to pretty names for display
        pretty_map = {k.replace('_', ' ').title(): v for k, v in name_to_id.items()}
        sel = CatalogSelectDialog.select(self, pretty_map, 'Select Starter')
        if sel is None:
            return
        # Find pretty name
        chosen = None
        for n, i in pretty_map.items():
            if i == sel:
                chosen = n
                break
        if chosen:
            self.starter_ac.set_value(chosen)

    def _analyze_mods_dialog(self):
        if not self.editor:
            messagebox.showwarning('Not logged in', 'Please login first')
            return
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if not slot:
            return
        def work():
            data = self.api.get_slot(slot)
            mods = data.get('modifiers') or []
            total = len(mods)
            type_counts: dict[str, int] = {}
            player_cnt = 0
            target_cnt = 0
            target_map: dict[int, int] = {}
            for m in mods:
                if not isinstance(m, dict):
                    continue
                t = str(m.get('typeId') or m.get('type') or m.get('id') or 'UNKNOWN')
                type_counts[t] = type_counts.get(t, 0) + 1
                if m.get('player'):
                    player_cnt += 1
                args = m.get('args') or []
                if isinstance(args, list) and args and isinstance(args[0], int):
                    target_cnt += 1
                    target_map[args[0]] = target_map.get(args[0], 0) + 1
            # Build report
            lines: list[str] = []
            lines.append(f"Slot {slot} Modifiers Summary")
            lines.append("".rstrip())
            lines.append(f"Total modifiers: {total}")
            lines.append(f"Player-only: {player_cnt}")
            lines.append(f"Targeted (pokemon): {target_cnt}")
            lines.append("")
            lines.append("By typeId (count):")
            for t, c in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0])):
                lines.append(f"  - {t}: {c}")
            if target_map:
                lines.append("")
                lines.append("Top targets (party ids):")
                for tid, c in sorted(target_map.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
                    lines.append(f"  - id {tid}: {c}")
            report = "\n".join(lines)
            self.after(0, lambda: self._show_text_dialog(f"Analyze Modifiers - Slot {slot}", report))
        self._run_async(f"Analyzing modifiers for slot {slot}...", work)

    # --- Actions ---
    def _new_user_dialog(self):
        top = tk.Toplevel(self)
        top.title("New User")
        ttk.Label(top, text="Username:").pack(padx=6, pady=6)
        ent = ttk.Entry(top)
        ent.pack(padx=6, pady=6)
        def ok():
            user = sanitize_username(ent.get().strip())
            vals = list_usernames()
            vals.append(user)
            self.user_combo["values"] = sorted(set(vals))
            self.user_combo.set(user)
            top.destroy()
        ttk.Button(top, text="OK", command=ok).pack(pady=6)

    def _login(self):
        user = self.user_combo.get().strip()
        if not user:
            messagebox.showwarning("Missing", "Select or create a username")
            return
        pwd = self.pass_entry.get()
        if not pwd:
            messagebox.showwarning("Missing", "Enter password")
            return
        csid_input = self.csid_entry.get().strip()
        def work():
            api = PokerogueAPI(user, pwd)
            api.login()
            csid = csid_input or load_client_session_id() or None
            if csid:
                api.client_session_id = csid
                try:
                    save_client_session_id(csid)
                    set_user_csid(user, csid)
                except Exception:
                    pass
            self.api = api
            self.editor = Editor(api)
            self.username = user
        def done():
            self.status_var.set(f"Status: Logged in as {user}")
            self._log(f"Logged in as {user}")
            # Enable backup/restore and update backup status
            try:
                self.btn_backup.configure(state=tk.NORMAL)
                self.btn_restore.configure(state=tk.NORMAL)
            except Exception:
                pass
            self._update_backup_status()
        self._run_async("Logging in...", work, done)

    def _verify(self):
        self.editor.system_verify()
        self._log("System verify executed.")

    def _dump_trainer(self):
        self.editor.dump_trainer()
        self._log(f"Dumped trainer to {trainer_save_path(self.username)}")

    def _dump_slot_dialog(self):
        slot = self._ask_slot()
        if slot:
            self.editor.dump_slot(slot)
            self._log(f"Dumped slot {slot} to {slot_save_path(self.username, slot)}")
    def _dump_slot_selected(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            messagebox.showwarning("Invalid", "Invalid slot")
            return
        self.editor.dump_slot(slot)
        self._log(f"Dumped slot {slot} to {slot_save_path(self.username, slot)}")

    def _update_trainer(self):
        if messagebox.askyesno("Confirm", "Update trainer from file?"):
            try:
                self.editor.update_trainer_from_file()
                self._log("Trainer updated from file.")
                messagebox.showinfo("Upload", "Trainer uploaded successfully.")
            except Exception as e:
                messagebox.showerror("Upload failed", str(e))

    def _update_slot_dialog(self):
        slot = self._ask_slot()
        if slot and messagebox.askyesno("Confirm", f"Update slot {slot} from file?"):
            self.editor.update_slot_from_file(slot)
            self._log(f"Slot {slot} updated from file.")
    def _update_slot_selected(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            messagebox.showwarning("Invalid", "Invalid slot")
            return
        if messagebox.askyesno("Confirm", f"Update slot {slot} from file?"):
            try:
                self.editor.update_slot_from_file(slot)
                self._log(f"Slot {slot} updated from file.")
                messagebox.showinfo("Upload", f"Slot {slot} uploaded successfully.")
            except Exception as e:
                messagebox.showerror("Upload failed", str(e))
                return

    def _hatch_eggs(self):
        try:
            self.editor.hatch_all_eggs()
            self._log("Eggs set to hatch after next fight.")
            messagebox.showinfo("Eggs", "All eggs will hatch after the next fight.")
        except Exception as e:
            messagebox.showerror("Hatch failed", str(e))

    def _open_local_dump_dialog(self):
        # Opens trainer.json or slot N.json in the OS default editor
        from rogueeditor.utils import trainer_save_path, slot_save_path
        if not self.username:
            messagebox.showwarning("Missing", "Please log in/select a user first.")
            return
        top = tk.Toplevel(self)
        top.title("Open Local Dump")
        ttk.Label(top, text="Open which file?").grid(row=0, column=0, columnspan=3, padx=6, pady=6, sticky=tk.W)
        choice = tk.StringVar(value='trainer')
        ttk.Radiobutton(top, text="Trainer (trainer.json)", variable=choice, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Radiobutton(top, text="Slot (slot N.json)", variable=choice, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6)
        ttk.Label(top, text="Slot:").grid(row=2, column=1, sticky=tk.E)
        slot_var = tk.StringVar(value=self.slot_var.get())
        ttk.Combobox(top, textvariable=slot_var, values=["1","2","3","4","5"], width=4, state='readonly').grid(row=2, column=2, sticky=tk.W)

        def open_path(path: str):
            if sys.platform.startswith('win'):
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except OSError as e:
                    messagebox.showerror("Open failed", str(e))
            elif sys.platform == 'darwin':
                try:
                    subprocess.run(['open', path], check=False)
                except Exception as e:
                    messagebox.showerror("Open failed", str(e))
            else:
                try:
                    subprocess.run(['xdg-open', path], check=False)
                except Exception as e:
                    messagebox.showerror("Open failed", str(e))

        def do_open():
            target = choice.get()
            if target == 'trainer':
                p = trainer_save_path(self.username)
            else:
                try:
                    s = int(slot_var.get())
                except Exception:
                    messagebox.showwarning("Invalid", "Invalid slot")
                    return
                p = slot_save_path(self.username, s)
            if not os.path.exists(p):
                messagebox.showwarning("Not found", f"{p} does not exist. Dump first.")
                return
            open_path(p)
            top.destroy()

        ttk.Button(top, text="Open", command=do_open).grid(row=3, column=0, padx=6, pady=10, sticky=tk.W)
        ttk.Button(top, text="Close", command=top.destroy).grid(row=3, column=1, padx=6, pady=10, sticky=tk.W)

    def _on_slot_select(self, event=None):
        sel = self.slot_tree.selection()
        if not sel:
            return
        item = self.slot_tree.item(sel[0])
        values = item.get('values') or []
        if values:
            self.slot_var.set(str(values[0]))

    def _refresh_slots(self):
        import time
        from rogueeditor.utils import slot_save_path
        def work():
            rows = []
            for i in range(1, 6):
                party_ct = '-'
                playtime = '-'
                empty = False
                try:
                    data = self.api.get_slot(i)
                    party = data.get('party') or []
                    party_ct = len(party)
                    pt = data.get('playTime') or 0
                    h = int(pt) // 3600
                    m = (int(pt) % 3600) // 60
                    s = int(pt) % 60
                    playtime = f"{h:02d}:{m:02d}:{s:02d}"
                    empty = (party_ct == 0 and pt == 0)
                except Exception:
                    empty = True
                    party_ct = 0
                    playtime = '-'
                # Local dump time
                local = '-'
                p = slot_save_path(self.username, i)
                if os.path.exists(p):
                    ts = os.path.getmtime(p)
                    local = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                rows.append((i, party_ct, playtime, local, empty))
            def update():
                for r in self.slot_tree.get_children():
                    self.slot_tree.delete(r)
                for (slot, party_ct, playtime, local, empty) in rows:
                    tags = ('empty',) if empty else ()
                    self.slot_tree.insert('', 'end', values=(slot, party_ct, playtime, local), tags=tags)
            self.after(0, update)
        self._run_async("Loading slots...", work)

    def _backup(self):
        def work():
            path = self.editor.backup_all()
            self._log(f"Backup created: {path}")
        def done():
            self._update_backup_status()
        self._run_async("Creating backup...", work, done)

    def _restore_dialog(self):
        base = os.path.join("Source", "saves", self.username, "backups")
        if not os.path.isdir(base):
            messagebox.showinfo("No backups", "No backups found.")
            return
        dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
        if not dirs:
            messagebox.showinfo("No backups", "No backups found.")
            return
        top = tk.Toplevel(self)
        top.title("Select Backup")
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        lb = tk.Listbox(frm, height=12)
        sb = ttk.Scrollbar(frm, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for d in dirs:
            lb.insert(tk.END, d)
        def restore():
            sel = lb.curselection()
            if not sel:
                return
            backup_dir = os.path.join(base, lb.get(sel[0]))
            # Options dialog for scope
            scope = tk.StringVar(value='all')
            opt = tk.Toplevel(self)
            opt.title("Restore Options")
            ttk.Radiobutton(opt, text="Restore ALL (trainer + slots)", variable=scope, value='all').grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Trainer ONLY", variable=scope, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Specific Slot", variable=scope, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Label(opt, text="Slot:").grid(row=2, column=1, sticky=tk.E)
            slot_var = tk.StringVar(value='1')
            slot_cb = ttk.Combobox(opt, textvariable=slot_var, values=["1","2","3","4","5"], width=4, state='readonly')
            slot_cb.grid(row=2, column=2, sticky=tk.W)
            def do_restore():
                choice = scope.get()
                name = lb.get(sel[0])
                if not messagebox.askyesno("Confirm", f"Restore ({choice}) from {name}? This overwrites server state."):
                    return
                if choice == 'all':
                    self._run_async(
                        "Restoring backup (all)...",
                        lambda: self.editor.restore_from_backup(backup_dir),
                        lambda: self._log(f"Restored backup {backup_dir} (all)")
                    )
                elif choice == 'trainer':
                    def work():
                        from rogueeditor.utils import load_json
                        tp = os.path.join(backup_dir, 'trainer.json')
                        if os.path.exists(tp):
                            data = load_json(tp)
                            self.api.update_trainer(data)
                    self._run_async("Restoring backup (trainer)...", work, lambda: self._log(f"Restored trainer from {backup_dir}"))
                else:
                    try:
                        s = int(slot_var.get())
                    except Exception:
                        messagebox.showwarning("Invalid", "Invalid slot")
                        return
                    def work():
                        from rogueeditor.utils import load_json
                        sp = os.path.join(backup_dir, f"slot {s}.json")
                        if os.path.exists(sp):
                            data = load_json(sp)
                            self.api.update_slot(s, data)
                    self._run_async("Restoring backup (slot)...", work, lambda: self._log(f"Restored slot {s} from {backup_dir}"))
                opt.destroy(); top.destroy()
            ttk.Button(opt, text="Restore", command=do_restore).grid(row=3, column=0, columnspan=3, pady=8)
        def delete_backup():
            sel = lb.curselection()
            if not sel:
                return
            target = lb.get(sel[0])
            backup_dir = os.path.join(base, target)
            dirs2 = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            is_last = len(dirs2) == 1
            is_latest = (dirs2 and target == dirs2[-1])
            msg = f"Delete backup {target}?"
            if is_last:
                msg += "\nWARNING: This is the last backup."
            elif is_latest:
                msg += "\nWarning: This is the most recent backup."
            if not messagebox.askyesno("Confirm Delete", msg):
                return
            import shutil
            try:
                shutil.rmtree(backup_dir)
                self._log(f"Deleted backup {target}")
                lb.delete(sel[0])
                self._update_backup_status()
            except Exception as e:
                messagebox.showerror("Delete failed", str(e))
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(btns, text="Restore", command=restore).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Delete", command=delete_backup).pack(side=tk.LEFT, padx=4)

    def _update_backup_status(self):
        try:
            from rogueeditor.utils import user_save_dir
            if not self.username:
                self.backup_status_var.set("Last backup: none")
                return
            base = os.path.join(user_save_dir(self.username), "backups")
            if not os.path.isdir(base):
                self.backup_status_var.set("Last backup: none")
                return
            dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            self.backup_status_var.set(f"Last backup: {dirs[-1]}") if dirs else self.backup_status_var.set("Last backup: none")
        except Exception:
            self.backup_status_var.set("Last backup: unknown")

    def _restore_dialog2(self):
        from rogueeditor.utils import user_save_dir, load_json
        base = os.path.join(user_save_dir(self.username or ""), "backups")
        if not os.path.isdir(base):
            messagebox.showinfo("No backups", "No backups found.")
            return
        dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
        if not dirs:
            messagebox.showinfo("No backups", "No backups found.")
            return
        top = tk.Toplevel(self)
        top.title("Select Backup")
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        lb = tk.Listbox(frm, height=12)
        sb = ttk.Scrollbar(frm, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for d in dirs:
            lb.insert(tk.END, d)
        def restore():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            backup_dir = os.path.join(base, name)
            scope = tk.StringVar(value='all')
            opt = tk.Toplevel(self)
            opt.title("Restore Options")
            ttk.Radiobutton(opt, text="Restore ALL (trainer + slots)", variable=scope, value='all').grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Trainer ONLY", variable=scope, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Specific Slot", variable=scope, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Label(opt, text="Slot:").grid(row=2, column=1, sticky=tk.E)
            slot_var = tk.StringVar(value='1')
            slot_cb = ttk.Combobox(opt, textvariable=slot_var, values=["1","2","3","4","5"], width=4, state='readonly')
            slot_cb.grid(row=2, column=2, sticky=tk.W)
            def do_restore():
                choice = scope.get()
                if not messagebox.askyesno("Confirm", f"Restore ({choice}) from {name}? This overwrites server state."):
                    return
                if choice == 'all':
                    self._run_async("Restoring backup (all)...", lambda: self.editor.restore_from_backup(backup_dir), lambda: self._log(f"Restored backup {name} (all)"))
                elif choice == 'trainer':
                    def work():
                        tp = os.path.join(backup_dir, 'trainer.json')
                        if os.path.exists(tp):
                            data = load_json(tp)
                            self.api.update_trainer(data)
                    self._run_async("Restoring trainer...", work, lambda: self._log(f"Restored trainer from {name}"))
                else:
                    try:
                        s = int(slot_var.get())
                    except Exception:
                        messagebox.showwarning("Invalid", "Invalid slot")
                        return
                    def work():
                        sp = os.path.join(backup_dir, f"slot {s}.json")
                        if os.path.exists(sp):
                            data = load_json(sp)
                            self.api.update_slot(s, data)
                    self._run_async("Restoring slot...", work, lambda: self._log(f"Restored slot {s} from {name}"))
                opt.destroy(); top.destroy()
            ttk.Button(opt, text="Restore", command=do_restore).grid(row=3, column=0, columnspan=3, pady=8)
        def delete_backup():
            sel = lb.curselection()
            if not sel:
                return
            target = lb.get(sel[0])
            bdir = os.path.join(base, target)
            d2 = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            is_last = (len(d2) == 1)
            is_latest = (d2 and target == d2[-1])
            msg = f"Delete backup {target}?"
            if is_last:
                msg += "\nWARNING: This is the last backup."
            elif is_latest:
                msg += "\nWarning: This is the most recent backup."
            if not messagebox.askyesno("Confirm Delete", msg):
                return
            import shutil
            try:
                shutil.rmtree(bdir)
                self._log(f"Deleted backup {target}")
                lb.delete(sel[0])
                self._update_backup_status()
            except Exception as e:
                messagebox.showerror("Delete failed", str(e))
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(btns, text="Restore", command=restore).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Delete", command=delete_backup).pack(side=tk.LEFT, padx=4)

    def _upload_local_dialog(self):
        # A simple dialog to upload trainer.json and/or selected slot file to server.
        from rogueeditor.utils import trainer_save_path, slot_save_path, load_json
        top = tk.Toplevel(self)
        top.title("Upload Local Changes")
        ttk.Label(top, text="Choose what to upload to the server:").grid(row=0, column=0, columnspan=3, padx=6, pady=6, sticky=tk.W)
        tr_var = tk.BooleanVar(value=True)
        sl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Trainer (trainer.json)", variable=tr_var).grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Label(top, text="Slot:").grid(row=2, column=0, sticky=tk.E, padx=6)
        slot_var = tk.StringVar(value=self.slot_var.get())
        ttk.Combobox(top, textvariable=slot_var, values=["1","2","3","4","5"], width=4, state='readonly').grid(row=2, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text="Upload slot file (slot N.json)", variable=sl_var).grid(row=2, column=2, sticky=tk.W, padx=6)
        def do_upload():
            # Trainer
            if tr_var.get():
                try:
                    tp = trainer_save_path(self.username)
                    if os.path.exists(tp):
                        data = load_json(tp)
                        self.api.update_trainer(data)
                        self._log(f"Uploaded trainer from {tp}")
                    else:
                        messagebox.showwarning("Missing", f"{tp} not found")
                except Exception as e:
                    messagebox.showerror("Trainer upload failed", str(e))
                    return
            # Slot
            if sl_var.get():
                try:
                    s = int(slot_var.get())
                except Exception:
                    messagebox.showwarning("Invalid", "Invalid slot")
                    return
                sp = slot_save_path(self.username, s)
                if os.path.exists(sp):
                    try:
                        data = load_json(sp)
                        self.api.update_slot(s, data)
                        self._log(f"Uploaded slot {s} from {sp}")
                    except Exception as e:
                        messagebox.showerror("Slot upload failed", str(e))
                        return
                else:
                    messagebox.showwarning("Missing", f"{sp} not found")
                    return
            messagebox.showinfo("Upload", "Upload completed.")
            top.destroy()
        ttk.Button(top, text="Upload", command=do_upload).grid(row=3, column=0, padx=6, pady=10, sticky=tk.W)
        ttk.Button(top, text="Close", command=top.destroy).grid(row=3, column=1, padx=6, pady=10, sticky=tk.W)

    def _analyze_team_dialog(self):
        if not self.editor:
            messagebox.showwarning("Not logged in", "Please login first")
            return
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            self._run_and_show_output(f"Team Analysis - Slot {slot}", lambda: self.editor.analyze_team(slot))

    def _analyze_run_conditions(self):
        if not self.editor:
            messagebox.showwarning("Not logged in", "Please login first")
            return
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            self._run_and_show_output(f"Run Conditions - Slot {slot}", lambda: self.editor.analyze_run_conditions(slot))

    def _edit_run_weather(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if not slot:
            return
        # Fetch session and find weather key
        data = self.api.get_slot(slot)
        wkey = None
        for k in ("weather", "weatherType", "currentWeather"):
            if k in data:
                wkey = k
                break
        if not wkey:
            messagebox.showinfo("Run Weather", "Weather field not found in session.")
            return
        from rogueeditor.catalog import load_weather_catalog
        n2i, i2n = load_weather_catalog()
        top = tk.Toplevel(self)
        top.title(f"Edit Run Weather - Slot {slot}")
        ttk.Label(top, text="Weather:").grid(row=0, column=0, padx=6, pady=6)
        items = [f"{name} ({iid})" for name, iid in sorted(n2i.items(), key=lambda kv: kv[0])]
        var = tk.StringVar()
        cb = ttk.Combobox(top, values=items, textvariable=var, width=28)
        cur = data.get(wkey)
        cur_disp = i2n.get(int(cur), str(cur)) if isinstance(cur, int) else str(cur)
        var.set(f"{cur_disp} ({cur})")
        cb.grid(row=0, column=1, padx=6, pady=6)
        def do_apply():
            text = var.get().strip()
            val = None
            if text.endswith(')') and '(' in text:
                try:
                    val = int(text.rsplit('(',1)[1].rstrip(')'))
                except Exception:
                    val = None
            if val is None:
                key = text.strip().lower().replace(' ', '_')
                val = n2i.get(key)
            if not isinstance(val, int):
                messagebox.showwarning('Invalid', 'Select a valid weather')
                return
            data[wkey] = val
            from rogueeditor.utils import slot_save_path, dump_json
            p = slot_save_path(self.api.username, slot)
            dump_json(p, data)
            self._log(f"Updated weather to {val}; wrote {p}")
            if messagebox.askyesno('Upload', 'Upload changes to server?'):
                try:
                    self.api.update_slot(slot, data)
                    messagebox.showinfo('Uploaded', 'Server updated successfully')
                except Exception as e:
                    messagebox.showerror('Upload failed', str(e))
            top.destroy()
        ttk.Button(top, text='Apply', command=do_apply).grid(row=1, column=1, padx=6, pady=6, sticky=tk.W)

    def _edit_team_dialog(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            TeamEditorDialog(self, self.api, self.editor, slot)
            self._log(f"Opened team editor for slot {slot}")

    def _list_mods_dialog(self):
        if not self.editor:
            messagebox.showwarning("Not logged in", "Please login first")
            return
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            self._run_and_show_output(f"Modifiers - Slot {slot}", lambda: self.editor.list_modifiers(slot))

    def _open_mod_mgr(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            ModifiersManagerDialog(self, self.api, self.editor, slot)
            self._log(f"Opened modifiers manager for slot {slot}")

    def _unlock_all_starters(self):
        # Strong warning + typed confirmation
        top = tk.Toplevel(self)
        top.title('Unlock ALL Starters - Confirmation')
        msg = (
            'WARNING:\n\n'
            'This action will UNLOCK ALL STARTERS with perfect IVs and shiny variants.\n'
            'It may significantly impact or ruin your player experience.\n\n'
            'To confirm, type the phrase exactly and check the acknowledgment:'
        )
        ttk.Label(top, text=msg, justify=tk.LEFT, wraplength=520).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
        expected = 'UNLOCK ALL STARTERS'
        ttk.Label(top, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
        phrase_var = tk.StringVar()
        ttk.Entry(top, textvariable=phrase_var, width=34).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
        ack_var = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='I accept the risks and understand this is final.', variable=ack_var).grid(row=2, column=0, columnspan=2, padx=8, pady=6, sticky=tk.W)
        def proceed():
            text = (phrase_var.get() or '').strip()
            if text != expected:
                messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                return
            if not ack_var.get():
                messagebox.showwarning('Not confirmed', 'Please acknowledge the risks to proceed.')
                return
            try:
                self.editor.unlock_all_starters()
                self._log('All starters unlocked (perfect IVs, shinies).')
                messagebox.showinfo('Completed', 'All starters unlocked successfully.')
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))
        ttk.Button(top, text='Cancel', command=top.destroy).grid(row=3, column=0, padx=8, pady=10, sticky=tk.W)
        ttk.Button(top, text='Proceed', command=proceed).grid(row=3, column=1, padx=8, pady=10, sticky=tk.E)

    def _unlock_all_passives(self):
        # Use the selected starter in the autocomplete
        ident = self.starter_ac.get().strip()
        if not ident:
            messagebox.showwarning('Missing', 'Select a Pokemon in the Starters section first.')
            return
        if not messagebox.askyesno('Confirm', f'Unlock all passives for {ident}?'):
            return
        try:
            self.editor.unlock_all_passives(ident, mask=7)
            self._log(f'Unlocked all passives for {ident}.')
        except Exception as e:
            messagebox.showerror('Failed', str(e))

    def _pokedex_list(self):
        if not self.editor:
            messagebox.showwarning('Not logged in', 'Please login first')
            return
        self._run_and_show_output('Pokedex', lambda: self.editor.pokedex_list())

    def _unlock_starter_dialog(self):
        # Dialog to pick a starter and set unlock properties
        from rogueeditor.utils import load_pokemon_index
        from rogueeditor.catalog import load_move_catalog, load_ability_attr_mask
        index = load_pokemon_index()
        dex = (index.get('dex') or {})
        # Build display mapping like "#001 Bulbasaur" -> id
        def _pretty(n: str) -> str:
            return n.replace('_', ' ').title()
        disp_to_id: dict[str, int] = {}
        for name, vid in dex.items():
            try:
                i = int(vid)
            except Exception:
                continue
            disp = f"#{i:03d} {_pretty(name)}"
            disp_to_id[disp] = i
        # Select starter via catalog dialog
        sid = CatalogSelectDialog.select(self, disp_to_id, 'Select Starter')
        if sid is None:
            return
        # Resolve display name
        sel_disp = None
        for n, i in disp_to_id.items():
            if i == sid:
                sel_disp = n
                break
        # Build dialog
        top = tk.Toplevel(self)
        top.title(f"Unlock Starter - {sel_disp or ('#%03d' % sid)}")
        ttk.Label(top, text=f"Selected: {sel_disp or ('#%03d' % sid)}").grid(row=0, column=0, columnspan=6, sticky=tk.W, padx=6, pady=6)

        # Options
        perfect_iv = tk.IntVar(value=1)
        shiny_var = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='Perfect IVs (31s)', variable=perfect_iv).grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Checkbutton(top, text='Shiny', variable=shiny_var).grid(row=1, column=1, sticky=tk.W, padx=6)

        ttk.Label(top, text='Seen:').grid(row=2, column=0, sticky=tk.E)
        seen_e = ttk.Entry(top, width=6); seen_e.insert(0, '10'); seen_e.grid(row=2, column=1, sticky=tk.W)
        ttk.Label(top, text='Caught:').grid(row=2, column=2, sticky=tk.E)
        caught_e = ttk.Entry(top, width=6); caught_e.insert(0, '5'); caught_e.grid(row=2, column=3, sticky=tk.W)
        ttk.Label(top, text='Hatched:').grid(row=2, column=4, sticky=tk.E)
        hatched_e = ttk.Entry(top, width=6); hatched_e.insert(0, '0'); hatched_e.grid(row=2, column=5, sticky=tk.W)

        # StarterData properties
        ttk.Label(top, text='Candy Count:').grid(row=3, column=0, sticky=tk.E)
        candy_e = ttk.Entry(top, width=8); candy_e.insert(0, '0'); candy_e.grid(row=3, column=1, sticky=tk.W)
        ttk.Label(top, text='valueReduction:').grid(row=3, column=2, sticky=tk.E)
        vr_e = ttk.Entry(top, width=8); vr_e.insert(0, '0'); vr_e.grid(row=3, column=3, sticky=tk.W)

        # abilityAttr mask
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        aa1 = tk.IntVar(value=1); aa2 = tk.IntVar(value=1); aah = tk.IntVar(value=1)
        ttk.Label(top, text='abilityAttr:').grid(row=4, column=0, sticky=tk.W, padx=6)
        ttk.Checkbutton(top, text='Ability 1', variable=aa1).grid(row=4, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text='Ability 2', variable=aa2).grid(row=4, column=2, sticky=tk.W)
        ttk.Checkbutton(top, text='Hidden', variable=aah).grid(row=4, column=3, sticky=tk.W)

        # passiveAttr flags
        ttk.Label(top, text='passiveAttr:').grid(row=5, column=0, sticky=tk.W, padx=6)
        p_unlocked = tk.IntVar(value=1); p_enabled = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='Unlocked', variable=p_unlocked).grid(row=5, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text='Enabled', variable=p_enabled).grid(row=5, column=2, sticky=tk.W)

        # Moveset (optional)
        ttk.Label(top, text='Starter Moves (optional):').grid(row=6, column=0, sticky=tk.W, padx=6)
        move_n2i, move_i2n = load_move_catalog()
        move_acs = []
        for i in range(4):
            ac = AutoCompleteEntry(top, move_n2i, width=24)
            ac.grid(row=6+i, column=1, sticky=tk.W, padx=4, pady=2)
            ttk.Button(top, text='Pick', command=lambda j=i: self._pick_from_catalog(move_acs[j], move_n2i, f'Select Move {j+1}')).grid(row=6+i, column=2, sticky=tk.W)
            move_acs.append(ac)

        def do_apply():
            try:
                seen = int(seen_e.get().strip() or '0')
                caught = int(caught_e.get().strip() or '0')
                hatched = int(hatched_e.get().strip() or '0')
                candy = int(candy_e.get().strip() or '0')
                vr = int(vr_e.get().strip() or '0')
            except ValueError:
                messagebox.showwarning('Invalid', 'Counts and valueReduction must be integers')
                return
            # Compose trainer update
            data = self.api.get_trainer()
            dex_id = str(sid)
            # dexData
            shiny_attr = 255 if shiny_var.get() else 253
            dex_entry = {
                "seenAttr": 479,
                "caughtAttr": shiny_attr,
                "natureAttr": 67108862,
                "seenCount": max(0, seen),
                "caughtCount": max(0, caught),
                "hatchedCount": max(0, hatched),
            }
            if perfect_iv.get():
                dex_entry["ivs"] = [31, 31, 31, 31, 31, 31]
            data.setdefault('dexData', {})[dex_id] = {**(data.get('dexData', {}).get(dex_id) or {}), **dex_entry}
            # starterData
            abil_mask = (mask.get('ability_1',1) if aa1.get() else 0) | (mask.get('ability_2',2) if aa2.get() else 0) | (mask.get('ability_hidden',4) if aah.get() else 0)
            passive = (1 if p_unlocked.get() else 0) | (2 if p_enabled.get() else 0)
            moves = []
            for ac in move_acs:
                mid = ac.get_id()
                if isinstance(mid, int):
                    moves.append(mid)
            starter_entry = {
                "moveset": moves or None,
                "eggMoves": 15,
                "candyCount": max(0, candy),
                "abilityAttr": abil_mask or 7,
                "passiveAttr": passive,
                "valueReduction": max(0, vr),
            }
            data.setdefault('starterData', {})[dex_id] = {**(data.get('starterData', {}).get(dex_id) or {}), **starter_entry}
            try:
                self.api.update_trainer(data)
                messagebox.showinfo('Starter', 'Starter unlocked/updated successfully.')
                self._log(f"Updated starter dex {dex_id}")
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))

        ttk.Button(top, text='Apply', command=do_apply).grid(row=10, column=1, padx=6, pady=8, sticky=tk.W)
        def do_apply_and_upload():
            if not messagebox.askyesno('Confirm Unlock', 'This will unlock the starter with the selected properties and is final. Proceed?'):
                return
            do_apply()
        ttk.Button(top, text='Apply and Upload', command=do_apply_and_upload).grid(row=10, column=2, padx=6, pady=8, sticky=tk.W)
        ttk.Button(top, text='Close', command=top.destroy).grid(row=10, column=3, padx=6, pady=8, sticky=tk.W)

    def _add_item_dialog(self):
        slot = self._ask_slot()
        if not slot:
            return
        idx = self._ask_int("Team slot (1-5): ")
        if not idx:
            return
        item = self._ask_str("Item type (e.g., WIDE_LENS, BERRY, BASE_STAT_BOOSTER): ")
        if not item:
            return
        if item.strip().upper() == "BASE_STAT_BOOSTER":
            # Ask stat
            from rogueeditor.catalog import load_stat_catalog
            n2i, i2n = load_stat_catalog()
            top = tk.Toplevel(self)
            top.title("Select Stat")
            ttk.Label(top, text="Stat (id or name):").pack(padx=6, pady=6)
            ac = AutoCompleteEntry(top, n2i)
            ac.pack(padx=6, pady=6)
            def ok():
                stat_id = ac.get_id()
                if stat_id is None:
                    messagebox.showwarning("Invalid", "Please select a stat")
                    return
                top.destroy()
                if messagebox.askyesno("Confirm", f"Attach {item}({stat_id}) to team slot {idx}?"):
                    # Build entry directly
                    data = self.api.get_slot(slot)
                    party = data.get("party") or []
                    mon = party[idx-1]
                    mon_id = mon.get("id")
                    entry = {
                        "args": [mon_id, stat_id],
                        "player": True,
                        "stackCount": 1,
                        "typeId": "BASE_STAT_BOOSTER",
                        "typePregenArgs": [stat_id],
                    }
                    mods = data.setdefault("modifiers", [])
                    mods.append(entry)
                    from rogueeditor.utils import slot_save_path, dump_json
                    p = slot_save_path(self.api.username, slot)
                    dump_json(p, data)
                    self._log(f"Attached BASE_STAT_BOOSTER({stat_id}) to slot {idx}; wrote {p}")
                    if messagebox.askyesno("Upload", "Upload changes to server?"):
                        try:
                            self.api.update_slot(slot, data)
                            messagebox.showinfo("Uploaded", "Server updated.")
                        except Exception as e:
                            messagebox.showerror("Upload failed", str(e))
            ttk.Button(top, text="OK", command=ok).pack(pady=6)
            ac.focus_set()
            self.wait_window(top)
        else:
            if messagebox.askyesno("Confirm", f"Attach {item} to team slot {idx}?"):
                self.editor.add_item_to_mon(slot, idx, item)
                self._log(f"Attached {item} to slot {idx}")

    def _remove_item_dialog(self):
        slot = self._ask_slot()
        if not slot:
            return
        idx = self._ask_int("Team slot (1-5): ")
        if not idx:
            return
        item = self._ask_str("Item type to remove: ")
        if not item:
            return
        if messagebox.askyesno("Confirm", f"Remove {item} from team slot {idx}?"):
            self.editor.remove_item_from_mon(slot, idx, item)
            self._log(f"Removed {item} from slot {idx}")

    # --- Simple inputs ---
    def _ask_slot(self) -> int | None:
        try:
            return int(self._ask_str("Slot (1-5): ") or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Invalid slot")
            return None

    def _ask_int(self, prompt: str) -> int | None:
        try:
            return int(self._ask_str(prompt) or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Invalid number")
            return None

    def _ask_str(self, prompt: str) -> str:
        top = tk.Toplevel(self)
        top.title("Input")
        ttk.Label(top, text=prompt).pack(padx=6, pady=6)
        ent = ttk.Entry(top)
        ent.pack(padx=6, pady=6)
        out = {"v": None}
        def ok():
            out["v"] = ent.get().strip()
            top.destroy()
        ttk.Button(top, text="OK", command=ok).pack(pady=6)
        ent.focus_set()
        self.wait_window(top)
        return out["v"]

    # --- Starters handlers ---
    def _get_starter_dex_id(self) -> int | None:
        sid = self.starter_ac.get_id()
        if sid is None:
            messagebox.showwarning("Missing", "Select a Pokemon by name or id")
            return None
        return sid

    def _apply_starter_attrs(self):
        sid = self._get_starter_dex_id()
        if sid is None:
            return
        # abilityAttr from checkboxes
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        ability_attr = (self.aa1.get() and mask.get("ability_1", 1) or 0) + \
                       (self.aa2.get() and mask.get("ability_2", 2) or 0) + \
                       (self.aah.get() and mask.get("ability_hidden", 4) or 0)
        # passiveAttr from flags
        passive_attr = (self.p_unlocked.get() and 1 or 0) + (self.p_enabled.get() and 2 or 0)
        try:
            value_reduction = int(self.starter_value_reduction.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "valueReduction must be integer")
            return
        if not messagebox.askyesno("Confirm", f"Apply attrs to dex {sid} (save locally)?"):
            return
        data = self.api.get_trainer()
        s = data.setdefault("starterData", {})
        key = str(sid)
        entry = s.get(key) or {"moveset": None, "eggMoves": 15, "candyCount": 0, "abilityAttr": 7, "passiveAttr": 0, "valueReduction": 0}
        entry["abilityAttr"] = ability_attr
        entry["passiveAttr"] = passive_attr
        entry["valueReduction"] = value_reduction
        s[key] = entry
        # Save locally then offer upload
        from rogueeditor.utils import trainer_save_path, dump_json
        p = trainer_save_path(self.api.username)
        dump_json(p, data)
        messagebox.showinfo("Saved", f"Wrote {p}")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Server updated.")

    def _inc_starter_candies(self):
        sid = self._get_starter_dex_id()
        if sid is None:
            return
        try:
            delta = int(self.starter_candy_delta.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Delta must be integer")
            return
        if not messagebox.askyesno("Confirm", f"Increment candies by {delta} (save locally)?"):
            return
        data = self.api.get_trainer()
        s = data.setdefault("starterData", {})
        key = str(sid)
        entry = s.get(key) or {"moveset": None, "eggMoves": 15, "candyCount": 0, "abilityAttr": 7, "passiveAttr": 0, "valueReduction": 0}
        entry["candyCount"] = max(0, int(entry.get("candyCount", 0)) + delta)
        s[key] = entry
        from rogueeditor.utils import trainer_save_path, dump_json
        p = trainer_save_path(self.api.username)
        dump_json(p, data)
        messagebox.showinfo("Saved", f"Wrote {p}")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Server updated.")

    def _apply_gacha_delta(self):
        try:
            d0 = int(self.gacha_d0.get().strip() or "0")
            d1 = int(self.gacha_d1.get().strip() or "0")
            d2 = int(self.gacha_d2.get().strip() or "0")
            d3 = int(self.gacha_d3.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "All deltas must be integers")
            return
        if not messagebox.askyesno("Confirm", f"Apply gacha deltas C/R/E/L = {d0}/{d1}/{d2}/{d3} (save locally)?"):
            return
        data = self.api.get_trainer()
        current = data.get("voucherCounts") or {}
        def cur(k):
            try:
                return int(current.get(k, 0))
            except Exception:
                return 0
        updated = {
            "0": max(0, cur("0") + d0),
            "1": max(0, cur("1") + d1),
            "2": max(0, cur("2") + d2),
            "3": max(0, cur("3") + d3),
        }
        data["voucherCounts"] = updated
        from rogueeditor.utils import trainer_save_path, dump_json
        p = trainer_save_path(self.api.username)
        dump_json(p, data)
        messagebox.showinfo("Saved", f"Wrote {p}")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Gacha tickets updated on server")


def run():
    app = App()
    app.mainloop()


class AutoCompleteEntry(ttk.Entry):
    def __init__(self, master, name_to_id: dict[str, int], **kwargs):
        super().__init__(master, **kwargs)
        self._name_to_id = name_to_id
        self._popup = None
        self._var = tk.StringVar()
        self.config(textvariable=self._var)
        self._var.trace_add('write', self._on_change)
        self.bind('<Down>', self._move_down)
        self._selected_id = None

    def get_id(self):
        v = self._var.get().strip()
        if v.isdigit():
            return int(v)
        key = v.lower().replace(' ', '_')
        if key in self._name_to_id:
            return self._name_to_id[key]
        return self._selected_id

    def set_value(self, text: str):
        self._var.set(text)

    def _on_change(self, *args):
        text = self._var.get().strip().lower().replace(' ', '_')
        if not text:
            self._hide_popup()
            return
        matches = [n for n in self._name_to_id.keys() if text in n][:10]
        if not matches:
            self._hide_popup()
            return
        if not self._popup:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._list = tk.Listbox(self._popup)
            self._list.pack()
            self._list.bind('<Double-Button-1>', self._select)
            self._list.bind('<Return>', self._select)
        self._list.delete(0, tk.END)
        for m in matches:
            disp = f"{m} ({self._name_to_id.get(m)})"
            self._list.insert(tk.END, disp)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self._popup.geometry(f"300x180+{x}+{y}")
        self._popup.deiconify()

    def _move_down(self, event):
        if self._popup:
            self._list.focus_set()
            if self._list.size() > 0:
                self._list.selection_set(0)
        return 'break'

    def _select(self, event=None):
        if not self._popup:
            return
        try:
            sel = self._list.get(self._list.curselection())
        except Exception:
            return
        # sel could be 'name (id)'; extract name
        name = sel.split(' (', 1)[0]
        self._var.set(name)
        self._selected_id = self._name_to_id.get(name)
        self._hide_popup()

    def _hide_popup(self):
        if self._popup:
            self._popup.destroy()
            self._popup = None


class TeamEditorDialog(tk.Toplevel):
    def __init__(self, master: App, api: PokerogueAPI, editor: Editor, slot: int):
        super().__init__(master)
        self.title(f"Team Editor - Slot {slot}")
        self.geometry("900x500")
        self.api = api
        self.editor = editor
        self.slot = slot
        self.data = self.api.get_slot(slot)
        self.party = self.data.get("party") or []
        self._build()

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
        move_name_to_id, move_id_to_name = load_move_catalog()
        abil_name_to_id, abil_id_to_name = load_ability_catalog()
        nat_name_to_id, nat_id_to_name = load_nature_catalog()
        # Store move catalogs for labels
        self.move_name_to_id = move_name_to_id
        self.move_id_to_name = move_id_to_name

        ttk.Label(parent, text="Level:").grid(row=0, column=0, sticky=tk.W)
        self.level_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.level_var, width=6).grid(row=0, column=1, sticky=tk.W)
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

        ttk.Label(parent, text="Nature:").grid(row=2, column=0, sticky=tk.W)
        # Nature combobox with effect hints (e.g., Adamant +Atk/-SpA)
        from rogueeditor.catalog import nature_multipliers_by_id
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
        # Use id->name to preserve source names; prettify for display
        for nid, raw_name in sorted(load_nature_catalog()[1].items(), key=lambda kv: kv[0]):
            effect = _effect_text(nid)
            disp = f"{_pretty(raw_name)} ({effect}) ({nid})"
            nature_items.append(disp)
        self.nature_cb = ttk.Combobox(parent, values=nature_items, width=28)
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

        # IVs in two columns of three
        ttk.Label(parent, text="IVs:").grid(row=3, column=0, sticky=tk.NW)
        self.iv_vars = [tk.StringVar() for _ in range(6)]
        iv_labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
        iv_frame = ttk.Frame(parent)
        iv_frame.grid(row=3, column=1, columnspan=3, sticky=tk.W)
        # Left column (HP/Atk/Def)
        for i, lab in enumerate(iv_labels[:3]):
            ttk.Label(iv_frame, text=lab+":").grid(row=i, column=0, sticky=tk.E, padx=2, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[i], width=4).grid(row=i, column=1, sticky=tk.W)
        # Right column (SpA/SpD/Spe)
        for j, lab in enumerate(iv_labels[3:], start=3):
            ttk.Label(iv_frame, text=lab+":").grid(row=j-3, column=2, sticky=tk.E, padx=8, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[j], width=4).grid(row=j-3, column=3, sticky=tk.W)

        # Calculated Stats (derived from Level + IVs, EV=0)
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

        ttk.Button(parent, text="Save to file", command=self._save).grid(row=10, column=0, pady=8)
        ttk.Button(parent, text="Upload", command=self._upload).grid(row=10, column=1, pady=8)

    def _on_select(self, event=None):
        if not self.team_list.curselection():
            return
        idx = self.team_list.curselection()[0]
        mon = self.party[idx]
        # Populate fields
        lvl = mon.get("level") or mon.get("lvl") or ""
        self.level_var.set(str(lvl))
        # Ability
        abil = mon.get("abilityId") or mon.get("ability") or ""
        self.ability_ac.set_value(str(abil))
        # Nature (handled via combobox below)
        nat = mon.get("natureId") or mon.get("nature") or ""
        try:
            nid = int(nat)
            from rogueeditor.catalog import load_nature_catalog, nature_multipliers_by_id
            n2i, i2n = load_nature_catalog()
            name = i2n.get(nid, str(nid))
            # include effect in display
            arr = nature_multipliers_by_id().get(int(nid), [1.0]*6)
            labs = ["HP","Atk","Def","SpA","SpD","Spe"]
            up = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-1.1)<1e-6), None)
            dn = next((labs[i] for i,v in enumerate(arr) if i>0 and abs(v-0.9)<1e-6), None)
            effect = "neutral" if (not up or not dn or up==dn) else f"+{up}/-{dn}"
            self.nature_cb.set(f"{name.replace('_',' ').title()} ({effect}) ({nid})")
            self._update_nature_hint(arr)
        except Exception:
            self.nature_cb.set(str(nat))
            self._update_nature_hint([1.0]*6)
        # Moves
        moves = []
        mv = mon.get("moveset") or mon.get("moveIds") or mon.get("moves") or []
        for i in range(4):
            cur = mv[i] if i < len(mv) else None
            if isinstance(cur, dict):
                val = cur.get("id") or cur.get("moveId") or ""
            else:
                val = cur or ""
            self.move_acs[i].set_value(str(val))
            self._update_move_label(i)
        # Held item id
        hid = mon.get("heldItemId") or mon.get("heldItem") or mon.get("item") or ""
        if hasattr(self, 'held_item_ac') and self.held_item_ac:
            self.held_item_ac.set_value(str(hid))
        else:
            self.held_item_var.set(str(hid))
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
        # Ability
        aid = self.ability_ac.get_id()
        if aid is not None:
            if "abilityId" in mon:
                mon["abilityId"] = aid
            elif "ability" in mon:
                mon["ability"] = aid
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
        pairs = [("maxHp", "hp"), ("attack", "atk"), ("defense", "def"), ("spAttack", "spAtk"), ("spDefense", "spDef"), ("speed", "spd")]
        out: list[int] = []
        for k1, k2 in pairs:
            val = mon.get(k1)
            if val is None:
                val = mon.get(k2)
            if val is None:
                return None
            try:
                out.append(int(val))
            except Exception:
                return None
        return out

    def _infer_base_stats(self, level: int, ivs: list[int], actual: list[int]) -> list[int]:
        def ev_effective(E: int) -> int:
            return math.floor(math.ceil(math.sqrt(E)) / 4)
        # Nature multipliers for current mon
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

    def _pick_from_catalog(self, ac: AutoCompleteEntry, name_to_id: dict[str, int], title: str):
        sel = CatalogSelectDialog.select(self, name_to_id, title)
        if sel is not None:
            # find name by id
            name = None
            for k, v in name_to_id.items():
                if v == sel:
                    name = k
                    break
            ac.set_value(name or str(sel))


class ModifiersManagerDialog(tk.Toplevel):
    def __init__(self, master: App, api: PokerogueAPI, editor: Editor, slot: int):
        super().__init__(master)
        self.title(f"Modifiers Manager - Slot {slot}")
        self.geometry("900x500")
        self.api = api
        self.editor = editor
        self.slot = slot
        self._build()
        self._refresh()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # Player modifiers
        left = ttk.LabelFrame(top, text="Player Modifiers")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        cols = ("idx", "typeId", "className", "args", "stack")
        self.player_tree = ttk.Treeview(left, columns=cols, show="headings", height=10)
        for c, w in (("idx", 50), ("typeId", 150), ("className", 200), ("args", 200), ("stack", 60)):
            self.player_tree.heading(c, text=c)
            self.player_tree.column(c, width=w, anchor=tk.W)
        self.player_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb1 = ttk.Scrollbar(left, orient="vertical", command=self.player_tree.yview)
        self.player_tree.configure(yscrollcommand=sb1.set)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        btns1 = ttk.Frame(left)
        btns1.pack(fill=tk.X)
        ttk.Button(btns1, text="Add Player Modifier", command=self._add_player_mod).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btns1, text="Remove Selected", command=self._remove_player_mod).pack(side=tk.LEFT, padx=4, pady=4)

        # Pokemon modifiers
        right = ttk.LabelFrame(top, text="Pokemon Modifiers")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        cols2 = ("idx", "typeId", "className", "args", "target")
        self.pokemon_tree = ttk.Treeview(right, columns=cols2, show="headings", height=10)
        for c, w in (("idx", 50), ("typeId", 150), ("className", 200), ("args", 200), ("target", 120)):
            self.pokemon_tree.heading(c, text=c)
            self.pokemon_tree.column(c, width=w, anchor=tk.W)
        self.pokemon_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(right, orient="vertical", command=self.pokemon_tree.yview)
        self.pokemon_tree.configure(yscrollcommand=sb2.set)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        btns2 = ttk.Frame(right)
        btns2.pack(fill=tk.X)
        ttk.Button(btns2, text="Remove Selected", command=self._remove_pokemon_mod).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btns2, text="Refresh", command=self._refresh).pack(side=tk.LEFT, padx=4, pady=4)

        # Upload/save
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(bottom, text="Upload Changes", command=self._upload).pack(side=tk.LEFT)

    def _refresh(self):
        # Populate trees
        det = self.editor.list_modifiers_detailed(self.slot)
        player_mods, by_mon = self.editor.group_modifiers(self.slot)
        for t in (self.player_tree, self.pokemon_tree):
            for r in t.get_children():
                t.delete(r)
        # Player
        for idx, m in player_mods:
            self.player_tree.insert('', 'end', values=(idx, m.get('typeId'), m.get('className'), m.get('args'), m.get('stackCount')))
        # Pokemon
        # Map mon id -> display label
        party = (self.api.get_slot(self.slot).get('party') or [])
        party_map = {p.get('id'): p for p in party if isinstance(p, dict) and 'id' in p}
        from rogueeditor.utils import invert_dex_map, load_pokemon_index
        inv = invert_dex_map(load_pokemon_index())
        for mon_id, mods in by_mon.items():
            label = 'unknown'
            mon = party_map.get(mon_id)
            if mon:
                did = str(mon.get('species') or mon.get('dexId') or mon.get('speciesId') or '?')
                name = inv.get(did, did)
                label = f"{name} (id {mon_id})"
            for idx, m in mods:
                self.pokemon_tree.insert('', 'end', values=(idx, m.get('typeId'), m.get('className'), m.get('args'), label))

    def _add_player_mod(self):
        top = tk.Toplevel(self)
        top.title("Add Player Modifier")
        ttk.Label(top, text="TypeId:").grid(row=0, column=0, padx=4, pady=4)
        type_var = tk.StringVar()
        ttk.Entry(top, textvariable=type_var, width=30).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(top, text="Args (comma ints, optional):").grid(row=1, column=0, padx=4, pady=4)
        args_var = tk.StringVar()
        ttk.Entry(top, textvariable=args_var, width=30).grid(row=1, column=1, padx=4, pady=4)
        ttk.Label(top, text="Stack count:").grid(row=2, column=0, padx=4, pady=4)
        stack_var = tk.StringVar(value='1')
        ttk.Entry(top, textvariable=stack_var, width=6).grid(row=2, column=1, padx=4, pady=4, sticky=tk.W)
        def ok():
            tid = type_var.get().strip()
            if not tid:
                return
            args_text = args_var.get().strip()
            args = None
            if args_text:
                try:
                    args = [int(x.strip()) for x in args_text.split(',') if x.strip()]
                except Exception:
                    messagebox.showwarning('Invalid', 'Args must be comma-separated integers')
                    return
            try:
                stack = int(stack_var.get().strip() or '1')
            except ValueError:
                stack = 1
            self.editor.add_player_modifier(self.slot, tid, args, stack)
            self._refresh()
            top.destroy()
        ttk.Button(top, text='Add', command=ok).grid(row=3, column=1, padx=4, pady=6, sticky=tk.W)

    def _remove_player_mod(self):
        sel = self.player_tree.selection()
        if not sel:
            return
        item = self.player_tree.item(sel[0])
        idx = item.get('values')[0]
        try:
            idx = int(idx)
        except Exception:
            return
        if messagebox.askyesno('Confirm', f'Remove player modifier index {idx}?'):
            if self.editor.remove_modifier_by_index(self.slot, idx):
                self._refresh()
            else:
                messagebox.showwarning('Failed', 'Unable to remove modifier')

    def _remove_pokemon_mod(self):
        sel = self.pokemon_tree.selection()
        if not sel:
            return
        item = self.pokemon_tree.item(sel[0])
        idx = item.get('values')[0]
        try:
            idx = int(idx)
        except Exception:
            return
        if messagebox.askyesno('Confirm', f'Remove pokemon modifier index {idx}?'):
            if self.editor.remove_modifier_by_index(self.slot, idx):
                self._refresh()
            else:
                messagebox.showwarning('Failed', 'Unable to remove modifier')

    def _upload(self):
        if not messagebox.askyesno('Confirm Upload', 'Upload all modifier changes for this slot to the server?'):
            return
        try:
            # Use current local file if present, else fetch live
            from rogueeditor.utils import slot_save_path, load_json
            p = slot_save_path(self.api.username, self.slot)
            data = load_json(p) if os.path.exists(p) else self.api.get_slot(self.slot)
            self.api.update_slot(self.slot, data)
            messagebox.showinfo('Uploaded', 'Server updated successfully.')
        except Exception as e:
            messagebox.showerror('Upload failed', str(e))


class CatalogSelectDialog(tk.Toplevel):
    def __init__(self, master, name_to_id: dict[str, int], title: str = 'Select'):
        super().__init__(master)
        self.title(title)
        self.geometry('400x400')
        self.name_to_id = name_to_id
        self._build()

    def _build(self):
        ttk.Label(self, text='Search:').pack(padx=6, pady=6, anchor=tk.W)
        self.var = tk.StringVar()
        ent = ttk.Entry(self, textvariable=self.var)
        ent.pack(fill=tk.X, padx=6)
        self.list = tk.Listbox(self)
        self.list.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.list.bind('<Double-Button-1>', lambda e: self._ok())
        self.list.bind('<Return>', lambda e: self._ok())
        ttk.Button(self, text='Select', command=self._ok).pack(pady=6)
        self.var.trace_add('write', self._on_change)
        self._all = sorted(self.name_to_id.items(), key=lambda kv: kv[0])
        self._filter('')
        ent.focus_set()

    def _on_change(self, *args):
        self._filter(self.var.get().strip().lower().replace(' ', '_'))

    def _filter(self, key: str):
        self.list.delete(0, tk.END)
        for name, iid in self._all:
            if key in name:
                self.list.insert(tk.END, f"{name} ({iid})")

    def _ok(self):
        try:
            sel = self.list.get(self.list.curselection())
        except Exception:
            return
        name = sel.split(' (', 1)[0]
        self.result = self.name_to_id.get(name)
        self.destroy()

    @classmethod
    def select(cls, master, name_to_id: dict[str, int], title: str = 'Select') -> int | None:
        dlg = cls(master, name_to_id, title)
        master.wait_window(dlg)
        return getattr(dlg, 'result', None)
