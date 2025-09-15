"""
Enhanced Backup System for Save Corruption Prevention

This module provides an enhanced backup system with:
1. Pre-modification backups with operation context
2. Automatic cleanup of old backups
3. Quick recovery UI integration
4. Backup integrity verification
5. Operation-specific backup organization

CRITICAL SAFETY: All risky operations must create backups before proceeding.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .utils import user_save_dir, sanitize_username

logger = logging.getLogger(__name__)


@dataclass
class BackupMetadata:
    """Metadata for a backup operation."""
    timestamp: str
    operation_type: str
    operation_description: str
    files_backed_up: List[str]
    total_size_bytes: int
    username: str
    session_info: Optional[Dict[str, Any]] = None
    validation_status: Optional[str] = None


@dataclass
class BackupEntry:
    """Individual backup file entry."""
    original_path: str
    backup_path: str
    size_bytes: int
    checksum: Optional[str] = None


class EnhancedBackupManager:
    """
    Enhanced backup manager with operation context and recovery features.

    Features:
    - Operation-specific backup organization
    - Comprehensive metadata tracking
    - Automated cleanup policies
    - Integrity verification
    - Quick recovery workflows
    """

    def __init__(self, username: str):
        self.username = sanitize_username(username)
        self.base_dir = user_save_dir(self.username)
        self.backup_root = os.path.join(self.base_dir, "backups")
        self.operations_dir = os.path.join(self.backup_root, "operations")
        self.metadata_dir = os.path.join(self.backup_root, "metadata")

        # Ensure directories exist
        os.makedirs(self.operations_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)

    def create_operation_backup(self, operation_type: str, description: str,
                              files_to_backup: List[str],
                              session_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a backup for a specific operation.

        Args:
            operation_type: Type of operation (e.g., "team_edit", "item_add", "upload")
            description: Human-readable description
            files_to_backup: List of file paths to backup
            session_info: Optional session context information

        Returns:
            backup_id: Unique identifier for this backup

        Raises:
            RuntimeError: If backup creation fails
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"  # Include milliseconds
        backup_id = f"{timestamp}_{operation_type}"

        backup_dir = os.path.join(self.operations_dir, backup_id)
        os.makedirs(backup_dir, exist_ok=True)

        backup_entries: List[BackupEntry] = []
        total_size = 0

        try:
            # Backup each file
            for file_path in files_to_backup:
                if not os.path.exists(file_path):
                    logger.warning(f"File not found for backup: {file_path}")
                    continue

                # Create backup entry
                file_name = os.path.basename(file_path)
                backup_path = os.path.join(backup_dir, file_name)

                # Handle duplicate names by adding suffix
                counter = 1
                while os.path.exists(backup_path):
                    name, ext = os.path.splitext(file_name)
                    backup_path = os.path.join(backup_dir, f"{name}_{counter}{ext}")
                    counter += 1

                # Copy file with metadata
                shutil.copy2(file_path, backup_path)

                file_size = os.path.getsize(file_path)
                total_size += file_size

                backup_entry = BackupEntry(
                    original_path=file_path,
                    backup_path=backup_path,
                    size_bytes=file_size
                )
                backup_entries.append(backup_entry)

                logger.debug(f"Backed up: {file_path} -> {backup_path}")

            # Create metadata
            metadata = BackupMetadata(
                timestamp=timestamp,
                operation_type=operation_type,
                operation_description=description,
                files_backed_up=[entry.original_path for entry in backup_entries],
                total_size_bytes=total_size,
                username=self.username,
                session_info=session_info
            )

            # Save metadata
            metadata_path = os.path.join(self.metadata_dir, f"{backup_id}.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(metadata), f, ensure_ascii=False, indent=2)

            # Save backup entries
            entries_path = os.path.join(backup_dir, "backup_entries.json")
            with open(entries_path, 'w', encoding='utf-8') as f:
                json.dump([asdict(entry) for entry in backup_entries], f,
                         ensure_ascii=False, indent=2)

            logger.info(f"Created operation backup: {backup_id} ({len(backup_entries)} files, {total_size} bytes)")
            return backup_id

        except Exception as e:
            # Clean up partial backup
            if os.path.exists(backup_dir):
                try:
                    shutil.rmtree(backup_dir)
                except Exception:
                    pass

            metadata_path = os.path.join(self.metadata_dir, f"{backup_id}.json")
            if os.path.exists(metadata_path):
                try:
                    os.remove(metadata_path)
                except Exception:
                    pass

            raise RuntimeError(f"Backup creation failed: {e}") from e

    def list_backups(self, operation_type: Optional[str] = None,
                    since_days: Optional[int] = None) -> List[BackupMetadata]:
        """
        List available backups with optional filtering.

        Args:
            operation_type: Filter by operation type
            since_days: Only show backups from last N days

        Returns:
            List of backup metadata, sorted by timestamp (newest first)
        """
        backups: List[BackupMetadata] = []

        if not os.path.exists(self.metadata_dir):
            return backups

        cutoff_time = None
        if since_days is not None:
            cutoff_time = time.time() - (since_days * 24 * 60 * 60)

        try:
            for metadata_file in os.listdir(self.metadata_dir):
                if not metadata_file.endswith('.json'):
                    continue

                metadata_path = os.path.join(self.metadata_dir, metadata_file)

                try:
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata_dict = json.load(f)

                    metadata = BackupMetadata(**metadata_dict)

                    # Apply filters
                    if operation_type and metadata.operation_type != operation_type:
                        continue

                    if cutoff_time:
                        # Parse timestamp for comparison
                        backup_time = time.mktime(time.strptime(
                            metadata.timestamp[:15], "%Y%m%d_%H%M%S"
                        ))
                        if backup_time < cutoff_time:
                            continue

                    backups.append(metadata)

                except Exception as e:
                    logger.warning(f"Could not load backup metadata {metadata_file}: {e}")

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")

        # Sort by timestamp (newest first)
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        return backups

    def get_backup_details(self, backup_id: str) -> Optional[Tuple[BackupMetadata, List[BackupEntry]]]:
        """
        Get detailed information about a specific backup.

        Args:
            backup_id: Backup identifier

        Returns:
            Tuple of (metadata, backup_entries) or None if not found
        """
        metadata_path = os.path.join(self.metadata_dir, f"{backup_id}.json")
        if not os.path.exists(metadata_path):
            return None

        try:
            # Load metadata
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata_dict = json.load(f)
            metadata = BackupMetadata(**metadata_dict)

            # Load backup entries
            backup_dir = os.path.join(self.operations_dir, backup_id)
            entries_path = os.path.join(backup_dir, "backup_entries.json")

            if os.path.exists(entries_path):
                with open(entries_path, 'r', encoding='utf-8') as f:
                    entries_dict = json.load(f)
                entries = [BackupEntry(**entry) for entry in entries_dict]
            else:
                entries = []

            return metadata, entries

        except Exception as e:
            logger.error(f"Failed to get backup details for {backup_id}: {e}")
            return None

    def restore_backup(self, backup_id: str, files_to_restore: Optional[List[str]] = None) -> bool:
        """
        Restore files from a backup.

        Args:
            backup_id: Backup identifier
            files_to_restore: Optional list of specific files to restore (restore all if None)

        Returns:
            True if restore was successful

        Raises:
            RuntimeError: If restore fails
        """
        backup_details = self.get_backup_details(backup_id)
        if not backup_details:
            raise RuntimeError(f"Backup not found: {backup_id}")

        metadata, entries = backup_details

        # Filter entries if specific files requested
        if files_to_restore is not None:
            entries = [entry for entry in entries if entry.original_path in files_to_restore]

        if not entries:
            logger.warning(f"No files to restore from backup: {backup_id}")
            return True

        errors = []

        for entry in entries:
            try:
                if not os.path.exists(entry.backup_path):
                    errors.append(f"Backup file not found: {entry.backup_path}")
                    continue

                # Ensure target directory exists
                os.makedirs(os.path.dirname(entry.original_path), exist_ok=True)

                # Restore file
                shutil.copy2(entry.backup_path, entry.original_path)

                # Verify restore
                if not os.path.exists(entry.original_path):
                    errors.append(f"Failed to restore: {entry.original_path}")
                    continue

                restored_size = os.path.getsize(entry.original_path)
                if restored_size != entry.size_bytes:
                    errors.append(f"Size mismatch after restore: {entry.original_path}")
                    continue

                logger.info(f"Restored: {entry.original_path}")

            except Exception as e:
                errors.append(f"Error restoring {entry.original_path}: {e}")

        if errors:
            raise RuntimeError(f"Restore partially failed: {'; '.join(errors)}")

        logger.info(f"Backup restore completed: {backup_id}")
        return True

    def verify_backup_integrity(self, backup_id: str) -> Tuple[bool, List[str]]:
        """
        Verify integrity of a backup.

        Args:
            backup_id: Backup identifier

        Returns:
            Tuple of (is_intact, error_messages)
        """
        backup_details = self.get_backup_details(backup_id)
        if not backup_details:
            return False, [f"Backup not found: {backup_id}"]

        metadata, entries = backup_details
        errors = []

        # Check metadata file
        metadata_path = os.path.join(self.metadata_dir, f"{backup_id}.json")
        if not os.path.exists(metadata_path):
            errors.append("Metadata file missing")

        # Check backup directory
        backup_dir = os.path.join(self.operations_dir, backup_id)
        if not os.path.exists(backup_dir):
            errors.append("Backup directory missing")

        # Check each backup file
        for entry in entries:
            if not os.path.exists(entry.backup_path):
                errors.append(f"Backup file missing: {entry.backup_path}")
                continue

            try:
                actual_size = os.path.getsize(entry.backup_path)
                if actual_size != entry.size_bytes:
                    errors.append(f"Size mismatch: {entry.backup_path}")

                # Verify JSON files can be loaded
                if entry.backup_path.endswith('.json'):
                    with open(entry.backup_path, 'r', encoding='utf-8') as f:
                        json.load(f)

            except Exception as e:
                errors.append(f"Integrity check failed for {entry.backup_path}: {e}")

        return len(errors) == 0, errors

    def cleanup_old_backups(self, keep_days: int = 30, keep_minimum: int = 5) -> int:
        """
        Clean up old backup files.

        Args:
            keep_days: Number of days to keep backups
            keep_minimum: Minimum number of backups to always keep

        Returns:
            Number of backups removed
        """
        if keep_days <= 0:
            return 0

        all_backups = self.list_backups()

        if len(all_backups) <= keep_minimum:
            return 0  # Don't clean up if we're at minimum

        cutoff_time = time.time() - (keep_days * 24 * 60 * 60)
        removed_count = 0

        # Sort by timestamp (oldest first for cleanup)
        backups_by_age = sorted(all_backups, key=lambda b: b.timestamp)

        for backup in backups_by_age:
            # Keep minimum number of recent backups
            if len(all_backups) - removed_count <= keep_minimum:
                break

            try:
                # Parse timestamp
                backup_time = time.mktime(time.strptime(
                    backup.timestamp[:15], "%Y%m%d_%H%M%S"
                ))

                if backup_time < cutoff_time:
                    backup_id = f"{backup.timestamp}_{backup.operation_type}"

                    # Remove backup directory
                    backup_dir = os.path.join(self.operations_dir, backup_id)
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)

                    # Remove metadata
                    metadata_path = os.path.join(self.metadata_dir, f"{backup_id}.json")
                    if os.path.exists(metadata_path):
                        os.remove(metadata_path)

                    removed_count += 1
                    logger.debug(f"Removed old backup: {backup_id}")

            except Exception as e:
                logger.warning(f"Failed to remove backup {backup.timestamp}: {e}")

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old backups")

        return removed_count

    def get_latest_backup(self, operation_type: Optional[str] = None) -> Optional[BackupMetadata]:
        """
        Get the most recent backup, optionally filtered by operation type.

        Args:
            operation_type: Optional operation type filter

        Returns:
            Latest backup metadata or None
        """
        backups = self.list_backups(operation_type=operation_type, since_days=None)
        return backups[0] if backups else None

    def export_backup_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive backup report.

        Returns:
            Dictionary with backup statistics and information
        """
        all_backups = self.list_backups()

        # Group by operation type
        by_operation: Dict[str, List[BackupMetadata]] = {}
        total_size = 0
        total_files = 0

        for backup in all_backups:
            op_type = backup.operation_type
            if op_type not in by_operation:
                by_operation[op_type] = []
            by_operation[op_type].append(backup)
            total_size += backup.total_size_bytes
            total_files += len(backup.files_backed_up)

        # Calculate statistics
        operation_stats = {}
        for op_type, backups in by_operation.items():
            operation_stats[op_type] = {
                "count": len(backups),
                "total_size_bytes": sum(b.total_size_bytes for b in backups),
                "latest_timestamp": max(b.timestamp for b in backups) if backups else None
            }

        return {
            "username": self.username,
            "total_backups": len(all_backups),
            "total_size_bytes": total_size,
            "total_files_backed_up": total_files,
            "operation_statistics": operation_stats,
            "latest_backup": all_backups[0].timestamp if all_backups else None,
            "backup_directory": self.backup_root
        }


def create_enhanced_backup_manager(username: str) -> EnhancedBackupManager:
    """Create an enhanced backup manager for the specified user."""
    return EnhancedBackupManager(username)