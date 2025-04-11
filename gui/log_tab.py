import tkinter as tk
from tkinter import ttk, scrolledtext
import sys
import time
import queue
import traceback
from typing import Optional

# Import WowMonitorApp for type hinting only
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from gui import WowMonitorApp # Import from the main gui module

# --- Log Redirector Class (Moved here) ---
class LogRedirector:
    """Redirects stdout/stderr to the GUI Log tab using a queue."""
    def __init__(self, text_widget, default_tag="INFO", tags=None):
        self.text_widget = text_widget
        self.default_tag = default_tag
        self.tags = tags or {} # Store tag configurations
        self.stdout_orig = sys.stdout
        self.stderr_orig = sys.stderr
        self.queue = queue.Queue()
        self.processing = False
        self._is_active = False # Flag to track if redirection is active

    def write(self, message, tag=None):
        # Only queue if redirection is active
        if not self._is_active or not message.strip(): return
        final_tag = tag or (self.default_tag if self is sys.stdout else "ERROR")
        self.queue.put((str(message), final_tag))
        # Schedule processing only if the widget seems valid and queue was empty
        # Check if processing is False before scheduling to avoid redundant calls
        if not self.processing and hasattr(self.text_widget, 'after_idle') and self.text_widget.winfo_exists():
            try:
                # Only schedule if the queue has items
                if not self.queue.empty():
                    self.text_widget.after_idle(self._process_queue)
            except tk.TclError: pass # Widget might be destroyed

    def _process_queue(self):
        if self.processing or not self._is_active or not self.text_widget or not self.text_widget.winfo_exists():
            # Reset processing flag if stopping early
            if self.processing: self.processing = False
            return
        self.processing = True
        try:
            # Process multiple items per call for efficiency
            processed_count = 0
            max_items_per_cycle = 50 # Limit items per cycle to keep GUI responsive
            while not self.queue.empty() and processed_count < max_items_per_cycle:
                try:
                    message, tag = self.queue.get_nowait()
                    self._insert_message(message, tag)
                    processed_count += 1
                except queue.Empty: break
                except Exception as e:
                    # Use original stderr for logging internal errors of the redirector
                    print(f"LogRedirector: Error processing log queue item: {e}", file=self.stderr_orig)
                    traceback.print_exc(file=self.stderr_orig)
        finally:
            self.processing = False
            # If queue still has items and we're active, schedule another run
            if self._is_active and not self.queue.empty() and self.text_widget.winfo_exists():
                try:
                    self.text_widget.after_idle(self._process_queue)
                except tk.TclError: pass # Widget might be destroyed


    def _insert_message(self, message, tag):
        try:
            if not self.text_widget or not self.text_widget.winfo_exists():
                # Redirector might still be active but widget gone, log to original stderr
                print(f"LogRedirector: Log Widget destroyed. Original Msg: [{tag}] {message.strip()}", file=self.stderr_orig)
                return

            # Ensure widget is in normal state for insertion
            current_state = self.text_widget.cget('state')
            if current_state == tk.DISABLED:
                self.text_widget.config(state=tk.NORMAL)

            timestamp = time.strftime("%H:%M:%S")
            display_tag = tag if tag in self.tags else self.default_tag
            debug_tag_tuple = ("DEBUG",) # Use a tuple for tags

            # Insert timestamp with DEBUG tag
            self.text_widget.insert(tk.END, f"{timestamp} ", debug_tag_tuple)
            # Insert message with its determined tag (ensure it's a tuple)
            self.text_widget.insert(tk.END, message.strip() + "\n", (display_tag,))

            self.text_widget.see(tk.END) # Scroll to the end

            # Restore original state if it was disabled
            if current_state == tk.DISABLED:
                self.text_widget.config(state=tk.DISABLED)

        except tk.TclError as e:
            print(f"LogRedirector: GUI Log Widget TclError: {e}. Original Msg: [{tag}] {message.strip()}", file=self.stderr_orig)
        except Exception as e:
            print(f"LogRedirector: Unexpected Error: {e}. Original Msg: [{tag}] {message.strip()}", file=self.stderr_orig)
            traceback.print_exc(file=self.stderr_orig)


    def flush(self): pass # Required for file-like object interface

    def start_redirect(self):
        """Starts redirecting stdout and stderr."""
        if not self._is_active:
            self._is_active = True
            sys.stdout = self
            sys.stderr = self
            print("LogRedirector: Standard output redirected.", file=self.stderr_orig) # Log activation

    def stop_redirect(self):
        """Stops redirecting and restores original streams."""
        if self._is_active:
            self._is_active = False
            # Process any remaining items in the queue *before* restoring streams
            self._process_queue()
            # Restore original streams only if they haven't been changed elsewhere
            if sys.stdout is self: sys.stdout = self.stdout_orig
            if sys.stderr is self: sys.stderr = self.stderr_orig
            print("LogRedirector: Standard output restored.", file=self.stderr_orig) # Log deactivation


class LogTab:
    """Handles the UI and logic for the Log Tab."""

    def __init__(self, parent_notebook: ttk.Notebook, app_instance: 'WowMonitorApp'):
        """
        Initializes the Log Tab.

        Args:
            parent_notebook: The ttk.Notebook widget to attach the tab frame to.
            app_instance: The instance of the main WowMonitorApp.
        """
        self.app = app_instance
        self.notebook = parent_notebook

        # Create the main frame for this tab
        self.tab_frame = ttk.Frame(self.notebook) # Use self.tab_frame as the parent for widgets
        self.notebook.add(self.tab_frame, text='Log')

        # --- Define Log specific widgets ---
        self.log_text: Optional[scrolledtext.ScrolledText] = None
        self.log_redirector: Optional[LogRedirector] = None # Will be created here

        # --- Build the UI for this tab ---
        self._setup_ui()

        # --- Initialize and start the log redirector ---
        # Must be done *after* log_text widget is created
        if self.log_text:
            # Pass tag definitions from the app instance
            self.log_redirector = LogRedirector(self.log_text, tags=self.app.LOG_TAGS)
            self.log_redirector.start_redirect()
            # Log redirection start message (will appear in the log tab itself now)
            # print("Log redirection started.", file=sys.stdout) # Use standard print - already done by redirector
        else:
            # Use original stderr if redirector failed
            print("ERROR: Log text widget not created, cannot initialize LogRedirector.", file=sys.stderr)

    def _setup_ui(self):
        """Creates the widgets for the Log tab."""
        # Use self.tab_frame as the parent for the LabelFrame and other widgets
        log_frame = ttk.LabelFrame(self.tab_frame, text="Log Output", padding=(10, 5))
        log_frame.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        # Use log_text_style from the app instance
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, width=80, state=tk.DISABLED, **self.app.LOG_TEXT_STYLE)
        self.log_text.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        # Use log_tags from the app instance
        for tag_name, config in self.app.LOG_TAGS.items():
            self.log_text.tag_configure(tag_name, **config)

        clear_log_button = ttk.Button(log_frame, text="Clear Log", command=self.clear_log_text)
        clear_log_button.grid(row=1, column=0, columnspan=2, pady=(5, 0))

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

    def stop_logging(self):
        """Stops the log redirector if it exists."""
        if self.log_redirector:
            self.log_redirector.stop_redirect() 