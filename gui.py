import tkinter as tk
from tkinter import ttk, Listbox, Scrollbar, messagebox, filedialog
import time
import os # To list files in Scripts directory
import configparser # To save/load config
import math # For distance calc
import sys # For redirecting stdout/stderr
import traceback # For detailed error logging

# Project Modules
from memory import MemoryHandler
from object_manager import ObjectManager
from wow_object import WowObject # Import class for type hinting and constants
from luainterface import LuaInterface
from combat_rotation import CombatRotation

class WowMonitorApp:
    """Main application class for the WoW Monitor and Rotation Engine GUI."""

    def __init__(self, root):
        self.root = root
        self.root.title("PyWoW Bot - WoW 3.3.5a Monitor & Rotation Engine")
        # Default size, will be overridden by config if exists
        self.root.geometry("750x600")

        # --- Load Config First ---
        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.config.read(self.config_file)

        # --- Initialize Core Components ---
        self.mem = MemoryHandler()
        if not self.mem.is_attached():
            self._show_error_and_exit("FATAL ERROR: Wow.exe not found or could not attach.\nPlease start WoW 3.3.5a (12340) first.")
            return

        self.om = ObjectManager(self.mem)
        if not self.om.is_ready():
            self._show_error_and_exit("FATAL ERROR: Could not initialize Object Manager.\nCheck game version/offsets or memory access permissions.")
            return

        self.lua = LuaInterface(self.mem)
        # Lua readiness check - allow continuing but warn if C API might fail
        if not self.lua.is_ready():
             print("Warning: Lua State pointer issue. Lua C API calls (Spell Info) may fail. Basic Lua execution should still work.", "WARNING")
             # No need for immediate popup, warning is in log

        self.combat_rotation = CombatRotation(self.mem, self.om, self.lua)

        # --- State Variables ---
        self.rotation_running = False
        self.loaded_script_path = None
        self.rotation_rules = [] # GUI's copy of rules for the editor
        self.update_job = None # To store the .after() job ID
        self.is_closing = False # Flag to prevent errors during shutdown

        # --- GUI Elements ---
        self.setup_gui() # Apply styles *before* creating widgets

        # --- Populate Initial State ---
        self.populate_script_dropdown()
        self._update_button_states() # Set initial button enable/disable state

        # --- Start Update Loop ---
        self.update_interval = 300 # milliseconds (Update ~3 times per second)
        print(f"Starting update loop with interval: {self.update_interval}ms", "INFO")
        self.update_data()

    def _show_error_and_exit(self, message):
        """Displays an error message and schedules window closure."""
        print(message, "ERROR") # Log the error
        try: # In case root itself fails
            # Simple message box is more reliable than labels if GUI is failing
            messagebox.showerror("Fatal Initialization Error", message)
            self.root.destroy() # Close immediately on fatal error
        except Exception as e:
             print(f"CRITICAL GUI ERROR during error display: {e}", "ERROR")
             os._exit(1) # Force exit if GUI fails completely

    def _load_config(self):
        """Loads configuration from ini file."""
        try:
            if os.path.exists(self.config_file):
                 self.config.read(self.config_file)
                 geometry = self.config.get('GUI', 'geometry', fallback='750x600')
                 self.root.geometry(geometry)
                 # Load last script path?
                 self.loaded_script_path = self.config.get('Rotation', 'last_script', fallback=None)
                 # TODO: Load last rules file path?
            else:
                 print(f"Config file '{self.config_file}' not found, using defaults.", "INFO")
        except Exception as e:
            print(f"Error loading config file '{self.config_file}': {e}", "ERROR")

    def _save_config(self):
        """Saves configuration to ini file."""
        try:
            if not self.config.has_section('GUI'): self.config.add_section('GUI')
            self.config.set('GUI', 'geometry', self.root.geometry())

            if not self.config.has_section('Rotation'): self.config.add_section('Rotation')
            self.config.set('Rotation', 'last_script', self.loaded_script_path if self.loaded_script_path else "")
            # TODO: Save last rules file path

            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
            print("Configuration saved.", "INFO")
        except Exception as e:
            print(f"Error saving config file '{self.config_file}': {e}", "ERROR")

    def setup_gui(self):
        """Sets up the main GUI elements, styling, and tabs."""
        # Style for ttk widgets (Dark Theme)
        style = ttk.Style()
        style.theme_use('clam') # 'clam' is often good base for customization

        # --- Define Colors ---
        BG_COLOR = '#1E1E1E'        # Dark background
        FG_COLOR = '#D4D4D4'        # Light text
        SELECT_BG = '#3A3D41'        # Darker selection background
        SELECT_FG = '#FFFFFF'        # White selected text
        DEBUG_BLUE = '#569CD6'       # Blue for titles, info
        ERROR_RED = '#F44747'        # Brighter red for errors
        WARNING_YELLOW = '#CDCD00'   # Yellow for warnings
        SUCCESS_GREEN = '#608B4E'    # Green for success/running
        BORDER_COLOR = '#333333'     # Dark borders
        ENTRY_BG = '#2D2D30'        # Background for entry fields, lists
        BUTTON_BG = '#3E3E42'        # Slightly lighter button background
        BUTTON_ACTIVE = '#4F4F53'    # Button hover/active
        DISABLED_FG = '#808080'     # Grey for disabled text/widgets

        # --- Define Fonts ---
        FONT_NAME = 'Consolas'
        FONT_SIZE_NORMAL = 10
        FONT_SIZE_SMALL = 9
        FONT_SIZE_TITLE = 11

        # --- Configure root window ---
        self.root.configure(bg=BG_COLOR)

        # --- Configure ttk widget styles globally ---
        style.configure('.', background=BG_COLOR, foreground=FG_COLOR, bordercolor=BORDER_COLOR,
                        lightcolor=BORDER_COLOR, darkcolor=BORDER_COLOR, font=(FONT_NAME, FONT_SIZE_NORMAL))
        style.map('.',
                  background=[('selected', SELECT_BG), ('active', BUTTON_ACTIVE)],
                  foreground=[('selected', SELECT_FG), ('disabled', DISABLED_FG)])

        style.configure('TFrame', background=BG_COLOR)
        style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR)
        # Specific Label styles for status/errors
        style.configure('Status.TLabel', foreground=SUCCESS_GREEN)
        style.configure('Warning.TLabel', foreground=WARNING_YELLOW)
        style.configure('Error.TLabel', foreground=ERROR_RED)
        style.configure('Info.TLabel', foreground=DEBUG_BLUE)

        style.configure('TButton', background=BUTTON_BG, foreground=FG_COLOR, borderwidth=1,
                        focusthickness=1, focuscolor='', padding=(6, 4), font=(FONT_NAME, FONT_SIZE_NORMAL))
        style.map('TButton', background=[('active', BUTTON_ACTIVE), ('pressed', BG_COLOR), ('disabled', ENTRY_BG)])

        style.configure('TNotebook', background=BG_COLOR, borderwidth=0, tabmargins=[2, 5, 2, 0])
        style.configure('TNotebook.Tab', background=ENTRY_BG, foreground=DISABLED_FG, padding=[10, 5],
                        font=(FONT_NAME, FONT_SIZE_NORMAL))
        style.map('TNotebook.Tab',
                  background=[('selected', BG_COLOR), ('active', BUTTON_ACTIVE)],
                  foreground=[('selected', DEBUG_BLUE), ('active', FG_COLOR)])

        style.configure('TLabelframe', background=BG_COLOR, bordercolor=BORDER_COLOR,
                        relief=tk.SOLID, borderwidth=1, padding=5) # Use solid border
        style.configure('TLabelframe.Label', background=BG_COLOR, foreground=DEBUG_BLUE,
                        font=(FONT_NAME, FONT_SIZE_TITLE))

        style.configure('TEntry', fieldbackground=ENTRY_BG, foreground=FG_COLOR, insertcolor=FG_COLOR,
                        borderwidth=1, relief=tk.FLAT, padding=4)
        style.map('TEntry', bordercolor=[('focus', DEBUG_BLUE)])

        style.configure('TCombobox', fieldbackground=ENTRY_BG, foreground=FG_COLOR, insertcolor=FG_COLOR,
                        arrowcolor=FG_COLOR, borderwidth=1, relief=tk.FLAT, padding=4)
        style.map('TCombobox',
                  fieldbackground=[('readonly', ENTRY_BG)],
                  bordercolor=[('focus', DEBUG_BLUE)],
                  foreground=[('disabled', DISABLED_FG)])
        # Combobox dropdown list styling (using root options)
        self.root.option_add('*TCombobox*Listbox.background', ENTRY_BG)
        self.root.option_add('*TCombobox*Listbox.foreground', FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', SELECT_BG)
        self.root.option_add('*TCombobox*Listbox.selectForeground', SELECT_FG)
        self.root.option_add('*TCombobox*Listbox.font', (FONT_NAME, FONT_SIZE_SMALL))
        self.root.option_add('*TCombobox*Listbox.relief', tk.FLAT)
        self.root.option_add('*TCombobox*Listbox.highlightThickness', 0)


        style.configure('Treeview', background=ENTRY_BG, fieldbackground=ENTRY_BG, foreground=FG_COLOR,
                        font=(FONT_NAME, FONT_SIZE_SMALL), rowheight=22) # Adjust row height
        style.map('Treeview', background=[('selected', SELECT_BG)], foreground=[('selected', SELECT_FG)])
        style.configure('Treeview.Heading', background=BUTTON_BG, foreground=DEBUG_BLUE, relief=tk.FLAT,
                        font=(FONT_NAME, FONT_SIZE_NORMAL, 'bold'), padding=5)
        style.map('Treeview.Heading', relief=[('active', tk.GROOVE)])

        # Listbox (for Rotation Editor) - Manual styling needed as it's tk, not ttk
        self.rule_listbox_style = {
            "bg": ENTRY_BG, "fg": FG_COLOR, "selectbackground": SELECT_BG,
            "selectforeground": SELECT_FG, "borderwidth": 0, "highlightthickness": 1,
            "highlightcolor": BORDER_COLOR, "highlightbackground": BORDER_COLOR,
            "font": (FONT_NAME, FONT_SIZE_SMALL), "relief": tk.FLAT, "activestyle": "none"
        }
        # Log Text Widget (tk) - Manual styling
        self.log_text_style = {
             "bg": ENTRY_BG, "fg": FG_COLOR, "bd": 0, "highlightthickness": 1,
             "highlightcolor": BORDER_COLOR, "highlightbackground": BORDER_COLOR,
             "font": (FONT_NAME, FONT_SIZE_SMALL), "wrap": tk.WORD, "relief": tk.FLAT,
             "insertbackground": FG_COLOR # Cursor color
        }
        # Log Tag Colors
        self.log_tags = {
            "INFO": {"foreground": FG_COLOR},
            "WARNING": {"foreground": WARNING_YELLOW},
            "ERROR": {"foreground": ERROR_RED},
            "DEBUG": {"foreground": DISABLED_FG},
            "ROTATION": {"foreground": "#2DDADA"} # Cyan for rotation actions
        }


        style.configure('Vertical.TScrollbar', background=ENTRY_BG, troughcolor=BG_COLOR,
                        bordercolor=BORDER_COLOR, arrowcolor=FG_COLOR, relief=tk.FLAT, arrowsize=12)
        style.map('Vertical.TScrollbar', background=[('active', BUTTON_ACTIVE)])


        # --- Create Notebook (Tabs) ---
        self.notebook = ttk.Notebook(self.root, style='TNotebook')

        # --- Tab 1: Monitor ---
        tab1 = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab1, text=' Monitor ')
        self.setup_monitor_tab(tab1)

        # --- Tab 2: Rotation Control ---
        tab2 = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab2, text=' Rotation Control ')
        self.setup_lua_runner_tab(tab2)

        # --- Tab 3: Rotation Editor ---
        tab3 = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab3, text=' Rotation Editor ')
        self.setup_rotation_editor_tab(tab3)

        # --- Tab 4: Log ---
        tab4 = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(tab4, text = ' Log ')
        self.setup_log_tab(tab4)

        # Pack the notebook
        self.notebook.pack(expand=True, fill='both', padx=5, pady=(5, 0))

        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- Tab Setup Methods --- (Simplified setup calls, details below)

    def setup_monitor_tab(self, tab):
        # Frame for Player/Target Info
        info_frame = ttk.LabelFrame(tab, text="Status", padding=(10, 5))
        info_frame.pack(pady=(5,10), padx=5, fill=tk.X)

        self.player_label = ttk.Label(info_frame, text="Player: Initializing...", style='Info.TLabel')
        self.player_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)

        self.target_label = ttk.Label(info_frame, text="Target: Initializing...", style='Info.TLabel')
        self.target_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)

        # Frame for Nearby Objects List
        list_frame = ttk.LabelFrame(tab, text="Nearby Units/Players", padding=(10, 5))
        list_frame.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(list_frame, columns=('GUID', 'Type', 'Name', 'HP', 'Power', 'Dist', 'Status'), show='headings', height=10, style='Treeview')
        self.tree.heading('GUID', text='GUID')
        self.tree.heading('Type', text='Type')
        self.tree.heading('Name', text='Name')
        self.tree.heading('HP', text='Health')
        self.tree.heading('Power', text='Power')
        self.tree.heading('Dist', text='Dist')
        self.tree.heading('Status', text='Status')

        # Column configurations
        self.tree.column('GUID', width=140, anchor=tk.W, stretch=False)
        self.tree.column('Type', width=60, anchor=tk.W, stretch=False)
        self.tree.column('Name', width=150, anchor=tk.W, stretch=True)
        self.tree.column('HP', width=110, anchor=tk.W, stretch=False)
        self.tree.column('Power', width=110, anchor=tk.W, stretch=False)
        self.tree.column('Dist', width=60, anchor=tk.E, stretch=False)
        self.tree.column('Status', width=100, anchor=tk.W, stretch=False)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview, style='Vertical.TScrollbar')
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_lua_runner_tab(self, tab):
        control_frame = ttk.LabelFrame(tab, text="Rotation Controls", padding=(10, 10))
        control_frame.pack(pady=10, padx=5, fill=tk.X)
        control_frame.columnconfigure(1, weight=1) # Allow dropdown/status to expand

        # --- Script Loading ---
        script_label = ttk.Label(control_frame, text="Script:")
        script_label.grid(row=0, column=0, padx=(0, 5), pady=5, sticky=tk.W)
        self.script_var = tk.StringVar()
        self.script_dropdown = ttk.Combobox(control_frame, textvariable=self.script_var, state="readonly", width=40, style='TCombobox')
        self.script_dropdown.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.load_script_button = ttk.Button(control_frame, text="Load Script", command=self.load_selected_script, style='TButton')
        self.load_script_button.grid(row=0, column=2, padx=5, pady=5)

        # --- Rules Info (Non-interactive for now) ---
        rules_label = ttk.Label(control_frame, text="Rules:")
        rules_label.grid(row=1, column=0, padx=(0, 5), pady=5, sticky=tk.W)
        self.rules_info_label = ttk.Label(control_frame, text="Load rules via Editor Tab", style='Info.TLabel')
        self.rules_info_label.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky=tk.W)

        # --- Start/Stop Controls ---
        button_frame = ttk.Frame(control_frame) # Use a sub-frame for buttons
        button_frame.grid(row=2, column=0, columnspan=3, pady=(10, 5))
        self.start_button = ttk.Button(button_frame, text="Start Rotation", command=self.start_rotation, style='TButton')
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(button_frame, text="Stop Rotation", command=self.stop_rotation, style='TButton')
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # --- Status Display ---
        self.rotation_status_label = ttk.Label(control_frame, text="Status: Stopped", anchor=tk.W)
        self.rotation_status_label.grid(row=3, column=0, columnspan=3, padx=5, pady=(5,5), sticky=tk.EW)
        self.rotation_status_label.configure(style='Warning.TLabel') # Default to warning color when stopped


    def setup_rotation_editor_tab(self, tab):
        main_frame = ttk.Frame(tab)
        main_frame.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        main_frame.columnconfigure(0, weight=1, minsize=300) # Left side (Define/Lookup)
        main_frame.columnconfigure(1, weight=2) # Right side (Rule List)
        main_frame.rowconfigure(0, weight=1)

        # --- Left Pane ---
        left_pane = ttk.Frame(main_frame)
        left_pane.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 10))
        left_pane.rowconfigure(2, weight=1) # Allow spell list to expand slightly if needed

        # Rule Definition Frame
        define_frame = ttk.LabelFrame(left_pane, text="Define Rule", padding=(10, 5))
        define_frame.grid(row=0, column=0, sticky=tk.NSEW, pady=(0,10))
        define_frame.columnconfigure(1, weight=1)

        # Spell ID + Lookup
        ttk.Label(define_frame, text="Spell ID:").grid(row=0, column=0, padx=5, pady=4, sticky=tk.W)
        spell_id_frame = ttk.Frame(define_frame)
        spell_id_frame.grid(row=0, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=4)
        self.rule_spell_id_var = tk.StringVar()
        self.rule_spell_id_entry = ttk.Entry(spell_id_frame, textvariable=self.rule_spell_id_var, width=10, style='TEntry')
        self.rule_spell_id_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        lookup_button = ttk.Button(spell_id_frame, text="Lookup", width=7, command=self.lookup_spell_info, style='TButton')
        lookup_button.pack(side=tk.LEFT, padx=(5, 0))

        # Target Combobox
        ttk.Label(define_frame, text="Target:").grid(row=1, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_target_var = tk.StringVar(value="Target")
        self.rule_target_combo = ttk.Combobox(define_frame, textvariable=self.rule_target_var, values=["Target", "Player", "Focus", "Pet", "Mouseover"], state="readonly", width=12, style='TCombobox')
        self.rule_target_combo.grid(row=1, column=1, columnspan=2, padx=5, pady=4, sticky=tk.W)

        # Condition Combobox (Basic)
        ttk.Label(define_frame, text="Condition:").grid(row=2, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_condition_var = tk.StringVar(value="Target Exists")
        conditions = ["None", "Target Exists", "Target < 20% HP", "Target < 35% HP", "Player < 30% HP", "Player < 50% HP", "Rage > 30", "Rage > 50", "Energy > 40", "Energy > 60", "Mana > 50%", "Mana < 20%", "Is Spell Ready", "Target Has Debuff", "Player Has Buff", "Is Moving", "Is Casting", "Target Is Casting"]
        self.rule_condition_combo = ttk.Combobox(define_frame, textvariable=self.rule_condition_var, values=conditions, state="readonly", width=25, style='TCombobox')
        self.rule_condition_combo.grid(row=2, column=1, columnspan=2, padx=5, pady=4, sticky=tk.EW)

        # Internal Cooldown Entry
        ttk.Label(define_frame, text="Int. CD (s):").grid(row=3, column=0, padx=5, pady=4, sticky=tk.W)
        self.rule_cooldown_var = tk.StringVar(value="0.0")
        self.rule_cooldown_entry = ttk.Entry(define_frame, textvariable=self.rule_cooldown_var, width=10, style='TEntry')
        self.rule_cooldown_entry.grid(row=3, column=1, columnspan=2, padx=5, pady=4, sticky=tk.W)

        # Add Rule Button
        add_rule_button = ttk.Button(define_frame, text="Add Rule", command=self.add_rotation_rule, style='TButton')
        add_rule_button.grid(row=4, column=0, columnspan=3, pady=(10, 5))

        # Spell Info Display Area
        info_frame = ttk.LabelFrame(left_pane, text="Spell Info Lookup", padding=(10, 5))
        info_frame.grid(row=1, column=0, sticky=tk.NSEW, pady=(0, 10))
        self.spell_name_label = ttk.Label(info_frame, text="Name: -", style='TLabel')
        self.spell_name_label.pack(anchor=tk.W, padx=5)
        self.spell_rank_label = ttk.Label(info_frame, text="Rank: -", style='TLabel')
        self.spell_rank_label.pack(anchor=tk.W, padx=5)
        self.spell_casttime_label = ttk.Label(info_frame, text="Cast Time: -", style='TLabel')
        self.spell_casttime_label.pack(anchor=tk.W, padx=5)
        self.spell_range_label = ttk.Label(info_frame, text="Range: -", style='TLabel')
        self.spell_range_label.pack(anchor=tk.W, padx=5)
        self.spell_cooldown_label = ttk.Label(info_frame, text="Cooldown: -", style='TLabel')
        self.spell_cooldown_label.pack(anchor=tk.W, padx=5)

        # Known Spell IDs Button
        self.scan_spellbook_button = ttk.Button(left_pane, text="List Known Spell IDs", command=self.scan_spellbook, style='TButton')
        self.scan_spellbook_button.grid(row=3, column=0, sticky=tk.SW, pady=10, padx=5)


        # --- Right Pane ---
        right_pane = ttk.Frame(main_frame)
        right_pane.grid(row=0, column=1, sticky=tk.NSEW, padx=(0, 0))
        right_pane.rowconfigure(0, weight=1)
        right_pane.columnconfigure(0, weight=1)

        # Rule list area
        list_frame = ttk.LabelFrame(right_pane, text="Rotation Rule Priority", padding=(10, 5))
        list_frame.grid(row=0, column=0, sticky=tk.NSEW)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.rule_listbox = Listbox(list_frame, height=15, **self.rule_listbox_style) # Apply manual style
        self.rule_listbox.grid(row=0, column=0, sticky=tk.NSEW)

        rule_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.rule_listbox.yview, style='Vertical.TScrollbar')
        self.rule_listbox.configure(yscrollcommand=rule_scrollbar.set)
        rule_scrollbar.grid(row=0, column=1, sticky=tk.NS)

        # Buttons below rule list
        rule_button_frame = ttk.Frame(right_pane)
        rule_button_frame.grid(row=1, column=0, sticky=tk.EW, pady=(5, 0))
        move_up_button = ttk.Button(rule_button_frame, text="Move Up", width=8, command=self.move_rule_up, style='TButton')
        move_up_button.pack(side=tk.LEFT, padx=(0,5))
        move_down_button = ttk.Button(rule_button_frame, text="Move Down", width=10, command=self.move_rule_down, style='TButton')
        move_down_button.pack(side=tk.LEFT, padx=5)
        remove_rule_button = ttk.Button(rule_button_frame, text="Remove Rule", width=12, command=self.remove_selected_rule, style='TButton')
        remove_rule_button.pack(side=tk.LEFT, padx=5)

        # Save/Load Rules Buttons
        save_load_frame = ttk.Frame(right_pane)
        save_load_frame.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        save_rules_button = ttk.Button(save_load_frame, text="Save Rules", style='TButton', command=self.save_rules_to_file, state=tk.NORMAL) # Enable save
        save_rules_button.pack(side=tk.LEFT, padx=5)
        load_rules_button = ttk.Button(save_load_frame, text="Load Rules", style='TButton', command=self.load_rules_from_file, state=tk.NORMAL) # Enable load
        load_rules_button.pack(side=tk.LEFT, padx=5)

    def setup_log_tab(self, tab):
        log_frame = ttk.LabelFrame(tab, text="Log Output", padding=(10, 5))
        log_frame.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=15, width=80, state=tk.DISABLED, **self.log_text_style) # Use manual style
        self.log_text.grid(row=0, column=0, sticky=tk.NSEW)

        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview, style='Vertical.TScrollbar')
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.grid(row=0, column=1, sticky=tk.NS)

        # Configure tags for log message colors
        for tag_name, config in self.log_tags.items():
            self.log_text.tag_configure(tag_name, **config)

        # Redirect print/stderr if not already done
        if not isinstance(sys.stdout, LogRedirector):
            sys.stdout = LogRedirector(self.log_text, "INFO")
            sys.stderr = LogRedirector(self.log_text, "ERROR")
            print("Standard output redirected to log tab.", "INFO")


    # --- GUI Actions --- (Methods for button commands, etc.)

    def _update_button_states(self):
        """Central place to update enable/disable state of buttons."""
        # Load Script Button
        can_load_script = bool(self.script_dropdown['values']) and not self.rotation_running
        self.load_script_button.config(state=tk.NORMAL if can_load_script else tk.DISABLED)
        # Script Dropdown
        self.script_dropdown.config(state="readonly" if can_load_script else tk.DISABLED)

        # Start Button
        can_start = (bool(self.loaded_script_path) or bool(self.rotation_rules)) and not self.rotation_running
        self.start_button.config(state=tk.NORMAL if can_start else tk.DISABLED)

        # Stop Button
        can_stop = self.rotation_running
        self.stop_button.config(state=tk.NORMAL if can_stop else tk.DISABLED)

        # Rotation Editor Buttons (Add, Remove, Move, Save, Load) - Enable if not running rotation
        editor_state = tk.NORMAL if not self.rotation_running else tk.DISABLED
        # Find widgets recursively? Safer to disable container frame if complex.
        # For now, just update specific known buttons:
        # (Assuming they are created - might need try/except if GUI setup changes)
        try:
             # Find relevant widgets in editor tab and set state
             editor_tab = self.notebook.tabs()[2] # Assuming tab index 2 is Editor
             for widget in editor_tab.winfo_children():
                  # Disable frames containing editor controls
                  if isinstance(widget, ttk.Frame): # Main frame, left/right panes
                       for child in widget.winfo_children():
                            if isinstance(child, ttk.LabelFrame): # Define Rule, Rule Priority frames
                                 for sub_child in child.winfo_children():
                                      if isinstance(sub_child, (ttk.Button, ttk.Entry, ttk.Combobox, tk.Listbox)):
                                           sub_child.config(state=editor_state)
                            elif isinstance(child, ttk.Button): # Buttons directly in panes (e.g. List Known IDs)
                                 child.config(state=editor_state)
        except Exception as e:
             print(f"Could not update editor button states: {e}", "WARNING")


    def populate_script_dropdown(self):
        scripts_dir = "Scripts"
        try:
            if not os.path.exists(scripts_dir): os.makedirs(scripts_dir)
            scripts = sorted([f for f in os.listdir(scripts_dir) if f.endswith('.lua')])
            if scripts:
                self.script_dropdown['values'] = scripts
                # Try to restore last script, otherwise select first
                if self.loaded_script_path and os.path.basename(self.loaded_script_path) in scripts:
                     self.script_var.set(os.path.basename(self.loaded_script_path))
                else:
                     self.script_var.set(scripts[0])
                self.script_dropdown.config(state="readonly")
            else:
                self.script_dropdown['values'] = []
                self.script_var.set("No *.lua scripts found in Scripts/")
                self.script_dropdown.config(state=tk.DISABLED)
        except Exception as e:
            print(f"Error populating script dropdown: {e}", "ERROR")
            self.script_dropdown['values'] = []
            self.script_var.set("Error loading scripts")
            self.script_dropdown.config(state=tk.DISABLED)
        self._update_button_states()


    def load_selected_script(self):
        if self.rotation_running: return
        selected_script = self.script_var.get()
        scripts_dir = "Scripts"
        if selected_script and not selected_script.startswith("No ") and not selected_script.startswith("Error "):
            script_path = os.path.join(scripts_dir, selected_script)
            if self.combat_rotation.load_rotation_script(script_path):
                self.loaded_script_path = script_path
                self.rotation_rules = [] # Clear editor rules
                self.update_rule_listbox()
                self.rotation_status_label.config(text=f"Status: Loaded Script '{selected_script}'", style='Info.TLabel')
                self.rules_info_label.config(text="Script loaded, rules cleared.")
                print(f"Loaded rotation script: {script_path}", "INFO")
            else:
                messagebox.showerror("Load Error", f"Failed to read script file:\n{script_path}")
                self.rotation_status_label.config(text="Status: Error loading script", style='Error.TLabel')
                self.loaded_script_path = None
        else:
            messagebox.showwarning("Load Warning", "Please select a valid script file from the dropdown.")
        self._update_button_states()


    def start_rotation(self):
        if self.rotation_running: return
        if not self.loaded_script_path and not self.rotation_rules:
            messagebox.showwarning("Start Error", "Cannot start rotation.\nNo script or rules loaded.")
            print("Cannot start: No script or rules loaded.", "WARNING")
            return

        self.rotation_running = True
        status_text = ""
        if self.rotation_rules:
            status_text = f"Status: Running Editor Rules ({len(self.rotation_rules)})"
        elif self.loaded_script_path:
             script_name = os.path.basename(self.loaded_script_path)
             status_text = f"Status: Running Script '{script_name}'"

        self.rotation_status_label.config(text=status_text, style='Status.TLabel') # Green when running
        print("Combat rotation started.", "INFO")
        self._update_button_states()


    def stop_rotation(self):
        if not self.rotation_running: return
        self.rotation_running = False
        status_text = "Status: Stopped"
        style = 'Warning.TLabel' # Yellow when stopped
        if self.rotation_rules:
             status_text = f"Status: Loaded Editor Rules ({len(self.rotation_rules)})"
             style = 'Info.TLabel' # Blue if rules loaded but stopped
        elif self.loaded_script_path:
            script_name = os.path.basename(self.loaded_script_path)
            status_text = f"Status: Loaded Script '{script_name}'"
            style = 'Info.TLabel' # Blue if script loaded but stopped

        self.rotation_status_label.config(text=status_text, style=style)
        print("Combat rotation stopped.", "INFO")
        self._update_button_states()


    def add_rotation_rule(self):
        if self.rotation_running: return
        spell_id_str = self.rule_spell_id_var.get().strip()
        target = self.rule_target_var.get()
        condition = self.rule_condition_var.get()
        cooldown_str = self.rule_cooldown_var.get().strip()

        try: spell_id = int(spell_id_str)
        except ValueError: messagebox.showerror("Input Error", "Invalid Spell ID."); return
        if spell_id <= 0: messagebox.showerror("Input Error", "Spell ID must be positive."); return

        try: cooldown = float(cooldown_str)
        except ValueError: messagebox.showerror("Input Error", "Invalid Internal CD."); return
        if cooldown < 0: messagebox.showerror("Input Error", "Internal CD must be non-negative."); return

        rule = {"spell_id": spell_id, "target": target, "condition": condition, "cooldown": cooldown}
        self.rotation_rules.append(rule) # Add to GUI's list
        self.combat_rotation.load_rotation_rules(self.rotation_rules) # Update engine's list
        self.update_rule_listbox()
        print(f"Added rule: {rule}", "DEBUG")

        # Clear script if adding rules
        if self.loaded_script_path:
             self.loaded_script_path = None
             self.script_var.set("") # Clear dropdown selection visually
             self.combat_rotation._clear_script()
             print("Cleared loaded script as rules were added.", "INFO")

        self.rules_info_label.config(text=f"{len(self.rotation_rules)} rules loaded.")
        self._update_button_states()


    def remove_selected_rule(self):
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices: messagebox.showwarning("Selection Error", "Select a rule to remove."); return

        for index in sorted(indices, reverse=True):
            try: removed = self.rotation_rules.pop(index)
            except IndexError: continue
            print(f"Removed rule: {removed}", "DEBUG")

        self.combat_rotation.load_rotation_rules(self.rotation_rules) # Update engine
        self.update_rule_listbox()
        self.rules_info_label.config(text=f"{len(self.rotation_rules)} rules loaded.")
        self._update_button_states()

    def move_rule_up(self):
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] == 0: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index - 1, rule)
        self.combat_rotation.load_rotation_rules(self.rotation_rules) # Update engine
        self.update_rule_listbox()
        self.rule_listbox.selection_clear(0, tk.END)
        self.rule_listbox.selection_set(index - 1)
        self.rule_listbox.activate(index - 1)
        self.rule_listbox.see(index - 1)

    def move_rule_down(self):
        if self.rotation_running: return
        indices = self.rule_listbox.curselection()
        if not indices or indices[0] >= len(self.rotation_rules) - 1: return
        index = indices[0]
        rule = self.rotation_rules.pop(index)
        self.rotation_rules.insert(index + 1, rule)
        self.combat_rotation.load_rotation_rules(self.rotation_rules) # Update engine
        self.update_rule_listbox()
        self.rule_listbox.selection_clear(0, tk.END)
        self.rule_listbox.selection_set(index + 1)
        self.rule_listbox.activate(index + 1)
        self.rule_listbox.see(index + 1)


    def update_rule_listbox(self):
        """Repopulates the rule listbox based on self.rotation_rules."""
        current_selection = self.rule_listbox.curselection() # Preserve selection
        self.rule_listbox.delete(0, tk.END)
        for i, rule in enumerate(self.rotation_rules):
            # Improved formatting
            cond_str = rule['condition'] if len(rule['condition']) < 25 else rule['condition'][:22]+"..."
            cd_str = f"{rule['cooldown']:.1f}s" if rule['cooldown'] > 0 else "-"
            rule_str = f"{i+1:02d}| ID:{rule['spell_id']:<5} -> {rule['target']:<9} | If: {cond_str:<25} | CD:{cd_str:<5}"
            self.rule_listbox.insert(tk.END, rule_str)
        # Restore selection if possible
        if current_selection:
            new_index = min(current_selection[0], len(self.rotation_rules) - 1)
            if new_index >= 0:
                 self.rule_listbox.selection_set(new_index)
                 self.rule_listbox.activate(new_index)
                 self.rule_listbox.see(new_index)

    def save_rules_to_file(self):
         """Saves the current rotation rules to a JSON file."""
         if not self.rotation_rules:
              messagebox.showwarning("Save Error", "No rules defined in the editor to save.")
              return
         import json
         file_path = filedialog.asksaveasfilename(
              defaultextension=".json",
              filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
              title="Save Rotation Rules As"
         )
         if not file_path: return # User cancelled

         try:
              with open(file_path, 'w', encoding='utf-8') as f:
                   json.dump(self.rotation_rules, f, indent=2)
              print(f"Rotation rules saved to: {file_path}", "INFO")
              messagebox.showinfo("Save Successful", f"Saved {len(self.rotation_rules)} rules to:\n{file_path}")
         except Exception as e:
              print(f"Error saving rules to {file_path}: {e}", "ERROR")
              messagebox.showerror("Save Error", f"Failed to save rules:\n{e}")

    def load_rules_from_file(self):
         """Loads rotation rules from a JSON file."""
         if self.rotation_running:
              messagebox.showerror("Load Error", "Stop the rotation before loading new rules.")
              return
         import json
         file_path = filedialog.askopenfilename(
              filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
              title="Load Rotation Rules"
         )
         if not file_path: return # User cancelled

         try:
              with open(file_path, 'r', encoding='utf-8') as f:
                   loaded_rules = json.load(f)
              # Basic validation: check if it's a list
              if not isinstance(loaded_rules, list):
                   raise ValueError("Invalid format: JSON root must be a list of rules.")
              # Further validation could check rule structure

              self.rotation_rules = loaded_rules
              self.combat_rotation.load_rotation_rules(self.rotation_rules) # Load into engine
              self.update_rule_listbox() # Update GUI list

              # Clear script if loading rules
              self._clear_script()
              self.script_var.set("") # Clear dropdown visual

              print(f"Loaded {len(self.rotation_rules)} rules from: {file_path}", "INFO")
              self.rules_info_label.config(text=f"{len(self.rotation_rules)} rules loaded from file.")
              self._update_button_states()
              messagebox.showinfo("Load Successful", f"Loaded {len(self.rotation_rules)} rules from:\n{file_path}")

         except json.JSONDecodeError as e:
              print(f"Error decoding JSON from {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
         except ValueError as e:
              print(f"Error validating rules file {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Invalid rule format:\n{e}")
         except Exception as e:
              print(f"Error loading rules from {file_path}: {e}", "ERROR")
              messagebox.showerror("Load Error", f"Failed to load rules file:\n{e}")


    def scan_spellbook(self):
        """Reads known spell IDs directly from memory and displays them."""
        print("Listing Known Spell IDs from memory...", "INFO")
        if not self.om or not self.om.is_ready():
            messagebox.showerror("Error", "Object Manager is not ready.")
            return

        known_spell_ids = self.om.read_known_spell_ids()
        if not known_spell_ids:
             messagebox.showerror("Error", "Failed to read known spell IDs from memory. Check logs or offsets.")
             return

        print(f"Read {len(known_spell_ids)} known spell IDs from memory.", "INFO")

        # --- Display in a dedicated Toplevel window ---
        spell_window = tk.Toplevel(self.root)
        spell_window.title(f"Known Spell IDs ({len(known_spell_ids)})")
        spell_window.geometry("350x450")
        spell_window.configure(bg=self.log_text_style["bg"]) # Use consistent BG

        # Frame for list and scrollbar
        list_frame = ttk.Frame(spell_window, padding=5)
        list_frame.pack(expand=True, fill=tk.BOTH)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        # Listbox with styling
        spell_listbox = Listbox(list_frame, **self.rule_listbox_style) # Use rule list style
        spell_listbox.grid(row=0, column=0, sticky=tk.NSEW)

        spell_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=spell_listbox.yview, style='Vertical.TScrollbar')
        spell_listbox.configure(yscrollcommand=spell_scrollbar.set)
        spell_scrollbar.grid(row=0, column=1, sticky=tk.NS)

        # Button to copy selected ID
        def copy_id():
             selected = spell_listbox.curselection()
             if selected:
                  id_text = spell_listbox.get(selected[0]).split(":")[1].strip()
                  self.root.clipboard_clear()
                  self.root.clipboard_append(id_text)
                  print(f"Copied Spell ID: {id_text}", "DEBUG")

        copy_button = ttk.Button(spell_window, text="Copy Selected ID", command=copy_id, style='TButton')
        copy_button.pack(pady=5, side=tk.LEFT, padx=(10, 5))

        # Close Button
        close_button = ttk.Button(spell_window, text="Close", command=spell_window.destroy, style='TButton')
        close_button.pack(pady=5, side=tk.RIGHT, padx=(5, 10))

        # Populate listbox (Sorted)
        for spell_id in sorted(known_spell_ids):
            spell_listbox.insert(tk.END, f"ID: {spell_id}")

        spell_window.transient(self.root) # Keep on top
        spell_window.grab_set() # Modal focus
        self.root.wait_window(spell_window) # Wait until closed


    def lookup_spell_info(self):
        """Looks up info for a specific spell ID using Lua C API calls via LuaInterface."""
        spell_id_str = self.rule_spell_id_var.get().strip()
        if not spell_id_str.isdigit():
            messagebox.showerror("Input Error", "Please enter a valid Spell ID.")
            return

        spell_id = int(spell_id_str)
        print(f"Looking up Spell ID via Lua C API: {spell_id}", "DEBUG")

        # Check if Lua C API seems ready
        if not self.lua.is_ready():
             messagebox.showerror("Lua Error", "Lua C API calls are not available (Lua State pointer issue?). Cannot lookup spell info.")
             return

        # Clear previous info & Update GUI
        labels_to_clear = [self.spell_name_label, self.spell_rank_label, self.spell_casttime_label, self.spell_range_label, self.spell_cooldown_label]
        default_texts = ["Name: ...", "Rank: ...", "Cast Time: ...", "Range: ...", "Cooldown: ..."]
        for label, text in zip(labels_to_clear, default_texts): label.config(text=text)
        self.root.update_idletasks()

        # --- Attempt calls using call_function ---
        # This now uses the improved LuaInterface which *should* be more stable.
        info_results, cd_results, time_result = None, None, None
        try:
            info_results = self.lua.call_function(f"return GetSpellInfo({spell_id})", 6)
            cd_results = self.lua.call_function(f"return GetSpellCooldown({spell_id})", 3)
            time_result = self.lua.call_function("return GetTime()", 1)
        except Exception as e:
             print(f"Error during Lua calls for spell info {spell_id}: {e}", "ERROR")
             messagebox.showerror("Lua Call Error", f"An error occurred during Lua execution:\n{e}")
             for label, text in zip(labels_to_clear, ["Name: Error", "Rank: -", "Cast Time: -", "Range: -", "Cooldown: -"]): label.config(text=text)
             return

        # --- Process Results ---
        try:
            # Process GetSpellInfo
            if info_results and len(info_results) >= 1 and info_results[0] is not None:
                s_name, s_rank, _, s_cast, s_min_rng, s_max_rng = (info_results + [None]*6)[:6]
                self.spell_name_label.config(text=f"Name: {s_name if s_name else 'N/A'}")
                self.spell_rank_label.config(text=f"Rank: {s_rank if s_rank else 'N/A'}")
                cast_time_ms = int(s_cast) if isinstance(s_cast, (int, float)) else 0
                cast_sec = cast_time_ms / 1000.0
                cast_str = f"{cast_sec:.1f}s" if cast_sec > 0 else "Instant"
                self.spell_casttime_label.config(text=f"Cast Time: {cast_str}")
                min_r = float(s_min_rng) if isinstance(s_min_rng, (int, float)) else 0
                max_r = float(s_max_rng) if isinstance(s_max_rng, (int, float)) else 0
                self.spell_range_label.config(text=f"Range: {min_r:.0f} - {max_r:.0f} yd")
            else:
                print(f"Warning: GetSpellInfo({spell_id}) failed. Result: {info_results}", "WARNING")
                for label, text in zip(labels_to_clear, ["Name: Failed", "Rank: -", "Cast Time: -", "Range: -", "Cooldown: -"]): label.config(text=text)
                return # Stop if basic info fails

            # Process GetSpellCooldown
            cd_start, cd_dur, cd_enabled = 0.0, 0.0, False
            if cd_results and len(cd_results) >= 3:
                cd_start = float(cd_results[0]) if isinstance(cd_results[0], (int, float)) else 0.0
                cd_dur = float(cd_results[1]) if isinstance(cd_results[1], (int, float)) else 0.0
                cd_enabled = bool(cd_results[2]) if cd_results[2] is not None else False
            else: print(f"Warning: GetSpellCooldown({spell_id}) failed. Result: {cd_results}", "WARNING")

            # Process GetTime
            game_time = 0.0
            if time_result and len(time_result) >= 1:
                 game_time = float(time_result[0]) if isinstance(time_result[0], (int, float)) else 0.0
            else: print("Warning: GetTime() failed.", "WARNING")

            # Calculate Cooldown Text
            cooldown_text = "CD: Unknown"
            if not cd_enabled: cooldown_text = "CD: Not Usable"
            elif cd_dur <= 0: cooldown_text = "CD: Ready (No CD)"
            elif game_time <= 0 or cd_start <= 0: cooldown_text = f"CD: {cd_dur:.1f}s (Full)"
            else:
                time_remaining = (cd_start + cd_dur) - game_time
                if time_remaining <= 0.1: cooldown_text = "CD: Ready"
                else: cooldown_text = f"CD: {time_remaining:.1f}s left"
            self.spell_cooldown_label.config(text=cooldown_text)
            print(f"Finished processing spell info for {spell_id}", "DEBUG")

        except Exception as e:
            print(f"Error processing Lua results for spell {spell_id}: {e}", "ERROR")
            messagebox.showerror("Processing Error", f"Failed to process Lua results:\n{e}")
            for label, text in zip(labels_to_clear, ["Name: Error", "Rank: -", "Cast Time: -", "Range: -", "Cooldown: -"]): label.config(text=text)


    # --- Data Update Loop ---

    def format_hp_energy(self, current, max_val, power_type = -1):
        current_int = int(current)
        max_int = int(max_val)
        if power_type == WowObject.POWER_ENERGY and max_int <= 0: max_int = 100
        if max_int <= 0: return f"{current_int}/?"
        return f"{current_int}/{max_int}"

    def calculate_distance(self, obj: WowObject) -> float:
        if not self.om.local_player or not obj: return float('inf')
        dx = self.om.local_player.x_pos - obj.x_pos
        dy = self.om.local_player.y_pos - obj.y_pos
        dz = self.om.local_player.z_pos - obj.z_pos
        return math.sqrt(dx**2 + dy**2 + dz**2)

    def update_data(self):
        """Periodically called to refresh data and update GUI elements."""
        if self.is_closing: return # Don't run if shutting down

        try:
             # Schedule next call immediately
             self.update_job = self.root.after(self.update_interval, self.update_data)
             start_time = time.perf_counter()

             # --- Check Connection & Refresh Core Data ---
             if not self.mem.is_attached():
                  self.player_label.config(text="Player: DISCONNECTED", style='Error.TLabel')
                  self.target_label.config(text="Target: DISCONNECTED", style='Error.TLabel')
                  if self.rotation_running: self.stop_rotation()
                  return # Stop update if disconnected

             self.om.refresh() # Updates OM cache, player, target

             # --- Direct Memory Read Test ---
             player = self.om.local_player # Get player object after refresh
             if player and player.unit_fields_address:
                 try:
                     pm = self.mem # Use the existing MemoryHandler instance
                     uf_addr = player.unit_fields_address
                     mana_curr_addr = uf_addr + 0x4C
                     mana_max_addr = uf_addr + 0x60 # Correct offset for MAXPOWER1
                     energy_curr_addr = uf_addr + 0x58
                     energy_max_addr = uf_addr + 0x6C # Correct offset for MAXPOWER3

                     mana_curr_bytes = pm.read_bytes(mana_curr_addr, 4)
                     mana_max_bytes = pm.read_bytes(mana_max_addr, 4)
                     energy_curr_bytes = pm.read_bytes(energy_curr_addr, 4)
                     energy_max_bytes = pm.read_bytes(energy_max_addr, 4)


                     mana_curr_val = int.from_bytes(mana_curr_bytes, 'little')
                     mana_max_val = int.from_bytes(mana_max_bytes, 'little')
                     energy_curr_val = int.from_bytes(energy_curr_bytes, 'little')
                     energy_max_val = int.from_bytes(energy_max_bytes, 'little')


                     print(f"[DIRECT READ TEST v2] UF: {uf_addr:X}")
                     print(f"  Mana Curr ({mana_curr_addr:X}): Bytes={mana_curr_bytes.hex()} Value={mana_curr_val}")
                     print(f"  Mana Max  ({mana_max_addr:X}): Bytes={mana_max_bytes.hex()} Value={mana_max_val}")
                     print(f"  Energy Curr ({energy_curr_addr:X}): Bytes={energy_curr_bytes.hex()} Value={energy_curr_val}")
                     print(f"  Energy Max  ({energy_max_addr:X}): Bytes={energy_max_bytes.hex()} Value={energy_max_val}")


                     # Also try reading a larger block around the area
                     block_addr = uf_addr + 0x40 # Start slightly before UNIT_FIELD_HEALTH
                     try:
                        block_bytes = pm.read_bytes(block_addr, 48) # Read 48 bytes (covers Health to past Max Energy)
                        print(f"  Block Read ({block_addr:X}): {block_bytes.hex()}")
                     except Exception as block_e:
                        print(f"  Block Read ({block_addr:X}): Error - {block_e}")


                 except Exception as e:
                     print(f"[DIRECT READ TEST v2] Error: {e}")
             # --- End Direct Memory Read Test ---


             # --- Update Player Label ---
             if self.om.local_player:
                 lp = self.om.local_player
                 player_name = lp.get_name() # Get name via method
                 hp_str = self.format_hp_energy(lp.health, lp.max_health)
                 power_str = self.format_hp_energy(lp.energy, lp.max_energy, lp.power_type)
                 player_info = f"Player: {player_name} | HP: {hp_str} | {lp.get_power_label()}: {power_str}"
                 self.player_label.config(text=player_info, style='Info.TLabel')
             else:
                 self.player_label.config(text="Player: Not Found / Not In World", style='Warning.TLabel')

             # --- Update Target Label ---
             if self.om.target:
                 t = self.om.target
                 target_name = t.get_name() # Get name via method
                 hp_str = self.format_hp_energy(t.health, t.max_health)
                 power_str = self.format_hp_energy(t.energy, t.max_energy, t.power_type)
                 target_info = f"Target: {target_name} | HP: {hp_str} | {t.get_power_label()}: {power_str}"
                 self.target_label.config(text=target_info, style='Info.TLabel')
             else:
                 self.target_label.config(text="Target: None", style='Warning.TLabel')

             # --- Update Monitor Tab List (if visible) ---
             try: # Wrap tree update in try/except as it can be complex
                 current_tab_index = self.notebook.index(self.notebook.select())
                 if current_tab_index == 0: # Monitor Tab is index 0
                      current_guids_in_tree = set(self.tree.get_children(""))
                      processed_guids_this_update = set()
                      type_map = {WowObject.TYPE_UNIT: "Unit", WowObject.TYPE_PLAYER: "Player"}

                      for obj in self.om.get_objects(): # Use OM generator
                          if obj.guid == self.om.local_player_guid: continue
                          if obj.type not in [WowObject.TYPE_PLAYER, WowObject.TYPE_UNIT]: continue

                          obj.update_dynamic_data() # Ensure data is fresh

                          # Name should be fetched by OM now
                          obj_name = obj.get_name()

                          dist = self.calculate_distance(obj)
                          if dist > 100: continue # Distance filter

                          guid_str = f"0x{obj.guid:X}"
                          obj_type_str = type_map.get(obj.type, f"T{obj.type}")
                          hp_str = self.format_hp_energy(obj.health, obj.max_health)
                          power_str = self.format_hp_energy(obj.energy, obj.max_energy, obj.power_type)
                          dist_str = f"{dist:.1f}yd"
                          status_str = "Dead" if obj.is_dead else ("Casting" if obj.is_casting else ("Channeling" if obj.is_channeling else "Alive"))

                          values = (guid_str, obj_type_str, obj_name, hp_str, power_str, dist_str, status_str)
                          guid_key = str(obj.guid)
                          processed_guids_this_update.add(guid_key)

                          if guid_key in current_guids_in_tree:
                              self.tree.item(guid_key, values=values)
                          else:
                              self.tree.insert("", tk.END, iid=guid_key, values=values)

                      # Remove stale entries
                      guids_to_remove = current_guids_in_tree - processed_guids_this_update
                      for guid_key in guids_to_remove:
                          if guid_key in self.tree.get_children(""):
                               self.tree.delete(guid_key)
             except tk.TclError as e:
                  # Can happen if tab is switched during update, ignore safely
                  if "invalid command name" not in str(e):
                       print(f"Warning: TclError during Treeview update: {e}", "WARNING")
             except Exception as e:
                  print(f"Error updating monitor list: {e}", "ERROR")
                  traceback.print_exc() # Log full traceback for complex errors


             # --- Run Combat Rotation ---
             if self.rotation_running:
                 self.combat_rotation.run()

             # --- Performance Monitoring ---
             end_time = time.perf_counter()
             update_duration = (end_time - start_time) * 1000
             if update_duration > self.update_interval:
                  print(f"Warning: Update loop duration ({update_duration:.0f}ms) exceeded interval ({self.update_interval}ms).", "WARNING")

        except Exception as e:
            print(f"Unhandled error in update_data loop: {e}", "ERROR")
            traceback.print_exc()
            # Optionally stop rotation on error?
            # if self.rotation_running: self.stop_rotation()


    def on_close(self):
        """Handles window closing action."""
        if self.is_closing: return
        self.is_closing = True # Prevent running again
        print("Closing application...", "INFO")
        # Cancel the scheduled update loop
        if self.update_job:
            self.root.after_cancel(self.update_job)
            self.update_job = None
        # Save config
        self._save_config()
        # Add any other cleanup (e.g., close handles if needed)
        # No need to close pymem handle explicitly, it's done on process exit
        print("Cleanup finished. Exiting.", "INFO")
        self.root.destroy()

