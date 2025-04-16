import tkinter as tk
from tkinter import ttk, scrolledtext
import sys # For potential debug prints to stderr
from typing import TYPE_CHECKING

# Avoid runtime circular imports
if TYPE_CHECKING:
    # Ensure this points to the correct location of WowMonitorApp if gui.py is in the parent dir
    # If gui.py is in the same dir, it might just be 'import WowMonitorApp'
    # Assuming gui.py is one level up:
    from ..gui import WowMonitorApp # Use relative import if needed

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

        # --- Widgets ---
        self.log_text = scrolledtext.ScrolledText(
            self, # Parent is now self (the Frame)
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

        # Add placeholder message
        self._add_log_entry("Combat Log Listener Initializing...\n", ("INFO",))

    def _add_log_entry(self, message: str, tags: tuple = ("INFO",)):
        """Internal helper to add formatted text to the log widget."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message, tags)
        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END) # Auto-scroll

    def log_event(self, parsed_event_data):
        """
        Public method to add a parsed combat log event to the display.
        (This will be called by the main app loop or a dedicated reader thread later)

        Args:
            parsed_event_data: A dictionary or object containing the parsed event details.
                               (Structure TBD based on RE)
        """
        # TODO: Format the parsed_event_data into a readable string with tags
        # Example placeholder formatting:
        timestamp = parsed_event_data.get("timestamp", "??:??:??")
        event_type = parsed_event_data.get("event_type", "UNKNOWN_EVENT")
        source_name = parsed_event_data.get("source_name", "UnknownSource")
        dest_name = parsed_event_data.get("dest_name", "UnknownDest")
        spell_name = parsed_event_data.get("spell_name", "")
        amount = parsed_event_data.get("amount", 0)

        log_string = f"[{timestamp}] "
        tags_to_apply = ("TIMESTAMP",) # Start with timestamp tag

        # Basic formatting based on event type (expand significantly later)
        log_string += f"{event_type}: "
        tags_to_apply += ("EVENT",)

        log_string += f"Source={source_name}, Dest={dest_name}"
        tags_to_apply += ("INFO",) # Apply default tag

        if spell_name:
            log_string += f", Spell={spell_name}"
            # Add SPELL tag?
        if amount:
            log_string += f", Amount={amount}"
            # Add DAMAGE/HEAL tag?

        log_string += "\n"

        self._add_log_entry(log_string, tags_to_apply)

    def clear_log(self):
         """Clears the combat log display."""
         self.log_text.config(state=tk.NORMAL)
         self.log_text.delete('1.0', tk.END)
         self.log_text.config(state=tk.DISABLED)

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