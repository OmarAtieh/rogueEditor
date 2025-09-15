"""Integration layer for enhanced user feedback systems."""

from __future__ import annotations

import functools
import threading
import time
import tkinter as tk
from typing import Callable, Any, Optional, Dict, Union
import logging

from .toast import ToastManager, ToastType
from .error_handler import EnhancedErrorHandler, ErrorContext, safe_operation
from .progress import ProgressManager, ProgressType, ProgressOperation


class FeedbackIntegrator:
    """Integrates all feedback systems with the existing GUI."""

    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.logger = logging.getLogger(__name__)

        # Initialize feedback systems
        self.toast_manager = ToastManager(parent)
        self.error_handler = EnhancedErrorHandler(parent, self.toast_manager)
        self.progress_manager = ProgressManager(parent, self.toast_manager)

        # Track operation states
        self._active_operations: Dict[str, ProgressOperation] = {}

    # === Toast Notifications ===

    def show_success(self, message: str, duration: int = 4000) -> str:
        """Show success toast notification."""
        return self.toast_manager.show_success(message, duration)

    def show_info(self, message: str, duration: int = 5000) -> str:
        """Show info toast notification."""
        return self.toast_manager.show_info(message, duration)

    def show_warning(self, message: str, duration: int = 6000) -> str:
        """Show warning toast notification."""
        return self.toast_manager.show_warning(message, duration)

    def show_error_toast(self, message: str, duration: int = 8000) -> str:
        """Show error toast notification."""
        return self.toast_manager.show_error(message, duration)

    # === Enhanced Error Handling ===

    def handle_error(self, exception: Exception, operation: str = "", user_action: str = "",
                    use_toast: bool = False) -> None:
        """Handle an exception with enhanced error reporting."""
        context = ErrorContext(operation, user_action)
        self.error_handler.handle_exception(exception, context, show_dialog=not use_toast, use_toast=use_toast)

    def confirm_action(self, title: str, message: str, operation: str = "") -> bool:
        """Show confirmation dialog with context logging."""
        context = ErrorContext(operation) if operation else None
        return self.error_handler.confirm_action(title, message, context)

    # === Progress Operations ===

    def start_progress(self, operation_id: str, title: str, description: str = "",
                      show_dialog: bool = False, show_toast: bool = True,
                      cancellable: bool = False) -> str:
        """Start a progress operation with appropriate feedback."""
        operation = self.progress_manager.start_operation(
            operation_id, title, description,
            progress_type=ProgressType.INDETERMINATE,
            cancellable=cancellable,
            show_dialog=show_dialog,
            show_toast=show_toast
        )
        self._active_operations[operation_id] = operation
        return operation_id

    def update_progress(self, operation_id: str, message: Optional[str] = None,
                       progress: Optional[float] = None) -> bool:
        """Update progress operation."""
        return self.progress_manager.update_operation(operation_id, progress, message)

    def complete_progress(self, operation_id: str, success_message: str = "") -> None:
        """Complete progress operation with success feedback."""
        self.progress_manager.complete_operation(operation_id, "Completed")
        if operation_id in self._active_operations:
            del self._active_operations[operation_id]

        if success_message:
            self.show_success(success_message)

    def fail_progress(self, operation_id: str, error: Exception, error_message: str = "") -> None:
        """Fail progress operation with error feedback."""
        self.progress_manager.fail_operation(operation_id, error)
        if operation_id in self._active_operations:
            del self._active_operations[operation_id]

        if error_message:
            self.show_error_toast(error_message)

    # === Safe Operation Wrappers ===

    def safe_wrapper(self, operation_name: str, use_toast: bool = True, show_progress: bool = False,
                    progress_message: str = "") -> Callable:
        """Create a safe wrapper for operations with comprehensive feedback."""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                operation_id = None

                try:
                    # Start progress if requested
                    if show_progress:
                        operation_id = f"{func.__name__}_{int(time.time() * 1000)}"
                        progress_title = progress_message or f"Processing {operation_name}..."
                        self.start_progress(operation_id, progress_title, show_dialog=False, show_toast=True)

                    # Execute the function
                    result = func(*args, **kwargs)

                    # Complete progress and show success
                    if operation_id:
                        self.complete_progress(operation_id, f"{operation_name} completed successfully")
                    elif not show_progress:
                        # Only show success toast if we're not already showing progress completion
                        self.show_success(f"{operation_name} completed successfully")

                    return result

                except Exception as e:
                    # Handle error
                    if operation_id:
                        self.fail_progress(operation_id, e)

                    self.handle_error(e, operation_name, f"executing {func.__name__}", use_toast=use_toast)
                    return None

            return wrapper
        return decorator

    def safe_async_wrapper(self, operation_name: str, use_toast: bool = True,
                          show_progress: bool = True, progress_message: str = "") -> Callable:
        """Create a safe async wrapper that runs operations in background threads."""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                operation_id = f"{func.__name__}_{int(time.time() * 1000)}"

                def background_work():
                    try:
                        if show_progress:
                            progress_title = progress_message or f"Processing {operation_name}..."
                            self.parent.after(0, lambda: self.start_progress(
                                operation_id, progress_title, show_dialog=False, show_toast=True
                            ))

                        # Execute the function
                        result = func(*args, **kwargs)

                        # Schedule UI updates on main thread
                        self.parent.after(0, lambda: self.complete_progress(
                            operation_id, f"{operation_name} completed successfully"
                        ))

                        return result

                    except Exception as e:
                        # Schedule error handling on main thread
                        self.parent.after(0, lambda: self.fail_progress(operation_id, e))
                        self.parent.after(0, lambda: self.handle_error(
                            e, operation_name, f"executing {func.__name__}", use_toast=use_toast
                        ))

                # Start background thread
                thread = threading.Thread(target=background_work, daemon=True)
                thread.start()

                # Return None immediately to allow UI to remain responsive
                return None

            return wrapper
        return decorator

    # === Integration with Legacy Code ===

    def replace_messagebox_calls(self, use_toasts: bool = True) -> Dict[str, Callable]:
        """
        Provide drop-in replacements for messagebox calls.

        Returns a dictionary of functions that can replace messagebox methods.
        """
        if use_toasts:
            return {
                'showinfo': lambda title, message: self.show_info(message),
                'showwarning': lambda title, message: self.show_warning(message),
                'showerror': lambda title, message: self.show_error_toast(message),
                'askyesno': lambda title, message: self.confirm_action(title, message)
            }
        else:
            # Keep dialogs but with enhanced error context
            from tkinter import messagebox
            return {
                'showinfo': messagebox.showinfo,
                'showwarning': messagebox.showwarning,
                'showerror': messagebox.showerror,
                'askyesno': messagebox.askyesno
            }

    def enhance_existing_busy_methods(self, gui_instance) -> None:
        """Enhance existing _show_busy/_hide_busy methods with toast notifications."""
        original_show_busy = gui_instance._show_busy
        original_hide_busy = gui_instance._hide_busy
        original_run_async = gui_instance._run_async

        def enhanced_show_busy():
            original_show_busy()
            # Could add toast notification here if desired

        def enhanced_hide_busy():
            original_hide_busy()
            # Could add completion toast here if desired

        def enhanced_run_async(desc: str, work, on_done=None):
            operation_id = f"async_{int(time.time() * 1000)}"

            def wrapped_work():
                try:
                    work()
                    if on_done:
                        def success_callback():
                            on_done()
                            self.show_success(f"{desc} completed")
                        gui_instance.after(0, success_callback)
                    else:
                        gui_instance.after(0, lambda: self.show_success(f"{desc} completed"))
                except Exception as e:
                    gui_instance.after(0, lambda: self.handle_error(e, desc, use_toast=True))

            original_run_async(desc, wrapped_work, None)

        # Replace methods
        gui_instance._show_busy = enhanced_show_busy
        gui_instance._hide_busy = enhanced_hide_busy
        gui_instance._run_async = enhanced_run_async

    # === Utility Methods ===

    def cleanup(self) -> None:
        """Clean up resources and close any active notifications."""
        self.toast_manager.close_all_toasts()
        self.progress_manager.cleanup_completed_operations()
        self._active_operations.clear()

    def get_active_operations(self) -> Dict[str, ProgressOperation]:
        """Get currently active operations."""
        return self._active_operations.copy()

    def cancel_all_operations(self) -> None:
        """Cancel all active operations."""
        for operation in self._active_operations.values():
            operation.cancel()
        self._active_operations.clear()