# --- Log Redirector Class ---
class LogRedirector:
    """Redirects print/stderr statements to a Tkinter Text widget."""
    def __init__(self, text_widget, default_tag="INFO"):
        self.text_widget = text_widget
        self.default_tag = default_tag
        self.log_queue = [] # Queue messages if widget not ready
        self.initialized = True # Assume ready unless error occurs

    def write(self, message, tag=None):
        if not self.initialized: return # Don't try if widget failed
        try:
            # Process the message immediately
            self._process_message(message, tag)
        except Exception as e:
            # Fallback to console if GUI logging fails
            print(f"GUI LOG ERROR: {e}\nOriginal message: {message}", file=sys.__stderr__)
            self.initialized = False # Stop trying to log to GUI

    def _process_message(self, message, tag=None):
         # Basic check to prevent recursive logging from within this method
         if "GUI LOG ERROR" in message:
              print(message, file=sys.__stderr__) # Ensure critical errors hit console
              return

         # Determine tag
         log_level = tag if tag else self.default_tag
         # Allow print("message", "TAG") override
         if isinstance(message, tuple) and len(message) > 1 and message[1] in self.text_widget.tag_names():
              log_level = message[1]
              message = message[0]
         message = str(message) # Ensure it's a string

         # Find explicit log level hints in the message itself for convenience
         if not tag: # Only check hints if no explicit tag given
             for hint, tag_name in {"ERROR": "ERROR", "WARNING": "WARNING", "DEBUG": "DEBUG", "INFO": "INFO", "ROTATION":"ROTATION"}.items():
                  if hint in message.upper():
                       log_level = tag_name
                       break

         # Write to Text widget
         self.text_widget.config(state=tk.NORMAL)
         timestamp = time.strftime("%H:%M:%S")
         self.text_widget.insert(tk.END, f"{timestamp} ", ("DEBUG",)) # Timestamp always debug grey
         self.text_widget.insert(tk.END, message.strip() + "\n", (log_level,))
         self.text_widget.config(state=tk.DISABLED)
         self.text_widget.see(tk.END) # Auto-scroll

    def flush(self): pass # Required for stdout/stderr interface


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = None # Define app outside try block for finally clause
    try:
        app = WowMonitorApp(root)
        # Only run mainloop if initialization was successful enough to show GUI
        if app.mem.is_attached() and app.om.is_ready():
            root.mainloop()
        else:
            # Error already shown by _show_error_and_exit
            print("Exiting due to initialization failure.", "ERROR")
            # Keep the error window open briefly if root wasn't destroyed
            if root.winfo_exists():
                 root.after(3500, root.destroy) # Give time to read error msg box
                 root.mainloop() # Keep GUI alive for the message box

    except Exception as e:
         print(f"Unhandled exception during application startup: {type(e).__name__}: {e}", "ERROR")
         traceback.print_exc(file=sys.stderr) # Ensure traceback goes somewhere
         try:
             # Attempt to show final error message
             messagebox.showerror("Fatal Application Error", f"A critical error occurred:\\n{e}\\n\\nCheck console/logs for details.")
             # Check if app and root exist before destroying
             if app and app.root and app.root.winfo_exists():
                  app.root.destroy()
             elif root and root.winfo_exists(): # Check root directly if app failed very early
                  root.destroy()
         except:
             os._exit(1) # Force exit if everything fails
    finally:
         # Ensure cleanup runs even if mainloop exits unexpectedly
         if app and not app.is_closing:
              print("Application exited unexpectedly, attempting cleanup...", "WARNING")
              app.on_close()