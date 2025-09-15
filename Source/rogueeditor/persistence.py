"""Unified persistence system for user and application data."""
from __future__ import annotations

import os
import json
from typing import Any, Optional, Dict
from pathlib import Path


class PersistenceManager:
    """Manages persistent data for users and application settings."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
    
    def _get_user_settings_path(self, username: str) -> str:
        """Get the path to user settings file."""
        from rogueeditor.utils import user_save_dir
        settings_dir = user_save_dir(username)
        os.makedirs(settings_dir, exist_ok=True)
        return os.path.join(settings_dir, "settings.json")
    
    def _get_app_settings_path(self) -> str:
        """Get the path to application settings file."""
        # Use a global settings directory
        app_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings")
        os.makedirs(app_dir, exist_ok=True)
        return os.path.join(app_dir, "app_settings.json")
    
    def _load_user_settings(self, username: str) -> Dict[str, Any]:
        """Load user settings from file."""
        cache_key = f"user:{username}"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        settings_path = self._get_user_settings_path(username)
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    self._cache[cache_key] = settings
                    return settings
            except Exception:
                pass
        
        # Return empty dict if file doesn't exist or can't be read
        settings = {}
        self._cache[cache_key] = settings
        return settings
    
    def _load_app_settings(self) -> Dict[str, Any]:
        """Load application settings from file."""
        cache_key = "app"
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        settings_path = self._get_app_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    self._cache[cache_key] = settings
                    return settings
            except Exception:
                pass
        
        # Return empty dict if file doesn't exist or can't be read
        settings = {}
        self._cache[cache_key] = settings
        return settings
    
    def _save_user_settings(self, username: str, settings: Dict[str, Any]) -> None:
        """Save user settings to file."""
        settings_path = self._get_user_settings_path(username)
        try:
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
            # Update cache
            self._cache[f"user:{username}"] = settings
        except Exception:
            pass
    
    def _save_app_settings(self, settings: Dict[str, Any]) -> None:
        """Save application settings to file."""
        settings_path = self._get_app_settings_path()
        try:
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=2)
            # Update cache
            self._cache["app"] = settings
        except Exception:
            pass
    
    def get_user_value(self, username: str, key: str, default: Any = None) -> Any:
        """Get a value from user settings."""
        settings = self._load_user_settings(username)
        return settings.get(key, default)
    
    def set_user_value(self, username: str, key: str, value: Any) -> None:
        """Set a value in user settings."""
        settings = self._load_user_settings(username)
        settings[key] = value
        self._save_user_settings(username, settings)
    
    def get_app_value(self, key: str, default: Any = None) -> Any:
        """Get a value from application settings."""
        settings = self._load_app_settings()
        return settings.get(key, default)
    
    def set_app_value(self, key: str, value: Any) -> None:
        """Set a value in application settings."""
        settings = self._load_app_settings()
        settings[key] = value
        self._save_app_settings(settings)
    
    def get_last_selected_slot(self, username: str) -> str:
        """Get the last selected slot for a user."""
        return self.get_user_value(username, "last_selected_slot", "1")
    
    def set_last_selected_slot(self, username: str, slot: str) -> None:
        """Set the last selected slot for a user."""
        self.set_user_value(username, "last_selected_slot", slot)
    
    def get_last_backup(self, username: str) -> Optional[str]:
        """Get the last backup timestamp for a user."""
        return self.get_user_value(username, "last_backup")
    
    def set_last_backup(self, username: str, backup_timestamp: str) -> None:
        """Set the last backup timestamp for a user."""
        self.set_user_value(username, "last_backup", backup_timestamp)
    
    def get_log_level(self, username: str) -> str:
        """Get the preferred log level for a user."""
        return self.get_user_value(username, "log_level", "INFO")
    
    def set_log_level(self, username: str, log_level: str) -> None:
        """Set the preferred log level for a user."""
        self.set_user_value(username, "log_level", log_level)
    
    def get_last_session_update(self, username: str) -> Optional[str]:
        """Get the last session update timestamp for a user."""
        return self.get_user_value(username, "last_session_update")
    
    def set_last_session_update(self, username: str, timestamp: str) -> None:
        """Set the last session update timestamp for a user."""
        self.set_user_value(username, "last_session_update", timestamp)


# Global persistence manager instance
persistence_manager = PersistenceManager()