from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def build(parent: tk.Widget, app) -> dict:
    """Build the Slots section UI into `parent`.

    Returns a handle dict with keys:
    - frame: the top-level frame for this section
    - slot_tree: the Treeview widget listing slots
    """
    boxS = ttk.LabelFrame(parent, text="Slots")
    boxS.pack(fill=tk.BOTH, padx=6, pady=6)
    # Toolbar on top
    tb = ttk.Frame(boxS)
    tb.pack(fill=tk.X, padx=4, pady=(4, 0))
    ttk.Button(tb, text="Refresh", command=app._refresh_slots).pack(side=tk.LEFT)
    ttk.Label(
        tb,
        text="Shows only available save slots. Select a slot to set the target for actions below.\n(Scroll down for more actions)",
        foreground="green",
    ).pack(side=tk.LEFT, padx=8)

    cols = ("slot", "party", "playtime", "wave", "local")
    slot_tree = ttk.Treeview(boxS, columns=cols, show="headings", height=6)
    for c, w in (("slot", 40), ("party", 60), ("playtime", 100), ("wave", 60), ("local", 180)):
        slot_tree.heading(c, text=c.capitalize())
        slot_tree.column(c, width=w, anchor=tk.W)
    slot_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
    sb = ttk.Scrollbar(boxS, orient="vertical", command=slot_tree.yview)
    slot_tree.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    slot_tree.tag_configure('empty', foreground='grey')
    # Configure selected item highlighting
    slot_tree.tag_configure('selected', background='#0078d4', foreground='white')
    slot_tree.bind('<<TreeviewSelect>>', app._on_slot_select)
    # Refresh button moved to toolbar

    return {"frame": boxS, "slot_tree": slot_tree}
