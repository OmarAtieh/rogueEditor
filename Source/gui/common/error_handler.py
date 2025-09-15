"""Enhanced error handling framework with actionable error messages and user guidance."""

from __future__ import annotations

import logging
import traceback
from typing import Optional, Dict, Any, Callable, Union, List
from enum import Enum
import tkinter as tk
from tkinter import messagebox

from .toast import ToastManager, ToastType


class ErrorCategory(Enum):
    """Categories of errors for better user guidance."""
    NETWORK = "network"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    FILE_SYSTEM = "file_system"
    DATA_CORRUPTION = "data_corruption"
    PERMISSION = "permission"
    SESSION = "session"
    API = "api"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"          # Info/warning level
    MEDIUM = "medium"    # Error but recoverable
    HIGH = "high"        # Critical error
    FATAL = "fatal"      # Application-breaking


class UserAction(Enum):
    """Suggested user actions for error recovery."""
    RETRY = "retry"
    LOGIN_AGAIN = "login_again"
    CHECK_CONNECTION = "check_connection"
    REFRESH_SESSION = "refresh_session"
    CHECK_FILE_PERMISSIONS = "check_file_permissions"
    VALIDATE_INPUT = "validate_input"
    CONTACT_SUPPORT = "contact_support"
    RESTART_APP = "restart_app"
    NONE = "none"


class ErrorContext:
    """Context information for an error."""

    def __init__(self, operation: str, user_action: str = "", additional_info: Optional[Dict[str, Any]] = None):
        self.operation = operation  # What the user was trying to do
        self.user_action = user_action  # What action triggered the error
        self.additional_info = additional_info or {}
        self.timestamp = None  # Will be set by error handler


class ErrorInfo:
    """Structured error information with user guidance."""

    def __init__(
        self,
        category: ErrorCategory,
        severity: ErrorSeverity,
        title: str,
        message: str,
        technical_details: str = "",
        suggested_actions: List[UserAction] = None,
        retry_callback: Optional[Callable] = None,
        context: Optional[ErrorContext] = None
    ):
        self.category = category
        self.severity = severity
        self.title = title
        self.message = message
        self.technical_details = technical_details
        self.suggested_actions = suggested_actions or []
        self.retry_callback = retry_callback
        self.context = context or ErrorContext("Unknown operation")


