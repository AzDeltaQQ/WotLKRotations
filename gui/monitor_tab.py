import tkinter as tk
from tkinter import ttk, messagebox
import logging
import math
from typing import TYPE_CHECKING, Optional

# Project Modules (Needed for type hints and enum access)
from wow_object import WowObject

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp # Import from the main gui module

# Restore ttk.Frame inheritance
class MonitorTab(ttk.Frame):
    """Handles the UI and logic for the Monitor Tab."""

    # Restore __init__ signature and super call
    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp', **kwargs):
        """
        Initializes the Monitor Tab.

        Args:
            parent_notebook: The ttk.Notebook widget this frame will be placed in.
            app_instance: The instance of the main WowMonitorApp.
        """
        # Restore super().__init__() call, passing parent_notebook
        super().__init__(parent_notebook, **kwargs)

        self.app = app_instance
        # Remove notebook reference and internal frame creation
        # self.notebook = parent_notebook
        # self.tab_frame = ttk.Frame(self.notebook)
        # Remove the add call from here
        # self.notebook.add(self.tab_frame, text='Monitor')

        # --- Define Monitor specific widgets ---
        self.tree: Optional[ttk.Treeview] = None
        # Define filter variables (used by the dialog and treeview update)
        self.filter_show_units_var = tk.BooleanVar(value=True)
        self.filter_show_players_var = tk.BooleanVar(value=True)

        # --- Build the UI for this tab ---
        self._setup_ui()

    def _setup_ui(self):
        """Creates the widgets for the Monitor tab."""
        # Use self as the parent frame

        # --- Status Info Frame --- (Uses StringVars from self.app)
        info_frame = ttk.LabelFrame(self, text="Status", padding=(10, 5))
        info_frame.pack(pady=(5,10), padx=5, fill=tk.X)
        info_frame.columnconfigure(1, weight=1)
        ttk.Label(info_frame, text="Player:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_name_var).grid(row=0, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Level:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_level_var).grid(row=1, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Health:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_hp_var).grid(row=2, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Power:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_energy_var).grid(row=3, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Pos:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_pos_var).grid(row=4, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Status:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.player_status_var).grid(row=5, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Separator(info_frame, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(info_frame, text="Target:").grid(row=7, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_name_var).grid(row=7, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Level:").grid(row=8, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_level_var).grid(row=8, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Health:").grid(row=9, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_hp_var).grid(row=9, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Power:").grid(row=10, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_energy_var).grid(row=10, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Pos:").grid(row=11, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_pos_var).grid(row=11, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Status:").grid(row=12, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_status_var).grid(row=12, column=1, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, text="Dist:").grid(row=13, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(info_frame, textvariable=self.app.target_dist_var).grid(row=13, column=1, sticky=tk.W, padx=5, pady=1)

        # --- Nearby Units Frame with Filter Button --- (Uses BOLD_FONT from self.app)
        list_outer_frame = ttk.Frame(self)
        list_outer_frame.pack(pady=5, padx=5, fill=tk.BOTH, expand=True)

        list_header_frame = ttk.Frame(list_outer_frame)
        list_header_frame.pack(fill=tk.X)
        ttk.Label(list_header_frame, text="Nearby Objects:", font=self.app.BOLD_FONT).pack(side=tk.LEFT, padx=(10, 5))
        # Bind button to self.open_monitor_filter_dialog
        ttk.Button(list_header_frame, text="Filter...", command=self.open_monitor_filter_dialog).pack(side=tk.LEFT, padx=5)

        # --- Treeview Frame ---
        list_frame = ttk.LabelFrame(list_outer_frame, text="", padding=(10, 5)) # LabelFrame for border, text removed
        list_frame.pack(pady=(5,0), padx=0, fill=tk.BOTH, expand=True)
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
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def open_monitor_filter_dialog(self):
        """Opens a dialog window to configure object type filters for the monitor list."""
        # Use self.app.root for the parent window
        filter_window = tk.Toplevel(self.app.root)
        filter_window.title("Monitor Filters")
        filter_window.geometry("250x280") # Adjusted size
        filter_window.transient(self.app.root)
        filter_window.grab_set() # Make it modal
        filter_window.resizable(False, False)

        main_frame = ttk.Frame(filter_window, padding=15)
        main_frame.pack(expand=True, fill=tk.BOTH)

        # Use BOLD_FONT from app instance
        ttk.Label(main_frame, text="Show Object Types:", font=self.app.BOLD_FONT).pack(pady=(0, 10))

        # Map object type enum to filter variable and label text
        # Use filter variables defined in self
        filter_map = {
            WowObject.TYPE_PLAYER: (self.filter_show_players_var, "Players"),
            WowObject.TYPE_UNIT: (self.filter_show_units_var, "Units (NPCs/Mobs)"),
            # Other types removed as per original code
        }

        for obj_type, (var, label) in filter_map.items():
            ttk.Checkbutton(main_frame, text=label, variable=var).pack(anchor=tk.W, padx=10)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, pady=(20, 0), fill=tk.X)

        def apply_and_close():
            # Call self.update_monitor_treeview on Apply
            self.update_monitor_treeview() # Update tree based on new filter settings
            filter_window.destroy()

        ok_button = ttk.Button(button_frame, text="OK", command=apply_and_close)
        ok_button.pack(side=tk.RIGHT, padx=5)

        filter_window.wait_window() # Wait for the window to be closed

    def update_monitor_treeview(self):
        """Updates the object list Treeview based on current ObjectManager data and filters."""
        try:
            # Use self.app.om for ObjectManager access
            # Use self.tree for the Treeview widget
            if not self.app.om or not self.app.om.is_ready() or not hasattr(self, 'tree') or not self.tree or not self.tree.winfo_exists():
                return

            # Use filter variables defined in self
            type_filter_map = {
                WowObject.TYPE_PLAYER: self.filter_show_players_var.get(),
                WowObject.TYPE_UNIT: self.filter_show_units_var.get(),
            }

            MAX_DISPLAY_DISTANCE = 100.0

            objects_in_om = self.app.om.get_objects()
            current_guids_in_tree = set(self.tree.get_children())
            processed_guids = set()

            for obj in objects_in_om:
                obj_type = getattr(obj, 'type', WowObject.TYPE_NONE)
                if not obj or not hasattr(obj, 'guid') or not type_filter_map.get(obj_type, False):
                    continue

                # Call helper methods from self.app
                dist_val = self.app.calculate_distance(obj)
                if dist_val < 0 or dist_val > MAX_DISPLAY_DISTANCE:
                     continue

                guid_str = str(obj.guid)
                processed_guids.add(guid_str)

                guid_hex = f"0x{obj.guid:X}"
                obj_type_str = obj.get_type_str() if hasattr(obj, 'get_type_str') else f"Type{obj_type}"
                name = obj.get_name()
                # Call helper methods from self.app
                hp_str = self.app.format_hp_energy(getattr(obj, 'health', 0), getattr(obj, 'max_health', 0))
                power_str = self.app.format_hp_energy(getattr(obj, 'energy', 0), getattr(obj, 'max_energy', 0), getattr(obj, 'power_type', -1))
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
            # Use logging, which should be redirected by LogTab's redirector
            logging.exception(f"Error updating monitor treeview: {e}")

    def _sort_treeview_column(self, col, reverse):
        """Sorts the Treeview column."""
        # This method was empty in the original code, keep it empty for now
        pass

