"""Toast notification system for non-blocking user feedback."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict, Any, Literal
import threading
import time
from enum import Enum


class ToastType(Enum):
    """Toast notification types."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PROGRESS = "progress"


class Toast:
    """Individual toast notification widget."""

    def __init__(self, parent: tk.Widget, message: str, toast_type: ToastType = ToastType.INFO,
                 duration: int = 5000, show_close: bool = True, progress_value: Optional[float] = None):
        self.parent = parent
        self.message = message
        self.toast_type = toast_type
        self.duration = duration
        self.show_close = show_close
        self.progress_value = progress_value
        self.widget: Optional[tk.Toplevel] = None
        self.progress_var: Optional[tk.DoubleVar] = None
        self._close_callback: Optional[callable] = None
        self._auto_close_timer: Optional[str] = None

        # Toast styling
        self.colors = {
            ToastType.INFO: {"bg": "#2196F3", "fg": "white"},
            ToastType.SUCCESS: {"bg": "#4CAF50", "fg": "white"},
            ToastType.WARNING: {"bg": "#FF9800", "fg": "white"},
            ToastType.ERROR: {"bg": "#F44336", "fg": "white"},
            ToastType.PROGRESS: {"bg": "#2196F3", "fg": "white"}
        }

        self.icons = {
            ToastType.INFO: "ℹ",
            ToastType.SUCCESS: "✓",
            ToastType.WARNING: "⚠",
            ToastType.ERROR: "✗",
            ToastType.PROGRESS: "⏳"
        }

    def show(self) -> None:
        """Display the toast notification."""
        if self.widget:
            return  # Already showing

        # Create toplevel window
        self.widget = tk.Toplevel(self.parent)
        self.widget.withdraw()  # Hide initially for positioning
        self.widget.overrideredirect(True)  # Remove window decorations
        self.widget.attributes("-topmost", True)  # Keep on top

        # Configure styling
        style_config = self.colors[self.toast_type]
        self.widget.configure(bg=style_config["bg"])

        # Main frame
        main_frame = tk.Frame(self.widget, bg=style_config["bg"], padx=16, pady=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Content frame
        content_frame = tk.Frame(main_frame, bg=style_config["bg"])
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Icon and message
        header_frame = tk.Frame(content_frame, bg=style_config["bg"])
        header_frame.pack(fill=tk.X, pady=(0, 4))

        icon_label = tk.Label(
            header_frame,
            text=self.icons[self.toast_type],
            bg=style_config["bg"],
            fg=style_config["fg"],
            font=("Arial", 12, "bold")
        )
        icon_label.pack(side=tk.LEFT, padx=(0, 8))

        message_label = tk.Label(
            header_frame,
            text=self.message,
            bg=style_config["bg"],
            fg=style_config["fg"],
            font=("Arial", 10),
            wraplength=300,
            justify=tk.LEFT
        )
        message_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Progress bar for progress toasts
        if self.toast_type == ToastType.PROGRESS:
            self.progress_var = tk.DoubleVar()
            if self.progress_value is not None:
                self.progress_var.set(self.progress_value)

            progress_frame = tk.Frame(content_frame, bg=style_config["bg"])
            progress_frame.pack(fill=tk.X, pady=(4, 0))

            progress_bar = ttk.Progressbar(
                progress_frame,
                variable=self.progress_var,
                maximum=100,
                mode='determinate' if self.progress_value is not None else 'indeterminate'
            )
            progress_bar.pack(fill=tk.X)

            if self.progress_value is None:
                progress_bar.start(10)

        # Close button
        if self.show_close:
            close_btn = tk.Label(
                main_frame,
                text="✕",
                bg=style_config["bg"],
                fg=style_config["fg"],
                font=("Arial", 12, "bold"),
                cursor="hand2"
            )
            close_btn.pack(side=tk.RIGHT, padx=(8, 0))
            close_btn.bind("<Button-1>", lambda e: self.close())

        # Position the toast
        self._position_toast()

        # Show the toast
        self.widget.deiconify()

        # Auto-close timer (not for progress toasts unless specified)
        if self.duration > 0 and self.toast_type != ToastType.PROGRESS:
            self._auto_close_timer = self.widget.after(self.duration, self.close)

    def _position_toast(self) -> None:
        """Position the toast in the bottom-right corner of the parent."""
        self.widget.update_idletasks()  # Ensure geometry is calculated

        # Get parent geometry
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        # Get toast geometry
        toast_width = self.widget.winfo_reqwidth()
        toast_height = self.widget.winfo_reqheight()

        # Position in bottom-right corner with margin
        margin = 20
        x = parent_x + parent_width - toast_width - margin
        y = parent_y + parent_height - toast_height - margin

        self.widget.geometry(f"+{x}+{y}")

    def update_progress(self, value: float) -> None:
        """Update progress bar value (0-100)."""
        if self.progress_var and self.widget:
            self.progress_var.set(max(0, min(100, value)))

    def update_message(self, message: str) -> None:
        """Update the toast message."""
        self.message = message
        if self.widget:
            # Find and update the message label
            for child in self.widget.winfo_children():
                if isinstance(child, tk.Frame):
                    for subchild in child.winfo_children():
                        if isinstance(subchild, tk.Frame):
                            for label in subchild.winfo_children():
                                if isinstance(label, tk.Label) and label.cget("text") not in self.icons.values():
                                    label.configure(text=message)
                                    return

    def close(self) -> None:
        """Close the toast notification."""
        if self._auto_close_timer:
            self.widget.after_cancel(self._auto_close_timer)
            self._auto_close_timer = None

        if self.widget:
            self.widget.destroy()
            self.widget = None

        if self._close_callback:
            self._close_callback(self)

    def set_close_callback(self, callback: callable) -> None:
        """Set callback to be called when toast is closed."""
        self._close_callback = callback


class ToastManager:
    """Manages multiple toast notifications with positioning and queuing."""

    def __init__(self, parent: tk.Widget, max_toasts: int = 5):
        self.parent = parent
        self.max_toasts = max_toasts
        self.active_toasts: Dict[str, Toast] = {}
        self._toast_counter = 0
        self._lock = threading.Lock()

    def show_toast(self, message: str, toast_type: ToastType = ToastType.INFO,
                   duration: int = 5000, show_close: bool = True,
                   toast_id: Optional[str] = None) -> str:
        """
        Show a toast notification.

        Args:
            message: The message to display
            toast_type: Type of toast (info, success, warning, error, progress)
            duration: Auto-close duration in milliseconds (0 = no auto-close)
            show_close: Whether to show close button
            toast_id: Optional ID for the toast (for updates/removal)

        Returns:
            Toast ID for future reference
        """
        with self._lock:
            if toast_id is None:
                self._toast_counter += 1
                toast_id = f"toast_{self._toast_counter}"

            # Close existing toast with same ID
            if toast_id in self.active_toasts:
                self.active_toasts[toast_id].close()

            # Remove oldest toasts if at limit
            while len(self.active_toasts) >= self.max_toasts:
                oldest_id = next(iter(self.active_toasts))
                self.active_toasts[oldest_id].close()

            # Create and show new toast
            toast = Toast(self.parent, message, toast_type, duration, show_close)
            toast.set_close_callback(self._on_toast_closed)
            self.active_toasts[toast_id] = toast

            # Schedule positioning and showing
            self.parent.after(0, lambda: self._show_and_position_toast(toast_id))

            return toast_id

    def _show_and_position_toast(self, toast_id: str) -> None:
        """Show and position a toast, considering existing toasts."""
        with self._lock:
            if toast_id not in self.active_toasts:
                return

            toast = self.active_toasts[toast_id]
            toast.show()

            # Reposition all toasts
            self._reposition_toasts()

    def _reposition_toasts(self) -> None:
        """Reposition all active toasts to avoid overlap."""
        margin = 20
        spacing = 10

        # Get parent geometry
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        current_y = parent_y + parent_height - margin

        for toast in reversed(list(self.active_toasts.values())):
            if toast.widget:
                toast.widget.update_idletasks()
                toast_width = toast.widget.winfo_reqwidth()
                toast_height = toast.widget.winfo_reqheight()

                x = parent_x + parent_width - toast_width - margin
                y = current_y - toast_height

                toast.widget.geometry(f"+{x}+{y}")
                current_y = y - spacing

    def _on_toast_closed(self, toast: Toast) -> None:
        """Handle toast closure."""
        with self._lock:
            # Remove from active toasts
            toast_id = None
            for tid, t in self.active_toasts.items():
                if t is toast:
                    toast_id = tid
                    break

            if toast_id:
                del self.active_toasts[toast_id]

            # Reposition remaining toasts
            self.parent.after(0, self._reposition_toasts)

    def update_toast(self, toast_id: str, message: Optional[str] = None,
                     progress: Optional[float] = None) -> bool:
        """
        Update an existing toast.

        Args:
            toast_id: ID of the toast to update
            message: New message (optional)
            progress: New progress value 0-100 (optional)

        Returns:
            True if toast was found and updated, False otherwise
        """
        with self._lock:
            if toast_id not in self.active_toasts:
                return False

            toast = self.active_toasts[toast_id]

            if message is not None:
                toast.update_message(message)

            if progress is not None:
                toast.update_progress(progress)

            return True

    def close_toast(self, toast_id: str) -> bool:
        """
        Close a specific toast.

        Args:
            toast_id: ID of the toast to close

        Returns:
            True if toast was found and closed, False otherwise
        """
        with self._lock:
            if toast_id not in self.active_toasts:
                return False

            self.active_toasts[toast_id].close()
            return True

    def close_all_toasts(self) -> None:
        """Close all active toasts."""
        with self._lock:
            for toast in list(self.active_toasts.values()):
                toast.close()
            self.active_toasts.clear()

    def show_info(self, message: str, duration: int = 5000) -> str:
        """Show an info toast."""
        return self.show_toast(message, ToastType.INFO, duration)

    def show_success(self, message: str, duration: int = 4000) -> str:
        """Show a success toast."""
        return self.show_toast(message, ToastType.SUCCESS, duration)

    def show_warning(self, message: str, duration: int = 6000) -> str:
        """Show a warning toast."""
        return self.show_toast(message, ToastType.WARNING, duration)

    def show_error(self, message: str, duration: int = 8000) -> str:
        """Show an error toast."""
        return self.show_toast(message, ToastType.ERROR, duration)

    def show_progress(self, message: str, progress: Optional[float] = None,
                     toast_id: Optional[str] = None) -> str:
        """Show a progress toast."""
        toast = Toast(self.parent, message, ToastType.PROGRESS, 0, True, progress)

        with self._lock:
            if toast_id is None:
                self._toast_counter += 1
                toast_id = f"progress_{self._toast_counter}"

            # Close existing toast with same ID
            if toast_id in self.active_toasts:
                self.active_toasts[toast_id].close()

            toast.set_close_callback(self._on_toast_closed)
            self.active_toasts[toast_id] = toast

            # Schedule showing
            self.parent.after(0, lambda: self._show_and_position_toast(toast_id))

            return toast_id