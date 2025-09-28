from __future__ import annotations

import os
import sys
import subprocess
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except Exception:
    # Ensure we can capture import-time Tk errors in the log
    try:
        from rogueeditor.logging_utils import (
            setup_logging,
            attach_stderr_tee,
            install_excepthook,
            log_environment,
            log_exception_context,
            crash_hint,
        )
        logger = setup_logging()
        attach_stderr_tee(logger)
        install_excepthook(logger)
        log_environment(logger)
        log_exception_context("Failed to import tkinter")
        print("[ERROR] Failed to import tkinter.")
        print(crash_hint())
    except Exception:
        pass
    raise
import threading
import math

from rogueeditor import PokerogueAPI
from rogueeditor.editor import Editor
from rogueeditor.session_manager import SessionManager, SessionObserver, SessionState
from rogueeditor.save_corruption_prevention import SafeSaveManager
# Enhanced item manager import removed - functionality integrated into main item manager
from rogueeditor.utils import (
    list_usernames,
    sanitize_username,
    save_client_session_id,
    load_client_session_id,
    set_user_csid,
    trainer_save_path,
    slot_save_path,
)
from rogueeditor.catalog import (
    load_move_catalog,
    load_ability_catalog,
    load_nature_catalog,
    load_ability_attr_mask,
    load_item_catalog,
)
from gui.common.widgets import AutoCompleteEntry
from gui.common.catalog_select import CatalogSelectDialog
from gui.dialogs.team_editor import TeamManagerDialog, warm_team_analysis_cache, invalidate_team_analysis_cache
from gui.sections.slots import build as build_slots_section
from gui.dialogs.item_manager import ItemManagerDialog
# Enhanced feedback systems
from gui.common.feedback_integration import FeedbackIntegrator
from gui.common.toast import ToastType
from gui.common.error_handler import ErrorContext
from rogueeditor.logging_utils import (
    setup_logging,
    install_excepthook,
    log_environment,
    log_exception_context,
    crash_hint,
    attach_stderr_tee,
)
from rogueeditor.healthcheck import (
    is_first_run,
    last_run_success,
    run_healthcheck,
    record_run_result,
)


