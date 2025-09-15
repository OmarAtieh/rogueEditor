"""
Rollback Manager for Save Corruption Recovery

This module provides comprehensive rollback capabilities for the save corruption
prevention system, including user-friendly recovery workflows and emergency
recovery procedures.

CRITICAL SAFETY: This system provides the last line of defense against data loss.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Callable

from .enhanced_backup import EnhancedBackupManager, BackupMetadata
from .save_corruption_prevention import SaveCorruptionPreventionSystem

logger = logging.getLogger(__name__)


@dataclass
class RecoveryOption:
    """Represents a recovery option for the user."""
    recovery_id: str
    description: str
    recovery_type: str  # "backup_restore", "operation_rollback", "emergency_restore"
    timestamp: str
    affected_files: List[str]
    risk_level: str  # "low", "medium", "high"
    recommendation: str


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    success: bool
    recovery_type: str
    files_restored: List[str]
    error_message: Optional[str] = None
    warnings: List[str] = None


class RollbackManager:
    """
    Manager for rollback and recovery operations.

    Provides user-friendly recovery workflows with clear guidance
    and comprehensive safety checks.
    """

    def __init__(self, username: str):
        self.username = username
        self.backup_manager = EnhancedBackupManager(username)
        self.corruption_prevention = SaveCorruptionPreventionSystem(username)

    def get_recovery_options(self, crisis_mode: bool = False) -> List[RecoveryOption]:
        """
        Get available recovery options for the user.

        Args:
            crisis_mode: If True, includes more aggressive recovery options

        Returns:
            List of recovery options sorted by recommendation
        """
        options: List[RecoveryOption] = []

        # Get recent backups
        recent_backups = self.backup_manager.list_backups(since_days=30)

        # Create backup-based recovery options
        for backup in recent_backups[:10]:  # Show up to 10 recent backups
            backup_id = f"{backup.timestamp}_{backup.operation_type}"

            # Determine risk level based on backup age and operation type
            try:
                backup_time = time.mktime(time.strptime(
                    backup.timestamp[:15], "%Y%m%d_%H%M%S"
                ))
                age_hours = (time.time() - backup_time) / 3600
            except Exception:
                age_hours = 999

            if age_hours < 1:
                risk_level = "low"
                recommendation = "Safe - Recent backup with minimal data loss"
            elif age_hours < 24:
                risk_level = "medium"
                recommendation = "Acceptable - May lose recent progress"
            else:
                risk_level = "high"
                recommendation = "High data loss - Only use if necessary"

            option = RecoveryOption(
                recovery_id=backup_id,
                description=f"Restore from {backup.operation_description} ({backup.timestamp})",
                recovery_type="backup_restore",
                timestamp=backup.timestamp,
                affected_files=backup.files_backed_up,
                risk_level=risk_level,
                recommendation=recommendation
            )
            options.append(option)

        # In crisis mode, add emergency options
        if crisis_mode:
            # Emergency: restore from any available backup
            all_backups = self.backup_manager.list_backups()
            if all_backups:
                latest = all_backups[0]
                latest_id = f"{latest.timestamp}_{latest.operation_type}"

                emergency_option = RecoveryOption(
                    recovery_id=f"emergency_{latest_id}",
                    description="EMERGENCY: Restore latest available backup",
                    recovery_type="emergency_restore",
                    timestamp=latest.timestamp,
                    affected_files=latest.files_backed_up,
                    risk_level="high",
                    recommendation="Last resort - Significant data loss possible"
                )
                options.append(emergency_option)

        # Sort by risk level and age (lower risk first, newer first)
        risk_order = {"low": 0, "medium": 1, "high": 2}
        options.sort(key=lambda opt: (risk_order.get(opt.risk_level, 3), opt.timestamp), reverse=True)

        return options

    def execute_recovery(self, recovery_id: str,
                        confirmation_callback: Optional[Callable[[RecoveryOption], bool]] = None) -> RecoveryResult:
        """
        Execute a recovery operation.

        Args:
            recovery_id: Recovery option ID
            confirmation_callback: Optional callback for user confirmation

        Returns:
            RecoveryResult with operation details
        """
        # Find the recovery option
        recovery_option = None
        for option in self.get_recovery_options(crisis_mode=True):
            if option.recovery_id == recovery_id:
                recovery_option = option
                break

        if not recovery_option:
            return RecoveryResult(
                success=False,
                recovery_type="unknown",
                files_restored=[],
                error_message=f"Recovery option not found: {recovery_id}"
            )

        # Get user confirmation if callback provided
        if confirmation_callback and not confirmation_callback(recovery_option):
            return RecoveryResult(
                success=False,
                recovery_type=recovery_option.recovery_type,
                files_restored=[],
                error_message="Recovery cancelled by user"
            )

        # Execute recovery based on type
        try:
            if recovery_option.recovery_type in ["backup_restore", "emergency_restore"]:
                return self._execute_backup_restore(recovery_option)
            elif recovery_option.recovery_type == "operation_rollback":
                return self._execute_operation_rollback(recovery_option)
            else:
                return RecoveryResult(
                    success=False,
                    recovery_type=recovery_option.recovery_type,
                    files_restored=[],
                    error_message=f"Unknown recovery type: {recovery_option.recovery_type}"
                )

        except Exception as e:
            logger.error(f"Recovery execution failed: {e}")
            return RecoveryResult(
                success=False,
                recovery_type=recovery_option.recovery_type,
                files_restored=[],
                error_message=f"Recovery failed: {e}"
            )

    def _execute_backup_restore(self, recovery_option: RecoveryOption) -> RecoveryResult:
        """Execute backup-based recovery."""
        # Extract backup ID from recovery ID
        if recovery_option.recovery_id.startswith("emergency_"):
            backup_id = recovery_option.recovery_id[10:]  # Remove "emergency_" prefix
        else:
            backup_id = recovery_option.recovery_id

        warnings = []

        # Verify backup integrity before restore
        is_intact, errors = self.backup_manager.verify_backup_integrity(backup_id)
        if not is_intact:
            warnings.extend([f"Backup integrity issue: {error}" for error in errors])
            if recovery_option.recovery_type != "emergency_restore":
                return RecoveryResult(
                    success=False,
                    recovery_type=recovery_option.recovery_type,
                    files_restored=[],
                    error_message=f"Backup integrity check failed: {'; '.join(errors)}"
                )

        # Create safety backup before restore
        safety_backup_id = None
        try:
            existing_files = [f for f in recovery_option.affected_files if os.path.exists(f)]
            if existing_files:
                safety_backup_id = self.backup_manager.create_operation_backup(
                    operation_type="pre_recovery",
                    description=f"Safety backup before recovery {recovery_option.recovery_id}",
                    files_to_backup=existing_files,
                    session_info={"recovery_operation": True}
                )
                warnings.append(f"Created safety backup: {safety_backup_id}")
        except Exception as e:
            warnings.append(f"Could not create safety backup: {e}")

        # Perform restore
        try:
            success = self.backup_manager.restore_backup(backup_id)
            if success:
                return RecoveryResult(
                    success=True,
                    recovery_type=recovery_option.recovery_type,
                    files_restored=recovery_option.affected_files,
                    warnings=warnings
                )
            else:
                return RecoveryResult(
                    success=False,
                    recovery_type=recovery_option.recovery_type,
                    files_restored=[],
                    error_message="Backup restore failed"
                )

        except Exception as e:
            # Try to restore safety backup if available
            if safety_backup_id:
                try:
                    self.backup_manager.restore_backup(safety_backup_id)
                    warnings.append("Restored safety backup after restore failure")
                except Exception:
                    warnings.append("Could not restore safety backup")

            return RecoveryResult(
                success=False,
                recovery_type=recovery_option.recovery_type,
                files_restored=[],
                error_message=f"Restore failed: {e}",
                warnings=warnings
            )

    def _execute_operation_rollback(self, recovery_option: RecoveryOption) -> RecoveryResult:
        """Execute operation-based rollback."""
        # This would be used for rolling back specific operations
        # Implementation depends on having operation tracking
        return RecoveryResult(
            success=False,
            recovery_type=recovery_option.recovery_type,
            files_restored=[],
            error_message="Operation rollback not yet implemented"
        )

    def emergency_file_recovery(self, file_path: str) -> Dict[str, Any]:
        """
        Attempt emergency recovery of a specific file.

        Args:
            file_path: Path to file that needs recovery

        Returns:
            Dictionary with recovery information and options
        """
        recovery_info = {
            "file_path": file_path,
            "current_status": "unknown",
            "recovery_options": [],
            "recommendations": []
        }

        # Check current file status
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    json.load(f)
                recovery_info["current_status"] = "valid_json"
                recovery_info["recommendations"].append("File appears to be valid")
            except json.JSONDecodeError:
                recovery_info["current_status"] = "corrupted_json"
                recovery_info["recommendations"].append("File contains invalid JSON")
            except Exception:
                recovery_info["current_status"] = "unreadable"
                recovery_info["recommendations"].append("File cannot be read")
        else:
            recovery_info["current_status"] = "missing"
            recovery_info["recommendations"].append("File does not exist")

        # Find backups containing this file
        all_backups = self.backup_manager.list_backups()
        for backup in all_backups:
            if file_path in backup.files_backed_up:
                backup_id = f"{backup.timestamp}_{backup.operation_type}"

                # Check if backup file exists and is valid
                backup_details = self.backup_manager.get_backup_details(backup_id)
                if backup_details:
                    metadata, entries = backup_details
                    for entry in entries:
                        if entry.original_path == file_path:
                            try:
                                if os.path.exists(entry.backup_path):
                                    with open(entry.backup_path, 'r', encoding='utf-8') as f:
                                        json.load(f)
                                    recovery_info["recovery_options"].append({
                                        "backup_id": backup_id,
                                        "timestamp": backup.timestamp,
                                        "description": backup.operation_description,
                                        "status": "valid"
                                    })
                                else:
                                    recovery_info["recovery_options"].append({
                                        "backup_id": backup_id,
                                        "timestamp": backup.timestamp,
                                        "description": backup.operation_description,
                                        "status": "missing"
                                    })
                            except Exception:
                                recovery_info["recovery_options"].append({
                                    "backup_id": backup_id,
                                    "timestamp": backup.timestamp,
                                    "description": backup.operation_description,
                                    "status": "corrupted"
                                })

        # Sort recovery options by timestamp (newest first)
        recovery_info["recovery_options"].sort(
            key=lambda opt: opt["timestamp"], reverse=True
        )

        # Add recommendations based on findings
        if recovery_info["recovery_options"]:
            valid_options = [opt for opt in recovery_info["recovery_options"] if opt["status"] == "valid"]
            if valid_options:
                recovery_info["recommendations"].append(
                    f"Found {len(valid_options)} valid backup(s) - recovery possible"
                )
            else:
                recovery_info["recommendations"].append(
                    "Found backups but none are valid - limited recovery options"
                )
        else:
            recovery_info["recommendations"].append(
                "No backups found for this file - recovery not possible"
            )

        return recovery_info

    def create_recovery_report(self) -> Dict[str, Any]:
        """
        Create a comprehensive recovery report for the user.

        Returns:
            Dictionary with recovery status and recommendations
        """
        report = {
            "username": self.username,
            "report_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system_status": {},
            "recovery_readiness": {},
            "recommendations": []
        }

        # Check system integrity
        integrity_check = self.corruption_prevention.verify_system_integrity()
        report["system_status"] = integrity_check

        # Analyze backup coverage
        all_backups = self.backup_manager.list_backups()
        recent_backups = self.backup_manager.list_backups(since_days=7)

        report["recovery_readiness"] = {
            "total_backups": len(all_backups),
            "recent_backups": len(recent_backups),
            "latest_backup": all_backups[0].timestamp if all_backups else None,
            "backup_integrity": "unknown"
        }

        # Check backup integrity for recent backups
        intact_count = 0
        for backup in recent_backups[:5]:  # Check up to 5 recent backups
            backup_id = f"{backup.timestamp}_{backup.operation_type}"
            is_intact, _ = self.backup_manager.verify_backup_integrity(backup_id)
            if is_intact:
                intact_count += 1

        if recent_backups:
            integrity_rate = intact_count / min(len(recent_backups), 5)
            if integrity_rate >= 0.8:
                report["recovery_readiness"]["backup_integrity"] = "good"
                report["recommendations"].append("Backup system is functioning well")
            elif integrity_rate >= 0.5:
                report["recovery_readiness"]["backup_integrity"] = "fair"
                report["recommendations"].append("Some backup integrity issues detected")
            else:
                report["recovery_readiness"]["backup_integrity"] = "poor"
                report["recommendations"].append("Critical backup integrity issues - immediate attention needed")

        # General recommendations
        if len(recent_backups) == 0:
            report["recommendations"].append("No recent backups - consider creating a backup")
        elif len(recent_backups) < 3:
            report["recommendations"].append("Limited backup history - consider more frequent backups")

        if integrity_check["overall_status"] != "ok":
            report["recommendations"].append("System integrity issues detected - run diagnostics")

        return report


def create_rollback_manager(username: str) -> RollbackManager:
    """Create a rollback manager for the specified user."""
    return RollbackManager(username)