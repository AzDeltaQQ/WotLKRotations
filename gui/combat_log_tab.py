import tkinter as tk
from tkinter import ttk, scrolledtext
import sys # For potential debug prints to stderr
from typing import TYPE_CHECKING, Optional
from datetime import datetime
import logging
import time
import ctypes # Needed for CombatLogEventNode type hint

# Avoid runtime circular imports
if TYPE_CHECKING:
    # Ensure this points to the correct location of WowMonitorApp if gui.py is in the parent dir
    # If gui.py is in the same dir, it might just be 'import WowMonitorApp'
    # Assuming gui.py is one level up:
    from ..gui import WowMonitorApp # Use relative import if needed
    from ..combat_log_reader import CombatLogEventNode # *** Import the correct Node structure ***

# Basic Mapping of known 3.3.5a Combat Log Event IDs to Names
# Source: Wowpedia / Common Knowledge - Needs expansion!
EVENT_ID_TO_NAME = {
    # Swings
    1: "SWING_DAMAGE",
    2: "SWING_MISSED",
    # Spell Damage/Healing
    3: "SPELL_DAMAGE",
    4: "SPELL_MISSED",
    5: "SPELL_HEAL",
    6: "SPELL_ENERGIZE",
    7: "SPELL_DRAIN",
    8: "SPELL_LEECH",
    # Periodic Effects
    9: "SPELL_PERIODIC_DAMAGE",
    10: "SPELL_PERIODIC_MISSED",
    11: "SPELL_PERIODIC_HEAL",
    12: "SPELL_PERIODIC_ENERGIZE",
    13: "SPELL_PERIODIC_DRAIN",
    14: "SPELL_PERIODIC_LEECH",
    # Spell Casting
    15: "SPELL_CAST_START",
    16: "SPELL_CAST_SUCCESS",
    17: "SPELL_CAST_FAILED",
    # Auras
    18: "SPELL_AURA_APPLIED",
    19: "SPELL_AURA_REMOVED",
    20: "SPELL_AURA_APPLIED_DOSE",
    21: "SPELL_AURA_REMOVED_DOSE",
    22: "SPELL_AURA_REFRESH",
    23: "SPELL_AURA_BROKEN",
    24: "SPELL_AURA_BROKEN_SPELL",
    # Unit Status
    25: "UNIT_DIED",
    26: "UNIT_DESTROYED",
    # Other
    27: "SPELL_INTERRUPT",
    28: "SPELL_EXTRA_ATTACKS",
    29: "SPELL_SUMMON",
    30: "SPELL_CREATE",
    31: "SPELL_INSTAKILL",
    32: "SPELL_DURABILITY_DAMAGE",
    33: "SPELL_DURABILITY_DAMAGE_ALL",
    34: "SPELL_DISPEL",
    35: "SPELL_DISPEL_FAILED",
    36: "SPELL_STOLEN",
    37: "SPELL_STEAL_FAILED",
    # Range Events (Often Auto-Shot / Wand)
    38: "RANGE_DAMAGE",
    39: "RANGE_MISSED",
    # Environmental
    40: "ENVIRONMENTAL_DAMAGE",
    # Dummies/Special
    41: "SPELL_BUILDING_DAMAGE",
    42: "SPELL_BUILDING_HEAL",
    43: "SPELL_BUILDING_MISSED", # Custom ID?
    44: "UNIT_ENTERED_COMBAT",   # Custom ID?
    # Damage Shields
    45: "DAMAGE_SHIELD",
    46: "DAMAGE_SHIELD_MISSED",
    # More?
    11385220: "Unknown_High_ID_Event", # Seen in logs
}

# Basic mapping for miss types (param5 for _MISSED events)
MISS_TYPE_MAP = {
    1: "MISS",
    2: "RESIST", # Often partial resists for spells
    3: "DODGE",
    4: "PARRY",
    5: "BLOCK",
    6: "EVADE",
    7: "IMMUNE",
    8: "DEFLECT",
    # More may exist (ABSORB is handled differently usually)
}

