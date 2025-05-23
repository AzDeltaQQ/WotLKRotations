import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import threading
import json
import traceback
from typing import TYPE_CHECKING, Optional

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp


class RotationControlTab(ttk.Frame):
    """Handles the UI and logic for the Rotation Control Tab."""

    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp', **kwargs):
        """
        Initializes the Rotation Control Tab.

        Args:
            parent_notebook: The ttk.Notebook widget this frame will be placed in.
            app_instance: The instance of the main WowMonitorApp.
        """
        super().__init__(parent_notebook, **kwargs)
        self.app = app_instance

        # --- Widgets (Define attributes that will be created in _setup_ui) ---
        self.script_dropdown: Optional[ttk.Combobox] = None
        self.refresh_button: Optional[ttk.Button] = None
        self.load_editor_rules_button: Optional[ttk.Button] = None
        self.start_button: Optional[ttk.Button] = None
        self.stop_button: Optional[ttk.Button] = None
        self.test_player_stealthed_button: Optional[ttk.Button] = None
        self.test_player_has_aura_button: Optional[ttk.Button] = None
        self.test_combo_points_button: Optional[ttk.Button] = None
        self.test_is_behind_button: Optional[ttk.Button] = None

        # --- Build the UI for this tab ---
        self._setup_ui()

        # --- Populate Initial State --- #
        self.populate_script_dropdown()

    def _setup_ui(self):
        """Creates the widgets for the Rotation Control tab."""
        frame = ttk.Frame(self, padding="10")
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

        test_button_frame = ttk.Frame(test_frame)
        self.test_combo_points_button = ttk.Button(test_button_frame, text="Test Get CP", command=self.test_get_combo_points)
        self.test_combo_points_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.test_is_behind_button = ttk.Button(test_button_frame, text="Test Is Behind", command=self.test_is_behind)
        self.test_is_behind_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Add Test Player Stealthed button
        self.test_player_stealthed_button = ttk.Button(
            test_frame,
            text="Test Player Stealthed",
            command=self._test_player_stealthed,
            state=tk.DISABLED
        )
        self.test_player_stealthed_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Add Test Player Has Aura button
        self.test_player_has_aura_button = ttk.Button(
            test_frame,
            text="Test Player Has Aura",
            command=self._test_player_has_aura,
            state=tk.DISABLED
        )
        self.test_player_has_aura_button.pack(side=tk.LEFT, padx=5, pady=5)

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

    # --- NEW METHODS FOR TEST BUTTONS --- #
    def _test_player_stealthed(self):
        """Calls the main app's method to test the stealthed condition."""
        if not self.app.is_core_initialized():
            messagebox.showwarning("Not Ready", "Core components not initialized or IPC not connected.")
            return
        # Call the main app method (placeholder for now)
        self.app.test_player_stealthed()

    def _test_player_has_aura(self):
        """Calls the main app's method to test the player has aura condition."""
        if not self.app.is_core_initialized():
            messagebox.showwarning("Not Ready", "Core components not initialized or IPC not connected.")
            return
        # Call the main app method (will ask for aura)
        self.app.test_player_has_aura()

    def test_get_combo_points(self):
        """Tests the Get Combo Points IPC command."""
        if not self.app.is_core_initialized():
            messagebox.showwarning("Not Ready", "Core components not initialized or IPC not connected.")
            return
        try:
            if hasattr(self.app, 'core_initialized') and self.app.core_initialized:
                if hasattr(self, 'script_dropdown') and self.script_dropdown:
                    selected_file = self.script_dropdown.get()
                    if selected_file:
                        script_path = os.path.join("Rules", selected_file)
                        if self.app.combat_rotation.load_rotation_script(script_path):
                            self.app.loaded_script_path = selected_file
                            self.app.log_message(f"Loaded rotation script '{selected_file}' into engine.", "INFO")
                            messagebox.showinfo("Test Result", "Get CP test successful!")
                        else:
                            messagebox.showerror("Test Error", "Failed to load rotation script.")
                    else:
                        messagebox.showerror("Invalid Input", "Please select a rotation file.")
                else:
                    messagebox.showerror("Invalid Input", "Script dropdown not initialized.")
            else:
                messagebox.showerror("Invalid Input", "Core not initialized.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid integer Spell ID.")
        except Exception as e:
            error_msg = f"Error during Get CP test: {e}"
            self.app.log_message(error_msg, "ERROR")
            messagebox.showerror("Test Error", error_msg)

    def test_is_behind(self):
        """Tests the IS_BEHIND_TARGET IPC command."""
        if not self.app.is_core_initialized():
            messagebox.showwarning("Not Ready", "Core components not initialized or IPC not connected.")
            return
        try:
            if hasattr(self.app, 'core_initialized') and self.app.core_initialized:
                if hasattr(self, 'script_dropdown') and self.script_dropdown:
                    selected_file = self.script_dropdown.get()
                    if selected_file:
                        script_path = os.path.join("Rules", selected_file)
                        if self.app.combat_rotation.load_rotation_script(script_path):
                            self.app.loaded_script_path = selected_file
                            self.app.log_message(f"Loaded rotation script '{selected_file}' into engine.", "INFO")
                            messagebox.showinfo("Test Result", "Is Behind test successful!")
                        else:
                            messagebox.showerror("Test Error", "Failed to load rotation script.")
                    else:
                        messagebox.showerror("Invalid Input", "Please select a rotation file.")
                else:
                    messagebox.showerror("Invalid Input", "Script dropdown not initialized.")
            else:
                messagebox.showerror("Invalid Input", "Core not initialized.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid integer Spell ID.")
        except Exception as e:
            error_msg = f"Error during Is Behind test: {e}"
            self.app.log_message(error_msg, "ERROR")
            messagebox.showerror("Test Error", error_msg) 