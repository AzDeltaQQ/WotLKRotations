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

        # --- Initialize Filter Variables (Default: Show Units & Players) ---
        self.filter_show_units_var = tk.BooleanVar(value=True)
        self.filter_show_players_var = tk.BooleanVar(value=True)
        self.filter_show_gameobjects_var = tk.BooleanVar(value=False)
        self.filter_show_items_var = tk.BooleanVar(value=False)
        self.filter_show_containers_var = tk.BooleanVar(value=False)
        self.filter_show_dynamicobj_var = tk.BooleanVar(value=False)
        self.filter_show_corpses_var = tk.BooleanVar(value=False)

        # --- Initialize Editor Data ---
        self.rule_conditions = ["None", "Target Exists", "Target Attackable", "Is Casting", "Target Is Casting",
                                "Target < 20% HP", "Target < 35% HP", "Player < 30% HP", "Player < 50% HP",
                                "Rage > 30", "Energy > 40", "Mana > 80%", "Mana < 20%",
                                "Is Spell Ready", "Target Has Debuff", "Player Has Buff", "Is Moving",
                                "Combo Points >= 3", "Combo Points >= 5", "Is Stealthed"]
        self.rule_actions = ["Spell", "Macro", "Lua"]
        self.rule_targets = ["target", "player", "focus", "pet", "mouseover"]

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
        ttk.Label(script_frame, text="Load Lua Script:").pack(side=tk.LEFT, padx=5)
        self.script_var = tk.StringVar()
        self.script_dropdown = ttk.Combobox(script_frame, textvariable=self.script_var, state="readonly")
        self.script_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.script_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_selected_script())
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
            results = self.game.run_lua(lua_code)
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
        left_pane.rowconfigure(2, weight=1)

        define_frame = ttk.LabelFrame(left_pane, text="Define Rule", padding=(10, 5))
        define_frame.grid(row=0, column=0, sticky="new")
        define_frame.columnconfigure(1, weight=1)

        ttk.Label(define_frame, text="Action:").grid(row=0, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_action_var = tk.StringVar(value=self.rule_actions[0])
        self.rule_action_combo = ttk.Combobox(define_frame, textvariable=self.rule_action_var, values=self.rule_actions, state="readonly", width=10)
        self.rule_action_combo.grid(row=0, column=1, padx=5, pady=4, sticky=tk.W)
        self.rule_action_combo.bind("<<ComboboxSelected>>", self._update_rule_input_state)

        ttk.Label(define_frame, text="Detail:").grid(row=1, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_detail_frame = ttk.Frame(define_frame)
        self.rule_detail_frame.grid(row=1, column=1, padx=5, pady=4, sticky=tk.EW)
        self.rule_spell_id_var = tk.StringVar()
        self.rule_spell_id_entry = ttk.Entry(self.rule_detail_frame, textvariable=self.rule_spell_id_var, width=10)
        self.rule_macro_text_var = tk.StringVar()
        self.rule_macro_text_entry = ttk.Entry(self.rule_detail_frame, textvariable=self.rule_macro_text_var)
        self.rule_lua_code_var = tk.StringVar()
        self.rule_lua_code_entry = ttk.Entry(self.rule_detail_frame, textvariable=self.rule_lua_code_var)
        self.rule_spell_id_entry.pack(fill=tk.X, expand=True)

        ttk.Label(define_frame, text="Target:").grid(row=2, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_target_var = tk.StringVar(value=self.rule_targets[0])
        self.rule_target_combo = ttk.Combobox(define_frame, textvariable=self.rule_target_var, values=self.rule_targets, state="readonly", width=12)
        self.rule_target_combo.grid(row=2, column=1, padx=5, pady=4, sticky=tk.W)

        ttk.Label(define_frame, text="Condition:").grid(row=3, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_condition_var = tk.StringVar(value=self.rule_conditions[0])
        self.rule_condition_combo = ttk.Combobox(define_frame, textvariable=self.rule_condition_var, values=self.rule_conditions, state="readonly", width=25)
        self.rule_condition_combo.grid(row=3, column=1, padx=5, pady=4, sticky=tk.EW)

        ttk.Label(define_frame, text="Int. CD (s):").grid(row=4, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_cooldown_var = tk.StringVar(value="0.0")
        self.rule_cooldown_entry = ttk.Entry(define_frame, textvariable=self.rule_cooldown_var, width=10)
        self.rule_cooldown_entry.grid(row=4, column=1, padx=5, pady=4, sticky=tk.W)

        add_rule_button = ttk.Button(define_frame, text="Add/Update Rule", command=self.add_rotation_rule)
        add_rule_button.grid(row=5, column=0, columnspan=2, pady=(10, 5))

        lookup_frame = ttk.LabelFrame(left_pane, text="Spell Info", padding=(10, 5))
        lookup_frame.grid(row=1, column=0, sticky="new", pady=(10, 10))
        lookup_frame.columnconfigure(1, weight=1)
        self.scan_spellbook_button = ttk.Button(lookup_frame, text="List Known Spells...", command=self.scan_spellbook)
        self.scan_spellbook_button.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.lookup_spell_button = ttk.Button(lookup_frame, text="Lookup Spell ID...", command=self.lookup_spell_info)
        self.lookup_spell_button.grid(row=0, column=1, padx=5, pady=5, sticky="w")

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

        self._update_rule_input_state()

    def _update_rule_input_state(self, event=None):
        action_type = self.rule_action_var.get()
        self.rule_spell_id_entry.pack_forget()
        self.rule_macro_text_entry.pack_forget()
        self.rule_lua_code_entry.pack_forget()
        if action_type == "Spell":
            self.rule_spell_id_entry.pack(fill=tk.X, expand=True)
        elif action_type == "Macro":
            self.rule_macro_text_entry.pack(fill=tk.X, expand=True)
        elif action_type == "Lua":
            self.rule_lua_code_entry.pack(fill=tk.X, expand=True)

    def clear_rule_input_fields(self):
         self.rule_action_var.set(self.rule_actions[0])
         self.rule_spell_id_var.set("")
         self.rule_macro_text_var.set("")
         self.rule_lua_code_var.set("")
         self.rule_target_var.set(self.rule_targets[0])
         self.rule_condition_var.set(self.rule_conditions[0])
         self.rule_cooldown_var.set("0.0")
         self._update_rule_input_state()
         if self.rule_listbox.curselection():
              self.rule_listbox.selection_clear(self.rule_listbox.curselection()[0])


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
             self.rule_action_var.set(action)
             self._update_rule_input_state()
             if action == "Spell": self.rule_spell_id_var.set(str(detail))
             elif action == "Macro": self.rule_macro_text_var.set(str(detail))
             elif action == "Lua": self.rule_lua_code_var.set(str(detail))
             self.rule_target_var.set(target)
             self.rule_condition_var.set(condition)
             self.rule_cooldown_var.set(f"{cooldown:.1f}")
        except IndexError:
             self.log_message(f"Error: Selected index {index} out of range for rules.", "ERROR")
             self.clear_rule_input_fields()
        except Exception as e:
             self.log_message(f"Error loading selected rule: {e}", "ERROR")
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
        rotation_loadable = bool(self.rotation_rules or (self.loaded_script_path and os.path.exists(self.loaded_script_path)))
        is_rotation_running = self.rotation_thread is not None and self.rotation_thread.is_alive()

        self.start_button['state'] = tk.NORMAL if core_ready and rotation_loadable and not is_rotation_running else tk.DISABLED
        self.stop_button['state'] = tk.NORMAL if is_rotation_running else tk.DISABLED
        self.test_cp_button['state'] = tk.NORMAL if core_ready else tk.DISABLED
        self.run_lua_button['state'] = tk.NORMAL if core_ready else tk.DISABLED

        # Status Label update (requires self.rotation_status_label) - Simplified for now
        # Need to ensure self.rotation_status_label is defined, maybe in control tab?
        # Let's focus on fixing the crash first.


    def populate_script_dropdown(self):
        scripts_dir = "Scripts"
        try:
            if not os.path.exists(scripts_dir): os.makedirs(scripts_dir)
            scripts = sorted([f for f in os.listdir(scripts_dir) if f.endswith('.lua')])
            if scripts:
                self.script_dropdown['values'] = scripts
                if self.loaded_script_path and os.path.basename(self.loaded_script_path) in scripts:
                     self.script_var.set(os.path.basename(self.loaded_script_path))
                elif scripts: # Select first if no last script or last script invalid
                     self.script_var.set(scripts[0])
                self.script_dropdown.config(state="readonly")
            else:
                self.script_dropdown['values'] = []
                self.script_var.set("No *.lua scripts found in Scripts/")
                self.script_dropdown.config(state=tk.DISABLED)
        except Exception as e:
            self.log_message(f"Error populating script dropdown: {e}", "ERROR")
            self.script_dropdown['values'] = []
            self.script_var.set("Error loading scripts")
            self.script_dropdown.config(state=tk.DISABLED)
        self._update_button_states()


    def load_selected_script(self):
        if self.rotation_running:
            messagebox.showerror("Error", "Stop the rotation before loading a new script.")
            return
        if not self.combat_rotation:
             messagebox.showerror("Error", "Combat Rotation engine not initialized.")
             return

        selected_script = self.script_var.get()
        scripts_dir = "Scripts"
        if selected_script and not selected_script.startswith("No ") and not selected_script.startswith("Error "):
            script_path = os.path.join(scripts_dir, selected_script)
            if os.path.exists(script_path):
                if self.combat_rotation and self.combat_rotation.load_rotation_script(script_path): # Check combat_rotation exists
                    self.loaded_script_path = script_path
                    self.rotation_rules = [] # Clear editor rules
                    self.update_rule_listbox()
                    self.log_message(f"Loaded rotation script: {script_path}", "INFO")
                    messagebox.showinfo("Script Loaded", f"Loaded script:\n{selected_script}")
                    # if hasattr(self, 'rules_info_label'): self.rules_info_label.config(text="Script loaded, rules cleared.") # Requires rules_info_label
                else:
                    messagebox.showerror("Load Error", f"Failed to load script content or Combat Rotation not ready:\n{script_path}")
                    self.loaded_script_path = None
            else:
                 messagebox.showerror("Load Error", f"Script file not found:\n{script_path}")
                 self.loaded_script_path = None
                 self.script_var.set("")
                 self.populate_script_dropdown()
        else:
            messagebox.showwarning("Load Warning", "Please select a valid script file.")
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

        using_rules = bool(self.combat_rotation.rotation_rules)
        using_script = bool(self.combat_rotation.lua_script_content)

        if using_rules:
            self.log_message("Starting rotation using loaded rules.", "INFO")
        elif using_script:
            script_name = os.path.basename(self.combat_rotation.current_rotation_script_path or "Unknown Script")
            self.log_message(f"Starting rotation using Lua script: {script_name}", "INFO")
        else:
            self.log_message("No rotation rules or script loaded.", "WARN")
            messagebox.showwarning("Warning", "No rotation rules or script loaded to start.")
            return

        self.stop_rotation_flag.clear()
        self.rotation_thread = threading.Thread(target=self._rotation_loop, daemon=True)
        self.rotation_thread.start()
        self._update_button_states()

    def stop_rotation(self):
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
            self.log_message("Stopping rotation...", "INFO")
            self.stop_rotation_flag.set()
        else:
            self.log_message("Rotation not running.", "INFO")
        # Cleanup happens in _on_rotation_thread_exit when thread confirms exit


    def _rotation_loop(self):
        self.log_message("Rotation thread started.", "DEBUG")
        while not self.stop_rotation_flag.is_set():
            try:
                # Check core components are still valid within the loop
                if not (self.mem and self.mem.is_attached() and self.om and self.om.is_ready() and self.game and self.game.is_ready() and self.combat_rotation):
                    self.log_message("Rotation loop stopping: Core component(s) unavailable.", "WARN")
                    break # Exit loop if something disconnected

                self.combat_rotation.run()
                time.sleep(0.1) # Rotation tick rate

            except Exception as e:
                self.log_message(f"Error in rotation loop: {e}", "ERROR")
                traceback.print_exc() # Print full traceback to log
                break # Stop on error

        self.log_message("Rotation thread finishing.", "DEBUG")
        # Schedule GUI update in main thread
        if self.root.winfo_exists(): # Check if root window still exists
            self.root.after(0, self._on_rotation_thread_exit)


    def _on_rotation_thread_exit(self):
        """Callback executed in the main GUI thread after the rotation thread exits."""
        self.rotation_thread = None
        self.log_message("Rotation stopped.", "INFO")
        self._update_button_states() # Update buttons now thread is confirmed gone

    def add_rotation_rule(self):
        """Adds or updates a rotation rule based on the input fields."""
        if self.rotation_running:
             messagebox.showerror("Error", "Stop the rotation before editing rules.")
             return

        action = self.rule_action_var.get()
        detail_str = ""
        detail_val: Any = None

        try:
            if action == "Spell":
                detail_str = self.rule_spell_id_var.get().strip()
                if not detail_str.isdigit() or int(detail_str) <= 0:
                    raise ValueError("Spell ID must be a positive integer.")
                detail_val = int(detail_str)
            elif action == "Macro":
                detail_str = self.rule_macro_text_var.get().strip()
                if not detail_str: raise ValueError("Macro Text cannot be empty.")
                detail_val = detail_str
            elif action == "Lua":
                detail_str = self.rule_lua_code_var.get().strip()
                if not detail_str: raise ValueError("Lua Code cannot be empty.")
                detail_val = detail_str
            else:
                raise ValueError(f"Unknown rule action: {action}")

            target = self.rule_target_var.get()
            condition = self.rule_condition_var.get()
            cooldown_str = self.rule_cooldown_var.get().strip()
            cooldown = float(cooldown_str)
            if cooldown < 0: raise ValueError("Internal CD must be non-negative.")

            rule = {
                "action": action,
                "detail": detail_val, # Store parsed value (int for spell, str for others)
                "target": target,
                "condition": condition,
                "cooldown": cooldown
            }

            # Check if a rule is selected for update
            selected_indices = self.rule_listbox.curselection()
            if selected_indices:
                index_to_update = selected_indices[0]
                self.rotation_rules[index_to_update] = rule
                self.log_message(f"Updated rule at index {index_to_update}: {rule}", "DEBUG")
            else:
                self.rotation_rules.append(rule)
                self.log_message(f"Added new rule: {rule}", "DEBUG")

            # Update combat engine and listbox
            if self.combat_rotation: # Check if engine exists before loading
                self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.update_rule_listbox()
            self.clear_rule_input_fields() # Clear inputs after successful add/update

            # Clear script if rules are modified
            self._clear_script()
            self.script_var.set("")

            self._update_button_states()

        except ValueError as e:
             messagebox.showerror("Input Error", str(e))
        except Exception as e:
             messagebox.showerror("Error", f"Failed to add/update rule: {e}")
             self.log_message(f"Error adding/updating rule: {e}", "ERROR")


    def remove_selected_rule(self):
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
            if self.combat_rotation: # Update engine
                self.combat_rotation.load_rotation_rules(self.rotation_rules)
            self.update_rule_listbox()
            self.clear_rule_input_fields() # Clear inputs after removal
            self._update_button_states()
        except IndexError:
            self.log_message(f"Error removing rule: Index {index_to_remove} out of range.", "ERROR")
        except Exception as e:
             self.log_message(f"Error removing rule: {e}", "ERROR")
             messagebox.showerror("Error", f"Could not remove rule: {e}")


    def move_rule_up(self):
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] == 0: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index - 1, rule)
        self.combat_rotation.load_rotation_rules(self.rotation_rules)
        self.update_rule_listbox(select_index=index - 1) # Pass new index

    def move_rule_down(self):
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] >= len(self.rotation_rules) - 1: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index + 1, rule)
        self.combat_rotation.load_rotation_rules(self.rotation_rules)
        self.update_rule_listbox(select_index=index + 1) # Pass new index


    def update_rule_listbox(self, select_index = -1):
        """Repopulates the rule listbox and optionally selects an index."""
        self.rule_listbox.delete(0, tk.END)
        for i, rule in enumerate(self.rotation_rules):
            action = rule.get('action', '?')
            detail = rule.get('detail', '?')
            target = rule.get('target', '?')
            condition = rule.get('condition', 'None')
            cd = rule.get('cooldown', 0.0)

            # Format detail based on action type
            if action == "Spell": detail_str = f"ID:{detail}"
            elif action == "Macro": detail_str = f"Macro:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Macro:'{detail}'"
            elif action == "Lua": detail_str = f"Lua:'{str(detail)[:15]}..'" if len(str(detail)) > 15 else f"Lua:'{detail}'"
            else: detail_str = str(detail)

            cond_str = condition if len(condition) < 25 else condition[:22]+"..."
            cd_str = f"{cd:.1f}s" if cd > 0 else "-"
            rule_str = f"{i+1:02d}| {action:<5} ({detail_str:<20}) -> {target:<9} | If: {cond_str:<25} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, rule_str)

        # Restore selection if index provided and valid
        if 0 <= select_index < len(self.rotation_rules):
            self.rule_listbox.selection_set(select_index)
            self.rule_listbox.activate(select_index)
            self.rule_listbox.see(select_index)
        else:
             self.clear_rule_input_fields() # Clear input if selection is lost/invalidated


    def save_rules_to_file(self):
         if not self.rotation_rules:
              messagebox.showwarning("Save Error", "No rules defined in the editor to save.")
              return
         file_path = filedialog.asksaveasfilename(
              defaultextension=".json",
              filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
              title="Save Rotation Rules As",
              initialdir="Rules" # Suggest Rules directory
         )
         if not file_path: return

         # Ensure directory exists
         os.makedirs(os.path.dirname(file_path), exist_ok=True)

         try:
              with open(file_path, 'w', encoding='utf-8') as f:
                   json.dump(self.rotation_rules, f, indent=2)
              self.log_message(f"Rotation rules saved to: {file_path}", "INFO")
              messagebox.showinfo("Save Successful", f"Saved {len(self.rotation_rules)} rules to:\n{os.path.basename(file_path)}")
         except Exception as e:
              self.log_message(f"Error saving rules to {file_path}: {e}", "ERROR")
              messagebox.showerror("Save Error", f"Failed to save rules:\n{e}")

    def load_rules_from_file(self):
         if self.rotation_running:
              messagebox.showerror("Load Error", "Stop the rotation before loading new rules.")
              return
         file_path = filedialog.askopenfilename(
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

              self.rotation_rules = loaded_rules
              if self.combat_rotation: # Ensure combat engine exists
                    self.combat_rotation.load_rotation_rules(self.rotation_rules)
              self.update_rule_listbox()

              self._clear_script()
              self.script_var.set("")

              self.log_message(f"Loaded {len(self.rotation_rules)} rules from: {file_path}", "INFO")
              # if hasattr(self, 'rules_info_label'): self.rules_info_label.config(text=f"{len(self.rotation_rules)} rules loaded from file.") # Requires rules_info_label
              self._update_button_states()
              messagebox.showinfo("Load Successful", f"Loaded {len(self.rotation_rules)} rules from:\n{os.path.basename(file_path)}")

         except json.JSONDecodeError as e:
              self.log_message(f"Error decoding JSON from {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
         except ValueError as e:
              self.log_message(f"Error validating rules file {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
         except Exception as e:
              self.log_message(f"Error loading rules from {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")


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
            return # Correct Indentation

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

        # Function to populate treeview, run in thread? No, IPC calls are fast enough.
        def populate_tree():
            count = 0
            max_to_fetch = 500
            for spell_id in sorted(spell_ids):
                if count >= max_to_fetch:
                    tree.insert("", tk.END, values=(f"({len(spell_ids)-max_to_fetch} more)", "...", "..."))
                    break
                info = self.game.get_spell_info(spell_id)
                if info:
                    name = info.get("name", "N/A")
                    rank = info.get("rank", "")
                    tree.insert("", tk.END, values=(spell_id, name, rank))
                else:
                    tree.insert("", tk.END, values=(spell_id, "(Info Failed)", ""))
                count += 1
                # Maybe update periodically if very slow? No, likely fast.
            # scan_window.update_idletasks() # Update after loop

        # Populate directly for simplicity now
        populate_tree()

        def copy_id():
            selected_item = tree.focus()
            if selected_item:
                item_data = tree.item(selected_item)
                spell_id_to_copy = item_data['values'][0]
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(str(spell_id_to_copy))
                    self.log_message(f"Copied Spell ID: {spell_id_to_copy}", "DEBUG")
                except Exception as e:
                     messagebox.showerror("Clipboard Error", f"Could not copy to clipboard:\n{e}", parent=scan_window) # Set parent

        copy_button = ttk.Button(scan_window, text="Copy Selected Spell ID", command=copy_id)
        copy_button.pack(pady=5)


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
                      if key == "castTime" and isinstance(value, (int, float)):
                           value_str = f"{value / 1000.0:.2f}s ({value}ms)" if value > 0 else "Instant"
                      elif key in ["minRange", "maxRange"] and isinstance(value, (int, float)):
                           value_str = f"{value:.1f} yd"
                      elif key == "cost" and isinstance(value, (int, float)):
                           value_str = f"{value:.0f}"
                      elif key == "powerType" and isinstance(value, int):
                           value_str = power_map.get(value, f"Type {value}")
                      else: value_str = str(value)
                      key_str = ''.join(' ' + c if c.isupper() else c for c in key).lstrip().title()
                      info_lines.append(f"{key_str}: {value_str}")
            messagebox.showinfo(f"Spell Info: {info.get('name', spell_id)}", "\n".join(info_lines))
            self.log_message(f"Looked up Spell ID {spell_id}: {info.get('name', 'N/A')}", "DEBUG")
        else:
            messagebox.showwarning("Spell Lookup", f"Could not find information for Spell ID {spell_id}.\nCheck DLL logs or if the ID is valid.")
            self.log_message(f"Spell info lookup failed for ID {spell_id}", "WARN")


    def format_hp_energy(self, current, max_val, power_type=-1):
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
                 if now > self.last_core_init_attempt + CORE_INIT_RETRY_INTERVAL_S:
                      self.log_message(f"Attempting core initialization (WoW running? DLL injected?)...", "INFO")
                      self.core_init_attempting = True
                      self.last_core_init_attempt = now # Record attempt time
                      init_thread = threading.Thread(target=self.connect_and_init_core, daemon=True)
                      init_thread.start()
                 else: # Waiting for retry interval
                      wait_time = int(CORE_INIT_RETRY_INTERVAL_S - (now - self.last_core_init_attempt))
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
            if target.power_type == WowObject.POWER_MANA and target.max_energy > 0:
                self.target_energy_var.set(self.format_hp_energy(target.energy, target.max_energy, target.power_type))
            else: self.target_energy_var.set("N/A")
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
        # REMOVE the old inline tree update logic below
        #     selected_guid = None
        #     selected_item = self.tree.focus()
        #     ... (rest of the old logic deleted) ...
        #     # Re-select the item if it still exists
        #     if new_selection_item:
        #         try: # Wrap selection in try/except
        #             self.tree.selection_set(new_selection_item)
        #             self.tree.focus(new_selection_item)
        #             self.tree.see(new_selection_item)
        #         except tk.TclError: pass # Ignore if item deleted before selection


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


    def on_closing(self):
        if self.is_closing: return
        self.is_closing = True
        self.log_message("Closing application...", "INFO")
        if self.update_job:
            self.root.after_cancel(self.update_job)
            self.update_job = None
        # Signal rotation thread to stop if running
        if self.rotation_thread is not None and self.rotation_thread.is_alive():
             self.log_message("Signaling rotation thread to stop...", "INFO")
             self.stop_rotation_flag.set()
             # Give it a moment to stop? Or just proceed with save/destroy?
             # Let's proceed, the thread is daemonized anyway.
        self._save_config()
        # Restore stdout/stderr? Only if LogRedirector is active
        if self.log_redirector:
            self.log_message("Restoring standard output streams.", "DEBUG")
            self.log_redirector.stop_redirect()
        print("Cleanup finished. Exiting.") # Print to original stdout
        self.root.destroy()

    def connect_and_init_core(self) -> bool:
        """Attempts to connect to WoW, initialize core components, and connect IPC."""
        # This method now runs in a thread, use self.log_message for GUI logging
        success = False
        try:
            self.log_message("Attempting core initialization...", "DEBUG") # Use log_message

            # 1. Memory Handler
            if not self.mem or not self.mem.is_attached():
                self.mem = MemoryHandler()
                if not self.mem.is_attached():
                    self.log_message(f"Failed to attach to WoW process ({PROCESS_NAME}).", "ERROR")
                    return False
                self.log_message(f"Attached to WoW process ({PROCESS_NAME}).", "INFO")

            # 2. Object Manager
            if not self.om or not self.om.is_ready():
                self.om = ObjectManager(self.mem)
                if not self.om.is_ready():
                    self.log_message("Failed to initialize Object Manager (Check ClientConnection/Offsets?).", "ERROR")
                    return False
                self.log_message("Object Manager initialized.", "INFO")

            # 3. Game Interface
            if not self.game:
                self.game = GameInterface(self.mem)
                self.log_message("Game Interface (IPC) created.", "INFO")

            # 4. IPC Pipe Connection
            if not self.game.is_ready():
                if self.game.connect_pipe():
                     self.log_message("IPC Pipe connected successfully.", "INFO")
                else:
                     self.log_message("Failed to connect IPC Pipe (Is DLL injected and running?).", "ERROR")
                     return False

            # 5. Target Selector
            if not self.target_selector:
                self.target_selector = TargetSelector(self.om)
                self.log_message("Target Selector initialized.", "INFO")

            # 6. Combat Rotation
            if not self.combat_rotation:
                 self.combat_rotation = CombatRotation(self.mem, self.om, self.game)
                 self.log_message("Combat Rotation engine initialized.", "INFO")

            success = True
            self.log_message("Core components initialized successfully.", "INFO")

        except Exception as e:
            # Use log_message here as well
            self.log_message(f"Error during core initialization: {e}", "ERROR")
            # Use print_exc which goes through the redirected stderr (LogRedirector)
            traceback.print_exc()
            success = False
        finally:
            # This runs in the init thread, signal main thread to potentially update state
             if self.root.winfo_exists():
                  self.root.after(0, self._finalize_core_init_attempt)

        return success # Return status (though it's mainly handled by _finalize)

    def _finalize_core_init_attempt(self):
         """Called in main thread after core init attempt finishes."""
         self.core_init_attempting = False # Reset flag
         self._update_button_states() # Update GUI based on new state


    def clear_log_text(self):
        """Clears all text from the log ScrolledText widget."""
        if hasattr(self, 'log_text') and self.log_text:
            try:
                self.log_text.config(state='normal')
                self.log_text.delete('1.0', tk.END)
                self.log_text.config(state='disabled')
            except tk.TclError as e:
                 print(f"Error clearing log text (widget likely destroyed): {e}", file=sys.stderr) # Use original stderr
            except Exception as e:
                 print(f"Unexpected error clearing log text: {e}", file=sys.stderr)
                 traceback.print_exc(file=sys.stderr)

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
            self._clear_script()
            self.script_var.set("")

            # Update status and buttons
            messagebox.showinfo("Rules Loaded", f"{len(self.rotation_rules)} rules from the editor are now active.")
            self._update_button_states()

        except Exception as e:
            error_msg = f"Error loading rules from editor: {e}"
            self.log_message(error_msg, "ERROR")
            messagebox.showerror("Load Error", error_msg)

    def _clear_script(self):
         """Helper to clear loaded script path and combat engine script."""
         if self.combat_rotation and hasattr(self.combat_rotation, '_clear_script'):
              self.combat_rotation._clear_script()
         self.loaded_script_path = None
         # Don't clear self.script_var here, let calling function decide

    def test_get_combo_points(self):
        """Starts a background thread to fetch combo points without freezing the GUI."""
        # Corrected check: use is_ready()
        if not self.game or not self.game.is_ready():
            messagebox.showwarning("Not Ready", "Game interface not connected.")
            return

        # Corrected log call
        self.log_message("Starting combo point fetch thread...", "DEBUG")
        # Disable button while fetching (optional, but good practice)
        self.test_cp_button.config(state=tk.DISABLED)

        # Create and start the thread
        thread = threading.Thread(target=self._fetch_combo_points_thread, daemon=True)
        thread.start()

    def _fetch_combo_points_thread(self):
        """This method runs in a separate thread to get combo points."""
        try:
            # Check readiness again inside the thread, just in case
            if not self.game or not self.game.is_ready():
                raise ConnectionError("Game interface became disconnected before fetch.")

            # Corrected log call
            self.log_message("Fetching combo points in background thread...", "DEBUG")
            cp = self.game.get_combo_points()
            # Corrected log call
            self.log_message(f"Combo points result from game interface: {cp}", "DEBUG")

            # Safely update GUI from the worker thread
            # Using self.after (now self.root.after) to schedule the messagebox call on the main thread
            if cp is not None:
                # Corrected: Use self.root.after
                self.root.after(0, lambda: messagebox.showinfo("Combo Points", f"Current Combo Points: {cp}"))
            else:
                # Corrected: Use self.root.after
                 self.root.after(0, lambda: messagebox.showerror("Combo Points", "Failed to get combo points (returned None)."))

        except Exception as e:
            self.log_message(f"Error fetching combo points in thread: {e}", "ERROR")
            # Schedule error message box on main thread
            # Corrected: Use self.root.after
            self.root.after(0, lambda e=e: messagebox.showerror("Error", f"Error fetching combo points: {e}"))
        finally:
            # Schedule button re-enable on main thread (ensure button exists)
            if hasattr(self, 'test_cp_button') and self.test_cp_button.winfo_exists():
                # Only re-enable if the core components are still ready
                state_to_set = tk.NORMAL if (self.game and self.game.is_ready()) else tk.DISABLED
                # Corrected: Use self.root.after
                self.root.after(0, lambda: self.test_cp_button.config(state=state_to_set))
            self.log_message("Combo point fetch thread finished.", "DEBUG")

    def update_status(self, connected):
        # Use 'connected' parameter passed to this function, which represents core readiness
        # Do not call self.game.is_ready() here directly, rely on the parameter
        if connected:
            self.test_cp_button.config(state=tk.NORMAL)
        else:
            self.test_cp_button.config(state=tk.DISABLED)

        # ... rest of update_status ...

    # --- Moved from LogRedirector class ---
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
                WowObject.TYPE_GAMEOBJECT: self.filter_show_gameobjects_var.get(),
                WowObject.TYPE_ITEM: self.filter_show_items_var.get(),
                WowObject.TYPE_CONTAINER: self.filter_show_containers_var.get(),
                WowObject.TYPE_DYNAMICOBJECT: self.filter_show_dynamicobj_var.get(),
                WowObject.TYPE_CORPSE: self.filter_show_corpses_var.get(),
                # Add others if needed, default to False if type not in map
            }

            objects_in_om = self.om.get_objects()
            player = self.om.local_player # Get player from OM
            current_guids_in_tree = set(self.tree.get_children())
            processed_guids = set()

            for obj in objects_in_om:
                # Check if object type is valid and should be displayed based on filter
                obj_type = getattr(obj, 'type', WowObject.TYPE_NONE)
                if not obj or not hasattr(obj, 'guid') or not type_filter_map.get(obj_type, False):
                    continue # Skip if obj is invalid, has no guid, or type is filtered out

                guid_str = str(obj.guid) # Keep original guid string for internal tree iid
                processed_guids.add(guid_str)

                # Format GUID as hex for display
                guid_hex = f"0x{obj.guid:X}"
                # --- TYPE --- Call get_type_str directly
                obj_type_str = obj.get_type_str() if hasattr(obj, 'get_type_str') else f"Type{obj_type}"
                # --- NAME --- Use the object's get_name method (now simple)
                name = obj.get_name()
                # --- HEALTH/POWER --- Use self.format_hp_energy (Handle potential AttributeError)
                hp_str = self.format_hp_energy(getattr(obj, 'health', 0), getattr(obj, 'max_health', 0))
                power_str = self.format_hp_energy(getattr(obj, 'energy', 0), getattr(obj, 'max_energy', 0), getattr(obj, 'power_type', -1))
                # --- DISTANCE --- Use self.calculate_distance
                dist_val = self.calculate_distance(obj)
                dist_str = f"{dist_val:.1f}" if dist_val >= 0 else "N/A"
                # --- STATUS --- Simplify for now - needs refinement
                # Basic status based on flags or casting state
                status_str = "Dead" if getattr(obj, 'is_dead', False) else (
                    "Casting" if getattr(obj, 'is_casting', False) else (
                        "Channeling" if getattr(obj, 'is_channeling', False) else "Idle"
                    )
                )
                # Consider adding combat flag if available and reliable
                # if hasattr(obj, 'unit_flags') and (obj.unit_flags & WowObject.UNIT_FLAG_IN_COMBAT):
                #    status_str += " (Combat?)" # Mark as potentially unreliable

                values = (
                    guid_hex,
                    obj_type_str,
                    name,
                    hp_str,
                    power_str,
                    dist_str,
                    status_str
                )

                try: # Wrap tree operations
                    if guid_str in current_guids_in_tree:
                        # Update existing item using the original guid_str as iid
                        self.tree.item(guid_str, values=values)
                        # Update tags if necessary (lowercase type string)
                        self.tree.item(guid_str, tags=(obj_type_str.lower(),))
                    else:
                        # Insert new item using the original guid_str as iid
                        self.tree.insert('', tk.END, iid=guid_str, values=values, tags=(obj_type_str.lower(),))
                except tk.TclError as e:
                    # This can happen if the tree is destroyed during update
                    logging.warning(f"TclError updating/inserting item {guid_str} in tree: {e}")
                    break # Exit loop if tree is bad

            # Remove items from tree that are no longer in the object manager OR filtered out
            guids_to_remove = current_guids_in_tree - processed_guids
            for guid_to_remove in guids_to_remove:
                try:
                    if self.tree.exists(guid_to_remove):
                         self.tree.delete(guid_to_remove)
                except tk.TclError as e:
                    # Handle potential errors if item already deleted or tree invalid
                    logging.warning(f"TclError deleting item {guid_to_remove} from tree: {e}")
                    break # Exit loop if tree is bad

        except Exception as e:
            logging.exception(f"Error updating monitor treeview: {e}")

    def _sort_treeview_column(self, col, reverse):
        # Implement sorting logic for the treeview column
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
            WowObject.TYPE_GAMEOBJECT: (self.filter_show_gameobjects_var, "Game Objects"),
            WowObject.TYPE_ITEM: (self.filter_show_items_var, "Items"),
            WowObject.TYPE_CONTAINER: (self.filter_show_containers_var, "Containers"),
            WowObject.TYPE_DYNAMICOBJECT: (self.filter_show_dynamicobj_var, "Dynamic Objects"),
            WowObject.TYPE_CORPSE: (self.filter_show_corpses_var, "Corpses"),
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
        final_tag = tag or (self.default_tag if self is sys.stdout else "ERROR")
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