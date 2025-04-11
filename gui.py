import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog, simpledialog
import threading
import time
import queue
import configparser
import os
import json
import sys
import math
import traceback
from typing import Optional, List, Dict, Any
import logging
import sv_ttk # Import the theme library

# Project Modules
from memory import MemoryHandler, PROCESS_NAME
from object_manager import ObjectManager
from gameinterface import GameInterface
from wow_object import WowObject
from combat_rotation import CombatRotation
from rules import Rule
from targetselector import TargetSelector

# Constants
UPDATE_INTERVAL_MS = 250 # How often to update GUI data (milliseconds)
CORE_INIT_RETRY_INTERVAL_S = 5 # How often to retry core initialization
CORE_INIT_RETRY_INTERVAL_FAST = 1 # How often to attempt core initialization if disconnected
CORE_INIT_RETRY_INTERVAL_SLOW = 10 # How often to attempt core initialization if connected

# Style Definitions (Define globally or early in __init__)
DEFAULT_FONT = ('TkDefaultFont', 9)
BOLD_FONT = ('TkDefaultFont', 9, 'bold')
CODE_FONT = ("Consolas", 10)

# Updated styles for dark theme
LISTBOX_STYLE = {
    "bg": "#2E2E2E",           # Dark background
    "fg": "#E0E0E0",           # Light text
    "font": DEFAULT_FONT,
    "selectbackground": "#005A9E", # Darker blue highlight (adjust as needed)
    "selectforeground": "#FFFFFF", # White selected text
    "borderwidth": 0,
    "highlightthickness": 1,      # Add a subtle border
    "highlightcolor": "#555555"   # Border color
}
LOG_TEXT_STYLE = {
    "bg": "#1E1E1E",           # Very dark background for log
    "fg": "#D4D4D4",           # Default light grey text
    "font": DEFAULT_FONT,
    "wrap": tk.WORD,
    "insertbackground": "#FFFFFF" # White cursor
}
# Create a specific style for Lua output based on LOG_TEXT_STYLE but with CODE_FONT
LUA_OUTPUT_STYLE = LOG_TEXT_STYLE.copy()
LUA_OUTPUT_STYLE["font"] = CODE_FONT

LOG_TAGS = {
    "DEBUG": {"foreground": "#888888"},      # Keep grey for debug
    "INFO": {"foreground": "#D4D4D4"},       # Use default light grey for info
    "WARN": {"foreground": "#FFA500"},      # Keep Orange
    "ERROR": {"foreground": "#FF6B6B", "font": BOLD_FONT}, # Lighter Red, Bold
    "ACTION": {"foreground": "#569CD6"},      # Lighter Blue
    "RESULT": {"foreground": "#60C060"},      # Lighter Green
    "ROTATION": {"foreground": "#C586C0"}     # Lighter Purple
}


