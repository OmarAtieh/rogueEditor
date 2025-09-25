"""
Enhanced Item Manager Dialog

Properly separates trainer vs Pokemon modifiers based on comprehensive save analysis.
Uses the modifier schema system for type-safe modifier creation.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Any

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.modifier_schema import modifier_catalog, ModifierTarget
from rogueeditor.save_corruption_prevention import SafeSaveManager
from rogueeditor.utils import slot_save_path
from rogueeditor.catalog import (
    get_items_by_category, get_item_display_name, get_item_emoji, get_item_description,
    format_item_for_display, get_form_change_items_for_pokemon
)


class EnhancedItemManagerDialog(tk.Toplevel):
    """Enhanced item manager with proper trainer/Pokemon modifier separation."""

    def __init__(self, master, api: PokerogueAPI, editor: Editor, slot: int, preselect_mon_id: int | None = None):
        super().__init__(master)
        self.title(f"Enhanced Modifiers & Items Manager - Slot {slot}")
        self.geometry("1000x700")
        self.api = api
        self.editor = editor
        self.slot = slot
        self.safe_save_manager = SafeSaveManager()

        # Load slot data
        self.data = self.api.get_slot(slot)
        self.party = self.data.get("party") or []
        self.modifiers = self.data.get("modifiers") or []

        # UI state
        self.selected_pokemon_id = preselect_mon_id
        self._dirty = False

        self._build_ui()
        self._refresh_data()

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

    def _build_ui(self):
        """Build the enhanced UI with proper categorization."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create notebook for different modifier categories
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Trainer Modifiers Tab
        self._build_trainer_tab()

        # Pokemon Modifiers Tab
        self._build_pokemon_tab()

        # Current Modifiers Tab
        self._build_current_modifiers_tab()

        # Action buttons
        self._build_action_buttons(main_frame)

    def _build_trainer_tab(self):
        """Build tab for trainer-wide modifiers."""
        trainer_frame = ttk.Frame(self.notebook)
        self.notebook.add(trainer_frame, text="Trainer Modifiers")

        # Instructions
        instructions = ttk.Label(
            trainer_frame,
            text="Trainer modifiers affect your entire team or provide global benefits.",
            font=("Arial", 10, "italic")
        )
        instructions.pack(pady=5)

        # Create sections for different types of trainer modifiers
        self._build_trainer_sections(trainer_frame)

    def _build_trainer_sections(self, parent):
        """Build sections for different trainer modifier categories."""
        # Get trainer modifiers from schema
        trainer_mods = modifier_catalog.get_trainer_modifiers()

        # Group by functionality
        experience_mods = {k: v for k, v in trainer_mods.items()
                          if 'exp' in v.description.lower() or 'experience' in v.description.lower()}

        battle_mods = {k: v for k, v in trainer_mods.items()
                      if 'battle' in v.description.lower() or 'encounter' in v.description.lower()}

        access_mods = {k: v for k, v in trainer_mods.items()
                      if any(word in v.description.lower() for word in ['access', 'enable', 'evolution', 'mega', 'tera', 'giganta'])}

        utility_mods = {k: v for k, v in trainer_mods.items()
                       if k not in {**experience_mods, **battle_mods, **access_mods}}

        # Create sections
        sections = [
            ("Experience & Training", experience_mods),
            ("Battle Encounters", battle_mods),
            ("Evolution Access", access_mods),
            ("Utility & Tools", utility_mods)
        ]

        for section_name, section_mods in sections:
            if section_mods:
                self._create_trainer_section(parent, section_name, section_mods)

    def _create_trainer_section(self, parent, section_name: str, modifiers: Dict):
        """Create a section for a specific type of trainer modifiers."""
        frame = ttk.LabelFrame(parent, text=section_name)
        frame.pack(fill=tk.X, padx=5, pady=5)

        row = 0
        for type_id, schema in modifiers.items():
            # Create controls for this modifier
            mod_frame = ttk.Frame(frame)
            mod_frame.pack(fill=tk.X, padx=5, pady=2)

            # Modifier name and description
            name_label = ttk.Label(mod_frame, text=f"{type_id}:", font=("Arial", 9, "bold"))
            name_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

            desc_label = ttk.Label(mod_frame, text=schema.description, font=("Arial", 8))
            desc_label.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))

            # Stack count input
            stack_var = tk.StringVar(value="1")
            stack_label = ttk.Label(mod_frame, text="Stacks:")
            stack_label.grid(row=0, column=2, sticky=tk.W, padx=(10, 5))

            stack_entry = ttk.Entry(mod_frame, textvariable=stack_var, width=5)
            stack_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))

            # Additional arguments if needed
            arg_vars = []
            if schema.arg_structure:
                for i, arg_type in enumerate(schema.arg_structure):
                    arg_var = tk.StringVar()
                    arg_vars.append(arg_var)

                    arg_label = ttk.Label(mod_frame, text=f"{arg_type.value}:")
                    arg_label.grid(row=0, column=4 + i*2, sticky=tk.W, padx=(10, 5))

                    if arg_type.value == "percentage":
                        # Use suggested values from examples
                        example_values = ["25", "60"] if "EXP" in type_id else ["10", "20", "30"]
                        arg_entry = ttk.Combobox(mod_frame, textvariable=arg_var, values=example_values, width=8)
                    else:
                        arg_entry = ttk.Entry(mod_frame, textvariable=arg_var, width=8)

                    arg_entry.grid(row=0, column=5 + i*2, sticky=tk.W, padx=(0, 5))

            # Add button
            add_btn = ttk.Button(
                mod_frame,
                text="Add",
                command=lambda tid=type_id, sv=stack_var, avs=arg_vars: self._add_trainer_modifier(tid, sv, avs)
            )
            add_btn.grid(row=0, column=10, sticky=tk.W, padx=(10, 0))

    def _build_pokemon_tab(self):
        """Build tab for Pokemon-specific modifiers."""
        pokemon_frame = ttk.Frame(self.notebook)
        self.notebook.add(pokemon_frame, text="Pokémon Modifiers")

        # Instructions
        instructions = ttk.Label(
            pokemon_frame,
            text="Pokémon modifiers affect specific party members. Select a Pokémon first.",
            font=("Arial", 10, "italic")
        )
        instructions.pack(pady=5)

        # Pokemon selection
        self._build_pokemon_selection(pokemon_frame)

        # Pokemon modifier sections
        self._build_pokemon_sections(pokemon_frame)

    def _build_pokemon_selection(self, parent):
        """Build Pokemon selection area."""
        selection_frame = ttk.LabelFrame(parent, text="Select Target Pokémon")
        selection_frame.pack(fill=tk.X, padx=5, pady=5)

        self.pokemon_listbox = tk.Listbox(selection_frame, height=4)
        self.pokemon_listbox.pack(fill=tk.X, padx=5, pady=5)
        self.pokemon_listbox.bind("<<ListboxSelect>>", self._on_pokemon_select)

        # Populate with party members
        self._refresh_pokemon_list()

    def _refresh_pokemon_list(self):
        """Refresh the Pokemon selection list."""
        self.pokemon_listbox.delete(0, tk.END)

        for i, mon in enumerate(self.party):
            species_id = mon.get("species", "Unknown")
            nickname = mon.get("nickname", f"Pokémon {i+1}")
            level = mon.get("level", "?")
            pokemon_id = mon.get("id", "No ID")

            display_text = f"#{i+1}: {nickname} (Species: {species_id}, Level: {level}, ID: {pokemon_id})"
            self.pokemon_listbox.insert(tk.END, display_text)

    def _on_pokemon_select(self, event):
        """Handle Pokemon selection."""
        selection = self.pokemon_listbox.curselection()
        if selection:
            index = selection[0]
            if 0 <= index < len(self.party):
                self.selected_pokemon_id = self.party[index].get("id")
                self._update_pokemon_modifier_states()

    def _build_pokemon_sections(self, parent):
        """Build sections for Pokemon modifiers."""
        pokemon_mods = modifier_catalog.get_pokemon_modifiers()

        # Group by functionality
        stat_mods = {k: v for k, v in pokemon_mods.items()
                    if 'stat' in v.description.lower() or k == 'BASE_STAT_BOOSTER'}

        held_items = {k: v for k, v in pokemon_mods.items()
                     if any(word in v.description.lower() for word in ['held', 'berry', 'heal', 'damage', 'chance'])}

        special_items = {k: v for k, v in pokemon_mods.items()
                        if any(word in v.description.lower() for word in ['form', 'change', 'nature', 'accuracy', 'critical', 'experience'])}

        sections = [
            ("Stat Boosters", stat_mods),
            ("Held Items & Effects", held_items),
            ("Special Items", special_items)
        ]

        for section_name, section_mods in sections:
            if section_mods:
                self._create_pokemon_section(parent, section_name, section_mods)

    def _create_pokemon_section(self, parent, section_name: str, modifiers: Dict):
        """Create a section for Pokemon modifiers."""
        frame = ttk.LabelFrame(parent, text=section_name)
        frame.pack(fill=tk.X, padx=5, pady=5)

        for type_id, schema in modifiers.items():
            mod_frame = ttk.Frame(frame)
            mod_frame.pack(fill=tk.X, padx=5, pady=2)

            # Modifier info
            name_label = ttk.Label(mod_frame, text=f"{type_id}:", font=("Arial", 9, "bold"))
            name_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

            desc_label = ttk.Label(mod_frame, text=schema.description, font=("Arial", 8))
            desc_label.grid(row=0, column=1, sticky=tk.W, padx=(0, 10))

            # Stack count
            stack_var = tk.StringVar(value="1")
            stack_label = ttk.Label(mod_frame, text="Stacks:")
            stack_label.grid(row=0, column=2, sticky=tk.W, padx=(10, 5))

            stack_entry = ttk.Entry(mod_frame, textvariable=stack_var, width=5)
            stack_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 10))

            # Additional arguments
            arg_vars = []
            col_offset = 4

            # Skip Pokemon ID arg since it's handled automatically
            relevant_args = [arg for arg in schema.arg_structure if arg.value != "pokemon_id"]

            for i, arg_type in enumerate(relevant_args):
                arg_var = tk.StringVar()
                arg_vars.append(arg_var)

                arg_label = ttk.Label(mod_frame, text=f"{arg_type.value}:")
                arg_label.grid(row=0, column=col_offset + i*2, sticky=tk.W, padx=(10, 5))

                # Special handling for different argument types
                if arg_type.value == "stat_type":
                    arg_entry = ttk.Combobox(mod_frame, textvariable=arg_var,
                                           values=["0 (HP)", "1 (ATK)", "2 (DEF)", "3 (SPA)", "4 (SPD)", "5 (SPE)"],
                                           width=12)
                elif arg_type.value == "berry_type":
                    try:
                        from rogueeditor.catalog import load_berry_catalog
                        _, berry_i2n = load_berry_catalog()
                        berry_options = [f"{i} ({name})" for i, name in berry_i2n.items()]
                        arg_entry = ttk.Combobox(mod_frame, textvariable=arg_var, values=berry_options[:20], width=15)
                    except:
                        arg_entry = ttk.Entry(mod_frame, textvariable=arg_var, width=8)
                elif arg_type.value == "form_change_type":
                    # Based on analysis: 22 for Gyarados, 56 for Blastoise
                    arg_entry = ttk.Combobox(mod_frame, textvariable=arg_var,
                                           values=["22 (Gyarados)", "56 (Blastoise)"], width=15)
                else:
                    arg_entry = ttk.Entry(mod_frame, textvariable=arg_var, width=8)

                arg_entry.grid(row=0, column=col_offset + i*2 + 1, sticky=tk.W, padx=(0, 5))

            # Add button
            add_btn = ttk.Button(
                mod_frame,
                text="Add",
                command=lambda tid=type_id, sv=stack_var, avs=arg_vars: self._add_pokemon_modifier(tid, sv, avs),
                state=tk.DISABLED  # Enabled when Pokemon is selected
            )
            add_btn.grid(row=0, column=20, sticky=tk.W, padx=(10, 0))

            # Store button reference for state management
            if not hasattr(self, '_pokemon_buttons'):
                self._pokemon_buttons = []
            self._pokemon_buttons.append(add_btn)

    def _update_pokemon_modifier_states(self):
        """Enable/disable Pokemon modifier buttons based on selection."""
        state = tk.NORMAL if self.selected_pokemon_id else tk.DISABLED
        if hasattr(self, '_pokemon_buttons'):
            for btn in self._pokemon_buttons:
                btn.config(state=state)

    def _build_current_modifiers_tab(self):
        """Build tab showing current modifiers."""
        current_frame = ttk.Frame(self.notebook)
        self.notebook.add(current_frame, text="Current Modifiers")

        # Modifiers list
        list_frame = ttk.Frame(current_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create treeview for modifiers
        columns = ("Type", "Target", "Description", "Stack Count", "Arguments")
        self.modifiers_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

        for col in columns:
            self.modifiers_tree.heading(col, text=col)
            self.modifiers_tree.column(col, width=150)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.modifiers_tree.yview)
        self.modifiers_tree.configure(yscrollcommand=scrollbar.set)

        self.modifiers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Removal controls
        remove_frame = ttk.Frame(current_frame)
        remove_frame.pack(fill=tk.X, padx=5, pady=5)

        remove_btn = ttk.Button(remove_frame, text="Remove Selected", command=self._remove_selected_modifier)
        remove_btn.pack(side=tk.LEFT, padx=5)

        clear_btn = ttk.Button(remove_frame, text="Clear All", command=self._clear_all_modifiers)
        clear_btn.pack(side=tk.LEFT, padx=5)

    def _build_action_buttons(self, parent):
        """Build action buttons."""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, pady=10)

        save_btn = ttk.Button(btn_frame, text="Save Changes", command=self._save_changes)
        save_btn.pack(side=tk.LEFT, padx=5)

        upload_btn = ttk.Button(btn_frame, text="Save & Upload", command=self._save_and_upload)
        upload_btn.pack(side=tk.LEFT, padx=5)

        close_btn = ttk.Button(btn_frame, text="Close", command=self.destroy)
        close_btn.pack(side=tk.RIGHT, padx=5)

    def _add_trainer_modifier(self, type_id: str, stack_var: tk.StringVar, arg_vars: List[tk.StringVar]):
        """Add a trainer modifier."""
        try:
            stack_count = int(stack_var.get() or "1")
            additional_args = []

            for arg_var in arg_vars:
                value = arg_var.get().strip()
                if value:
                    # Try to parse as int first, then keep as string
                    try:
                        additional_args.append(int(value))
                    except ValueError:
                        additional_args.append(value)

            # Create modifier using schema
            modifier = modifier_catalog.create_modifier(
                type_id=type_id,
                pokemon_id=None,  # Trainer modifiers don't need Pokemon ID
                additional_args=additional_args,
                stack_count=stack_count
            )

            # Add to modifiers list
            self.modifiers.append(modifier)
            self._dirty = True
            self._refresh_current_modifiers()

            messagebox.showinfo("Success", f"Added trainer modifier: {type_id}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to add modifier: {e}")

    def _add_pokemon_modifier(self, type_id: str, stack_var: tk.StringVar, arg_vars: List[tk.StringVar]):
        """Add a Pokemon modifier."""
        if not self.selected_pokemon_id:
            messagebox.showwarning("No Selection", "Please select a Pokémon first")
            return

        try:
            stack_count = int(stack_var.get() or "1")
            additional_args = []

            for arg_var in arg_vars:
                value = arg_var.get().strip()
                if value:
                    # Handle special parsing for combo box values
                    if "(" in value and ")" in value:
                        # Extract number from "ID (Name)" format
                        try:
                            extracted = int(value.split("(")[0].strip())
                            additional_args.append(extracted)
                        except ValueError:
                            additional_args.append(value)
                    else:
                        try:
                            additional_args.append(int(value))
                        except ValueError:
                            additional_args.append(value)

            # Create modifier using schema
            modifier = modifier_catalog.create_modifier(
                type_id=type_id,
                pokemon_id=self.selected_pokemon_id,
                additional_args=additional_args,
                stack_count=stack_count
            )

            # Add to modifiers list
            self.modifiers.append(modifier)
            self._dirty = True
            self._refresh_current_modifiers()

            messagebox.showinfo("Success", f"Added Pokémon modifier: {type_id} for ID {self.selected_pokemon_id}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to add modifier: {e}")

    def _refresh_current_modifiers(self):
        """Refresh the current modifiers display."""
        # Clear existing items
        for item in self.modifiers_tree.get_children():
            self.modifiers_tree.delete(item)

        # Add current modifiers
        from rogueeditor.catalog import format_item_for_display
        for i, modifier in enumerate(self.modifiers):
            type_id = modifier.get("typeId", "Unknown")
            schema = modifier_catalog.get_modifier_schema(type_id)

            target = schema.target.value if schema else "Unknown"
            description = schema.description if schema else "Unknown modifier"
            stack_count = modifier.get("stackCount", 1)
            args = modifier.get("args", [])

            display = format_item_for_display(type_id, stacks=stack_count, args=args)

            self.modifiers_tree.insert("", "end", values=(display, target, description, stack_count, str(args) if args else "None"))

    def _remove_selected_modifier(self):
        """Remove selected modifier."""
        selection = self.modifiers_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a modifier to remove")
            return

        for item in selection:
            index = self.modifiers_tree.index(item)
            if 0 <= index < len(self.modifiers):
                del self.modifiers[index]
                self._dirty = True

        self._refresh_current_modifiers()

    def _clear_all_modifiers(self):
        """Clear all modifiers."""
        if messagebox.askyesno("Confirm", "Remove all modifiers?"):
            self.modifiers.clear()
            self._dirty = True
            self._refresh_current_modifiers()

    def _save_changes(self):
        """Save changes to local file."""
        if not self._dirty:
            messagebox.showinfo("No Changes", "No changes to save")
            return

        try:
            # Update slot data
            self.data["modifiers"] = self.modifiers

            # Save with corruption prevention
            file_path = slot_save_path(self.api.username, self.slot)
            backup_path = self.safe_save_manager.safe_dump_json(
                file_path, self.data, f"Enhanced modifier management for slot {self.slot}"
            )

            self._dirty = False
            messagebox.showinfo("Saved", f"Changes saved locally (backup: {backup_path})")

        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save: {e}")

    def _save_and_upload(self):
        """Save changes and upload to server."""
        self._save_changes()

        if messagebox.askyesno("Upload", "Upload changes to server?"):
            try:
                self.api.update_slot(self.slot, self.data)
                messagebox.showinfo("Uploaded", "Changes uploaded to server successfully")
            except Exception as e:
                messagebox.showerror("Upload Error", f"Failed to upload: {e}")

    def _refresh_data(self):
        """Refresh all data displays."""
        self._refresh_pokemon_list()
        self._refresh_current_modifiers()
        self._update_pokemon_modifier_states()


def show_enhanced_item_manager(master, api: PokerogueAPI, editor: Editor, slot: int, preselect_mon_id: int | None = None):
    """Show the enhanced item manager dialog."""
    dialog = EnhancedItemManagerDialog(master, api, editor, slot, preselect_mon_id)
    return dialog