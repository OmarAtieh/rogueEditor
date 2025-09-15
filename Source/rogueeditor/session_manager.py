"""
Session management for Pokerogue API operations.

Provides automatic session health monitoring, refresh capabilities, and observer pattern
for UI updates. Designed to improve upload success rates by preventing session
expiration failures.
"""

from __future__ import annotations

import time
import threading
import logging
from typing import Optional, Callable, Dict, Any, List
from enum import Enum


logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session health states."""
    HEALTHY = "healthy"
    EXPIRED = "expired"
    REFRESHING = "refreshing"
    ERROR = "error"
    UNKNOWN = "unknown"


class SessionObserver:
    """Interface for session state observers."""

    def on_session_state_changed(self, state: SessionState, message: str = "") -> None:
        """Called when session state changes."""
        pass

    def on_session_refresh_started(self) -> None:
        """Called when session refresh begins."""
        pass

    def on_session_refresh_completed(self, success: bool, message: str = "") -> None:
        """Called when session refresh completes."""
        pass


class SessionManager:
    """
    Manages Pokerogue API session health and automatic refresh.

    Features:
    - Automatic session health monitoring
    - Proactive session refresh before expiration
    - Observer pattern for UI updates
    - Thread-safe operation
    - Configurable timing parameters
    """

    def __init__(self, api_instance=None, check_interval: int = 300,
                 refresh_threshold: int = 600, max_retries: int = 3):
        """
        Initialize session manager.

        Args:
            api_instance: PokerogueAPI instance to manage
            check_interval: Seconds between health checks (default: 5 minutes)
            refresh_threshold: Refresh session when it will expire in this many seconds (default: 10 minutes)
            max_retries: Maximum refresh attempts before marking as error
        """
        self._api = api_instance
        self._check_interval = check_interval
        self._refresh_threshold = refresh_threshold
        self._max_retries = max_retries

        self._state = SessionState.UNKNOWN
        self._last_activity = 0.0
        self._last_refresh = 0.0
        self._observers: List[SessionObserver] = []

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        self._lock = threading.RLock()

        self._refresh_in_progress = False
        self._consecutive_failures = 0

    def set_api_instance(self, api_instance) -> None:
        """Set the API instance to manage."""
        with self._lock:
            self._api = api_instance
            self._mark_activity()

    def add_observer(self, observer: SessionObserver) -> None:
        """Add a session state observer."""
        with self._lock:
            self._observers.append(observer)

    def remove_observer(self, observer: SessionObserver) -> None:
        """Remove a session state observer."""
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)

    def start_monitoring(self) -> None:
        """Start automatic session health monitoring."""
        with self._lock:
            if self._monitor_thread is not None and self._monitor_thread.is_alive():
                return  # Already monitoring

            self._stop_monitoring.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            logger.info("Session monitoring started")

    def stop_monitoring(self) -> None:
        """Stop automatic session health monitoring."""
        self._stop_monitoring.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("Session monitoring stopped")

    def check_session_health(self) -> SessionState:
        """
        Check current session health.

        Returns:
            Current session state
        """
        with self._lock:
            if not self._api or not self._api.token:
                self._set_state(SessionState.UNKNOWN)
                return self._state

            try:
                # Try a lightweight operation to test session validity
                if self._api.client_session_id:
                    # Test with system verify if available
                    self._api.system_verify()
                else:
                    # Fallback to account info
                    self._api.get_account_info()

                self._mark_activity()
                self._set_state(SessionState.HEALTHY)
                self._consecutive_failures = 0

            except Exception as e:
                error_msg = str(e).lower()
                if "401" in error_msg or "unauthorized" in error_msg:
                    self._set_state(SessionState.EXPIRED)
                else:
                    self._set_state(SessionState.ERROR, str(e))

                logger.warning(f"Session health check failed: {e}")

            return self._state

    def ensure_valid_session(self) -> bool:
        """
        Ensure session is valid, refreshing if necessary.

        Returns:
            True if session is valid, False otherwise
        """
        with self._lock:
            if self._refresh_in_progress:
                # Wait for ongoing refresh to complete
                return self._wait_for_refresh()

            current_state = self.check_session_health()

            if current_state == SessionState.HEALTHY:
                # Check if we're approaching expiration
                time_since_activity = time.time() - self._last_activity
                if time_since_activity > self._refresh_threshold:
                    logger.info("Session approaching expiration, refreshing proactively")
                    return self._refresh_session()
                return True

            elif current_state == SessionState.EXPIRED:
                logger.info("Session expired, attempting refresh")
                return self._refresh_session()

            elif current_state == SessionState.ERROR:
                logger.error("Session in error state")
                return False

            else:  # UNKNOWN
                logger.warning("Session state unknown, attempting refresh")
                return self._refresh_session()

    def force_refresh(self) -> bool:
        """
        Force an immediate session refresh.

        Returns:
            True if refresh successful, False otherwise
        """
        with self._lock:
            return self._refresh_session()

    def get_state(self) -> SessionState:
        """Get current session state."""
        return self._state

    def get_last_activity(self) -> float:
        """Get timestamp of last successful activity."""
        return self._last_activity

    def get_time_since_activity(self) -> float:
        """Get seconds since last activity."""
        return time.time() - self._last_activity

    def _mark_activity(self) -> None:
        """Mark successful activity timestamp."""
        self._last_activity = time.time()

    def _set_state(self, state: SessionState, message: str = "") -> None:
        """Set session state and notify observers."""
        if self._state != state:
            old_state = self._state
            self._state = state
            logger.info(f"Session state changed: {old_state.value} -> {state.value}")

            # Notify observers
            for observer in self._observers:
                try:
                    observer.on_session_state_changed(state, message)
                except Exception as e:
                    logger.error(f"Observer notification failed: {e}")

    def _refresh_session(self) -> bool:
        """
        Internal session refresh implementation.

        Returns:
            True if refresh successful, False otherwise
        """
        if not self._api:
            return False

        if self._refresh_in_progress:
            return self._wait_for_refresh()

        self._refresh_in_progress = True
        self._set_state(SessionState.REFRESHING)

        # Notify observers
        for observer in self._observers:
            try:
                observer.on_session_refresh_started()
            except Exception as e:
                logger.error(f"Observer notification failed: {e}")

        success = False
        error_message = ""

        try:
            logger.info("Attempting session refresh")

            # Re-authenticate to get fresh token
            self._api.login()
            self._mark_activity()
            self._last_refresh = time.time()
            self._consecutive_failures = 0

            # Verify the new session works
            if self._api.client_session_id:
                self._api.system_verify()
            else:
                self._api.get_account_info()

            self._set_state(SessionState.HEALTHY)
            success = True
            logger.info("Session refresh successful")

        except Exception as e:
            self._consecutive_failures += 1
            error_message = str(e)

            if self._consecutive_failures >= self._max_retries:
                self._set_state(SessionState.ERROR, f"Max retries exceeded: {error_message}")
                logger.error(f"Session refresh failed after {self._max_retries} attempts: {e}")
            else:
                self._set_state(SessionState.EXPIRED, error_message)
                logger.warning(f"Session refresh failed (attempt {self._consecutive_failures}): {e}")

        finally:
            self._refresh_in_progress = False

            # Notify observers
            for observer in self._observers:
                try:
                    observer.on_session_refresh_completed(success, error_message)
                except Exception as e:
                    logger.error(f"Observer notification failed: {e}")

        return success

    def _wait_for_refresh(self, timeout: float = 30.0) -> bool:
        """Wait for ongoing refresh to complete."""
        start_time = time.time()
        while self._refresh_in_progress and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        return self._state == SessionState.HEALTHY

    def _monitor_loop(self) -> None:
        """Main monitoring loop (runs in background thread)."""
        logger.info("Session monitoring loop started")

        while not self._stop_monitoring.is_set():
            try:
                # Wait for check interval or stop signal
                if self._stop_monitoring.wait(self._check_interval):
                    break  # Stop signal received

                # Skip if no API instance
                if not self._api:
                    continue

                # Perform health check
                current_state = self.check_session_health()

                # Proactive refresh if approaching expiration
                if current_state == SessionState.HEALTHY:
                    time_since_activity = time.time() - self._last_activity
                    if time_since_activity > self._refresh_threshold:
                        logger.info("Proactive session refresh triggered by monitor")
                        self._refresh_session()

                elif current_state == SessionState.EXPIRED:
                    logger.info("Expired session detected by monitor, refreshing")
                    self._refresh_session()

            except Exception as e:
                logger.error(f"Error in session monitoring loop: {e}")

        logger.info("Session monitoring loop stopped")


# Convenience functions for global session management
_global_session_manager: Optional[SessionManager] = None


def get_global_session_manager() -> Optional[SessionManager]:
    """Get the global session manager instance."""
    return _global_session_manager


def set_global_session_manager(session_manager: SessionManager) -> None:
    """Set the global session manager instance."""
    global _global_session_manager
    _global_session_manager = session_manager


def ensure_session_valid() -> bool:
    """
    Convenience function to ensure global session is valid.

    Returns:
        True if session is valid, False otherwise
    """
    if _global_session_manager:
        return _global_session_manager.ensure_valid_session()
    return False