class RogueManagerGUI(ttk.Frame):
    def __init__(self, master: tk.Misc):
        # Add initialization debugging
        self._debug_log("GUI Initialization Started")
        
        super().__init__(master)
        self._debug_log("Super class initialized")
        
        root = self.winfo_toplevel()
        self._debug_log("Root window obtained")
        
        try:
            root.title("Rogue Manager GUI")
            # Slightly wider default to avoid rightmost button cutoff
            root.geometry("1050x800")
            root.minsize(720, 600)
            # Ensure window opens focused in foreground
            root.lift()
            root.focus_force()
            # On Windows, also try to bring to front
            try:
                root.attributes('-topmost', True)
                root.after(100, lambda: root.attributes('-topmost', False))
            except Exception:
                pass
            self._debug_log("Root window configured")
        except Exception as e:
            self._debug_log(f"Root window configuration failed: {e}")
            pass
            
        self.api: PokerogueAPI | None = None
        self.editor: Editor | None = None
        self.username: str | None = None
        self.safe_save_manager: SafeSaveManager = SafeSaveManager()
        self._available_slots = []  # Initialize empty, will be populated by _refresh_slots
        
        # Slot selection
        self.slot_var = tk.StringVar(value="1")  # Default to slot 1

        self._debug_log("API and editor attributes initialized")

        # Session management
        self.session_manager: SessionManager | None = None
        self.session_observer: SessionObserver | None = None
        self._debug_log("Session management attributes initialized")

        # Enhanced feedback systems
        try:
            self.feedback = FeedbackIntegrator(self)
            self._debug_log("Feedback integrator initialized")
        except Exception as e:
            self._debug_log(f"Feedback integrator initialization failed: {e}")

        # Console logging levels
        try:
            self.log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
            self.current_log_level = tk.StringVar(value="INFO")  # Default to INFO
            self._load_log_level_preference()  # Load user preference
            self._debug_log("Logging levels initialized")
        except Exception as e:
            self._debug_log(f"Logging levels initialization failed: {e}")

        # Global style + compact mode state
        try:
            self.style = ttk.Style(self)
            self.compact_mode = tk.BooleanVar(value=False)
            # Compact mode preference will be loaded after login
            self._debug_log("Style and compact mode initialized")
        except Exception as e:
            self._debug_log(f"Style and compact mode initialization failed: {e}")
            
        # Hint font for de-emphasized helper text
        try:
            from tkinter import font as _tkfont
            base_font = _tkfont.nametofont('TkDefaultFont')
            self.hint_font = base_font.copy()
            self.hint_font.configure(slant='italic')
            self._debug_log("Hint font configured")
        except Exception:
            self.hint_font = None
            self._debug_log("Hint font configuration failed, using default")

        # Set application icon
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "data", "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
                self._debug_log(f"Application icon set: {icon_path}")
            else:
                self._debug_log(f"Application icon not found: {icon_path}")
        except Exception as e:
            self._debug_log(f"Failed to set application icon: {e}")

        # Top warning banner (disclaimer) - simplified layout
        try:
            banner = ttk.Frame(self)
            banner.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=4, pady=2)
            banner.columnconfigure(0, weight=1)
            warn_text = (
                "⚠️ WARNING: Use at your own risk. The author is not responsible for "
                "data loss or account bans. No data is collected; only data is "
                "exchanged between your local computer and the official game server.\n"
                "❕Tip: Going overboard can trivialize the game and reduce enjoyment. "
                "Intended uses include backing up/restoring your own data, recovering from desync/corruption, "
                "and safe personal experimentation. Always back up before editing.\n"
                "❕Note: This is a side project, so some features (e.g., Items/Modifiers) may be partially functional, "
                "and data catalogs may contain inaccuracies (for example, certain move data).\n"
                "❕Important: Close ALL running game instances (browser tabs/apps) before editing or uploading to avoid "
                "overwrites and desync. After uploading changes, reopen the game and validate (Analyze/Verify tools) before continuing."
            )
            self.banner_label = ttk.Label(
                banner,
                text=warn_text,
                foreground="red",
                wraplength=800,
                justify=tk.LEFT,
            )
            self.banner_label.grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
            # Reflow banner text based on available width
            try:
                banner.bind(
                    "<Configure>",
                    lambda e: self._update_banner_wraplength(e.width)
                )
                # Also set an initial wrap length after layout
                self.after(0, lambda: self._update_banner_wraplength(banner.winfo_width()))
            except Exception:
                pass
            # Right side buttons (top-right)
            right_buttons = ttk.Frame(banner)
            right_buttons.grid(row=0, column=1, sticky=tk.E, padx=4)

            # Compact mode toggle
            ttk.Checkbutton(
                right_buttons,
                text="Hide banner",
                variable=self.compact_mode,
                command=lambda: self._apply_compact_mode(self.compact_mode.get()),
            ).pack(side=tk.TOP)
            self._debug_log("Banner created successfully")
        except Exception as e:
            self._debug_log(f"Banner creation failed: {e}")

        self._debug_log("Starting grid layout setup")
        try:
            # Corrected layout structure:
            # Row 0: Banner (spans all columns)
            # Row 1: Main content area with two columns
            self.grid_rowconfigure(0, weight=0)  # Banner row - fixed height
            self.grid_rowconfigure(1, weight=1)  # Main content row - expands
            self.grid_columnconfigure(0, weight=3)  # Left column (main content)
            self.grid_columnconfigure(1, weight=1)  # Right column (console)
            self._debug_log("Grid weights configured")
            
            # Create main column frames
            self.left_col = ttk.Frame(self)   # Contains auth/status/tools (top) + actions (scrollable below)
            self.console_col = ttk.Frame(self)  # Console column (collapsible)
            self._debug_log("Column frames created")
            
            # Grid the column frames
            self.left_col.grid(row=1, column=0, sticky=tk.NSEW, padx=4, pady=4)
            self.console_col.grid(row=1, column=1, sticky=tk.NSEW, padx=4, pady=4)
            self._debug_log("Column frames gridded")
            
            # Create sub-frames within left column
            self.left_top_frame = ttk.Frame(self.left_col)  # Non-scrollable top section
            self.left_bottom_frame = ttk.Frame(self.left_col)  # Scrollable bottom section
            self.left_top_frame.pack(fill=tk.X, padx=4, pady=4)
            self.left_bottom_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            
            # Create sub-columns within top frame (auth, tools)
            self.auth_col = ttk.Frame(self.left_top_frame)
            self.tools_col = ttk.Frame(self.left_top_frame)
            self.auth_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            self.tools_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            self._debug_log("Sub-frames created")

            self._build_login()
            self._debug_log("Login section built")

            # Set up window geometry persistence immediately (not just after login)
            self._setup_window_persistence()
            self._debug_log("Window persistence setup completed")

            self._build_actions()
            self._debug_log("Actions section built")
            
            # Check for auto-login credentials
            self._check_auto_login()

            self._build_console()
            self._debug_log("Console section built")

            # Mount root container
            self.pack(fill=tk.BOTH, expand=True)
            self._debug_log("Root container packed")

            # Window persistence will be set up after login

            self._debug_log("GUI Initialization Completed Successfully")
        except Exception as e:
            self._debug_log(f"Grid layout setup failed: {e}")
            import traceback
            self._debug_log(f"Traceback: {traceback.format_exc()}")

    def _check_auto_login(self):
        """Check for auto-login credentials and perform automatic login."""
        try:
            import os
            username = os.environ.get('ROGUEEDITOR_AUTO_USERNAME')
            password = os.environ.get('ROGUEEDITOR_AUTO_PASSWORD')
            
            if username and password:
                self._debug_log(f"Auto-login credentials found for user: {username}")
                
                # Set the username in the combo box
                try:
                    self.user_combo.set(username)
                    self.pass_entry.delete(0, tk.END)
                    self.pass_entry.insert(0, password)
                    self._debug_log("Auto-login credentials set in UI")
                    
                    # Schedule auto-login after a short delay to ensure UI is ready
                    self.after(1000, self._perform_auto_login)
                except Exception as e:
                    self._debug_log(f"Failed to set auto-login credentials in UI: {e}")
            else:
                self._debug_log("No auto-login credentials found")
        except Exception as e:
            self._debug_log(f"Auto-login check failed: {e}")

    def _perform_auto_login(self):
        """Perform the actual auto-login."""
        try:
            self._debug_log("Performing auto-login...")
            self._login()
        except Exception as e:
            self._debug_log(f"Auto-login failed: {e}")
            self.feedback.show_error_toast(f"Auto-login failed: {e}")

    def _debug_log(self, message):
        """Write debug message to file for initialization tracking."""
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            with open("gui_debug.log", "a") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass  # Silently fail to avoid recursion
            
    def _debug_exception(self, message, exception):
        """Write exception details to debug log."""
        try:
            import datetime
            import traceback
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            with open("gui_debug.log", "a") as f:
                f.write(f"[{timestamp}] EXCEPTION in {message}: {exception}\n")
                f.write(f"[{timestamp}] TRACEBACK: {traceback.format_exc()}\n")
        except:
            pass  # Silently fail to avoid recursion
            
    def _load_last_selected_slot(self):
        """Load the last selected slot for the current user."""
        try:
            if not self.username:
                self._log("[DEBUG] No username available for slot saving")
                return
                
            from rogueeditor.persistence import persistence_manager
            last_slot = persistence_manager.get_last_selected_slot(self.username)
            self.slot_var.set(last_slot)
            self._log(f"[DEBUG] Loaded last selected slot: {last_slot}")
        except Exception as e:
            self._log(f"[DEBUG] Failed to load last selected slot: {e}")
            # Default to slot 1 on error
            self.slot_var.set("1")

    def _save_last_selected_slot(self):
        """Save the currently selected slot for the current user."""
        try:
            if not self.username:
                self._log("[DEBUG] No username available for slot saving")
                return
                
            from rogueeditor.persistence import persistence_manager
            selected_slot = self.slot_var.get()
            persistence_manager.set_last_selected_slot(self.username, selected_slot)
            self._log(f"[DEBUG] Saved selected slot: {selected_slot}")
        except Exception as e:
            self._log(f"[DEBUG] Failed to save selected slot: {e}")

    def _load_log_level_preference(self):
        """Load user's preferred log level from settings."""
        try:
            from rogueeditor.persistence import persistence_manager
            import os
            
            # Use a safe default directory if username is not set yet
            username = getattr(self, 'username', None) or "default"
            log_level = persistence_manager.get_log_level(username)
            if log_level in self.log_levels:
                self.current_log_level.set(log_level)
                # Can't log here since logging system might not be fully initialized yet
        except Exception:
            # Silently fail - don't log since logging might not be ready
            pass

    def _load_last_selected_slot(self):
        """Load the last selected slot for the current user."""
        try:
            if not self.username:
                self._log("[DEBUG] No username available for slot loading")
                return
                
            from rogueeditor.persistence import persistence_manager
            last_slot = persistence_manager.get_last_selected_slot(self.username)
            self.slot_var.set(last_slot)
            self._log(f"[DEBUG] Loaded last selected slot: {last_slot}")
        except Exception as e:
            self._log(f"[DEBUG] Failed to load last selected slot: {e}")
            # Default to slot 1 on error
            self.slot_var.set("1")

    def _save_last_selected_slot(self):
        """Save the currently selected slot for the current user."""
        try:
            if not self.username:
                self._log("[DEBUG] No username available for slot saving")
                return
                
            from rogueeditor.persistence import persistence_manager
            selected_slot = self.slot_var.get()
            persistence_manager.set_last_selected_slot(self.username, selected_slot)
            self._log(f"[DEBUG] Saved selected slot: {selected_slot}")
        except Exception as e:
            self._log(f"[DEBUG] Failed to save selected slot: {e}")

    # --- UI builders ---
    def _build_login(self):
        # Build the top section (auth, tools)
        self._build_auth_column()
        self._build_tools_column()

        # Update session label when user changes selection
        try:
            self.user_combo.bind('<<ComboboxSelected>>', lambda e: self._update_session_label_from_store())
        except Exception:
            pass

    def _build_auth_column(self):
        """Build the narrow authentication column (left)"""
        auth_frm = ttk.LabelFrame(self.auth_col, text="Authentication")
        auth_frm.pack(fill=tk.BOTH, expand=True)

        # Ensure status var exists for session callbacks
        try:
            _ = self.status_var
        except Exception:
            self.status_var = tk.StringVar(value="")

        # User and password fields in a compact vertical layout
        auth_grid = ttk.Frame(auth_frm)
        auth_grid.pack(fill=tk.X, padx=4, pady=4)

        # User selection
        ttk.Label(auth_grid, text="User:").grid(row=0, column=0, sticky=tk.W, padx=1, pady=1)
        self.user_combo = ttk.Combobox(auth_grid, values=list_usernames(), state="readonly", width=12)
        self.user_combo.grid(row=0, column=1, sticky=tk.EW, padx=1, pady=1)
        ttk.Button(auth_grid, text="New", command=self._new_user_dialog, width=4).grid(row=0, column=2, padx=1, pady=1)

        # Password
        ttk.Label(auth_grid, text="Pwd:").grid(row=1, column=0, sticky=tk.W, padx=1, pady=1)
        self.pass_entry = ttk.Entry(auth_grid, show="*", width=12)
        self.pass_entry.grid(row=1, column=1, sticky=tk.EW, padx=1, pady=1)
        self.show_pwd_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(auth_grid, text="Show", variable=self.show_pwd_var,
                       command=lambda: self.pass_entry.config(show="" if self.show_pwd_var.get() else "*")).grid(row=1, column=2, sticky=tk.W, padx=1, pady=1)

        # Configure grid weights for responsiveness
        auth_grid.columnconfigure(1, weight=1)

        # Action buttons
        btn_frm = ttk.Frame(auth_frm)
        btn_frm.pack(fill=tk.X, padx=4, pady=4)
        self.btn_login = ttk.Button(btn_frm, text="Login", command=self._safe(self._login), width=16)
        self.btn_login.pack(side=tk.LEFT, padx=1)
        ttk.Button(btn_frm, text="Refresh Session", command=self._safe(self._refresh_session), width=16).pack(side=tk.RIGHT, padx=1)

        # Last session update label under the buttons
        try:
            self.session_updated_var
        except Exception:
            self.session_updated_var = tk.StringVar(value="Last session update: -")
        ttk.Label(auth_frm, textvariable=self.session_updated_var,
                 font=('TkDefaultFont', 8), foreground='gray50').pack(anchor=tk.W, padx=4, pady=(0, 4))

    def _build_session_column(self):
        """Build the session information column (middle) - DEPRECATED"""
        # This method is no longer used since session column was removed
        # Session information is now displayed in the auth column
        pass

    def _build_tools_column(self):
        """Build the quick tools column (right) with vertical stacking"""
        tools_frm = ttk.LabelFrame(self.tools_col, text="Quick Tools")
        tools_frm.pack(fill=tk.BOTH, expand=True)

        # Backup and restore tools (sharing one row)
        backup_frm = ttk.Frame(tools_frm)
        backup_frm.pack(fill=tk.X, padx=4, pady=2)
        self.btn_backup = ttk.Button(backup_frm, text="Backup", command=self._safe(self._backup), state=tk.DISABLED)
        self.btn_backup.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        self.btn_restore = ttk.Button(backup_frm, text="Restore", command=self._safe(self._restore_dialog2), state=tk.DISABLED)
        self.btn_restore.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=1)

        # Backup status label
        self.backup_status_var = tk.StringVar(value="Last backup: none")
        ttk.Label(tools_frm, textvariable=self.backup_status_var, foreground='gray50',
                 font=('TkDefaultFont', 8)).pack(fill=tk.X, padx=4, pady=2)

        # Log level selector (in one row)
        log_frm = ttk.Frame(tools_frm)
        log_frm.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(log_frm, text="Log Level:").pack(side=tk.LEFT)
        log_level_combo = ttk.Combobox(log_frm, textvariable=self.current_log_level,
                                      values=self.log_levels, width=8, state="readonly")
        log_level_combo.pack(side=tk.RIGHT, fill=tk.X, expand=True, pady=1)
        log_level_combo.bind('<<ComboboxSelected>>', lambda e: self._on_log_level_changed())

        # Console toggle and open/clear logs buttons (sharing one row)
        console_frm = ttk.Frame(tools_frm)
        console_frm.pack(fill=tk.X, padx=4, pady=2)
        self.console_visible = tk.BooleanVar(value=True)  # Console visible by default
        ttk.Checkbutton(console_frm, text="Show Console", variable=self.console_visible,
                       command=self._toggle_console).pack(side=tk.LEFT)
        # Place Clear Logs to the left of Open Logs
        ttk.Button(console_frm, text="Clear Logs", command=self._clear_logs_action).pack(side=tk.RIGHT, padx=(0,4))
        ttk.Button(console_frm, text="Open Logs", command=self._open_log_directory).pack(side=tk.RIGHT)

    def _build_actions(self):
        """Build the scrollable actions section (bottom-left) with all action groups."""
        # Scrollable container for actions
        container = ttk.LabelFrame(self.left_bottom_frame, text="Actions")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        self.actions_frame = inner

        # Ensure a shared slot variable exists for all actions
        try:
            _ = self.slot_var
        except Exception:
            self.slot_var = tk.StringVar(value="1")

        # Slots summary (move to top to act as the shared slot selector)
        handle = build_slots_section(inner, self)
        self.slot_tree = handle["slot_tree"]

        # Data IO
        box1 = ttk.LabelFrame(inner, text="Data I/O")
        box1.pack(fill=tk.X, padx=6, pady=6)

        # Create main content frame with side-by-side layout
        content_frame = ttk.Frame(box1)
        content_frame.pack(fill=tk.X, padx=4, pady=4)

        # Left side: Dump from server to local
        dump_f = ttk.LabelFrame(content_frame, text="↓ From Server to Local")
        dump_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
        ttk.Button(dump_f, text="↓ Trainer", command=self._safe(self._dump_trainer)).grid(row=0, column=0, padx=2, pady=2, sticky=tk.W)
        ttk.Button(dump_f, text="↓ Selected Slot", command=self._safe(self._dump_slot_selected)).grid(row=0, column=1, padx=2, pady=2, sticky=tk.W)
        ttk.Button(dump_f, text="↓ All", command=self._safe(self._dump_all)).grid(row=0, column=2, padx=2, pady=2, sticky=tk.W)

        # Right side: Upload local changes to server
        up_f = ttk.LabelFrame(content_frame, text="↑ From Local to Server")
        up_f.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2, 0))
        ttk.Button(up_f, text="↑ Trainer", command=self._safe(self._update_trainer)).grid(row=0, column=0, padx=2, pady=2, sticky=tk.W)
        ttk.Button(up_f, text="↑ Selected Slot", command=self._safe(self._update_slot_selected)).grid(row=0, column=1, padx=2, pady=2, sticky=tk.W)
        ttk.Button(up_f, text="↑ All", command=self._safe(self._upload_all)).grid(row=0, column=2, padx=2, pady=2, sticky=tk.W)

        # (Slots summary moved above)

        # Team
        box2 = ttk.LabelFrame(inner, text="Active Run Team")
        box2.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(
            box2,
            text="Works with the selected slot's ongoing run (slot file).",
            foreground='gray50',
            font=(self.hint_font if self.hint_font else None),
        ).pack(fill=tk.X, padx=6, pady=(2, 0))
        # Team management and modifiers section
        ttk.Button(box2, text="Manage Team", command=self._safe(self._edit_team_dialog)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="Manage Modifiers & Items", command=self._safe(self._open_item_mgr)).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(box2, text="⚠️ Manage Weather", command=self._safe(self._edit_run_weather)).pack(side=tk.LEFT, padx=4, pady=4)

        # Note: Modifiers / Items section removed - functionality moved to team section above

        # Account-Wide Settings
        box4 = ttk.LabelFrame(inner, text="Account-Wide Settings")
        box4.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(
            box4,
            text="⚠️ Account-wide changes that persist across runs. Use with caution!",
            foreground="red",
            font=('TkDefaultFont', 8)
        ).pack(padx=4, pady=2, anchor=tk.W)
        
        # Account-wide actions
        actions_frame = ttk.Frame(box4)
        actions_frame.pack(fill=tk.X, padx=4, pady=4)
        
        ttk.Button(actions_frame, text="Manage Starters", 
                  command=self._open_starters_manager).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="Hatch All Eggs", 
                  command=self._safe(self._hatch_all_eggs_quick)).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="Pokedex List", 
                  command=self._safe(self._pokedex_list)).pack(side=tk.LEFT, padx=5)
        
        # Open Local Files moved to bottom below Account-Wide Settings
        local_f = ttk.LabelFrame(inner, text="Open Local Files")
        local_f.pack(fill=tk.X, padx=6, pady=6)
        local_btn_frame = ttk.Frame(local_f)
        local_btn_frame.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(local_btn_frame, text="Open Local Dump...", command=self._safe(self._open_local_dump_dialog)).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(local_btn_frame, text="⚠️ Manual edits may corrupt saves. Proceed at your own risk.",
                 foreground="red", font=('TkDefaultFont', 8)).pack(side=tk.LEFT)


    def _build_console(self):
        self.console_frame = ttk.LabelFrame(self.console_col, text="Console")
        # Don't pack immediately, let toggle_console control visibility
        # The frame exists but is not visible by default
        self.console = tk.Text(self.console_frame, height=30, width=40, state=tk.DISABLED)
        self.console.pack(fill=tk.BOTH, expand=True)
        
        # Add context menu for copying
        self.console_menu = tk.Menu(self.console, tearoff=0)
        self.console_menu.add_command(label="Copy", command=self._copy_console_selection)
        self.console_menu.add_command(label="Copy All", command=self._copy_console_all)
        self.console_menu.add_separator()
        self.console_menu.add_command(label="Clear", command=self._clear_console)
        
        # Bind right-click to show context menu
        self.console.bind("<Button-3>", self._show_console_context_menu)
        self.console.bind("<Button-2>", self._show_console_context_menu)  # Middle click on some systems
        
        # Note: Progress bar removed as we now use toast notifications for progress
        self._busy_count = 0
        # Enable mouse wheel scrolling on canvas and trees
        def _on_mousewheel(event):
            try:
                delta = int(event.delta / 120)
            except Exception:
                delta = 1 if event.num == 4 else -1
            widgets = [w for w in (self.actions_frame.master, self.slot_tree) if w.winfo_ismapped()]
            for w in widgets:
                if hasattr(w, 'yview_scroll'):
                    w.yview_scroll(-delta, 'units')
        self.bind_all('<MouseWheel>', _on_mousewheel)
        self.bind_all('<Button-4>', _on_mousewheel)
        self.bind_all('<Button-5>', _on_mousewheel)
        
        # Set initial state based on user preference
        if self.console_visible.get():
            self.console_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        # If console is not visible by default, the frame exists but is not packed

    def _apply_compact_mode(self, enabled: bool):
        """Compact mode collapses the warning banner text (session only)."""
        try:
            # Save compact mode preference
            try:
                from rogueeditor.persistence import persistence_manager
                if self.username:
                    persistence_manager.set_user_value(self.username, "compact_mode", enabled)
                    self._log(f"[DEBUG] Saved compact mode preference: {enabled}")
            except Exception as e:
                self._log(f"[DEBUG] Failed to save compact mode preference: {e}")
                
            if enabled:
                try:
                    self.banner_label.grid_remove()
                except Exception:
                    pass
            else:
                try:
                    self.banner_label.grid()
                except Exception:
                    pass
        except Exception:
            pass

    def _update_banner_wraplength(self, width: int):
        try:
            # Leave space for the toggle on the right and padding
            wrap = max(300, int(width) - 220)
            self.banner_label.configure(wraplength=wrap)
        except Exception:
            pass

    # --- Helpers ---
    def _log(self, text: str):
        """Log message to console with timestamp and log level filtering."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Determine log level from message
        log_level = "INFO"
        if "[DEBUG]" in text:
            log_level = "DEBUG"
        elif "[ERROR]" in text:
            log_level = "ERROR"
        elif "[WARNING]" in text:
            log_level = "WARNING"
            
        # Check if message should be displayed based on current log level
        level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
        current_level = level_order.get(self.current_log_level.get(), 1)  # Default to INFO
        message_level = level_order.get(log_level, 1)  # Default to INFO
        
        # Only display message if its level is >= current log level
        if message_level < current_level:
            return  # Don't display this message
            
        formatted_text = f"[{timestamp}] {text}"
        
        def append():
            try:
                # Temporarily enable console for writing
                self.console.config(state=tk.NORMAL)
                self.console.insert(tk.END, formatted_text + "\n")
                self.console.see(tk.END)
                # Disable console again to make it read-only
                self.console.config(state=tk.DISABLED)
            except Exception:
                # Fallback in case of any issues
                try:
                    self.console.config(state=tk.NORMAL)
                    self.console.insert(tk.END, formatted_text + "\n")
                    self.console.see(tk.END)
                    self.console.config(state=tk.DISABLED)
                except:
                    pass
        self.after(0, append)

    def _show_busy(self):
        self._busy_count += 1
        self._log(f"[DEBUG] Show busy: count = {self._busy_count}")
        # Note: Progress bar removed as we now use toast notifications for progress

    def _hide_busy(self):
        self._busy_count = max(0, self._busy_count - 1)
        self._log(f"[DEBUG] Hide busy: count = {self._busy_count}")
        # Note: Progress bar removed as we now use toast notifications for progress

    def _run_async(self, desc: str, work, on_done=None):
        # Simple wrapper that just runs work in background thread without busy indicators
        def runner():
            err = None
            try:
                work()
            except Exception as e:
                err = e
            def finish():
                if err:
                    self._log(f"[ERROR] {desc} failed: {err}")
                    self.feedback.show_error_toast(f"Error: {str(err)}")
                elif on_done:
                    on_done()
                self._log(f"Completed: {desc}")
            self.after(0, finish)
        threading.Thread(target=runner, daemon=True).start()

    def _safe(self, fn):
        """Simple safe wrapper that handles exceptions without complex feedback."""
        def wrapper():
            # Skip editor check for functions that create the editor
            func_name = getattr(fn, '__name__', 'unknown')
            if func_name not in ['_login', '_refresh_session'] and not self.editor:
                self.feedback.show_warning("Please login first")
                return

            try:
                fn()
            except Exception as e:
                operation_name = getattr(fn, '__name__', 'operation').replace('_', ' ').title()
                self._log(f"[ERROR] {operation_name} failed: {e}")
                self.feedback.handle_error(e, operation_name, f"executing {func_name}", use_toast=True)
        return wrapper

    def _modalize(self, top: tk.Toplevel, focus_widget: tk.Widget | None = None):
        try:
            top.transient(self)
            top.grab_set()
        except Exception:
            pass
        try:
            (focus_widget or top).focus_set()
        except Exception:
            pass

    def _center_window(self, window: tk.Toplevel, width: int = None, height: int = None):
        """Center a window relative to the parent window."""
        try:
            # Update window to ensure geometry is correct
            window.update_idletasks()

            # Get parent window geometry
            parent_x = self.winfo_rootx()
            parent_y = self.winfo_rooty()
            parent_width = self.winfo_width()
            parent_height = self.winfo_height()

            # Get child window size
            if width is None or height is None:
                window.update_idletasks()
                child_width = window.winfo_reqwidth()
                child_height = window.winfo_reqheight()
            else:
                child_width = width
                child_height = height

            # Calculate center position
            x = parent_x + (parent_width - child_width) // 2
            y = parent_y + (parent_height - child_height) // 2

            # Ensure window stays on screen
            x = max(0, x)
            y = max(0, y)

            # Set window position
            window.geometry(f"{child_width}x{child_height}+{x}+{y}")
        except Exception as e:
            # Fallback to default positioning if centering fails
            self._log(f"[DEBUG] Window centering failed: {e}")

    def _show_text_dialog(self, title: str, content: str):
        top = tk.Toplevel(self)
        top.title(title)
        self._center_window(top, 700, 450)
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(frm, wrap='word')
        sb = ttk.Scrollbar(frm, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.insert(tk.END, content)
        txt.config(state='disabled')
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, pady=6)
        def do_save():
            path = filedialog.asksaveasfilename(title='Save Report', defaultextension='.txt', filetypes=[('Text Files','*.txt'), ('All Files','*.*')])
            if not path:
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo('Saved', f'Saved to {path}')
            except Exception as e:
                messagebox.showerror('Save failed', str(e))
        ttk.Button(btns, text='Save...', command=do_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text='Close', command=top.destroy).pack(side=tk.RIGHT, padx=6)
        self._center_window(top)
        self._modalize(top)

    def _run_and_show_output(self, title: str, func):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        def work():
            with redirect_stdout(buf):
                func()
        def done():
            out = buf.getvalue().strip() or '(no output)'
            self._show_text_dialog(title, out)
        self._run_async(title, work, done)

    def _pick_starter_from_catalog(self):
        # Build pretty display mapping using current dex mapping
        try:
            name_to_id = getattr(self, '_starter_name_to_id', {}) or {}
            if not name_to_id:
                from rogueeditor.utils import load_pokemon_index
                dex = (load_pokemon_index().get('dex') or {})
                name_to_id = {k.lower(): int(v) for k, v in dex.items()}
        except Exception:
            name_to_id = {}
        # Convert to pretty names for display
        pretty_map = {k.replace('_', ' ').title(): v for k, v in name_to_id.items()}
        sel = CatalogSelectDialog.select(self, pretty_map, 'Select Starter')
        if sel is None:
            return
        # Find pretty name
        chosen = None
        for n, i in pretty_map.items():
            if i == sel:
                chosen = n
                break
        if chosen:
            # Set numeric id into the field, and update label text to chosen name
            self.starter_ac.set_value(str(sel))
            try:
                self.starter_label.configure(text=f"{chosen} (#{sel})")
            except Exception:
                pass
    def _update_starter_label(self):
        try:
            raw = (self.starter_ac.get() or '').strip()
            if not raw:
                self.starter_label.configure(text="")
                return
            if raw.isdigit():
                did = str(int(raw))
                # Map id to canonical name from current dex
                try:
                    from rogueeditor.utils import load_pokemon_index, invert_dex_map
                    inv = invert_dex_map(load_pokemon_index())
                    name = inv.get(did)
                except Exception:
                    name = None
                if name:
                    disp = name.replace('-', ' ').title()
                    self.starter_label.configure(text=f"{disp} (#{did})")
                else:
                    self.starter_label.configure(text=f"#{did}")
            else:
                # Not a pure id; try resolve via mapping
                key = raw.lower().replace(' ', '_')
                mid = getattr(self, '_starter_name_to_id', {}).get(key)
                if isinstance(mid, int):
                    disp = raw.replace('_', ' ').title()
                    self.starter_label.configure(text=f"{disp} (#{mid})")
                else:
                    self.starter_label.configure(text=raw)
        except Exception:
            try:
                self.starter_label.configure(text="")
            except Exception:
                pass

    # _analyze_mods_dialog removed - marked for removal

    # --- Actions ---
    def _new_user_dialog(self):
        top = tk.Toplevel(self)
        top.title("Rogue Manager GUI - New User")
        ttk.Label(top, text="Username:").pack(padx=6, pady=6)
        ent = ttk.Entry(top)
        ent.pack(padx=6, pady=6)
        def ok():
            user = sanitize_username(ent.get().strip())
            vals = list_usernames()
            vals.append(user)
            self.user_combo["values"] = sorted(set(vals))
            self.user_combo.set(user)
            top.destroy()
        ttk.Button(top, text="OK", command=ok).pack(pady=6)
        self._center_window(top)
        self._modalize(top, ent)

    def _test_feedback_system(self):
        """Test the feedback system without blocking the main application."""
        self._log("[DEBUG] Test feedback system button clicked")
        try:
            self._log("[DEBUG] Starting feedback test in background thread")
            # Import and run the test in a separate thread to avoid blocking
            def run_test():
                try:
                    self._log("[DEBUG] Background test thread started")
                    import subprocess
                    import sys
                    import os
                    # Run the test script in a separate process
                    self._log("[DEBUG] Launching test_feedback_systems.py")
                    subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), 'test_feedback_systems.py')])
                    self._log("[DEBUG] Test process launched successfully")
                except Exception as e:
                    self._log(f"[ERROR] Failed to start feedback test: {e}")
                    self.after(0, lambda: self.feedback.show_error_toast(f"Failed to start feedback test: {e}"))
            
            # Run in background thread
            import threading
            self._log("[DEBUG] Creating background thread for test")
            thread = threading.Thread(target=run_test, daemon=True)
            self._log("[DEBUG] Starting background thread")
            thread.start()
            self._log("[DEBUG] Background thread started")
            
            self._log("[DEBUG] Showing info toast")
            self.feedback.show_info("Feedback system test started in separate window")
            self._log("[DEBUG] Test feedback system method completed")
        except Exception as e:
            self._log(f"[ERROR] Error starting feedback test: {e}")
            self.feedback.show_error_toast(f"Error starting feedback test: {e}")
        self._log("[DEBUG] Test feedback system method fully completed")

    def _open_log_directory(self):
        """Open the directory where log files are stored."""
        try:
            from rogueeditor.logging_utils import log_file_path
            import os
            import sys
            import subprocess
            
            # Get the log directory
            log_path = log_file_path()
            log_dir = os.path.dirname(log_path)
            
            # Open the directory using the appropriate command for the OS
            if sys.platform.startswith('win'):
                # Windows
                os.startfile(log_dir)
            elif sys.platform == 'darwin':
                # macOS
                subprocess.run(['open', log_dir], check=False)
            else:
                # Linux and other Unix-like systems
                subprocess.run(['xdg-open', log_dir], check=False)
                
            self._log(f"[DEBUG] Opened log directory: {log_dir}")
        except Exception as e:
            self._log(f"[ERROR] Failed to open log directory: {e}")
            self.feedback.show_error_toast(f"Failed to open log directory: {e}")

    def _clear_logs_action(self):
        """Clear current and rotated log files, then notify user."""
        try:
            from rogueeditor.logging_utils import clear_logs
            ok, msg = clear_logs()
            if ok:
                self._log(f"[INFO] {msg}")
                try:
                    self.feedback.show_toast("Logs cleared", duration_ms=2000)
                except Exception:
                    pass
            else:
                self._log(f"[ERROR] {msg}")
                try:
                    self.feedback.show_error_toast(msg)
                except Exception:
                    pass
        except Exception as e:
            self._log(f"[ERROR] Failed to clear logs: {e}")
            try:
                self.feedback.show_error_toast(f"Failed to clear logs: {e}")
            except Exception:
                pass

    def _toggle_console(self):
        """Toggle visibility of the console panel."""
        if hasattr(self, 'console_col'):
            if self.console_visible.get():
                # Show console column
                self.console_col.grid(row=1, column=1, sticky=tk.NSEW, padx=4, pady=4)
                # Restore normal column weights
                self.grid_columnconfigure(0, weight=3)
                self.grid_columnconfigure(1, weight=1)
                self._log("[DEBUG] Console shown")
            else:
                # Hide console column
                self.console_col.grid_forget()
                # Adjust column weights to give more space to left column
                self.grid_columnconfigure(0, weight=4)
                self.grid_columnconfigure(1, weight=0)
                self._log("[DEBUG] Console hidden")
                
    def _show_console_context_menu(self, event):
        """Show context menu for console text widget."""
        try:
            self.console_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.console_menu.grab_release()
            
    def _copy_console_selection(self):
        """Copy selected text from console to clipboard."""
        try:
            selected_text = self.console.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(selected_text)
        except tk.TclError:
            # No selection
            pass
            
    def _copy_console_all(self):
        """Copy all text from console to clipboard."""
        try:
            all_text = self.console.get("1.0", tk.END)
            self.clipboard_clear()
            self.clipboard_append(all_text)
        except Exception as e:
            self._log(f"[ERROR] Failed to copy console text: {e}")
            
    def _clear_console(self):
        """Clear all text from console."""
        try:
            self.console.delete("1.0", tk.END)
        except Exception as e:
            self._log(f"[ERROR] Failed to clear console: {e}")
            
    def _on_log_level_changed(self):
        """Handle log level change."""
        new_level = self.current_log_level.get()
        self._log(f"[DEBUG] Log level changed to: {new_level}")
        self._save_log_level_preference()  # Save user preference

    def __del__(self):
        """Cleanup when app is destroyed."""
        try:
            self._cleanup_session_manager()
        except Exception:
            pass

    def destroy(self):
        """Override destroy to cleanup session manager."""
        try:
            self._cleanup_session_manager()
        except Exception:
            pass
        super().destroy()

    class GUISessionObserver(SessionObserver):
        """Session observer that updates GUI state."""

        def __init__(self, gui_app):
            self.gui = gui_app

        def on_session_state_changed(self, state: SessionState, message: str = "") -> None:
            """Update status display when session state changes."""
            try:
                if state == SessionState.HEALTHY:
                    status = f"Status: Session healthy ({self.gui.username})"
                elif state == SessionState.EXPIRED:
                    status = f"Status: Session expired ({self.gui.username}) - {message}"
                elif state == SessionState.REFRESHING:
                    status = f"Status: Refreshing session ({self.gui.username})..."
                elif state == SessionState.ERROR:
                    status = f"Status: Session error ({self.gui.username}) - {message}"
                else:
                    status = f"Status: Session state unknown ({self.gui.username})"

                # Update status in GUI thread
                self.gui.after(0, lambda: self.gui.status_var.set(status))
            except Exception as e:
                print(f"Error updating session status: {e}")

        def on_session_refresh_started(self) -> None:
            """Called when session refresh begins."""
            try:
                self.gui.after(0, lambda: self.gui._log("Session refresh started automatically"))
            except Exception as e:
                print(f"Error logging session refresh start: {e}")

        def on_session_refresh_completed(self, success: bool, message: str = "") -> None:
            """Called when session refresh completes."""
            try:
                if success:
                    self.gui.after(0, lambda: self.gui._log("Session refresh completed successfully"))
                    # Update session timestamp
                    try:
                        from datetime import datetime
                        from rogueeditor.utils import set_user_last_session_update
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        if self.gui.username:
                            set_user_last_session_update(self.gui.username, ts)
                            self.gui.after(0, lambda: self.gui.session_updated_var.set(f"Last session update: {ts}"))
                    except Exception as e:
                        print(f"Error updating session timestamp: {e}")
                else:
                    self.gui.after(0, lambda: self.gui._log(f"Session refresh failed: {message}"))
            except Exception as e:
                print(f"Error logging session refresh completion: {e}")

    def _setup_session_manager(self):
        """Initialize session manager with GUI integration."""
        self._log("[DEBUG] Setting up session manager...")
        if self.api and not self.session_manager:
            self._log("[DEBUG] Creating new session manager...")
            self.session_manager = SessionManager(self.api)
            self.session_observer = self.GUISessionObserver(self)
            self.session_manager.add_observer(self.session_observer)
            self.api.set_session_manager(self.session_manager)
            self._log("[DEBUG] Starting session monitoring...")
            try:
                # Start monitoring with timeout to prevent blocking
                import threading
                def start_monitoring_safe():
                    try:
                        self.session_manager.start_monitoring()
                        self._log("[DEBUG] Session monitoring started successfully")
                    except Exception as e:
                        self._log(f"[ERROR] Failed to start session monitoring: {e}")
                
                monitor_thread = threading.Thread(target=start_monitoring_safe, daemon=True)
                monitor_thread.start()
                # Don't wait for it to complete, just start it in background
            except Exception as e:
                self._log(f"[ERROR] Exception during session monitoring start: {e}")
            self._log("[DEBUG] Session manager setup completed")
        else:
            self._log("[DEBUG] Session manager already exists or API not available")

    def _cleanup_session_manager(self):
        """Clean up session manager resources."""
        if self.session_manager:
            self.session_manager.stop_monitoring()
            if self.session_observer:
                self.session_manager.remove_observer(self.session_observer)
            self.session_manager = None
            self.session_observer = None

    def _login(self):
        user = self.user_combo.get().strip()
        if not user:
            self.feedback.show_warning("Select or create a username")
            return
        pwd = self.pass_entry.get()
        if not pwd:
            self.feedback.show_warning("Enter password")
            return

        # Log start of login attempt
        self._log(f"Attempting login for user: {user}")

        try:
            self._log("[DEBUG] Creating API instance...")
            # Intentionally ignore any prefilled clientSessionId; always establish a fresh session per login
            api = PokerogueAPI(user, pwd)

            self._log("[DEBUG] Calling API login...")
            api.login()

            self._log("[DEBUG] Login successful, setting up session...")
            # Prefer server-provided clientSessionId; otherwise generate a new one for this session
            try:
                from rogueeditor.utils import generate_client_session_id
                csid = api.client_session_id or generate_client_session_id()
                api.client_session_id = csid
                # Persist for convenience/debug; UI shows current csid
                try:
                    save_client_session_id(csid)
                    set_user_csid(user, csid)
                except Exception as e:
                    self._log(f"Warning: Could not save client session ID: {e}")
            except Exception as e:
                self._log(f"Warning: Could not generate client session ID: {e}")

            self.api = api
            self.editor = Editor(api)
            self.username = user

            self._log("[DEBUG] Scheduling login completion...")
            # Schedule done callback on main thread
            self.after(0, lambda: self._safe_login_done_wrapper())

        except Exception as e:
            # Handle login errors properly - ensure we're on the main thread
            def handle_login_error(error_exception):
                self._log(f"[ERROR] Login failed: {error_exception}")
                self.feedback.handle_error(error_exception, "Login", "authenticating user", use_toast=True)
                self.status_var.set("Status: Login failed")
                # Make sure we hide busy indicator
                try:
                    # Ensure busy indicator is completely hidden
                    while self._busy_count > 0:
                        self._hide_busy()
                    self._log("[DEBUG] Busy indicator hidden after login error")
                except Exception as hide_err:
                    self._log(f"[ERROR] Failed to hide busy indicator: {hide_err}")

            self._log(f"[ERROR] Scheduling login error handler: {e}")
            self.after(0, lambda error=e: handle_login_error(error))
        
    def _safe_login_done_wrapper(self):
        """Wrapper to ensure login completion doesn't freeze UI"""
        self._log("[DEBUG] Login completion wrapper called")
        try:
            self._login_done()
            self._log("[DEBUG] Login completion finished successfully")
        except Exception as e:
            self._log(f"[ERROR] Login completion failed: {e}")
            self.feedback.show_error_toast(f"Login completion error: {e}")

    def _logout(self):
        """Log out the current user, warning if there are unsent local changes."""
        try:
            user = self.username
        except Exception:
            user = None
        # Check dirty state
        try:
            from rogueeditor.persistence import persistence_manager
            is_dirty = persistence_manager.get_user_value(user or "", "local_dirty", False)
        except Exception:
            is_dirty = False
        if is_dirty:
            if not self.feedback.confirm_action("Unsynced Changes",
                "There are local changes not uploaded. Log out anyway?",
                "logging out"):
                return
        
        # Clear all user data and state completely
        self._clear_user_data()
        
        # Cleanup session manager and API
        try:
            self._cleanup_session_manager()
        except Exception:
            pass
        self.api = None
        self.editor = None
        self.username = None
        
        # Reset UI pieces
        try:
            self.status_var.set("Status: Not logged in")
        except Exception:
            pass
        try:
            self.btn_backup.configure(state=tk.DISABLED)
            self.btn_restore.configure(state=tk.DISABLED)
        except Exception:
            pass
        try:
            self.btn_login.configure(text="Login", command=self._safe(self._login))
        except Exception:
            pass
        
        # Clear all user-related UI elements
        try:
            self.user_combo.set("")
        except Exception:
            pass
        try:
            self.pass_entry.delete(0, tk.END)
        except Exception:
            pass
        try:
            self.slot_var.set("1")
        except Exception:
            pass
        try:
            self.session_updated_var.set("Last session update: -")
        except Exception:
            pass
        try:
            self.backup_status_var.set("Last backup: none")
        except Exception:
            pass
        
        # Clear slot data
        try:
            self._available_slots = []
        except Exception:
            pass
        
        # Clear slot tree if it exists
        try:
            if hasattr(self, 'slot_tree'):
                for item in self.slot_tree.get_children():
                    self.slot_tree.delete(item)
        except Exception:
            pass
        
        # Clear any cached data
        try:
            self._clear_cached_data()
        except Exception:
            pass
        
        finally:
            # Ensure busy indicator is always hidden
            try:
                while self._busy_count > 0:
                    self._hide_busy()
                self._log("[DEBUG] Busy indicator hidden in logout")
            except:
                pass
        
    def _login_done(self):
        self._log("[DEBUG] Login completion started...")
        user = self.username
        # Set up session manager after successful login
        try:
            self._log("[DEBUG] Setting up session manager...")
            self._setup_session_manager()
            self._log("[DEBUG] Session manager setup completed")
        except Exception as e:
            self._log(f"Warning: Session manager setup failed: {e}")

        try:
            self._log("[DEBUG] Updating status display...")
            self.status_var.set(f"Status: Logged in as {user}")
            self._log(f"Logged in as {user}")
            self.feedback.show_success(f"Successfully logged in as {user}")
            self._log("[DEBUG] Status display updated")
        except Exception as e:
            self._log(f"Warning: Could not update status: {e}")

        # Load last selected slot for this user
        self._load_last_selected_slot()

        # Start background cache warming for team analysis
        self._start_background_cache_warming()

        # Toggle Login -> Logout
        try:
            self.btn_login.configure(text="Logout", command=self._safe(self._logout))
        except Exception:
            pass

        # Persist and show last session update time
        try:
            self._log("[DEBUG] Updating session timestamp...")
            from datetime import datetime
            from rogueeditor.utils import set_user_last_session_update
            from rogueeditor.persistence import persistence_manager
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            set_user_last_session_update(user, ts)
            self.session_updated_var.set(f"Last session update: {ts}")
            # Also save to persistence manager
            persistence_manager.set_last_session_update(user, ts)
            self._log("[DEBUG] Session timestamp updated")
        except Exception as e:
            self._log(f"Warning: Could not update session timestamp: {e}")

        # Enable backup/restore and update backup status
        try:
            self._log("[DEBUG] Enabling backup buttons...")
            self.btn_backup.configure(state=tk.NORMAL)
            self.btn_restore.configure(state=tk.NORMAL)
            self._log("[DEBUG] Backup buttons enabled")
            # Refresh backup status after enabling
            try:
                self._refresh_backup_status()
            except Exception as e:
                self._log(f"Warning: Could not refresh backup status: {e}")
        except Exception as e:
            self._log(f"Warning: Could not enable backup buttons: {e}")

        try:
            self._log("[DEBUG] Updating backup status...")
            self._update_backup_status()
            self._log("[DEBUG] Backup status updated")
        except Exception as e:
            self._log(f"Warning: Could not update backup status: {e}")

        # Load compact mode preference for this user
        try:
            self._log("[DEBUG] Loading compact mode preference after login...")
            from rogueeditor.persistence import persistence_manager
            last_compact = persistence_manager.get_user_value(self.username, "compact_mode", False)
            self.compact_mode.set(bool(last_compact))
            # Apply the setting immediately
            self._apply_compact_mode(last_compact)
            self._log(f"[DEBUG] Loaded and applied compact mode: {last_compact}")
        except Exception as e:
            self._log(f"Warning: Could not load compact mode preference: {e}")

        # Set up window geometry persistence after login
        try:
            self._setup_window_persistence()
            self._log("[DEBUG] Window persistence setup completed")
        except Exception as e:
            self._log(f"Warning: Could not setup window persistence: {e}")

        # Automatically refresh slots after login
        try:
            self._log("[DEBUG] Refreshing slots after login...")
            self._refresh_slots()
            self._log("[DEBUG] Slots refreshed after login")
        except Exception as e:
            self._log(f"Warning: Could not refresh slots after login: {e}")

        # Make sure busy indicator is hidden
        try:
            self._log("[DEBUG] Ensuring busy indicator is hidden...")
            while self._busy_count > 0:
                self._hide_busy()
            self._log("[DEBUG] Busy indicator hidden")
        except Exception as e:
            self._log(f"[ERROR] Failed to hide busy indicator: {e}")

        self._log("[DEBUG] Login completion finished.")

    def _start_background_cache_warming(self):
        """Start background cache warming for current slot only (reduced load)."""
        try:
            if not self.api or not self.username:
                return

            # Only warm cache for currently selected slot to reduce system load
            try:
                from rogueeditor.persistence import persistence_manager
                current_slot = int(persistence_manager.get_last_selected_slot(self.username))

                self._log(f"[DEBUG] Starting cache warming for current slot {current_slot} only...")
                future = warm_team_analysis_cache(self.api, current_slot, self.username)
                self._log(f"[DEBUG] Started cache warming for slot {current_slot}")

            except Exception as e:
                self._log(f"Warning: Could not start cache warming: {e}")

        except Exception as e:
            self._log(f"Warning: Could not start background cache warming: {e}")

    def _verify(self):
        self.editor.system_verify()
        self._log("System verify executed.")

    def _refresh_session(self):
        if not self.user_combo.get().strip() or not self.pass_entry.get():
            messagebox.showwarning("Missing", "Enter user and password first")
            return
        user = self.user_combo.get().strip()
        pwd = self.pass_entry.get()

        self._log(f"Starting session refresh for user: {user}")

        try:
            self._log("Creating new API instance for refresh...")
            # Re-login to obtain a fresh token and possibly server-provided clientSessionId
            api = PokerogueAPI(user, pwd)
            api.login()

            # If server did not send csid, generate a fresh one
            try:
                from rogueeditor.utils import generate_client_session_id
                csid = api.client_session_id or generate_client_session_id()
                api.client_session_id = csid
                try:
                    save_client_session_id(csid)
                    set_user_csid(user, csid)
                except Exception:
                    pass
            except Exception:
                pass

            # Schedule done callback on main thread with the new API
            def done_callback():
                try:
                    # Update session manager after refresh
                    try:
                        if self.session_manager:
                            self.session_manager.set_api_instance(api)
                    except Exception as e:
                        self._log(f"Warning: Session manager update failed: {e}")

                    # Update references
                    self.api = api
                    self.status_var.set(f"Status: Session refreshed for {user}")
                    # Session ID no longer displayed
                    self._log("Session refreshed.")
                    # Persist and reflect last session update time
                    try:
                        from datetime import datetime
                        from rogueeditor.utils import set_user_last_session_update
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        set_user_last_session_update(user, ts)
                        self.session_updated_var.set(f"Last session update: {ts}")
                    except Exception:
                        pass
                except Exception as done_err:
                    self._log(f"[ERROR] Session refresh completion failed: {done_err}")
                    self.feedback.show_error_toast(f"Session refresh completion failed: {done_err}")

            self.after(0, done_callback)

        except Exception as e:
            # Handle refresh errors properly
            def handle_refresh_error():
                self._log(f"[ERROR] Session refresh failed: {e}")
                self.feedback.handle_error(e, "Session Refresh", "refreshing session", use_toast=True)
                self.status_var.set(f"Status: Session refresh failed for {user}")

            self.after(0, handle_refresh_error)

    def _update_session_label_from_store(self):
        user = self.user_combo.get().strip()
        if not user:
            self.session_updated_var.set("Last session update: -")
            return
        try:
            from rogueeditor.utils import get_user_last_session_update
            ts = get_user_last_session_update(user)
            self.session_updated_var.set(f"Last session update: {ts}" if ts else "Last session update: -")
        except Exception:
            self.session_updated_var.set("Last session update: -")

    def _dump_trainer(self):
        p = trainer_save_path(self.username)
        if os.path.exists(p):
            if not self.feedback.confirm_action("Overwrite?", f"{p} exists. Overwrite with a fresh dump?", "dumping trainer data"):
                return

        self.editor.dump_trainer()
        self._log(f"Dumped trainer to {p}")
        # Refresh slots to show updated dump time
        self._refresh_slots()

    def _dump_slot_dialog(self):
        slot = self._ask_slot()
        if slot:
            p = slot_save_path(self.username, slot)
            if os.path.exists(p):
                if not messagebox.askyesno("Overwrite?", f"{p} exists. Overwrite with a fresh dump?"):
                    return
            self.editor.dump_slot(slot)
            self._log(f"Dumped slot {slot} to {p}")
            # Refresh slots to show updated dump time
            self._refresh_slots()
    def _dump_slot_selected(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            self.feedback.show_warning("Invalid slot")
            return

        p = slot_save_path(self.username, slot)
        if os.path.exists(p):
            if not self.feedback.confirm_action("Overwrite?", f"{p} exists. Overwrite with a fresh dump?", f"dumping slot {slot} data"):
                return

        self.editor.dump_slot(slot)
        self._log(f"Dumped slot {slot} to {p}")

    def _dump_all(self):
        if not self.feedback.confirm_action("Confirm", "Dump trainer and all slots to local files? Existing files will be overwritten.", "dumping all data"):
            return

        successes: list[str] = []
        errors: list[str] = []
        total_files = 6  # trainer + 5 slots max
        current_file = 0

        # Trainer
        try:
            current_file += 1
            self._log(f"Dumping trainer data... ({current_file}/{total_files})")
            self.editor.dump_trainer()
            successes.append("trainer")
            self._log("Dumped trainer data successfully")
        except Exception as e:
            errors.append(f"trainer: {e}")
            self._log(f"Trainer dump failed: {e}")

        # Slots 1..5
        for i in range(1, 6):
            try:
                current_file += 1
                self._log(f"Dumping slot {i}... ({current_file}/{total_files})")
                self.editor.dump_slot(i)
                successes.append(f"slot {i}")
                self._log(f"Dumped slot {i} successfully")
            except Exception as e:
                errors.append(f"slot {i}: {e}")
                self._log(f"Slot {i} dump failed: {e}")

        # Show summary on main thread
        def show_summary():
            # Only warn if no operations succeeded
            if errors and not successes:
                error_details = "\n".join(errors)
                self.feedback.error_handler.show_warning(
                    f"Dump failed completely - no files were dumped:\n{error_details}",
                    ErrorContext("dumping all data", "batch dump operation")
                )
            elif errors:
                # Some succeeded, some failed - log but don't warn user
                error_details = "\n".join(errors)
                self._log(f"Some dump operations failed:\n{error_details}")
                self.feedback.show_success(f"Dump partially successful - {len(successes)} files dumped, {len(errors)} failed")
            else:
                self.feedback.show_success("All files dumped successfully")
            # Refresh slots to show updated dump times
            self._refresh_slots()

        self.after(0, show_summary)

        # Log summary
        if successes:
            self._log("Successfully dumped: " + ", ".join(successes))

    def _update_trainer(self):
        if not self.feedback.confirm_action("Confirm", "Update trainer from file?", "uploading trainer data"):
            return

        def work():
            try:
                # Pre-validate JSON
                from rogueeditor.utils import trainer_save_path, load_json
                p = trainer_save_path(self.username)
                try:
                    data = load_json(p)
                except Exception as e:
                    self.feedback.error_handler.show_error(
                        Exception(f"{p}\n\n{e}"),
                        ErrorContext("uploading trainer data", "validating trainer.json")
                    )
                    return
                if not isinstance(data, dict):
                    self.feedback.error_handler.show_error(
                        Exception("Top-level must be a JSON object."),
                        ErrorContext("uploading trainer data", "validating trainer.json structure")
                    )
                    return
                self.api.update_trainer(data)
                self._log("Trainer updated from file.")

                # Schedule success message on main thread
                def show_success():
                    self.feedback.show_success("Trainer uploaded successfully.")
                    # Offer verification
                    if self.feedback.confirm_action("Verify", "Verify trainer on server matches local changes (key fields)?", "verifying trainer data"):
                        self._verify_trainer_against_local()

                self.after(0, show_success)

            except Exception as e:
                def show_error():
                    self.feedback.error_handler.show_error(e, ErrorContext("uploading trainer data"))
                self.after(0, show_error)
        
        # Run the upload asynchronously to avoid freezing the UI
        self._run_async("Uploading trainer data...", work)

    def _update_slot_dialog(self):
        slot = self._ask_slot()
        if slot and messagebox.askyesno("Confirm", f"Update slot {slot} from file?"):
            self.editor.update_slot_from_file(slot)
            self._log(f"Slot {slot} updated from file.")
    def _update_slot_selected(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            self.feedback.show_warning("Invalid slot")
            return
            
        if not self.feedback.confirm_action("Confirm", f"Update slot {slot} from file?", f"uploading slot {slot} data"):
            return

        def work():
            try:
                from rogueeditor.utils import slot_save_path, load_json
                p = slot_save_path(self.username, slot)
                try:
                    data = load_json(p)
                except Exception as e:
                    self.feedback.error_handler.show_error(
                        Exception(f"{p}\n\n{e}"),
                        ErrorContext(f"uploading slot {slot} data", "validating slot file")
                    )
                    return
                if not isinstance(data, dict):
                    self.feedback.error_handler.show_error(
                        Exception("Top-level must be a JSON object."),
                        ErrorContext(f"uploading slot {slot} data", "validating slot file structure")
                    )
                    return
                self.api.update_slot(slot, data)
                self._log(f"Slot {slot} updated from file.")

                # Schedule success message on main thread
                def show_success():
                    self.feedback.show_success(f"Slot {slot} uploaded successfully.")
                    # Offer verification
                    if self.feedback.confirm_action("Verify", f"Verify slot {slot} on server matches local changes (party/modifiers)?", f"verifying slot {slot} data"):
                        self._verify_slot_against_local(slot)

                self.after(0, show_success)

            except Exception as e:
                def show_error():
                    self.feedback.error_handler.show_error(e, ErrorContext(f"uploading slot {slot} data"))
                self.after(0, show_error)
                
        self._run_async(f"Uploading slot {slot} data...", work)

    def _upload_all(self):
        """Upload trainer.json and all present slot files (1-5) to the server with enhanced feedback."""
        from rogueeditor.utils import trainer_save_path, slot_save_path, load_json

        if not self.username:
            self.feedback.show_warning("Please login first")
            return

        if not self.feedback.confirm_action(
            "Confirm Upload All",
            "Upload trainer.json and all available slot files (1-5) to the server?\\n\\nThis overwrites server state.",
            "uploading all data"
        ):
            return

        def work():
            successes: list[str] = []
            errors: list[str] = []
            total_files = 6  # trainer + 5 slots max
            current_file = 0

            # Trainer
            try:
                current_file += 1
                # Update progress on main thread
                self.after(0, lambda: self.feedback.show_info(f"Uploading trainer data... ({current_file}/{total_files})"))

                tp = trainer_save_path(self.username)
                if os.path.exists(tp):
                    data = load_json(tp)
                    if not isinstance(data, dict):
                        raise ValueError("trainer.json must contain a JSON object")
                    self.api.update_trainer(data)
                    successes.append("trainer")
                    self._log("Uploaded trainer data successfully")
                else:
                    self._log(f"trainer.json not found at {tp}; skipping trainer upload")
            except Exception as e:
                errors.append(f"trainer: {e}")
                self._log(f"Failed to upload trainer: {e}")

            # Slots 1..5
            for i in range(1, 6):
                try:
                    current_file += 1
                    # Update progress on main thread
                    self.after(0, lambda i=i, current=current_file, total=total_files: self.feedback.show_info(f"Checking slot {i}... ({current}/{total})"))

                    sp = slot_save_path(self.username, i)
                    if not os.path.exists(sp):
                        continue

                    # Update progress on main thread
                    self.after(0, lambda i=i, current=current_file, total=total_files: self.feedback.show_info(f"Uploading slot {i}... ({current}/{total})"))

                    data = load_json(sp)
                    if not isinstance(data, dict):
                        raise ValueError(f"slot {i}.json must contain a JSON object")
                    self.api.update_slot(i, data)
                    successes.append(f"slot {i}")
                    self._log(f"Uploaded slot {i} successfully")
                except Exception as e:
                    errors.append(f"slot {i}: {e}")
                    self._log(f"Failed to upload slot {i}: {e}")

            # Complete progress and show summary on main thread
            def show_summary():
                if errors:
                    # Show detailed error message
                    error_details = "\n".join(errors)
                    self.feedback.error_handler.show_warning(
                        f"Upload completed with errors:\n{error_details}",
                        ErrorContext("uploading all data", "batch upload operation")
                    )
                else:
                    self.feedback.show_success("All files uploaded successfully")

                # Log summary
                if successes:
                    self._log("Successfully uploaded: " + ", ".join(successes))
                    
            self.after(0, show_summary)
            
        self._run_async("Uploading all data...", work)

    def _hatch_eggs(self):
        try:
            self.editor.hatch_all_eggs()
            self._log("Eggs set to hatch after next fight.")

            # Schedule success message on main thread
            def show_success():
                self.feedback.show_success("All eggs will hatch after the next fight.")
            self.after(0, show_success)

        except Exception as e:
            def show_error():
                self.feedback.error_handler.show_error(e, ErrorContext("hatching eggs"))
            self.after(0, show_error)

    # --- Verification helpers ---
    def _verify_slot_against_local(self, slot: int) -> None:
        try:
            from rogueeditor.utils import slot_save_path, load_json
            local_path = slot_save_path(self.username, slot)
            if not os.path.exists(local_path):
                messagebox.showwarning("No local dump", f"{local_path} not found. Dump first.")
                return
            local = load_json(local_path)
            remote = self.api.get_slot(slot)
            report_lines = [f"Verify slot {slot}", ""]
            keys = ['party', 'modifiers']
            all_ok = True
            for k in keys:
                l = local.get(k)
                r = remote.get(k)
                ok = (l == r)
                all_ok = all_ok and ok
                report_lines.append(f"[{k}] -> {'OK' if ok else 'MISMATCH'}")
            if all_ok:
                messagebox.showinfo("Verify", f"Slot {slot} matches local for keys: {', '.join(keys)}.")
            else:
                self._show_text_dialog(f"Verify Slot {slot}", "\n".join(report_lines))
        except Exception as e:
            messagebox.showerror("Verify failed", str(e))

    def _verify_trainer_against_local(self) -> None:
        try:
            from rogueeditor.utils import trainer_save_path, load_json
            local_path = trainer_save_path(self.username)
            if not os.path.exists(local_path):
                messagebox.showwarning("No local dump", f"{local_path} not found. Dump first.")
                return
            local = load_json(local_path)
            remote = self.api.get_trainer()
            report_lines = ["Verify trainer", ""]
            keys = ['voucherCounts', 'starterData', 'dexData', 'money']
            all_ok = True
            for k in keys:
                l = local.get(k)
                r = remote.get(k)
                ok = (l == r)
                all_ok = all_ok and ok
                report_lines.append(f"[{k}] -> {'OK' if ok else 'MISMATCH'}")
            if all_ok:
                messagebox.showinfo("Verify", "Trainer matches local for key fields.")
            else:
                self._show_text_dialog("Verify Trainer", "\n".join(report_lines))
        except Exception as e:
            messagebox.showerror("Verify failed", str(e))

    def _open_local_dump_dialog(self):
        # Opens trainer.json or slot N.json in the OS default editor
        from rogueeditor.utils import trainer_save_path, slot_save_path
        if not self.username:
            messagebox.showwarning("Missing", "Please log in/select a user first.")
            return
        top = tk.Toplevel(self)
        top.title("Rogue Manager GUI - Open Local Dump")
        ttk.Label(top, text="Open which file?").grid(row=0, column=0, columnspan=3, padx=6, pady=6, sticky=tk.W)
        choice = tk.StringVar(value='trainer')
        ttk.Radiobutton(top, text="Trainer (trainer.json)", variable=choice, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Radiobutton(top, text="Slot (slot N.json)", variable=choice, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6)
        ttk.Label(top, text="Slot:").grid(row=2, column=1, sticky=tk.E)
        slot_var = tk.StringVar(value=self.slot_var.get())
        ttk.Combobox(top, textvariable=slot_var, values=self._get_slot_values(), width=4, state='readonly').grid(row=2, column=2, sticky=tk.W)

        def open_path(path: str):
            if sys.platform.startswith('win'):
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except OSError as e:
                    messagebox.showerror("Open failed", str(e))
            elif sys.platform == 'darwin':
                try:
                    subprocess.run(['open', path], check=False)
                except Exception as e:
                    messagebox.showerror("Open failed", str(e))
            else:
                try:
                    subprocess.run(['xdg-open', path], check=False)
                except Exception as e:
                    messagebox.showerror("Open failed", str(e))

        def do_open():
            target = choice.get()
            if target == 'trainer':
                p = trainer_save_path(self.username)
            else:
                try:
                    s = int(slot_var.get())
                except Exception:
                    messagebox.showwarning("Invalid", "Invalid slot")
                    return
                p = slot_save_path(self.username, s)
            if not os.path.exists(p):
                messagebox.showwarning("Not found", f"{p} does not exist. Dump first.")
                return
            open_path(p)
            top.destroy()

        ttk.Button(top, text="Open", command=do_open).grid(row=3, column=0, padx=6, pady=10, sticky=tk.W)
        ttk.Button(top, text="Close", command=top.destroy).grid(row=3, column=1, padx=6, pady=10, sticky=tk.W)
        self._center_window(top)
        self._modalize(top)

    def _on_slot_select(self, event=None):
        # Remove selected tag from all items
        for item in self.slot_tree.get_children():
            current_tags = list(self.slot_tree.item(item, 'tags'))
            if 'selected' in current_tags:
                current_tags.remove('selected')
                self.slot_tree.item(item, tags=current_tags)
        
        # Add selected tag to currently selected items
        sel = self.slot_tree.selection()
        for item in sel:
            current_tags = list(self.slot_tree.item(item, 'tags'))
            if 'selected' not in current_tags:
                current_tags.append('selected')
                self.slot_tree.item(item, tags=current_tags)
        
        if sel:
            item = self.slot_tree.item(sel[0])
            values = item.get('values') or []
            if values:
                self.slot_var.set(str(values[0]))
                # Save the selected slot
                self._save_last_selected_slot()

    def _refresh_slots(self):
        import time
        from rogueeditor.utils import slot_save_path, load_json
        
        def work():
            rows = []
            any_local = False
            any_outdated = False

            # Get available slots from server (if connected) or fallback to local
            available_slots = self._get_available_slots()

            # Compare dump times with last session update if available
            last_update_ts = None
            try:
                from rogueeditor.utils import get_user_last_session_update
                ts_str = get_user_last_session_update(self.username or "")
                if ts_str:
                    import datetime as _dt
                    last_update_ts = _dt.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp()
            except Exception:
                last_update_ts = None

            # Only process slots that are actually available
            for i in available_slots:
                party_ct = '-'
                playtime = '-'
                empty = True
                local = '-'
                p = slot_save_path(self.username, i)
                if os.path.exists(p):
                    any_local = True
                    try:
                        data = load_json(p)
                        party = data.get('party') or []
                        party_ct = len(party)
                        pt = data.get('playTime') or 0
                        try:
                            h = int(pt) // 3600
                            m = (int(pt) % 3600) // 60
                            s = int(pt) % 60
                            playtime = f"{h:02d}:{m:02d}:{s:02d}"
                        except Exception:
                            playtime = '-'
                        empty = (party_ct == 0 and (int(pt) if isinstance(pt, int) else 0) == 0)
                        
                        # Extract wave data
                        wave_index = data.get('waveIndex')
                        if wave_index is not None:
                            try:
                                wave = str(int(wave_index))
                            except (ValueError, TypeError):
                                wave = '-'
                        else:
                            wave = '-'
                    except Exception:
                        empty = True
                        wave = '-'
                    ts = os.path.getmtime(p)
                    local = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                    if last_update_ts and ts < last_update_ts:
                        any_outdated = True
                else:
                    # Slot exists on server but not locally - mark as empty with server indicator
                    empty = True
                    wave = '-'
                    local = 'Not dumped'

                rows.append((i, party_ct, playtime, wave, local, empty))

            def update():
                # Clear existing slots
                for r in self.slot_tree.get_children():
                    self.slot_tree.delete(r)

                # Add only available slots
                if rows:
                    selected_slot = self.slot_var.get()
                    selected_slot_found = False
                    
                    for (slot, party_ct, playtime, wave, local, empty) in rows:
                        tags = ('empty',) if empty else ()
                        item_id = self.slot_tree.insert('', 'end', values=(slot, party_ct, playtime, wave, local), tags=tags)
                        
                        # Highlight the selected slot
                        if str(slot) == selected_slot:
                            selected_slot_found = True
                            self.slot_tree.selection_set(item_id)
                            # Apply selected tag for visual highlighting
                            current_tags = list(tags)
                            current_tags.append('selected')
                            self.slot_tree.item(item_id, tags=current_tags)
                    
                    # If selected slot not found or is empty, reset to slot 1
                    if not selected_slot_found or (selected_slot_found and any(str(row[0]) == selected_slot and row[5] for row in rows)):
                        # Selected slot is empty, reset to slot 1
                        self.slot_var.set("1")
                        # Find and select slot 1
                        for child in self.slot_tree.get_children():
                            item_values = self.slot_tree.item(child, 'values')
                            if item_values and str(item_values[0]) == "1":
                                self.slot_tree.selection_set(child)
                                # Apply selected tag for visual highlighting
                                current_tags = list(self.slot_tree.item(child, 'tags'))
                                if 'selected' not in current_tags:
                                    current_tags.append('selected')
                                    self.slot_tree.item(child, tags=current_tags)
                                break
                        # Save the reset slot
                        self._save_last_selected_slot()
                    elif not selected_slot_found:
                        # Selected slot doesn't exist, reset to slot 1
                        self.slot_var.set("1")
                        # Select the first available slot (should be slot 1)
                        if self.slot_tree.get_children():
                            first_item = self.slot_tree.get_children()[0]
                            self.slot_tree.selection_set(first_item)
                            # Apply selected tag for visual highlighting
                            current_tags = list(self.slot_tree.item(first_item, 'tags'))
                            if 'selected' not in current_tags:
                                current_tags.append('selected')
                                self.slot_tree.item(first_item, tags=current_tags)
                        # Save the reset slot
                        self._save_last_selected_slot()
                else:
                    # Show a placeholder when no slots exist
                    self.slot_tree.insert('', 'end', values=('No slots found', '-', '-', '-'), tags=('empty',))

                # Update available slot values for comboboxes
                self._update_slot_combobox_values(available_slots)

                # Informative messages
                if not available_slots:
                    try:
                        messagebox.showinfo('No save slots', 'No save slots found on server. Start a new game to create slots.')
                    except Exception:
                        pass
                elif not any_local:
                    try:
                        self.feedback.show_info('No local dumps found. Use Data IO → Dump to fetch trainer and/or slots you want to edit.', duration=6000)
                    except Exception:
                        pass
                elif any_outdated:
                    try:
                        self.feedback.show_warning('Some local dumps are older than the last login. Consider dumping again to avoid overwriting newer server data.', duration=8000)
                    except Exception:
                        pass

            self.after(0, update)
        self._run_async("Loading slots...", work)

    def _get_available_slots(self) -> list[int]:
        """
        Get list of available slot numbers, combining server and local detection.
        Prioritizes server data when available, falls back to local files.
        """
        available_slots = set()

        # Try to get slots from server first
        try:
            if hasattr(self, 'api') and self.api:
                server_slots = self.api.get_available_slots()
                available_slots.update(server_slots)
        except Exception:
            # Server detection failed, continue with local detection
            pass

        # Also check local files to include any locally dumped slots
        from rogueeditor.utils import slot_save_path, load_json
        import os
        for i in range(1, 6):
            p = slot_save_path(self.username, i)
            if os.path.exists(p):
                try:
                    data = load_json(p)
                    # Only include if it has meaningful content
                    if self._is_local_slot_non_empty(data):
                        available_slots.add(i)
                except Exception:
                    continue

        return sorted(list(available_slots))

    def _is_local_slot_non_empty(self, slot_data: dict) -> bool:
        """
        Check if local slot data indicates a non-empty/active slot.
        Similar to the API version but for local data structure.
        """
        if not slot_data:
            return False

        # Check for party with Pokemon
        party = slot_data.get('party', [])
        if party and len(party) > 0:
            return True

        # Check for playtime
        play_time = slot_data.get('playTime', 0)
        if play_time and play_time > 0:
            return True

        return False

    def _update_slot_combobox_values(self, available_slots: list[int]):
        """
        Update all slot comboboxes in the UI to show only available slots.
        """
        slot_values = [str(slot) for slot in available_slots] if available_slots else ["1"]

        # Store available slots for other components to use
        self._available_slots = available_slots

        # Update the main slot selector if it exists
        if hasattr(self, 'slot_var') and self.slot_var:
            current_value = self.slot_var.get()
            # If current selection is not in available slots, pick the first available
            if current_value not in slot_values and slot_values:
                self.slot_var.set(slot_values[0])

        # Note: Individual comboboxes will be updated when they're accessed or refreshed
        # This is because there are many comboboxes throughout the UI and updating them all
        # here would require tracking references to all of them

    def _get_slot_values(self) -> list[str]:
        """
        Get the current list of available slot values for comboboxes.
        Falls back to ["1"] if no slots are available.
        """
        if hasattr(self, '_available_slots') and self._available_slots:
            return [str(slot) for slot in self._available_slots]
        return ["1"]  # Fallback to ensure UI doesn't break

    def _backup(self):
        path = self.editor.backup_all()
        self._log(f"Backup created: {path}")
        # Schedule UI update on main thread
        def _post_backup():
            try:
                self._update_backup_status()
                self._refresh_backup_status()
            except Exception as e:
                self._log(f"Warning: Could not refresh backup status after backup: {e}")
            try:
                self._refresh_slots()
            except Exception as e:
                self._log(f"Warning: Could not refresh slots after backup: {e}")
        self.after(0, _post_backup)

    def _restore_dialog(self):
        base = os.path.join("Source", "saves", self.username, "backups")
        if not os.path.isdir(base):
            messagebox.showinfo("No backups", "No backups found.")
            return
        dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
        if not dirs:
            messagebox.showinfo("No backups", "No backups found.")
            return
        top = tk.Toplevel(self)
        top.title("Rogue Manager GUI - Select Backup")
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        lb = tk.Listbox(frm, height=12)
        sb = ttk.Scrollbar(frm, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for d in dirs:
            lb.insert(tk.END, d)
        def restore():
            sel = lb.curselection()
            if not sel:
                return
            backup_dir = os.path.join(base, lb.get(sel[0]))
            # Options dialog for scope
            scope = tk.StringVar(value='all')
            opt = tk.Toplevel(self)
            opt.title("Restore Options")
            ttk.Radiobutton(opt, text="Restore ALL (trainer + slots)", variable=scope, value='all').grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Trainer ONLY", variable=scope, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Specific Slot", variable=scope, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Label(opt, text="Slot:").grid(row=2, column=1, sticky=tk.E)
            slot_var = tk.StringVar(value='1')
            slot_cb = ttk.Combobox(opt, textvariable=slot_var, values=self._get_slot_values(), width=4, state='readonly')
            slot_cb.grid(row=2, column=2, sticky=tk.W)
            def do_restore():
                choice = scope.get()
                name = lb.get(sel[0])
                if not messagebox.askyesno("Confirm", f"Restore ({choice}) from {name}? This overwrites server state."):
                    return
                if choice == 'all':
                    self._run_async(
                        "Restoring backup (all)...",
                        lambda: self.editor.restore_from_backup(backup_dir),
                        lambda: self._log(f"Restored backup {backup_dir} (all)")
                    )
                elif choice == 'trainer':
                    def work():
                        from rogueeditor.utils import load_json
                        tp = os.path.join(backup_dir, 'trainer.json')
                        if os.path.exists(tp):
                            data = load_json(tp)
                            self.api.update_trainer(data)
                    self._run_async("Restoring backup (trainer)...", work, lambda: self._log(f"Restored trainer from {backup_dir}"))
                else:
                    try:
                        s = int(slot_var.get())
                    except Exception:
                        messagebox.showwarning("Invalid", "Invalid slot")
                        return
                    def work():
                        from rogueeditor.utils import load_json
                        sp = os.path.join(backup_dir, f"slot {s}.json")
                        if os.path.exists(sp):
                            data = load_json(sp)
                            self.api.update_slot(s, data)
                    self._run_async("Restoring backup (slot)...", work, lambda: self._log(f"Restored slot {s} from {backup_dir}"))
                opt.destroy(); top.destroy()
            ttk.Button(opt, text="Restore", command=do_restore).grid(row=3, column=0, columnspan=3, pady=8)
        def delete_backup():
            sel = lb.curselection()
            if not sel:
                return
            target = lb.get(sel[0])
            backup_dir = os.path.join(base, target)
            dirs2 = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            is_last = len(dirs2) == 1
            is_latest = (dirs2 and target == dirs2[-1])
            msg = f"Delete backup {target}?"
            if is_last:
                msg += "\nWARNING: This is the last backup."
            elif is_latest:
                msg += "\nWarning: This is the most recent backup."
            if not messagebox.askyesno("Confirm Delete", msg):
                return
            import shutil
            try:
                shutil.rmtree(backup_dir)
                self._log(f"Deleted backup {target}")
                lb.delete(sel[0])
                self._update_backup_status()
            except Exception as e:
                messagebox.showerror("Delete failed", str(e))
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(btns, text="Restore", command=restore).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Delete", command=delete_backup).pack(side=tk.LEFT, padx=4)

    def _update_backup_status(self):
        try:
            from rogueeditor.utils import user_save_dir
            from rogueeditor.persistence import persistence_manager
            import re
            import os
            if not self.username:
                self.backup_status_var.set("Last backup: none")
                return
            base = os.path.join(user_save_dir(self.username), "backups")
            if not os.path.isdir(base):
                self.backup_status_var.set("Last backup: none")
                return
            # Only consider timestamped backup folders: YYYYMMDD_HHMMSS
            all_dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
            ts_re = re.compile(r"^\d{8}_\d{6}$")
            dirs = sorted([d for d in all_dirs if ts_re.match(d)])
            
            if dirs:
                latest_backup = dirs[-1]
                self.backup_status_var.set(f"Last backup: {latest_backup}")
                # Save to persistence
                persistence_manager.set_last_backup(self.username, latest_backup)
            else:
                self.backup_status_var.set("Last backup: none")
                # Clear persistence
                persistence_manager.set_last_backup(self.username, None)
        except Exception:
            self.backup_status_var.set("Last backup: unknown")

    def _refresh_backup_status(self):
        # Backwards-compatible alias; centralize any extra refresh logic here
        self._update_backup_status()

    def _restore_dialog2(self):
        from rogueeditor.utils import user_save_dir, load_json
        base = os.path.join(user_save_dir(self.username or ""), "backups")
        if not os.path.isdir(base):
            messagebox.showinfo("No backups", "No backups found.")
            return
        dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
        if not dirs:
            messagebox.showinfo("No backups", "No backups found.")
            return
        top = tk.Toplevel(self)
        top.title("Rogue Manager GUI - Select Backup")
        frm = ttk.Frame(top)
        frm.pack(fill=tk.BOTH, expand=True)
        lb = tk.Listbox(frm, height=12)
        sb = ttk.Scrollbar(frm, orient='vertical', command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        for d in dirs:
            lb.insert(tk.END, d)
        def restore():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            backup_dir = os.path.join(base, name)
            scope = tk.StringVar(value='all')
            opt = tk.Toplevel(self)
            opt.title("Restore Options")
            ttk.Radiobutton(opt, text="Restore ALL (trainer + slots)", variable=scope, value='all').grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Trainer ONLY", variable=scope, value='trainer').grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Radiobutton(opt, text="Restore Specific Slot", variable=scope, value='slot').grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
            ttk.Label(opt, text="Slot:").grid(row=2, column=1, sticky=tk.E)
            slot_var = tk.StringVar(value='1')
            slot_cb = ttk.Combobox(opt, textvariable=slot_var, values=self._get_slot_values(), width=4, state='readonly')
            slot_cb.grid(row=2, column=2, sticky=tk.W)
            def do_restore():
                choice = scope.get()
                if not messagebox.askyesno("Confirm", f"Restore ({choice}) from {name}? This overwrites server state."):
                    return
                if choice == 'all':
                    self._run_async("Restoring backup (all)...", lambda: self.editor.restore_from_backup(backup_dir), lambda: [self._log(f"Restored backup {name} (all)"), self._update_backup_status(), self._refresh_slots()])
                elif choice == 'trainer':
                    def work():
                        tp = os.path.join(backup_dir, 'trainer.json')
                        if os.path.exists(tp):
                            data = load_json(tp)
                            self.api.update_trainer(data)
                    self._run_async("Restoring trainer...", work, lambda: [self._log(f"Restored trainer from {name}"), self._update_backup_status(), self._refresh_slots()])
                else:
                    try:
                        s = int(slot_var.get())
                    except Exception:
                        messagebox.showwarning("Invalid", "Invalid slot")
                        return
                    def work():
                        sp = os.path.join(backup_dir, f"slot {s}.json")
                        if os.path.exists(sp):
                            data = load_json(sp)
                            self.api.update_slot(s, data)
                    self._run_async("Restoring slot...", work, lambda: [self._log(f"Restored slot {s} from {name}"), self._update_backup_status(), self._refresh_slots()])
                opt.destroy(); top.destroy()
            ttk.Button(opt, text="Restore", command=do_restore).grid(row=3, column=0, columnspan=3, pady=8)
            try:
                opt.transient(self)
                opt.grab_set()
            except Exception:
                pass
        def delete_backup():
            sel = lb.curselection()
            if not sel:
                return
            target = lb.get(sel[0])
            bdir = os.path.join(base, target)
            d2 = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
            is_last = (len(d2) == 1)
            is_latest = (d2 and target == d2[-1])
            msg = f"Delete backup {target}?"
            if is_last:
                msg += "\nWARNING: This is the last backup."
            elif is_latest:
                msg += "\nWarning: This is the most recent backup."
            if not messagebox.askyesno("Confirm Delete", msg):
                return
            import shutil
            try:
                shutil.rmtree(bdir)
                self._log(f"Deleted backup {target}")
                lb.delete(sel[0])
                self._update_backup_status()
            except Exception as e:
                messagebox.showerror("Delete failed", str(e))
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(btns, text="Restore", command=restore).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Delete", command=delete_backup).pack(side=tk.LEFT, padx=4)
        self._modalize(top)

    def _upload_local_dialog(self):
        # A simple dialog to upload trainer.json and/or selected slot file to server.
        from rogueeditor.utils import trainer_save_path, slot_save_path, load_json
        top = tk.Toplevel(self)
        top.title("Upload Local Changes")
        ttk.Label(top, text="Choose what to upload to the server:").grid(row=0, column=0, columnspan=3, padx=6, pady=6, sticky=tk.W)
        tr_var = tk.BooleanVar(value=True)
        sl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Trainer (trainer.json)", variable=tr_var).grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Label(top, text="Slot:").grid(row=2, column=0, sticky=tk.E, padx=6)
        slot_var = tk.StringVar(value=self.slot_var.get())
        ttk.Combobox(top, textvariable=slot_var, values=self._get_slot_values(), width=4, state='readonly').grid(row=2, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text="Upload slot file (slot N.json)", variable=sl_var).grid(row=2, column=2, sticky=tk.W, padx=6)
        def do_upload():
            # Trainer
            if tr_var.get():
                try:
                    tp = trainer_save_path(self.username)
                    if os.path.exists(tp):
                        data = load_json(tp)
                        self.api.update_trainer(data)
                        self._log(f"Uploaded trainer from {tp}")
                    else:
                        messagebox.showwarning("Missing", f"{tp} not found")
                except Exception as e:
                    messagebox.showerror("Trainer upload failed", str(e))
                    return
            # Slot
            if sl_var.get():
                try:
                    s = int(slot_var.get())
                except Exception:
                    messagebox.showwarning("Invalid", "Invalid slot")
                    return
                sp = slot_save_path(self.username, s)
                if os.path.exists(sp):
                    try:
                        data = load_json(sp)
                        self.api.update_slot(s, data)
                        self._log(f"Uploaded slot {s} from {sp}")
                    except Exception as e:
                        messagebox.showerror("Slot upload failed", str(e))
                        return
                else:
                    messagebox.showwarning("Missing", f"{sp} not found")
                    return
            messagebox.showinfo("Upload", "Upload completed.")
            top.destroy()
        ttk.Button(top, text="Upload", command=do_upload).grid(row=3, column=0, padx=6, pady=10, sticky=tk.W)
        ttk.Button(top, text="Close", command=top.destroy).grid(row=3, column=1, padx=6, pady=10, sticky=tk.W)
        self._center_window(top)

    # _analyze_team_dialog removed - marked for removal

    # _analyze_run_conditions removed - marked for removal

    def _edit_run_weather(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if not slot:
            return
        # Fetch session and find weather key
        data = self.api.get_slot(slot)
        wkey = None
        for k in ("weather", "weatherType", "currentWeather"):
            if k in data:
                wkey = k
                break
        if not wkey:
            messagebox.showinfo("Run Weather", "Weather field not found in session.")
            return
        from rogueeditor.catalog import load_weather_catalog
        n2i, i2n = load_weather_catalog()
        top = tk.Toplevel(self)
        top.title(f"Rogue Manager GUI - Edit Run Weather (Slot {slot})")
        ttk.Label(top, text="Weather:").grid(row=0, column=0, padx=6, pady=6)
        items = [f"{name} ({iid})" for name, iid in sorted(n2i.items(), key=lambda kv: kv[0])]
        var = tk.StringVar()
        cb = ttk.Combobox(top, values=items, textvariable=var, width=28)
        cur = data.get(wkey)
        cur_disp = i2n.get(int(cur), str(cur)) if isinstance(cur, int) else str(cur)
        var.set(f"{cur_disp} ({cur})")
        cb.grid(row=0, column=1, padx=6, pady=6)
        def do_apply():
            text = var.get().strip()
            val = None
            if text.endswith(')') and '(' in text:
                try:
                    val = int(text.rsplit('(',1)[1].rstrip(')'))
                except Exception:
                    val = None
            if val is None:
                key = text.strip().lower().replace(' ', '_')
                val = n2i.get(key)
            if not isinstance(val, int):
                messagebox.showwarning('Invalid', 'Select a valid weather')
                return
            data[wkey] = val
            from rogueeditor.utils import slot_save_path
            p = slot_save_path(self.api.username, slot)
            # Use safe save operation with backup
            backup_path = self.safe_save_manager.safe_dump_json(
                p, data, f"Weather change to {val} for slot {slot}"
            )
            self._log(f"Updated weather to {val}; wrote {p} (backup: {backup_path})")
            if messagebox.askyesno('Upload', 'Upload changes to server?'):
                try:
                    self.api.update_slot(slot, data)
                    messagebox.showinfo('Uploaded', 'Server updated successfully')
                except Exception as e:
                    messagebox.showerror('Upload failed', str(e))
            top.destroy()
        ttk.Button(top, text='Apply', command=do_apply).grid(row=1, column=1, padx=6, pady=6, sticky=tk.W)
        self._center_window(top)

    def _edit_team_dialog(self):
        print("[TRACE] _edit_team_dialog ENTRY")
        self._log("[DEBUG] _edit_team_dialog method called")
        print("[TRACE] About to get slot variable")
        try:
            slot = int(self.slot_var.get())
            print(f"[TRACE] Got slot from variable: {slot}")
        except Exception as e:
            print(f"[TRACE] Exception getting slot variable: {e}")
            slot = self._ask_slot()
            print(f"[TRACE] Got slot from dialog: {slot}")
        print(f"[TRACE] Checking if slot {slot} is valid")
        if slot:
            # Ensure clientSessionId is available for team editor
            if not getattr(self.api, 'client_session_id', None):
                self._log("[DEBUG] clientSessionId missing, regenerating...")
                try:
                    from rogueeditor.utils import generate_client_session_id, save_client_session_id
                    csid = generate_client_session_id()
                    self.api.client_session_id = csid
                    save_client_session_id(csid)
                    self._log(f"[DEBUG] Generated new clientSessionId: {csid[:12]}...")
                except Exception as e:
                    self._log(f"[ERROR] Failed to generate clientSessionId: {e}")

            print(f"[TRACE] About to create TeamManagerDialog for slot {slot}")
            self._log(f"[DEBUG] About to create TeamManagerDialog for slot {slot}")
            TeamManagerDialog(self, self.api, self.editor, slot)
            print(f"[TRACE] TeamManagerDialog created successfully")
            self._log(f"Opened team editor for slot {slot}")

    # _enhanced_item_manager_dialog removed - marked for removal, functionality integrated into main item manager

    def _list_mods_dialog(self):
        if not self.editor:
            messagebox.showwarning("Not logged in", "Please login first")
            return
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            self._run_and_show_output(f"Modifiers - Slot {slot}", lambda: self.editor.list_modifiers(slot))

    def _open_item_mgr(self):
        try:
            slot = int(self.slot_var.get())
        except Exception:
            slot = self._ask_slot()
        if slot:
            ItemManagerDialog(self, self.api, self.editor, slot)
            self._log(f"Opened item manager for slot {slot}")

    def _open_starters_manager(self):
        """Open the comprehensive starters management dialog."""
        if not self.editor:
            self.feedback.show_warning("Please login first")
            return
        from gui.dialogs.starters_manager import StartersManagerDialog
        StartersManagerDialog(self, self.api, self.editor)
        self._log("Opened starters manager")

    def _hatch_all_eggs_quick(self):
        """Quick action to hatch all eggs."""
        if not self.editor:
            self.feedback.show_warning("Please login first")
            return
        try:
            self.editor.hatch_all_eggs()
            self._log("All eggs will hatch after the next battle!")
            self.feedback.show_success("All eggs will hatch after the next battle!")
        except Exception as e:
            self.feedback.handle_error(e, "Hatch Eggs", "hatching all eggs")

    def _unlock_all_starters(self):
        # Strong warning + typed confirmation
        if not messagebox.askyesno('Warning', 'This will UNLOCK ALL STARTERS with perfect IVs and shiny variants. Proceed?'):
            return
        top = tk.Toplevel(self)
        top.title('Unlock ALL Starters - Confirmation')
        msg = (
            'WARNING:\n\n'
            'This action will UNLOCK ALL STARTERS with perfect IVs and shiny variants.\n'
            'It may significantly impact or ruin your player experience.\n\n'
            'To confirm, type the phrase exactly and check the acknowledgment:'
        )
        ttk.Label(top, text=msg, justify=tk.LEFT, wraplength=520).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
        expected = 'UNLOCK ALL STARTERS'
        ttk.Label(top, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
        phrase_var = tk.StringVar()
        ttk.Entry(top, textvariable=phrase_var, width=34).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
        ack_var = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='I accept the risks and understand this is final.', variable=ack_var).grid(row=2, column=0, columnspan=2, padx=8, pady=6, sticky=tk.W)
        def proceed():
            text = (phrase_var.get() or '').strip()
            if text != expected:
                messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                return
            if not ack_var.get():
                messagebox.showwarning('Not confirmed', 'Please acknowledge the risks to proceed.')
                return
            try:
                self.editor.unlock_all_starters()
                self._log('All starters unlocked (perfect IVs, shinies).')
                messagebox.showinfo('Completed', 'All starters unlocked successfully.')
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))
        ttk.Button(top, text='Cancel', command=top.destroy).grid(row=3, column=0, padx=8, pady=10, sticky=tk.W)
        ttk.Button(top, text='Proceed', command=proceed).grid(row=3, column=1, padx=8, pady=10, sticky=tk.E)

    def _unlock_all_passives(self):
        # Use the selected starter in the autocomplete
        ident = self.starter_ac.get().strip()
        if not ident:
            messagebox.showwarning('Missing', 'Select a Pokemon in the Starters section first.')
            return
        if not messagebox.askyesno('Warning', f'This will unlock ALL passives for {ident}. Proceed?'):
            return
        # Phrase confirmation
        top = tk.Toplevel(self)
        top.title('Unlock All Passives - Confirmation')
        msg = (
            'WARNING:\n\nThis action will set passiveAttr to an unlocked mask for the selected starter.\n'
            'It may impact progression. To confirm, type the phrase exactly:'
        )
        ttk.Label(top, text=msg, justify=tk.LEFT, wraplength=520).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
        expected = 'UNLOCK ALL PASSIVES'
        ttk.Label(top, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
        phrase_var = tk.StringVar()
        ttk.Entry(top, textvariable=phrase_var, width=34).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
        def proceed():
            text = (phrase_var.get() or '').strip()
            if text != expected:
                messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                return
            try:
                self.editor.unlock_all_passives(ident, mask=7)
                self._log(f'Unlocked all passives for {ident}.')
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))
        ttk.Button(top, text='Cancel', command=top.destroy).grid(row=2, column=0, padx=8, pady=10, sticky=tk.W)
        ttk.Button(top, text='Proceed', command=proceed).grid(row=2, column=1, padx=8, pady=10, sticky=tk.E)

    def _pokedex_list(self):
        if not self.editor:
            messagebox.showwarning('Not logged in', 'Please login first')
            return
        self._run_and_show_output('Pokedex', lambda: self.editor.pokedex_list())

    def _unlock_starter_dialog(self):
        # Dialog to pick a starter and set unlock properties
        from rogueeditor.utils import load_pokemon_index
        from rogueeditor.catalog import load_move_catalog, load_ability_attr_mask
        index = load_pokemon_index()
        dex = (index.get('dex') or {})
        # Build display mapping like "#001 Bulbasaur" -> id
        def _pretty(n: str) -> str:
            return n.replace('_', ' ').title()
        disp_to_id: dict[str, int] = {}
        for name, vid in dex.items():
            try:
                i = int(vid)
            except Exception:
                continue
            disp = f"#{i:03d} {_pretty(name)}"
            disp_to_id[disp] = i
        # Select starter via catalog dialog
        sid = CatalogSelectDialog.select(self, disp_to_id, 'Select Starter')
        if sid is None:
            return
        # Resolve display name
        sel_disp = None
        for n, i in disp_to_id.items():
            if i == sid:
                sel_disp = n
                break
        # Build dialog
        top = tk.Toplevel(self)
        top.title(f"Unlock Starter - {sel_disp or ('#%03d' % sid)}")
        ttk.Label(top, text=f"Selected: {sel_disp or ('#%03d' % sid)}").grid(row=0, column=0, columnspan=6, sticky=tk.W, padx=6, pady=6)

        # Options
        perfect_iv = tk.IntVar(value=1)
        shiny_var = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='Perfect IVs (31s)', variable=perfect_iv).grid(row=1, column=0, sticky=tk.W, padx=6)
        ttk.Checkbutton(top, text='Shiny', variable=shiny_var).grid(row=1, column=1, sticky=tk.W, padx=6)

        ttk.Label(top, text='Seen:').grid(row=2, column=0, sticky=tk.E)
        seen_e = ttk.Entry(top, width=6); seen_e.insert(0, '10'); seen_e.grid(row=2, column=1, sticky=tk.W)
        ttk.Label(top, text='Caught:').grid(row=2, column=2, sticky=tk.E)
        caught_e = ttk.Entry(top, width=6); caught_e.insert(0, '5'); caught_e.grid(row=2, column=3, sticky=tk.W)
        ttk.Label(top, text='Hatched:').grid(row=2, column=4, sticky=tk.E)
        hatched_e = ttk.Entry(top, width=6); hatched_e.insert(0, '0'); hatched_e.grid(row=2, column=5, sticky=tk.W)

        # StarterData properties
        ttk.Label(top, text='Candy Count:').grid(row=3, column=0, sticky=tk.E)
        candy_e = ttk.Entry(top, width=8); candy_e.insert(0, '0'); candy_e.grid(row=3, column=1, sticky=tk.W)
        ttk.Label(top, text='Cost Reduction (valueReduction):').grid(row=3, column=2, sticky=tk.E)
        vr_e = ttk.Entry(top, width=8); vr_e.insert(0, '0'); vr_e.grid(row=3, column=3, sticky=tk.W)

        # abilityAttr mask
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        aa1 = tk.IntVar(value=1); aa2 = tk.IntVar(value=1); aah = tk.IntVar(value=1)
        ttk.Label(top, text='abilityAttr:').grid(row=4, column=0, sticky=tk.W, padx=6)
        ttk.Checkbutton(top, text='Ability 1', variable=aa1).grid(row=4, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text='Ability 2', variable=aa2).grid(row=4, column=2, sticky=tk.W)
        ttk.Checkbutton(top, text='Hidden', variable=aah).grid(row=4, column=3, sticky=tk.W)

        # passiveAttr flags
        ttk.Label(top, text='passiveAttr:').grid(row=5, column=0, sticky=tk.W, padx=6)
        p_unlocked = tk.IntVar(value=1); p_enabled = tk.IntVar(value=0)
        ttk.Checkbutton(top, text='Unlocked', variable=p_unlocked).grid(row=5, column=1, sticky=tk.W)
        ttk.Checkbutton(top, text='Enabled', variable=p_enabled).grid(row=5, column=2, sticky=tk.W)

        # Moveset (optional)
        ttk.Label(top, text='Starter Moves (optional):').grid(row=6, column=0, sticky=tk.W, padx=6)
        move_n2i, move_i2n = load_move_catalog()
        move_acs = []
        for i in range(4):
            ac = AutoCompleteEntry(top, move_n2i, width=24)
            ac.grid(row=6+i, column=1, sticky=tk.W, padx=4, pady=2)
            ttk.Button(top, text='Pick', command=lambda j=i: self._pick_from_catalog(move_acs[j], move_n2i, f'Select Move {j+1}')).grid(row=6+i, column=2, sticky=tk.W)
            move_acs.append(ac)

        def do_apply():
            try:
                seen = int(seen_e.get().strip() or '0')
                caught = int(caught_e.get().strip() or '0')
                hatched = int(hatched_e.get().strip() or '0')
                candy = int(candy_e.get().strip() or '0')
                vr = int(vr_e.get().strip() or '0')
            except ValueError:
                messagebox.showwarning('Invalid', 'Counts and cost reduction must be integers')
                return
            # Compose trainer update
            data = self.api.get_trainer()
            dex_id = str(sid)
            # dexData
            shiny_attr = 255 if shiny_var.get() else 253
            dex_entry = {
                "seenAttr": 479,
                "caughtAttr": shiny_attr,
                "natureAttr": 67108862,
                "seenCount": max(0, seen),
                "caughtCount": max(0, caught),
                "hatchedCount": max(0, hatched),
            }
            if perfect_iv.get():
                dex_entry["ivs"] = [31, 31, 31, 31, 31, 31]
            data.setdefault('dexData', {})[dex_id] = {**(data.get('dexData', {}).get(dex_id) or {}), **dex_entry}
            # starterData
            abil_mask = (mask.get('ability_1',1) if aa1.get() else 0) | (mask.get('ability_2',2) if aa2.get() else 0) | (mask.get('ability_hidden',4) if aah.get() else 0)
            passive = (1 if p_unlocked.get() else 0) | (2 if p_enabled.get() else 0)
            moves = []
            for ac in move_acs:
                mid = ac.get_id()
                if isinstance(mid, int):
                    moves.append(mid)
            starter_entry = {
                "moveset": moves or None,
                "eggMoves": 15,
                "candyCount": max(0, candy),
                "abilityAttr": abil_mask or 7,
                "passiveAttr": passive,
                "valueReduction": max(0, vr),
            }
            data.setdefault('starterData', {})[dex_id] = {**(data.get('starterData', {}).get(dex_id) or {}), **starter_entry}
            try:
                self.api.update_trainer(data)
                messagebox.showinfo('Starter', 'Starter unlocked/updated successfully.')
                self._log(f"Updated starter dex {dex_id}")
                top.destroy()
            except Exception as e:
                messagebox.showerror('Failed', str(e))

        ttk.Button(top, text='Apply', command=do_apply).grid(row=10, column=1, padx=6, pady=8, sticky=tk.W)
        def do_apply_and_upload():
            if not messagebox.askyesno('Warning', 'This will unlock the selected starter and update your account on the server. Proceed?'):
                return
            # Phrase confirmation
            confirm = tk.Toplevel(self)
            confirm.title('Unlock Starter - Confirmation')
            msg = 'Type the phrase to confirm:'
            ttk.Label(confirm, text=msg, justify=tk.LEFT, wraplength=420).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky=tk.W)
            expected = 'UNLOCK STARTER'
            ttk.Label(confirm, text=f"Type: {expected}").grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
            pv = tk.StringVar()
            ttk.Entry(confirm, textvariable=pv, width=30).grid(row=1, column=1, padx=8, pady=4, sticky=tk.W)
            def proceed_unlock():
                if (pv.get() or '').strip() != expected:
                    messagebox.showwarning('Not confirmed', 'Phrase does not match. Action cancelled.')
                    return
                confirm.destroy()
                do_apply()
            ttk.Button(confirm, text='Cancel', command=confirm.destroy).grid(row=2, column=0, padx=8, pady=8, sticky=tk.W)
            ttk.Button(confirm, text='Proceed', command=proceed_unlock).grid(row=2, column=1, padx=8, pady=8, sticky=tk.E)
        ttk.Button(top, text='Apply and Upload', command=do_apply_and_upload).grid(row=10, column=2, padx=6, pady=8, sticky=tk.W)
        ttk.Button(top, text='Close', command=top.destroy).grid(row=10, column=3, padx=6, pady=8, sticky=tk.W)

    def _add_item_dialog(self):
        slot = self._ask_slot()
        if not slot:
            return
        idx = self._ask_int("Team slot (1-5): ")
        if not idx:
            return
        item = self._ask_str("Item type (e.g., WIDE_LENS, BERRY, BASE_STAT_BOOSTER): ")
        if not item:
            return
        if item.strip().upper() == "BASE_STAT_BOOSTER":
            # Ask stat
            from rogueeditor.catalog import load_stat_catalog
            n2i, i2n = load_stat_catalog()
            top = tk.Toplevel(self)
            top.title("Select Stat")
            ttk.Label(top, text="Stat (id or name):").pack(padx=6, pady=6)
            ac = AutoCompleteEntry(top, n2i)
            ac.pack(padx=6, pady=6)
            def ok():
                stat_id = ac.get_id()
                if stat_id is None:
                    messagebox.showwarning("Invalid", "Please select a stat")
                    return
                top.destroy()
                if messagebox.askyesno("Confirm", f"Attach {item}({stat_id}) to team slot {idx}?"):
                    # Build entry directly
                    data = self.api.get_slot(slot)
                    party = data.get("party") or []
                    mon = party[idx-1]
                    mon_id = mon.get("id")
                    entry = {
                        "args": [mon_id, stat_id],
                        "player": True,
                        "stackCount": 1,
                        "typeId": "BASE_STAT_BOOSTER",
                        "typePregenArgs": [stat_id],
                    }
                    mods = data.setdefault("modifiers", [])
                    mods.append(entry)
                    from rogueeditor.utils import slot_save_path
                    p = slot_save_path(self.api.username, slot)
                    # Use safe save operation with backup
                    backup_path = self.safe_save_manager.safe_dump_json(
                        p, data, f"Added BASE_STAT_BOOSTER({stat_id}) to slot {slot} position {idx}"
                    )
                    self._log(f"Attached BASE_STAT_BOOSTER({stat_id}) to slot {idx}; wrote {p} (backup: {backup_path})")
                    if messagebox.askyesno("Upload", "Upload changes to server?"):
                        try:
                            self.api.update_slot(slot, data)
                            messagebox.showinfo("Uploaded", "Server updated.")
                        except Exception as e:
                            messagebox.showerror("Upload failed", str(e))
            ttk.Button(top, text="OK", command=ok).pack(pady=6)
            ac.focus_set()
            self.wait_window(top)
        else:
            if messagebox.askyesno("Confirm", f"Attach {item} to team slot {idx}?"):
                self.editor.add_item_to_mon(slot, idx, item)
                self._log(f"Attached {item} to slot {idx}")

    def _remove_item_dialog(self):
        slot = self._ask_slot()
        if not slot:
            return
        idx = self._ask_int("Team slot (1-5): ")
        if not idx:
            return
        item = self._ask_str("Item type to remove: ")
        if not item:
            return
        if messagebox.askyesno("Confirm", f"Remove {item} from team slot {idx}?"):
            self.editor.remove_item_from_mon(slot, idx, item)
            self._log(f"Removed {item} from slot {idx}")

    # --- Simple inputs ---
    def _ask_slot(self) -> int | None:
        try:
            return int(self._ask_str("Slot (1-5): ") or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Invalid slot")
            return None

    def _ask_int(self, prompt: str) -> int | None:
        try:
            return int(self._ask_str(prompt) or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Invalid number")
            return None

    def _ask_str(self, prompt: str) -> str:
        top = tk.Toplevel(self)
        top.title("Input")
        ttk.Label(top, text=prompt).pack(padx=6, pady=6)
        ent = ttk.Entry(top)
        ent.pack(padx=6, pady=6)
        out = {"v": None}
        def ok():
            out["v"] = ent.get().strip()
            top.destroy()
        ttk.Button(top, text="OK", command=ok).pack(pady=6)
        ent.focus_set()
        self.wait_window(top)
        return out["v"]

    # --- Starters handlers ---
    def _get_starter_dex_id(self) -> int | None:
        sid = self.starter_ac.get_id()
        if sid is None:
            messagebox.showwarning("Missing", "Select a Pokemon by name or id")
            return None
        return sid

    def _apply_starter_attrs(self):
        sid = self._get_starter_dex_id()
        if sid is None:
            return
        # abilityAttr from checkboxes
        mask = load_ability_attr_mask() or {"ability_1": 1, "ability_2": 2, "ability_hidden": 4}
        ability_attr = (self.aa1.get() and mask.get("ability_1", 1) or 0) + \
                       (self.aa2.get() and mask.get("ability_2", 2) or 0) + \
                       (self.aah.get() and mask.get("ability_hidden", 4) or 0)
        # passiveAttr from flags
        passive_attr = (self.p_unlocked.get() and 1 or 0) + (self.p_enabled.get() and 2 or 0)
        try:
            value_reduction = int(self.starter_value_reduction.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Cost reduction must be integer")
            return
        if not messagebox.askyesno("Confirm", f"Apply attrs to dex {sid} (save locally)?"):
            return
        data = self.api.get_trainer()
        s = data.setdefault("starterData", {})
        key = str(sid)
        entry = s.get(key) or {"moveset": None, "eggMoves": 15, "candyCount": 0, "abilityAttr": 7, "passiveAttr": 0, "valueReduction": 0}
        entry["abilityAttr"] = ability_attr
        entry["passiveAttr"] = passive_attr
        entry["valueReduction"] = value_reduction
        s[key] = entry
        # Save locally then offer upload
        from rogueeditor.utils import trainer_save_path
        p = trainer_save_path(self.api.username)
        # Use safe save operation with backup
        backup_path = self.safe_save_manager.safe_dump_json(
            p, data, f"Starter data update: abilityAttr={ability_attr}, passiveAttr={passive_attr}, valueReduction={value_reduction}"
        )
        messagebox.showinfo("Saved", f"Wrote {p} (backup: {backup_path})")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Server updated.")

    def _inc_starter_candies(self):
        sid = self._get_starter_dex_id()
        if sid is None:
            return
        try:
            delta = int(self.starter_candy_delta.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "Delta must be integer")
            return
        if not messagebox.askyesno("Confirm", f"Increment candies by {delta} (save locally)?"):
            return
        data = self.api.get_trainer()
        s = data.setdefault("starterData", {})
        key = str(sid)
        entry = s.get(key) or {"moveset": None, "eggMoves": 15, "candyCount": 0, "abilityAttr": 7, "passiveAttr": 0, "valueReduction": 0}
        entry["candyCount"] = max(0, int(entry.get("candyCount", 0)) + delta)
        s[key] = entry
        from rogueeditor.utils import trainer_save_path
        p = trainer_save_path(self.api.username)
        # Use safe save operation with backup
        backup_path = self.safe_save_manager.safe_dump_json(
            p, data, f"Candy count increment by {delta} for starter {sid}"
        )
        messagebox.showinfo("Saved", f"Wrote {p} (backup: {backup_path})")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Server updated.")

    def _apply_gacha_delta(self):
        try:
            d0 = int(self.gacha_d0.get().strip() or "0")
            d1 = int(self.gacha_d1.get().strip() or "0")
            d2 = int(self.gacha_d2.get().strip() or "0")
            d3 = int(self.gacha_d3.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Invalid", "All deltas must be integers")
            return
        if not messagebox.askyesno("Confirm", f"Apply Gacha ? C/R/E/L = {d0}/{d1}/{d2}/{d3} (save locally)?"):
            return
        data = self.api.get_trainer()
        current = data.get("voucherCounts") or {}
        def cur(k):
            try:
                return int(current.get(k, 0))
            except Exception:
                return 0
        updated = {
            "0": max(0, cur("0") + d0),
            "1": max(0, cur("1") + d1),
            "2": max(0, cur("2") + d2),
            "3": max(0, cur("3") + d3),
        }
        data["voucherCounts"] = updated
        from rogueeditor.utils import trainer_save_path
        p = trainer_save_path(self.api.username)
        # Use safe save operation with backup
        backup_path = self.safe_save_manager.safe_dump_json(
            p, data, f"Gacha voucher update: C/R/E/L = {d0}/{d1}/{d2}/{d3}"
        )
        messagebox.showinfo("Saved", f"Wrote {p} (backup: {backup_path})")
        if messagebox.askyesno("Upload", "Upload trainer changes to server?"):
            self.api.update_trainer(data)
            messagebox.showinfo("Uploaded", "Gacha tickets updated on server")

    def _setup_window_persistence(self):
        """Set up window geometry persistence for the main window."""
        try:
            root = self.winfo_toplevel()
            # Load saved geometry if available (try current user first, then fallback to app-wide)
            saved_geometry = self._load_main_window_geometry()
            if saved_geometry:
                root.geometry(saved_geometry)
            # Set up save on resize/move
            root.bind('<Configure>', self._on_main_window_configure)
        except Exception as e:
            self._debug_log(f"Window persistence setup error: {e}")
            pass  # Fail silently if persistence setup fails

    def _load_main_window_geometry(self) -> str:
        """Load saved main window geometry from persistence."""
        try:
            from rogueeditor.persistence import persistence_manager
            # Try user-specific geometry first
            if self.username:
                user_geometry = persistence_manager.get_user_value(self.username, 'main_window_geometry')
                if user_geometry:
                    return user_geometry
            # Fallback to app-wide geometry
            return persistence_manager.get_app_value('main_window_geometry')
        except Exception:
            pass
        return None

    def _on_main_window_configure(self, event=None):
        """Save main window geometry when window is resized or moved."""
        # Only save if the event is for the main window (not child widgets)
        if event and event.widget != self.winfo_toplevel():
            return
        try:
            from rogueeditor.persistence import persistence_manager
            root = self.winfo_toplevel()
            geometry = root.geometry()
            # Save to app-wide settings (works for all users)
            persistence_manager.set_app_value('main_window_geometry', geometry)
            # Also save to user-specific settings if logged in
            if self.username:
                persistence_manager.set_user_value(self.username, 'main_window_geometry', geometry)
        except Exception:
            pass


def _debug_simple_log(message):
    """Simple debug logging to file."""
    try:
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        with open("gui_debug.log", "a") as f:
            f.write(f"[RUN] [{timestamp}] {message}\n")
    except:
        pass  # Silently fail to avoid recursion

def run():
    _debug_simple_log("Run function started")
    # Initialize logging early so startup issues are captured
    logger = setup_logging()
    attach_stderr_tee(logger)
    install_excepthook(logger)
    log_environment(logger)

    # Ensure GUI starts from the main thread to avoid Tcl/Tk notifier errors on Windows
    try:
        import threading as _th
        if _th.current_thread() is not _th.main_thread():
            raise RuntimeError('GUI must be launched from the main thread')
    except Exception as e:
        log_exception_context("Main-thread check failed", logger)
        print("[ERROR] GUI must be launched from the main thread.")
        print(crash_hint())
        return 2

    # Optional proactive healthcheck on first run or after a failed run
    try:
        should_check = is_first_run() or (last_run_success() is False)
    except Exception:
        should_check = False
    if should_check:
        try:
            run_healthcheck(trigger="startup")
        except Exception:
            log_exception_context("Healthcheck failed", logger)

    # Create a single Tk root and host App as a Frame to avoid multiple Tk instances
    try:
        # On Windows, help Tk find the correct bundled Tcl/Tk if env vars are unset
        import sys as _sys, os as _os
        if _os.name == 'nt' and not _os.environ.get('TCL_LIBRARY') and not _os.environ.get('TK_LIBRARY'):
            base = getattr(_sys, 'base_prefix', _sys.exec_prefix)
            tcl_dir = _os.path.join(base, 'tcl', 'tcl8.6')
            tk_dir = _os.path.join(base, 'tcl', 'tk8.6')
            if _os.path.isdir(tcl_dir) and _os.path.isdir(tk_dir):
                _os.environ['TCL_LIBRARY'] = tcl_dir
                _os.environ['TK_LIBRARY'] = tk_dir
                try:
                    logger.info('Set TCL_LIBRARY to %s and TK_LIBRARY to %s', tcl_dir, tk_dir)
                except Exception:
                    pass
        root = tk.Tk()
    except Exception:
        log_exception_context("Failed to initialize Tk root", logger)
        print("[ERROR] Failed to initialize GUI (Tk).")
        print(crash_hint())
        record_run_result(3, trigger="gui")
        return 3
    try:
        logger.debug("About to create App instance")
        app = RogueManagerGUI(root)
        logger.debug("App instance created successfully")
        logger.debug("Starting mainloop")
        root.mainloop()
        logger.debug("Mainloop ended")
    except Exception:
        log_exception_context("Unhandled error in GUI mainloop", logger)
        print("[ERROR] Unhandled GUI error.")
        print(crash_hint())
        record_run_result(4, trigger="gui")
        return 4
    record_run_result(0, trigger="gui")
    return 0
