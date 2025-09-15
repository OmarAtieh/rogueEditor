"""Advanced progress indication system with cancellation support."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, Any, Dict, Union
from enum import Enum
import queue
import logging

from .toast import ToastManager, ToastType


class ProgressState(Enum):
    """Progress operation states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ProgressType(Enum):
    """Types of progress indicators."""
    DETERMINATE = "determinate"    # Known progress (0-100%)
    INDETERMINATE = "indeterminate"  # Unknown progress (spinner)
    STEPS = "steps"                # Step-based progress (1 of N)


class ProgressUpdate:
    """Update message for progress operations."""
    def __init__(self, progress: Optional[float] = None, message: Optional[str] = None,
                 step: Optional[int] = None, total_steps: Optional[int] = None):
        self.progress = progress  # 0-100 for determinate progress
        self.message = message
        self.step = step
        self.total_steps = total_steps
        self.timestamp = time.time()


class ProgressOperation:
    """Represents a long-running operation with progress tracking."""

    def __init__(self, operation_id: str, title: str, description: str = "",
                 progress_type: ProgressType = ProgressType.INDETERMINATE,
                 cancellable: bool = True, total_steps: Optional[int] = None):
        self.operation_id = operation_id
        self.title = title
        self.description = description
        self.progress_type = progress_type
        self.cancellable = cancellable
        self.total_steps = total_steps

        # State
        self.state = ProgressState.PENDING
        self.progress = 0.0  # 0-100
        self.current_step = 0
        self.current_message = description
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.error: Optional[Exception] = None

        # Threading
        self._cancel_event = threading.Event()
        self._update_queue: queue.Queue = queue.Queue()
        self._callbacks: Dict[ProgressState, list] = {state: [] for state in ProgressState}

    def start(self) -> None:
        """Mark operation as started."""
        self.state = ProgressState.RUNNING
        self.start_time = time.time()
        self._notify_callbacks(ProgressState.RUNNING)

    def update(self, update: ProgressUpdate) -> None:
        """Update progress information."""
        if self.state != ProgressState.RUNNING:
            return

        if update.progress is not None:
            self.progress = max(0, min(100, update.progress))

        if update.message is not None:
            self.current_message = update.message

        if update.step is not None:
            self.current_step = update.step
            if self.total_steps and self.progress_type == ProgressType.STEPS:
                self.progress = (update.step / self.total_steps) * 100

        if update.total_steps is not None:
            self.total_steps = update.total_steps

        self._update_queue.put(update)

    def complete(self, message: str = "Completed") -> None:
        """Mark operation as completed."""
        if self.state == ProgressState.RUNNING:
            self.state = ProgressState.COMPLETED
            self.end_time = time.time()
            self.progress = 100.0
            self.current_message = message
            self._notify_callbacks(ProgressState.COMPLETED)

    def cancel(self) -> None:
        """Cancel the operation."""
        if self.state == ProgressState.RUNNING:
            self.state = ProgressState.CANCELLED
            self.end_time = time.time()
            self.current_message = "Cancelled"
            self._cancel_event.set()
            self._notify_callbacks(ProgressState.CANCELLED)

    def fail(self, error: Exception, message: str = "Failed") -> None:
        """Mark operation as failed."""
        if self.state == ProgressState.RUNNING:
            self.state = ProgressState.FAILED
            self.end_time = time.time()
            self.error = error
            self.current_message = message
            self._notify_callbacks(ProgressState.FAILED)

    def is_cancelled(self) -> bool:
        """Check if operation was cancelled."""
        return self._cancel_event.is_set()

    def add_callback(self, state: ProgressState, callback: Callable) -> None:
        """Add callback for state changes."""
        self._callbacks[state].append(callback)

    def _notify_callbacks(self, state: ProgressState) -> None:
        """Notify callbacks of state change."""
        for callback in self._callbacks[state]:
            try:
                callback(self)
            except Exception as e:
                logging.getLogger(__name__).error(f"Progress callback error: {e}")

    @property
    def duration(self) -> Optional[float]:
        """Get operation duration in seconds."""
        if self.start_time is None:
            return None
        end_time = self.end_time or time.time()
        return end_time - self.start_time

    @property
    def estimated_remaining(self) -> Optional[float]:
        """Estimate remaining time in seconds."""
        if (self.start_time is None or self.progress <= 0 or
            self.state != ProgressState.RUNNING):
            return None

        elapsed = time.time() - self.start_time
        progress_fraction = self.progress / 100.0
        total_estimated = elapsed / progress_fraction
        return max(0, total_estimated - elapsed)