class WowMonitorApp:
    """Main application class for the WoW Monitor and Rotation Engine GUI."""

    def __init__(self, root):
        self.root = root

        # --- Style Application ---
        style = ttk.Style()
        try:
            # Try using 'clam' theme for a potentially better look
            style.theme_use('clam')
        except tk.TclError:
            print("Warning: 'clam' theme not available, using default.", file=sys.stderr) # Fallback

        # --- Load Config First ---
        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.config.read(self.config_file) # Read config file early

        # --- GUI Setup ---
        self.root.title("PyWoW Bot Interface")
        default_geometry = "750x600+150+150"
        geometry = self.config.get('GUI', 'geometry', fallback=default_geometry)
        self.root.geometry(geometry)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Apply the Sun Valley theme (set theme *before* creating widgets)
        sv_ttk.set_theme("dark")

        # --- Notebook (Tabs) ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        self.monitor_tab = ttk.Frame(self.notebook)
        self.rotation_control_tab = ttk.Frame(self.notebook)
        self.rotation_editor_tab = ttk.Frame(self.notebook)
        self.lua_runner_tab = ttk.Frame(self.notebook)
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.monitor_tab, text='Monitor')
        self.notebook.add(self.rotation_control_tab, text='Rotation Control / Test')
        self.notebook.add(self.rotation_editor_tab, text='Rotation Editor')
        self.notebook.add(self.lua_runner_tab, text='Lua Runner')
        self.notebook.add(self.log_tab, text='Log')

        # --- Status Bar ---
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var.set("Initializing...")

        # --- Initialize GUI Variables ---
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

        # --- Initialize Filter Variables (Only Units & Players) ---
        self.filter_show_units_var = tk.BooleanVar(value=True)
        self.filter_show_players_var = tk.BooleanVar(value=True)
        # self.filter_show_gameobjects_var = tk.BooleanVar(value=False) # Removed
        # self.filter_show_dynamicobj_var = tk.BooleanVar(value=False) # Removed
        # self.filter_show_corpses_var = tk.BooleanVar(value=False) # Removed

        # --- Initialize Editor Data & Variables ---
        # Condition definitions (moved for clarity)
        self.rule_conditions = [
            # Simple
            "None",
            "Target Exists",
            "Target Attackable",
            "Player Is Casting", # Renamed for clarity
            "Target Is Casting",
            "Player Is Moving",  # Renamed for clarity
            "Player Is Stealthed", # Renamed for clarity
            # Spell Readiness
            "Is Spell Ready", # Requires Spell ID input
            # Health
            "Target HP % < X",
            "Target HP % > X",
            "Target HP % Between X-Y",
            "Player HP % < X",
            "Player HP % > X",
            # Resources
            "Player Rage >= X",
            "Player Energy >= X",
            "Player Mana % < X",
            "Player Mana % > X",
            "Player Combo Points >= X",
            # Distance
            "Target Distance < X",
            "Target Distance > X",
            # Auras (Requires Name/ID input)
            "Target Has Aura",
            "Target Missing Aura",
            "Player Has Aura",
            "Player Missing Aura",
        ]
        self.rule_actions = ["Spell", "Macro", "Lua"]
        self.rule_targets = ["target", "player", "focus", "pet", "mouseover"]

        # Editor Input Variables
        self.action_var = tk.StringVar()
        self.spell_id_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.condition_var = tk.StringVar()
        self.condition_value_x_var = tk.StringVar()
        self.condition_value_y_var = tk.StringVar() # For Between X-Y
        self.condition_text_var = tk.StringVar() # For Aura/Spell Name/ID
        self.int_cd_var = tk.StringVar(value="0.0")
        # These need to be defined here for binding in setup_rotation_editor_tab
        self.lua_code_var = tk.StringVar() # For the scrolledtext binding
        self.macro_text_var = tk.StringVar()

        # --- Style Dictionaries (For non-ttk widgets) ---
        self.rule_listbox_style = LISTBOX_STYLE
        self.log_text_style = LOG_TEXT_STYLE
        self.log_tags = LOG_TAGS

        # --- Log Redirector (Initialize before setup_log_tab) ---
        self.log_redirector = None # Placeholder, set in setup_log_tab

        # --- Populate Tabs ---
        self.setup_monitor_tab(self.monitor_tab)
        self.setup_rotation_control_tab(self.rotation_control_tab)
        self.setup_rotation_editor_tab(self.rotation_editor_tab)
        self.setup_lua_runner_tab(self.lua_runner_tab)
        self.setup_log_tab(self.log_tab) # Initializes self.log_redirector

        # --- Initialize Core Components ---
        self.mem: Optional[MemoryHandler] = None
        self.om: Optional[ObjectManager] = None
        self.game: Optional[GameInterface] = None
        self.combat_rotation: Optional[CombatRotation] = None
        self.target_selector: Optional[TargetSelector] = None
        self.rotation_running = False
        self.loaded_script_path = self.config.get('Rotation', 'last_script', fallback=None)
        self.rotation_rules = []
        self.update_job = None
        self.is_closing = False

        # --- WoW Path ---
        self.wow_path = self._get_wow_path()

        # --- Setup GUI states ---
        self.rotation_thread: Optional[threading.Thread] = None
        self.stop_rotation_flag = threading.Event()
        self.core_init_attempting = False
        self.last_core_init_attempt = 0.0
        self.core_initialized = False # <<< ADD THIS LINE

        # --- Populate Initial State ---
        self.populate_script_dropdown()
        self._update_button_states()

        # --- Start Update Loop ---
        self.log_message(f"Starting update loop with interval: {UPDATE_INTERVAL_MS}ms", "INFO") # Use log_message
        self.update_data()

    # --- Logging Method ---
    def log_message(self, message, tag="INFO"):
        """Logs a message to the GUI log tab via the LogRedirector."""
        if self.log_redirector:
            self.log_redirector.write(message, tag)
        else:
            # Fallback to print if redirector isn't ready yet (should be rare)
            print(f"[{tag}] {message}", file=sys.stderr if tag in ["ERROR", "WARN"] else sys.stdout)


    def _get_wow_path(self):
        try:
            path = self.config.get('Settings', 'WowPath', fallback=None)
            if path and os.path.isdir(path):
                self.log_message(f"Read WowPath from {self.config_file}: {path}", "INFO")
                return path
            elif path:
                self.log_message(f"Warning: WowPath '{path}' in {self.config_file} is not a valid directory.", "WARN")
            default_path = "C:/Users/Jacob/Desktop/World of Warcraft 3.3.5a"
            self.log_message(f"Using default WoW path: {default_path}", "INFO")
            if os.path.isdir(default_path):
                return default_path
            else:
                self.log_message(f"Error: Default WoW path '{default_path}' is not valid.", "ERROR")
                return None
        except Exception as e:
            self.log_message(f"Error getting WoW path: {e}. Using fallback.", "ERROR")
            fallback_path = "C:/Users/Jacob/Desktop/World of Warcraft 3.3.5a"
            return fallback_path if os.path.isdir(fallback_path) else None

    def _show_error_and_exit(self, message):
        self.log_message(message, "ERROR")
        try:
            messagebox.showerror("Fatal Initialization Error", message)
            self.root.destroy()
        except Exception as e:
             print(f"CRITICAL GUI ERROR during error display: {e}", file=sys.stderr)
             os._exit(1)

    def _load_config(self):
        try:
                 self.loaded_script_path = self.config.get('Rotation', 'last_script', fallback=None)
        except Exception as e:
            self.log_message(f"Error loading config settings (beyond geometry): {e}", "ERROR")


    def _save_config(self):
        try:
            if not self.config.has_section('GUI'): self.config.add_section('GUI')
            self.config.set('GUI', 'geometry', self.root.geometry())
            if not self.config.has_section('Rotation'): self.config.add_section('Rotation')
            self.config.set('Rotation', 'last_script', self.loaded_script_path if self.loaded_script_path else "")
            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
            self.log_message("Configuration saved.", "INFO")
        except Exception as e:
            self.log_message(f"Error saving config file '{self.config_file}': {e}", "ERROR")

    def setup_gui(self):
        self.log_message("Warning: setup_gui() called, but GUI is now initialized in __init__.", "WARN")
        pass


    def setup_rotation_control_tab(self, tab):
        frame = ttk.Frame(tab, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        control_frame = ttk.LabelFrame(frame, text="Rotation Control", padding="10")
        control_frame.pack(pady=10, fill=tk.X)

        script_frame = ttk.Frame(control_frame)
        script_frame.pack(fill=tk.X, pady=5)
        ttk.Label(script_frame, text="Load Rotation File:").pack(side=tk.LEFT, padx=5)
        self.script_var = tk.StringVar()
        self.script_dropdown = ttk.Combobox(script_frame, textvariable=self.script_var, state="readonly")
        self.script_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.script_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_selected_rotation_file())
        ttk.Button(script_frame, text="Refresh", command=self.populate_script_dropdown).pack(side=tk.LEFT, padx=5)

        ttk.Button(control_frame, text="Load Rules from Editor", command=self.load_rules_from_editor).pack(pady=5, fill=tk.X)

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(pady=10, fill=tk.X)
        self.start_button = ttk.Button(button_frame, text="Start Rotation", command=self.start_rotation, state=tk.DISABLED)
        self.start_button.pack(side=tk.LEFT, expand=True, padx=5)
        self.stop_button = ttk.Button(button_frame, text="Stop Rotation", command=self.stop_rotation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, expand=True, padx=5)

        test_frame = ttk.LabelFrame(frame, text="DLL/IPC Tests", padding="10")
        test_frame.pack(pady=10, fill=tk.X)

        self.test_cp_button = ttk.Button(
            test_frame,
            text="Test Get Combo Points",
            command=self.test_get_combo_points, # Keep command pointing here
            state=tk.DISABLED
        )
        self.test_cp_button.pack(pady=5)


    def setup_monitor_tab(self, tab):
        info_frame = ttk.LabelFrame(tab, text="Status", padding=(10, 5))
        info_frame.pack(pady=(5,10), padx=5, fill=tk.X)
        info_frame.columnconfigure(1, weight=1)
        ttk.Label(info_frame, text="Player:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_name_var).grid(row=0, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Level:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_level_var).grid(row=1, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Health:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_hp_var).grid(row=2, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Power:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_energy_var).grid(row=3, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Pos:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_pos_var).grid(row=4, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Status:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.player_status_var).grid(row=5, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Separator(info_frame, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(info_frame, text="Target:").grid(row=7, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_name_var).grid(row=7, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Level:").grid(row=8, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_level_var).grid(row=8, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Health:").grid(row=9, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_hp_var).grid(row=9, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Power:").grid(row=10, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_energy_var).grid(row=10, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Pos:").grid(row=11, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_pos_var).grid(row=11, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Status:").grid(row=12, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_status_var).grid(row=12, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Dist:").grid(row=13, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.target_dist_var).grid(row=13, column=1, sticky=tk.W, padx=5, pady=1)

        # --- Nearby Units Frame with Filter Button ---
        list_outer_frame = ttk.Frame(tab)
        list_outer_frame.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)
        # list_outer_frame.columnconfigure(0, weight=1)

        list_header_frame = ttk.Frame(list_outer_frame)
        list_header_frame.pack(fill=tk.X)
        ttk.Label(list_header_frame, text="Nearby Objects:", font=BOLD_FONT).pack(side=tk.LEFT, padx=(10, 5))
        ttk.Button(list_header_frame, text="Filter...", command=self.open_monitor_filter_dialog).pack(side=tk.LEFT, padx=5)

        # --- Treeview Frame ---
        list_frame = ttk.LabelFrame(list_outer_frame, text="", padding=(10, 5)) # LabelFrame for border, text removed
        list_frame.pack(pady=(5,0), padx=0, fill=tk.BOTH, expand=True) # No internal padding needed if tree fills it
        self.tree = ttk.Treeview(list_frame, columns=('GUID', 'Type', 'Name', 'HP', 'Power', 'Dist', 'Status'), show='headings', height=10)
        self.tree.heading('GUID', text='GUID')
        self.tree.heading('Type', text='Type')
        self.tree.heading('Name', text='Name')
        self.tree.heading('HP', text='Health')
        self.tree.heading('Power', text='Power')
        self.tree.heading('Dist', text='Dist')
        self.tree.heading('Status', text='Status')
        self.tree.column('GUID', width=140, anchor=tk.W, stretch=False)
        self.tree.column('Type', width=60, anchor=tk.W, stretch=False)
        self.tree.column('Name', width=150, anchor=tk.W, stretch=True)
        self.tree.column('HP', width=110, anchor=tk.W, stretch=False)
        self.tree.column('Power', width=110, anchor=tk.W, stretch=False)
        self.tree.column('Dist', width=60, anchor=tk.E, stretch=False)
        self.tree.column('Status', width=100, anchor=tk.W, stretch=False)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview) # Removed style='Vertical.TScrollbar'
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_lua_runner_tab(self, tab):
        main_frame = ttk.Frame(tab, padding=10)
        main_frame.pack(expand=True, fill=tk.BOTH)
        input_frame = ttk.LabelFrame(main_frame, text="Lua Code", padding=10)
        input_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        input_frame.rowconfigure(0, weight=1)
        input_frame.columnconfigure(0, weight=1)
        # Use CODE_FONT for input
        self.lua_input_text = scrolledtext.ScrolledText(input_frame, wrap=tk.WORD, height=10, font=CODE_FONT)
        self.lua_input_text.grid(row=0, column=0, sticky="nsew")
        self.lua_input_text.insert(tk.END, '-- Enter Lua code to execute in WoW\nprint("Hello from Python!")\nlocal name, realm = GetUnitName("player"), GetRealmName()\nprint("Player:", name, "-", realm)\nreturn 42, "Done"')
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X)
        self.run_lua_button = ttk.Button(control_frame, text="Run Lua Code", command=self.run_lua_from_input, state=tk.DISABLED)
        self.run_lua_button.pack(side=tk.LEFT, padx=5)
        output_frame = ttk.LabelFrame(main_frame, text="Lua Output / Result", padding=10)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        # Use the dedicated LUA_OUTPUT_STYLE dictionary here
        self.lua_output_text = scrolledtext.ScrolledText(output_frame, height=5, state=tk.DISABLED, **LUA_OUTPUT_STYLE)
        self.lua_output_text.grid(row=0, column=0, sticky="nsew")

    def run_lua_from_input(self):
        if not self.game or not self.game.is_ready():
            messagebox.showerror("Error", "Game Interface (IPC) not connected.")
            return
        lua_code = self.lua_input_text.get("1.0", tk.END).strip()
        if not lua_code:
            messagebox.showwarning("Input Needed", "Please enter some Lua code to run.")
            return
        self.log_message("Executing Lua from input box...", "ACTION")
        try:
            # results = self.game.run_lua(lua_code) # Incorrect method name
            results = self.game.execute(lua_code) # Correct method name
            self.lua_output_text.config(state=tk.NORMAL)
            self.lua_output_text.delete("1.0", tk.END)
            if results is not None:
                result_str = "\n".join(map(str, results))
                self.lua_output_text.insert(tk.END, f"Result(s):\n{result_str}\n")
                self.log_message(f"Lua Execution Result: {results}", "RESULT")
            else:
                self.lua_output_text.insert(tk.END, "Lua Execution Failed (Check DLL/Game Logs)\n")
                self.log_message("Lua execution failed (None returned).", "WARN")
            self.lua_output_text.config(state=tk.DISABLED)
            self.lua_output_text.see(tk.END)
        except Exception as e:
            error_msg = f"Error running Lua: {e}"
            self.log_message(error_msg, "ERROR")
            messagebox.showerror("Lua Error", error_msg)
            self.lua_output_text.config(state=tk.NORMAL)
            self.lua_output_text.delete("1.0", tk.END)
            self.lua_output_text.insert(tk.END, f"ERROR:\n{error_msg}\n")
            self.lua_output_text.config(state=tk.DISABLED)

    def setup_rotation_editor_tab(self, tab):
        main_frame = ttk.Frame(tab, padding=10)
        main_frame.pack(expand=True, fill=tk.BOTH)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=2)
        main_frame.rowconfigure(0, weight=1)

        left_pane = ttk.Frame(main_frame)
        left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        # Make left_pane resize vertically if needed (e.g., Spell Info)
        # left_pane.rowconfigure(0, weight=1)
        # left_pane.rowconfigure(1, weight=0) # Spell Info section doesn't need to expand typically

        # --- Define Rule Section ---
        define_frame = ttk.LabelFrame(left_pane, text="Define Rule", padding="10")
        define_frame.grid(row=0, column=0, sticky="new", pady=(0, 10))
        define_frame.columnconfigure(1, weight=1)

        # Action Dropdown
        ttk.Label(define_frame, text="Action:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.action_dropdown = ttk.Combobox(define_frame, textvariable=self.action_var, values=["Spell", "Lua", "Macro"], state="readonly")
        self.action_dropdown.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.action_dropdown.set("Spell")
        self.action_dropdown.bind("<<ComboboxSelected>>", self._update_detail_inputs)

        # Detail Inputs Frame (Managed by _update_detail_inputs)
        self.detail_frame = ttk.Frame(define_frame)
        self.detail_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.detail_frame.columnconfigure(1, weight=1)

        # Spell ID Input
        self.spell_id_label = ttk.Label(self.detail_frame, text="Spell ID:")
        self.spell_id_entry = ttk.Entry(self.detail_frame, textvariable=self.spell_id_var)
        # Lua Code Input
        self.lua_code_label = ttk.Label(self.detail_frame, text="Lua Code:")
        self.lua_code_text = scrolledtext.ScrolledText(self.detail_frame, wrap=tk.WORD, height=3, width=30, font=CODE_FONT)
        self.lua_code_text.bind("<KeyRelease>", self._on_lua_change) # Bind update
        # Macro Text Input
        self.macro_text_label = ttk.Label(self.detail_frame, text="Macro Text:")
        self.macro_text_entry = ttk.Entry(self.detail_frame, textvariable=self.macro_text_var)

        # Target Dropdown
        ttk.Label(define_frame, text="Target:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.target_dropdown = ttk.Combobox(define_frame, textvariable=self.target_var, values=["target", "player", "pet", "focus"], state="readonly")
        self.target_dropdown.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        self.target_dropdown.set("target")

        # Condition Dropdown
        ttk.Label(define_frame, text="Condition:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.condition_dropdown = ttk.Combobox(
            define_frame,
            textvariable=self.condition_var,
            state="readonly",
            values=[
                "None", "Target Exists", "Player Health <= X", "Target Health <= X",
                "Player Energy >= X", "Rage >= X", "Mana >= X", # Renamed Rage/Energy for consistency
                "Combo Points >= X", "Target Is Enemy", "Player Has Aura",
                "Target Has Aura", "Target Has Debuff", "Player In Combat", "Target In Combat",
                "Target Is Casting", "Player Is Moving" # Added more examples
                # Add more conditions as needed
            ]
        )
        self.condition_dropdown.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.condition_dropdown.set("None") # Default value
        self.condition_dropdown.bind("<<ComboboxSelected>>", self._update_condition_inputs) # Bind update function

        # ADDED: Condition Value Input
        ttk.Label(define_frame, text="Condition Value (X):").grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.condition_value_x_entry = ttk.Entry(define_frame, textvariable=self.condition_value_x_var, state=tk.DISABLED)
        self.condition_value_x_entry.grid(row=4, column=1, sticky="ew", padx=5, pady=2)

        # Internal Cooldown (Row adjustment needed)
        ttk.Label(define_frame, text="Int. CD (s):").grid(row=5, column=0, sticky=tk.W, padx=5, pady=2) # Changed row to 5
        self.int_cd_entry = ttk.Entry(define_frame, textvariable=self.int_cd_var)
        self.int_cd_entry.grid(row=5, column=1, sticky="ew", padx=5, pady=2) # Changed row to 5

        # Add/Update Button (Row adjustment needed)
        self.add_update_button = ttk.Button(define_frame, text="Add/Update Rule", command=self.add_rotation_rule)
        self.add_update_button.grid(row=6, column=0, columnspan=2, pady=10) # Changed row to 6

        # --- Spell Info Section ---
        spell_info_frame = ttk.LabelFrame(left_pane, text="Spell Info", padding="10")
        spell_info_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        spell_info_frame.columnconfigure(0, weight=1)
        spell_info_frame.columnconfigure(1, weight=1)

        list_spells_button = ttk.Button(spell_info_frame, text="List Known Spells...", command=self.scan_spellbook)
        list_spells_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        lookup_spell_button = ttk.Button(spell_info_frame, text="Lookup Spell ID...", command=self.lookup_spell_info)
        lookup_spell_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        right_pane = ttk.Frame(main_frame)
        right_pane.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right_pane.rowconfigure(0, weight=1)
        right_pane.columnconfigure(0, weight=1)

        rule_list_frame = ttk.LabelFrame(right_pane, text="Rotation Rule Priority", padding="5")
        rule_list_frame.grid(row=0, column=0, sticky="nsew")
        rule_list_frame.grid_rowconfigure(0, weight=1)
        rule_list_frame.grid_columnconfigure(0, weight=1)

        # Apply style to tk.Listbox
        self.rule_listbox = tk.Listbox(rule_list_frame, height=15, selectmode=tk.SINGLE, **self.rule_listbox_style)
        self.rule_listbox.grid(row=0, column=0, sticky="nsew")
        self.rule_listbox.bind('<<ListboxSelect>>', self.on_rule_select)

        scrollbar = ttk.Scrollbar(rule_list_frame, orient=tk.VERTICAL, command=self.rule_listbox.yview)
        self.rule_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        rule_button_frame = ttk.Frame(right_pane)
        rule_button_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        move_up_button = ttk.Button(rule_button_frame, text="Move Up", command=self.move_rule_up)
        move_up_button.pack(side=tk.LEFT, padx=5)
        move_down_button = ttk.Button(rule_button_frame, text="Move Down", command=self.move_rule_down)
        move_down_button.pack(side=tk.LEFT, padx=5)
        remove_rule_button = ttk.Button(rule_button_frame, text="Remove Selected", command=self.remove_selected_rule)
        remove_rule_button.pack(side=tk.LEFT, padx=5)
        clear_button = ttk.Button(rule_button_frame, text="Clear Input", command=self.clear_rule_input_fields)
        clear_button.pack(side=tk.LEFT, padx=15)

        file_button_frame = ttk.Frame(right_pane)
        file_button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        save_rules_button = ttk.Button(file_button_frame, text="Save Rules...", command=self.save_rules_to_file)
        save_rules_button.pack(side=tk.LEFT, padx=5)
        load_rules_button = ttk.Button(file_button_frame, text="Load Rules...", command=self.load_rules_from_file)
        load_rules_button.pack(side=tk.LEFT, padx=5)

        # Call initial updates for dynamic inputs
        self._update_detail_inputs()
        self._update_condition_inputs()

    # --- Rename _update_rule_input_state to _update_detail_inputs ---
    def _update_detail_inputs(self, event=None):
        action_type = self.action_dropdown.get()
        # Forget all detail entries first
        self.spell_id_entry.grid_forget()
        self.lua_code_text.grid_forget()
        self.macro_text_entry.grid_forget()
        # Update label and show the correct entry
        if action_type == "Spell":
            self.spell_id_label.config(text="Spell ID:")
            self.spell_id_entry.grid(row=0, column=0, sticky=tk.EW)
        elif action_type == "Macro":
            self.macro_text_label.config(text="Macro Text:")
            self.macro_text_entry.grid(row=0, column=0, sticky=tk.EW)
        elif action_type == "Lua":
            self.lua_code_label.config(text="Lua Code:")
            self.lua_code_text.grid(row=0, column=0, sticky=tk.EW)
        else:
            self.spell_id_label.config(text="Detail:")

    # --- New method to manage condition inputs --- 
    def _update_condition_inputs(self, event=None):
        condition = self.condition_dropdown.get()
        
        # Hide all dynamic inputs first
        self.condition_value_x_entry.grid_forget()
        self.int_cd_entry.grid_forget()
        
        # Show inputs based on selected condition
        if "< X" in condition or "> X" in condition or ">= X" in condition:
            label_text = "Value X:"
            if "HP %" in condition: label_text = "HP % X:"
            elif "Mana %" in condition: label_text = "Mana % X:"
            elif "Distance" in condition: label_text = "Dist. X (yd):"
            elif "Rage" in condition: label_text = "Rage X:"
            elif "Energy" in condition: label_text = "Energy X:"
            elif "Combo Points" in condition: label_text = "CP X:"
            self.condition_value_x_entry.config(text=label_text)
            self.condition_value_x_entry.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
        elif "Between X-Y" in condition:
            label_text = "HP %" # Currently only HP uses this
            self.condition_value_x_entry.config(text=f"{label_text} X:")
            self.condition_value_x_entry.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
            ttk.Label(self.detail_frame, text="Y:").grid(row=0, column=2, padx=(0, 2), sticky=tk.W) # Add Y label
            self.condition_value_y_entry.grid(row=0, column=3, sticky=tk.W)
        elif "Aura" in condition:
            self.spell_id_label.config(text="Aura Name/ID:")
            self.condition_value_x_entry.config(text="Aura Name/ID:")
            self.condition_value_x_entry.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
            self.condition_text_entry.grid(row=0, column=1, columnspan=3, sticky=tk.EW)
        elif "Is Spell Ready" in condition:
            self.spell_id_label.config(text="Spell ID:")
            self.condition_value_x_entry.config(text="Spell ID:")
            self.condition_value_x_entry.grid(row=0, column=0, padx=(0, 2), sticky=tk.W)
            self.condition_text_entry.grid(row=0, column=1, columnspan=3, sticky=tk.EW)

    # --- Modify clear_rule_input_fields --- 
    def clear_rule_input_fields(self):
         self.action_dropdown.set("Spell")
         self.spell_id_var.set("")
         self.lua_code_var.set("")
         self.macro_text_var.set("")
         self.target_var.set("target")
         self.condition_var.set("None")
         # Clear dynamic fields
         self.condition_value_x_var.set("") 
         self.condition_value_y_var.set("") 
         self.condition_text_var.set("") 
         self.int_cd_var.set("0.0")
         self._update_detail_inputs() # Update detail label/entry
         self._update_condition_inputs() # Hide dynamic condition inputs
         if self.rule_listbox.curselection():
              self.rule_listbox.selection_clear(self.rule_listbox.curselection()[0])

    # --- Modify on_rule_select --- 
    def on_rule_select(self, event=None):
        indices = self.rule_listbox.curselection()
        if not indices: return
        index = indices[0]
        try:
             rule = self.rotation_rules[index]
             action = rule.get('action', 'Spell')
             detail = rule.get('detail', '')
             target = rule.get('target', self.rule_targets[0])
             condition = rule.get('condition', self.rule_conditions[0])
             cooldown = rule.get('cooldown', 0.0)
             # Get dynamic values
             value_x = rule.get('condition_value_x', '')
             value_y = rule.get('condition_value_y', '')
             cond_text = rule.get('condition_text', '') # Aura Name/ID or Spell ID

             self.action_dropdown.set(action)
             self._update_detail_inputs() # Update detail based on action
             if action == "Spell": self.spell_id_var.set(str(detail))
             elif action == "Macro": self.macro_text_var.set(str(detail))
             elif action == "Lua": self.lua_code_var.set(str(detail))
             
             self.target_var.set(target)
             self.condition_var.set(condition)
             self._update_condition_inputs() # Show/hide dynamic fields based on condition

             # Populate dynamic fields
             self.condition_value_x_var.set(str(value_x))
             self.condition_value_y_var.set(str(value_y))
             self.condition_text_var.set(str(cond_text))
             
             self.int_cd_var.set(f"{cooldown:.1f}")
        except IndexError:
             # This is where the old error handling was
             self.log_message(f"Error: Selected index {index} out of range for rules.", "ERROR")
             self.clear_rule_input_fields()
        except Exception as e:
             # This is where the old error handling was
             self.log_message(f"Error loading selected rule: {e}", "ERROR")
             traceback.print_exc() # Print traceback for debugging
             self.clear_rule_input_fields()


    def setup_log_tab(self, tab):
        log_frame = ttk.LabelFrame(tab, text="Log Output", padding=(10, 5))
        log_frame.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        # Use self.log_text_style defined in __init__
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, width=80, state=tk.DISABLED, **self.log_text_style)
        self.log_text.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        # Use self.log_tags defined in __init__
        for tag_name, config in self.log_tags.items():
            self.log_text.tag_configure(tag_name, **config)

        clear_log_button = ttk.Button(log_frame, text="Clear Log", command=self.clear_log_text)
        clear_log_button.grid(row=1, column=0, columnspan=2, pady=(5, 0))

        # Initialize LogRedirector HERE, after self.log_text is created
        self.log_redirector = LogRedirector(self.log_text, tags=self.log_tags) # Pass tags
        self.log_redirector.start_redirect()
        # self.log_message("Standard output redirected to log tab.", "INFO") # Can't log until __init__ finishes


    # --- GUI Actions ---

    def _update_button_states(self):
        core_ready = self.mem and self.mem.is_attached() and self.om and self.om.is_ready() and self.game and self.game.is_ready()
        # Check rules loaded in the ENGINE, not just the editor
        rules_in_engine = bool(self.combat_rotation and self.combat_rotation.rotation_rules)
        # Check script loaded in the ENGINE
        script_in_engine = bool(self.combat_rotation and self.combat_rotation.lua_script_content)
        # Rotation is loadable if either rules OR script is loaded into the engine
        rotation_loadable = rules_in_engine or script_in_engine 
        is_rotation_running = self.rotation_thread is not None and self.rotation_thread.is_alive()

        # Update Start/Stop Buttons
        self.start_button['state'] = tk.NORMAL if core_ready and rotation_loadable and not is_rotation_running else tk.DISABLED
        self.stop_button['state'] = tk.NORMAL if is_rotation_running else tk.DISABLED
        self.test_cp_button['state'] = tk.NORMAL if core_ready else tk.DISABLED
        self.run_lua_button['state'] = tk.NORMAL if core_ready else tk.DISABLED

        # Status Label update (requires self.rotation_status_label) - Simplified for now
        # Need to ensure self.rotation_status_label is defined, maybe in control tab?
        # Let's focus on fixing the crash first.


    def populate_script_dropdown(self):
        # Look in Rules directory for .json files
        rules_dir = "Rules"
        try:
            if not os.path.exists(rules_dir): os.makedirs(rules_dir)
            # Look for .json files
            files = sorted([f for f in os.listdir(rules_dir) if f.endswith('.json')]) 
            if files:
                self.script_dropdown['values'] = files
                # Try to load last saved rule file? Need to store this separately.
                # For now, just select the first one if available.
                # last_loaded_file = self.config.get('Rotation', 'last_rule_file', fallback=None)
                # if last_loaded_file and os.path.basename(last_loaded_file) in files:
                #      self.script_var.set(os.path.basename(last_loaded_file))
                # el
                if files: # Select first if list is not empty
                     self.script_var.set(files[0])
                self.script_dropdown.config(state="readonly")
            else:
                self.script_dropdown['values'] = []
                # Update message
                self.script_var.set(f"No *.json files found in {rules_dir}/") 
                self.script_dropdown.config(state=tk.DISABLED)
        except Exception as e:
            self.log_message(f"Error populating rotation file dropdown: {e}", "ERROR")
            self.script_dropdown['values'] = []
            self.script_var.set("Error loading rotation files")
            self.script_dropdown.config(state=tk.DISABLED)
        self._update_button_states()

    def load_selected_rotation_file(self):
        if self.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before loading a new file.")
            return
        if not self.combat_rotation:
             messagebox.showerror("Error", "Combat Rotation engine not initialized.")
             return

        selected_file = self.script_var.get()
        rules_dir = "Rules" # Load from Rules directory
        if selected_file and not selected_file.startswith("No ") and not selected_file.startswith("Error "):
            file_path = os.path.join(rules_dir, selected_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        loaded_rules = json.load(f)
                    if not isinstance(loaded_rules, list):
                        raise ValueError("Invalid format: JSON root must be a list of rules.")
                    # TODO: Add validation for individual rule structure?

                    # Load rules into the combat rotation engine
                    self.combat_rotation.load_rotation_rules(loaded_rules)
                    
                    # Clear any loaded script content (using the combat_rotation method)
                    if hasattr(self.combat_rotation, 'clear_lua_script'):
                        self.combat_rotation.clear_lua_script()
                    else:
                        self.log_message("Warning: CombatRotation has no clear_lua_script method.", "WARN")
                        
                    # Update last loaded file? Maybe store this config value
                    # self.loaded_rule_file_path = file_path 

                    self.log_message(f"Loaded and activated {len(loaded_rules)} rules from: {file_path}", "INFO")
                    messagebox.showinfo("Rotation Loaded", f"Loaded and activated {len(loaded_rules)} rules from file:\n{selected_file}")
                    # If we want to reflect loaded rules in editor, uncomment these:
                    # self.rotation_rules = loaded_rules
                    # self.update_rule_listbox()
                    self._update_button_states()

                except json.JSONDecodeError as e:
                    self.log_message(f"Error decoding JSON from {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
                except ValueError as e:
                    self.log_message(f"Error validating rules file {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
                except Exception as e:
                    self.log_message(f"Error loading rules from {file_path}: {e}", "ERROR")
                    messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")
            else:
                 messagebox.showerror("Load Error", f"Rotation file not found:\n{file_path}")
                 # self.loaded_rule_file_path = None
                 self.script_var.set("")
                 self.populate_script_dropdown()
        else:
            messagebox.showwarning("Load Warning", "Please select a valid rotation file.")
        self._update_button_states()

    def start_rotation(self):
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
            self.log_message("Rotation already running.", "WARN")
            return
        if not self.combat_rotation:
            self.log_message("Cannot start rotation: Combat Rotation module not initialized.", "ERROR")
            messagebox.showerror("Error", "Combat Rotation module not initialized.")
            return
        if not self.mem or not self.mem.is_attached():
             self.log_message("Cannot start rotation: Not attached to WoW.", "ERROR")
             messagebox.showerror("Error", "Cannot start rotation: Not attached to WoW.")
             return
        if not self.game or not self.game.is_ready():
             self.log_message("Cannot start rotation: Game Interface (IPC) not ready.", "ERROR")
             messagebox.showerror("Error", "Cannot start rotation: Pipe to DLL not connected.")
             return # Correct indentation

        # Check if rules are loaded OR a script is loaded
        using_rules = bool(self.combat_rotation.rotation_rules)
        # using_script = bool(self.combat_rotation.lua_script_content)

        if using_rules:
            self.log_message("Starting rotation using loaded rules.", "INFO")
        # elif using_script:
        #     script_name = os.path.basename(self.combat_rotation.current_rotation_script_path or "Unknown Script")
        #     self.log_message(f"Starting rotation using Lua script: {script_name}", "INFO")
        else:
            # Update message to reflect rules file or editor rules
            self.log_message("No rotation rules loaded from file or editor.", "WARN") 
            messagebox.showwarning("Warning", "No rotation rules loaded to start.")
            return

        self.stop_rotation_flag.clear()
        # Correct the target function name for the thread
        self.rotation_thread = threading.Thread(target=self._run_rotation_loop, daemon=True)
        self.rotation_thread.start()
        self.log_message("Rotation thread started.", "INFO")
        self._update_button_states() # Update buttons after starting

    def _run_rotation_loop(self):
        loop_count = 0
        while not self.stop_rotation_flag.is_set():
            start_time = time.monotonic()
            try:
                # --- Add debug prints here --- #
                # core_status = self.core_initialized
                # rotation_engine_status = "Exists" if self.combat_rotation else "None"
                # print(f"[Rotation Loop Check] Core Initialized: {core_status}, Combat Rotation: {rotation_engine_status}", file=sys.stderr)
                # ----------------------------- #
                
                # self.log_message(f"[THREAD LOOP {loop_count}] Before combat_rotation.run()", "DEBUG") # Commented out spam
                if self.core_initialized and self.combat_rotation:
                    # Only run if core is up and we have a rotation engine
                    self.combat_rotation.run()
                # Added else block for debugging potential loop without core
                else:
                     if not self.core_initialized:
                         print("[Rotation Loop] Skipping run: Core not initialized.", file=sys.stderr)
                     if not self.combat_rotation:
                         print("[Rotation Loop] Skipping run: Combat rotation engine not available.", file=sys.stderr)
                     # Optional: Add a small sleep here if it's looping without core
                     time.sleep(0.5)

                loop_count += 1
                time.sleep(0.1) # Rotation tick rate

            except Exception as e:
                self.log_message(f"Error in rotation loop: {e}", "ERROR")
                traceback.print_exc() # Print full traceback to log
                # Force print exception to stderr as well
                print(f"[THREAD LOOP {loop_count}] EXCEPTION: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                break # Stop on error

        self.log_message("Rotation thread finishing.", "DEBUG")
        # Schedule GUI update in main thread
        if self.root.winfo_exists(): # Check if root window still exists
            self.root.after(0, self._on_rotation_thread_exit)

    def _on_rotation_thread_exit(self):
        # Add the method body back
        """Callback executed in the main GUI thread after the rotation thread exits."""
        self.rotation_thread = None
        self.log_message("Rotation stopped.", "INFO")
        self._update_button_states() # Update buttons now thread is confirmed gone

    def _sort_treeview_column(self, col, reverse):
        # Add the pass statement back
        pass

    def open_monitor_filter_dialog(self):
        """Opens a dialog window to configure object type filters for the monitor list."""
        filter_window = tk.Toplevel(self.root)
        filter_window.title("Monitor Filters")
        filter_window.geometry("250x280") # Adjusted size
        filter_window.transient(self.root)
        filter_window.grab_set() # Make it modal
        filter_window.resizable(False, False)

        main_frame = ttk.Frame(filter_window, padding=15)
        main_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(main_frame, text="Show Object Types:", font=BOLD_FONT).pack(pady=(0, 10))

        # Map object type enum to filter variable and label text
        filter_map = {
            WowObject.TYPE_PLAYER: (self.filter_show_players_var, "Players"),
            WowObject.TYPE_UNIT: (self.filter_show_units_var, "Units (NPCs/Mobs)"),
            # WowObject.TYPE_GAMEOBJECT: (self.filter_show_gameobjects_var, "Game Objects"), # Removed
            # WowObject.TYPE_DYNAMICOBJECT: (self.filter_show_dynamicobj_var, "Dynamic Objects"), # Removed
            # WowObject.TYPE_CORPSE: (self.filter_show_corpses_var, "Corpses"), # Removed
        }

        for obj_type, (var, label) in filter_map.items():
            ttk.Checkbutton(main_frame, text=label, variable=var).pack(anchor=tk.W, padx=10)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, pady=(20, 0), fill=tk.X)

        def apply_and_close():
            self.update_monitor_treeview() # Update tree based on new filter settings
            filter_window.destroy()

        ok_button = ttk.Button(button_frame, text="OK", command=apply_and_close)
        ok_button.pack(side=tk.RIGHT, padx=5)
        # No need for cancel if closing doesn't change anything
        # cancel_button = ttk.Button(button_frame, text="Cancel", command=filter_window.destroy)
        # cancel_button.pack(side=tk.RIGHT)

        filter_window.wait_window() # Wait for the window to be closed

    # --- Add back the on_closing method --- 
    def on_closing(self):
        if self.is_closing: return
        self.is_closing = True
        self.log_message("Closing application...", "INFO")
        if self.update_job:
            try:
                self.root.after_cancel(self.update_job)
            except tk.TclError:
                pass # Ignore error if root is already gone
            self.update_job = None
        # Signal rotation thread to stop if running
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
             self.log_message("Signaling rotation thread to stop...", "INFO")
             self.stop_rotation_flag.set()
             # Optional: Add a short join with timeout?
             # try:
             #     self.rotation_thread.join(timeout=0.5)
             # except Exception as e:
             #     self.log_message(f"Error joining rotation thread: {e}", "WARN")
        
        # Disconnect IPC
        if self.game:
            self.game.disconnect_pipe()
            
        self._save_config()
        
        # Restore stdout/stderr? Only if LogRedirector is active
        if self.log_redirector:
            self.log_message("Restoring standard output streams.", "DEBUG")
            self.log_redirector.stop_redirect()
        
        print("Cleanup finished. Exiting.") # Print to original stdout
        try:
            self.root.destroy()
        except tk.TclError:
            pass # Ignore error if root is already destroyed

    def connect_and_init_core(self) -> bool:
        """Attempts to connect to WoW, initialize core components, and connect IPC."""
        # This method now runs in a thread, use self.log_message for GUI logging
        success = False
        try:
            self.log_message("Init Core: Starting...", "DEBUG") # Use log_message

            # 1. Memory Handler
            if not self.mem or not self.mem.is_attached():
                self.log_message("Init Core: Initializing MemoryHandler...", "DEBUG")
                self.mem = MemoryHandler()
                if not self.mem.is_attached():
                    self.log_message(f"Init Core: Failed to attach to WoW process ({PROCESS_NAME}).", "ERROR")
                    return False
                self.log_message(f"Init Core: Attached to WoW process ({PROCESS_NAME}).", "INFO")
            else:
                 self.log_message("Init Core: MemoryHandler already attached.", "DEBUG")

            # 2. Object Manager
            if not self.om or not self.om.is_ready():
                self.log_message("Init Core: Initializing ObjectManager...", "DEBUG")
                self.om = ObjectManager(self.mem)
                if not self.om.is_ready():
                    self.log_message("Init Core: Failed to initialize Object Manager (Check ClientConnection/Offsets?).", "ERROR")
                    return False
                self.log_message("Init Core: Object Manager initialized.", "INFO")
            else:
                 self.log_message("Init Core: ObjectManager already initialized.", "DEBUG")

            # 3. Game Interface (Creation)
            if not self.game:
                self.log_message("Init Core: Initializing GameInterface...", "DEBUG")
                self.game = GameInterface(self.mem)
                self.log_message("Init Core: Game Interface (IPC) created.", "INFO")
            else:
                self.log_message("Init Core: GameInterface already created.", "DEBUG")

            # 4. IPC Pipe Connection
            if not self.game.is_ready():
                self.log_message("Init Core: Attempting IPC Pipe connection...", "DEBUG")
                if self.game.connect_pipe():
                     self.log_message("Init Core: IPC Pipe connected successfully.", "INFO")
                else:
                     self.log_message("Init Core: Failed to connect IPC Pipe (Is DLL injected and running?).", "ERROR")
                     return False
            else:
                 self.log_message("Init Core: IPC Pipe already connected.", "DEBUG")

            # 5. Target Selector
            if not self.target_selector:
                self.log_message("Init Core: Initializing TargetSelector...", "DEBUG")
                self.target_selector = TargetSelector(self.om)
                self.log_message("Init Core: Target Selector initialized.", "INFO")
            else:
                 self.log_message("Init Core: TargetSelector already initialized.", "DEBUG")

            # 6. Combat Rotation
            if not self.combat_rotation:
                 self.log_message("Init Core: Initializing CombatRotation...", "DEBUG")
                 self.combat_rotation = CombatRotation(self.mem, self.om, self.game)
                 self.log_message("Init Core: Combat Rotation engine initialized.", "INFO")
            else:
                 self.log_message("Init Core: CombatRotation already initialized.", "DEBUG")

            success = True
            self.log_message("Init Core: Core components initialized successfully.", "INFO")

        except Exception as e:
            # Use log_message here as well
            self.log_message(f"Init Core: Error during core initialization: {e}", "ERROR")
            # Use print_exc which goes through the redirected stderr (LogRedirector)
            traceback.print_exc()
            success = False
        finally:
            # This runs in the init thread, signal main thread to potentially update state
             self.log_message("Init Core: Finalizing attempt.", "DEBUG")
             if self.root.winfo_exists():
                  # Pass the success status to the callback
                  self.root.after(0, self._finalize_core_init_attempt, success)

        # return success # Return value not directly used by caller thread

    # --- Add back load_rules_from_editor --- 
    def load_rules_from_editor(self):
        """Loads the rules currently defined in the editor into the combat engine."""
        if self.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before editing rules.")
            return
        if not self.combat_rotation:
             messagebox.showerror("Error", "Combat Rotation engine not initialized.")
             self.log_message("Attempted to load rules from editor, but combat engine missing.", "ERROR")
             return

        if not self.rotation_rules:
            messagebox.showwarning("No Rules", "No rules defined in the editor to load.")
            return

        try:
            # Load the current rules from the editor's list into the engine
            self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.log_message(f"Loaded {len(self.rotation_rules)} rules from editor into engine.", "INFO")

            # Clear any loaded script information
            if hasattr(self.combat_rotation, 'clear_lua_script'):
                self.combat_rotation.clear_lua_script()
            else:
                self.log_message("Warning: CombatRotation has no clear_lua_script method.", "WARN")
            self.script_var.set("") # Clear the file dropdown selection

            # Update status and buttons
            messagebox.showinfo("Rules Loaded", f"{len(self.rotation_rules)} rules from the editor are now active.")
            self._update_button_states()

        except Exception as e:
            error_msg = f"Error loading rules from editor: {e}"
            self.log_message(error_msg, "ERROR")
            messagebox.showerror("Load Error", error_msg)

    # --- Add back scan_spellbook --- 
    def scan_spellbook(self):
        if not self.om or not self.om.is_ready():
            messagebox.showerror("Error", "Object Manager not ready. Cannot scan spellbook.")
            return
        if not self.game or not self.game.is_ready():
            messagebox.showerror("Error", "Game Interface not ready. Cannot get spell info.")
            return

        spell_ids = self.om.read_known_spell_ids()
        if not spell_ids:
            messagebox.showinfo("Spellbook Scan", "No spell IDs found or unable to read spellbook.")
            return

        scan_window = tk.Toplevel(self.root)
        scan_window.title("Known Spells")
        scan_window.geometry("500x400")
        scan_window.transient(self.root)
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

        # Function to populate treeview (runs in main thread)
        def populate_tree():
            count = 0
            max_to_fetch = 500 # Limit to prevent extreme slowness
            for spell_id in sorted(spell_ids):
                if count >= max_to_fetch:
                    try:
                        tree.insert("", tk.END, values=(f"({len(spell_ids)-max_to_fetch} more)", "...", "..."))
                    except tk.TclError: break # Stop if window closed
                    break
                
                # Call get_spell_info via game interface
                info = self.game.get_spell_info(spell_id)
                
                try:
                    if info:
                        name = info.get("name", "N/A")
                        rank = info.get("rank", "None") # Default to None if empty
                        if not rank: rank = "None" # Ensure empty ranks show as None
                        tree.insert("", tk.END, values=(spell_id, name, rank))
                    else:
                        tree.insert("", tk.END, values=(spell_id, "(Info Failed)", ""))
                except tk.TclError: break # Stop if window closed during insert
                
                count += 1
                # If the window requires manual updates for long lists:
                # if count % 20 == 0: scan_window.update_idletasks()
            
            # Final update might be needed
            # try: scan_window.update_idletasks() 
            # except tk.TclError: pass

        # Populate directly for simplicity now
        populate_tree()

        def copy_id():
            selected_item = tree.focus()
            if selected_item:
                item_data = tree.item(selected_item)
                try:
                    # Ensure the value exists and is indexable
                    if item_data and 'values' in item_data and len(item_data['values']) > 0:
                        spell_id_to_copy = item_data['values'][0]
                        self.root.clipboard_clear()
                        self.root.clipboard_append(str(spell_id_to_copy))
                        self.log_message(f"Copied Spell ID: {spell_id_to_copy}", "DEBUG")
                    else:
                         messagebox.showwarning("Copy Error", "Could not retrieve Spell ID from selected item.", parent=scan_window)
                except Exception as e:
                     messagebox.showerror("Clipboard Error", f"Could not copy to clipboard:\n{e}", parent=scan_window)

        copy_button = ttk.Button(scan_window, text="Copy Selected Spell ID", command=copy_id)
        copy_button.pack(pady=5)

    # --- Add back stop_rotation --- 
    def stop_rotation(self):
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
            self.log_message("Stopping rotation...", "INFO")
            self.stop_rotation_flag.set()
            # Note: Actual cleanup and button state update happens 
            # in _on_rotation_thread_exit when the thread confirms exit.
        else:
            self.log_message("Rotation not running.", "INFO")
        # Do NOT update buttons here, wait for thread exit callback

    # --- Add back test_get_combo_points ---
    def test_get_combo_points(self):
        """Checks for target via direct memory read, then starts background thread to fetch combo points."""
        # Check if game interface and object manager are ready
        if not self.game or not self.game.is_ready():
            messagebox.showwarning("Not Ready", "Game interface not connected or process not found.")
            return
        if not self.om:
             messagebox.showwarning("Not Ready", "Object Manager not initialized.")
             return

        # --- Use ObjectManager direct read for target check (like the monitor panel) ---
        try:
            # Access the target property which reads memory directly
            current_target = self.om.target
            if not current_target:
                self.log_message("No target detected via direct memory read (om.target).", "INFO")
                messagebox.showinfo("No Target", "You must have a target selected to get combo points.")
                return # Return if no target found by direct read
            else:
                self.log_message(f"Target detected via direct memory read: {current_target.guid:#X}", "DEBUG")
        except Exception as e:
            self.log_message(f"Error checking target via om.target: {e}", "ERROR")
            traceback.print_exc()
            messagebox.showerror("Error", f"Error checking target status: {e}")
            return # Don't proceed if direct check fails
        # --- End target check ---

        # If target exists, proceed to fetch combo points via pipe in background thread
        self.log_message("Target confirmed, starting combo point fetch thread...", "INFO")
        # Disable button while fetching
        button_to_disable = None
        if hasattr(self, 'test_get_cp_button') and self.test_get_cp_button.winfo_exists():
            button_to_disable = self.test_get_cp_button
            button_to_disable.config(state=tk.DISABLED)
        else:
             self.log_message("Warning: Combo points button 'test_get_cp_button' not found.", "WARNING")

        # Create and start the thread that does the real work (fetching CP via pipe)
        thread = threading.Thread(target=self._fetch_combo_points_thread, daemon=True)
        thread.start()

    def _fetch_combo_points_thread(self):
        """Worker thread to fetch combo points via pipe (ASSUMES target already validated)."""
        self.log_message("Combo point thread: Started (target assumed valid)", "DEBUG")
        combo_points = None
        button_to_re_enable = self.test_cp_button

        try:
            # Connection check still relevant for fetching CP
            # Use is_ready() to check if the pipe handle is valid
            if not self.game or not self.game.is_ready():
                self.log_message("Combo point thread: Game interface not connected/ready for CP fetch.", "WARNING")
                self.root.after(0, self._show_combo_points_result, None)
                return

            # --- REMOVED TARGET CHECK VIA PIPE - Handled before thread start ---
            # self.log_message("Combo point thread: Checking target via pipe...")
            # target_guid = self.game.get_target_guid() # NO LONGER NEEDED HERE
            # if not target_guid or target_guid == 0:
            #     self.log_message("Combo point thread: No target found via pipe (should not happen?).", "WARNING")
            #     self.root.after(0, self._show_no_target_message) # Use dedicated message
            #     return
            # --- END REMOVED CHECK ---

            # Directly call get_combo_points (assumes target is set)
            self.log_message("Combo point thread: Calling game.get_combo_points()...", "DEBUG")
            combo_points = self.game.get_combo_points() # Fetches via pipe
            self.log_message(f"Combo point thread: Received CP result: {combo_points}", "DEBUG")

            # Schedule the result display in the main GUI thread
            self.log_message("Combo point thread: Scheduling result display.", "DEBUG")
            self.root.after(0, self._show_combo_points_result, combo_points)

        except BrokenPipeError:
            self.log_message("Combo point thread: Broken pipe during combo point fetch.", "ERROR")
            self.root.after(0, self._handle_pipe_error, "Error fetching combo points")
            self.root.after(0, self._show_combo_points_result, None)
        except Exception as e:
            self.log_message(f"Combo point thread: Error fetching combo points: {e}", "ERROR")
            traceback.print_exc()
            self.root.after(0, self._show_combo_points_result, None)
        finally:
            self.log_message("Combo point thread: Scheduling button re-enable.", "DEBUG")
            if hasattr(self, 'test_cp_button') and self.test_cp_button.winfo_exists():
                 self.root.after(0, lambda btn=button_to_re_enable: btn.config(state=tk.NORMAL))
            self.log_message("Combo point thread: Finished.", "DEBUG")

    def _show_combo_points_result(self, combo_points):
        """Displays the combo points result in the main GUI thread."""
        self.log_message(f"GUI Update: Received combo points result: {combo_points}", "DEBUG")
        button_to_re_enable = self.test_cp_button

        if combo_points is None:
            # Error already logged by the thread or pipe handler
            messagebox.showerror("Error", "Failed to retrieve combo points. Pipe error or target lost? Check logs.")
        elif isinstance(combo_points, int):
            messagebox.showinfo("Combo Points", f"Current Combo Points: {combo_points}")
        else:
             # This case indicates a potential logic error in the DLL or communication protocol
             self.log_message(f"Received unexpected data type for combo points: {type(combo_points)} - {combo_points}", "ERROR")
             messagebox.showerror("Internal Error", f"Received unexpected data for combo points: {type(combo_points)}. Check logs.")

        # Re-enable button (might be redundant with finally block, but safe)
        if hasattr(self, 'test_cp_button') and self.test_cp_button.winfo_exists():
            button_to_re_enable.config(state=tk.NORMAL)
        self.log_message("GUI Update: Combo points result processed.", "DEBUG")

    # --- Add back add_rotation_rule ---
    def add_rotation_rule(self):
        """Adds or updates a rotation rule based on the input fields."""
        if self.rotation_running:
             messagebox.showerror("Error", "Stop the rotation before editing rules.")
             return

        action = self.action_dropdown.get()
        detail_str = ""
        detail_val: Any = None
        condition = self.condition_dropdown.get()
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
                detail_str = self.lua_code_var.get().strip()
                if not detail_str: raise ValueError("Lua Code cannot be empty.")
                detail_val = detail_str
            else:
                raise ValueError(f"Unknown rule action: {action}")

            # --- Get Condition Details --- 
            # Parse dynamic condition values based on selected condition
            if "< X" in condition or "> X" in condition or ">= X" in condition:
                val_str = self.condition_value_x_var.get().strip()
                if not val_str: raise ValueError(f"Value X is required for condition '{condition}'.")
                try: # Try float first, then int
                    value_x = float(val_str) 
                except ValueError:
                    raise ValueError(f"Value X ('{val_str}') must be a number.")
            elif "Between X-Y" in condition:
                x_str = self.condition_value_x_var.get().strip()
                y_str = self.condition_value_y_var.get().strip()
                if not x_str or not y_str: raise ValueError(f"Values X and Y are required for condition '{condition}'.")
                try:
                    value_x = float(x_str)
                    value_y = float(y_str)
                except ValueError:
                    raise ValueError(f"Values X ('{x_str}') and Y ('{y_str}') must be numbers.")
                if value_x >= value_y: raise ValueError("Value X must be less than Value Y for Between X-Y.")
            elif "Aura" in condition:
                cond_text = self.condition_text_var.get().strip()
                if not cond_text: 
                    req = "Aura Name/ID" if "Aura" in condition else "Spell ID"
                    raise ValueError(f"{req} is required for condition '{condition}'.")
                # Could add validation if Spell ID should be int here

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
            # Add conditional values if they exist
            if value_x is not None: rule['condition_value_x'] = value_x
            if value_y is not None: rule['condition_value_y'] = value_y
            if cond_text is not None: rule['condition_text'] = cond_text

            # --- Add or Update Rule in List --- 
            selected_indices = self.rule_listbox.curselection()
            if selected_indices:
                index_to_update = selected_indices[0]
                self.rotation_rules[index_to_update] = rule
                self.log_message(f"Updated rule at index {index_to_update}: {rule}", "DEBUG")
            else:
                self.rotation_rules.append(rule)
                self.log_message(f"Added new rule: {rule}", "DEBUG")

            # Update combat engine and listbox
            # No, don't auto-load here. Let user press Load from Editor button.
            # if self.combat_rotation: 
            #     self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.update_rule_listbox() 
            self.clear_rule_input_fields() # Clear inputs after successful add/update

            # --- Clear script if rules are modified --- 
            if self.combat_rotation:
                # Assuming CombatRotation has a method to clear loaded Lua scripts
                try:
                     # Replace self._clear_script() with the actual method if known
                     # Let's assume a method like clear_lua_script() exists
                    if hasattr(self.combat_rotation, 'clear_lua_script'):
                        self.combat_rotation.clear_lua_script()
                        self.log_message("Cleared active Lua script due to rule modification.", "DEBUG")
                    # else:
                        # Fallback/Placeholder if method name is different
                        # self.log_message("Rule modified: CombatRotation found, but clear_lua_script method missing. Script might remain active.", "WARN")
                        # We'll assume it doesn't exist or isn't needed if the attribute isn't found.
                except Exception as clear_err:
                    self.log_message(f"Error trying to clear Lua script after rule change: {clear_err}", "ERROR")
            # else:
            #      self.log_message("CombatRotation not initialized, cannot clear script state.", "WARN")
            
            # Also clear the dropdown selection to avoid confusion
            self.script_var.set("")

            self._update_button_states()

        except ValueError as e:
             messagebox.showerror("Input Error", str(e))
        except Exception as e:
             messagebox.showerror("Error", f"Failed to add/update rule: {e}")
             self.log_message(f"Error adding/updating rule: {e}", "ERROR")
             traceback.print_exc()

    def remove_selected_rule(self):
        # Add the method body back
        if self.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before editing rules.")
            return
        indices = self.rule_listbox.curselection()
        if not indices:
             messagebox.showwarning("Selection Error", "Select a rule to remove.")
             return

        index_to_remove = indices[0]
        try:
            removed_rule = self.rotation_rules.pop(index_to_remove)
            self.log_message(f"Removed rule: {removed_rule}", "DEBUG")
            # Don't auto-load into engine on remove, let user choose via button
            # if self.combat_rotation: 
            #     self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.update_rule_listbox()
            self.clear_rule_input_fields() # Clear inputs after removal
            self._update_button_states()
        except IndexError:
            self.log_message(f"Error removing rule: Index {index_to_remove} out of range.", "ERROR")
        except Exception as e:
             self.log_message(f"Error removing rule: {e}", "ERROR")
             messagebox.showerror("Error", f"Could not remove rule: {e}")

    def move_rule_up(self):
        # Add the method body back
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] == 0: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index - 1, rule)
        # self.combat_rotation.load_rotation_rules(self.rotation_rules) # Don't auto-load
        self.update_rule_listbox(select_index=index - 1)

    def move_rule_down(self):
        # Add the method body back
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] >= len(self.rotation_rules) - 1: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index + 1, rule)
        # self.combat_rotation.load_rotation_rules(self.rotation_rules) # Don't auto-load
        self.update_rule_listbox(select_index=index + 1)

    def update_rule_listbox(self, select_index = -1):
        # Add the method body back
        """Repopulates the rule listbox and optionally selects an index."""
        self.rule_listbox.delete(0, tk.END)
        for i, rule in enumerate(self.rotation_rules):
            action = rule.get('action', '?')
            detail = rule.get('detail', '?')
            target = rule.get('target', '?')
            condition = rule.get('condition', 'None')
            cd = rule.get('cooldown', 0.0)
            value_x = rule.get('condition_value_x', None)
            value_y = rule.get('condition_value_y', None)
            cond_text = rule.get('condition_text', None)

            # Format detail based on action type
            if action == "Spell": detail_str = f"ID:{detail}"
            elif action == "Macro": detail_str = f"Macro:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Macro:'{detail}'"
            elif action == "Lua": detail_str = f"Lua:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Lua:'{detail}'"
            else: detail_str = str(detail)

            # Format condition string including dynamic values
            cond_str = condition
            if value_x is not None: cond_str = cond_str.replace(" X", f" {value_x}")
            if value_y is not None: cond_str = cond_str.replace("Y", f"{value_y}")
            if cond_text is not None: 
                # Add text for aura/spell ID conditions
                cond_str += f" ({cond_text})"
                
            cond_str_display = cond_str if len(cond_str) < 30 else cond_str[:27]+"..." # Adjust display length
            cd_str = f"{cd:.1f}s" if cd > 0 else "-"
            rule_str = f"{i+1:02d}| {action:<5} ({detail_str:<20}) -> {target:<9} | If: {cond_str_display:<30} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, rule_str)

        # Restore selection if index provided and valid
        if 0 <= select_index < len(self.rotation_rules):
            self.rule_listbox.selection_set(select_index)
            self.rule_listbox.activate(select_index)
            self.rule_listbox.see(select_index)
        else:
             # Keep selection cleared if index is invalid or not provided
             # self.clear_rule_input_fields() # Don't clear input just because list updated
             pass

    def save_rules_to_file(self):
        # Add the method body back
         if not self.rotation_rules:
              messagebox.showwarning("Save Error", "No rules defined in the editor to save.")
              return
         file_path = filedialog.asksaveasfilename(
              defaultextension=".json",
              filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
              initialdir="Rules", # Start in Rules directory
              title="Save Rotation Rules As"
         )
         
         # Check if user cancelled
         if not file_path:
             self.log_message("Save operation cancelled.", "INFO")
             return

         # Write the rules to the file
         try:
             # Ensure the directory exists
             save_dir = os.path.dirname(file_path)
             if save_dir and not os.path.exists(save_dir):
                 os.makedirs(save_dir)
                 self.log_message(f"Created directory: {save_dir}", "INFO")
                 
             with open(file_path, 'w', encoding='utf-8') as f:
                 # Use json.dump to write the list of rules
                 json.dump(self.rotation_rules, f, indent=4) 
             
             self.log_message(f"Saved {len(self.rotation_rules)} rules to {file_path}", "INFO")
             # Refresh the dropdown list to include the new file
             self.populate_script_dropdown()
             messagebox.showinfo("Save Successful", f"Saved {len(self.rotation_rules)} rules to:\n{os.path.basename(file_path)}")

         except Exception as e:
             error_msg = f"Failed to save rules to {file_path}: {e}"
             self.log_message(error_msg, "ERROR")
             messagebox.showerror("Save Error", error_msg)

    # --- Add back lookup_spell_info --- 
    def lookup_spell_info(self):
        if not self.game or not self.game.is_ready():
            messagebox.showerror("Error", "Game Interface not ready. Cannot get spell info.")
            return # Correct Indentation

        spell_id_str = simpledialog.askstring("Lookup Spell", "Enter Spell ID:", parent=self.root)
        if not spell_id_str: return
        try:
            spell_id = int(spell_id_str)
            if spell_id <= 0: raise ValueError("Spell ID must be positive.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Spell ID must be a positive integer.")
            return

        info = self.game.get_spell_info(spell_id)
        if info:
            info_lines = [f"Spell ID: {spell_id}"]
            # Define power map inside or retrieve from WowObject if accessible
            power_map = {
                WowObject.POWER_MANA: "Mana", WowObject.POWER_RAGE: "Rage",
                WowObject.POWER_FOCUS: "Focus", WowObject.POWER_ENERGY: "Energy",
                WowObject.POWER_RUNIC_POWER: "Runic Power", -1: "N/A"
            }
            for key, value in info.items():
                 if value is not None:
                      # Format values nicely for display
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
                      # Format key nicely
                      key_str = ''.join(' ' + c if c.isupper() else c for c in key).lstrip().title()
                      info_lines.append(f"{key_str}: {value_str}")
                      
            messagebox.showinfo(f"Spell Info: {info.get('name', spell_id)}", "\n".join(info_lines))
            self.log_message(f"Looked up Spell ID {spell_id}: {info.get('name', 'N/A')}", "DEBUG")
        else:
            messagebox.showwarning("Spell Lookup", f"Could not find information for Spell ID {spell_id}.\nCheck DLL logs or if the ID is valid.")
            self.log_message(f"Spell info lookup failed for ID {spell_id}", "WARN")

    def format_hp_energy(self, current, max_val, power_type=-1):
        # Add the method body back
        try:
            # Convert to int, handling potential None or non-numeric values
            current_int = int(current) if current is not None and str(current).isdigit() else 0
            max_int = int(max_val) if max_val is not None and str(max_val).isdigit() else 0

            if power_type == WowObject.POWER_ENERGY and max_int <= 0: max_int = 100 # Default max energy if missing
            if max_int <= 0: return f"{current_int}/?" # Avoid division by zero
            pct = (current_int / max_int) * 100
            return f"{current_int}/{max_int} ({pct:.0f}%)"
        except (ValueError, TypeError) as e:
            logging.warning(f"Error formatting HP/Energy (current={current}, max={max_val}, type={power_type}): {e}")
            current_disp = str(current) if current is not None else '?'
            max_disp = str(max_val) if max_val is not None else '?'
            return f"{current_disp}/{max_disp} (?%)" # Fallback display

    def calculate_distance(self, obj: Optional[WowObject]) -> float:
        # Add the method body back
        # Ensure OM, player, and obj are valid and have position attributes
        if not self.om or not self.om.local_player or not obj:
            return -1.0

        player = self.om.local_player
        required_attrs = ['x_pos', 'y_pos', 'z_pos']
        if not all(hasattr(player, attr) for attr in required_attrs) or \
           not all(hasattr(obj, attr) for attr in required_attrs):
            # Log only once or less frequently if this becomes noisy
            # logging.debug(f"Missing position attribute for distance calc: player or obj {getattr(obj, 'guid', '?')}")
            return -1.0

        try:
            # Ensure positions are numbers
            px, py, pz = float(player.x_pos), float(player.y_pos), float(player.z_pos)
            ox, oy, oz = float(obj.x_pos), float(obj.y_pos), float(obj.z_pos)

            dx = px - ox
            dy = py - oy
            dz = pz - oz

            # Calculate 3D distance
            dist_3d = math.sqrt(dx*dx + dy*dy + dz*dz)
            return dist_3d
        except (TypeError, ValueError) as e:
             # This error suggests position attributes are not numbers
             logging.error(f"Type/Value error calculating distance between {player.guid} and {obj.guid}: {e}. Pos Player:({player.x_pos},{player.y_pos},{player.z_pos}), Pos Obj:({obj.x_pos},{obj.y_pos},{obj.z_pos})")
             return -1.0
        except Exception as e:
             logging.exception(f"Unexpected error calculating distance: {e}")
             return -1.0

    def update_data(self):
        # Add the method body back
        """Periodically updates displayed data and attempts core initialization if needed."""
        # Check if closing
        if self.is_closing: return

        core_ready = False
        status_text = "Initializing..."

        # --- Core Initialization Check/Retry ---
        if not (self.mem and self.mem.is_attached() and self.om and self.om.is_ready() and self.game and self.game.is_ready()):
             status_text = "Connecting..."
             if not self.core_init_attempting:
                 now = time.time()
                 # Determine retry interval: faster if disconnected, slower if connected (but failed)
                 retry_interval = CORE_INIT_RETRY_INTERVAL_FAST if not core_ready else CORE_INIT_RETRY_INTERVAL_SLOW
                 if now > self.last_core_init_attempt + retry_interval:
                      self.log_message(f"Attempting core initialization (WoW running? DLL injected?)...", "INFO")
                      self.core_init_attempting = True
                      self.last_core_init_attempt = now # Record attempt time
                      init_thread = threading.Thread(target=self.connect_and_init_core, daemon=True)
                      init_thread.start()
                 else: # Waiting for retry interval
                      wait_time = int(retry_interval - (now - self.last_core_init_attempt))
                      status_text = f"Connection failed. Retrying in {max(0, wait_time)}s..."
             # else: still attempting, status_text remains "Connecting..."
        else: # Core components seem ready
             core_ready = True
             status_text = "Connected"
             try:
                  # Refresh data only if connected and OM exists
                  if self.om:
                      self.om.refresh()
                  else:
                       raise RuntimeError("Object Manager not initialized despite core_ready being True.")
             except Exception as e:
                  self.log_message(f"Error during ObjectManager refresh: {e}", "ERROR")
                  traceback.print_exc() # Log full traceback
                  core_ready = False # Mark as not ready if refresh fails
                  status_text = "Error Refreshing OM"
                  # Attempt to disconnect/reset core components on major error?
                  # self.disconnect_core_components() # Example of a potential reset function


        # --- Update Monitor Tab ---
        if core_ready and self.om and self.om.local_player: # Check OM exists
            player = self.om.local_player
            p_name = player.get_name() or "Unknown"
            status_text += f" | Player: {p_name} Lvl:{player.level}"
            self.player_name_var.set(p_name)
            self.player_level_var.set(str(player.level))
            self.player_hp_var.set(self.format_hp_energy(player.health, player.max_health))
            self.player_energy_var.set(self.format_hp_energy(player.energy, player.max_energy, player.power_type))
            self.player_pos_var.set(f"({player.x_pos:.1f}, {player.y_pos:.1f}, {player.z_pos:.1f})")
            # Build status string from individual boolean attributes - REVISED
            p_flags = []
            if hasattr(player, 'is_casting') and player.is_casting: p_flags.append("Casting")
            if hasattr(player, 'is_channeling') and player.is_channeling: p_flags.append("Channeling")
            if hasattr(player, 'is_dead') and player.is_dead: p_flags.append("Dead")
            if hasattr(player, 'is_stunned') and player.is_stunned: p_flags.append("Stunned")
            # Add other relevant flags if they exist (e.g., is_in_combat)
            # if hasattr(player, 'is_in_combat') and player.is_in_combat: p_flags.append("Combat")
            self.player_status_var.set(", ".join(p_flags) if p_flags else "Idle")
        else:
            # Reset player info if not ready or player is None
            self.player_name_var.set("N/A")
            self.player_level_var.set("N/A")
            self.player_hp_var.set("N/A")
            self.player_energy_var.set("N/A")
            self.player_pos_var.set("N/A")
            self.player_status_var.set("N/A")

        if core_ready and self.om and self.om.target: # Check OM exists
            target = self.om.target
            t_name = target.get_name() or "Unknown"
            dist = self.calculate_distance(target)
            dist_str = f"{dist:.1f}y" if dist >= 0 else "N/A"
            status_text += f" | Target: {t_name} ({dist_str})"
            self.target_name_var.set(t_name)
            self.target_level_var.set(str(target.level))
            self.target_hp_var.set(self.format_hp_energy(target.health, target.max_health))
            # Correctly display target power only if it's mana and max>0
            if target.power_type == WowObject.POWER_MANA and getattr(target, 'max_energy', 0) > 0:
                self.target_energy_var.set(self.format_hp_energy(target.energy, target.max_energy, target.power_type))
            else: 
                self.target_energy_var.set("N/A") # Set to N/A if not mana or max is 0
            self.target_pos_var.set(f"({target.x_pos:.1f}, {target.y_pos:.1f}, {target.z_pos:.1f})")
            # Build status string from individual boolean attributes for target - REVISED
            t_flags = []
            if hasattr(target, 'is_casting') and target.is_casting: t_flags.append("Casting")
            if hasattr(target, 'is_channeling') and target.is_channeling: t_flags.append("Channeling")
            if hasattr(target, 'is_dead') and target.is_dead: t_flags.append("Dead")
            if hasattr(target, 'is_stunned') and target.is_stunned: t_flags.append("Stunned")
            # if hasattr(target, 'is_in_combat') and target.is_in_combat: t_flags.append("Combat")
            self.target_status_var.set(", ".join(t_flags) if t_flags else "Idle")
            self.target_dist_var.set(dist_str)
        else:
            # Reset target info if not ready or target is None
            self.target_name_var.set("N/A")
            self.target_level_var.set("N/A")
            self.target_hp_var.set("N/A")
            self.target_energy_var.set("N/A")
            self.target_pos_var.set("N/A")
            self.target_status_var.set("N/A")
            self.target_dist_var.set("N/A")

        # --- Update Object Tree ---
        if core_ready and self.om: # Check OM exists
            self.update_monitor_treeview() # CALL the dedicated update method
        # REMOVE the old inline tree update logic

        # Update Status Bar
        self.status_var.set(status_text)
        self._update_button_states()

        # Check if rotation thread has finished
        if self.rotation_thread is not None and not self.rotation_thread.is_alive():
             self.log_message("Detected rotation thread is no longer alive. Cleaning up.", "DEBUG")
             if self.root.winfo_exists():
                  self.root.after(0, self._on_rotation_thread_exit)

        # Schedule next update only if not closing
        if not self.is_closing:
             try:
                 # Check if root window exists before scheduling
                 if self.root.winfo_exists():
                     self.update_job = self.root.after(UPDATE_INTERVAL_MS, self.update_data)
             except tk.TclError:
                  # This can happen if the window is destroyed between checks
                  self.log_message("Root window destroyed before next update could be scheduled.", "DEBUG")
                  self.is_closing = True # Ensure we stop trying

    # --- Add back load_rules_from_file --- 
    def load_rules_from_file(self):
        if self.rotation_running:
            messagebox.showerror("Load Error", "Stop the rotation before loading new rules.")
            return
        file_path = filedialog.askopenfilename(
            # Corrected the filetypes list syntax
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")], 
            title="Load Rotation Rules",
            initialdir="Rules" # Suggest Rules directory
        )
        if not file_path: return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_rules = json.load(f)
            if not isinstance(loaded_rules, list):
                raise ValueError("Invalid format: JSON root must be a list of rules.")
            # TODO: Add validation for individual rule structure?

            # Update the editor's internal list and the listbox
            self.rotation_rules = loaded_rules
            self.update_rule_listbox()
            self.clear_rule_input_fields() # Clear input fields after load

            # Clear any loaded script information (if rules are loaded)
            if hasattr(self.combat_rotation, 'clear_lua_script'):
                self.combat_rotation.clear_lua_script()
            else:
                self.log_message("Warning: CombatRotation has no clear_lua_script method.", "WARN")
            self.script_var.set("") # Clear the file dropdown selection

            self.log_message(f"Loaded {len(self.rotation_rules)} rules from: {file_path} into editor.", "INFO")
            self._update_button_states()
            messagebox.showinfo("Load Successful", f"Loaded {len(self.rotation_rules)} rules into editor from:\n{os.path.basename(file_path)}")
            # Note: These rules are now in the editor, but NOT yet active in the rotation engine.
            # User must click "Load Rules from Editor" on the Control tab to activate them.

        except json.JSONDecodeError as e:
            self.log_message(f"Error decoding JSON from {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
        except ValueError as e:
            self.log_message(f"Error validating rules file {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
        except Exception as e:
            self.log_message(f"Error loading rules from {file_path}: {e}", "ERROR")
            messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")

    # --- Add back clear_log_text --- 
    def clear_log_text(self):
        """Clears all text from the log ScrolledText widget."""
        if hasattr(self, 'log_text') and self.log_text:
            try:
                # Check if widget exists before configuring
                if self.log_text.winfo_exists(): 
                    self.log_text.config(state='normal')
                    self.log_text.delete('1.0', tk.END)
                    self.log_text.config(state='disabled')
            except tk.TclError as e:
                 # Use original stderr as logger might be involved
                 print(f"Error clearing log text (widget likely destroyed): {e}", file=sys.stderr) 
            except Exception as e:
                 print(f"Unexpected error clearing log text: {e}", file=sys.stderr)
                 traceback.print_exc(file=sys.stderr)

    # --- Add back _finalize_core_init_attempt --- 
    def _finalize_core_init_attempt(self, success: bool):
         """Called in main thread after core init attempt finishes."""
         self.core_init_attempting = False # Reset flag
         # --- ADDED: Update core_initialized based on result --- #
         self.core_initialized = success
         if success:
             self.log_message("Core initialization successful (finalized).", "INFO")
         else:
             self.log_message("Core initialization failed (finalized).", "WARN")
         # ---------------------------------------------------- #
         self._update_button_states() # Update GUI based on new state

    # --- Add back update_monitor_treeview --- 
    def update_monitor_treeview(self):
        try:
            # Ensure OM and tree exist before proceeding
            if not self.om or not self.om.is_ready() or not hasattr(self, 'tree') or not self.tree.winfo_exists():
                 # logging.debug("OM or Treeview not ready for update or destroyed.")
                 return

            # Build a map of which object types to display based on filter vars
            type_filter_map = {
                WowObject.TYPE_PLAYER: self.filter_show_players_var.get(),
                WowObject.TYPE_UNIT: self.filter_show_units_var.get(),
                # WowObject.TYPE_GAMEOBJECT: self.filter_show_gameobjects_var.get(), # Removed
                # WowObject.TYPE_DYNAMICOBJECT: self.filter_show_dynamicobj_var.get(), # Removed
                # WowObject.TYPE_CORPSE: self.filter_show_corpses_var.get(), # Removed
            }

            MAX_DISPLAY_DISTANCE = 100.0

            objects_in_om = self.om.get_objects()
            current_guids_in_tree = set(self.tree.get_children())
            processed_guids = set()

            for obj in objects_in_om:
                obj_type = getattr(obj, 'type', WowObject.TYPE_NONE)
                if not obj or not hasattr(obj, 'guid') or not type_filter_map.get(obj_type, False):
                    continue

                dist_val = self.calculate_distance(obj)
                if dist_val < 0 or dist_val > MAX_DISPLAY_DISTANCE:
                     continue

                guid_str = str(obj.guid) 
                processed_guids.add(guid_str)

                guid_hex = f"0x{obj.guid:X}"
                obj_type_str = obj.get_type_str() if hasattr(obj, 'get_type_str') else f"Type{obj_type}"
                name = obj.get_name()
                hp_str = self.format_hp_energy(getattr(obj, 'health', 0), getattr(obj, 'max_health', 0))
                power_str = self.format_hp_energy(getattr(obj, 'energy', 0), getattr(obj, 'max_energy', 0), getattr(obj, 'power_type', -1))
                dist_str = f"{dist_val:.1f}"
                status_str = "Dead" if getattr(obj, 'is_dead', False) else (
                    "Casting" if getattr(obj, 'is_casting', False) else (
                        "Channeling" if getattr(obj, 'is_channeling', False) else "Idle"
                    )
                )
                
                values = ( guid_hex, obj_type_str, name, hp_str, power_str, dist_str, status_str )

                try: 
                    if guid_str in current_guids_in_tree:
                        self.tree.item(guid_str, values=values)
                        self.tree.item(guid_str, tags=(obj_type_str.lower(),))
                    else:
                        self.tree.insert('', tk.END, iid=guid_str, values=values, tags=(obj_type_str.lower(),))
                except tk.TclError as e:
                    logging.warning(f"TclError updating/inserting item {guid_str} in tree: {e}")
                    break 

            # Remove old items
            guids_to_remove = current_guids_in_tree - processed_guids
            for guid_to_remove in guids_to_remove:
                try:
                    if self.tree.exists(guid_to_remove):
                         self.tree.delete(guid_to_remove)
                except tk.TclError as e:
                    logging.warning(f"TclError deleting item {guid_to_remove} from tree: {e}")
                    break 

        except Exception as e:
            logging.exception(f"Error updating monitor treeview: {e}")

    def _sort_treeview_column(self, col, reverse):
        # Add the pass statement back correctly indented
        pass

    # ADDED: Method to sync Lua code text widget with its variable
    def _on_lua_change(self, event=None):
        """Updates the lua_code_var when the ScrolledText widget changes."""
        try:
            if hasattr(self, 'lua_code_text') and self.lua_code_text.winfo_exists() and \
               hasattr(self, 'lua_code_var'):
                current_text = self.lua_code_text.get("1.0", tk.END).strip()
                self.lua_code_var.set(current_text)
        except tk.TclError:
            # Handle case where widget might be destroyed during update
            pass
        except Exception as e:
            self.log_message(f"Error updating lua_code_var: {e}", "ERROR")


# --- Log Redirector Class ---
class LogRedirector:
    """Redirects stdout/stderr to the GUI Log tab using a queue."""
    def __init__(self, text_widget, default_tag="INFO", tags=None): # Added tags param
        self.text_widget = text_widget
        self.default_tag = default_tag
        self.tags = tags or {} # Store tag configurations
        self.stdout_orig = sys.stdout
        self.stderr_orig = sys.stderr
        self.queue = queue.Queue()
        self.processing = False

    def write(self, message, tag=None):
        if not message.strip(): return
        final_tag = tag or (self.default_tag if self is sys.stdout else "ERROR") # Syntax fixed: added 'is'
        self.queue.put((str(message), final_tag))
        # Schedule processing only if the widget seems valid
        if hasattr(self.text_widget, 'after_idle') and self.text_widget.winfo_exists():
            try:
                self.text_widget.after_idle(self._process_queue)
            except tk.TclError: pass # Widget might be destroyed


    def _process_queue(self):
        if self.processing or not self.text_widget or not self.text_widget.winfo_exists():
            return
        self.processing = True
        try:
            while not self.queue.empty():
                try:
                    message, tag = self.queue.get_nowait()
                    self._insert_message(message, tag)
                except queue.Empty: break
                except Exception as e:
                    # Use original stderr for logging internal errors
                    print(f"Error processing log queue: {e}", file=self.stderr_orig)
                    traceback.print_exc(file=self.stderr_orig)
        finally:
            self.processing = False

    def _insert_message(self, message, tag):
        try:
            if not self.text_widget or not self.text_widget.winfo_exists():
                print("Log Widget destroyed:", message.strip(), file=self.stderr_orig)
                return # Correct Indentation

            self.text_widget.config(state=tk.NORMAL)
            timestamp = time.strftime("%H:%M:%S")

            # Use tag name for insertion, Tkinter handles missing tags gracefully
            display_tag = tag if tag in self.tags else self.default_tag

            # Insert timestamp (maybe always DEBUG color?)
            self.text_widget.insert(tk.END, f"{timestamp} ", ("DEBUG",))
            # Insert message with its determined tag
            self.text_widget.insert(tk.END, message.strip() + "\n", (display_tag,))

            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)

        except tk.TclError as e:
            print(f"GUI Log Widget TclError: {e}. Original: {message.strip()}", file=self.stderr_orig)
        except Exception as e:
            print(f"LogRedirector Error: {e}. Original: {message.strip()}", file=self.stderr_orig)
            traceback.print_exc(file=self.stderr_orig)


    def flush(self): pass # Required for file-like object interface

    def start_redirect(self):
        sys.stdout = self
        sys.stderr = self

    def stop_redirect(self):
        # Restore original streams only if they haven't been changed elsewhere
        if sys.stdout is self: sys.stdout = self.stdout_orig
        if sys.stderr is self: sys.stderr = self.stderr_orig


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = WowMonitorApp(root)
    root.mainloop()