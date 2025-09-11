from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class AutoCompleteEntry(ttk.Entry):
    """Entry with dropdown autocomplete for name->id catalogs.

    Extracted from Source/gui.py (Phase 1). See
    debug/docs/GUI_MIGRATION_PLAN.md for line references and context.
    """

    def __init__(self, master, name_to_id: dict[str, int], **kwargs):
        super().__init__(master, **kwargs)
        self._name_to_id = name_to_id
        # Precompute normalized lookup to improve substring matching
        def _norm(s: str) -> str:
            s = s.strip().lower()
            s = s.replace(' ', '_').replace('-', '_')
            # remove apostrophes/periods
            s = s.replace("'", "").replace('.', '')
            return s
        self._norm = _norm
        self._index = [(k, v, _norm(k)) for k, v in name_to_id.items()]
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
        key = self._norm(v)
        # Try exact normalized match
        for orig, iid, normed in self._index:
            if normed == key:
                return iid
        return self._selected_id

    def set_value(self, text: str):
        self._var.set(text)

    def _on_change(self, *args):
        raw = self._var.get().strip()
        key = self._norm(raw)
        if not key:
            self._hide_popup()
            return
        # Rank: prefix matches, then substring, then close matches via difflib
        names = self._index
        pref = [n for n in names if n[2].startswith(key)]
        subs = [n for n in names if key in n[2] and n not in pref]
        matches = pref + subs
        if len(matches) < 10:
            try:
                import difflib
                pool = [n[2] for n in names]
                close_keys = difflib.get_close_matches(key, pool, n=10, cutoff=0.6)
                for ck in close_keys:
                    for n in names:
                        if n[2] == ck and n not in matches:
                            matches.append(n)
                            if len(matches) >= 20:
                                break
                    if len(matches) >= 20:
                        break
            except Exception:
                pass
        matches = matches[:20]
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
        for orig, iid, _ in matches:
            self._list.insert(tk.END, f"{orig} ({iid})")
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self._popup.geometry(f"300x220+{x}+{y}")
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
        name = sel.split(' (', 1)[0]
        self._var.set(name)
        self._selected_id = self._name_to_id.get(name)
        self._hide_popup()

    def _hide_popup(self):
        if self._popup:
            self._popup.destroy()
            self._popup = None