class EnhancedErrorHandler:
    """Enhanced error handling with actionable user guidance."""

    def __init__(self, parent: tk.Widget, toast_manager: Optional[ToastManager] = None):
        self.parent = parent
        self.toast_manager = toast_manager or ToastManager(parent)
        self.logger = logging.getLogger(__name__)

        # Error pattern matchers
        self.error_patterns = self._build_error_patterns()

        # Action descriptions
        self.action_descriptions = {
            UserAction.RETRY: "Try the operation again",
            UserAction.LOGIN_AGAIN: "Re-enter your username and password to login again",
            UserAction.CHECK_CONNECTION: "Check your internet connection and try again",
            UserAction.REFRESH_SESSION: "Use the 'Refresh Session' button to renew your session",
            UserAction.CHECK_FILE_PERMISSIONS: "Check file permissions and ensure the file is not in use",
            UserAction.VALIDATE_INPUT: "Check your input values and try again",
            UserAction.CONTACT_SUPPORT: "Contact support if this problem persists",
            UserAction.RESTART_APP: "Restart the application",
            UserAction.NONE: ""
        }

    def _build_error_patterns(self) -> Dict[str, ErrorInfo]:
        """Build patterns for common errors."""
        return {
            # Network errors
            "connection": ErrorInfo(
                ErrorCategory.NETWORK,
                ErrorSeverity.MEDIUM,
                "Connection Error",
                "Could not connect to the server. Please check your internet connection.",
                suggested_actions=[UserAction.CHECK_CONNECTION, UserAction.RETRY]
            ),
            "timeout": ErrorInfo(
                ErrorCategory.NETWORK,
                ErrorSeverity.MEDIUM,
                "Request Timeout",
                "The server took too long to respond. This might be due to network issues or high server load.",
                suggested_actions=[UserAction.CHECK_CONNECTION, UserAction.RETRY]
            ),

            # Authentication errors
            "401": ErrorInfo(
                ErrorCategory.AUTHENTICATION,
                ErrorSeverity.HIGH,
                "Authentication Failed",
                "Your session has expired or your credentials are invalid.",
                suggested_actions=[UserAction.LOGIN_AGAIN, UserAction.REFRESH_SESSION]
            ),
            "unauthorized": ErrorInfo(
                ErrorCategory.AUTHENTICATION,
                ErrorSeverity.HIGH,
                "Unauthorized Access",
                "You don't have permission to perform this action.",
                suggested_actions=[UserAction.LOGIN_AGAIN, UserAction.REFRESH_SESSION]
            ),
            "illegal base64": ErrorInfo(
                ErrorCategory.SESSION,
                ErrorSeverity.HIGH,
                "Session Corrupted",
                "Your session token is corrupted. This usually happens when the session expires.",
                suggested_actions=[UserAction.REFRESH_SESSION, UserAction.LOGIN_AGAIN]
            ),

            # File system errors
            "permission denied": ErrorInfo(
                ErrorCategory.FILE_SYSTEM,
                ErrorSeverity.MEDIUM,
                "File Permission Error",
                "Unable to access the file. Check that the file isn't open in another program.",
                suggested_actions=[UserAction.CHECK_FILE_PERMISSIONS, UserAction.RETRY]
            ),
            "file not found": ErrorInfo(
                ErrorCategory.FILE_SYSTEM,
                ErrorSeverity.MEDIUM,
                "File Not Found",
                "The required file could not be found. Make sure you've dumped your data first.",
                suggested_actions=[UserAction.VALIDATE_INPUT]
            ),

            # Data validation errors
            "json": ErrorInfo(
                ErrorCategory.VALIDATION,
                ErrorSeverity.MEDIUM,
                "Invalid Data Format",
                "The data file is corrupted or in an invalid format.",
                suggested_actions=[UserAction.VALIDATE_INPUT, UserAction.RETRY]
            ),
            "invalid slot": ErrorInfo(
                ErrorCategory.VALIDATION,
                ErrorSeverity.LOW,
                "Invalid Slot",
                "Please select a valid slot number (1-5).",
                suggested_actions=[UserAction.VALIDATE_INPUT]
            ),

            # API errors
            "403": ErrorInfo(
                ErrorCategory.API,
                ErrorSeverity.HIGH,
                "Access Forbidden",
                "The server denied access to this resource.",
                suggested_actions=[UserAction.LOGIN_AGAIN, UserAction.CONTACT_SUPPORT]
            ),
            "500": ErrorInfo(
                ErrorCategory.API,
                ErrorSeverity.HIGH,
                "Server Error",
                "The server encountered an internal error. Please try again later.",
                suggested_actions=[UserAction.RETRY, UserAction.CONTACT_SUPPORT]
            )
        }

    def handle_exception(
        self,
        exception: Exception,
        context: Optional[ErrorContext] = None,
        show_dialog: bool = True,
        use_toast: bool = False
    ) -> ErrorInfo:
        """
        Handle an exception with enhanced error reporting.

        Args:
            exception: The exception to handle
            context: Context information about the operation
            show_dialog: Whether to show error dialog
            use_toast: Whether to show toast notification instead of dialog

        Returns:
            ErrorInfo object with structured error details
        """
        error_info = self._analyze_exception(exception, context)

        # Log the error
        self._log_error(error_info, exception)

        # Show user feedback
        if use_toast:
            self._show_toast_error(error_info)
        elif show_dialog:
            self._show_error_dialog(error_info)

        return error_info

    def _analyze_exception(self, exception: Exception, context: Optional[ErrorContext] = None) -> ErrorInfo:
        """Analyze an exception and return structured error information."""
        error_str = str(exception).lower()
        exc_type = type(exception).__name__

        # Check for known patterns
        for pattern, error_info in self.error_patterns.items():
            if pattern in error_str:
                # Clone the error info and customize
                customized = ErrorInfo(
                    error_info.category,
                    error_info.severity,
                    error_info.title,
                    error_info.message,
                    f"{exc_type}: {str(exception)}",
                    error_info.suggested_actions.copy(),
                    context=context
                )
                return customized

        # Handle specific exception types
        if isinstance(exception, ConnectionError):
            return ErrorInfo(
                ErrorCategory.NETWORK,
                ErrorSeverity.MEDIUM,
                "Connection Error",
                "Unable to connect to the server. Please check your internet connection.",
                f"{exc_type}: {str(exception)}",
                [UserAction.CHECK_CONNECTION, UserAction.RETRY],
                context=context
            )

        if isinstance(exception, FileNotFoundError):
            return ErrorInfo(
                ErrorCategory.FILE_SYSTEM,
                ErrorSeverity.MEDIUM,
                "File Not Found",
                "The required file could not be found.",
                f"{exc_type}: {str(exception)}",
                [UserAction.VALIDATE_INPUT],
                context=context
            )

        if isinstance(exception, PermissionError):
            return ErrorInfo(
                ErrorCategory.FILE_SYSTEM,
                ErrorSeverity.MEDIUM,
                "Permission Denied",
                "Unable to access the file. Check permissions and ensure it's not open elsewhere.",
                f"{exc_type}: {str(exception)}",
                [UserAction.CHECK_FILE_PERMISSIONS, UserAction.RETRY],
                context=context
            )

        if isinstance(exception, ValueError):
            return ErrorInfo(
                ErrorCategory.VALIDATION,
                ErrorSeverity.LOW,
                "Invalid Value",
                "Please check your input values and try again.",
                f"{exc_type}: {str(exception)}",
                [UserAction.VALIDATE_INPUT],
                context=context
            )

        # Default error handling
        return ErrorInfo(
            ErrorCategory.UNKNOWN,
            ErrorSeverity.MEDIUM,
            "Unexpected Error",
            "An unexpected error occurred. Please try again or contact support if the problem persists.",
            f"{exc_type}: {str(exception)}",
            [UserAction.RETRY, UserAction.CONTACT_SUPPORT],
            context=context
        )

    def _log_error(self, error_info: ErrorInfo, exception: Exception) -> None:
        """Log error details."""
        context_str = ""
        if error_info.context:
            context_str = f" during '{error_info.context.operation}'"

        self.logger.error(
            f"{error_info.category.value.upper()} ERROR{context_str}: {error_info.title} - {error_info.message}"
        )
        self.logger.error(f"Technical details: {error_info.technical_details}")
        self.logger.debug(f"Full traceback:\n{traceback.format_exc()}")

    def _show_error_dialog(self, error_info: ErrorInfo) -> None:
        """Show enhanced error dialog with actionable guidance."""
        # Build the message
        message_parts = [error_info.message]

        if error_info.suggested_actions:
            message_parts.append("\nSuggested actions:")
            for i, action in enumerate(error_info.suggested_actions, 1):
                action_desc = self.action_descriptions.get(action, action.value)
                if action_desc:
                    message_parts.append(f"{i}. {action_desc}")

        if error_info.context and error_info.context.operation:
            message_parts.append(f"\nOperation: {error_info.context.operation}")

        full_message = "\n".join(message_parts)

        # Show appropriate dialog based on severity
        if error_info.severity == ErrorSeverity.FATAL:
            messagebox.showerror(error_info.title, full_message)
        elif error_info.severity == ErrorSeverity.HIGH:
            messagebox.showerror(error_info.title, full_message)
        elif error_info.severity == ErrorSeverity.MEDIUM:
            messagebox.showwarning(error_info.title, full_message)
        else:
            messagebox.showinfo(error_info.title, full_message)

    def _show_toast_error(self, error_info: ErrorInfo) -> None:
        """Show error as toast notification."""
        toast_type = ToastType.ERROR
        duration = 8000

        if error_info.severity == ErrorSeverity.LOW:
            toast_type = ToastType.WARNING
            duration = 6000
        elif error_info.severity == ErrorSeverity.MEDIUM:
            toast_type = ToastType.ERROR
            duration = 8000
        else:
            toast_type = ToastType.ERROR
            duration = 10000

        # Build short message for toast
        message = error_info.message
        if error_info.suggested_actions and len(error_info.suggested_actions) > 0:
            first_action = self.action_descriptions.get(error_info.suggested_actions[0], "")
            if first_action:
                message += f"\n💡 {first_action}"

        self.toast_manager.show_toast(message, toast_type, duration)

    def show_success(self, message: str, context: Optional[ErrorContext] = None, use_toast: bool = True) -> None:
        """Show success message."""
        if use_toast:
            self.toast_manager.show_success(message)
        else:
            messagebox.showinfo("Success", message)

        # Log success
        context_str = f" for '{context.operation}'" if context else ""
        self.logger.info(f"SUCCESS{context_str}: {message}")

    def show_warning(self, message: str, context: Optional[ErrorContext] = None, use_toast: bool = False) -> None:
        """Show warning message."""
        if use_toast:
            self.toast_manager.show_warning(message)
        else:
            messagebox.showwarning("Warning", message)

        # Log warning
        context_str = f" for '{context.operation}'" if context else ""
        self.logger.warning(f"WARNING{context_str}: {message}")

    def show_info(self, message: str, context: Optional[ErrorContext] = None, use_toast: bool = True) -> None:
        """Show info message."""
        if use_toast:
            self.toast_manager.show_info(message)
        else:
            messagebox.showinfo("Information", message)

        # Log info
        context_str = f" for '{context.operation}'" if context else ""
        self.logger.info(f"INFO{context_str}: {message}")

    def confirm_action(self, title: str, message: str, context: Optional[ErrorContext] = None) -> bool:
        """Show confirmation dialog."""
        result = messagebox.askyesno(title, message)

        # Log confirmation request
        context_str = f" for '{context.operation}'" if context else ""
        action = "confirmed" if result else "cancelled"
        self.logger.info(f"USER {action.upper()}{context_str}: {title}")

        return result


def safe_operation(error_handler: EnhancedErrorHandler, operation_name: str, use_toast: bool = False):
    """Decorator for safe operation execution with enhanced error handling."""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                context = ErrorContext(operation_name, f"calling {func.__name__}")
                error_handler.handle_exception(e, context, show_dialog=not use_toast, use_toast=use_toast)
                return None
        return wrapper
    return decorator