class ProgressDialog:
    """Modal progress dialog with cancellation support."""

    def __init__(self, parent: tk.Widget, operation: ProgressOperation):
        self.parent = parent
        self.operation = operation
        self.dialog: Optional[tk.Toplevel] = None
        self.progress_var: Optional[tk.DoubleVar] = None
        self.message_var: Optional[tk.StringVar] = None
        self.cancel_button: Optional[tk.Button] = None
        self._update_timer: Optional[str] = None

    def show(self) -> None:
        """Show the progress dialog."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.operation.title)
        self.dialog.geometry("400x200")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        # Center on parent
        self.dialog.update_idletasks()
        x = (self.parent.winfo_rootx() + (self.parent.winfo_width() // 2) -
             (self.dialog.winfo_width() // 2))
        y = (self.parent.winfo_rooty() + (self.parent.winfo_height() // 2) -
             (self.dialog.winfo_height() // 2))
        self.dialog.geometry(f"+{x}+{y}")

        # Build UI
        self._build_ui()

        # Set up callbacks
        self.operation.add_callback(ProgressState.COMPLETED, self._on_completed)
        self.operation.add_callback(ProgressState.CANCELLED, self._on_cancelled)
        self.operation.add_callback(ProgressState.FAILED, self._on_failed)

        # Start update timer
        self._schedule_update()

        # Handle window close
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _build_ui(self) -> None:
        """Build the dialog UI."""
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text=self.operation.title, font=("Arial", 12, "bold"))
        title_label.pack(pady=(0, 10))

        # Description/current message
        self.message_var = tk.StringVar(value=self.operation.current_message)
        message_label = ttk.Label(main_frame, textvariable=self.message_var, wraplength=350)
        message_label.pack(pady=(0, 15))

        # Progress bar
        self.progress_var = tk.DoubleVar()

        if self.operation.progress_type == ProgressType.INDETERMINATE:
            progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
            progress_bar.start(10)
        else:
            progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)

        progress_bar.pack(fill=tk.X, pady=(0, 10))

        # Progress text (for determinate progress)
        if self.operation.progress_type in (ProgressType.DETERMINATE, ProgressType.STEPS):
            self.progress_text_var = tk.StringVar()
            progress_text_label = ttk.Label(main_frame, textvariable=self.progress_text_var)
            progress_text_label.pack(pady=(0, 15))

        # Time info
        self.time_info_var = tk.StringVar()
        time_info_label = ttk.Label(main_frame, textvariable=self.time_info_var, font=("Arial", 9))
        time_info_label.pack(pady=(0, 15))

        # Cancel button
        if self.operation.cancellable:
            button_frame = ttk.Frame(main_frame)
            button_frame.pack(fill=tk.X)

            self.cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
            self.cancel_button.pack(side=tk.RIGHT)

    def _schedule_update(self) -> None:
        """Schedule next UI update."""
        if self.dialog and self.operation.state == ProgressState.RUNNING:
            self._update_ui()
            self._update_timer = self.dialog.after(100, self._schedule_update)

    def _update_ui(self) -> None:
        """Update UI with current progress."""
        if not self.dialog:
            return

        # Process any queued updates
        try:
            while True:
                update = self.operation._update_queue.get_nowait()
                # Update is processed by the operation itself
        except queue.Empty:
            pass

        # Update message
        if self.message_var:
            self.message_var.set(self.operation.current_message)

        # Update progress
        if self.progress_var and self.operation.progress_type != ProgressType.INDETERMINATE:
            self.progress_var.set(self.operation.progress)

        # Update progress text
        if hasattr(self, 'progress_text_var'):
            if self.operation.progress_type == ProgressType.STEPS and self.operation.total_steps:
                text = f"Step {self.operation.current_step} of {self.operation.total_steps}"
            else:
                text = f"{self.operation.progress:.1f}%"
            self.progress_text_var.set(text)

        # Update time info
        if self.time_info_var and self.operation.duration:
            duration_str = f"Elapsed: {self.operation.duration:.1f}s"

            if (self.operation.progress_type != ProgressType.INDETERMINATE and
                self.operation.estimated_remaining):
                duration_str += f" | Remaining: ~{self.operation.estimated_remaining:.1f}s"

            self.time_info_var.set(duration_str)

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        if self.cancel_button:
            self.cancel_button.configure(state='disabled', text='Cancelling...')
        self.operation.cancel()

    def _on_completed(self, operation: ProgressOperation) -> None:
        """Handle operation completion."""
        self._close_dialog()

    def _on_cancelled(self, operation: ProgressOperation) -> None:
        """Handle operation cancellation."""
        self._close_dialog()

    def _on_failed(self, operation: ProgressOperation) -> None:
        """Handle operation failure."""
        self._close_dialog()

    def _on_window_close(self) -> None:
        """Handle window close button."""
        if self.operation.cancellable and self.operation.state == ProgressState.RUNNING:
            self.operation.cancel()
        else:
            self._close_dialog()

    def _close_dialog(self) -> None:
        """Close the dialog."""
        if self._update_timer:
            self.dialog.after_cancel(self._update_timer)
            self._update_timer = None

        if self.dialog:
            self.dialog.grab_release()
            self.dialog.destroy()
            self.dialog = None


class ProgressManager:
    """Manages multiple progress operations and provides different display modes."""

    def __init__(self, parent: tk.Widget, toast_manager: Optional[ToastManager] = None):
        self.parent = parent
        self.toast_manager = toast_manager
        self.operations: Dict[str, ProgressOperation] = {}
        self.logger = logging.getLogger(__name__)

    def start_operation(self, operation_id: str, title: str, description: str = "",
                       progress_type: ProgressType = ProgressType.INDETERMINATE,
                       cancellable: bool = True, total_steps: Optional[int] = None,
                       show_dialog: bool = True, show_toast: bool = False) -> ProgressOperation:
        """
        Start a new progress operation.

        Args:
            operation_id: Unique identifier for the operation
            title: Operation title
            description: Operation description
            progress_type: Type of progress indicator
            cancellable: Whether the operation can be cancelled
            total_steps: Total number of steps (for step-based progress)
            show_dialog: Whether to show progress dialog
            show_toast: Whether to show progress toast

        Returns:
            ProgressOperation instance
        """
        # Stop existing operation with same ID
        if operation_id in self.operations:
            self.operations[operation_id].cancel()

        # Create new operation
        operation = ProgressOperation(
            operation_id, title, description, progress_type, cancellable, total_steps
        )

        self.operations[operation_id] = operation

        # Set up completion callbacks
        operation.add_callback(ProgressState.COMPLETED, self._on_operation_completed)
        operation.add_callback(ProgressState.CANCELLED, self._on_operation_cancelled)
        operation.add_callback(ProgressState.FAILED, self._on_operation_failed)

        # Show progress UI
        if show_dialog:
            dialog = ProgressDialog(self.parent, operation)
            dialog.show()

        if show_toast and self.toast_manager:
            toast_id = self.toast_manager.show_progress(title)
            operation._toast_id = toast_id

        operation.start()
        return operation

    def update_operation(self, operation_id: str, progress: Optional[float] = None,
                        message: Optional[str] = None, step: Optional[int] = None) -> bool:
        """
        Update an existing operation.

        Returns:
            True if operation was found and updated, False otherwise
        """
        if operation_id not in self.operations:
            return False

        operation = self.operations[operation_id]
        update = ProgressUpdate(progress, message, step)
        operation.update(update)

        # Update toast if present
        if hasattr(operation, '_toast_id') and self.toast_manager:
            self.toast_manager.update_toast(operation._toast_id, message, progress)

        return True

    def complete_operation(self, operation_id: str, message: str = "Completed") -> bool:
        """
        Mark an operation as completed.

        Returns:
            True if operation was found and completed, False otherwise
        """
        if operation_id not in self.operations:
            return False

        operation = self.operations[operation_id]
        operation.complete(message)
        return True

    def cancel_operation(self, operation_id: str) -> bool:
        """
        Cancel an operation.

        Returns:
            True if operation was found and cancelled, False otherwise
        """
        if operation_id not in self.operations:
            return False

        operation = self.operations[operation_id]
        operation.cancel()
        return True

    def fail_operation(self, operation_id: str, error: Exception, message: str = "Failed") -> bool:
        """
        Mark an operation as failed.

        Returns:
            True if operation was found and marked as failed, False otherwise
        """
        if operation_id not in self.operations:
            return False

        operation = self.operations[operation_id]
        operation.fail(error, message)
        return True

    def get_operation(self, operation_id: str) -> Optional[ProgressOperation]:
        """Get an operation by ID."""
        return self.operations.get(operation_id)

    def _on_operation_completed(self, operation: ProgressOperation) -> None:
        """Handle operation completion."""
        self.logger.info(f"Operation completed: {operation.title} ({operation.duration:.1f}s)")

        # Close toast if present
        if hasattr(operation, '_toast_id') and self.toast_manager:
            self.toast_manager.close_toast(operation._toast_id)
            self.toast_manager.show_success(f"{operation.title} completed successfully")

    def _on_operation_cancelled(self, operation: ProgressOperation) -> None:
        """Handle operation cancellation."""
        self.logger.info(f"Operation cancelled: {operation.title}")

        # Close toast if present
        if hasattr(operation, '_toast_id') and self.toast_manager:
            self.toast_manager.close_toast(operation._toast_id)
            self.toast_manager.show_warning(f"{operation.title} was cancelled")

    def _on_operation_failed(self, operation: ProgressOperation) -> None:
        """Handle operation failure."""
        self.logger.error(f"Operation failed: {operation.title} - {operation.error}")

        # Close toast if present
        if hasattr(operation, '_toast_id') and self.toast_manager:
            self.toast_manager.close_toast(operation._toast_id)
            self.toast_manager.show_error(f"{operation.title} failed: {operation.current_message}")

    def cleanup_completed_operations(self) -> None:
        """Remove completed, cancelled, and failed operations."""
        to_remove = []
        for op_id, operation in self.operations.items():
            if operation.state in (ProgressState.COMPLETED, ProgressState.CANCELLED, ProgressState.FAILED):
                to_remove.append(op_id)

        for op_id in to_remove:
            del self.operations[op_id]


def with_progress(progress_manager: ProgressManager, title: str, description: str = "",
                 progress_type: ProgressType = ProgressType.INDETERMINATE,
                 show_dialog: bool = True, show_toast: bool = False):
    """Decorator to run a function with progress indication."""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            operation_id = f"{func.__name__}_{int(time.time() * 1000)}"

            operation = progress_manager.start_operation(
                operation_id, title, description, progress_type,
                cancellable=False, show_dialog=show_dialog, show_toast=show_toast
            )

            try:
                result = func(*args, **kwargs)
                progress_manager.complete_operation(operation_id)
                return result
            except Exception as e:
                progress_manager.fail_operation(operation_id, e)
                raise

        return wrapper
    return decorator