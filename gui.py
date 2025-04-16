import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog, simpledialog
import threading
import time
import configparser
import os
import json
import sys
import math
import traceback
from typing import Optional, List, Dict, Any, TYPE_CHECKING
import logging
import sv_ttk # Import the theme library

# Project Modules
from memory import MemoryHandler, PROCESS_NAME
from object_manager import ObjectManager
from gameinterface import GameInterface
from wow_object import WowObject
from combat_rotation import CombatRotation
from rules import Rule # Keep Rule for potential type hints if needed
from targetselector import TargetSelector
from combat_log_reader import CombatLogReader # <-- Import CombatLogReader

# Import Tab Handlers
from gui.monitor_tab import MonitorTab
from gui.rotation_control_tab import RotationControlTab
from gui.rotation_editor_tab import RotationEditorTab
from gui.lua_runner_tab import LuaRunnerTab
from gui.log_tab import LogTab # LogRedirector is now defined within log_tab.py
from gui.combat_log_tab import CombatLogTab # <-- Import CombatLogTab

# Use TYPE_CHECKING for the tab handler types to avoid runtime circular dependency issues
if TYPE_CHECKING:
    # These imports are only for type analysis, not runtime execution
    from gui.monitor_tab import MonitorTab
    from gui.rotation_control_tab import RotationControlTab
    from gui.rotation_editor_tab import RotationEditorTab
    from gui.lua_runner_tab import LuaRunnerTab
    from gui.log_tab import LogTab
    from gui.combat_log_tab import CombatLogTab # <-- Add CombatLogTab type hint

# Constants
UPDATE_INTERVAL_MS = 250 # How often to update GUI data (milliseconds)
CORE_INIT_RETRY_INTERVAL_S = 5 # How often to retry core initialization
CORE_INIT_RETRY_INTERVAL_FAST = 1 # How often to attempt core initialization if disconnected
CORE_INIT_RETRY_INTERVAL_SLOW = 10 # How often to attempt core initialization if connected

# Style Definitions (Shared styles accessed via self.app in tabs)
DEFAULT_FONT = ('TkDefaultFont', 9)
BOLD_FONT = ('TkDefaultFont', 9, 'bold')
CODE_FONT = ("Consolas", 10)

LISTBOX_STYLE = {
    "bg": "#2E2E2E",
    "fg": "#E0E0E0",
    "font": DEFAULT_FONT,
    "selectbackground": "#005A9E",
    "selectforeground": "#FFFFFF",
    "borderwidth": 0,
    "highlightthickness": 1,
    "highlightcolor": "#555555"
}
LOG_TEXT_STYLE = {
    "bg": "#1E1E1E",
    "fg": "#D4D4D4",
    "font": DEFAULT_FONT,
    "wrap": tk.WORD,
    "insertbackground": "#FFFFFF"
}
LUA_OUTPUT_STYLE = LOG_TEXT_STYLE.copy()
LUA_OUTPUT_STYLE["font"] = CODE_FONT

LOG_TAGS = {
    "DEBUG": {"foreground": "#888888"},
    "INFO": {"foreground": "#D4D4D4"},
    "WARN": {"foreground": "#FFA500"},
    "ERROR": {"foreground": "#FF6B6B", "font": BOLD_FONT},
    "ACTION": {"foreground": "#569CD6"},
    "RESULT": {"foreground": "#60C060"},
    "ROTATION": {"foreground": "#C586C0"}
}