# === Decorators for Easy Integration ===

def with_feedback(integrator: FeedbackIntegrator, operation_name: str,
                 use_toast: bool = True, show_progress: bool = False,
                 progress_message: str = ""):
    """Decorator to add feedback to any function."""
    return integrator.safe_wrapper(operation_name, use_toast, show_progress, progress_message)


def with_async_feedback(integrator: FeedbackIntegrator, operation_name: str,
                       use_toast: bool = True, show_progress: bool = True,
                       progress_message: str = ""):
    """Decorator to add async feedback to any function."""
    return integrator.safe_async_wrapper(operation_name, use_toast, show_progress, progress_message)


# === Helper Functions for Common Patterns ===

def create_upload_feedback(integrator: FeedbackIntegrator, item_name: str = "data"):
    """Create feedback decorators for upload operations."""
    return {
        'start': lambda: integrator.start_progress(
            f"upload_{item_name}", f"Uploading {item_name}...", show_toast=True
        ),
        'success': lambda: integrator.show_success(f"{item_name.title()} uploaded successfully"),
        'error': lambda e: integrator.handle_error(e, f"uploading {item_name}", use_toast=True)
    }


def create_download_feedback(integrator: FeedbackIntegrator, item_name: str = "data"):
    """Create feedback decorators for download operations."""
    return {
        'start': lambda: integrator.start_progress(
            f"download_{item_name}", f"Downloading {item_name}...", show_toast=True
        ),
        'success': lambda: integrator.show_success(f"{item_name.title()} downloaded successfully"),
        'error': lambda e: integrator.handle_error(e, f"downloading {item_name}", use_toast=True)
    }