# Basic mapping for aura types (param5 for _AURA_ events)
AURA_TYPE_MAP = {
    1: "BUFF",
    2: "DEBUFF",
}

# Basic mapping for power types (param6 for _ENERGIZE/_DRAIN/_LEECH)
POWER_TYPE_MAP = {
    0: "MANA",
    1: "RAGE",
    2: "FOCUS",
    3: "ENERGY",
    4: "HAPPINESS", # Not used in combat log?
    5: "RUNE",      # DK
    6: "RUNIC_POWER", # DK
    # More? Health is usually separate event.
}

# Wowpedia mapping for Spell School Masks (param6 for spell events)
# **NOTE**: Needs verification based on actual parameter mapping
SCHOOL_MASK_MAP = {
    0x1: "Physical",
    0x2: "Holy",
    0x4: "Fire",
    0x8: "Nature",
    0x10: "Frost",
    0x20: "Shadow",
    0x40: "Arcane",
    # Combinations are possible, but usually single school for log
}

def combine_guid(low: int, high: int) -> int:
    """Combines the low and high parts of a GUID into a 64-bit integer."""
    return (high << 32) | low

# *** IMPORTANT: Make CombatLogTab inherit from ttk.Frame ***
class CombatLogTab(ttk.Frame): # Inherit from ttk.Frame
    """
    GUI Tab for displaying WoW Combat Log events read from memory.
    """
    # Correct __init__ signature for ttk.Frame inheritance
    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp', **kwargs):
        # Call the parent Frame constructor
        super().__init__(parent_notebook, **kwargs)

        self.app = app_instance
        self.logger = logging.getLogger(__name__) # Get logger instance

        # Variable for pausing log output
        self.paused_var = tk.BooleanVar(value=False)

        # --- Widgets ---
        # Main frame to hold log and controls
        main_frame = ttk.Frame(self)
        main_frame.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        main_frame.rowconfigure(0, weight=1)    # Log area expands
        main_frame.columnconfigure(0, weight=1) # Log area expands

        self.log_text = scrolledtext.ScrolledText(
            main_frame, # Parent is now main_frame
            wrap=tk.WORD,
            font=self.app.DEFAULT_FONT,
            bg="#1E1E1E", # Use similar style to LogTab
            fg="#D4D4D4",
            insertbackground="#FFFFFF" # Cursor color
        )
        self.log_text.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED) # Read-only initially

        # --- Log Tag Configuration (Example - customize as needed) ---
        self.log_text.tag_config("TIMESTAMP", foreground="#888888")
        self.log_text.tag_config("EVENT", foreground="#569CD6", font=self.app.BOLD_FONT)
        self.log_text.tag_config("SOURCE", foreground="#9CDCFE") # Light blue
        self.log_text.tag_config("DEST", foreground="#CE9178")   # Orange-ish
        self.log_text.tag_config("SPELL", foreground="#C586C0") # Purple
        self.log_text.tag_config("DAMAGE", foreground="#FF6B6B") # Red
        self.log_text.tag_config("HEAL", foreground="#60C060")   # Green
        self.log_text.tag_config("MISS", foreground="#D4D4D4")   # Default grey/white
        self.log_text.tag_config("INFO", foreground="#D4D4D4")   # Default grey/white
        self.log_text.tag_config("ERROR", foreground="#FF6B6B", font=self.app.BOLD_FONT)

        # Grid the log text area
        self.log_text.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        # --- Control Frame --- #
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=1, column=0, sticky="ew")

        clear_button = ttk.Button(control_frame, text="Clear Log", command=self.clear_log)
        clear_button.pack(side=tk.LEFT, padx=(0, 5))

        pause_button = ttk.Checkbutton(control_frame, text="Pause Log", variable=self.paused_var)
        pause_button.pack(side=tk.LEFT, padx=5)

        # Add placeholder message
        self._add_log_entry("Combat Log Listener Initializing...\n", ("INFO",))

        # Store player GUID for filtering
        self.player_guid = getattr(self.app.om, 'player_guid', None)

    def update_player_guid(self):
        """Update the stored player GUID if it changes."""
        self.player_guid = getattr(self.app.om, 'player_guid', None)

    def _add_log_entry(self, message: str, tags: tuple = ("INFO",)):
        """Internal helper to add formatted text to the log widget."""
        # --- Check pause state --- #
        if self.paused_var.get():
            return # Do nothing if paused

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message, tags)
        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END) # Auto-scroll

    def _get_unit_name(self, guid_low: int, guid_high: int) -> str:
        """Helper to get unit name from GUID parts, falling back to GUID string."""
        if guid_low == 0 and guid_high == 0:
            return "None" # Or handle appropriately
        full_guid = combine_guid(guid_low, guid_high)
        # Check against player GUID *before* looking up object
        # Assuming self.app.om.player_guid holds the 64-bit player GUID
        # *** Check if om and player_guid exist before accessing ***
        player_guid = getattr(self.app.om, 'player_guid', None) # Safely get player_guid
        # player_guid = self.app.om.player_guid if hasattr(self.app.om, 'player_guid') else None
        if player_guid and full_guid == player_guid:
            # Prefer player name from object manager if available, fallback to "You"
            # *** Check if om exists before accessing ***
            player_obj = self.app.om.get_object_by_guid(full_guid) if self.app.om else None
            return player_obj.name if player_obj and player_obj.name else "You"

        obj = self.app.om.get_object_by_guid(full_guid)
        if obj and obj.name:
            return obj.name
        else:
            # Only show GUID if it wasn't the player and wasn't found
            return f"GUID:{full_guid:X}"

    def log_event(self, timestamp: int, event_struct: Optional['CombatLogEventNode'], message: Optional[str] = None, level: str = "INFO"):
        """Logs a combat log event or a simple message with timestamp."""
        if self.paused_var.get() and event_struct: # Only pause actual events, not system messages like "Log Paused"
            return

        self.log_text.config(state=tk.NORMAL)

        # Clear the initial message on the first actual log event or message
        if "Initializing" in self.log_text.get("1.0", "2.0"): # Check first line more reliably
             self.log_text.delete('1.0', tk.END)
             self.log_text.insert(tk.END, "Combat Log started.\n", "DEBUG") # Add a start message

        # Get timestamp directly from the event struct if available, otherwise use passed timestamp
        actual_timestamp = event_struct.timestamp if event_struct else timestamp
        dt_object = datetime.fromtimestamp(actual_timestamp)
        formatted_time = dt_object.strftime("%H:%M:%S") # Removed milliseconds for now

        log_line = f"{formatted_time} "
        tags = [level.upper()] if level.upper() in ["INFO", "WARN", "ERROR", "DEBUG"] else ["INFO"] # Start with level tag

        if event_struct:
            # --- Use fields directly from CombatLogEventNode --- #
            source_guid = combine_guid(event_struct.source_guid_low, event_struct.source_guid_high)
            dest_guid = combine_guid(event_struct.dest_guid_low, event_struct.dest_guid_high)

            # *** Get current player GUID directly from local_player object ***
            current_player_guid = self.app.om.local_player.guid if self.app.om and self.app.om.local_player else None

            # --- Re-enable Debugging Filter --- # Commented out
            # self.logger.debug(f"Filter Check: current_player_guid={current_player_guid}, src={source_guid:X}, dst={dest_guid:X}")
            # --- End Debugging --- #

            # Filter: Skip if player GUID is known and neither src nor dest match
            if current_player_guid and source_guid != current_player_guid and dest_guid != current_player_guid:
                # self.logger.debug(f"Skipping event (Not player related)") # Re-enable log for skipped event
                self.log_text.config(state=tk.DISABLED) # Ensure state is reset even if skipped
                return

            # --- Basic Event Parsing --- #
            event_id = event_struct.event_type_id
            event_name = EVENT_ID_TO_NAME.get(event_id, f"UnknownEvent({event_id})")

            source_name = self._get_unit_name(event_struct.source_guid_low, event_struct.source_guid_high)
            dest_name = self._get_unit_name(event_struct.dest_guid_low, event_struct.dest_guid_high)

            # *** Use current_player_guid (fetched from local_player) for "You" replacement ***
            if current_player_guid:
                # Use the already combined GUIDs
                if source_guid == current_player_guid:
                    tags.append("PLAYER_SOURCE")
                    source_name = "You"
                if dest_guid == current_player_guid:
                    tags.append("PLAYER_DEST")
                    dest_name = "You"

            # --- Parameter Parsing (Using Attempt 5 field names) --- #
            amount = event_struct.amount
            overkill_or_power = event_struct.overkill_or_power_type
            school_mask = event_struct.school_mask
            absorbed = event_struct.absorbed
            resisted = event_struct.resisted
            blocked_or_miss = event_struct.blocked_or_miss_type
            flags = event_struct.flags

            # Derived values
            critical_flag = bool(flags & 0x1) # Bit 0 = Crit (Verified)
            # glancing = bool(flags & 0x2) # Bit 1 = Glance? (TBD)
            # crushing = bool(flags & 0x4) # Bit 2 = Crush? (TBD)

            # --- Parameter Interpretation based on Event Type --- #
            params_str = ""
            details_str = ""
            spell_id = 0 # UNKNOWN where SpellID is stored via this path
            overkill = 0 # Default
            power_type_code = -1 # Default

            # --- Damage Events (Spell, Periodic, Swing) --- #
            if "DAMAGE" in event_name:
                params_str = f" Amt:{amount}"
                overkill = overkill_or_power # Assume this field is overkill
                # if event_name.startswith("SPELL"):
                    # Display SpellID if we find it later
                    # params_str = f" Spell:{spell_id}{params_str}"
                # else: # SWING_DAMAGE - Amount is in amount field. SpellID=0/1?
                #     pass

                # Add details
                if overkill > 0: details_str += f" (Overkill:{overkill})"
                if absorbed > 0: details_str += f" (Absorbed:{absorbed})"
                if blocked_or_miss > 0: details_str += f" (Blocked:{blocked_or_miss})"
                if resisted > 0: details_str += f" (Resisted:{resisted})"
                if critical_flag: details_str += " (Critical)"
                actual_school_name = SCHOOL_MASK_MAP.get(school_mask)
                if actual_school_name: details_str += f" ({actual_school_name})"

            # --- Heal Events (Spell, Periodic) --- #
            elif "HEAL" in event_name:
                params_str = f" Amt:{amount}"
                overheal = overkill_or_power # Assume this field is overheal
                # SpellID location unknown
                # params_str = f" Spell:{spell_id}{params_str}"
                if overheal > 0: details_str += f" (Overheal:{overheal})"
                if blocked_or_miss > 0: details_str += f" (Blocked?:{blocked_or_miss})"
                if critical_flag: details_str += " (Critical)"
                # school_name = SCHOOL_MASK_MAP.get(school_mask) # Does heal store school here?
                # if school_name: details_str += f" ({school_name})"

            # --- Miss Events (Spell, Swing) --- #
            elif "MISSED" in event_name:
                miss_type_code = blocked_or_miss # Verified mapping
                miss_type_str = MISS_TYPE_MAP.get(miss_type_code, f"Miss?({miss_type_code})")
                params_str = f" ({miss_type_str})"
                # SpellID location unknown
                # if event_name.startswith("SPELL") or event_name.startswith("RANGE") or event_name.startswith("BUILDING"):
                #     params_str = f" Spell:{spell_id}{params_str}"

            # --- Energize/Drain/Leech Events --- #
            elif "ENERGIZE" in event_name or "DRAIN" in event_name or "LEECH" in event_name:
                power_amount = amount
                power_type_code = overkill_or_power # Assume this field is Power Type
                power_type_str = POWER_TYPE_MAP.get(power_type_code, f"Type?({power_type_code})")
                params_str = f" Amt:{power_amount} Type:{power_type_str}"
                # SpellID location unknown
                # params_str = f" Spell:{spell_id}{params_str}"
                if resisted > 0: details_str += f" (Resisted:{resisted})"
                if critical_flag: details_str += " (Critical)"

            # --- Cast Events --- #
            elif event_name in ["SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_CAST_FAILED", "SPELL_SUMMON", "SPELL_CREATE", "SPELL_INSTAKILL"]:
                # SpellID location unknown
                params_str = " (SpellID?)"

            # --- Interrupt Events --- #
            elif event_name == "SPELL_INTERRUPT":
                # SpellID locations unknown
                 params_str = " (SpellID?, InterruptedBy?)"

            # --- Aura Events --- # Needs more specific IDA traces
            elif "AURA" in event_name:
                 # SpellID location unknown
                 params_str = " (SpellID?)"
                 # Other params (Type, Stacks, etc.) need investigation

            # --- Other Events --- #
            elif event_name in ["UNIT_DIED", "UNIT_DESTROYED", "UNIT_ENTERED_COMBAT", "ENVIRONMENTAL_DAMAGE"]:
                if event_name == "ENVIRONMENTAL_DAMAGE":
                    env_amount = amount
                    env_type = overkill_or_power # GUESS Env type ID?
                    params_str = f" Amt:{env_amount} Type:{env_type}"
                else:
                    params_str = ""

            # --- Fallback for Unknown --- #
            else:
                # Display all params with their mapped names
                params_str = f" Amt:{amount} O/P:{overkill_or_power} Sch:{school_mask} Abs:{absorbed} Res:{resisted} B/M:{blocked_or_miss} Flg:{flags:#x}"

            # Construct log string
            log_line += f"{source_name} {event_name} {dest_name}{params_str}{details_str}"

        elif message:
            log_line += message # Add the direct message if provided
        else:
            log_line += "Received empty event data." # Fallback

        log_line += "\n"

        # Insert message and apply tags
        self.log_text.insert(tk.END, log_line, tuple(tags))

        # Auto-scroll to the bottom
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_log(self):
         """Clears the combat log display."""
         self.log_text.config(state=tk.NORMAL)
         self.log_text.delete('1.0', tk.END)
         # Re-insert initial message when cleared manually
         self.log_text.insert(tk.END, "Combat Log Cleared.\n", "DEBUG") # Corrected newline
         self.log_text.configure(state='disabled')

# Example placeholder usage (can be removed if causing issues)
# if __name__ == "__main__":
#     root = tk.Tk()
#     notebook = ttk.Notebook(root)
#     # Mock app object for basic testing
#     mock_app = type('obj', (object,), {'DEFAULT_FONT': ('TkDefaultFont', 9), 'BOLD_FONT': ('TkDefaultFont', 9, 'bold')})()
#     tab = CombatLogTab(notebook, mock_app)
#     notebook.add(tab, text="Combat Log (Test)")
#     notebook.pack(expand=True, fill="both")
#
#     # Example log calls
#     tab.log_event({"timestamp": "12:34:56", "event_type": "SPELL_DAMAGE", "source_name": "Player", "dest_name": "Boar", "spell_name": "Fireball", "amount": 123})
#     tab.log_event({"timestamp": "12:34:57", "event_type": "SWING_MISSED", "source_name": "Boar", "dest_name": "Player"})
#
#     root.mainloop() 