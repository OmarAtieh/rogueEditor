from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.simpledialog
from typing import Any, Dict, List, Optional, Tuple
import random
import os
import json
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from rogueeditor.utils import load_pokemon_index, trainer_save_path, load_json, dump_json
from rogueeditor.catalog import load_ability_attr_mask, load_berry_catalog, load_move_catalog
from rogueeditor.editor import Editor
from rogueeditor.api import PokerogueAPI
from gui.common.catalog_select import CatalogSelectDialog


class StartersManagerDialog:
    """Comprehensive starters management dialog with multiple tabs."""
    
    def __init__(self, parent: tk.Tk, api: PokerogueAPI, editor: Editor):
        self.parent = parent
        self.api = api
        self.editor = editor
        self.username = api.username
        
        # Load data
        self.pokemon_index = load_pokemon_index()
        self.dex_map = self.pokemon_index.get("dex", {})
        self.name_to_id = {k.lower(): int(v) for k, v in self.dex_map.items()}
        self.id_to_name = {int(v): k for k, v in self.dex_map.items()}
        
        # Load trainer data
        self.trainer_data = self.api.get_trainer()
        self.starter_data = self.trainer_data.get("starterData", {})
        self.dex_data = self.trainer_data.get("dexData", {})
        self.voucher_counts = self.trainer_data.get("voucherCounts", {})
        self.eggs = self.trainer_data.get("eggs", [])
        
        self._create_dialog()
        self._load_data()
    
    def _create_dialog(self):
        """Create the main dialog window."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(f"Rogue Manager GUI - Starters Manager - {self.username}")
        self.dialog.geometry("900x700")
        self.dialog.resizable(True, True)
        
        # Keep focus on this dialog
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        
        # Center the dialog
        self._center_dialog()
        
        # Create main notebook
        self.notebook = ttk.Notebook(self.dialog)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create tabs
        self._create_unlocked_tab()
        self._create_unlock_tab()
        self._create_vouchers_tab()
        self._create_eggs_tab()
        
        # Bottom button frame
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.refresh_btn = ttk.Button(button_frame, text="Refresh Data", command=self._refresh_data)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)
        
        self.save_btn = ttk.Button(button_frame, text="Save Changes", command=self._save_changes)
        self.save_btn.pack(side=tk.LEFT, padx=5)
        
        self.close_btn = ttk.Button(button_frame, text="Close", command=self.dialog.destroy)
        self.close_btn.pack(side=tk.RIGHT, padx=5)
        
        # Add tooltips to clarify workflow
        self._create_tooltip(self.refresh_btn, 
            "Refresh Data: Reloads all data from the server.\n"
            "This discards any unsaved changes.")
        self._create_tooltip(self.save_btn, 
            "Save Changes: Uploads all changes to the server.\n"
            "Changes are automatically applied to memory as you edit.")
        self._create_tooltip(self.close_btn, 
            "Close: Closes the dialog.\n"
            "Make sure to 'Save Changes' first to upload your changes.")
    
    def _center_dialog(self):
        """Center the dialog relative to parent."""
        self.dialog.update_idletasks()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        
        dialog_width = 900
        dialog_height = 700
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        
        self.dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
    
    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget."""
        try:
            def on_enter(event):
                tooltip = tk.Toplevel()
                tooltip.wm_overrideredirect(True)
                tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
                label = tk.Label(tooltip, text=text, justify=tk.LEFT, 
                               background="lightyellow", relief=tk.SOLID, borderwidth=1,
                               font=("TkDefaultFont", 9))
                label.pack(ipadx=4, ipady=2)
                widget._tooltip = tooltip
            
            def on_leave(event):
                if hasattr(widget, '_tooltip'):
                    widget._tooltip.destroy()
                    del widget._tooltip
            
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
        except Exception as e:
            print(f"Error creating tooltip: {e}")
    
    def _create_unlocked_tab(self):
        """Create tab for managing already unlocked starters."""
        self.unlocked_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.unlocked_frame, text="Unlocked Starters")
        
        # Header
        header_frame = ttk.Frame(self.unlocked_frame)
        header_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(header_frame, text="Manage Unlocked Starters", 
                 font=('TkDefaultFont', 12, 'bold')).pack(side=tk.LEFT)
        
        # Search frame
        search_frame = ttk.Frame(self.unlocked_frame)
        search_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self._filter_unlocked)
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(0, 10))
        
        # Create treeview for unlocked starters
        tree_frame = ttk.Frame(self.unlocked_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview with scrollbars
        self.unlocked_tree = ttk.Treeview(tree_frame, columns=('name', 'dex_id', 'candies', 'abilities', 'passives', 'reduction'), show='headings')
        
        # Configure columns with sorting
        self.unlocked_tree.heading('name', text='Pokemon', command=lambda: self._sort_column('name'))
        self.unlocked_tree.heading('dex_id', text='Dex ID', command=lambda: self._sort_column('dex_id'))
        self.unlocked_tree.heading('candies', text='Candies', command=lambda: self._sort_column('candies'))
        self.unlocked_tree.heading('abilities', text='Abilities', command=lambda: self._sort_column('abilities'))
        self.unlocked_tree.heading('passives', text='Passives', command=lambda: self._sort_column('passives'))
        self.unlocked_tree.heading('reduction', text='Value Reduction', command=lambda: self._sort_column('reduction'))
        
        self.unlocked_tree.column('name', width=150)
        self.unlocked_tree.column('dex_id', width=80)
        self.unlocked_tree.column('candies', width=80)
        self.unlocked_tree.column('abilities', width=100)
        self.unlocked_tree.column('passives', width=100)
        self.unlocked_tree.column('reduction', width=100)
        
        # Initialize sorting state
        self.sort_column = None
        self.sort_reverse = False
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.unlocked_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.unlocked_tree.xview)
        self.unlocked_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack treeview and scrollbars
        self.unlocked_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind double-click for editing
        self.unlocked_tree.bind('<Double-1>', self._edit_starter)
        
        # Action buttons
        action_frame = ttk.Frame(self.unlocked_frame)
        action_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(action_frame, text="Edit Selected", command=self._edit_starter).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Bulk Edit Candies", command=self._bulk_edit_candies).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="Unlock All Passives", command=self._unlock_all_passives_bulk).pack(side=tk.LEFT, padx=5)
    
    def _create_unlock_tab(self):
        """Create tab for unlocking new starters."""
        self.unlock_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.unlock_frame, text="Unlock Starters")
        
        # Header
        header_frame = ttk.Frame(self.unlock_frame)
        header_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(header_frame, text="Unlock New Starters", 
                 font=('TkDefaultFont', 12, 'bold')).pack(side=tk.LEFT)
        
        # Single starter unlock
        single_frame = ttk.LabelFrame(self.unlock_frame, text="Unlock Single Starter")
        single_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Pokemon selection
        pokemon_frame = ttk.Frame(single_frame)
        pokemon_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(pokemon_frame, text="Pokemon:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.unlock_pokemon_var = tk.StringVar()
        # Populate with only locked Pokemon
        locked_names = []
        for name, dex_id in self.name_to_id.items():
            if not self._is_starter_unlocked(str(dex_id)):
                locked_names.append(name)
        locked_names.sort()
        self.unlock_pokemon_combo = ttk.Combobox(pokemon_frame, textvariable=self.unlock_pokemon_var, 
                                                values=locked_names, width=30)
        self.unlock_pokemon_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
        ttk.Button(pokemon_frame, text="Pick...", command=self._pick_pokemon_for_unlock).grid(row=0, column=2, padx=5)
        
        # Attributes & Quick Actions
        attrs_frame = ttk.Frame(single_frame)
        attrs_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Ability checkboxes
        ttk.Label(attrs_frame, text="Abilities:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.aa1_var = tk.BooleanVar()
        self.aa2_var = tk.BooleanVar()
        self.aah_var = tk.BooleanVar()
        ttk.Checkbutton(attrs_frame, text="Ability 1", variable=self.aa1_var).grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(attrs_frame, text="Ability 2", variable=self.aa2_var).grid(row=0, column=2, sticky=tk.W, padx=5)
        ttk.Checkbutton(attrs_frame, text="Hidden", variable=self.aah_var).grid(row=0, column=3, sticky=tk.W, padx=5)
        
        # Passive checkboxes
        ttk.Label(attrs_frame, text="Passives:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.p_unlocked_var = tk.BooleanVar()
        self.p_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(attrs_frame, text="Unlocked", variable=self.p_unlocked_var).grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(attrs_frame, text="Enabled", variable=self.p_enabled_var).grid(row=1, column=2, sticky=tk.W, padx=5)
        
        # Value reduction
        ttk.Label(attrs_frame, text="Value Reduction:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5))
        self.value_reduction_var = tk.StringVar(value="0")
        ttk.Entry(attrs_frame, textvariable=self.value_reduction_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=5)
        
        # IVs
        ttk.Label(attrs_frame, text="IVs:").grid(row=3, column=0, sticky=tk.W, padx=(0, 5))
        self.iv_vars = [tk.StringVar(value="0") for _ in range(6)]
        iv_labels = ["HP","Atk","Def","SpA","SpD","Spe"]
        for i, (lbl, var) in enumerate(zip(iv_labels, self.iv_vars)):
            ttk.Label(attrs_frame, text=lbl+":").grid(row=3 + (i//3)*1, column=1 + (i%3)*2, sticky=tk.W)
            ttk.Entry(attrs_frame, textvariable=var, width=5).grid(row=3 + (i//3)*1, column=2 + (i%3)*2, sticky=tk.W, padx=(0,8))

        # Progress fields (seen/caught/hatched)
        prog_frame = ttk.Frame(single_frame)
        prog_frame.pack(fill=tk.X, padx=10, pady=(0,10))
        ttk.Label(prog_frame, text="Seen:").grid(row=0, column=0, sticky=tk.W)
        self.unlock_seen_var = tk.StringVar(value="0")
        ttk.Entry(prog_frame, textvariable=self.unlock_seen_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=(0,10))
        ttk.Label(prog_frame, text="Caught:").grid(row=0, column=2, sticky=tk.W)
        self.unlock_caught_var = tk.StringVar(value="0")
        ttk.Entry(prog_frame, textvariable=self.unlock_caught_var, width=8).grid(row=0, column=3, sticky=tk.W, padx=(0,10))
        ttk.Label(prog_frame, text="Hatched:").grid(row=0, column=4, sticky=tk.W)
        self.unlock_hatched_var = tk.StringVar(value="0")
        ttk.Entry(prog_frame, textvariable=self.unlock_hatched_var, width=8).grid(row=0, column=5, sticky=tk.W, padx=(0,10))

        # Quick actions
        qa_frame = ttk.Frame(single_frame)
        qa_frame.pack(fill=tk.X, padx=10, pady=(0,10))
        self.qa_perfect_ivs = tk.BooleanVar()
        self.qa_naturalize_counts = tk.BooleanVar()
        self.qa_unlock_shiny = tk.BooleanVar()
        ttk.Checkbutton(qa_frame, text="Perfect IVs", variable=self.qa_perfect_ivs).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(qa_frame, text="Naturalize counts", variable=self.qa_naturalize_counts).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(qa_frame, text="Unlock shiny", variable=self.qa_unlock_shiny).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        button_frame = ttk.Frame(single_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Unlock Selected", command=self._unlock_single_starter).pack(side=tk.LEFT, padx=5)
        
        # Bind unlock tab fields for automatic updates
        self._bind_unlock_tab_fields()
        
        # Bulk unlock section
        bulk_frame = ttk.LabelFrame(self.unlock_frame, text="Bulk Unlock")
        bulk_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        warning_text = (
            "⚠️ WARNING: This will unlock ALL starters with perfect IVs and shiny variants.\n"
            "This action may significantly impact your player experience.\n"
            "Use with extreme caution!"
        )
        ttk.Label(bulk_frame, text=warning_text, foreground="red", 
                 font=('TkDefaultFont', 9)).pack(padx=10, pady=10)
        
        ttk.Button(bulk_frame, text="UNLOCK ALL STARTERS", 
                  command=self._unlock_all_starters).pack(pady=10)
    
    def _create_vouchers_tab(self):
        """Create tab for managing vouchers."""
        self.vouchers_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.vouchers_frame, text="Vouchers & Eggs")
        
        # Vouchers section
        vouchers_section = ttk.LabelFrame(self.vouchers_frame, text="Voucher Counts")
        vouchers_section.pack(fill=tk.X, padx=10, pady=10)
        
        # Voucher types
        voucher_types = [
            ("Common", "0", "Common egg vouchers"),
            ("Rare", "1", "Rare egg vouchers"),
            ("Epic", "2", "Epic egg vouchers"),
            ("Legendary", "3", "Legendary egg vouchers")
        ]
        
        self.voucher_vars = {}
        for i, (name, key, desc) in enumerate(voucher_types):
            row_frame = ttk.Frame(vouchers_section)
            row_frame.pack(fill=tk.X, padx=10, pady=5)
            
            ttk.Label(row_frame, text=f"{name}:", width=12).pack(side=tk.LEFT)
            var = tk.StringVar(value=str(self.voucher_counts.get(key, 0)))
            self.voucher_vars[key] = var
            ttk.Entry(row_frame, textvariable=var, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Label(row_frame, text=desc, foreground="gray").pack(side=tk.LEFT, padx=10)
        
        # Eggs section
        eggs_section = ttk.LabelFrame(self.vouchers_frame, text="Eggs")
        eggs_section.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Eggs info
        eggs_info_frame = ttk.Frame(eggs_section)
        eggs_info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.eggs_count_label = ttk.Label(eggs_info_frame, text="")
        self.eggs_count_label.pack(side=tk.LEFT)
        
        ttk.Button(eggs_info_frame, text="Hatch All Eggs", 
                  command=self._hatch_all_eggs).pack(side=tk.RIGHT, padx=5)
        
        # Eggs list
        eggs_tree_frame = ttk.Frame(eggs_section)
        eggs_tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.eggs_tree = ttk.Treeview(eggs_tree_frame, columns=('index', 'hatch_waves'), show='headings')
        self.eggs_tree.heading('index', text='Index')
        self.eggs_tree.heading('hatch_waves', text='Hatch Waves')
        self.eggs_tree.column('index', width=100)
        self.eggs_tree.column('hatch_waves', width=150)
        
        eggs_scrollbar = ttk.Scrollbar(eggs_tree_frame, orient=tk.VERTICAL, command=self.eggs_tree.yview)
        self.eggs_tree.configure(yscrollcommand=eggs_scrollbar.set)
        
        self.eggs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        eggs_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _create_eggs_tab(self):
        """Create tab for egg management (placeholder for future expansion)."""
        self.eggs_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.eggs_frame, text="Egg Management")
        
        ttk.Label(self.eggs_frame, text="Egg Management", 
                 font=('TkDefaultFont', 12, 'bold')).pack(pady=20)
        ttk.Label(self.eggs_frame, text="Advanced egg management features will be added here.").pack(pady=10)
    
    def _load_data(self):
        """Load and populate data in all tabs."""
        self._load_unlocked_starters()
        self._load_vouchers()
        self._load_eggs()
    
    def _is_starter_unlocked(self, dex_id_str):
        """Check if a starter is unlocked based on meaningful values."""
        starter_info = self.starter_data.get(dex_id_str, {})
        
        candies = starter_info.get("candyCount", 0)
        ability_attr = starter_info.get("abilityAttr", 0)
        passive_attr = starter_info.get("passiveAttr", 0)
        value_reduction = starter_info.get("valueReduction", 0)
        moveset = starter_info.get("moveset")
        
        # A starter is considered unlocked if it has meaningful values
        return (
            candies > 0 or 
            ability_attr > 0 or 
            passive_attr > 0 or 
            value_reduction > 0 or 
            (moveset is not None and len(moveset) > 0)
        )
    
    def _load_unlocked_starters(self):
        """Load unlocked starters into the treeview."""
        # Clear existing items
        for item in self.unlocked_tree.get_children():
            self.unlocked_tree.delete(item)
        
        # Add unlocked starters (only those that are actually unlocked)
        unlocked_items = []
        for dex_id_str, starter_info in self.starter_data.items():
            dex_id = int(dex_id_str)
            name = self.id_to_name.get(dex_id, f"#{dex_id}")
            
            if not self._is_starter_unlocked(dex_id_str):
                continue  # Skip locked starters
            
            candies = starter_info.get("candyCount", 0)
            ability_attr = starter_info.get("abilityAttr", 0)
            passive_attr = starter_info.get("passiveAttr", 0)
            value_reduction = starter_info.get("valueReduction", 0)
            
            # Capitalize the name for display
            display_name = name.replace('_', ' ').title()
            
            # Decode abilities
            abilities = []
            if ability_attr & 1: abilities.append("1")
            if ability_attr & 2: abilities.append("2")
            if ability_attr & 4: abilities.append("H")
            abilities_str = "/".join(abilities) if abilities else "None"
            
            # Decode passives
            passives = []
            if passive_attr & 1: passives.append("Unlocked")
            if passive_attr & 2: passives.append("Enabled")
            passives_str = "/".join(passives) if passives else "None"
            
            unlocked_items.append((dex_id, display_name, candies, abilities_str, passives_str, value_reduction))
        
        # Sort by dex number
        unlocked_items.sort(key=lambda x: x[0])
        
        # Insert into treeview
        for dex_id, display_name, candies, abilities_str, passives_str, value_reduction in unlocked_items:
            self.unlocked_tree.insert('', 'end', values=(
                display_name, dex_id, candies, abilities_str, passives_str, value_reduction
            ))
    
    def _load_vouchers(self):
        """Load voucher data."""
        for key, var in self.voucher_vars.items():
            var.set(str(self.voucher_counts.get(key, 0)))
    
    def _load_eggs(self):
        """Load eggs data."""
        # Update eggs count
        self.eggs_count_label.config(text=f"Total eggs: {len(self.eggs)}")
        
        # Clear and populate eggs tree
        for item in self.eggs_tree.get_children():
            self.eggs_tree.delete(item)
        
        for i, egg in enumerate(self.eggs):
            hatch_waves = egg.get("hatchWaves", 0)
            self.eggs_tree.insert('', 'end', values=(i, hatch_waves))
    
    def _filter_unlocked(self, *args):
        """Filter unlocked starters based on search."""
        search_term = self.search_var.get().lower()
        
        for item in self.unlocked_tree.get_children():
            values = self.unlocked_tree.item(item, 'values')
            if search_term in values[0].lower() or search_term in values[1]:
                self.unlocked_tree.reattach(item, '', 'end')
            else:
                self.unlocked_tree.detach(item)
    
    def _sort_column(self, col):
        """Sort treeview by column."""
        # Get all items
        items = list(self.unlocked_tree.get_children())
        
        # Determine if we're reversing the sort
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_reverse = False
        self.sort_column = col
        
        # Sort items based on column
        def sort_key(item):
            values = self.unlocked_tree.item(item, 'values')
            if col == 'dex_id':
                return int(values[1])  # Dex ID as integer
            elif col == 'candies':
                return int(values[2])  # Candies as integer
            elif col == 'reduction':
                return int(values[5])  # Value reduction as integer
            else:
                return values[self.unlocked_tree['columns'].index(col)].lower()  # Text columns
        
        items.sort(key=sort_key, reverse=self.sort_reverse)
        
        # Reorder items in treeview
        for item in items:
            self.unlocked_tree.move(item, '', 'end')
    
    def _pick_pokemon_for_unlock(self):
        """Pick a Pokemon for unlocking (only show locked ones)."""
        # Only show Pokemon that are NOT already unlocked
        available_pokemon = {}
        
        for name, dex_id in self.name_to_id.items():
            dex_id_str = str(dex_id)
            
            # Only show Pokemon that are NOT already unlocked
            if not self._is_starter_unlocked(dex_id_str):
                display_name = f"#{dex_id:03d} {name.replace('_', ' ').title()}"
                available_pokemon[display_name] = dex_id
        
        if not available_pokemon:
            messagebox.showinfo("All Unlocked", "All Pokemon are already unlocked!")
            return
            
        selected = CatalogSelectDialog.select(self.dialog, available_pokemon, 'Select Pokemon to Unlock')
        if selected:
            name = self.id_to_name.get(selected, f"#{selected}")
            self.unlock_pokemon_var.set(name)
    
    def _edit_starter(self, event=None):
        """Edit the selected starter."""
        selection = self.unlocked_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a starter to edit.")
            return
        
        item = selection[0]
        values = self.unlocked_tree.item(item, 'values')
        dex_id = int(values[1])
        
        # Create edit dialog
        self._create_edit_starter_dialog(dex_id, values)
    
    def _create_edit_starter_dialog(self, dex_id: int, current_values):
        """Create dialog to edit a starter."""
        edit_dialog = tk.Toplevel(self.dialog)
        edit_dialog.title(f"Rogue Manager GUI - Edit Starter - {current_values[0]}")
        edit_dialog.geometry("500x600")
        edit_dialog.transient(self.dialog)
        edit_dialog.grab_set()
        
        # Center the dialog
        edit_dialog.update_idletasks()
        x = self.dialog.winfo_x() + (self.dialog.winfo_width() // 2) - 250
        y = self.dialog.winfo_y() + (self.dialog.winfo_height() // 2) - 300
        edit_dialog.geometry(f"500x600+{x}+{y}")
        
        # Create scrollable frame
        canvas = tk.Canvas(edit_dialog)
        scrollbar = ttk.Scrollbar(edit_dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Form fields
        form_frame = ttk.Frame(scrollable_frame)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        row = 0
        
        # Basic Info
        ttk.Label(form_frame, text="Basic Information", font=('TkDefaultFont', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        row += 1
        
        # Candies
        ttk.Label(form_frame, text="Candies:").grid(row=row, column=0, sticky=tk.W, pady=5)
        candies_var = tk.StringVar(value=str(current_values[2]))
        ttk.Entry(form_frame, textvariable=candies_var, width=15).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1
        
        # Value Reduction
        ttk.Label(form_frame, text="Value Reduction:").grid(row=row, column=0, sticky=tk.W, pady=5)
        reduction_var = tk.StringVar(value=str(current_values[5]))
        ttk.Entry(form_frame, textvariable=reduction_var, width=15).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1
        
        # Abilities
        ttk.Label(form_frame, text="Abilities:", font=('TkDefaultFont', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        row += 1
        
        ability_frame = ttk.Frame(form_frame)
        ability_frame.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        aa1_var = tk.BooleanVar()
        aa2_var = tk.BooleanVar()
        aah_var = tk.BooleanVar()
        
        # Parse current abilities
        current_abilities = current_values[3]
        if "1" in current_abilities: aa1_var.set(True)
        if "2" in current_abilities: aa2_var.set(True)
        if "H" in current_abilities: aah_var.set(True)
        
        ttk.Checkbutton(ability_frame, text="Ability 1", variable=aa1_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(ability_frame, text="Ability 2", variable=aa2_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(ability_frame, text="Hidden", variable=aah_var).pack(side=tk.LEFT, padx=5)
        row += 1
        
        # Passives
        ttk.Label(form_frame, text="Passives:", font=('TkDefaultFont', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        row += 1
        
        passive_frame = ttk.Frame(form_frame)
        passive_frame.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        p_unlocked_var = tk.BooleanVar()
        p_enabled_var = tk.BooleanVar()
        
        # Parse current passives
        current_passives = current_values[4]
        if "Unlocked" in current_passives: p_unlocked_var.set(True)
        if "Enabled" in current_passives: p_enabled_var.set(True)
        
        ttk.Checkbutton(passive_frame, text="Unlocked", variable=p_unlocked_var).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(passive_frame, text="Enabled", variable=p_enabled_var).pack(side=tk.LEFT, padx=5)
        row += 1
        
        # Progress & Advanced Attributes
        ttk.Label(form_frame, text="Progress & Advanced Attributes", font=('TkDefaultFont', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(20, 10))
        row += 1
        
        # Friendship
        ttk.Label(form_frame, text="Friendship:").grid(row=row, column=0, sticky=tk.W, pady=5)
        current_friendship = (self.starter_data.get(str(dex_id), {}) or {}).get("friendship", 0)
        friendship_var = tk.StringVar(value=str(current_friendship))
        ttk.Entry(form_frame, textvariable=friendship_var, width=15).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1

        # Classic Wins
        ttk.Label(form_frame, text="Classic Wins:").grid(row=row, column=0, sticky=tk.W, pady=5)
        current_wins = (self.starter_data.get(str(dex_id), {}) or {}).get("classicWinCount", 0)
        classic_wins_var = tk.StringVar(value=str(current_wins))
        ttk.Entry(form_frame, textvariable=classic_wins_var, width=15).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1

        # Egg Moves
        ttk.Label(form_frame, text="Egg Moves:").grid(row=row, column=0, sticky=tk.W, pady=5)
        egg_moves_var = tk.StringVar(value="15")  # Default value
        ttk.Entry(form_frame, textvariable=egg_moves_var, width=15).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1
        
        # IVs
        ttk.Label(form_frame, text="IVs (0-31):", font=('TkDefaultFont', 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        row += 1
        iv_frame = ttk.Frame(form_frame)
        iv_frame.grid(row=row, column=0, columnspan=2, sticky=tk.W)
        iv_labels = ["HP","Atk","Def","SpA","SpD","Spe"]
        current_iv_list = (self.dex_data.get(str(dex_id), {}) or {}).get("ivs", [0,0,0,0,0,0])
        iv_vars = []
        for i, lbl in enumerate(iv_labels):
            ttk.Label(iv_frame, text=lbl+":").grid(row=0, column=i*2, sticky=tk.W)
            var = tk.StringVar(value=str(current_iv_list[i] if i < len(current_iv_list) else 0))
            ttk.Entry(iv_frame, textvariable=var, width=5).grid(row=0, column=i*2+1, sticky=tk.W, padx=(0,8))
            iv_vars.append(var)
        row += 1
        
        # Shiny Status (placeholder for future implementation)
        ttk.Label(form_frame, text="Shiny Status:").grid(row=row, column=0, sticky=tk.W, pady=5)
        shiny_var = tk.BooleanVar()
        ttk.Checkbutton(form_frame, text="Shiny", variable=shiny_var).grid(row=row, column=1, sticky=tk.W, pady=5)
        row += 1
        
        # Buttons
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, padx=20, pady=10)
        
        def save_changes():
            try:
                # Update starter data
                starter_data = self.starter_data.get(str(dex_id), {})
                starter_data["candyCount"] = int(candies_var.get())
                starter_data["valueReduction"] = int(reduction_var.get())
                starter_data["eggMoves"] = int(egg_moves_var.get())
                # Friendship & wins
                try:
                    starter_data["friendship"] = int(friendship_var.get())
                except ValueError:
                    starter_data["friendship"] = 0
                try:
                    starter_data["classicWinCount"] = int(classic_wins_var.get())
                except ValueError:
                    starter_data["classicWinCount"] = 0
                
                # Calculate ability attr
                ability_attr = 0
                if aa1_var.get(): ability_attr += 1
                if aa2_var.get(): ability_attr += 2
                if aah_var.get(): ability_attr += 4
                starter_data["abilityAttr"] = ability_attr
                
                # Calculate passive attr
                passive_attr = 0
                if p_unlocked_var.get(): passive_attr += 1
                if p_enabled_var.get(): passive_attr += 2
                starter_data["passiveAttr"] = passive_attr
                
                # IVs for this dex in dexData
                iv_values = []
                for var in iv_vars:
                    try:
                        val = int(var.get())
                    except ValueError:
                        val = 0
                    val = max(0, min(31, val))
                    iv_values.append(val)
                dex_entry = self.dex_data.get(str(dex_id), {}) or {}
                dex_entry["ivs"] = iv_values
                self.dex_data[str(dex_id)] = dex_entry
                
                self.starter_data[str(dex_id)] = starter_data
                # Suggest naturalized dex progression based on candies (optional quick action later)
                # Ensure seen >= caught
                dex_entry = self.dex_data.get(str(dex_id), {}) or {}
                caught_count = max(0, int(dex_entry.get("caughtCount", 0)))
                seen_count = max(caught_count, int(dex_entry.get("seenCount", caught_count)))
                hatched_count = max(0, int(dex_entry.get("hatchedCount", 0)))
                dex_entry.update({
                    "seenCount": seen_count,
                    "caughtCount": caught_count,
                    "hatchedCount": hatched_count,
                })
                self.dex_data[str(dex_id)] = dex_entry
                self._load_unlocked_starters()
                edit_dialog.destroy()
                messagebox.showinfo("Success", "Starter updated successfully!")
                
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid input: {e}")
        
        # Bind all fields for automatic updates
        self._bind_edit_dialog_fields(edit_dialog, dex_id, candies_var, reduction_var, 
                                    egg_moves_var, friendship_var, classic_wins_var,
                                    aa1_var, aa2_var, aah_var, p_unlocked_var, p_enabled_var,
                                    iv_vars, shiny_var)
        
        # Note: Changes are automatically applied to memory as you edit
        # Use "Save Changes" in main dialog to upload to server
        ttk.Button(button_frame, text="Close", command=edit_dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def _bind_edit_dialog_fields(self, edit_dialog, dex_id, candies_var, reduction_var, 
                                egg_moves_var, friendship_var, classic_wins_var,
                                aa1_var, aa2_var, aah_var, p_unlocked_var, p_enabled_var,
                                iv_vars, shiny_var):
        """Bind all fields in edit dialog to automatically apply changes."""
        try:
            # Bind all field changes to automatically update data
            def apply_changes():
                try:
                    # Update starter data
                    starter_data = self.starter_data.get(str(dex_id), {})
                    starter_data["candyCount"] = int(candies_var.get())
                    starter_data["valueReduction"] = int(reduction_var.get())
                    starter_data["eggMoves"] = int(egg_moves_var.get())
                    
                    # Friendship & wins
                    try:
                        starter_data["friendship"] = int(friendship_var.get())
                    except ValueError:
                        starter_data["friendship"] = 0
                    try:
                        starter_data["classicWinCount"] = int(classic_wins_var.get())
                    except ValueError:
                        starter_data["classicWinCount"] = 0
                    
                    # Calculate ability attr
                    ability_attr = 0
                    if aa1_var.get(): ability_attr += 1
                    if aa2_var.get(): ability_attr += 2
                    if aah_var.get(): ability_attr += 4
                    starter_data["abilityAttr"] = ability_attr
                    
                    # Calculate passive attr
                    passive_attr = 0
                    if p_unlocked_var.get(): passive_attr += 1
                    if p_enabled_var.get(): passive_attr += 2
                    starter_data["passiveAttr"] = passive_attr
                    
                    # IVs for this dex in dexData
                    iv_values = []
                    for var in iv_vars:
                        try:
                            val = int(var.get())
                        except ValueError:
                            val = 0
                        val = max(0, min(31, val))
                        iv_values.append(val)
                    dex_entry = self.dex_data.get(str(dex_id), {}) or {}
                    dex_entry["ivs"] = iv_values
                    self.dex_data[str(dex_id)] = dex_entry
                    
                    self.starter_data[str(dex_id)] = starter_data
                    
                    # Update dex progression
                    dex_entry = self.dex_data.get(str(dex_id), {}) or {}
                    caught_count = max(0, int(dex_entry.get("caughtCount", 0)))
                    seen_count = max(caught_count, int(dex_entry.get("seenCount", caught_count)))
                    hatched_count = max(0, int(dex_entry.get("hatchedCount", 0)))
                    dex_entry.update({
                        "seenCount": seen_count,
                        "caughtCount": caught_count,
                        "hatchedCount": hatched_count,
                    })
                    self.dex_data[str(dex_id)] = dex_entry
                    
                    # Refresh the main dialog display
                    self._load_unlocked_starters()
                    
                except Exception as e:
                    print(f"Error applying starter changes: {e}")
            
            # Bind all variables to apply changes automatically
            candies_var.trace_add("write", lambda *args: apply_changes())
            reduction_var.trace_add("write", lambda *args: apply_changes())
            egg_moves_var.trace_add("write", lambda *args: apply_changes())
            friendship_var.trace_add("write", lambda *args: apply_changes())
            classic_wins_var.trace_add("write", lambda *args: apply_changes())
            
            aa1_var.trace_add("write", lambda *args: apply_changes())
            aa2_var.trace_add("write", lambda *args: apply_changes())
            aah_var.trace_add("write", lambda *args: apply_changes())
            p_unlocked_var.trace_add("write", lambda *args: apply_changes())
            p_enabled_var.trace_add("write", lambda *args: apply_changes())
            
            for var in iv_vars:
                var.trace_add("write", lambda *args: apply_changes())
            
            shiny_var.trace_add("write", lambda *args: apply_changes())
            
        except Exception as e:
            print(f"Error binding edit dialog fields: {e}")
    
    def _bind_unlock_tab_fields(self):
        """Bind unlock tab fields to automatically apply changes."""
        try:
            # Bind IV fields for automatic updates
            for var in self.iv_vars:
                var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            
            # Bind other fields
            self.value_reduction_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.unlock_seen_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.unlock_caught_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.unlock_hatched_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            
            # Bind checkboxes
            self.aa1_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.aa2_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.aah_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.p_unlocked_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            self.p_enabled_var.trace_add("write", lambda *args: self._apply_unlock_tab_changes())
            
        except Exception as e:
            print(f"Error binding unlock tab fields: {e}")
    
    def _apply_unlock_tab_changes(self):
        """Apply changes from unlock tab fields to temporary data."""
        try:
            # This method can be used to apply changes to a temporary data structure
            # that gets used when "Unlock Selected" is clicked
            # For now, we'll just ensure the fields are validated
            pass
        except Exception as e:
            print(f"Error applying unlock tab changes: {e}")
    
    def _bulk_edit_candies(self):
        """Bulk edit candies for selected starters."""
        selection = self.unlocked_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select starters to edit.")
            return
        
        # Get candy delta
        delta = tk.simpledialog.askinteger("Bulk Edit Candies", 
                                         "Enter candy delta (can be negative):", 
                                         initialvalue=0)
        if delta is None:
            return
        
        # Apply to selected starters
        for item in selection:
            values = self.unlocked_tree.item(item, 'values')
            dex_id = str(values[1])
            current_candies = int(values[2])
            new_candies = max(0, current_candies + delta)
            
            if dex_id in self.starter_data:
                self.starter_data[dex_id]["candyCount"] = new_candies
        
        self._load_unlocked_starters()
        messagebox.showinfo("Success", f"Updated candies for {len(selection)} starters.")
    
    def _unlock_all_passives_bulk(self):
        """Unlock all passives for selected starters."""
        selection = self.unlocked_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select starters to edit.")
            return
        
        if not messagebox.askyesno("Confirm", f"Unlock all passives for {len(selection)} starters?"):
            return
        
        # Apply to selected starters
        for item in selection:
            values = self.unlocked_tree.item(item, 'values')
            dex_id = str(values[1])
            
            if dex_id in self.starter_data:
                self.starter_data[dex_id]["passiveAttr"] = 7  # All passives unlocked
        
        self._load_unlocked_starters()
        messagebox.showinfo("Success", f"Unlocked all passives for {len(selection)} starters.")
    
    def _unlock_single_starter(self):
        """Unlock a single starter."""
        pokemon_name = self.unlock_pokemon_var.get().strip()
        if not pokemon_name:
            messagebox.showwarning("Missing", "Please select a Pokemon.")
            return
        
        # Get dex ID
        if pokemon_name.isdigit():
            dex_id = int(pokemon_name)
        else:
            dex_id = self.name_to_id.get(pokemon_name.lower())
            if dex_id is None:
                messagebox.showerror("Error", f"Pokemon '{pokemon_name}' not found.")
                return
        
        # Calculate attributes
        ability_attr = 0
        if self.aa1_var.get(): ability_attr += 1
        if self.aa2_var.get(): ability_attr += 2
        if self.aah_var.get(): ability_attr += 4
        
        passive_attr = 0
        if self.p_unlocked_var.get(): passive_attr += 1
        if self.p_enabled_var.get(): passive_attr += 2
        
        try:
            value_reduction = int(self.value_reduction_var.get())
        except ValueError:
            value_reduction = 0
        
        # Create starter data
        starter_data = {
            "moveset": None,
            "eggMoves": 15,
            "candyCount": 0,
            "abilityAttr": ability_attr,
            "passiveAttr": passive_attr,
            "valueReduction": value_reduction
        }
        
        self.starter_data[str(dex_id)] = starter_data

        # Compose dex entry updates (IVs + counts + shiny if requested)
        iv_values = []
        for var in self.iv_vars:
            try:
                val = int(var.get())
            except ValueError:
                val = 0
            if self.qa_perfect_ivs.get():
                val = 31
            val = max(0, min(31, val))
            iv_values.append(val)

        try:
            seen = int(self.unlock_seen_var.get() or '0')
        except ValueError:
            seen = 0
        try:
            caught = int(self.unlock_caught_var.get() or '0')
        except ValueError:
            caught = 0
        try:
            hatched = int(self.unlock_hatched_var.get() or '0')
        except ValueError:
            hatched = 0

        # Naturalize counts (optional): tie to candies
        if self.qa_naturalize_counts.get():
            # Heuristic: caught += 1-2 per 10 candies; seen >= caught with jitter
            candy = starter_data.get('candyCount', 0)
            caught = max(caught, candy // 10 + random.randint(0, 2))
            seen = max(seen, caught + random.randint(0, 3))
            hatched = max(hatched, max(0, candy // 50))

        # Ensure seen >= caught
        seen = max(seen, caught)

        dex_entry = self.dex_data.get(str(dex_id), {}) or {}
        dex_entry['ivs'] = iv_values
        dex_entry['seenCount'] = max(0, seen)
        dex_entry['caughtCount'] = max(0, caught)
        dex_entry['hatchedCount'] = max(0, hatched)

        # Shiny unlock (basic): set caughtAttr shiny bit if requested
        if self.qa_unlock_shiny.get():
            shiny_attr = max(dex_entry.get('caughtAttr', 0), 255)
            dex_entry['caughtAttr'] = shiny_attr

        self.dex_data[str(dex_id)] = dex_entry

        self._load_unlocked_starters()
        messagebox.showinfo("Success", f"Unlocked {pokemon_name} (#{dex_id})")
    
    def _unlock_all_starters(self):
        """Unlock all starters with confirmation."""
        if not messagebox.askyesno("WARNING", 
                                  "This will unlock ALL starters with perfect IVs and shiny variants.\n"
                                  "This may significantly impact your player experience.\n\n"
                                  "Are you sure you want to proceed?"):
            return
        
        # Additional confirmation
        confirm_text = tk.simpledialog.askstring("Final Confirmation", 
                                               "Type 'UNLOCK ALL STARTERS' to confirm:")
        if confirm_text != "UNLOCK ALL STARTERS":
            messagebox.showinfo("Cancelled", "Operation cancelled.")
            return
        
        try:
            self.editor.unlock_all_starters()
            self._refresh_data()
            messagebox.showinfo("Success", "All starters unlocked successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to unlock all starters: {e}")
    
    def _hatch_all_eggs(self):
        """Hatch all eggs."""
        if not self.eggs:
            messagebox.showinfo("No Eggs", "No eggs to hatch.")
            return
        
        if not messagebox.askyesno("Confirm", f"Hatch all {len(self.eggs)} eggs?"):
            return
        
        try:
            self.editor.hatch_all_eggs()
            self._refresh_data()
            messagebox.showinfo("Success", "All eggs will hatch after the next battle!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to hatch eggs: {e}")
    
    def _refresh_data(self):
        """Refresh all data from the server."""
        try:
            self.trainer_data = self.api.get_trainer()
            self.starter_data = self.trainer_data.get("starterData", {})
            self.dex_data = self.trainer_data.get("dexData", {})
            self.voucher_counts = self.trainer_data.get("voucherCounts", {})
            self.eggs = self.trainer_data.get("eggs", [])
            
            self._load_data()
            messagebox.showinfo("Success", "Data refreshed from server.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh data: {e}")
    
    def _save_changes(self):
        """Save changes to the server."""
        try:
            # Update trainer data
            self.trainer_data["starterData"] = self.starter_data
            self.trainer_data["voucherCounts"] = {k: int(v.get()) for k, v in self.voucher_vars.items()}
            
            # Save locally first
            trainer_path = trainer_save_path(self.username)
            dump_json(trainer_path, self.trainer_data)
            
            # Upload to server
            self.api.update_trainer(self.trainer_data)
            
            messagebox.showinfo("Success", "Changes saved and uploaded to server.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save changes: {e}")
