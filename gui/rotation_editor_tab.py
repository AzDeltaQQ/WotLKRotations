import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog, simpledialog, Listbox
import os
import json
import traceback
from typing import TYPE_CHECKING, Optional, Any, List, Dict

# Project Modules (for type hints)
from wow_object import WowObject # Needed for spell info power types

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp # Import from the main gui module

# Constants (can be moved later)
RULE_SAVE_DIR = "Rules"

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

        # Internal state for the currently edited conditions list
        self._current_rule_conditions: List[Dict[str, Any]] = []
        # --- Initialize selected_rule_index --- 
        self.selected_rule_index: Optional[int] = None # Track selected rule in main list

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
        self.condition_value_frame: Optional[ttk.Frame] = None
        self.add_update_button: Optional[ttk.Button] = None

        # --- NEW: Widgets for managing conditions of the *current* rule ---
        self.current_conditions_frame: Optional[ttk.LabelFrame] = None
        self.conditions_listbox: Optional[tk.Listbox] = None
        self.remove_condition_button: Optional[ttk.Button] = None
        # --- End NEW ---

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
        self._update_condition_value_inputs_visibility()

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
        self.detail_inputs_frame = ttk.Frame(define_frame)
        self.detail_inputs_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=5, pady=3)
        self.detail_inputs_frame.columnconfigure(1, weight=1) # Allow detail input to expand

        # Detail Widgets (placed inside detail_frame by _update_detail_inputs)
        self.spell_id_label = ttk.Label(self.detail_inputs_frame, text="Spell ID:")
        self.spell_id_entry = ttk.Entry(self.detail_inputs_frame, textvariable=self.spell_id_var)
        self.lua_code_label = ttk.Label(self.detail_inputs_frame, text="Lua Code:")
        self.lua_code_text = scrolledtext.ScrolledText(self.detail_inputs_frame, wrap=tk.WORD, height=4, width=30, font=self.app.CODE_FONT)
        self.lua_code_text.bind("<KeyRelease>", self._on_lua_change)
        self.macro_text_label = ttk.Label(self.detail_inputs_frame, text="Macro Text:")
        self.macro_text_entry = ttk.Entry(self.detail_inputs_frame, textvariable=self.macro_text_var)

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
        # Bind to self._update_condition_value_inputs_visibility in this class
        self.condition_dropdown.bind("<<ComboboxSelected>>", self._update_condition_value_inputs_visibility)

        # Row 4: Dynamic Condition Inputs (Labels & Entries managed by _update_condition_value_inputs_visibility)
        self.condition_value_frame = ttk.Frame(define_frame)
        self.condition_value_frame.grid(row=4, column=0, columnspan=4, pady=10)
        self.condition_value_frame.columnconfigure(3, weight=0) # Ensure Add Cond button doesn't expand weirdly

        # Value X Widgets (inside condition_value_frame)
        self.condition_value_x_frame = ttk.Frame(self.condition_value_frame) # Container frame for X
        self.condition_value_x_label = ttk.Label(self.condition_value_x_frame, text="Value (X):")
        self.condition_value_x_label.pack(side=tk.LEFT, padx=(0, 2)) # Pack inside x_frame
        self.condition_value_x_entry = ttk.Entry(self.condition_value_x_frame, textvariable=self.condition_value_x_var, width=8)
        self.condition_value_x_entry.pack(side=tk.LEFT) # Pack inside x_frame
        # Value Y Widgets
        self.condition_value_y_frame = ttk.Frame(self.condition_value_frame) # Container frame for Y
        self.condition_value_y_label = ttk.Label(self.condition_value_y_frame, text="Value (Y):")
        self.condition_value_y_label.pack(side=tk.LEFT, padx=(0, 2)) # Pack inside y_frame
        self.condition_value_y_entry = ttk.Entry(self.condition_value_y_frame, textvariable=self.condition_value_y_var, width=8)
        self.condition_value_y_entry.pack(side=tk.LEFT) # Pack inside y_frame
        # Text Widgets
        self.condition_text_frame = ttk.Frame(self.condition_value_frame) # Container frame for Text
        self.condition_text_label = ttk.Label(self.condition_text_frame, text="Name/ID:")
        self.condition_text_label.pack(side=tk.LEFT, padx=(0, 2)) # Pack inside text_frame
        self.condition_text_entry = ttk.Entry(self.condition_text_frame, textvariable=self.condition_text_var, width=15)
        self.condition_text_entry.pack(side=tk.LEFT) # Pack inside text_frame
        # (These container frames - x_frame, y_frame, text_frame - are gridded/forgotten inside condition_value_frame by _update_condition_value_inputs_visibility)

        self.add_condition_button = ttk.Button(self.condition_value_frame, text="Add Cond.", command=self._add_condition_to_list, width=10)
        self.add_condition_button.grid(row=0, column=3, padx=(5, 0))

        # --- NEW: Current Conditions List Section ---
        self.current_conditions_frame = ttk.LabelFrame(define_frame, text="Current Rule Conditions", padding="5")
        self.current_conditions_frame.grid(row=5, column=0, columnspan=4, sticky="ew", padx=5, pady=(5,10))
        self.current_conditions_frame.columnconfigure(0, weight=1) # Listbox expands
        self.current_conditions_frame.rowconfigure(0, weight=1) # Listbox expands vertically (optional)

        self.conditions_listbox = tk.Listbox(
            self.current_conditions_frame,
            height=3, # Start small
            exportselection=False,
            # Apply styles from app instance if desired, or use defaults
            bg=self.app.rule_listbox_style.get("bg", "#FFFFFF"),
            fg=self.app.rule_listbox_style.get("fg", "#000000"),
            font=self.app.DEFAULT_FONT,
            selectbackground=self.app.rule_listbox_style.get("selectbackground", "#AED6F1"), # Lighter blue?
            selectforeground=self.app.rule_listbox_style.get("selectforeground", "#000000")
        )
        self.conditions_listbox.grid(row=0, column=0, sticky="nsew")

        cond_scrollbar = ttk.Scrollbar(self.current_conditions_frame, orient=tk.VERTICAL, command=self.conditions_listbox.yview)
        self.conditions_listbox.config(yscrollcommand=cond_scrollbar.set)
        cond_scrollbar.grid(row=0, column=1, sticky='ns')

        self.remove_condition_button = ttk.Button(self.current_conditions_frame, text="Remove Cond.", command=self._remove_selected_condition, width=12)
        self.remove_condition_button.grid(row=1, column=0, columnspan=2, pady=(5,0), sticky='ew')
        # --- End NEW ---

        # Row 6: Internal Cooldown (Use self.int_cd_var from app)
        ttk.Label(define_frame, text="Int. CD (s):").grid(row=6, column=0, sticky=tk.W, padx=5, pady=3)
        self.int_cd_entry = ttk.Entry(define_frame, textvariable=self.int_cd_var, width=8)
        self.int_cd_entry.grid(row=6, column=1, sticky=tk.W, padx=5, pady=3)

        # Row 7: Add/Update Rule Buttons Frame
        add_update_frame = ttk.Frame(define_frame)
        add_update_frame.grid(row=7, column=0, columnspan=4, pady=10)

        self.add_new_rule_button = ttk.Button(add_update_frame, text="Add New Rule", command=self._add_new_rule)
        self.add_new_rule_button.pack(side=tk.LEFT, padx=5)

        self.update_selected_rule_button = ttk.Button(add_update_frame, text="Update Selected Rule", command=self._update_selected_rule, state=tk.DISABLED) # Starts disabled
        self.update_selected_rule_button.pack(side=tk.LEFT, padx=5)

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
        self.rule_listbox = Listbox(
            rule_list_frame,
            # Apply styles from app instance
            bg=self.app.rule_listbox_style.get("bg", "#FFFFFF"),
            fg=self.app.rule_listbox_style.get("fg", "#000000"),
            font=self.app.DEFAULT_FONT,
            selectbackground=self.app.rule_listbox_style.get("selectbackground", "#0078D7"),
            selectforeground=self.app.rule_listbox_style.get("selectforeground", "#FFFFFF"),
            borderwidth=self.app.rule_listbox_style.get("borderwidth", 1),
            highlightthickness=self.app.rule_listbox_style.get("highlightthickness", 1),
            exportselection=False # Prevent selection loss on focus change
        )
        self.rule_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Bind to self.on_rule_select in this class
        self.rule_listbox.bind('<<ListboxSelect>>', self.on_rule_select)
        # Bind left-click release to handle deselection
        self.rule_listbox.bind('<ButtonRelease-1>', self._handle_listbox_click)

        scrollbar = ttk.Scrollbar(rule_list_frame, orient=tk.VERTICAL, command=self.rule_listbox.yview)
        self.rule_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Listbox Button Frame ---
        rule_button_frame = ttk.Frame(right_pane)
        rule_button_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        # Bind buttons to methods in this class
        self.move_up_button = ttk.Button(rule_button_frame, text="Move Up", command=self.move_rule_up)
        self.move_up_button.pack(side=tk.LEFT, padx=(0,5))
        self.move_down_button = ttk.Button(rule_button_frame, text="Move Down", command=self.move_rule_down)
        self.move_down_button.pack(side=tk.LEFT, padx=5)
        self.remove_rule_button = ttk.Button(rule_button_frame, text="Remove Selected", command=self._remove_selected_rule)
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
                    self.detail_inputs_frame]):
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
        self.detail_inputs_frame.rowconfigure(0, weight=0)
        self.detail_inputs_frame.columnconfigure(1, weight=1) # Default weight for entry

        # Grid the correct label and input widget inside self.detail_inputs_frame
        if action_type == "Spell":
            self.spell_id_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=2)
            self.spell_id_entry.grid(row=0, column=1, sticky="ew", pady=2)
        elif action_type == "Lua":
            self.lua_code_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=2)
            self.lua_code_text.grid(row=0, column=1, sticky="nsew", pady=2)
            # Sync text widget content from variable (important if action switched)
            self.lua_code_text.delete('1.0', tk.END)
            self.lua_code_text.insert('1.0', self.lua_code_var.get())
            # Allow Lua text box to expand vertically if needed
            self.detail_inputs_frame.rowconfigure(0, weight=1)
        elif action_type == "Macro":
            self.macro_text_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 5), pady=2)
            self.macro_text_entry.grid(row=0, column=1, sticky="ew", pady=2)

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

        # --- NEW: Clear current conditions list and its listbox ---
        self._current_rule_conditions = []
        if hasattr(self, 'conditions_listbox') and self.conditions_listbox:
            try:
                self.conditions_listbox.delete(0, tk.END)
            except tk.TclError: pass # Ignore if widget destroyed
        # --- End NEW ---

        # Update visibility of detail and condition inputs based on cleared state
        self._update_detail_inputs()
        self._update_condition_value_inputs_visibility()

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
            self.selected_rule_index = None
            if self.update_selected_rule_button:
                self.update_selected_rule_button.config(state=tk.DISABLED)
            return
        index = indices[0]

        # --- Sanity Check: Ensure index is valid before proceeding --- 
        if not (0 <= index < len(self.app.rotation_rules)):
            self.app.log_message(f"on_rule_select: Index {index} out of bounds for rules list (len={len(self.app.rotation_rules)}). Clearing selection.", "WARN")
            self.rule_listbox.selection_clear(0, tk.END)
            self.selected_rule_index = None
            if self.update_selected_rule_button:
                self.update_selected_rule_button.config(state=tk.DISABLED)
            # Consider clearing fields? Maybe not, leave them as they were.
            # self.clear_rule_input_fields()
            return
        # --- End Sanity Check ---

        # If check passes, set the index
        self.selected_rule_index = index

        try:
            # Use self.app.rotation_rules (this list holds the editor rules)
            rule = self.app.rotation_rules[index]
            action = rule.get('action', 'Spell')
            detail_val = rule.get('detail', '')
            target = rule.get('target', self.app.rule_targets[0])
            condition = rule.get('condition', self.app.rule_conditions[0])
            cooldown = rule.get('cooldown', 0.0)
            value_x = rule.get('condition_value_x', '')
            value_y = rule.get('condition_value_y', '')
            cond_text = rule.get('condition_text', '')

            # --- NEW: Load conditions into the internal list and listbox ---
            loaded_conditions = rule.get('conditions') # Get the list, might be None or empty

            # --- BACKWARD COMPATIBILITY: Handle old single condition format --- 
            if not loaded_conditions and 'condition' in rule and rule['condition'] != 'None':
                self.app.log_message(f"Loading rule {index+1} with old condition format. Converting.", "DEBUG")
                old_condition_data = {"condition": rule['condition']}
                if 'condition_value_x' in rule: old_condition_data['value_x'] = rule['condition_value_x']
                if 'condition_value_y' in rule: old_condition_data['value_y'] = rule['condition_value_y']
                if 'condition_text' in rule: old_condition_data['text'] = rule['condition_text']
                # Overwrite loaded_conditions with a list containing the converted old condition
                loaded_conditions = [old_condition_data]
            # --- End BACKWARD COMPATIBILITY --- 

            # Use the potentially converted list, default to empty list if still None/empty
            self._current_rule_conditions = list(loaded_conditions) if loaded_conditions else []

            if hasattr(self, 'conditions_listbox') and self.conditions_listbox:
                self.conditions_listbox.delete(0, tk.END)
                for cond_data in self._current_rule_conditions:
                    display_str = self._format_condition_for_display(cond_data)
                    self.conditions_listbox.insert(tk.END, display_str)

            # --- Set controls using self.app variables ---
            self.action_var.set(action)
            # Trigger updates implicitly

            # Ensure GUI updates before setting details/conditions
            # Use self.app.root for update_idletasks
            self.app.root.update_idletasks()

            if action == "Spell":
                self.spell_id_var.set(str(detail_val))
            elif action == "Macro":
                self.macro_text_var.set(str(detail_val))
            elif action == "Lua":
                self.lua_code_var.set(str(detail_val))
                # Update ScrolledText widget
                if hasattr(self, 'lua_code_text') and self.lua_code_text and self.lua_code_text.winfo_exists():
                    self.lua_code_text.delete('1.0', tk.END)
                    self.lua_code_text.insert('1.0', str(detail_val))

            self.target_var.set(target)
            self.condition_var.set(condition)
            # Trigger updates implicitly

            # Ensure GUI updates before setting condition values
            self.app.root.update_idletasks()

            self.condition_value_x_var.set(str(value_x))
            self.condition_value_y_var.set(str(value_y))
            self.condition_text_var.set(str(cond_text))

            self.int_cd_var.set(f"{cooldown:.1f}")

            # Update button state
            if self.update_selected_rule_button:
                self.update_selected_rule_button.config(state=tk.NORMAL) # Enable update button

        except IndexError:
            self.app.log_message(f"Error: Selected index {index} out of range for editor rules.", "ERROR")
            self.clear_rule_input_fields()
            self.update_selected_rule_button.config(state=tk.DISABLED)
        except Exception as e:
            self.app.log_message(f"Error loading selected rule into editor: {e}", "ERROR")
            traceback.print_exc() # Log via redirector
            self.clear_rule_input_fields()
            self.update_selected_rule_button.config(state=tk.DISABLED)

    def _gather_rule_data_from_inputs(self) -> Optional[Dict[str, Any]]:
        """Gathers data from input fields and returns a rule dictionary or None on error."""
        action = self.action_var.get()
        target = self.target_var.get()
        conditions = self._current_rule_conditions # Use the internal list

        # Get detail based on action
        detail: Any = None
        if action == "Spell":
            try: detail = int(self.spell_id_var.get())
            except ValueError: messagebox.showerror("Error", "Spell ID must be a number."); return None
        elif action == "Macro": detail = self.macro_text_var.get()
        elif action == "Lua": detail = self.lua_code_var.get() # Get from var synced by _on_lua_change
        if detail is None or (isinstance(detail, str) and not detail.strip()):
             messagebox.showerror("Error", f"{action} detail cannot be empty."); return None

        # Get internal cooldown
        try: cooldown = float(self.int_cd_var.get())
        except ValueError: messagebox.showerror("Error", "Internal CD must be a number."); return None

        # --- Create Rule Dictionary ---
        rule_data: Dict[str, Any] = {
            "action": action,
            "detail": detail,
            "target": target,
            "conditions": conditions, # Save the list of conditions
            "cooldown": cooldown,
            # Add other fields like "enabled": True if needed
        }
        return rule_data

    def _add_new_rule(self):
        """Adds a new rule based on the current input fields."""
        new_rule_data = self._gather_rule_data_from_inputs()
        if new_rule_data is None:
            return # Error occurred during data gathering

        # Add new rule to the main list in the app
        self.app.rotation_rules.append(new_rule_data)
        self.app.log_message("New rule added.", "INFO")
        added_index = len(self.app.rotation_rules) - 1

        # Refresh UI
        self._update_rule_listbox_display()
        # Select the newly added rule
        if self.rule_listbox:
            self.rule_listbox.selection_clear(0, tk.END)
            self.rule_listbox.selection_set(added_index)
            self.rule_listbox.see(added_index)
        # Reload data into fields to confirm add and set button state
        # self.on_rule_select() # Removed: _update_rule_listbox_display should handle selection state

    def _update_selected_rule(self):
        """Updates the currently selected rule with data from input fields."""
        if self.selected_rule_index is None or not (0 <= self.selected_rule_index < len(self.app.rotation_rules)):
            messagebox.showerror("Error", "No rule selected or selection is invalid.")
            return

        updated_rule_data = self._gather_rule_data_from_inputs()
        if updated_rule_data is None:
            return # Error occurred during data gathering

        # Update the rule in the main list
        self.app.rotation_rules[self.selected_rule_index] = updated_rule_data
        self.app.log_message(f"Rule {self.selected_rule_index + 1} updated.", "INFO")
        updated_index = self.selected_rule_index

        # Clear the temporary condition list *after* successful update
        self._current_rule_conditions = []

        # Refresh UI
        self._update_rule_listbox_display()
        # Re-select the updated rule programmatically to ensure consistency
        if self.rule_listbox:
            self.rule_listbox.selection_clear(0, tk.END)
            self.rule_listbox.selection_set(updated_index)
            self.rule_listbox.see(updated_index)
        # Reload data into fields to confirm update
        # self.on_rule_select() # Removed: _update_rule_listbox_display should handle selection state

    def _remove_selected_rule(self):
        """Removes the selected rule from the main list (app.rotation_rules)."""
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
            self.app.log_message(f"Removed rule {index_to_remove + 1} from editor list: {removed_rule}", "DEBUG")

            # --- Explicitly clear selected index --- 
            self.selected_rule_index = None
            # --- End --- 

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
            detail_val = rule.get('detail', '?')
            target = rule.get('target', '?')
            condition = rule.get('condition', 'None')
            cooldown = rule.get('cooldown', 0.0)
            value_x = rule.get('condition_value_x', None)
            value_y = rule.get('condition_value_y', None)
            cond_text = rule.get('condition_text', None)

            # Format conditions for display (simplified)
            # --- GET the conditions list from the rule FIRST --- 
            conditions_list = rule.get('conditions', []) # Default to empty list
            # --- End GET --- 
            condition_display = "No Condition" # Default

            # --- Check NEW format first ---
            condition_strs = [self._format_condition_for_display(c) for c in conditions_list]
            if len(condition_strs) > 1:
                condition_display = condition_strs[0] + " AND ..." # Show first + indicator
            elif len(condition_strs) == 1:
                condition_display = condition_strs[0]
            else:
                # --- If NEW format empty, check OLD format --- 
                old_condition = rule.get('condition')
                if old_condition and old_condition != 'None':
                    # Reconstruct dict for formatting
                    old_condition_data = {"condition": old_condition}
                    if 'condition_value_x' in rule: old_condition_data['value_x'] = rule['condition_value_x']
                    if 'condition_value_y' in rule: old_condition_data['value_y'] = rule['condition_value_y']
                    if 'condition_text' in rule: old_condition_data['text'] = rule['condition_text']
                    condition_display = self._format_condition_for_display(old_condition_data)
                # If neither format found, it remains "No Condition"
            # --- End OLD format check ---

            # Format Detail
            if action == "Spell": detail_str = f"ID:{detail_val}"
            elif action == "Macro": detail_str = f"Macro:'{str(detail_val)[:10]}..'" if len(str(detail_val)) > 10 else f"Macro:'{detail_val}'"
            elif action == "Lua": detail_str = f"Lua:'{str(detail_val)[:10]}..'" if len(str(detail_val)) > 10 else f"Lua:'{detail_val}'"
            else: detail_str = str(detail_val)

            # Truncate long details/conditions for display
            # if isinstance(detail_str, str) and len(detail_str) > 20: detail_str = detail_str[:17] + "..." # Already handled above
            if len(condition_display) > 30: condition_display = condition_display[:27] + "..."

            cd_str = f"{cooldown:.1f}s" if cooldown > 0 else "-"

            display_text = f"{i+1:02d}| {action:<5} ({detail_str:<20}) -> {target:<9} | If: {condition_display:<30} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, display_text)

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

        copy_button = ttk.Button(scan_window, text="Use Selected ID", command=copy_id)
        copy_button.pack(pady=5)

    def lookup_spell_info(self):
        """Opens a dialog to enter a Spell ID and displays its info using GameInterface."""
        # Use app components
        if not self.app.game or not self.app.game.is_ready():
            messagebox.showerror("Error", "Game Interface not ready. Cannot get spell info.")
            return

        # Use app.root as parent
        spell_id_str = simpledialog.askstring("Spell ID Lookup", "Enter Spell ID:", parent=self.app.root)
        if not spell_id_str: return
        try:
            spell_id = int(spell_id_str)
            if spell_id <= 0: raise ValueError("Spell ID must be positive.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Spell ID must be a positive integer.")
            return

        info = self.app.game.get_spell_info(spell_id)
        if info:
            info_lines = [f"Spell ID: {spell_id}", f"Name: {info.get('name', 'N/A')}", f"Rank: {info.get('rank', 'N/A')}", f"Cast Time: {info.get('castTime', 0) / 1000.0:.2f}s ({info.get('castTime', 0)}ms)", f"Power Type: {info.get('powerType', 'N/A')}"]
            messagebox.showinfo(f"Spell Info: {info.get('name', spell_id)}", "\n".join(info_lines))
            self.app.log_message(f"Looked up Spell ID {spell_id}: {info.get('name', 'N/A')}", "INFO")
        else:
            messagebox.showwarning("Not Found", f"Could not find information for Spell ID {spell_id}.\nCheck DLL logs or if the ID is valid.")
            self.app.log_message(f"Spell info lookup failed for ID {spell_id}", "WARN")

    # --- Condition Input Management ---
    def _update_condition_value_inputs_visibility(self, event=None):
        """Shows/hides Value X, Value Y, or Text input based on selected Condition."""
        # Get the selected condition
        try:
            condition: str = self.condition_var.get()
        except AttributeError: # Handle case where self.condition_var might not be ready
            self.app.log_message("Condition variable not ready during visibility update.", "DEBUG")
            return

        # Define which conditions need which inputs
        needs_x = any(s in condition for s in ["< X", "> X", ">= X", "% < X", "% > X", "Points >= X", "Distance < X", "Distance > X"])
        needs_y = "Between X-Y" in condition
        needs_text = "Aura" in condition # For "Target Has Aura", "Target Missing Aura", etc.

        # Forget all container frames first, checking existence
        if hasattr(self, 'condition_value_x_frame') and self.condition_value_x_frame:
            self.condition_value_x_frame.grid_forget()
        if hasattr(self, 'condition_value_y_frame') and self.condition_value_y_frame:
            self.condition_value_y_frame.grid_forget()
        if hasattr(self, 'condition_text_frame') and self.condition_text_frame:
            self.condition_text_frame.grid_forget()

        # Grid the required container frame(s) inside self.condition_value_frame
        # Arrange them horizontally using columns in condition_value_frame
        col_index = 0
        if needs_x:
            if hasattr(self, 'condition_value_x_frame') and self.condition_value_x_frame:
                self.condition_value_x_frame.grid(row=0, column=col_index, sticky=tk.W, padx=(0, 5))
                col_index += 1

        if needs_y:
            # Assumes needs_x is also true for Between X-Y
            if hasattr(self, 'condition_value_y_frame') and self.condition_value_y_frame:
                self.condition_value_y_frame.grid(row=0, column=col_index, sticky=tk.W, padx=(0, 5))
                col_index += 1

        if needs_text:
            if hasattr(self, 'condition_text_frame') and self.condition_text_frame:
                self.condition_text_frame.grid(row=0, column=col_index, sticky=tk.W, padx=(0, 5))
                col_index += 1

    def _format_condition_for_display(self, condition_dict: Dict[str, Any]) -> str:
        """Formats a condition dictionary into a readable string for the listbox (more robust)."""
        cond_template = condition_dict.get("condition", "Invalid Condition")
        val_x = condition_dict.get("value_x")
        val_y = condition_dict.get("value_y")
        val_text = condition_dict.get("text")

        display_str = cond_template # Start with the template

        # Special case: "Between X-Y" needs both replaced together
        if "Between X-Y" in display_str:
            x_disp = "?"
            y_disp = "?"
            if val_x is not None:
                try: x_disp = f"{float(val_x):g}"
                except (ValueError, TypeError): x_disp = str(val_x)
            if val_y is not None:
                try: y_disp = f"{float(val_y):g}"
                except (ValueError, TypeError): y_disp = str(val_y)
            display_str = display_str.replace("X-Y", f"{x_disp}-{y_disp}")
        else:
            # Replace X placeholder if value exists
            if " X" in display_str and val_x is not None:
                try: val_x_disp = f"{float(val_x):g}"
                except (ValueError, TypeError): val_x_disp = str(val_x)
                display_str = display_str.replace(" X", f" {val_x_disp}") # Note the space

            # Replace Y placeholder if value exists (shouldn't happen if not Between X-Y, but safe)
            if " Y" in display_str and val_y is not None:
                try: val_y_disp = f"{float(val_y):g}"
                except (ValueError, TypeError): val_y_disp = str(val_y)
                display_str = display_str.replace(" Y", f" {val_y_disp}")

        # Handle text (Aura Name/ID) - Append if implied by condition type
        # Assume conditions needing text imply it rather than having a placeholder
        if "Aura" in cond_template and val_text:
            display_str += f": {val_text}" # Append the text value

        return display_str

    def _add_condition_to_list(self):
        """Adds the currently configured condition to the internal list and listbox."""
        # Add hasattr check for safety
        if not hasattr(self, 'conditions_listbox') or not self.conditions_listbox or not self.conditions_listbox.winfo_exists():
            self.app.log_message("Conditions listbox not ready.", "ERROR")
            return

        condition = self.condition_var.get()
        if not condition or condition == "None":
            messagebox.showwarning("No Condition", "Please select a valid condition to add.")
            return

        new_condition_data: Dict[str, Any] = {"condition": condition}

        # Define which conditions need which inputs (copied)
        needs_x = any(s in condition for s in ["< X", "> X", ">= X", "% < X", "% > X", "Points >= X", "Distance < X", "Distance > X"])
        needs_y = "Between X-Y" in condition
        needs_text = "Aura" in condition

        try:
            if needs_x:
                value_x_str = self.condition_value_x_var.get()
                if not value_x_str: raise ValueError("Value (X) cannot be empty.")
                # Attempt to convert to float, might need int for some conditions later
                new_condition_data["value_x"] = float(value_x_str)
            if needs_y:
                value_y_str = self.condition_value_y_var.get()
                if not value_y_str: raise ValueError("Value (Y) cannot be empty.")
                new_condition_data["value_y"] = float(value_y_str)
            if needs_text:
                value_text = self.condition_text_var.get()
                if not value_text.strip(): raise ValueError("Name/ID cannot be empty.")
                new_condition_data["text"] = value_text.strip()
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Error adding condition: {e}")
            return

        # Add to internal list (associated with the rule being edited)
        self._current_rule_conditions.append(new_condition_data)

        # Add formatted string to the dedicated conditions listbox
        display_str = self._format_condition_for_display(new_condition_data)
        self.conditions_listbox.insert(tk.END, display_str)

    def _update_rule_listbox_display(self):
        """Updates the main listbox displaying the rules from app.rotation_rules."""
        if not self.rule_listbox: return

        # Store current selection to restore it later
        current_selection_index = self.selected_rule_index # Use our tracker

        self.rule_listbox.delete(0, tk.END)
        for i, rule in enumerate(self.app.rotation_rules):
            action = rule.get("action", "?")
            detail_val = rule.get("detail", "?")
            target = rule.get("target", "?")
            conditions = rule.get("conditions", []) # Get list
            cooldown = rule.get('cooldown', 0.0)

            # Format conditions for display (simplified)
            # --- GET the conditions list from the rule FIRST --- 
            conditions_list = rule.get('conditions', []) # Default to empty list
            # --- End GET --- 
            condition_display = "No Condition" # Default

            # --- Check NEW format first ---
            condition_strs = [self._format_condition_for_display(c) for c in conditions_list]
            if len(condition_strs) > 1:
                condition_display = condition_strs[0] + " AND ..." # Show first + indicator
            elif len(condition_strs) == 1:
                condition_display = condition_strs[0]
            else:
                # --- If NEW format empty, check OLD format --- 
                old_condition = rule.get('condition')
                if old_condition and old_condition != 'None':
                    # Reconstruct dict for formatting
                    old_condition_data = {"condition": old_condition}
                    if 'condition_value_x' in rule: old_condition_data['value_x'] = rule['condition_value_x']
                    if 'condition_value_y' in rule: old_condition_data['value_y'] = rule['condition_value_y']
                    if 'condition_text' in rule: old_condition_data['text'] = rule['condition_text']
                    condition_display = self._format_condition_for_display(old_condition_data)
                # If neither format found, it remains "No Condition"
            # --- End OLD format check ---

            # Format Detail
            if action == "Spell": detail_str = f"ID:{detail_val}"
            elif action == "Macro": detail_str = f"Macro:'{str(detail_val)[:10]}..'" if len(str(detail_val)) > 10 else f"Macro:'{detail_val}'"
            elif action == "Lua": detail_str = f"Lua:'{str(detail_val)[:10]}..'" if len(str(detail_val)) > 10 else f"Lua:'{detail_val}'"
            else: detail_str = str(detail_val)

            # Truncate long details/conditions for display
            # if isinstance(detail_str, str) and len(detail_str) > 20: detail_str = detail_str[:17] + "..." # Already handled above
            if len(condition_display) > 30: condition_display = condition_display[:27] + "..."

            cd_str = f"{cooldown:.1f}s" if cooldown > 0 else "-"

            display_text = f"{i+1:02d}| {action:<5} ({detail_str:<20}) -> {target:<9} | If: {condition_display:<30} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, display_text)

        # Restore selection if possible
        if current_selection_index is not None:
            try:
                if 0 <= current_selection_index < self.rule_listbox.size():
                    self.rule_listbox.selection_set(current_selection_index)
                    self.rule_listbox.activate(current_selection_index)
                    self.rule_listbox.see(current_selection_index)
                    # Ensure internal index is still correct
                    self.selected_rule_index = current_selection_index
                else:
                     self.selected_rule_index = None # Selection index no longer valid
                     if self.update_selected_rule_button: self.update_selected_rule_button.config(state=tk.DISABLED)
            except (IndexError, tk.TclError):
                 self.selected_rule_index = None # Clear selection if error
                 if self.update_selected_rule_button: self.update_selected_rule_button.config(state=tk.DISABLED)
        else:
             # Ensure update button is disabled if nothing was selected
             if self.update_selected_rule_button: self.update_selected_rule_button.config(state=tk.DISABLED)

    # --- Event Handlers ---
    def _handle_listbox_click(self, event):
        """Handles left-click release in the rule listbox to allow deselection."""
        if not self.rule_listbox:
            return

        # Use nearest and bbox to check if click was outside items
        clicked_index = self.rule_listbox.nearest(event.y)
        item_bbox = self.rule_listbox.bbox(clicked_index)

        clicked_outside = False
        if item_bbox is None:
            # Clicked in a completely empty listbox
            clicked_outside = True
        else:
            # Check if the y-coordinate is outside the item's bounding box
            item_y, item_height = item_bbox[1], item_bbox[3]
            if not (item_y <= event.y < item_y + item_height):
                clicked_outside = True

        if clicked_outside:
            current_selection = self.rule_listbox.curselection()
            if current_selection: # Only clear if something was selected
                self.app.log_message("Listbox click in empty space (using nearest/bbox), clearing selection.", "DEBUG")
                self.rule_listbox.selection_clear(0, tk.END)
                # Trigger the same actions as clearing selection normally
                self.on_rule_select() # Call this to clear inputs and button state

    # Note: _power_type_to_string removed as logic incorporated directly in _lookup_spell_info

    # Note: _power_type_to_string removed as logic incorporated directly in _lookup_spell_info 

    def _remove_selected_condition(self):
        """Removes the selected condition from the internal list and the conditions_listbox."""
        if not hasattr(self, 'conditions_listbox') or not self.conditions_listbox:
            self.app.log_message("Cannot remove condition: Conditions listbox not ready.", "ERROR")
            return

        selected_indices = self.conditions_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Selection Error", "Select a condition to remove from the 'Current Rule Conditions' list.")
            return

        index_to_remove = selected_indices[0]

        try:
            # Remove from the internal list first
            removed_condition = self._current_rule_conditions.pop(index_to_remove)
            # Remove from the listbox display
            self.conditions_listbox.delete(index_to_remove)
            self.app.log_message(f"Removed condition: {removed_condition}", "DEBUG")
        except IndexError:
            self.app.log_message(f"Error removing condition: Index {index_to_remove} out of range for internal list.", "ERROR")
        except Exception as e:
            self.app.log_message(f"Error removing condition: {e}", "ERROR")

    # Note: _power_type_to_string removed as logic incorporated directly in _lookup_spell_info 