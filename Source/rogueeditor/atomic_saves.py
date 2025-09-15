"""
Atomic Save Operations for Save Corruption Prevention

This module provides atomic file operations that prevent save corruption through:
1. Write-to-temp-then-rename pattern for atomic writes
2. Automatic backup before modifications
3. Transaction-like behavior for multi-file operations
4. Rollback capabilities on failure

CRITICAL SAFETY: Never overwrite original files without verified backup.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Generator

from .save_validation import SaveValidator, ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Information about a created backup."""
    backup_path: str
    original_path: str
    operation: str
    timestamp: str
    size_bytes: int


@dataclass
class SaveOperation:
    """Represents a save operation with rollback information."""
    operation_id: str
    files: List[str]
    backups: List[BackupInfo]
    completed: bool = False

    def get_rollback_info(self) -> Dict[str, str]:
        """Get mapping of original_path -> backup_path for rollback."""
        return {backup.original_path: backup.backup_path for backup in self.backups}


class AtomicSaveManager:
    """
    Manager for atomic save operations with corruption prevention.

    Features:
    - Atomic write operations (temp-file-then-rename)
    - Automatic backup before any modification
    - Transaction-like multi-file operations
    - Comprehensive rollback capabilities
    - Save validation integration
    """

    def __init__(self, validator: Optional[SaveValidator] = None):
        self.validator = validator or SaveValidator()
        self.active_operations: Dict[str, SaveOperation] = {}
        self._operation_counter = 0

    def _generate_operation_id(self) -> str:
        """Generate unique operation ID."""
        self._operation_counter += 1
        timestamp = int(time.time() * 1000)
        return f"op_{timestamp}_{self._operation_counter}"

    def _create_backup_path(self, original_path: str, operation: str) -> str:
        """Create backup path with operation context."""
        original = Path(original_path)
        parent_dir = original.parent
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # Create operation-specific backup directory
        backup_dir = parent_dir / "backups" / "operations" / f"{timestamp}_{operation}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        return str(backup_dir / original.name)

    def _create_temp_path(self, target_path: str) -> str:
        """Create temporary file path for atomic writes."""
        target = Path(target_path)
        parent_dir = target.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # Use same directory as target to ensure atomic rename
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f"{target.stem}_",
            dir=parent_dir
        )
        os.close(fd)  # We'll open it properly for writing
        return temp_path

    def create_backup(self, file_path: str, operation: str) -> BackupInfo:
        """
        Create backup of file before modification.

        Args:
            file_path: Path to file to backup
            operation: Description of operation requiring backup

        Returns:
            BackupInfo with backup details

        Raises:
            RuntimeError: If backup creation fails
        """
        if not os.path.exists(file_path):
            raise RuntimeError(f"Cannot backup non-existent file: {file_path}")

        backup_path = self._create_backup_path(file_path, operation)

        try:
            # Ensure backup directory exists
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)

            # Copy with metadata preservation
            shutil.copy2(file_path, backup_path)

            # Verify backup integrity
            if not os.path.exists(backup_path):
                raise RuntimeError(f"Backup file was not created: {backup_path}")

            original_size = os.path.getsize(file_path)
            backup_size = os.path.getsize(backup_path)

            if original_size != backup_size:
                raise RuntimeError(f"Backup size mismatch: {original_size} != {backup_size}")

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            backup_info = BackupInfo(
                backup_path=backup_path,
                original_path=file_path,
                operation=operation,
                timestamp=timestamp,
                size_bytes=original_size
            )

            logger.info(f"Created backup: {file_path} -> {backup_path}")
            return backup_info

        except Exception as e:
            # Clean up partial backup
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except Exception:
                    pass
            raise RuntimeError(f"Backup creation failed: {e}") from e

    def safe_write_json(self, file_path: str, data: Any, operation: str,
                       create_backup: bool = True, validate: bool = True) -> BackupInfo:
        """
        Safely write JSON data with atomic operation and backup.

        Args:
            file_path: Target file path
            data: Data to write
            operation: Operation description for backup context
            create_backup: Whether to backup existing file
            validate: Whether to validate data before writing

        Returns:
            BackupInfo if backup was created, None otherwise

        Raises:
            RuntimeError: If validation fails or write operation fails
        """
        # Validate data if requested
        if validate and isinstance(data, dict):
            # Determine validation type based on file name
            if "trainer" in os.path.basename(file_path).lower():
                result = self.validator.validate_trainer_data(data)
            elif "slot" in os.path.basename(file_path).lower():
                result = self.validator.validate_slot_data(data)
            else:
                # Generic validation
                result = ValidationResult(True, [])

            if result.has_errors:
                error_msgs = [issue.message for issue in result.get_errors()]
                raise RuntimeError(f"Validation failed: {'; '.join(error_msgs)}")

            if result.has_warnings:
                warning_msgs = [issue.message for issue in result.get_warnings()]
                logger.warning(f"Validation warnings: {'; '.join(warning_msgs)}")

        backup_info = None

        # Create backup if file exists and requested
        if create_backup and os.path.exists(file_path):
            backup_info = self.create_backup(file_path, operation)

        # Prepare for atomic write
        temp_path = self._create_temp_path(file_path)

        try:
            # Write to temporary file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Verify temp file was written correctly
            if not os.path.exists(temp_path):
                raise RuntimeError("Temporary file was not created")

            # Verify JSON integrity by loading it back
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                # Basic structure check
                if type(loaded_data) != type(data):
                    raise RuntimeError("Data type mismatch after write")
            except Exception as e:
                raise RuntimeError(f"JSON integrity check failed: {e}")

            # Atomic rename (this is the critical atomic operation)
            if os.name == 'nt':  # Windows
                # On Windows, target must not exist for rename to work
                if os.path.exists(file_path):
                    # Create a backup name for the old file during the swap
                    old_backup = file_path + ".old"
                    if os.path.exists(old_backup):
                        os.remove(old_backup)
                    os.rename(file_path, old_backup)
                    try:
                        os.rename(temp_path, file_path)
                        # Remove the temporary old backup
                        os.remove(old_backup)
                    except Exception:
                        # Restore original if rename failed
                        os.rename(old_backup, file_path)
                        raise
                else:
                    os.rename(temp_path, file_path)
            else:  # Unix-like systems
                os.rename(temp_path, file_path)

            logger.info(f"Atomic write completed: {file_path}")
            return backup_info

        except Exception as e:
            # Clean up temporary file
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            # If we created a backup but failed to write, the original is still safe
            raise RuntimeError(f"Atomic write failed: {e}") from e

    @contextmanager
    def transaction(self, operation_name: str) -> Generator[str, None, None]:
        """
        Context manager for multi-file transaction-like operations.

        Args:
            operation_name: Name describing the transaction

        Yields:
            operation_id: Unique ID for this transaction

        Example:
            with atomic_manager.transaction("team_update") as op_id:
                atomic_manager.safe_write_json("trainer.json", trainer_data, op_id)
                atomic_manager.safe_write_json("slot1.json", slot_data, op_id)
        """
        operation_id = self._generate_operation_id()
        operation = SaveOperation(
            operation_id=operation_id,
            files=[],
            backups=[]
        )

        self.active_operations[operation_id] = operation

        try:
            logger.info(f"Starting transaction: {operation_name} (ID: {operation_id})")
            yield operation_id

            # Mark as completed
            operation.completed = True
            logger.info(f"Transaction completed: {operation_name} (ID: {operation_id})")

        except Exception as e:
            logger.error(f"Transaction failed: {operation_name} (ID: {operation_id}): {e}")

            # Attempt rollback
            try:
                self.rollback_operation(operation_id)
                logger.info(f"Rollback completed for: {operation_name} (ID: {operation_id})")
            except Exception as rollback_error:
                logger.error(f"Rollback failed for {operation_id}: {rollback_error}")

            raise RuntimeError(f"Transaction failed: {e}") from e

        finally:
            # Clean up operation tracking
            self.active_operations.pop(operation_id, None)

    def safe_write_json_in_transaction(self, file_path: str, data: Any, operation_id: str,
                                     create_backup: bool = True, validate: bool = True) -> None:
        """
        Write JSON as part of a transaction.

        Args:
            file_path: Target file path
            data: Data to write
            operation_id: Transaction operation ID
            create_backup: Whether to backup existing file
            validate: Whether to validate data
        """
        if operation_id not in self.active_operations:
            raise RuntimeError(f"Invalid operation ID: {operation_id}")

        operation = self.active_operations[operation_id]
        operation.files.append(file_path)

        backup_info = self.safe_write_json(
            file_path=file_path,
            data=data,
            operation=operation_id,
            create_backup=create_backup,
            validate=validate
        )

        if backup_info:
            operation.backups.append(backup_info)

    def rollback_operation(self, operation_id: str) -> None:
        """
        Rollback an operation using its backups.

        Args:
            operation_id: Operation ID to rollback

        Raises:
            RuntimeError: If rollback fails
        """
        if operation_id not in self.active_operations:
            raise RuntimeError(f"Unknown operation ID: {operation_id}")

        operation = self.active_operations[operation_id]

        if not operation.backups:
            logger.warning(f"No backups to rollback for operation: {operation_id}")
            return

        errors = []

        # Restore files from backups in reverse order
        for backup_info in reversed(operation.backups):
            try:
                if not os.path.exists(backup_info.backup_path):
                    errors.append(f"Backup not found: {backup_info.backup_path}")
                    continue

                # Restore using atomic operation
                temp_path = self._create_temp_path(backup_info.original_path)

                try:
                    shutil.copy2(backup_info.backup_path, temp_path)

                    # Atomic rename
                    if os.name == 'nt':  # Windows
                        if os.path.exists(backup_info.original_path):
                            old_backup = backup_info.original_path + ".rollback_old"
                            if os.path.exists(old_backup):
                                os.remove(old_backup)
                            os.rename(backup_info.original_path, old_backup)
                            try:
                                os.rename(temp_path, backup_info.original_path)
                                os.remove(old_backup)
                            except Exception:
                                os.rename(old_backup, backup_info.original_path)
                                raise
                        else:
                            os.rename(temp_path, backup_info.original_path)
                    else:  # Unix-like
                        os.rename(temp_path, backup_info.original_path)

                    logger.info(f"Restored: {backup_info.original_path}")

                except Exception as e:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    errors.append(f"Failed to restore {backup_info.original_path}: {e}")

            except Exception as e:
                errors.append(f"Rollback error for {backup_info.original_path}: {e}")

        if errors:
            raise RuntimeError(f"Rollback partially failed: {'; '.join(errors)}")

    def cleanup_old_backups(self, base_dir: str, keep_days: int = 30) -> None:
        """
        Clean up old backup files.

        Args:
            base_dir: Base directory containing backups
            keep_days: Number of days to keep backups
        """
        if keep_days <= 0:
            return

        cutoff_time = time.time() - (keep_days * 24 * 60 * 60)

        backup_root = os.path.join(base_dir, "backups", "operations")
        if not os.path.exists(backup_root):
            return

        removed_count = 0

        try:
            for item in os.listdir(backup_root):
                item_path = os.path.join(backup_root, item)
                if os.path.isdir(item_path):
                    try:
                        mtime = os.path.getmtime(item_path)
                        if mtime < cutoff_time:
                            shutil.rmtree(item_path)
                            removed_count += 1
                            logger.debug(f"Removed old backup: {item_path}")
                    except Exception as e:
                        logger.warning(f"Could not remove backup {item_path}: {e}")

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} old backup directories")

        except Exception as e:
            logger.warning(f"Backup cleanup failed: {e}")

    def verify_backup_integrity(self, backup_info: BackupInfo) -> bool:
        """
        Verify integrity of a backup file.

        Args:
            backup_info: Backup information to verify

        Returns:
            True if backup is intact and valid
        """
        try:
            if not os.path.exists(backup_info.backup_path):
                return False

            # Check file size
            actual_size = os.path.getsize(backup_info.backup_path)
            if actual_size != backup_info.size_bytes:
                return False

            # Verify JSON structure
            with open(backup_info.backup_path, 'r', encoding='utf-8') as f:
                json.load(f)

            return True

        except Exception:
            return False


def create_atomic_save_manager(validator: Optional[SaveValidator] = None) -> AtomicSaveManager:
    """Create configured atomic save manager."""
    return AtomicSaveManager(validator)