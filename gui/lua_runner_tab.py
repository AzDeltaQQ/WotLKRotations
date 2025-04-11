import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import traceback
from typing import TYPE_CHECKING, Optional

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp


class LuaRunnerTab:
    """Handles the UI and logic for the Lua Runner Tab."""

    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp'):
        """
        Initializes the Lua Runner Tab.

        Args:
            parent_notebook: The ttk.Notebook widget to attach the tab frame to.
            app_instance: The instance of the main WowMonitorApp.
        """
        self.app = app_instance
        self.notebook = parent_notebook

        # Create the main frame for this tab
        self.tab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_frame, text='Lua Runner')

        # --- Define Lua Runner specific widgets ---
        self.lua_input_text: Optional[scrolledtext.ScrolledText] = None
        self.run_lua_button: Optional[ttk.Button] = None
        self.lua_output_text: Optional[scrolledtext.ScrolledText] = None

        # --- Build the UI for this tab ---
        self._setup_ui()

    def _setup_ui(self):
        """Creates the widgets for the Lua Runner tab."""
        main_frame = ttk.Frame(self.tab_frame, padding=10)
        main_frame.pack(expand=True, fill=tk.BOTH)

        input_frame = ttk.LabelFrame(main_frame, text="Lua Code", padding=10)
        input_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        input_frame.rowconfigure(0, weight=1)
        input_frame.columnconfigure(0, weight=1)

        # Use CODE_FONT from app instance
        self.lua_input_text = scrolledtext.ScrolledText(input_frame, wrap=tk.WORD, height=10, font=self.app.CODE_FONT)
        self.lua_input_text.grid(row=0, column=0, sticky="nsew")
        self.lua_input_text.insert(tk.END, '-- Enter Lua code to execute in WoW\nprint("Hello from Python!")\nlocal name, realm = GetUnitName("player"), GetRealmName()\nprint("Player:", name, "-", realm)\nreturn 42, "Done"')

        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X)

        # Button command uses self.run_lua_from_input
        # Button state depends on app state, potentially set in app's update loop or _update_button_states
        self.run_lua_button = ttk.Button(control_frame, text="Run Lua Code", command=self.run_lua_from_input, state=tk.DISABLED)
        self.run_lua_button.pack(side=tk.LEFT, padx=5)

        output_frame = ttk.LabelFrame(main_frame, text="Lua Output / Result", padding=10)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)

        # Use LUA_OUTPUT_STYLE from app instance
        self.lua_output_text = scrolledtext.ScrolledText(output_frame, height=5, state=tk.DISABLED, **self.app.LUA_OUTPUT_STYLE)
        self.lua_output_text.grid(row=0, column=0, sticky="nsew")

    def run_lua_from_input(self):
        """Gets Lua code from the input text widget and executes it via GameInterface."""
        # Access game interface via self.app.game
        if not self.app.game or not self.app.game.is_ready():
            messagebox.showerror("Error", "Game Interface (IPC) not connected.")
            return

        # Check if widgets exist
        if not self.lua_input_text or not self.lua_output_text:
            self.app.log_message("Lua runner widgets not initialized.", "ERROR")
            return

        lua_code = self.lua_input_text.get("1.0", tk.END).strip()
        if not lua_code:
            messagebox.showwarning("Input Needed", "Please enter some Lua code to run.")
            return

        self.app.log_message("Executing Lua from input box...", "ACTION")
        try:
            # Use game interface from app instance
            results = self.app.game.execute(lua_code) # Correct method name

            self.lua_output_text.config(state=tk.NORMAL)
            self.lua_output_text.delete("1.0", tk.END)
            if results is not None:
                result_str = "\n".join(map(str, results))
                self.lua_output_text.insert(tk.END, f"Result(s):\n{result_str}\n")
                self.app.log_message(f"Lua Execution Result: {results}", "RESULT")
            else:
                self.lua_output_text.insert(tk.END, "Lua Execution Failed (Check DLL/Game Logs)\n")
                self.app.log_message("Lua execution failed (None returned).", "WARN")
            self.lua_output_text.config(state=tk.DISABLED)
            self.lua_output_text.see(tk.END)

        except Exception as e:
            error_msg = f"Error running Lua: {e}"
            self.app.log_message(error_msg, "ERROR")
            traceback.print_exc() # Log traceback via redirector
            messagebox.showerror("Lua Error", error_msg)
            # Ensure output text is writable before inserting error
            if self.lua_output_text:
                try:
                    self.lua_output_text.config(state=tk.NORMAL)
                    self.lua_output_text.delete("1.0", tk.END)
                    self.lua_output_text.insert(tk.END, f"ERROR:\n{error_msg}\n")
                    self.lua_output_text.config(state=tk.DISABLED)
                except tk.TclError: pass # Widget might be destroyed