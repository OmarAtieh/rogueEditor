?from __future__ import annotations

import os
import sys
import subprocess
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except Exception:
    # Ensure we can capture import-time Tk errors in the log
    try:
        from rogueeditor.logging_utils import (
            setup_logging,
            attach_stderr_tee,
            install_excepthook,
            log_environment,
            log_exception_context,
            crash_hint,
        )
        logger = setup_logging()
        attach_stderr_tee(logger)
        install_excepthook(logger)
        log_environment(logger)
        log_exception_context("Failed to import tkinter")
        print("[ERROR] Failed to import tkinter.")
        print(crash_hint())
    except Exception:
        pass
    raise
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
from gui.common.widgets import AutoCompleteEntry
from gui.common.catalog_select import CatalogSelectDialog
from gui.dialogs.team_editor import TeamEditorDialog
from gui.sections.slots import build as build_slots_section
from gui.dialogs.item_manager import ItemManagerDialog
from rogueeditor.logging_utils import (
    setup_logging,
    install_excepthook,
    log_environment,
    log_exception_context,
    crash_hint,
    attach_stderr_tee,
)
from rogueeditor.healthcheck import (
    is_first_run,
    last_run_success,
    run_healthcheck,
    record_run_result,
)


class App(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        root = self.winfo_toplevel()
        try:
            root.title("rogueEditor GUI")
            # Slightly wider default to avoid rightmost button cutoff
            root.geometry("1050x800")
            root.minsize(720, 600)
        except Exception:
            pass
        self.api: PokerogueAPI | None = None
        self.editor: Editor | None = None
        self.username: str | None = None

        # Global style + compact mode state
        self.style = ttk.Style(self)
        self.compact_mode = tk.BooleanVar(value=False)
        # Hint font for de-emphasized helper text
        try:
            from tkinter import font as _tkfont
            base_font = _tkfont.nametofont('TkDefaultFont')
            self.hint_font = base_font.copy()
            self.hint_font.configure(slant='italic')
        except Exception:
            self.hint_font = None

        # Top warning banner (disclaimer)
        banner = ttk.Frame(self)
        banner.grid(row=0, column=0, columnspan=2, sticky=tk.EW)
        banner.columnconfigure(0, weight=1)
        warn_text = (
            "WARNING: Use at your own risk. The author is not responsible for "
            "data loss or account bans. No data is collected; only data is "
            "exchanged between your local computer and the official game server.\n"
            "Tip: Going overboard can trivialize the game and reduce enjoyment.\n"
            "Intended uses include backing up/restoring your own data, recovering from desync/corruption, "
            "and safe personal experimentation. Always back up before editing."
        )
        self.banner_label = ttk.Label(
            banner,
            text=warn_text,
            foreground="red",
            wraplength=900,
            justify=tk.LEFT,
        )
        self.banner_label.grid(row=0, column=0, sticky=tk.W, padx=8, pady=(6, 2))
        # Compact mode toggle (top-right)
        ttk.Checkbutton(
            banner,
            text="Compact (hide banner)",
            variable=self.compact_mode,
            command=lambda: self._apply_compact_mode(self.compact_mode.get()),
        ).grid(row=0, column=1, sticky=tk.E, padx=8)

        # Layout: left (controls), right (console)
        # Reserve row 0 for top banner
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.left_col = ttk.Frame(self)
        self.right_col = ttk.Frame(self)
        self.left_col.grid(row=1, column=0, sticky=tk.NSEW)
        self.right_col.grid(row=1, column=1, sticky=tk.NSEW)

        self._build_login()
        self._build_actions()
        self._build_console()
        # Mount root container
        self.pack(fill=tk.BOTH, expand=True)

    # --- UI builders ---
    def _build_login(self):
        frm = ttk.LabelFrame(self.left_col, text="Login")
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

        # Row of buttons (keep within 4 side-by-side)
        ttk.Button(frm, text="Login", command=self._login).grid(row=3, column=1, padx=4, pady=6, sticky=tk.W)
        ttk.Button(frm, text="Refresh Session", command=self._refresh_session).grid(row=3, column=2, padx=4, pady=6, sticky=tk.W)

        self.status_var = tk.StringVar(value="Status: Not logged in")
        ttk.Label(frm, textvariable=self.status_var).grid(row=4, column=0, columnspan=3, sticky=tk.W, padx=4, pady=4)
        # Session last updated label (persisted per user)
        self.session_updated_var = tk.StringVar(value="Last session update: -")
        ttk.Label(frm, textvariable=self.session_updated_var).grid(row=5, column=0, columnspan=3, sticky=tk.W, padx=4, pady=2)
        # Quick Actions toolbar (prominent backup/restore)
        qa = ttk.Frame(frm)
        qa.grid(row=6, column=0, columnspan=3, sticky=tk.W, padx=4, pady=4)
        self.btn_backup = ttk.Button(qa, text="Backup All", command=self._safe(self._backup), state=tk.DISABLED)
        self.btn_backup.pack(side=tk.LEFT, padx=4)
        self.btn_restore = ttk.Button(qa, text="Restore Backup (to server)", command=self._safe(self._restore_dialog2), state=tk.DISABLED)
        self.btn_restore.pack(side=tk.LEFT, padx=4)
        self.backup_status_var = tk.StringVar(value="Last backup: none")
        ttk.Label(qa, textvariable=self.backup_status_var).pack(side=tk.LEFT, padx=8)
        # Update session label when user changes selection
        try:
            self.user_combo.bind('<<ComboboxSelected>>', lambda e: self._update_session_label_from_store())
        except Exception:
            pass

    def _build_actions(self):
        # Scrollable container for actions
        container = ttk.LabelFrame(self.left_col, text="Actions")
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

        # Ensure a shared slot variable exists for all actions
        try:
            _ = self.slot_var
        except Exception:
            self.slot_var = tk.StringVar(value="1")

        # Slots summary (move to top to act as the shared slot selector)
        handle = build_slots_section(inner, self)
        self.slot_tree = handle["slot_tree"]

        # Data IO
        box1 = ttk.LabelFrame(inner, text="Data IO")
        box1.pack(fill=tk.X, padx=6, pady=6)

        # Section: Dumps
        dump_f = ttk.LabelFrame(box1, text="Dump from server to local (for editing)")
        dump_f.grid(row=0, column=0, columnspan=3, sticky=tk.W+tk.E, padx=4, pady=4)
        ttk.Button(dump_f, text="Dump Trainer", command=self._safe(self._dump_trainer)).grid(row=1, column=0, padx=4, pady=4, sticky=tk.W)
        # Shared slot selection comes from the Slots overview above
        ttk.Button(dump_f, text="Dump Selected Slot", command=self._safe(self._dump_slot_selected)).grid(row=1, column=1, padx=4, pady=4, sticky=tk.W)
        ttk.Button(dump_f, text="Dump All", command=self._safe(self._dump_all)).grid(row=1, column=2, padx=4, pady=4, sticky=tk.W)

        # Section: Upload
        up_f = ttk.LabelFrame(box1, text="Upload local changes to server")
        up_f.grid(row=1, column=0, columnspan=3, sticky=tk.W+tk.E, padx=4, pady=4)
        ttk.Button(up_f, text="Upload Trainer", command=self._safe(self._update_trainer)).grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Button(up_f, text="Upload Selected Slot", command=self._safe(self._update_slot_selected)).grid(row=0, column=1, padx=4, pady=4, sticky=tk.W)
        ttk.Button(up_f, text="Upload All", command=self._safe(self._upload_all)).grid(row=0, column=2, padx=4, pady=4, sticky=tk.W)

        # Section: Local Files
        local_f = ttk.LabelFrame(box1, text="Open local dumps (view/edit at your own risk)")
        local_f.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.E, padx=4, pady=4)
        ttk.Button(local_f, text="Open Local Dump...", command=self._safe(self._open_local_dump_dialog)).grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Label(local_f, text=(
            "Manual edits may corrupt saves. Proceed at your own risk."),
            foreground="red",
        ).grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        # (Slots summary moved above)

        # Team
        box2 = ttk.LabelFrame(inner, text="Active Run Team")
        box2.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(
            box2,
            text="Works with the selected slot's ongoing run (slot file).",
            foreground='gray50',
            font=(self.hint_font if self.hint_font else None),
        ).pack(fill=tk.X, padx=6, pady=(2, 0))
        ttk.Button(box2, text="Analyze Team", command=self._analyze_team_dialog).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Edit Team", command=self._safe(self._edit_team_dialog)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Analyze Run Conditions", command=self._analyze_run_conditions).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Edit Run Weather", command=self._safe(self._edit_run_weather)).pack(side=tk.LEFT, padx=4, pady=4)

        # Modifiers
        box3 = ttk.LabelFrame(inner, text="Modifiers / Items")
        box3.pack(fill=tk.BOTH, padx=6, pady=6)
        ttk.Label(
            box3,
            text="Affects modifiers and items in the selected slot's current run (slot file).",
            foreground='gray50',
            font=(self.hint_font if self.hint_font else None),
        ).pack(fill=tk.X, padx=6, pady=(2, 0))
        # Modifiers manager
        mod_btns = ttk.Frame(box3)
        mod_btns.pack(fill=tk.X)
        ttk.Button(mod_btns, text="Open Modifiers & Items Manager", command=self._safe(self._open_item_mgr)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(mod_btns, text="Analyze Modifiers", command=self._analyze_mods_dialog).pack(side=tk.LEFT, padx=4, pady=4)

        # Starters
        box4 = ttk.LabelFrame(inner, text="Starters")
        box4.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(
            box4,
            text="Edits trainer (account-wide) data — persists across runs (trainer.json).",
            foreground='gray50',
            font=(self.hint_font if getattr(self, 'hint_font', None) else None),
        ).grid(row=0, column=0, columnspan=5, sticky=tk.W, padx=6, pady=(2, 2))
        # Pokemon selector
        from rogueeditor.utils import load_pokemon_index
        dex = (load_pokemon_index().get("dex") or {})
        # Map name->id (int), keys lower
        name_to_id = {k.lower(): int(v) for k, v in dex.items()}
        self._starter_name_to_id = name_to_id
        ttk.Label(box4, text="Pokemon:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_ac = AutoCompleteEntry(box4, name_to_id, width=30)
        self.starter_ac.grid(row=1, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Button(box4, text="Pick...", command=self._pick_starter_from_catalog).grid(row=1, column=2, sticky=tk.W, padx=4, pady=2)
        ttk.Button(box4, text="Pokedex IDs", command=self._safe(self._pokedex_list)).grid(row=1, column=3, sticky=tk.W, padx=4, pady=2)
        # Label to show chosen Pokemon name and id
        self.starter_label = ttk.Label(box4, text="")
        self.starter_label.grid(row=1, column=4, sticky=tk.W, padx=6, pady=2)
        # Update label as the entry changes
        try:
            self.starter_ac.bind('<KeyRelease>', lambda e: self._update_starter_label())
            self.starter_ac.bind('<FocusOut>', lambda e: self._update_starter_label())
        except Exception:
            pass
        # Attributes
        ttk.Label(box4, text="abilityAttr:").grid(row=2, column=0, sticky=tk.W, padx=4, pady=2)
        # abilityAttr presets via checkboxes
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        self.aa1 = tk.IntVar(value=1)
        self.aa2 = tk.IntVar(value=1)
        self.aah = tk.IntVar(value=1)
        ttk.Checkbutton(box4, text="Ability 1", variable=self.aa1).grid(row=2, column=1, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Ability 2", variable=self.aa2).grid(row=2, column=2, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Hidden", variable=self.aah).grid(row=2, column=3, sticky=tk.W, padx=4)

        ttk.Label(box4, text="passiveAttr:").grid(row=3, column=0, sticky=tk.W, padx=4, pady=2)
        # Passive presets (UNLOCKED=1, ENABLED=2)
        self.p_unlocked = tk.IntVar(value=1)
        self.p_enabled = tk.IntVar(value=0)
        ttk.Checkbutton(box4, text="Unlocked", variable=self.p_unlocked).grid(row=3, column=1, sticky=tk.W, padx=4)
        ttk.Checkbutton(box4, text="Enabled", variable=self.p_enabled).grid(row=3, column=2, sticky=tk.W, padx=4)

        ttk.Label(box4, text="Cost Reduction (valueReduction):").grid(row=4, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_value_reduction = ttk.Entry(box4, width=8)
        self.starter_value_reduction.insert(0, "0")
        self.starter_value_reduction.grid(row=4, column=1, sticky=tk.W, padx=4, pady=2)

        btn_row = ttk.Frame(box4)
        btn_row.grid(row=5, column=1, columnspan=3, sticky=tk.W)
        ttk.Button(btn_row, text="Apply Attributes", command=self._safe(self._apply_starter_attrs)).grid(row=0, column=0, padx=4, pady=4, sticky=tk.W)
        ttk.Button(btn_row, text="Unlock Starter...", command=self._safe(self._unlock_starter_dialog)).grid(row=0, column=1, padx=4, pady=4, sticky=tk.W)
        ttk.Button(btn_row, text="Unlock All Starters", command=self._safe(self._unlock_all_starters)).grid(row=0, column=2, padx=4, pady=4, sticky=tk.W)
        # Pokedex IDs moved next to the Pick button

        # Candies increment
        ttk.Label(box4, text="Candies (selected):").grid(row=6, column=0, sticky=tk.W, padx=4, pady=2)
        self.starter_candy_delta = ttk.Entry(box4, width=8)
        self.starter_candy_delta.insert(0, "0")
        self.starter_candy_delta.grid(row=6, column=1, sticky=tk.W, padx=4, pady=2)
        # Secondary actions aligned under the primary actions row
        btn_row2 = ttk.Frame(box4)
        btn_row2.grid(row=7, column=1, columnspan=3, sticky=tk.W)
        ttk.Button(btn_row2, text="Increment Candies", command=self._safe(self._inc_starter_candies)).grid(row=0, column=1, padx=4, pady=2, sticky=tk.W)
        ttk.Button(btn_row2, text="Unlock All Passives (mask=7)", command=self._safe(self._unlock_all_passives)).grid(row=0, column=2, padx=4, pady=2, sticky=tk.W)
        # moved: Increment Candies button now appears below under secondary actions

        # Passives unlock near candies
        # moved: Unlock All Passives button now appears below under secondary actions

        # Subsection: Eggs & Tickets
        s2 = ttk.LabelFrame(box4, text="Eggs & Tickets")
        s2.grid(row=8, column=0, columnspan=5, sticky=tk.W+tk.E, padx=4, pady=6)
        ttk.Label(s2, text="Gacha ? C/R/E/L:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        self.gacha_d0 = ttk.Entry(s2, width=5); self.gacha_d0.insert(0, "0"); self.gacha_d0.grid(row=0, column=1, sticky=tk.W, padx=2)
        self.gacha_d1 = ttk.Entry(s2, width=5); self.gacha_d1.insert(0, "0"); self.gacha_d1.grid(row=0, column=2, sticky=tk.W, padx=2)
        self.gacha_d2 = ttk.Entry(s2, width=5); self.gacha_d2.insert(0, "0"); self.gacha_d2.grid(row=0, column=3, sticky=tk.W, padx=2)
        self.gacha_d3 = ttk.Entry(s2, width=5); self.gacha_d3.insert(0, "0"); self.gacha_d3.grid(row=0, column=4, sticky=tk.W, padx=2)
        ttk.Button(s2, text="Apply Gacha ?", command=self._safe(self._apply_gacha_delta)).grid(row=0, column=5, sticky=tk.W, padx=4, pady=2)
        ttk.Button(s2, text="Hatch All Eggs After Next Fight", command=self._safe(self._hatch_eggs)).grid(row=1, column=1, columnspan=3, sticky=tk.W, padx=4, pady=4)

    def _build_console(self):
        frm = ttk.LabelFrame(self.right_col, text="Console")
        frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.console = tk.Text(frm, height=30, width=40)
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

    def _apply_compact_mode(self, enabled: bool):
        """Compact mode collapses the warning banner text (session only)."""
        try:
            if enabled:
                try:
                    self.banner_label.grid_remove()
                except Exception:
                    pass
            else:
                try:
                    self.banner_label.grid()
                except Exception:
                    pass
        except Exception:
            pass

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

    def _modalize(self, top: tk.Toplevel, focus_widget: tk.Widget | None = None):
        try:
            top.transient(self)
            top.grab_set()
        except Exception:
            pass
        try:
            (focus_widget or top).focus_set()
        except Exception:
            pass

    def _show_text_dialog(self, title: str, content: str):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry('700x450')
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(frm, wrap='word')
        sb = ttk.Scrollbar(frm, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.insert(tk.END, content)
        txt.config(state='disabled')
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, pady=6)
        def do_save():
            path = filedialog.asksaveasfilename(title='Save Report', defaultextension='.txt', filetypes=[('Text Files','*.txt'), ('All Files','*.*')])
            if not path:
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo('Saved', f'Saved to {path}')
            except Exception as e:
                messagebox.showerror('Save failed', str(e))
        ttk.Button(btns, text='Save...', command=do_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT, padx=6)
        self._modalize(top)

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
            # Set numeric id into the field, and update label text to chosen name
            self.starter_ac.set_value(str(sel))
            try:
                self.starter_label.configure(text=f"{chosen} (#{sel})")
            except Exception:
                pass
    def _update_starter_label(self):
        try:
            raw = (self.starter_ac.get() or '').strip()
            if not raw:
                self.starter_label.configure(text="")
                return
            if raw.isdigit():
                did = str(int(raw))
                # Map id to canonical name from current dex
                try:
                    from rogueeditor.utils import load_pokemon_index, invert_dex_map
                    inv = invert_dex_map(load_pokemon_index())
                    name = inv.get(did)
                except Exception:
                    name = None
                if name:
                    disp = name.replace('-', ' ').title()
                    self.starter_label.configure(text=f"{disp} (#{did})")
                else:
                    self.starter_label.configure(text=f"#{did}")
            else:
                # Not a pure id; try resolve via mapping
                key = raw.lower().replace(' ', '_')
                mid = getattr(self, '_starter_name_to_id', {}).get(key)
                if isinstance(mid, int):
                    disp = raw.replace('_', ' ').title()
                    self.starter_label.configure(text=f"{disp} (#{mid})")
                else:
                    self.starter_label.configure(text=raw)
        except Exception:
            try:
                self.starter_label.configure(text="")
            except Exception:
                pass

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
        self._modalize(top, ent)

    def _login(self):
        user = self.user_combo.get().strip()
        if not user:
            messagebox.showwarning("Missing", "Select or create a username")
            return
        pwd = self.pass_entry.get()
        if not pwd:
            messagebox.showwarning("Missing", "Enter password")
            return
        # Intentionally ignore any prefilled clientSessionId; always establish a fresh session per login
        def work():
            api = PokerogueAPI(user, pwd)
            api.login()
            # Prefer server-provided clientSessionId; otherwise generate a new one for this session
            try:
                from rogueeditor.utils import generate_client_session_id
                csid = api.client_session_id or generate_client_session_id()
                api.client_session_id = csid
                # Persist for convenience/debug; UI shows current csid
                try:
                    save_client_session_id(csid)
                    set_user_csid(user, csid)
                except Exception:
                    pass
            except Exception:
                pass
            self.api = api
            self.editor = Editor(api)
            self.username = user
        def done():
            self.status_var.set(f"Status: Logged in as {user}")
            self._log(f"Logged in as {user}")
            # Reflect the active clientSessionId in the UI field
            try:
                self.csid_entry.delete(0, tk.END)
                self.csid_entry.insert(0, str(self.api.client_session_id or ""))
            except Exception:
                pass
            # Persist and show last session update time
            try:
                from datetime import datetime
                from rogueeditor.utils import set_user_last_session_update
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                set_user_last_session_update(user, ts)
                self.session_updated_var.set(f"Last session update: {ts}")
            except Exception:
                pass
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

    def _refresh_session(self):
        if not self.user_combo.get().strip() or not self.pass_entry.get():
            messagebox.showwarning("Missing", "Enter user and password first")
            return
        user = self.user_combo.get().strip()
        pwd = self.pass_entry.get()
        def work():
            try:
                # Re-login to obtain a fresh token and possibly server-provided clientSessionId
                self.api.username = user
                self.api.password = pwd
                self.api.login()
                # If server did not send csid, generate a fresh one
                try:
                    from rogueeditor.utils import generate_client_session_id
                    csid = self.api.client_session_id or generate_client_session_id()
                    self.api.client_session_id = csid
                    try:
                        save_client_session_id(csid)
                        set_user_csid(user, csid)
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception as e:
                raise e
        def done():
            self.status_var.set(f"Status: Session refreshed for {user}")
            try:
                self.csid_entry.delete(0, tk.END)
                self.csid_entry.insert(0, str(self.api.client_session_id or ""))
            except Exception:
                pass
            self._log("Session refreshed.")
            # Persist and reflect last session update time
            try:
                from datetime import datetime
                from rogueeditor.utils import set_user_last_session_update
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                set_user_last_session_update(user, ts)
                self.session_updated_var.set(f"Last session update: {ts}")
            except Exception:
                pass
        self._run_async("Refreshing session...", work, done)

    def _update_session_label_from_store(self):
        user = self.user_combo.get().strip()
        if not user:
            self.session_updated_var.set("Last session update: -")
            return
        try:
            from rogueeditor.utils import get_user_last_session_update
            ts = get_user_last_session_update(user)
            self.session_updated_var.set(f"Last session update: {ts}" if ts else "Last session update: -")
        except Exception:
            self.session_updated_var.set("Last session update: -")

    def _dump_trainer(self):
        p = trainer_save_path(self.username)
        if os.path.exists(p):
            if not messagebox.askyesno("Overwrite?", f"{p} exists. Overwrite with a fresh dump?"):
                return
        self.editor.dump_trainer()
        self._log(f"Dumped trainer to {p}")

    def _dump_slot_dialog(self):
        slot = self._ask_slot()
        if slot:
            p = slot_save_path(self.username, slot)
            if os.path.exists(p):
                if not messagebox.askyesno("Overwrite?", f"{p} exists. Overwrite with a fresh dump?"):
                    return
            self.editor.dump_slot(slot)
            self._log(f"Dumped slot {slot} to {p}")
    def _dump_slot_selected(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            messagebox.showwarning("Invalid", "Invalid slot")
            return
        p = slot_save_path(self.username, slot)
        if os.path.exists(p):
            if not messagebox.askyesno("Overwrite?", f"{p} exists. Overwrite with a fresh dump?"):
                return
        self.editor.dump_slot(slot)
        self._log(f"Dumped slot {slot} to {p}")

    def _dump_all(self):
        if not messagebox.askyesno("Confirm", "Dump trainer and all slots to local files? Existing files will be overwritten."):
            return
        try:
            self.editor.dump_trainer()
        except Exception as e:
            self._log(f"Trainer dump failed: {e}")
        for i in range(1, 6):
            try:
                self.editor.dump_slot(i)
            except Exception as e:
                self._log(f"Slot {i} dump failed: {e}")
        messagebox.showinfo("Dump All", "Completed dump of trainer and slots 1-5.")
        self._log("Dumped trainer and slots 1-5")

    def _update_trainer(self):
        if messagebox.askyesno("Confirm", "Update trainer from file?"):
            try:
                # Pre-validate JSON
                from rogueeditor.utils import trainer_save_path, load_json
                p = trainer_save_path(self.username)
                try:
                    data = load_json(p)
                except Exception as e:
                    messagebox.showerror("Invalid trainer.json", f"{p}\n\n{e}")
                    return
                if not isinstance(data, dict):
                    messagebox.showerror("Invalid trainer.json", "Top-level must be a JSON object.")
                    return
                self.api.update_trainer(data)
                self._log("Trainer updated from file.")
                messagebox.showinfo("Upload", "Trainer uploaded successfully.")
                # Offer verification
                if messagebox.askyesno("Verify", "Verify trainer on server matches local changes (key fields)?"):
                    self._verify_trainer_against_local()
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
                from rogueeditor.utils import slot_save_path, load_json
                p = slot_save_path(self.username, slot)
                try:
                    data = load_json(p)
                except Exception as e:
                    messagebox.showerror("Invalid slot file", f"{p}\n\n{e}")
                    return
                if not isinstance(data, dict):
                    messagebox.showerror("Invalid slot file", "Top-level must be a JSON object.")
                    return
                self.api.update_slot(slot, data)
                self._log(f"Slot {slot} updated from file.")
                messagebox.showinfo("Upload", f"Slot {slot} uploaded successfully.")
                # Offer verification
                if messagebox.askyesno("Verify", f"Verify slot {slot} on server matches local changes (party/modifiers)?"):
                    self._verify_slot_against_local(slot)
            except Exception as e:
                messagebox.showerror("Upload failed", str(e))
                return

    def _upload_all(self):
        # Upload trainer.json and all present slot files (1-5) to the server
        from rogueeditor.utils import trainer_save_path, slot_save_path, load_json
        if not self.username:
            messagebox.showwarning("Not logged in", "Please login first")
            return
        if not messagebox.askyesno(
            "Confirm",
            "Upload trainer.json and all available slot files (1-5) to the server?\n\nThis overwrites server state.",
        ):
            return
        successes: list[str] = []
        errors: list[str] = []
        # Trainer
        try:
            tp = trainer_save_path(self.username)
            if os.path.exists(tp):
                data = load_json(tp)
                if not isinstance(data, dict):
                    raise ValueError("trainer.json must contain a JSON object")
                self.api.update_trainer(data)
                successes.append("trainer")
            else:
                self._log(f"trainer.json not found at {tp}; skipping trainer upload")
        except Exception as e:
            errors.append(f"trainer: {e}")
        # Slots 1..5
        for i in range(1, 6):
            try:
                sp = slot_save_path(self.username, i)
                if not os.path.exists(sp):
                    continue
                data = load_json(sp)
                if not isinstance(data, dict):
                    raise ValueError(f"slot {i}.json must contain a JSON object")
                self.api.update_slot(i, data)
                successes.append(f"slot {i}")
            except Exception as e:
                errors.append(f"slot {i}: {e}")
        # Summary
        if successes:
            self._log("Uploaded: " + ", ".join(successes))
        if errors:
            messagebox.showwarning("Upload completed with errors", "\n".join(errors))
        else:
            messagebox.showinfo("Upload All", "Upload completed successfully.")

    def _hatch_eggs(self):
        try:
            self.editor.hatch_all_eggs()
            self._log("Eggs set to hatch after next fight.")
            messagebox.showinfo("Eggs", "All eggs will hatch after the next fight.")
        except Exception as e:
            messagebox.showerror("Hatch failed", str(e))

    # --- Verification helpers ---
    def _verify_slot_against_local(self, slot: int) -> None:
        try:
            from rogueeditor.utils import slot_save_path, load_json
            local_path = slot_save_path(self.username, slot)
            if not os.path.exists(local_path):
                messagebox.showwarning("No local dump", f"{local_path} not found. Dump first.")
                return
            local = load_json(local_path)
            remote = self.api.get_slot(slot)
            report_lines = [f"Verify slot {slot}", ""]
            keys = ['party', 'modifiers']
            all_ok = True
            for k in keys:
                l = local.get(k)
                r = remote.get(k)
                ok = (l == r)
                all_ok = all_ok and ok
                report_lines.append(f"[{k}] -> {'OK' if ok else 'MISMATCH'}")
            if all_ok:
                messagebox.showinfo("Verify", f"Slot {slot} matches local for keys: {', '.join(keys)}.")
            else:
                self._show_text_dialog(f"Verify Slot {slot}", "\n".join(report_lines))
        except Exception as e:
            messagebox.showerror("Verify failed", str(e))

    def _verify_trainer_against_local(self) -> None:
        try:
            from rogueeditor.utils import trainer_save_path, load_json
            local_path = trainer_save_path(self.username)
            if not os.path.exists(local_path):
                messagebox.showwarning("No local dump", f"{local_path} not found. Dump first.")
                return
            local = load_json(local_path)
            remote = self.api.get_trainer()
            report_lines = ["Verify trainer", ""]
            keys = ['voucherCounts', 'starterData', 'dexData', 'money']
            all_ok = True
            for k in keys:
                l = local.get(k)
                r = remote.get(k)
                ok = (l == r)
                all_ok = all_ok and ok
                report_lines.append(f"[{k}] -> {'OK' if ok else 'MISMATCH'}")
            if all_ok:
                messagebox.showinfo("Verify", "Trainer matches local for key fields.")
            else:
                self._show_text_dialog("Verify Trainer", "\n".join(report_lines))
        except Exception as e:
            messagebox.showerror("Verify failed", str(e))

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
        self._modalize(top)

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
        from rogueeditor.utils import slot_save_path, load_json
        def work():
            rows = []
            any_local = False
            any_outdated = False
            # Compare dump times with last session update if available
            last_update_ts = None
            try:
                from rogueeditor.utils import get_user_last_session_update
                ts_str = get_user_last_session_update(self.username or "")
                if ts_str:
                    import datetime as _dt
                    last_update_ts = _dt.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp()
            except Exception:
                last_update_ts = None
            for i in range(1, 6):
                party_ct = '-'
                playtime = '-'
                empty = True
                local = '-'
                p = slot_save_path(self.username, i)
                if os.path.exists(p):
                    any_local = True
                    try:
                        data = load_json(p)
                        party = data.get('party') or []
                        party_ct = len(party)
                        pt = data.get('playTime') or 0
                        try:
                            h = int(pt) // 3600
                            m = (int(pt) % 3600) // 60
                            s = int(pt) % 60
                            playtime = f"{h:02d}:{m:02d}:{s:02d}"
                        except Exception:
                            playtime = '-'
                        empty = (party_ct == 0 and (int(pt) if isinstance(pt, int) else 0) == 0)
                    except Exception:
                        empty = True
                    ts = os.path.getmtime(p)
                    local = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                    if last_update_ts and ts < last_update_ts:
                        any_outdated = True
                rows.append((i, party_ct, playtime, local, empty))
            def update():
                for r in self.slot_tree.get_children():
                    self.slot_tree.delete(r)
                for (slot, party_ct, playtime, local, empty) in rows:
                    tags = ('empty',) if empty else ()
                    self.slot_tree.insert('', 'end', values=(slot, party_ct, playtime, local), tags=tags)
                # Informative messages
                if not any_local:
                    try:
                        messagebox.showinfo('No local dumps', 'No local dumps found. Use Data IO ? Dump to fetch trainer and/or slots you want to edit.')
                    except Exception:
                        pass
                elif any_outdated:
                    try:
                        messagebox.showwarning('Dumps may be out of date', 'Some local dumps are older than the last login. Consider dumping again to avoid overwriting newer server data.')
                    except Exception:
                        pass
            self.after(0, update)
        self._run_async("Loading local slots...", work)

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
            try:
                opt.transient(self)
                opt.grab_set()
            except Exception:
                pass
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
        self._modalize(top)

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

    def _open_item_mgr(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            ItemManagerDialog(self, self.api, self.editor, slot)
            self._log(f"Opened item manager for slot {slot}")

    def _unlock_all_starters(self):
        # Strong warning + typed confirmation
        if not messagebox.askyesno('Warning', 'This will UNLOCK ALL STARTERS with perfect IVs and shiny variants. Proceed?'):
            return
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
        if not messagebox.askyesno('Warning', f'This will unlock ALL passives for {ident}. Proceed?'):
            return
        # Phrase confirmation
        top = tk.Toplevel(self)
        top.title('Unlock All Passives - Confirmation')
        msg = (
            'WARNING:\n\nThis action will set passiveAttr to an unlocked mask for the selected starter.\n'
            'It may impact progression. To confirm, type the phrase exactly:'
        )
        ttk.Label(top, text=msg, justify=tk.LEFT, wraplength=520).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
        expected = 'UNLOCK ALL PASSIVES'
        ttk.Label(top, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
        phrase_var = tk.StringVar()
        ttk.Entry(top, textvariable=phrase_var, width=34).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
        def proceed():
            text = (phrase_var.get() or '').strip()
            if text != expected:
                messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                return
            try:
                self.editor.unlock_all_passives(ident, mask=7)
                self._log(f'Unlocked all passives for {ident}.')
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))
        ttk.Button(top, text='Cancel', command=top.destroy).grid(row=2, column=0, padx=8, pady=10, sticky=tk.W)
        ttk.Button(top, text='Proceed', command=proceed).grid(row=2, column=1, padx=8, pady=10, sticky=tk.E)

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
        ttk.Label(top, text='Cost Reduction (valueReduction):').grid(row=3, column=2, sticky=tk.E)
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
                messagebox.showwarning('Invalid', 'Counts and cost reduction must be integers')
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
            if not messagebox.askyesno('Warning', 'This will unlock the selected starter and update your account on the server. Proceed?'):
                return
            # Phrase confirmation
            confirm = tk.Toplevel(self)
            confirm.title('Unlock Starter - Confirmation')
            msg = 'Type the phrase to confirm:'
            ttk.Label(confirm, text=msg, justify=tk.LEFT, wraplength=420).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
            expected = 'UNLOCK STARTER'
            ttk.Label(confirm, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
            pv = tk.StringVar()
            ttk.Entry(confirm, textvariable=pv, width=30).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
            def proceed_unlock():
                if (pv.get() or '').strip() != expected:
                    messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                    return
                confirm.destroy()
                do_apply()
            ttk.Button(confirm, text='Cancel', command=confirm.destroy).grid(row=2, column=0, padx=8, pady=8, sticky=tk.W)
            ttk.Button(confirm, text='Proceed', command=proceed_unlock).grid(row=2, column=1, padx=8, pady=8, sticky=tk.E)
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
            messagebox.showwarning("Invalid", "Cost reduction must be integer")
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
        if not messagebox.askyesno("Confirm", f"Apply Gacha ? C/R/E/L = {d0}/{d1}/{d2}/{d3} (save locally)?"):
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
    # Initialize logging early so startup issues are captured
    logger = setup_logging()
    attach_stderr_tee(logger)
    install_excepthook(logger)
    log_environment(logger)

    # Ensure GUI starts from the main thread to avoid Tcl/Tk notifier errors on Windows
    try:
        import threading as _th
        if _th.current_thread() is not _th.main_thread():
            raise RuntimeError('GUI must be launched from the main thread')
    except Exception as e:
        log_exception_context("Main-thread check failed", logger)
        print("[ERROR] GUI must be launched from the main thread.")
        print(crash_hint())
        return 2

    # Optional proactive healthcheck on first run or after a failed run
    try:
        should_check = is_first_run() or (last_run_success() is False)
    except Exception:
        should_check = False
    if should_check:
        try:
            run_healthcheck(trigger="startup")
        except Exception:
            log_exception_context("Healthcheck failed", logger)

    # Create a single Tk root and host App as a Frame to avoid multiple Tk instances
    try:
        # On Windows, help Tk find the correct bundled Tcl/Tk if env vars are unset
        import sys as _sys, os as _os
        if _os.name == 'nt' and not _os.environ.get('TCL_LIBRARY') and not _os.environ.get('TK_LIBRARY'):
            base = getattr(_sys, 'base_prefix', _sys.exec_prefix)
            tcl_dir = _os.path.join(base, 'tcl', 'tcl8.6')
            tk_dir = _os.path.join(base, 'tcl', 'tk8.6')
            if _os.path.isdir(tcl_dir) and _os.path.isdir(tk_dir):
                _os.environ['TCL_LIBRARY'] = tcl_dir
                _os.environ['TK_LIBRARY'] = tk_dir
                try:
                    logger.info('Set TCL_LIBRARY to %s and TK_LIBRARY to %s', tcl_dir, tk_dir)
                except Exception:
                    pass
        root = tk.Tk()
    except Exception:
        log_exception_context("Failed to initialize Tk root", logger)
        print("[ERROR] Failed to initialize GUI (Tk).")
        print(crash_hint())
        record_run_result(3, trigger="gui")
        return 3
    try:
        app = App(root)
        root.mainloop()
    except Exception:
        log_exception_context("Unhandled error in GUI mainloop", logger)
        print("[ERROR] Unhandled GUI error.")
        print(crash_hint())
        record_run_result(4, trigger="gui")
        return 4
    record_run_result(0, trigger="gui")
    return 0
    def __init__(self, master: App, api: PokerogueAPI, editor: Editor, slot: int):
        super().__init__(master)
        self.title(f"Team Editor - Slot {slot}")
        self.geometry("1000x600")
        self.api = api
        self.editor = editor
        self.slot = slot
        self.data = self.api.get_slot(slot)
        self.party = self.data.get("party") or []
        self._build()
        try:
            master._modalize(self)
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
        move_name_to_id, move_id_to_name = load_move_catalog()
        abil_name_to_id, abil_id_to_name = load_ability_catalog()
        nat_name_to_id, nat_id_to_name = load_nature_catalog()
        # Store move catalogs for labels
        self.move_name_to_id = move_name_to_id
        self.move_id_to_name = move_id_to_name

        # Section: Identity
        ident = ttk.LabelFrame(parent, text="Identity")
        ident.grid(row=0, column=0, columnspan=6, sticky=tk.W+tk.E, padx=2, pady=2)
        ttk.Label(ident, text="Level:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        self.level_var = tk.StringVar()
        ttk.Entry(ident, textvariable=self.level_var, width=6).grid(row=0, column=1, sticky=tk.W, padx=2, pady=2)
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

        ttk.Label(ident, text="Ability:").grid(row=0, column=2, sticky=tk.W, padx=8)
        self.ability_ac = AutoCompleteEntry(ident, abil_name_to_id, width=24)
        self.ability_ac.grid(row=0, column=3, sticky=tk.W, padx=2)
        ttk.Button(ident, text="Pick", command=lambda: self._pick_from_catalog(self.ability_ac, abil_name_to_id, 'Select Ability')).grid(row=0, column=4, sticky=tk.W, padx=2)

        ttk.Label(ident, text="Nature:").grid(row=1, column=0, sticky=tk.W, padx=4)
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
        self.nature_cb = ttk.Combobox(ident, values=nature_items, width=28)
        self.nature_cb.grid(row=1, column=1, sticky=tk.W, padx=2)
        self.nature_cb.bind('<<ComboboxSelected>>', lambda e: self._on_nature_change())
        # Nature effect hint label
        self.nature_hint = ttk.Label(ident, text="")
        self.nature_hint.grid(row=1, column=5, sticky=tk.W, padx=6)

        # Held Item(s)
        ttk.Label(ident, text="Held Item(s):").grid(row=1, column=2, sticky=tk.W, padx=8)
        try:
            item_name_to_id, item_id_to_name = load_item_catalog()
        except Exception:
            item_name_to_id = {}
            item_id_to_name = {}
        if item_name_to_id:
            self.held_item_ac = AutoCompleteEntry(ident, item_name_to_id, width=20)
            self.held_item_ac.grid(row=1, column=3, sticky=tk.W, padx=2)
            ttk.Button(ident, text="Pick", command=lambda: self._pick_from_catalog(self.held_item_ac, item_name_to_id, 'Select Item')).grid(row=1, column=4, sticky=tk.W, padx=2)
            ttk.Button(ident, text="Manage Items...", command=self._open_item_manager_for_current).grid(row=1, column=6, sticky=tk.W, padx=6)
            self.held_item_var = None
        else:
            self.held_item_var = tk.StringVar()
            ttk.Entry(ident, textvariable=self.held_item_var, width=8).grid(row=1, column=3, sticky=tk.W, padx=2)
            ttk.Button(ident, text="Manage Items...", command=self._open_item_manager_for_current).grid(row=1, column=6, sticky=tk.W, padx=6)

        # Section: IVs and Calculated Stats
        stats_sec = ttk.LabelFrame(parent, text="IVs & Stats")
        stats_sec.grid(row=1, column=0, columnspan=6, sticky=tk.W+tk.E, padx=2, pady=4)
        ttk.Label(stats_sec, text="IVs:").grid(row=0, column=0, sticky=tk.NW, padx=4)
        self.iv_vars = [tk.StringVar() for _ in range(6)]
        iv_labels = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]
        iv_frame = ttk.Frame(stats_sec)
        iv_frame.grid(row=0, column=1, columnspan=3, sticky=tk.W)
        # Left column (HP/Atk/Def)
        for i, lab in enumerate(iv_labels[:3]):
            ttk.Label(iv_frame, text=lab+":").grid(row=i, column=0, sticky=tk.E, padx=2, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[i], width=4).grid(row=i, column=1, sticky=tk.W)
        # Right column (SpA/SpD/Spe)
        for j, lab in enumerate(iv_labels[3:], start=3):
            ttk.Label(iv_frame, text=lab+":").grid(row=j-3, column=2, sticky=tk.E, padx=8, pady=1)
            ttk.Entry(iv_frame, textvariable=self.iv_vars[j], width=4).grid(row=j-3, column=3, sticky=tk.W)

        # Calculated Stats (derived from Level + IVs, EV=0)
        ttk.Label(stats_sec, text="Calculated Stats:").grid(row=1, column=0, sticky=tk.NW, padx=4)
        stats_frame = ttk.Frame(stats_sec)
        stats_frame.grid(row=1, column=1, columnspan=3, sticky=tk.W)
        self.stat_lbls = []
        for i, lab in enumerate(["HP", "Atk", "Def", "SpA", "SpD", "Spe"]):
            ttk.Label(stats_frame, text=lab+":").grid(row=i//3, column=(i%3)*2, sticky=tk.W, padx=(0, 4))
            val = ttk.Label(stats_frame, text="-")
            val.grid(row=i//3, column=(i%3)*2+1, sticky=tk.W, padx=(0, 12))
            self.stat_lbls.append(val)

        # Section: Moves
        moves_sec = ttk.LabelFrame(parent, text="Moves")
        moves_sec.grid(row=2, column=0, columnspan=6, sticky=tk.W+tk.E, padx=2, pady=4)
        ttk.Label(moves_sec, text="Moves:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.move_acs = []
        self.move_lbls = []
        for i in range(4):
            ac = AutoCompleteEntry(moves_sec, move_name_to_id, width=30)
            ac.grid(row=i, column=1, sticky=tk.W, pady=1, padx=2)
            ac.bind('<KeyRelease>', lambda e, j=i: self._on_move_ac_change(j))
            ac.bind('<FocusOut>', lambda e, j=i: self._on_move_ac_change(j))
            ttk.Button(moves_sec, text="Pick", command=lambda j=i: self._pick_from_catalog(self.move_acs[j], move_name_to_id, f'Select Move {j+1}')).grid(row=i, column=2, sticky=tk.W, padx=2)
            lbl = ttk.Label(moves_sec, text="", width=28)
            lbl.grid(row=i, column=3, sticky=tk.W, padx=6)
            self.move_lbls.append(lbl)
            self.move_acs.append(ac)

        # Section: Items & Modifiers preview
        itm_sec = ttk.LabelFrame(parent, text="Items & Modifiers")
        itm_sec.grid(row=3, column=0, columnspan=6, sticky=tk.W+tk.E, padx=2, pady=4)
        ttk.Label(itm_sec, text="Item effects (preview):").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.item_effects_lbl = ttk.Label(itm_sec, text="-", width=60)
        self.item_effects_lbl.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(itm_sec, text="Adjust Item Stacks...", command=self._edit_item_stacks).grid(row=0, column=2, sticky=tk.W, padx=4)

        # Actions
        ttk.Button(parent, text="Save to file", command=self._save).grid(row=4, column=0, pady=8, padx=2, sticky=tk.W)
        ttk.Button(parent, text="Upload", command=self._upload).grid(row=4, column=1, pady=8, padx=2, sticky=tk.W)

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
        # Update item effects preview
        self._update_item_effects()

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
        # Divide out item multipliers first
        try:
            sel = self.team_list.curselection()[0]
            mon = self.party[sel]
            item_mults = self._item_stat_multipliers(mon)
            for i in range(6):
                m = item_mults[i] if 0 <= i < len(item_mults) else 1.0
                if m and abs(m - 1.0) > 1e-6:
                    actual[i] = max(1, round(actual[i] / m))
        except Exception:
            pass
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
        # Apply item-based stat multipliers (10% per stack)
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
        # Prefer catalog base stats if available (from Source/data/base_stats.json)
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

    def _open_item_manager_for_current(self):
        # Open the item/modifier manager with the currently selected Pokemon pre-selected
        try:
            if not self.team_list.curselection():
                messagebox.showwarning("No selection", "Select a team member first")
                return
            sel = self.team_list.curselection()[0]
            mon = self.party[sel]
            mon_id = mon.get('id')
        except Exception:
            mon_id = None
        try:
            # Instantiate with optional preselect id
            ItemManagerDialog(self, self.api, self.editor, self.slot, preselect_mon_id=mon_id)
        except TypeError:
            # Fallback if constructor signature not updated
            ItemManagerDialog(self, self.api, self.editor, self.slot)

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

    def _update_item_effects(self):
        # Inspect modifiers targeting current mon and show multipliers summary
        try:
            if not self.team_list.curselection():
                self.item_effects_lbl.configure(text='-')
                return
            idx = self.team_list.curselection()[0]
            mon = self.party[idx]
            mults = self._item_stat_multipliers(mon)
            labels = ["HP","Atk","Def","SpA","SpD","Spe"]
            parts = []
            for i, m in enumerate(mults):
                if abs(m - 1.0) > 1e-6:
                    parts.append(f"{labels[i]} x{m:.2f}")
            text = ', '.join(parts) if parts else 'None'
            self.item_effects_lbl.configure(text=text)
        except Exception:
            self.item_effects_lbl.configure(text='-')

    def _item_stat_multipliers(self, mon: dict) -> list[float]:
        # Returns per-stat multipliers [HP, Atk, Def, SpA, SpD, Spe]
        out = [1.0] * 6
        try:
            mon_id = mon.get('id')
            mods = self.data.get('modifiers') or []
            # Map typeId -> affected stat indices
            type_to_indices = {
                'CHOICE_BAND': [1],
                'MUSCLE_BAND': [1],
                'CHOICE_SPECS': [3],
                'WISE_GLASSES': [3],
                'CHOICE_SCARF': [5],
                'EVIOLITE': [2, 4],
            }
            # Build stat id -> index mapping for BASE_STAT_BOOSTER
            from rogueeditor.catalog import load_stat_catalog
            _, stat_id_to_name = load_stat_catalog()
            name_to_idx = {
                'hp': 0,
                'attack': 1,
                'defense': 2,
                'sp_attack': 3,
                'sp_defense': 4,
                'speed': 5,
            }
            for m in mods:
                if not isinstance(m, dict):
                    continue
                args = m.get('args') or []
                if not (args and isinstance(args, list) and isinstance(args[0], int) and args[0] == mon_id):
                    continue
                tid = str(m.get('typeId') or '').upper()
                stacks = 0
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
                        name = stat_id_to_name.get(int(sid), '').strip().lower()
                        name = name.replace(' ', '_')
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

    def _edit_item_stacks(self):
        # Dialog to adjust stackCount for stat-boosting modifiers on current mon
        if not self.team_list.curselection():
            return
        idx = self.team_list.curselection()[0]
        mon = self.party[idx]
        mon_id = mon.get('id')
        mods = self.data.get('modifiers') or []
        # Collect indexes for recognized modifiers
        recognized = []
        rec_types = {'CHOICE_BAND','MUSCLE_BAND','CHOICE_SPECS','WISE_GLASSES','CHOICE_SCARF','EVIOLITE','BASE_STAT_BOOSTER'}
        for i, m in enumerate(mods):
            if not isinstance(m, dict):
                continue
            args = m.get('args') or []
            if args and isinstance(args, list) and isinstance(args[0], int) and args[0] == mon_id:
                tid = str(m.get('typeId') or '').upper()
                if tid in rec_types:
                    recognized.append((i, m))
        if not recognized:
            messagebox.showinfo('No items', 'No recognized stat-boosting modifiers found for this PokÃ©mon.')
            return
        top = tk.Toplevel(self)
        top.title('Adjust Item Stacks')
        rows = []
        for r, (i, m) in enumerate(recognized):
            tid = str(m.get('typeId') or '')
            ttk.Label(top, text=f"[{i}] {tid}").grid(row=r, column=0, sticky=tk.W, padx=6, pady=4)
            var = tk.StringVar(value=str(m.get('stackCount') or 1))
            ttk.Entry(top, textvariable=var, width=6).grid(row=r, column=1, sticky=tk.W)
            rows.append((i, var))
        def apply_changes():
            changed = False
            for i, var in rows:
                try:
                    val = int(var.get().strip())
                except Exception:
                    continue
                if val < 0:
                    val = 0
                if mods[i].get('stackCount') != val:
                    mods[i]['stackCount'] = val
                    changed = True
            if changed:
                from rogueeditor.utils import slot_save_path, dump_json
                p = slot_save_path(self.api.username, self.slot)
                dump_json(p, self.data)
                if messagebox.askyesno('Upload', 'Upload changes to server now?'):
                    from rogueeditor.utils import load_json
                    payload = load_json(p)
                    try:
                        self.api.update_slot(self.slot, payload)
                        messagebox.showinfo('Uploaded', 'Server updated.')
                    except Exception as e:
                        messagebox.showerror('Upload failed', str(e))
                # Refresh previews and stats
                self._update_item_effects()
                self._update_calculated_stats()
            top.destroy()
        ttk.Button(top, text='Apply', command=apply_changes).grid(row=len(rows), column=0, columnspan=2, pady=8)



class _ItemManagerDialog_Legacy(tk.Toplevel):
    def __init__(self, master: App, api: PokerogueAPI, editor: Editor, slot: int, preselect_mon_id: int | None = None):
        super().__init__(master)
        self.title(f"Modifiers & Items Manager - Slot {slot}")
        self.geometry('900x520')
        self.api = api
        self.editor = editor
        self.slot = slot
        self._preselect_mon_id = preselect_mon_id
        # Load slot data once
        self.data = self.api.get_slot(slot)
        self.party = self.data.get('party') or []
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
        left = ttk.LabelFrame(top, text='Target')
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        ttk.Label(left, text='Apply to:').pack(anchor=tk.W, padx=4, pady=(2,0))
        self.target_var = tk.StringVar(value='Pokemon')
        target_row = ttk.Frame(left)
        target_row.pack(fill=tk.X, padx=4, pady=2)
        ttk.Radiobutton(target_row, text='Pokemon', variable=self.target_var, value='Pokemon', command=self._on_target_change).pack(side=tk.LEFT)
        ttk.Radiobutton(target_row, text='Trainer', variable=self.target_var, value='Trainer', command=self._on_target_change).pack(side=tk.LEFT, padx=8)
        ttk.Label(left, text='Party:').pack(anchor=tk.W, padx=4)
        self.party_list = tk.Listbox(left, height=10)
        self.party_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.party_list.bind('<<ListboxSelect>>', lambda e: self._refresh_mods())
        self.mod_list = tk.Listbox(left, height=10)
        self.mod_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.mod_list.bind('<Double-Button-1>', lambda e: self._show_selected_detail())
        btns = ttk.Frame(left)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text='Edit Stacks...', command=self._edit_selected_stacks).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btns, text='Remove Selected', command=self._remove_selected).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btns, text='Refresh', command=self._refresh_mods).pack(side=tk.LEFT, padx=4, pady=4)

        # Right: pickers to add items/modifiers
        right = ttk.LabelFrame(top, text='Add Item / Modifier')
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        row = 0
        ttk.Label(right, text='Category:').grid(row=row, column=0, sticky=tk.W)
        self.cat_var = tk.StringVar(value='Common')
        cat_opts = ['Common', 'Accuracy', 'Berries', 'Base Stat Booster', 'Observed', 'Player (Trainer)']
        self.cat_cb = ttk.Combobox(right, textvariable=self.cat_var, values=cat_opts, state='readonly', width=24)
        self.cat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        self.cat_cb.bind('<<ComboboxSelected>>', lambda e: self._on_cat_change())
        row += 1

        # Common one-arg items
        self.common_var = tk.StringVar()
        self.common_cb = ttk.Combobox(right, textvariable=self.common_var, values=sorted(list(self._common_items())), width=28)
        ttk.Label(right, text='Common:').grid(row=row, column=0, sticky=tk.W)
        self.common_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        row += 1

        # Accuracy items with boost
        self.acc_var = tk.StringVar()
        self.acc_cb = ttk.Combobox(right, textvariable=self.acc_var, values=['WIDE_LENS', 'MULTI_LENS'], width=28)
        ttk.Label(right, text='Accuracy item:').grid(row=row, column=0, sticky=tk.W)
        self.acc_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Label(right, text='Boost:').grid(row=row, column=2, sticky=tk.E)
        self.acc_boost = ttk.Entry(right, width=6)
        self.acc_boost.insert(0, '5')
        self.acc_boost.grid(row=row, column=3, sticky=tk.W)
        row += 1

        # Berries
        from rogueeditor.catalog import load_berry_catalog
        berry_n2i, berry_i2n = load_berry_catalog()
        self.berry_var = tk.StringVar()
        self.berry_cb = ttk.Combobox(right, textvariable=self.berry_var, values=sorted([f"{k} ({v})" for k,v in berry_n2i.items()]), width=28)
        ttk.Label(right, text='Berry:').grid(row=row, column=0, sticky=tk.W)
        self.berry_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        row += 1

        # Base Stat Booster
        from rogueeditor.catalog import load_stat_catalog
        stat_n2i, stat_i2n = load_stat_catalog()
        self.stat_var = tk.StringVar()
        self.stat_cb = ttk.Combobox(right, textvariable=self.stat_var, values=sorted([f"{k} ({v})" for k,v in stat_n2i.items()]), width=28)
        ttk.Label(right, text='Base stat:').grid(row=row, column=0, sticky=tk.W)
        self.stat_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        # Hint about stat boosters per stack
        try:
            self.stat_hint = ttk.Label(right, text='')
            self.stat_hint.grid(row=row, column=2, columnspan=2, sticky=tk.W)
        except Exception:
            pass
        row += 1

        # Observed from dumps
        self.obs_var = tk.StringVar()
        self.obs_cb = ttk.Combobox(right, textvariable=self.obs_var, values=[], width=28)
        ttk.Label(right, text='Observed typeId:').grid(row=row, column=0, sticky=tk.W)
        self.obs_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        row += 1

        # Player (trainer) modifiers
        ttk.Label(right, text='Player mod typeId:').grid(row=row, column=0, sticky=tk.W)
        self.player_type_var = tk.StringVar()
        self.player_type_cb = ttk.Combobox(right, textvariable=self.player_type_var, values=['EXP_CHARM','SUPER_EXP_CHARM','EXP_SHARE','MAP','IV_SCANNER','GOLDEN_POKEBALL'], width=28)
        self.player_type_cb.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        ttk.Label(right, text='Args (ints, comma-separated):').grid(row=row, column=2, sticky=tk.E)
        self.player_args_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.player_args_var, width=18).grid(row=row, column=3, sticky=tk.W)
        row += 1

        ttk.Label(right, text='Stacks:').grid(row=row, column=2, sticky=tk.E)
        self.stack_var = tk.StringVar(value='1')
        ttk.Entry(right, textvariable=self.stack_var, width=6).grid(row=row, column=3, sticky=tk.W)
        row += 1
        self.btn_add = ttk.Button(right, text='Add', command=self._add, state=tk.DISABLED)
        self.btn_add.grid(row=row, column=1, sticky=tk.W, padx=4, pady=6)
        self.btn_save = ttk.Button(right, text='Save to file', command=self._save, state=tk.DISABLED)
        self.btn_save.grid(row=row, column=2, sticky=tk.W, padx=4, pady=6)
        self.btn_upload = ttk.Button(right, text='Upload', command=self._upload, state=tk.DISABLED)
        self.btn_upload.grid(row=row, column=3, sticky=tk.W, padx=4, pady=6)

    def _common_items(self) -> set[str]:
        return {
            "FOCUS_BAND", "MYSTICAL_ROCK", "SOOTHE_BELL", "SCOPE_LENS", "LEEK", "EVIOLITE",
            "SOUL_DEW", "GOLDEN_PUNCH", "GRIP_CLAW", "QUICK_CLAW", "KINGS_ROCK", "LEFTOVERS",
            "SHELL_BELL", "TOXIC_ORB", "FLAME_ORB", "BATON"
        }

    def _on_cat_change(self):
        # Adjust available categories and hint text when switching contexts
        try:
            if hasattr(self, 'stat_hint'):
                self.stat_hint.configure(text='')
        except Exception:
            pass
        # When target changes, restrict categories accordingly
        tgt = self.target_var.get()
        if tgt == 'Trainer':
            vals = ['Player (Trainer)']
        else:
            vals = ['Common', 'Accuracy', 'Berries', 'Base Stat Booster', 'Observed']
        try:
            self.cat_cb['values'] = vals
            if self.cat_var.get() not in vals:
                self.cat_var.set(vals[0])
        except Exception:
            pass

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
            did = str(mon.get('species') or mon.get('dexId') or mon.get('speciesId') or '?')
            name = inv.get(did, did)
            mid = mon.get('id')
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

    def _preselect_party(self):
        try:
            if not isinstance(self._preselect_mon_id, int):
                return
            # Find index in party by mon id
            for idx, mon in enumerate(self.party):
                try:
                    if int(mon.get('id')) == int(self._preselect_mon_id):
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
        mods = self.data.get('modifiers') or []
        for m in mods:
            if isinstance(m, dict) and m.get('typeId'):
                obs.add(str(m.get('typeId')))
        try:
            from rogueeditor.utils import user_save_dir
            base = user_save_dir(self.api.username)
            for fname in os.listdir(base):
                if not fname.endswith('.json'):
                    continue
                try:
                    from rogueeditor.utils import load_json
                    d = load_json(os.path.join(base, fname))
                    for m in d.get('modifiers') or []:
                        if isinstance(m, dict) and m.get('typeId'):
                            obs.add(str(m.get('typeId')))
                except Exception:
                    continue
        except Exception:
            pass
        # Merge with curated sets
        obs |= self._common_items() | { 'WIDE_LENS', 'MULTI_LENS', 'BERRY', 'BASE_STAT_BOOSTER' }
        self.obs_cb['values'] = sorted(list(obs))

    def _current_mon(self):
        try:
            idx = self.party_list.curselection()[0]
            return self.party[idx]
        except Exception:
            return None

    def _refresh_mods(self):
        self.mod_list.delete(0, tk.END)
        target = self.target_var.get()
        mods = self.data.get('modifiers') or []
        if target == 'Trainer':
            # Show player-level mods
            party_ids = set(int((p.get('id'))) for p in self.party if isinstance(p.get('id'), int))
            for i, m in enumerate(mods):
                if not isinstance(m, dict):
                    continue
                args = m.get('args') or []
                first = args[0] if (isinstance(args, list) and args) else None
                if not (isinstance(first, int) and first in party_ids):
                    self.mod_list.insert(tk.END, f"[{i}] {m.get('typeId')} args={m.get('args')} stack={m.get('stackCount')}")
        else:
            mon = self._current_mon()
            if not mon:
                return
            mon_id = mon.get('id')
            for i, m in enumerate(mods):
                if not isinstance(m, dict):
                    continue
                args = m.get('args') or []
                if args and isinstance(args, list) and isinstance(args[0], int) and args[0] == mon_id:
                    self.mod_list.insert(tk.END, f"[{i}] {m.get('typeId')} args={m.get('args')} stack={m.get('stackCount')}")
        # Adjust category and button states after refresh
        try:
            self._on_cat_change()
        except Exception:
            pass
        try:
            # Enable Save/Upload only if dirty flags say so
            self.btn_save.configure(state=(tk.NORMAL if getattr(self, '_dirty_local', False) or getattr(self, '_dirty_server', False) else tk.DISABLED))
            self.btn_upload.configure(state=(tk.NORMAL if getattr(self, '_dirty_server', False) else tk.DISABLED))
        except Exception:
            pass

    def _remove_selected(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith('['):
            return
        try:
            idx = int(sel.split(']',1)[0][1:])
        except Exception:
            return
        if messagebox.askyesno('Confirm', f'Remove modifier index {idx}?'):
            ok = self.editor.remove_modifier_by_index(self.slot, idx)
            if ok:
                # Reload latest slot snapshot
                self.data = self.api.get_slot(self.slot)
                self.party = self.data.get('party') or []
                self._refresh_mods()
            else:
                messagebox.showwarning('Failed', 'Unable to remove modifier')

    def _show_selected_detail(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith('['):
            return
        try:
            idx = int(sel.split(']',1)[0][1:])
        except Exception:
            return
        mods = self.data.get('modifiers') or []
        if 0 <= idx < len(mods):
            import json as _json
            content = _json.dumps(mods[idx], ensure_ascii=False, indent=2)
            self.master._show_text_dialog(f"Modifier Detail [{idx}]", content)

    def _add(self):
        target = self.target_var.get()
        mon = self._current_mon()
        mon_id = mon.get('id') if mon else None
        cat = self.cat_var.get()
        entry = None
        try:
            stacks = int((self.stack_var.get() or '1').strip())
            if stacks < 0:
                stacks = 0
        except Exception:
            stacks = 1
        if cat == 'Player (Trainer)' or target == 'Trainer':
            t = (self.player_type_var.get() or '').strip().upper()
            if not t:
                return
            # Parse args as comma separated ints
            s = (self.player_args_var.get() or '').strip()
            args = None
            if s:
                try:
                    args = [int(x.strip()) for x in s.split(',') if x.strip()]
                except Exception:
                    args = None
            entry = { 'args': args, 'player': True, 'stackCount': stacks, 'typeId': t }
        elif cat == 'Common':
            t = (self.common_var.get() or '').strip().upper()
            if not t:
                return
            entry = { 'args': [mon_id], 'player': True, 'stackCount': stacks, 'typeId': t }
        elif cat == 'Accuracy':
            t = (self.acc_var.get() or '').strip().upper()
            if not t:
                return
            try:
                boost = int(self.acc_boost.get().strip() or '5')
            except ValueError:
                boost = 5
            entry = { 'args': [mon_id, boost], 'player': True, 'stackCount': stacks, 'typeId': t }
        elif cat == 'Berries':
            sel = (self.berry_var.get() or '').strip()
            bid = None
            if sel.endswith(')') and '(' in sel:
                try:
                    bid = int(sel.rsplit('(',1)[1].rstrip(')'))
                except Exception:
                    bid = None
            if bid is None:
                from rogueeditor.catalog import load_berry_catalog
                n2i, _ = load_berry_catalog()
                key = sel.lower().replace(' ', '_')
                bid = n2i.get(key)
            if not isinstance(bid, int):
                messagebox.showwarning('Invalid', 'Select a berry')
                return
            entry = { 'args': [mon_id, bid], 'player': True, 'stackCount': stacks, 'typeId': 'BERRY', 'typePregenArgs': [bid] }
        elif cat == 'Base Stat Booster':
            sel = (self.stat_var.get() or '').strip()
            sid = None
            if sel.endswith(')') and '(' in sel:
                try:
                    sid = int(sel.rsplit('(',1)[1].rstrip(')'))
                except Exception:
                    sid = None
            if not isinstance(sid, int):
                from rogueeditor.catalog import load_stat_catalog
                n2i, _ = load_stat_catalog()
                key = sel.lower().replace(' ', '_')
                sid = n2i.get(key)
            if not isinstance(sid, int):
                messagebox.showwarning('Invalid', 'Select a stat')
                return
            entry = { 'args': [mon_id, sid], 'player': True, 'stackCount': stacks, 'typeId': 'BASE_STAT_BOOSTER', 'typePregenArgs': [sid] }
        else: # Observed
            t = (self.obs_var.get() or '').strip().upper()
            if not t:
                return
            # Best effort: attach with one arg (mon id)
            entry = { 'args': [mon_id], 'player': True, 'stackCount': stacks, 'typeId': t }
        if not entry:
            return
        mods = self.data.setdefault('modifiers', [])
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
        messagebox.showinfo('Saved', f'Wrote {p}')

    def _upload(self):
        if not messagebox.askyesno('Confirm Upload', 'Upload item changes for this slot to the server?'):
            return
        try:
            from rogueeditor.utils import slot_save_path, load_json
            p = slot_save_path(self.api.username, self.slot)
            data = load_json(p) if os.path.exists(p) else self.data
            self.api.update_slot(self.slot, data)
            messagebox.showinfo('Uploaded', 'Server updated successfully')
            # Refresh snapshot and clear server dirty flag
            try:
                self.data = self.api.get_slot(self.slot)
                self.party = self.data.get('party') or []
                self._dirty_server = False
                self.btn_upload.configure(state=tk.DISABLED)
                if not self._dirty_local:
                    self.btn_save.configure(state=tk.DISABLED)
                self._refresh_mods()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Upload failed', str(e))

    def _edit_selected_stacks(self):
        try:
            sel = self.mod_list.get(self.mod_list.curselection())
        except Exception:
            return
        if not sel.startswith('['):
            return
        try:
            idx = int(sel.split(']',1)[0][1:])
        except Exception:
            return
        top = tk.Toplevel(self)
        top.title(f'Edit Stacks [{idx}]')
        ttk.Label(top, text='stackCount:').grid(row=0, column=0, padx=6, pady=6, sticky=tk.E)
        var = tk.StringVar(value='1')
        ttk.Entry(top, textvariable=var, width=8).grid(row=0, column=1, sticky=tk.W)
        def apply():
            try:
                sc = int(var.get().strip())
            except Exception:
                sc = 1
            if sc < 0:
                sc = 0
            mods = self.data.get('modifiers') or []
            if 0 <= idx < len(mods):
                mods[idx]['stackCount'] = sc
                from rogueeditor.utils import slot_save_path, dump_json
                p = slot_save_path(self.api.username, self.slot)
                dump_json(p, self.data)
                if messagebox.askyesno('Upload', 'Upload changes to server now?'):
                    from rogueeditor.utils import load_json
                    try:
                        payload = load_json(p)
                        self.api.update_slot(self.slot, payload)
                        messagebox.showinfo('Uploaded', 'Server updated.')
                    except Exception as e:
                        messagebox.showerror('Upload failed', str(e))
                self._refresh_mods()
            top.destroy()
        ttk.Button(top, text='Apply', command=apply).grid(row=1, column=0, columnspan=2, pady=8)

class _TeamEditorDialog_Legacy(tk.Toplevel):
    pass


    def _on_target_change(self):
        # Refresh lists and adjust categories when switching target
        try:
            self._refresh_mods()
            self._on_cat_change()
        except Exception:
            pass


