import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog, simpledialog
import os
import json
import traceback
from typing import TYPE_CHECKING, Optional, Any

# Project Modules (for type hints)
from wow_object import WowObject # Needed for spell info power types

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp # Import from the main gui module


class RotationEditorTab:
    """Handles the UI and logic for the Rotation Editor Tab."""

    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp'):
        """
        Initializes the Rotation Editor Tab.

        Args:
            parent_notebook: The ttk.Notebook widget to attach the tab frame to.
            app_instance: The instance of the main WowMonitorApp.
        """
        self.app = app_instance
        self.notebook = parent_notebook

        # Create the main frame for this tab
        self.tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_frame, text='Rotation Editor')

        # --- Define Editor specific widgets ---
        # Use StringVars from the app instance for shared state
        self.action_var = self.app.action_var
        self.spell_id_var = self.app.spell_id_var
        self.target_var = self.app.target_var
        self.condition_var = self.app.condition_var
        self.condition_value_x_var = self.app.condition_value_x_var
        self.condition_value_y_var = self.app.condition_value_y_var
        self.condition_text_var = self.app.condition_text_var
        self.int_cd_var = self.app.int_cd_var
        self.lua_code_var = self.app.lua_code_var
        self.macro_text_var = self.app.macro_text_var

        # Widgets for rule definition (left pane)
        self.action_dropdown: Optional[ttk.Combobox] = None
        self.detail_frame: Optional[ttk.Frame] = None # Container for spell/lua/macro
        self.spell_id_label: Optional[ttk.Label] = None
        self.spell_id_entry: Optional[ttk.Entry] = None
        self.lua_code_label: Optional[ttk.Label] = None
        self.lua_code_text: Optional[scrolledtext.ScrolledText] = None
        self.macro_text_label: Optional[ttk.Label] = None
        self.macro_text_entry: Optional[ttk.Entry] = None
        self.target_dropdown: Optional[ttk.Combobox] = None
        self.condition_dropdown: Optional[ttk.Combobox] = None
        self.condition_value_label: Optional[ttk.Label] = None
        self.condition_value_x_entry: Optional[ttk.Entry] = None
        self.condition_value_y_label: Optional[ttk.Label] = None
        self.condition_value_y_entry: Optional[ttk.Entry] = None
        self.condition_text_label: Optional[ttk.Label] = None
        self.condition_text_entry: Optional[ttk.Entry] = None
        self.int_cd_entry: Optional[ttk.Entry] = None
        self.add_update_button: Optional[ttk.Button] = None

        # Widgets for spell info (left pane)
        self.list_spells_button: Optional[ttk.Button] = None
        self.lookup_spell_button: Optional[ttk.Button] = None

        # Widgets for rule list (right pane)
        self.rule_listbox: Optional[tk.Listbox] = None
        self.move_up_button: Optional[ttk.Button] = None
        self.move_down_button: Optional[ttk.Button] = None
        self.remove_rule_button: Optional[ttk.Button] = None
        self.clear_button: Optional[ttk.Button] = None
        self.save_rules_button: Optional[ttk.Button] = None
        self.load_rules_button: Optional[ttk.Button] = None

        # --- Build the UI for this tab ---
        self._setup_ui()

        # --- Initial UI State Update ---
        self._update_detail_inputs() # Call initial updates after UI setup
        self._update_condition_inputs()

    def _setup_ui(self):
        """Creates the widgets for the Rotation Editor tab."""
        main_frame = ttk.Frame(self.tab_frame, padding=10)
        main_frame.pack(expand=True, fill=tk.BOTH)
        main_frame.columnconfigure(0, weight=1)  # Left pane column
        main_frame.columnconfigure(1, weight=2)  # Right pane column
        main_frame.rowconfigure(0, weight=1)     # Allow panes to expand vertically

        # --- Left Pane ---
        left_pane = ttk.Frame(main_frame)
        left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left_pane.rowconfigure(0, weight=0) # Define frame doesn't need to expand much
        left_pane.rowconfigure(1, weight=0) # Spell info frame doesn't need to expand much
        left_pane.columnconfigure(0, weight=1)

        # --- Define Rule Section ---
        define_frame = ttk.LabelFrame(left_pane, text="Define Rule", padding="10")
        define_frame.grid(row=0, column=0, sticky="new", pady=(0, 10))
        define_frame.columnconfigure(1, weight=1) # Allow inputs to expand horizontally

        # Row 0: Action (Use self.action_var from app)
        ttk.Label(define_frame, text="Action:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.action_dropdown = ttk.Combobox(define_frame, textvariable=self.action_var, values=self.app.rule_actions, state="readonly")
        self.action_dropdown.grid(row=0, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.action_dropdown.set("Spell") # Default value
        # Bind to self._update_detail_inputs in this class
        self.action_dropdown.bind("<<ComboboxSelected>>", self._update_detail_inputs)

        # Row 1: Detail Frame (Container for Spell/Lua/Macro inputs)
        self.detail_frame = ttk.Frame(define_frame)
        self.detail_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=5, pady=3)
        self.detail_frame.columnconfigure(1, weight=1) # Allow detail input to expand

        # Detail Widgets (placed inside detail_frame by _update_detail_inputs)
        self.spell_id_label = ttk.Label(self.detail_frame, text="Spell ID:")
        # Use self.spell_id_var from app
        self.spell_id_entry = ttk.Entry(self.detail_frame, textvariable=self.spell_id_var)
        self.lua_code_label = ttk.Label(self.detail_frame, text="Lua Code:")
        # Use self.app.CODE_FONT
        self.lua_code_text = scrolledtext.ScrolledText(self.detail_frame, wrap=tk.WORD, height=4, width=30, font=self.app.CODE_FONT)
        # Bind to self._on_lua_change in this class (syncs widget to self.lua_code_var)
        self.lua_code_text.bind("<KeyRelease>", self._on_lua_change)
        self.macro_text_label = ttk.Label(self.detail_frame, text="Macro Text:")
        # Use self.macro_text_var from app
        self.macro_text_entry = ttk.Entry(self.detail_frame, textvariable=self.macro_text_var)

        # Row 2: Target (Use self.target_var from app)
        ttk.Label(define_frame, text="Target:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        self.target_dropdown = ttk.Combobox(define_frame, textvariable=self.target_var, values=self.app.rule_targets, state="readonly")
        self.target_dropdown.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.target_dropdown.set("target") # Default

        # Row 3: Condition (Use self.condition_var from app)
        ttk.Label(define_frame, text="Condition:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=3)
        # Use self.app.rule_conditions
        self.condition_dropdown = ttk.Combobox(define_frame, textvariable=self.condition_var, values=self.app.rule_conditions, state="readonly", width=28)
        self.condition_dropdown.grid(row=3, column=1, columnspan=3, sticky="ew", padx=5, pady=3)
        self.condition_dropdown.set("None") # Default
        # Bind to self._update_condition_inputs in this class
        self.condition_dropdown.bind("<<ComboboxSelected>>", self._update_condition_inputs)

        # Row 4: Dynamic Condition Inputs (Labels & Entries managed by _update_condition_inputs)
        self.condition_value_label = ttk.Label(define_frame, text="Value (X):") # Default text
        # Use self.condition_value_x_var from app
        self.condition_value_x_entry = ttk.Entry(define_frame, textvariable=self.condition_value_x_var, state=tk.DISABLED, width=10)
        self.condition_value_y_label = ttk.Label(define_frame, text="Value (Y):") # Default text
        # Use self.condition_value_y_var from app
        self.condition_value_y_entry = ttk.Entry(define_frame, textvariable=self.condition_value_y_var, state=tk.DISABLED, width=10)
        self.condition_text_label = ttk.Label(define_frame, text="Name/ID:") # Default text
        # Use self.condition_text_var from app
        self.condition_text_entry = ttk.Entry(define_frame, textvariable=self.condition_text_var, state=tk.DISABLED)

        # Row 5: Internal Cooldown (Use self.int_cd_var from app)
        ttk.Label(define_frame, text="Int. CD (s):").grid(row=5, column=0, sticky=tk.W, padx=5, pady=3)
        self.int_cd_entry = ttk.Entry(define_frame, textvariable=self.int_cd_var, width=10)
        self.int_cd_entry.grid(row=5, column=1, sticky="ew", padx=5, pady=3)

        # Row 6: Add/Update Button (Bind to self.add_rotation_rule in this class)
        self.add_update_button = ttk.Button(define_frame, text="Add Rule", command=self.add_rotation_rule)
        self.add_update_button.grid(row=6, column=0, columnspan=4, pady=10)

        # --- Spell Info Section ---
        spell_info_frame = ttk.LabelFrame(left_pane, text="Spell Info", padding="10")
        spell_info_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        spell_info_frame.columnconfigure(0, weight=1)
        spell_info_frame.columnconfigure(1, weight=1)

        # Bind to self.scan_spellbook in this class
        self.list_spells_button = ttk.Button(spell_info_frame, text="List Known Spells...", command=self.scan_spellbook)
        self.list_spells_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        # Bind to self.lookup_spell_info in this class
        self.lookup_spell_button = ttk.Button(spell_info_frame, text="Lookup Spell ID...", command=self.lookup_spell_info)
        self.lookup_spell_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # --- Right Pane ---
        right_pane = ttk.Frame(main_frame)
        right_pane.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right_pane.rowconfigure(0, weight=1)  # Allow listbox frame to expand
        right_pane.columnconfigure(0, weight=1) # Allow listbox frame to expand

        rule_list_frame = ttk.LabelFrame(right_pane, text="Rotation Rule Priority", padding="5")
        rule_list_frame.grid(row=0, column=0, sticky="nsew")
        rule_list_frame.rowconfigure(0, weight=1)
        rule_list_frame.columnconfigure(0, weight=1)

        # Apply style from self.app.rule_listbox_style
        self.rule_listbox = tk.Listbox(rule_list_frame, height=15, selectmode=tk.SINGLE, **self.app.rule_listbox_style)
        self.rule_listbox.grid(row=0, column=0, sticky="nsew")
        # Bind to self.on_rule_select in this class
        self.rule_listbox.bind('<<ListboxSelect>>', self.on_rule_select)

        scrollbar = ttk.Scrollbar(rule_list_frame, orient=tk.VERTICAL, command=self.rule_listbox.yview)
        self.rule_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # --- Listbox Button Frame ---
        rule_button_frame = ttk.Frame(right_pane)
        rule_button_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        # Bind buttons to methods in this class
        self.move_up_button = ttk.Button(rule_button_frame, text="Move Up", command=self.move_rule_up)
        self.move_up_button.pack(side=tk.LEFT, padx=(0,5))
        self.move_down_button = ttk.Button(rule_button_frame, text="Move Down", command=self.move_rule_down)
        self.move_down_button.pack(side=tk.LEFT, padx=5)
        self.remove_rule_button = ttk.Button(rule_button_frame, text="Remove Selected", command=self.remove_selected_rule)
        self.remove_rule_button.pack(side=tk.LEFT, padx=5)
        ttk.Frame(rule_button_frame, width=20).pack(side=tk.LEFT) # Spacer
        self.clear_button = ttk.Button(rule_button_frame, text="Clear Input", command=self.clear_rule_input_fields)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        # --- File Button Frame ---
        file_button_frame = ttk.Frame(right_pane)
        file_button_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        # Bind buttons to methods in this class
        self.save_rules_button = ttk.Button(file_button_frame, text="Save Rules...", command=self.save_rules_to_file)
        self.save_rules_button.pack(side=tk.LEFT, padx=(0,5))
        self.load_rules_button = ttk.Button(file_button_frame, text="Load Rules...", command=self.load_rules_from_file)
        self.load_rules_button.pack(side=tk.LEFT, padx=5)

    def _update_detail_inputs(self, event=None):
        """Shows/hides the correct detail input widget based on Action."""
        # Check widgets exist
        if not all([self.spell_id_label, self.spell_id_entry, self.lua_code_label,
                    self.lua_code_text, self.macro_text_label, self.macro_text_entry,
                    self.detail_frame]):
            self.app.log_message("Detail input widgets not initialized.", "ERROR")
            return

        action_type = self.action_var.get()

        # Forget all detail widgets first
        self.spell_id_label.grid_forget()
        self.spell_id_entry.grid_forget()
        self.lua_code_label.grid_forget()
        self.lua_code_text.grid_forget()
        self.macro_text_label.grid_forget()
        self.macro_text_entry.grid_forget()
        # Reset row/column configure in case Lua expanded it
        self.detail_frame.rowconfigure(0, weight=0)
        self.detail_frame.columnconfigure(1, weight=1) # Default weight for entry

        # Grid the correct label and input widget inside self.detail_frame
        if action_type == "Spell":
            self.spell_id_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=2)
            self.spell_id_entry.grid(row=0, column=1, sticky="ew", pady=2)
        elif action_type == "Lua":
            self.lua_code_label.grid(row=0, column=0, sticky=tk.NW, padx=(0, 5), pady=2) # Align top-west
            self.lua_code_text.grid(row=0, column=1, sticky="nsew", pady=2)
            # Sync text widget content from variable (important if action switched)
            self.lua_code_text.delete('1.0', tk.END)
            self.lua_code_text.insert('1.0', self.lua_code_var.get())
            # Allow Lua text box to expand vertically if needed
            self.detail_frame.rowconfigure(0, weight=1)
        elif action_type == "Macro":
            self.macro_text_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=2)
            self.macro_text_entry.grid(row=0, column=1, sticky="ew", pady=2)

    def _update_condition_inputs(self, event=None):
        """Shows/hides the correct dynamic condition input widgets."""
        # Check widgets exist
        if not all([self.condition_value_label, self.condition_value_x_entry,
                    self.condition_value_y_label, self.condition_value_y_entry,
                    self.condition_text_label, self.condition_text_entry]):
            self.app.log_message("Condition input widgets not initialized.", "ERROR")
            return

        condition = self.condition_var.get()

        # Forget all dynamic inputs first
        self.condition_value_label.grid_forget()
        self.condition_value_x_entry.grid_forget()
        self.condition_value_y_label.grid_forget()
        self.condition_value_y_entry.grid_forget()
        self.condition_text_label.grid_forget()
        self.condition_text_entry.grid_forget()

        # Reset variables for hidden fields to prevent carrying over old values
        # Use variables from self.app
        self.condition_value_x_var.set("")
        self.condition_value_y_var.set("")
        self.condition_text_var.set("")

        # Disable entries by default, enable only if shown
        self.condition_value_x_entry.config(state=tk.DISABLED)
        self.condition_value_y_entry.config(state=tk.DISABLED)
        self.condition_text_entry.config(state=tk.DISABLED)

        # --- Show and configure inputs based on selected condition (using row 4 of define_frame) ---

        # Conditions requiring a single numeric value (X)
        if "< X" in condition or "> X" in condition or ">= X" in condition:
            label_text = "Value (X):" # Default label
            if "HP %" in condition: label_text = "HP % (X):"
            elif "Mana %" in condition: label_text = "Mana % (X):"
            elif "Distance" in condition: label_text = "Dist (X) yd:"
            elif "Rage" in condition: label_text = "Rage (X):"
            elif "Energy" in condition: label_text = "Energy (X):"
            elif "Combo Points" in condition: label_text = "CPs (X):"
            # Add more specific labels if needed

            self.condition_value_label.config(text=label_text)
            self.condition_value_label.grid(row=4, column=0, sticky=tk.W, padx=5, pady=3)
            self.condition_value_x_entry.config(state=tk.NORMAL)
            self.condition_value_x_entry.grid(row=4, column=1, columnspan=1, sticky="ew", padx=5, pady=3) # Use col 1

        # Conditions requiring two numeric values (X and Y)
        elif "Between X-Y" in condition:
            self.condition_value_label.config(text="Min HP% (X):")
            self.condition_value_label.grid(row=4, column=0, sticky=tk.W, padx=(5,2), pady=3)
            self.condition_value_x_entry.config(state=tk.NORMAL)
            self.condition_value_x_entry.grid(row=4, column=1, sticky="ew", padx=(0,5), pady=3)

            self.condition_value_y_label.config(text="Max (Y):")
            self.condition_value_y_label.grid(row=4, column=2, sticky=tk.W, padx=(5,2), pady=3)
            self.condition_value_y_entry.config(state=tk.NORMAL)
            self.condition_value_y_entry.grid(row=4, column=3, sticky="ew", padx=(0,5), pady=3)

        # Conditions requiring text input (Aura Name/ID or Spell ID)
        elif "Aura" in condition or "Spell Ready" in condition:
            label_text = "Aura Name/ID:" if "Aura" in condition else "Spell ID:"
            self.condition_text_label.config(text=label_text)
            self.condition_text_label.grid(row=4, column=0, sticky=tk.W, padx=5, pady=3)
            self.condition_text_entry.config(state=tk.NORMAL)
            self.condition_text_entry.grid(row=4, column=1, columnspan=3, sticky="ew", padx=5, pady=3)

    def _on_lua_change(self, event=None):
        """Updates the lua_code_var when the ScrolledText widget changes."""
        try:
            # Use self.lua_code_text and self.lua_code_var (from app)
            if hasattr(self, 'lua_code_text') and self.lua_code_text and self.lua_code_text.winfo_exists() and \
               hasattr(self, 'lua_code_var'):
                current_text = self.lua_code_text.get("1.0", tk.END).strip()
                self.lua_code_var.set(current_text)
        except tk.TclError:
            pass # Handle case where widget might be destroyed
        except Exception as e:
            self.app.log_message(f"Error updating lua_code_var: {e}", "ERROR")

    def clear_rule_input_fields(self):
        """Clears all input fields and resets dynamic widgets."""
        # Use StringVars from self.app
        self.action_var.set("Spell") # Reset action first
        self.spell_id_var.set("")
        # Clear Lua ScrolledText widget if it exists
        if hasattr(self, 'lua_code_text') and self.lua_code_text and self.lua_code_text.winfo_exists():
            try:
                self.lua_code_text.delete('1.0', tk.END)
            except tk.TclError: pass # Ignore if widget destroyed
        self.lua_code_var.set("") # Clear variable too
        self.macro_text_var.set("")
        self.target_var.set("target")
        self.condition_var.set("None") # Reset condition
        self.int_cd_var.set("0.0")

        # Clear dynamic field variables explicitly
        self.condition_value_x_var.set("")
        self.condition_value_y_var.set("")
        self.condition_text_var.set("")

        # Update visibility of detail and condition inputs based on cleared state
        self._update_detail_inputs()
        self._update_condition_inputs()

        # Deselect listbox item
        if hasattr(self, 'rule_listbox') and self.rule_listbox and self.rule_listbox.winfo_exists():
            try:
                if self.rule_listbox.curselection():
                    self.rule_listbox.selection_clear(self.rule_listbox.curselection()[0])
            except tk.TclError: pass # Ignore if widget destroyed

        # Reset button text
        if hasattr(self, 'add_update_button') and self.add_update_button:
             self.add_update_button.config(text="Add Rule")

    def on_rule_select(self, event=None):
        """Loads the selected rule's data into the input fields."""
        if not self.rule_listbox:
             self.app.log_message("Rule listbox not initialized.", "ERROR")
             return

        indices = self.rule_listbox.curselection()
        if not indices:
            if self.add_update_button:
                self.add_update_button.config(text="Add Rule")
            return
        index = indices[0]

        try:
            # Use self.app.rotation_rules (this list holds the editor rules)
            rule = self.app.rotation_rules[index]
            action = rule.get('action', 'Spell')
            detail = rule.get('detail', '')
            target = rule.get('target', self.app.rule_targets[0])
            condition = rule.get('condition', self.app.rule_conditions[0])
            cooldown = rule.get('cooldown', 0.0)
            value_x = rule.get('condition_value_x', '')
            value_y = rule.get('condition_value_y', '')
            cond_text = rule.get('condition_text', '')

            # --- Set controls using self.app variables ---
            self.action_var.set(action)
            # Trigger updates implicitly

            # Ensure GUI updates before setting details/conditions
            # Use self.app.root for update_idletasks
            self.app.root.update_idletasks()

            if action == "Spell":
                self.spell_id_var.set(str(detail))
            elif action == "Macro":
                self.macro_text_var.set(str(detail))
            elif action == "Lua":
                self.lua_code_var.set(str(detail))
                # Update ScrolledText widget
                if hasattr(self, 'lua_code_text') and self.lua_code_text and self.lua_code_text.winfo_exists():
                    self.lua_code_text.delete('1.0', tk.END)
                    self.lua_code_text.insert('1.0', str(detail))

            self.target_var.set(target)
            self.condition_var.set(condition)
            # Trigger updates implicitly

            # Ensure GUI updates before setting condition values
            self.app.root.update_idletasks()

            self.condition_value_x_var.set(str(value_x))
            self.condition_value_y_var.set(str(value_y))
            self.condition_text_var.set(str(cond_text))

            self.int_cd_var.set(f"{cooldown:.1f}")

            if self.add_update_button:
                self.add_update_button.config(text="Update Rule")

        except IndexError:
            self.app.log_message(f"Error: Selected index {index} out of range for editor rules.", "ERROR")
            self.clear_rule_input_fields()
        except Exception as e:
            self.app.log_message(f"Error loading selected rule into editor: {e}", "ERROR")
            traceback.print_exc() # Log via redirector
            self.clear_rule_input_fields()

    def add_rotation_rule(self):
        """Adds or updates a rotation rule based on the input fields to the app's editor list."""
        # Use app state
        if self.app.rotation_running:
             messagebox.showerror("Error", "Stop the rotation before editing rules.")
             return

        # Use StringVars from app
        action = self.action_var.get()
        detail_str = ""
        detail_val: Any = None
        condition = self.condition_var.get()
        value_x = None
        value_y = None
        cond_text = None

        try:
            # --- Get Action Detail ---
            if action == "Spell":
                detail_str = self.spell_id_var.get().strip()
                if not detail_str.isdigit() or int(detail_str) <= 0:
                    raise ValueError("Spell ID must be a positive integer.")
                detail_val = int(detail_str)
            elif action == "Macro":
                detail_str = self.macro_text_var.get().strip()
                if not detail_str: raise ValueError("Macro Text cannot be empty.")
                detail_val = detail_str
            elif action == "Lua":
                # Get from the variable synced by _on_lua_change
                detail_str = self.lua_code_var.get().strip()
                if not detail_str: raise ValueError("Lua Code cannot be empty.")
                detail_val = detail_str
            else:
                raise ValueError(f"Unknown rule action: {action}")

            # --- Get Condition Details ---
            if "< X" in condition or "> X" in condition or ">= X" in condition:
                val_str = self.condition_value_x_var.get().strip()
                if not val_str: raise ValueError(f"Value (X) is required for condition '{condition}'.")
                try:
                    value_x = float(val_str)
                    if value_x.is_integer(): value_x = int(value_x)
                except ValueError:
                    raise ValueError(f"Value (X) ('{val_str}') must be a number.")
            elif "Between X-Y" in condition:
                x_str = self.condition_value_x_var.get().strip()
                y_str = self.condition_value_y_var.get().strip()
                if not x_str or not y_str: raise ValueError(f"Values X and Y are required for condition '{condition}'.")
                try:
                    value_x = float(x_str)
                    value_y = float(y_str)
                    if value_x.is_integer(): value_x = int(value_x)
                    if value_y.is_integer(): value_y = int(value_y)
                except ValueError:
                    raise ValueError(f"Values X ('{x_str}') and Y ('{y_str}') must be numbers.")
                if value_x >= value_y: raise ValueError("Value X must be less than Value Y for Between X-Y.")
            elif "Aura" in condition or "Spell Ready" in condition:
                cond_text = self.condition_text_var.get().strip()
                req = "Aura Name/ID" if "Aura" in condition else "Spell ID"
                if not cond_text:
                    raise ValueError(f"{req} is required for condition '{condition}'.")

            # --- Get Target & Cooldown ---
            target = self.target_var.get()
            cooldown_str = self.int_cd_var.get().strip()
            cooldown = float(cooldown_str)
            if cooldown < 0: raise ValueError("Internal CD must be non-negative.")

            # --- Construct Rule Dictionary ---
            rule = {
                "action": action,
                "detail": detail_val,
                "target": target,
                "condition": condition,
                "cooldown": cooldown
            }
            if value_x is not None: rule['condition_value_x'] = value_x
            if value_y is not None: rule['condition_value_y'] = value_y
            if cond_text is not None: rule['condition_text'] = cond_text

            # --- Add or Update Rule in app's editor list ---
            selected_indices = self.rule_listbox.curselection() if self.rule_listbox else []
            if selected_indices:
                index_to_update = selected_indices[0]
                # Modify app's list directly
                self.app.rotation_rules[index_to_update] = rule
                self.app.log_message(f"Updated editor rule at index {index_to_update}", "DEBUG")
                self.update_rule_listbox(select_index=index_to_update)
            else:
                # Modify app's list directly
                self.app.rotation_rules.append(rule)
                new_index = len(self.app.rotation_rules) - 1
                self.app.log_message(f"Added new rule to editor list", "DEBUG")
                self.update_rule_listbox(select_index=new_index)
                self.clear_rule_input_fields() # Clear inputs after adding NEW

            # No auto-load to engine from editor add/update

        except ValueError as e:
             messagebox.showerror("Input Error", str(e))
        except Exception as e:
             messagebox.showerror("Error", f"Failed to add/update rule: {e}")
             self.app.log_message(f"Error adding/updating editor rule: {e}", "ERROR")
             traceback.print_exc()

    def remove_selected_rule(self):
        """Removes the selected rule from the app's editor list."""
        if self.app.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before editing rules.")
            return
        if not self.rule_listbox:
            self.app.log_message("Rule listbox not initialized.", "ERROR")
            return

        indices = self.rule_listbox.curselection()
        if not indices:
             messagebox.showwarning("Selection Error", "Select a rule to remove.")
             return

        index_to_remove = indices[0]
        try:
            # Remove from app's list
            removed_rule = self.app.rotation_rules.pop(index_to_remove)
            self.app.log_message(f"Removed rule from editor list: {removed_rule}", "DEBUG")
            self.update_rule_listbox()
            self.clear_rule_input_fields()
            self.app._update_button_states() # State might depend on editor list size?
        except IndexError:
            self.app.log_message(f"Error removing rule: Index {index_to_remove} out of range.", "ERROR")
        except Exception as e:
             self.app.log_message(f"Error removing rule from editor list: {e}", "ERROR")
             messagebox.showerror("Error", f"Could not remove rule: {e}")

    def move_rule_up(self):
        """Moves the selected rule up in the app's editor list."""
        if self.app.rotation_running: return
        if not self.rule_listbox: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] == 0: return
        index = indices[0]
        # Modify app's list
        rule = self.app.rotation_rules.pop(index)
        self.app.rotation_rules.insert(index - 1, rule)
        self.update_rule_listbox(select_index=index - 1)

    def move_rule_down(self):
        """Moves the selected rule down in the app's editor list."""
        if self.app.rotation_running: return
        if not self.rule_listbox: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] >= len(self.app.rotation_rules) - 1: return
        index = indices[0]
        # Modify app's list
        rule = self.app.rotation_rules.pop(index)
        self.app.rotation_rules.insert(index + 1, rule)
        self.update_rule_listbox(select_index=index + 1)

    def update_rule_listbox(self, select_index = -1):
        """Repopulates the rule listbox based on the app's editor list."""
        if not self.rule_listbox:
            self.app.log_message("Rule listbox not initialized.", "ERROR")
            return

        self.rule_listbox.delete(0, tk.END)
        # Use self.app.rotation_rules
        for i, rule in enumerate(self.app.rotation_rules):
            action = rule.get('action', '?')
            detail = rule.get('detail', '?')
            target = rule.get('target', '?')
            condition = rule.get('condition', 'None')
            cd = rule.get('cooldown', 0.0)
            value_x = rule.get('condition_value_x', None)
            value_y = rule.get('condition_value_y', None)
            cond_text = rule.get('condition_text', None)

            if action == "Spell": detail_str = f"ID:{detail}"
            elif action == "Macro": detail_str = f"Macro:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Macro:'{detail}'"
            elif action == "Lua": detail_str = f"Lua:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Lua:'{detail}'"
            else: detail_str = str(detail)

            cond_str = condition
            if value_x is not None: cond_str = cond_str.replace(" X", f" {value_x}")
            if value_y is not None: cond_str = cond_str.replace("Y", f"{value_y}")
            if cond_text is not None:
                cond_str += f" ({cond_text})"

            cond_str_display = cond_str if len(cond_str) < 30 else cond_str[:27]+"..."
            cd_str = f"{cd:.1f}s" if cd > 0 else "-"
            rule_str = f"{i+1:02d}| {action:<5} ({detail_str:<20}) -> {target:<9} | If: {cond_str_display:<30} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, rule_str)

        if 0 <= select_index < len(self.app.rotation_rules):
            self.rule_listbox.selection_set(select_index)
            self.rule_listbox.activate(select_index)
            self.rule_listbox.see(select_index)

    def save_rules_to_file(self):
        """Saves the rules currently in the app's editor list to a JSON file."""
        # Use app's list
        if not self.app.rotation_rules:
             messagebox.showwarning("Save Error", "No rules defined in the editor to save.")
             return
        file_path = filedialog.asksaveasfilename(
             defaultextension=".json",
             filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
             initialdir="Rules",
             title="Save Rotation Rules As"
        )
        if not file_path: return

        try:
            save_dir = os.path.dirname(file_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir)
                self.app.log_message(f"Created directory: {save_dir}", "INFO")

            with open(file_path, 'w', encoding='utf-8') as f:
                # Save app's list
                json.dump(self.app.rotation_rules, f, indent=4)

            self.app.log_message(f"Saved {len(self.app.rotation_rules)} editor rules to {file_path}", "INFO")
            # Refresh dropdown via app's control tab handler
            if self.app.rotation_control_tab_handler:
                self.app.rotation_control_tab_handler.populate_script_dropdown()
            messagebox.showinfo("Save Successful", f"Saved {len(self.app.rotation_rules)} rules to:\n{os.path.basename(file_path)}")

        except Exception as e:
            error_msg = f"Failed to save rules to {file_path}: {e}"
            self.app.log_message(error_msg, "ERROR")
            messagebox.showerror("Save Error", error_msg)

    def load_rules_from_file(self):
        """Loads rules from a JSON file into the app's editor list."""
        if self.app.rotation_running:
            messagebox.showerror("Load Error", "Stop the rotation before loading new rules.")
            return
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Load Rotation Rules",
            initialdir="Rules"
        )
        if not file_path: return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_rules = json.load(f)
            if not isinstance(loaded_rules, list):
                raise ValueError("Invalid format: JSON root must be a list of rules.")

            # Update the app's editor list
            self.app.rotation_rules = loaded_rules
            self.update_rule_listbox()
            self.clear_rule_input_fields()

            # Clear loaded script info in engine via app
            if self.app.combat_rotation and hasattr(self.app.combat_rotation, 'clear_lua_script'):
                self.app.combat_rotation.clear_lua_script()
            self.app.script_var.set("") # Clear file dropdown selection via app var

            self.app.log_message(f"Loaded {len(self.app.rotation_rules)} rules from: {file_path} into editor.", "INFO")
            self.app._update_button_states()
            messagebox.showinfo("Load Successful", f"Loaded {len(self.app.rotation_rules)} rules into editor from:\n{os.path.basename(file_path)}")

        except json.JSONDecodeError as e:
            self.app.log_message(f"Error decoding JSON from {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
        except ValueError as e:
            self.app.log_message(f"Error validating rules file {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
        except Exception as e:
            self.app.log_message(f"Error loading rules from {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")

    def scan_spellbook(self):
        """Opens a window displaying known spells from the ObjectManager."""
        # Use app components
        if not self.app.om or not self.app.om.is_ready():
            messagebox.showerror("Error", "Object Manager not ready. Cannot scan spellbook.")
            return
        if not self.app.game or not self.app.game.is_ready():
            messagebox.showerror("Error", "Game Interface not ready. Cannot get spell info.")
            return

        spell_ids = self.app.om.read_known_spell_ids()
        if not spell_ids:
            messagebox.showinfo("Spellbook Scan", "No spell IDs found or unable to read spellbook.")
            return

        # Use app.root as parent
        scan_window = tk.Toplevel(self.app.root)
        scan_window.title("Known Spells")
        scan_window.geometry("500x400")
        scan_window.transient(self.app.root)
        scan_window.grab_set()

        tree_frame = ttk.Frame(scan_window)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("id", "name", "rank")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        tree.heading("id", text="ID")
        tree.heading("name", text="Name")
        tree.heading("rank", text="Rank")
        tree.column("id", width=70, anchor=tk.E)
        tree.column("name", width=250)
        tree.column("rank", width=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        def populate_tree():
            count = 0
            max_to_fetch = 500
            for spell_id in sorted(spell_ids):
                if count >= max_to_fetch:
                    try: tree.insert("", tk.END, values=(f"({len(spell_ids)-max_to_fetch} more)", "...", "..."))
                    except tk.TclError: break
                    break

                # Call get_spell_info via app.game
                info = self.app.game.get_spell_info(spell_id)

                try:
                    if info:
                        name = info.get("name", "N/A")
                        rank = info.get("rank", "None")
                        if not rank: rank = "None"
                        tree.insert("", tk.END, values=(spell_id, name, rank))
                    else:
                        tree.insert("", tk.END, values=(spell_id, "(Info Failed)", ""))
                except tk.TclError: break
                count += 1
        populate_tree()

        def copy_id():
            selected_item = tree.focus()
            if selected_item:
                item_data = tree.item(selected_item)
                try:
                    if item_data and 'values' in item_data and len(item_data['values']) > 0:
                        spell_id_to_copy = item_data['values'][0]
                        # Use app.root for clipboard
                        self.app.root.clipboard_clear()
                        self.app.root.clipboard_append(str(spell_id_to_copy))
                        self.app.log_message(f"Copied Spell ID: {spell_id_to_copy}", "DEBUG")
                    else:
                         messagebox.showwarning("Copy Error", "Could not retrieve Spell ID from selected item.", parent=scan_window)
                except Exception as e:
                     messagebox.showerror("Clipboard Error", f"Could not copy to clipboard:\n{e}", parent=scan_window)

        copy_button = ttk.Button(scan_window, text="Copy Selected Spell ID", command=copy_id)
        copy_button.pack(pady=5)

    def lookup_spell_info(self):
        """Opens a dialog to enter a Spell ID and displays its info using GameInterface."""
        # Use app components
        if not self.app.game or not self.app.game.is_ready():
            messagebox.showerror("Error", "Game Interface not ready. Cannot get spell info.")
            return

        # Use app.root as parent
        spell_id_str = simpledialog.askstring("Lookup Spell", "Enter Spell ID:", parent=self.app.root)
        if not spell_id_str: return
        try:
            spell_id = int(spell_id_str)
            if spell_id <= 0: raise ValueError("Spell ID must be positive.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Spell ID must be a positive integer.")
            return

        info = self.app.game.get_spell_info(spell_id)
        if info:
            info_lines = [f"Spell ID: {spell_id}"]
            power_map = {
                WowObject.POWER_MANA: "Mana", WowObject.POWER_RAGE: "Rage",
                WowObject.POWER_FOCUS: "Focus", WowObject.POWER_ENERGY: "Energy",
                WowObject.POWER_RUNIC_POWER: "Runic Power", -1: "N/A"
            }
            for key, value in info.items():
                 if value is not None:
                      if key == "castTime" and isinstance(value, (int, float)):
                           value_str = f"{value / 1000.0:.2f}s ({value}ms)" if value > 0 else "Instant"
                      elif key in ["minRange", "maxRange"] and isinstance(value, (int, float)):
                           value_str = f"{value:.1f} yd"
                      elif key == "cost" and isinstance(value, (int, float)):
                           value_str = f"{value:.0f}"
                      elif key == "powerType" and isinstance(value, int):
                           value_str = power_map.get(value, f"Type {value}")
                      else:
                           value_str = str(value)
                      key_str = ''.join(' ' + c if c.isupper() else c for c in key).lstrip().title()
                      info_lines.append(f"{key_str}: {value_str}")

            messagebox.showinfo(f"Spell Info: {info.get('name', spell_id)}", "\n".join(info_lines))
            self.app.log_message(f"Looked up Spell ID {spell_id}: {info.get('name', 'N/A')}", "DEBUG")
        else:
            messagebox.showwarning("Spell Lookup", f"Could not find information for Spell ID {spell_id}.\nCheck DLL logs or if the ID is valid.")
            self.app.log_message(f"Spell info lookup failed for ID {spell_id}", "WARN") 