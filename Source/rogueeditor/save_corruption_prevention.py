"""
Save Corruption Prevention System - Main Integration Module

This module provides the main interface for the save corruption prevention system,
integrating validation, atomic saves, and enhanced backups into a cohesive framework.

CRITICAL SAFETY: This system is the primary defense against save file corruption.
All save operations should go through this system.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Generator, Callable

from .save_validation import SaveValidator, ValidationResult, ValidationSeverity, ValidationIssue
from .atomic_saves import AtomicSaveManager, SaveOperation
from .enhanced_backup import EnhancedBackupManager, BackupMetadata
from .utils import trainer_save_path, slot_save_path

logger = logging.getLogger(__name__)


@dataclass
class SaveOperationResult:
    """Result of a save operation with all relevant information."""
    success: bool
    operation_id: Optional[str]
    backup_id: Optional[str]
    validation_result: Optional[ValidationResult]
    files_saved: List[str]
    error_message: Optional[str] = None
    rollback_performed: bool = False


class SaveCorruptionPreventionSystem:
    """
    Main interface for the save corruption prevention system.

    Combines validation, atomic operations, and enhanced backups to provide
    bulletproof save file protection with comprehensive recovery options.

    Features:
    - Mandatory validation before all saves
    - Automatic backup before modifications
    - Atomic write operations
    - Transaction support for multi-file operations
    - Comprehensive rollback capabilities
    - User-friendly error reporting
    """

    def __init__(self, username: str):
        self.username = username
        self.validator = SaveValidator()
        self.atomic_manager = AtomicSaveManager(self.validator)
        self.backup_manager = EnhancedBackupManager(username)

        # Configuration
        self.auto_backup = True
        self.validate_before_save = True
        self.cleanup_temp_files = True

        logger.info(f"Save corruption prevention system initialized for user: {username}")

    def safe_save_trainer(self, trainer_data: Dict[str, Any],
                         operation_description: str = "trainer_update") -> SaveOperationResult:
        """
        Safely save trainer data with full corruption prevention.

        Args:
            trainer_data: Trainer data to save
            operation_description: Human-readable operation description

        Returns:
            SaveOperationResult with operation details
        """
        return self._safe_save_single_file(
            file_path=trainer_save_path(self.username),
            data=trainer_data,
            operation_type="trainer_save",
            operation_description=operation_description,
            validation_type="trainer"
        )

    def safe_save_slot(self, slot: int, slot_data: Dict[str, Any],
                      operation_description: str = "slot_update") -> SaveOperationResult:
        """
        Safely save slot data with full corruption prevention.

        Args:
            slot: Slot number (1-5)
            slot_data: Slot data to save
            operation_description: Human-readable operation description

        Returns:
            SaveOperationResult with operation details
        """
        return self._safe_save_single_file(
            file_path=slot_save_path(self.username, slot),
            data=slot_data,
            operation_type="slot_save",
            operation_description=f"{operation_description}_slot_{slot}",
            validation_type="slot"
        )

    @contextmanager
    def safe_transaction(self, operation_type: str,
                        operation_description: str) -> Generator[str, None, None]:
        """
        Context manager for safe multi-file transactions.

        Args:
            operation_type: Type of operation (e.g., "team_edit", "bulk_update")
            operation_description: Human-readable description

        Yields:
            transaction_id: Unique transaction identifier

        Example:
            with system.safe_transaction("team_edit", "Update team roster") as tx_id:
                system.safe_save_trainer_in_transaction(trainer_data, tx_id)
                system.safe_save_slot_in_transaction(1, slot_data, tx_id)
        """
        # Create backup before starting transaction
        backup_id = None
        if self.auto_backup:
            files_to_backup = []

            # Add existing files that might be modified
            trainer_path = trainer_save_path(self.username)
            if os.path.exists(trainer_path):
                files_to_backup.append(trainer_path)

            for slot in range(1, 6):
                slot_path = slot_save_path(self.username, slot)
                if os.path.exists(slot_path):
                    files_to_backup.append(slot_path)

            if files_to_backup:
                try:
                    backup_id = self.backup_manager.create_operation_backup(
                        operation_type=operation_type,
                        description=operation_description,
                        files_to_backup=files_to_backup,
                        session_info={"transaction_mode": True}
                    )
                    logger.info(f"Created transaction backup: {backup_id}")
                except Exception as e:
                    logger.warning(f"Could not create transaction backup: {e}")

        # Start atomic transaction
        with self.atomic_manager.transaction(operation_description) as operation_id:
            yield operation_id

        # Transaction completed successfully
        logger.info(f"Transaction completed: {operation_type} (backup: {backup_id})")

    def safe_save_trainer_in_transaction(self, trainer_data: Dict[str, Any],
                                       transaction_id: str) -> None:
        """Save trainer data as part of a transaction."""
        # Validate if enabled
        if self.validate_before_save:
            result = self.validator.validate_trainer_data(trainer_data)
            if result.has_errors:
                errors = [issue.message for issue in result.get_errors()]
                raise RuntimeError(f"Trainer validation failed: {'; '.join(errors)}")

        # Save using atomic manager
        file_path = trainer_save_path(self.username)
        self.atomic_manager.safe_write_json_in_transaction(
            file_path=file_path,
            data=trainer_data,
            operation_id=transaction_id,
            create_backup=False,  # Backup already created for transaction
            validate=False  # Already validated above
        )

    def safe_save_slot_in_transaction(self, slot: int, slot_data: Dict[str, Any],
                                    transaction_id: str) -> None:
        """Save slot data as part of a transaction."""
        # Validate if enabled
        if self.validate_before_save:
            result = self.validator.validate_slot_data(slot_data)
            if result.has_errors:
                errors = [issue.message for issue in result.get_errors()]
                raise RuntimeError(f"Slot {slot} validation failed: {'; '.join(errors)}")

        # Save using atomic manager
        file_path = slot_save_path(self.username, slot)
        self.atomic_manager.safe_write_json_in_transaction(
            file_path=file_path,
            data=slot_data,
            operation_id=transaction_id,
            create_backup=False,  # Backup already created for transaction
            validate=False  # Already validated above
        )

    def validate_data(self, data: Dict[str, Any],
                     data_type: str) -> ValidationResult:
        """
        Validate data without saving.

        Args:
            data: Data to validate
            data_type: Type of data ("trainer" or "slot")

        Returns:
            ValidationResult with any issues found
        """
        if data_type == "trainer":
            return self.validator.validate_trainer_data(data)
        elif data_type == "slot":
            return self.validator.validate_slot_data(data)
        else:
            raise ValueError(f"Unknown data type: {data_type}")

    def rollback_operation(self, operation_id: str) -> bool:
        """
        Rollback a failed operation.

        Args:
            operation_id: Operation ID to rollback

        Returns:
            True if rollback successful
        """
        try:
            self.atomic_manager.rollback_operation(operation_id)
            logger.info(f"Successfully rolled back operation: {operation_id}")
            return True
        except Exception as e:
            logger.error(f"Rollback failed for operation {operation_id}: {e}")
            return False

    def restore_from_backup(self, backup_id: str,
                          files_to_restore: Optional[List[str]] = None) -> bool:
        """
        Restore files from a backup.

        Args:
            backup_id: Backup identifier
            files_to_restore: Optional list of specific files to restore

        Returns:
            True if restore successful
        """
        try:
            return self.backup_manager.restore_backup(backup_id, files_to_restore)
        except Exception as e:
            logger.error(f"Backup restore failed for {backup_id}: {e}")
            return False

    def list_recovery_options(self) -> Dict[str, Any]:
        """
        Get available recovery options for the user.

        Returns:
            Dictionary with backup information and recovery options
        """
        recent_backups = self.backup_manager.list_backups(since_days=7)

        # Group by operation type
        by_operation: Dict[str, List[BackupMetadata]] = {}
        for backup in recent_backups:
            op_type = backup.operation_type
            if op_type not in by_operation:
                by_operation[op_type] = []
            by_operation[op_type].append(backup)

        return {
            "total_backups": len(recent_backups),
            "by_operation_type": {
                op_type: {
                    "count": len(backups),
                    "latest": backups[0].timestamp if backups else None,
                    "backups": [
                        {
                            "id": f"{b.timestamp}_{b.operation_type}",
                            "timestamp": b.timestamp,
                            "description": b.operation_description,
                            "files": b.files_backed_up
                        }
                        for b in backups[:5]  # Show up to 5 recent
                    ]
                }
                for op_type, backups in by_operation.items()
            },
            "latest_backup": recent_backups[0] if recent_backups else None
        }

    def verify_system_integrity(self) -> Dict[str, Any]:
        """
        Verify integrity of the save corruption prevention system.

        Returns:
            Dictionary with integrity check results
        """
        results = {
            "validator": {"status": "ok", "issues": []},
            "atomic_manager": {"status": "ok", "issues": []},
            "backup_manager": {"status": "ok", "issues": []},
            "overall_status": "ok"
        }

        # Check validator
        try:
            # Test validation with minimal data
            test_data = {"gameStats": {}, "dexData": {}}
            self.validator.validate_trainer_data(test_data)
        except Exception as e:
            results["validator"]["status"] = "error"
            results["validator"]["issues"].append(str(e))

        # Check backup manager
        try:
            self.backup_manager.list_backups()
        except Exception as e:
            results["backup_manager"]["status"] = "error"
            results["backup_manager"]["issues"].append(str(e))

        # Check file system access
        try:
            trainer_path = trainer_save_path(self.username)
            os.makedirs(os.path.dirname(trainer_path), exist_ok=True)
        except Exception as e:
            results["atomic_manager"]["status"] = "error"
            results["atomic_manager"]["issues"].append(f"File system access: {e}")

        # Overall status
        if any(component["status"] != "ok" for component in results.values() if isinstance(component, dict)):
            results["overall_status"] = "degraded"

        return results

    def cleanup_old_data(self, keep_days: int = 30) -> Dict[str, int]:
        """
        Clean up old backups and temporary files.

        Args:
            keep_days: Number of days to keep backups

        Returns:
            Dictionary with cleanup statistics
        """
        results = {"backups_removed": 0, "temp_files_removed": 0}

        # Clean up old backups
        try:
            removed_backups = self.backup_manager.cleanup_old_backups(keep_days=keep_days)
            results["backups_removed"] = removed_backups
        except Exception as e:
            logger.warning(f"Backup cleanup failed: {e}")

        # Clean up temporary files in user directory
        if self.cleanup_temp_files:
            try:
                user_dir = os.path.dirname(trainer_save_path(self.username))
                temp_files = 0
                for root, dirs, files in os.walk(user_dir):
                    for file in files:
                        if file.endswith('.tmp') or file.endswith('.bak'):
                            file_path = os.path.join(root, file)
                            try:
                                # Only remove files older than 1 day
                                if time.time() - os.path.getmtime(file_path) > 86400:
                                    os.remove(file_path)
                                    temp_files += 1
                            except Exception:
                                pass
                results["temp_files_removed"] = temp_files
            except Exception as e:
                logger.warning(f"Temp file cleanup failed: {e}")

        return results

    def _safe_save_single_file(self, file_path: str, data: Dict[str, Any],
                             operation_type: str, operation_description: str,
                             validation_type: str) -> SaveOperationResult:
        """Internal method for safe single file saving."""
        operation_id = None
        backup_id = None
        validation_result = None
        rollback_performed = False

        try:
            # Validate data if enabled
            if self.validate_before_save:
                validation_result = self.validate_data(data, validation_type)
                if validation_result.has_errors:
                    errors = [issue.message for issue in validation_result.get_errors()]
                    return SaveOperationResult(
                        success=False,
                        operation_id=None,
                        backup_id=None,
                        validation_result=validation_result,
                        files_saved=[],
                        error_message=f"Validation failed: {'; '.join(errors)}"
                    )

            # Create backup if enabled and file exists
            if self.auto_backup and os.path.exists(file_path):
                backup_id = self.backup_manager.create_operation_backup(
                    operation_type=operation_type,
                    description=operation_description,
                    files_to_backup=[file_path],
                    session_info={"single_file_operation": True}
                )

            # Perform atomic save
            backup_info = self.atomic_manager.safe_write_json(
                file_path=file_path,
                data=data,
                operation=operation_description,
                create_backup=False,  # We created our own backup above
                validate=False  # Already validated above
            )

            return SaveOperationResult(
                success=True,
                operation_id=operation_id,
                backup_id=backup_id,
                validation_result=validation_result,
                files_saved=[file_path]
            )

        except Exception as e:
            error_message = f"Save operation failed: {e}"
            logger.error(error_message)

            # Attempt rollback if we have operation info
            if operation_id:
                try:
                    rollback_performed = self.rollback_operation(operation_id)
                except Exception:
                    pass

            return SaveOperationResult(
                success=False,
                operation_id=operation_id,
                backup_id=backup_id,
                validation_result=validation_result,
                files_saved=[],
                error_message=error_message,
                rollback_performed=rollback_performed
            )

    def get_corruption_prevention_status(self) -> Dict[str, Any]:
        """Get status of corruption prevention features."""
        return {
            "auto_backup_enabled": self.auto_backup,
            "validation_enabled": self.validate_before_save,
            "cleanup_enabled": self.cleanup_temp_files,
            "system_integrity": self.verify_system_integrity(),
            "recent_backups": len(self.backup_manager.list_backups(since_days=7)),
            "username": self.username
        }


def create_save_corruption_prevention_system(username: str) -> SaveCorruptionPreventionSystem:
    """Create a configured save corruption prevention system for a user."""
    return SaveCorruptionPreventionSystem(username)