import tkinter as tk
from tkinter import ttk, messagebox
import os
import threading
import json
import traceback
from typing import TYPE_CHECKING, Optional

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp


class RotationControlTab:
    """Handles the UI and logic for the Rotation Control Tab."""

    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp'):
        """
        Initializes the Rotation Control Tab.

        Args:
            parent_notebook: The ttk.Notebook widget to attach the tab frame to.
            app_instance: The instance of the main WowMonitorApp.
        """
        self.app = app_instance
        self.notebook = parent_notebook

        # Create the main frame for this tab
        self.tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_frame, text='Rotation Control / Test')

        # --- Define Rotation Control specific widgets ---
        self.script_dropdown: Optional[ttk.Combobox] = None
        self.refresh_button: Optional[ttk.Button] = None
        self.load_editor_rules_button: Optional[ttk.Button] = None
        self.start_button: Optional[ttk.Button] = None
        self.stop_button: Optional[ttk.Button] = None
        self.test_cp_button: Optional[ttk.Button] = None

        # --- Build the UI for this tab ---
        self._setup_ui()

        # --- Initial population ---
        # self.populate_script_dropdown() # Moved call to end of _setup_ui

    def _setup_ui(self):
        """Creates the widgets for the Rotation Control tab."""
        frame = ttk.Frame(self.tab_frame, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        control_frame = ttk.LabelFrame(frame, text="Rotation Control", padding="10")
        control_frame.pack(pady=10, fill=tk.X)

        script_frame = ttk.Frame(control_frame)
        script_frame.pack(fill=tk.X, pady=5)
        ttk.Label(script_frame, text="Load Rotation File:").pack(side=tk.LEFT, padx=5)
        self.script_dropdown = ttk.Combobox(script_frame, textvariable=self.app.script_var, state="readonly")
        self.script_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.script_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_selected_rotation_file())
        self.refresh_button = ttk.Button(script_frame, text="Refresh", command=self.populate_script_dropdown)
        self.refresh_button.pack(side=tk.LEFT, padx=5)

        self.load_editor_rules_button = ttk.Button(control_frame, text="Load Rules from Editor", command=self.app.load_rules_from_editor)
        self.load_editor_rules_button.pack(pady=5, fill=tk.X)

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=10, fill=tk.X)
        self.start_button = ttk.Button(button_frame, text="Start Rotation", command=self.app.start_rotation, state=tk.DISABLED)
        self.start_button.pack(side=tk.LEFT, expand=True, padx=5)
        self.stop_button = ttk.Button(button_frame, text="Stop Rotation", command=self.app.stop_rotation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, expand=True, padx=5)

        test_frame = ttk.LabelFrame(frame, text="DLL/IPC Tests", padding="10")
        test_frame.pack(pady=10, fill=tk.X)

        self.test_cp_button = ttk.Button(
            test_frame,
            text="Test Get Combo Points",
            command=self.test_get_combo_points,
            state=tk.DISABLED
        )
        self.test_cp_button.pack(pady=5)

        # self.populate_script_dropdown() # Removed call from here

    def populate_script_dropdown(self):
        """Populates the rotation script dropdown with files from the Rules directory."""
        rules_dir = "Rules"
        try:
            if not os.path.exists(rules_dir): os.makedirs(rules_dir)
            files = sorted([f for f in os.listdir(rules_dir) if f.endswith('.json')])

            if not self.script_dropdown:
                 self.app.log_message("Script dropdown not initialized in RotationControlTab.", "ERROR")
                 return

            if files:
                self.script_dropdown['values'] = files
                self.app.script_var.set(files[0])
                self.script_dropdown.config(state="readonly")
            else:
                self.script_dropdown['values'] = []
                self.app.script_var.set(f"No *.json files found in {rules_dir}/")
                self.script_dropdown.config(state=tk.DISABLED)
        except Exception as e:
            self.app.log_message(f"Error populating rotation file dropdown: {e}", "ERROR")
            if self.script_dropdown:
                self.script_dropdown['values'] = []
                self.app.script_var.set("Error loading rotation files")
                self.script_dropdown.config(state=tk.DISABLED)

        self.app._update_button_states()

    def load_selected_rotation_file(self):
        """Loads the selected rotation file (.json) into the combat engine."""
        if self.app.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before loading a new file.")
            return
        if not self.app.combat_rotation:
             messagebox.showerror("Error", "Combat Rotation engine not initialized.")
             return

        selected_file = self.app.script_var.get()
        rules_dir = "Rules"
        if selected_file and not selected_file.startswith("No ") and not selected_file.startswith("Error "):
            file_path = os.path.join(rules_dir, selected_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        loaded_rules = json.load(f)
                    if not isinstance(loaded_rules, list):
                        raise ValueError("Invalid format: JSON root must be a list of rules.")

                    self.app.combat_rotation.load_rotation_rules(loaded_rules)

                    if hasattr(self.app.combat_rotation, 'clear_lua_script'):
                        self.app.combat_rotation.clear_lua_script()
                    else:
                        self.app.log_message("Warning: CombatRotation has no clear_lua_script method.", "WARN")

                    self.app.log_message(f"Loaded and activated {len(loaded_rules)} rules from: {file_path}", "INFO")
                    messagebox.showinfo("Rotation Loaded", f"Loaded and activated {len(loaded_rules)} rules from file:\n{selected_file}")
                    self.app._update_button_states()

                except json.JSONDecodeError as e:
                    self.app.log_message(f"Error decoding JSON from {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
                except ValueError as e:
                    self.app.log_message(f"Error validating rules file {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
                except Exception as e:
                    self.app.log_message(f"Error loading rules from {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")
            else:
                 messagebox.showerror("Load Error", f"Rotation file not found:\n{file_path}")
                 self.app.script_var.set("")
                 self.populate_script_dropdown()
        else:
            messagebox.showwarning("Load Warning", "Please select a valid rotation file.")
        self.app._update_button_states()

    def test_get_combo_points(self):
        """Initiates the process to get combo points from the target (uses app's core components)."""
        if not self.app.game or not self.app.game.is_ready():
            messagebox.showwarning("Not Ready", "Game interface not connected or process not found.")
            return
        if not self.app.om:
             messagebox.showwarning("Not Ready", "Object Manager not initialized.")
             return

        try:
            current_target = self.app.om.target
            if not current_target:
                self.app.log_message("No target detected via direct memory read (om.target).", "INFO")
                messagebox.showinfo("No Target", "You must have a target selected to get combo points.")
                return
            else:
                self.app.log_message(f"Target detected via direct memory read: {current_target.guid:#X}", "DEBUG")
        except Exception as e:
            self.app.log_message(f"Error checking target via om.target: {e}", "ERROR")
            traceback.print_exc()
            messagebox.showerror("Error", f"Error checking target status: {e}")
            return

        self.app.log_message("Target confirmed, starting combo point fetch thread...", "INFO")

        if self.test_cp_button and self.test_cp_button.winfo_exists():
            self.test_cp_button.config(state=tk.DISABLED)
        else:
             self.app.log_message("Warning: Combo points button 'test_cp_button' not found in RotationControlTab.", "WARNING")

        thread = threading.Thread(target=self.app._fetch_combo_points_thread, args=(self.test_cp_button,), daemon=True)
        thread.start() 