class WowMonitorApp:
    """Main application class for the WoW Monitor and Rotation Engine GUI."""

    def __init__(self, root):
        self.root = root
        self.root.title("PyWoW Bot Interface") # Set title early

        # --- Style Application --- (Store on instance for tabs to access)
        self.DEFAULT_FONT = DEFAULT_FONT
        self.BOLD_FONT = BOLD_FONT
        self.CODE_FONT = CODE_FONT
        self.rule_listbox_style = LISTBOX_STYLE
        self.LOG_TEXT_STYLE = LOG_TEXT_STYLE
        self.LUA_OUTPUT_STYLE = LUA_OUTPUT_STYLE
        self.LOG_TAGS = LOG_TAGS

        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            # Use original stderr for pre-logging issues
            print("Warning: 'clam' theme not available, using default.", file=sys.stderr)

        # --- Load Config First ---
        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        # Use _load_config to handle potential errors
        self._load_config()

        # --- GUI Setup ---
        self.root.title("PyWoW Bot Interface")
        default_geometry = "750x600+150+150"
        geometry = self.config.get('GUI', 'geometry', fallback=default_geometry)
        self.root.geometry(geometry)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        sv_ttk.set_theme("dark")

        # --- Notebook (Tabs) ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # --- Status Bar ---
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var.set("Initializing...")

        # --- Initialize SHARED GUI Variables --- #
        # These StringVars are used by multiple tabs or updated by the main app loop
        self.player_name_var = tk.StringVar(value="N/A")
        self.player_level_var = tk.StringVar(value="N/A")
        self.player_hp_var = tk.StringVar(value="N/A")
        self.player_energy_var = tk.StringVar(value="N/A")
        self.player_pos_var = tk.StringVar(value="N/A")
        self.player_status_var = tk.StringVar(value="N/A")
        self.target_name_var = tk.StringVar(value="N/A")
        self.target_level_var = tk.StringVar(value="N/A")
        self.target_hp_var = tk.StringVar(value="N/A")
        self.target_energy_var = tk.StringVar(value="N/A")
        self.target_pos_var = tk.StringVar(value="N/A")
        self.target_status_var = tk.StringVar(value="N/A")
        self.target_dist_var = tk.StringVar(value="N/A")
        self.script_var = tk.StringVar() # For rotation control dropdown

        # Shared definitions for Rotation Editor dropdowns
        self.rule_conditions = [
            "None", "Target Exists", "Target Attackable", "Player Is Casting",
            "Target Is Casting", "Player Is Moving", "Player Is Stealthed",
            "Is Spell Ready", "Target HP % < X", "Target HP % > X",
            "Target HP % Between X-Y", "Player HP % < X", "Player HP % > X",
            "Player Rage >= X", "Player Energy >= X", "Player Mana % < X",
            "Player Mana % > X", "Player Combo Points >= X",
            "Target Distance < X", "Target Distance > X", "Target Has Aura",
            "Target Missing Aura", "Player Has Aura", "Player Missing Aura",
            "Player Is Behind Target",
        ]
        self.rule_actions = ["Spell", "Macro", "Lua"]
        self.rule_targets = ["target", "player", "focus", "pet", "mouseover"]

        # Shared StringVars for Rotation Editor inputs
        self.action_var = tk.StringVar(value="Spell")
        self.spell_id_var = tk.StringVar()
        self.target_var = tk.StringVar(value="target")
        self.condition_var = tk.StringVar(value="None")
        self.condition_value_x_var = tk.StringVar()
        self.condition_value_y_var = tk.StringVar()
        self.condition_text_var = tk.StringVar()
        self.int_cd_var = tk.StringVar(value="0.0")
        self.lua_code_var = tk.StringVar()
        self.macro_text_var = tk.StringVar()

        # This list holds the rules CURRENTLY IN THE EDITOR, not the engine
        self.rotation_rules: List[Dict[str, Any]] = []

        # --- Initialize Core Components FIRST --- #
        self.mem: Optional[MemoryHandler] = None
        self.om: Optional[ObjectManager] = None
        self.game: Optional[GameInterface] = None
        self.combat_rotation: Optional[CombatRotation] = None
        self.target_selector: Optional[TargetSelector] = None
        self.combat_log_reader: Optional[CombatLogReader] = None
        self.rotation_running = False
        self.loaded_script_path = self.config.get('Rotation', 'last_script', fallback=None)
        self.update_job = None
        self.is_closing = False
        self.core_initialized = False # Flag to track if core init succeeded

        # --- Instantiate Tab Handlers (Depend on Core Components / App State) --- #
        # Provide type hints using TYPE_CHECKING block above
        self.monitor_tab_handler: 'MonitorTab' = MonitorTab(self.notebook, self)
        self.rotation_control_tab_handler: 'RotationControlTab' = RotationControlTab(self.notebook, self)
        self.rotation_editor_tab_handler: 'RotationEditorTab' = RotationEditorTab(self.notebook, self)
        self.lua_runner_tab_handler: 'LuaRunnerTab' = LuaRunnerTab(self.notebook, self)
        # LogTab creates its own LogRedirector and starts redirection internally
        self.log_tab_handler: 'LogTab' = LogTab(self.notebook, self)
        self.combat_log_tab_handler: 'CombatLogTab' = CombatLogTab(self.notebook, self) # <-- Instantiate CombatLogTab

        # --- WoW Path --- #
        self.wow_path = self._get_wow_path()

        # --- Setup GUI states --- #
        self.rotation_thread: Optional[threading.Thread] = None
        self.stop_rotation_flag = threading.Event()
        self.core_init_attempting = False
        self.last_core_init_attempt = 0.0

        # --- Populate Initial State --- #
        # Dropdown is populated by RotationControlTab init
        # Initial rule list display is handled by RotationEditorTab init (if needed)
        # Populate script dropdown AFTER handler is created and core_initialized exists
        if hasattr(self, 'rotation_control_tab_handler') and self.rotation_control_tab_handler:
            self.rotation_control_tab_handler.populate_script_dropdown()

        self._update_button_states() # Update based on initial state

        # --- Start Update Loop --- #
        # Ensure LogTab handler is available before logging
        if hasattr(self, 'log_tab_handler') and self.log_tab_handler:
             self.log_message(f"Starting update loop with interval: {UPDATE_INTERVAL_MS}ms", "INFO")
        else:
             print("ERROR: LogTab handler not ready, cannot log startup message.", file=sys.stderr)
        self.update_data() # Start the main update cycle

        # --- Add Tabs to Notebook (Original location) ---
        # Test: Add a simple frame first # REMOVED SECTION
        # try:
        #     test_frame = ttk.Frame(self.notebook)
        #     self.notebook.add(test_frame, text="Test")
        #     print("Successfully added test frame.")
        # except Exception as e:
        #     print(f"ERROR adding test frame: {e}")
        #     # If this fails, the problem is more fundamental

        self.notebook.add(self.monitor_tab_handler, text='Monitor')
        self.notebook.add(self.rotation_control_tab_handler, text='Rotation Control / Test')
        self.notebook.add(self.rotation_editor_tab_handler, text='Rotation Editor')
        self.notebook.add(self.lua_runner_tab_handler, text='Lua Runner')
        self.notebook.add(self.log_tab_handler, text='Log')
        self.notebook.add(self.combat_log_tab_handler, text='Combat Log') # <-- Add CombatLogTab to notebook

    # --- Logging Method --- #
    def log_message(self, message, tag="INFO"):
        """Logs a message via the LogRedirector in LogTab."""
        if hasattr(self, 'log_tab_handler') and self.log_tab_handler and \
           hasattr(self.log_tab_handler, 'log_redirector') and self.log_tab_handler.log_redirector:
            try:
                self.log_tab_handler.log_redirector.write(message, tag)
            except Exception as e:
                print(f"CRITICAL: Failed to write log via redirector: {e}", file=sys.stderr)
                print(f"Original Msg: [{tag}] {message}", file=sys.stderr)
        else:
            print(f"[{tag}] {message} (LogRedirector not ready)",
                  file=sys.stderr if tag in ["ERROR", "WARN"] else sys.stdout)

    # --- Config, Path, Core Init, Rotation Control Methods --- #

    def _get_wow_path(self):
        # (Implementation remains unchanged)
        try:
            path = self.config.get('Settings', 'WowPath', fallback=None)
            if path and os.path.isdir(path):
                # self.log_message(f"Read WowPath from {self.config_file}: {path}", "INFO") # Logged later if successful
                return path
            elif path:
                # Use print as logging might not be ready
                print(f"Warning: WowPath '{path}' in {self.config_file} is not a valid directory.", file=sys.stderr)
            default_path = "C:/Users/Jacob/Desktop/World of Warcraft 3.3.5a"
            print(f"Using default WoW path: {default_path}", file=sys.stdout)
            if os.path.isdir(default_path):
                return default_path
            else:
                print(f"Error: Default WoW path '{default_path}' is not valid.", file=sys.stderr)
                return None
        except Exception as e:
            print(f"Error getting WoW path: {e}. Using fallback.", file=sys.stderr)
            fallback_path = "C:/Users/Jacob/Desktop/World of Warcraft 3.3.5a"
            return fallback_path if os.path.isdir(fallback_path) else None

    def _show_error_and_exit(self, message):
        # (Implementation remains unchanged)
        self.log_message(message, "ERROR") # Attempt to log
        try:
            messagebox.showerror("Fatal Initialization Error", message)
            self.root.destroy()
        except Exception as e:
             print(f"CRITICAL GUI ERROR during error display: {e}", file=sys.stderr)
             os._exit(1)

    def _load_config(self):
        # (Implementation remains unchanged)
        try:
            if not self.config.has_section('GUI'): self.config.add_section('GUI')
            if not self.config.has_section('Rotation'): self.config.add_section('Rotation')
            self.loaded_script_path = self.config.get('Rotation', 'last_script', fallback=None)
            # Load geometry if needed, handled in __init__ currently
        except configparser.Error as e:
            print(f"Error parsing config file {self.config_file}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Error loading config settings: {e}", file=sys.stderr)

    def _save_config(self):
        # (Implementation remains unchanged)
        try:
            if not self.config.has_section('GUI'): self.config.add_section('GUI')
            if self.root.winfo_exists():
                 self.config.set('GUI', 'geometry', self.root.geometry())
            if not self.config.has_section('Rotation'): self.config.add_section('Rotation')
            self.config.set('Rotation', 'last_script', self.loaded_script_path if self.loaded_script_path else "")
            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
            self.log_message("Configuration saved.", "INFO") # Log success
        except configparser.Error as e:
             self.log_message(f"Error writing config file {self.config_file}: {e}", "ERROR")
        except Exception as e:
            self.log_message(f"Error saving config file '{self.config_file}': {e}", "ERROR")

    def connect_and_init_core(self) -> bool:
        """Attempts core component initialization. Runs in a thread."""
        # (Implementation remains unchanged, uses self.log_message)
        success = False
        log_prefix = "Init Core:"
        try:
            self.log_message(f"{log_prefix} Starting...", "DEBUG")
            # 1. Memory Handler
            if not self.mem or not self.mem.is_attached():
                self.log_message(f"{log_prefix} Initializing MemoryHandler...", "DEBUG")
                self.mem = MemoryHandler()
                if not self.mem.is_attached():
                    self.log_message(f"{log_prefix} Failed attach ({PROCESS_NAME}). WoW running?", "ERROR")
                    return False
                self.log_message(f"{log_prefix} Attached to WoW process.", "INFO")

                # 1.5 Initialize Combat Log Reader (Needs MemoryHandler)
                if not self.combat_log_reader:
                    self.log_message(f"{log_prefix} Initializing CombatLogReader...", "DEBUG")
                    # Pass self (WowMonitorApp instance) for logging
                    self.combat_log_reader = CombatLogReader(self.mem, self)
                    if self.combat_log_reader.initialized:
                        self.log_message(f"{log_prefix} CombatLogReader initialized.", "INFO")
                    else:
                        self.log_message(f"{log_prefix} CombatLogReader failed initialization.", "WARN")
                        # Don't fail core init just because log reader failed, but log it.

            # 2. Object Manager
            if not self.om or not self.om.is_ready():
                self.log_message(f"{log_prefix} Initializing ObjectManager...", "DEBUG")
                if not self.mem: return False # Should not happen if step 1 passed
                self.om = ObjectManager(self.mem)
                if not self.om.is_ready():
                    self.log_message(f"{log_prefix} Failed init ObjectManager. Offsets ok?", "ERROR")
                    return False
                self.log_message(f"{log_prefix} ObjectManager initialized.", "INFO")
            # 3. Game Interface
            if not self.game:
                self.log_message(f"{log_prefix} Initializing GameInterface...", "DEBUG")
                if not self.mem: return False
                self.game = GameInterface(self.mem)
                self.log_message(f"{log_prefix} GameInterface object created.", "INFO")
            # 4. IPC Pipe Connection
            if not self.game.is_ready():
                self.log_message(f"{log_prefix} Attempting IPC Pipe connection...", "DEBUG")
                if self.game.connect_pipe():
                     self.log_message(f"{log_prefix} IPC Pipe connected.", "INFO")
                else:
                     self.log_message(f"{log_prefix} IPC Pipe connect FAILED. DLL injected?", "ERROR")
            else: self.log_message(f"{log_prefix} IPC Pipe already connected.", "DEBUG")
            # 5. Target Selector
            if not self.target_selector:
                self.log_message(f"{log_prefix} Initializing TargetSelector...", "DEBUG")
                if self.om and self.om.is_ready():
                    self.target_selector = TargetSelector(self.om)
                    self.log_message(f"{log_prefix} TargetSelector initialized.", "INFO")
                else: self.log_message(f"{log_prefix} Skip TargetSelector init (OM not ready).", "WARN")
            # 6. Combat Rotation
            if not self.combat_rotation:
                 self.log_message(f"{log_prefix} Initializing CombatRotation...", "DEBUG")
                 if self.mem and self.om and self.game:
                     # Pass self.log_message from the app
                     self.combat_rotation = CombatRotation(self.mem, self.om, self.game, self.log_message)
                     self.log_message(f"{log_prefix} CombatRotation engine initialized.", "INFO")
                 else: self.log_message(f"{log_prefix} Skip CombatRotation init (core missing).", "WARN")

            success = bool(self.mem and self.mem.is_attached() and self.om and self.om.is_ready())
            self.log_message(f"{log_prefix} Components check {'passed' if success else 'failed'}.", "INFO" if success else "ERROR")

        except Exception as e:
            self.log_message(f"{log_prefix} EXCEPTION: {e}", "ERROR")
            traceback.print_exc() # Log via redirector
            success = False
        finally:
             self.log_message(f"{log_prefix} Finalizing attempt (Success: {success}).", "DEBUG")
             if self.root.winfo_exists():
                  self.root.after(0, self._finalize_core_init_attempt, success)
        # Return value not used by caller thread

    def _finalize_core_init_attempt(self, success: bool):
        """Called in main thread after core init attempt finishes."""
        # (Implementation remains unchanged)
        self.core_init_attempting = False
        self.core_initialized = success
        if success:
            self.log_message("Core initialization successful (finalized).", "INFO")
        else:
            self.log_message("Core initialization failed (finalized).", "WARN")
        self._update_button_states()

    def start_rotation(self):
        """Starts the combat rotation thread if conditions are met."""
        # (Implementation remains unchanged)
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
            self.log_message("Rotation already running.", "WARN")
            return
        if not self.combat_rotation:
            self.log_message("Engine not ready.", "ERROR"); messagebox.showerror("Error", "Engine not ready.")
            return
        if not self.core_initialized or not self.mem or not self.om or not self.game:
             self.log_message("Core not ready.", "ERROR"); messagebox.showerror("Error", "Core not ready.")
             return
        if not self.game.is_ready():
             self.log_message("IPC not ready.", "ERROR"); messagebox.showerror("Error", "IPC not ready.")
             return

        rules_loaded = bool(self.combat_rotation.rotation_rules)
        script_loaded = bool(self.combat_rotation.lua_script_content)
        if not rules_loaded and not script_loaded:
            self.log_message("No rotation loaded in engine.", "WARN")
            messagebox.showwarning("Warning", "No rotation loaded in engine.")
            return

        log_msg = f"Starting rotation using {len(self.combat_rotation.rotation_rules)} rules." if rules_loaded else "Starting rotation using Lua script."
        self.log_message(log_msg, "INFO")

        self.stop_rotation_flag.clear()
        self.rotation_thread = threading.Thread(target=self._run_rotation_loop, daemon=True)
        self.rotation_thread.start()
        self.log_message("Rotation thread started.", "INFO")
        self._update_button_states()

    def stop_rotation(self):
        """Signals the combat rotation thread to stop."""
        # (Implementation remains unchanged)
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
            self.log_message("Stopping rotation...", "INFO")
            self.stop_rotation_flag.set()
        else:
            self.log_message("Rotation not running.", "INFO")
        # State update happens in callback

    def _run_rotation_loop(self):
        """The main loop for the combat rotation thread."""
        # (Implementation remains unchanged)
        loop_count = 0
        while not self.stop_rotation_flag.is_set():
            start_time = time.monotonic()
            try:
                if self.core_initialized and self.combat_rotation and self.game and self.game.is_ready():
                    self.combat_rotation.run()
                else:
                    if loop_count == 0: # Log skip reason only once
                        reason = "Core not initialized" if not self.core_initialized else \
                                 "Engine missing" if not self.combat_rotation else \
                                 "IPC not ready" if not (self.game and self.game.is_ready()) else "Unknown"
                        print(f"[Rotation Loop] Skipping run: {reason}.", file=sys.stderr)
                    time.sleep(0.5)
                    continue
                loop_count += 1
                elapsed = time.monotonic() - start_time
                sleep_time = max(0.01, 0.1 - elapsed)
                time.sleep(sleep_time)
            except Exception as e:
                self.log_message(f"Error in rotation loop (Loop {loop_count}): {e}", "ERROR")
                traceback.print_exc()
                print(f"[THREAD LOOP {loop_count}] FATAL EXCEPTION: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                self.stop_rotation_flag.set()
                break
        self.log_message("Rotation thread finishing.", "DEBUG")
        if self.root.winfo_exists():
            self.root.after(0, self._on_rotation_thread_exit)

    def _on_rotation_thread_exit(self):
        """Callback executed in the main GUI thread after the rotation thread exits."""
        # (Implementation remains unchanged)
        self.rotation_thread = None
        self.log_message("Rotation stopped.", "INFO")
        self._update_button_states()

    def load_rules_from_editor(self):
        """Loads rules from the editor list (self.rotation_rules) into the engine."""
        # (Implementation remains unchanged)
        if self.rotation_running:
            messagebox.showerror("Error", "Stop rotation before loading rules.")
            return
        if not self.combat_rotation:
             messagebox.showerror("Error", "Engine not initialized.")
             return
        if not self.rotation_rules:
            messagebox.showwarning("No Rules", "No rules in editor to load.")
            return
        try:
            self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.log_message(f"Loaded {len(self.rotation_rules)} rule(s) from editor into engine.", "INFO")
            if hasattr(self.combat_rotation, 'clear_lua_script'):
                self.combat_rotation.clear_lua_script()
            self.script_var.set("") # Clear file dropdown
            messagebox.showinfo("Rules Loaded", f"{len(self.rotation_rules)} editor rule(s) active.")
            self._update_button_states()
        except Exception as e:
            error_msg = f"Error loading editor rules: {e}"
            self.log_message(error_msg, "ERROR")
            traceback.print_exc()
            messagebox.showerror("Load Error", error_msg)

    # --- GUI Update Methods --- #

    def _update_button_states(self):
        """Updates the state of buttons based on application state."""
        # (Implementation updated to access buttons via handlers)
        core_ready = self.is_core_initialized()
        ipc_ready = core_ready and self.game and self.game.is_ready()
        # Safely check if combat_rotation exists before accessing its attributes
        rules_in_engine = bool(hasattr(self, 'combat_rotation') and self.combat_rotation and self.combat_rotation.rotation_rules)
        script_in_engine = bool(hasattr(self, 'combat_rotation') and self.combat_rotation and self.combat_rotation.lua_script_content)
        rotation_loadable = rules_in_engine or script_in_engine
        # Safely check if rotation_thread exists before accessing it
        is_rotation_running = hasattr(self, 'rotation_thread') and self.rotation_thread is not None and self.rotation_thread.is_alive()

        # --- Update buttons via tab handlers --- #
        # Rotation Control Tab
        if hasattr(self, 'rotation_control_tab_handler') and self.rotation_control_tab_handler:
            rct_handler = self.rotation_control_tab_handler
            # Check if widgets exist on the handler before accessing state
            if hasattr(rct_handler, 'start_button') and rct_handler.start_button:
                rct_handler.start_button['state'] = tk.NORMAL if ipc_ready and rotation_loadable and not is_rotation_running else tk.DISABLED
            if hasattr(rct_handler, 'stop_button') and rct_handler.stop_button:
                rct_handler.stop_button['state'] = tk.NORMAL if is_rotation_running else tk.DISABLED
            if hasattr(rct_handler, 'load_editor_rules_button') and rct_handler.load_editor_rules_button:
                 rct_handler.load_editor_rules_button['state'] = tk.NORMAL if core_ready and not is_rotation_running else tk.DISABLED
            if hasattr(rct_handler, 'script_dropdown') and rct_handler.script_dropdown:
                 rct_handler.script_dropdown['state'] = 'readonly' if core_ready and not is_rotation_running else tk.DISABLED
            if hasattr(rct_handler, 'refresh_button') and rct_handler.refresh_button:
                rct_handler.refresh_button['state'] = tk.NORMAL if core_ready and not is_rotation_running else tk.DISABLED

        # Lua Runner Tab
        if hasattr(self, 'lua_runner_tab_handler') and self.lua_runner_tab_handler:
            lr_handler = self.lua_runner_tab_handler
            if hasattr(lr_handler, 'run_lua_button') and lr_handler.run_lua_button:
                lr_handler.run_lua_button['state'] = tk.NORMAL if ipc_ready else tk.DISABLED

        # Rotation Editor Tab (Pass state down to handler method if needed)
        if hasattr(self, 'rotation_editor_tab_handler') and self.rotation_editor_tab_handler:
             # Let the editor tab manage its own button states based on core/ipc/running status
             # We could pass the relevant status flags if needed:
             # self.rotation_editor_tab_handler.update_button_states(core_ready, ipc_ready, is_rotation_running)
             pass # Assuming editor tab manages its state internally for now

        # --- Update new buttons via tab handlers --- #
        if hasattr(self, 'rotation_control_tab_handler') and self.rotation_control_tab_handler:
            rct_handler = self.rotation_control_tab_handler
            if hasattr(rct_handler, 'test_player_stealthed_button') and rct_handler.test_player_stealthed_button:
                 rct_handler.test_player_stealthed_button['state'] = tk.NORMAL if ipc_ready else tk.DISABLED
            if hasattr(rct_handler, 'test_player_has_aura_button') and rct_handler.test_player_has_aura_button:
                 rct_handler.test_player_has_aura_button['state'] = tk.NORMAL if ipc_ready else tk.DISABLED

    def update_data(self):
        """Periodically updates displayed data and core status."""
        # (Implementation updated to call monitor tab handler)
        if self.is_closing: return
        core_ready = False; status_text = "Initializing..."

        # --- Core Initialization/Check --- #
        if not self.core_initialized:
             status_text = "Connecting..."
             if not self.core_init_attempting:
                 now = time.time(); retry_interval = CORE_INIT_RETRY_INTERVAL_FAST
                 if now > self.last_core_init_attempt + retry_interval:
                      self.log_message(f"Attempting core initialization...", "INFO")
                      self.core_init_attempting = True; self.last_core_init_attempt = now
                      threading.Thread(target=self.connect_and_init_core, daemon=True).start()
                 else:
                      wait_time = int(retry_interval - (now - self.last_core_init_attempt))
                      status_text = f"Conn. failed. Retry in {max(0, wait_time)}s..."
        else: # Core initialized, check health
             if not (self.mem and self.mem.is_attached() and self.om and self.om.is_ready() and self.game):
                 self.log_message("Core component check failed. Resetting.", "WARN")
                 self.core_initialized = False; status_text = "Conn. Lost. Reconnecting..."
                 # TODO: Add component reset logic here if needed
             else:
                 pipe_ready = self.game.is_ready()
                 core_ready = True; status_text = f"Connected {'(IPC Ready)' if pipe_ready else '(IPC Failed)'}"
                 try:
                     if self.om: self.om.refresh()
                 except Exception as e:
                     self.log_message(f"Error OM refresh: {e}", "ERROR")
                     traceback.print_exc(); core_ready = False; self.core_initialized = False
                     status_text = "Error Refreshing OM"

        # --- Update Monitor Tab Data (using StringVars) --- #
        # (Logic remains the same)
        if core_ready and self.om and self.om.local_player:
            player = self.om.local_player; p_name = player.get_name() or "?"
            status_text += f" | Player: {p_name} Lvl:{player.level}"
            self.player_name_var.set(p_name); self.player_level_var.set(str(player.level))
            self.player_hp_var.set(self.format_hp_energy(player.health, player.max_health))
            self.player_energy_var.set(self.format_hp_energy(player.energy, player.max_energy, player.power_type))
            self.player_pos_var.set(f"({player.x_pos:.1f}, {player.y_pos:.1f}, {player.z_pos:.1f})")
            p_flags = [f for f, flag in [("Casting", getattr(player, 'is_casting', False)),
                                         ("Channeling", getattr(player, 'is_channeling', False)),
                                         ("Dead", getattr(player, 'is_dead', False)),
                                         ("Stunned", getattr(player, 'is_stunned', False))] if flag]
            self.player_status_var.set(", ".join(p_flags) if p_flags else "Idle")
        else:
            self.player_name_var.set("N/A"); self.player_level_var.set("N/A"); self.player_hp_var.set("N/A")
            self.player_energy_var.set("N/A"); self.player_pos_var.set("N/A"); self.player_status_var.set("N/A")

        if core_ready and self.om and self.om.target:
            target = self.om.target; t_name = target.get_name() or "?"
            dist = self.calculate_distance(target); dist_str = f"{dist:.1f}y" if dist >= 0 else "N/A"
            status_text += f" | Target: {t_name} ({dist_str})"
            self.target_name_var.set(t_name); self.target_level_var.set(str(target.level))
            self.target_hp_var.set(self.format_hp_energy(target.health, target.max_health))
            if target.power_type == WowObject.POWER_MANA and getattr(target, 'max_energy', 0) > 0:
                self.target_energy_var.set(self.format_hp_energy(target.energy, target.max_energy, target.power_type))
            else: self.target_energy_var.set("N/A")
            self.target_pos_var.set(f"({target.x_pos:.1f}, {target.y_pos:.1f}, {target.z_pos:.1f})")
            t_flags = [f for f, flag in [("Casting", getattr(target, 'is_casting', False)),
                                         ("Channeling", getattr(target, 'is_channeling', False)),
                                         ("Dead", getattr(target, 'is_dead', False)),
                                         ("Stunned", getattr(target, 'is_stunned', False))] if flag]
            self.target_status_var.set(", ".join(t_flags) if t_flags else "Idle")
            self.target_dist_var.set(dist_str)
        else:
            self.target_name_var.set("N/A"); self.target_level_var.set("N/A"); self.target_hp_var.set("N/A")
            self.target_energy_var.set("N/A"); self.target_pos_var.set("N/A"); self.target_status_var.set("N/A")
            self.target_dist_var.set("N/A")

        # --- Update Object Tree via MonitorTab handler --- #
        if core_ready and hasattr(self, 'monitor_tab_handler') and self.monitor_tab_handler:
            self.monitor_tab_handler.update_monitor_treeview()

        # --- Read and Display Combat Log Entries --- #
        local_player_found = bool(self.om and self.om.local_player)
        if core_ready and local_player_found and self.combat_log_reader and self.combat_log_reader.initialized and hasattr(self, 'combat_log_tab_handler'):
            entries_found = 0
            try:
                for timestamp, event_struct in self.combat_log_reader.read_new_entries():
                    entries_found += 1
                    self.combat_log_tab_handler.log_event(timestamp, event_struct)

                if entries_found > 0:
                    self.log_message(f"Processed {entries_found} combat log entries this cycle.", "DEBUG")
            except Exception as e:
                self.log_message(f"Error reading/processing combat log: {e}", "ERROR")
        elif core_ready and self.om and not local_player_found:
            self.log_message("Combat log processing skipped: Local player object not yet identified by Object Manager.", "DEBUG")
        elif not (hasattr(self, 'combat_log_reader') and self.combat_log_reader and self.combat_log_reader.initialized):
            pass

        # --- Final Updates --- #
        self.status_var.set(status_text)
        self._update_button_states()
        if self.rotation_thread is not None and not self.rotation_thread.is_alive():
             self.log_message("Rotation thread died unexpectedly. Cleaning up.", "WARN")
             if self.root.winfo_exists(): self.root.after(0, self._on_rotation_thread_exit)
        if not self.is_closing:
             try:
                 if self.root.winfo_exists(): self.update_job = self.root.after(UPDATE_INTERVAL_MS, self.update_data)
             except tk.TclError: self.log_message("Root window destroyed.", "DEBUG"); self.is_closing = True

    def on_closing(self):
        """Handles the application closing sequence."""
        # (Implementation updated to use log_tab_handler)
        if self.is_closing: return
        self.is_closing = True; self.log_message("Closing application...", "INFO")
        if self.update_job: # Cancel pending update
            try:
                self.root.after_cancel(self.update_job)
            except tk.TclError:
                pass # Ignore error if root/job destroyed
            self.update_job = None
        if self.rotation_thread and self.rotation_thread.is_alive(): # Stop rotation thread
             self.log_message("Signaling rotation thread stop...", "INFO")
             self.stop_rotation_flag.set()
             # Optional: self.rotation_thread.join(timeout=0.5)
        if self.game: # Disconnect IPC
            try: self.game.disconnect_pipe(); self.log_message("IPC Pipe disconnected.", "DEBUG")
            except Exception as e: self.log_message(f"Error disconnecting IPC: {e}", "WARN")
        self._save_config() # Save config
        if hasattr(self, 'log_tab_handler') and self.log_tab_handler: # Stop logging
            self.log_message("Stopping log redirection.", "DEBUG")
            self.log_tab_handler.stop_logging()
        print("Cleanup finished. Exiting.") # Final message to original stdout
        try: self.root.destroy() # Destroy window
        except: pass

    # --- Helper Methods (Remain in App) --- #
    def format_hp_energy(self, current, max_val, power_type=-1):
        # (Implementation remains unchanged)
        try:
            current_int = int(current) if current is not None and str(current).isdigit() else 0
            max_int = int(max_val) if max_val is not None and str(max_val).isdigit() else 0
            if max_int <= 0:
                if power_type == WowObject.POWER_ENERGY: max_int = 100
                else: return f"{current_int}/?"
            if max_int == 0: return f"{current_int}/0 (?%)"
            pct = (current_int / max_int) * 100
            return f"{current_int}/{max_int} ({pct:.0f}%)"
        except (ValueError, TypeError) as e:
            logging.warning(f"Format HP/Energy Err: {e} (c={current}, m={max_val}, t={power_type})")
            return f"{str(current) if current is not None else '?'}/{str(max_val) if max_val is not None else '?'} (?%)"

    def calculate_distance(self, obj: Optional[WowObject]) -> float:
        # (Implementation remains unchanged)
        if not self.om or not self.om.local_player or not obj: return -1.0
        player = self.om.local_player; attrs = ['x_pos', 'y_pos', 'z_pos']
        if not all(hasattr(player, a) and getattr(player, a) is not None for a in attrs) or \
           not all(hasattr(obj, a) and getattr(obj, a) is not None for a in attrs):
            return -1.0
        try:
            px, py, pz = float(player.x_pos), float(player.y_pos), float(player.z_pos)
            ox, oy, oz = float(obj.x_pos), float(obj.y_pos), float(obj.z_pos)
            return math.sqrt((px - ox)**2 + (py - oy)**2 + (pz - oz)**2)
        except (TypeError, ValueError) as e:
             logging.error(f"Dist Calc Err: {e} P:{getattr(player, 'guid', '?')} O:{getattr(obj, 'guid', '?')}")
             return -1.0
        except Exception as e:
             logging.exception(f"Unexpected Dist Calc Err: {e}"); return -1.0

    def test_player_stealthed(self):
        """Tests the player stealth condition using has_aura_by_id."""
        if not self.is_core_initialized() or not self.om or not self.om.local_player:
            messagebox.showwarning("Not Ready", "Core components not initialized or Player object not found.")
            return

        player = self.om.local_player
        stealth_aura_id = 1784 # Standard Stealth aura ID
        self.log_message(f"Testing Player Stealthed (Checking Aura ID: {stealth_aura_id})...", "INFO")

        try:
            player.update_dynamic_data(force_update=True) # Ensure latest data for check
            is_stealthed = player.has_aura_by_id(stealth_aura_id)
            result_message = f"Is Player Stealthed? {'Yes' if is_stealthed else 'No'}"
            self.log_message(result_message, "RESULT")
            messagebox.showinfo("Stealth Check Result", result_message)
        except Exception as e:
            error_msg = f"Error during stealth check: {e}"
            self.log_message(error_msg, "ERROR")
            traceback.print_exc()
            messagebox.showerror("Stealth Check Error", error_msg)

    def test_player_has_aura(self):
        """Tests the player has aura condition using has_aura_by_id."""
        if not self.is_core_initialized() or not self.om or not self.om.local_player:
            messagebox.showwarning("Not Ready", "Core components not initialized or Player object not found.")
            return

        player = self.om.local_player
        aura_id_str = simpledialog.askstring("Test Player Has Aura",
                                             "Enter Aura Spell ID:")
        if not aura_id_str:
            return # User cancelled

        try:
            aura_id_to_check = int(aura_id_str)
            if aura_id_to_check <= 0:
                 messagebox.showerror("Invalid ID", "Please enter a positive Spell ID.")
                 return

            self.log_message(f"Testing Player Has Aura ID: {aura_id_to_check}...", "INFO")
            player.update_dynamic_data(force_update=True) # Ensure latest data
            has_the_aura = player.has_aura_by_id(aura_id_to_check)
            result_message = f"Player Has Aura {aura_id_to_check}? {'Yes' if has_the_aura else 'No'}"
            self.log_message(result_message, "RESULT")
            messagebox.showinfo("Aura Check Result", result_message)

        except ValueError:
             messagebox.showerror("Invalid Input", f"'{aura_id_str}' is not a valid integer Spell ID.")
        except Exception as e:
            error_msg = f"Error during aura check for ID {aura_id_str}: {e}"
            self.log_message(error_msg, "ERROR")
            traceback.print_exc()
            messagebox.showerror("Aura Check Error", error_msg)

    def is_core_initialized(self) -> bool:
        """Checks if all required core components are initialized and ready."""
        # Check components directly and safely
        mem_ready = hasattr(self, 'mem') and self.mem is not None and self.mem.is_attached()
        om_ready = hasattr(self, 'om') and self.om is not None and self.om.is_ready()
        game_ready = hasattr(self, 'game') and self.game is not None # GameInterface doesn't have an is_ready() for init, only for pipe.
        # Consider adding self.combat_rotation check if it's essential for 'core' state
        return mem_ready and om_ready and game_ready

# --- REMOVED Methods fully moved to tab classes --- #
# - setup_monitor_tab
# - setup_rotation_control_tab
# - setup_rotation_editor_tab
# - setup_lua_runner_tab
# - setup_log_tab
# - populate_script_dropdown (moved to RotationControlTab)
# - load_selected_rotation_file (moved to RotationControlTab)
# - _sort_treeview_column (moved to MonitorTab)
# - open_monitor_filter_dialog (moved to MonitorTab)
# - run_lua_from_input (moved to LuaRunnerTab)
# - _update_detail_inputs (moved to RotationEditorTab)
# - _update_condition_inputs (moved to RotationEditorTab)
# - clear_rule_input_fields (moved to RotationEditorTab)
# - on_rule_select (moved to RotationEditorTab)
# - add_rotation_rule (moved to RotationEditorTab)
# - remove_selected_rule (moved to RotationEditorTab)
# - move_rule_up (moved to RotationEditorTab)
# - move_rule_down (moved to RotationEditorTab)
# - update_rule_listbox (moved to RotationEditorTab)
# - save_rules_to_file (moved to RotationEditorTab)
# - scan_spellbook (moved to RotationEditorTab)
# - lookup_spell_info (moved to RotationEditorTab)
# - test_get_combo_points (initial part moved to RotationControlTab)
# - update_monitor_treeview (moved to MonitorTab)
# - _on_lua_change (moved to RotationEditorTab)
# - load_rules_from_file (moved to RotationEditorTab)
# - clear_log_text (moved to LogTab)

# --- REMOVED LogRedirector Class Definition --- #

# --- Main Execution --- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    root = tk.Tk()
    try:
        app = WowMonitorApp(root)
        root.mainloop()
    except Exception as main_e:
        logging.exception("FATAL ERROR during application startup!")
        try: messagebox.showerror("Fatal Startup Error", f"App failed: {main_e}\nCheck logs.")
        except: pass