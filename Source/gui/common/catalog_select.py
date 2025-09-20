from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class CatalogSelectDialog(tk.Toplevel):
    """Simple searchable select dialog for name->id catalogs.

    Extracted from Source/gui.py (Phase 1). See
    debug/docs/GUI_MIGRATION_PLAN.md for line references and context.
    """

    def __init__(self, master, name_to_id: dict[str, int], title: str = 'Select'):
        super().__init__(master)
        self.title(title)
        self.geometry('400x400')
        self.name_to_id = name_to_id
        self._build()
        
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
        # Precompute normalized names for better filtering
        def _norm(s: str) -> str:
            s = s.strip().lower().replace(' ', '_').replace('-', '_').replace("'", "").replace('.', '')
            return s
        self._norm = _norm
        self._all_norm = [(name, iid, _norm(name)) for name, iid in self._all]
        self._filter('')
        ent.focus_set()

    def _on_change(self, *args):
        self._filter(self.var.get().strip().lower().replace(' ', '_'))

    def _filter(self, key: str):
        k = self._norm(key)
        self.list.delete(0, tk.END)
        # Prefix then substring
        pref = [e for e in self._all_norm if e[2].startswith(k)]
        subs = [e for e in self._all_norm if k in e[2] and e not in pref]
        results = pref + subs
        if not results:
            try:
                import difflib
                pool = [e[2] for e in self._all_norm]
                close = difflib.get_close_matches(k, pool, n=20, cutoff=0.6)
                for ck in close:
                    for e in self._all_norm:
                        if e[2] == ck and e not in results:
                            results.append(e)
                            if len(results) >= 50:
                                break
                    if len(results) >= 50:
                        break
            except Exception:
                pass
        for name, iid, _ in results:
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

