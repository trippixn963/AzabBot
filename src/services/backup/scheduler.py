"""
AzabBot - Database Backup Scheduler
===================================

Wrapper around unified backup system with AzabBot-specific configuration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from pathlib import Path
from typing import Optional, Callable, Dict, List, Any


# =============================================================================
# AzabBot-Specific Configuration
# =============================================================================

DATABASE_PATH = Path("data/azab.db")
BACKUP_DIR = Path("data/backups")
BACKUP_PREFIX = "azab"
LOCAL_RETENTION_DAYS = 3  # Local VPS retention (R2 keeps 7 days)
BACKUP_RETENTION_DAYS = 7  # For backwards compatibility


# =============================================================================
# Lazy-loaded Backup System
# =============================================================================

_backup_system: Optional[Dict[str, Any]] = None


def _get_backup_system() -> Dict[str, Any]:
    """Get or create the backup system (lazy initialization)."""
    global _backup_system
    if _backup_system is None:
        from src.services.backup.base import create_backup_system
        _backup_system = create_backup_system(
            database_path=str(DATABASE_PATH),
            backup_prefix=BACKUP_PREFIX,
            backup_dir=str(BACKUP_DIR),
            retention_days=LOCAL_RETENTION_DAYS,
        )
    return _backup_system


def create_backup() -> Optional[Path]:
    """Create a backup of the database."""
    return _get_backup_system()["create_backup"]()


def cleanup_old_backups() -> int:
    """Clean up old backups beyond retention period."""
    return _get_backup_system()["cleanup_old_backups"]()


def list_backups() -> List[Dict]:
    """List all available backups."""
    return _get_backup_system()["list_backups"]()


def get_latest_backup() -> Optional[Path]:
    """Get the most recent backup file."""
    return _get_backup_system()["get_latest_backup"]()


# =============================================================================
# Configured Backup Scheduler
# =============================================================================

class BackupScheduler:
    """BackupScheduler configured for AzabBot."""

    def __init__(self) -> None:
        from src.services.backup.base import BackupSchedulerBase
        self._scheduler = BackupSchedulerBase(
            database_path=str(DATABASE_PATH),
            backup_prefix=BACKUP_PREFIX,
            backup_dir=str(BACKUP_DIR),
            retention_days=LOCAL_RETENTION_DAYS,
        )

    @property
    def create_backup(self) -> Callable[[], Optional[Path]]:
        """Get the create_backup function."""
        return self._scheduler.create_backup

    @property
    def cleanup_old_backups(self) -> Callable[[], int]:
        """Get the cleanup_old_backups function."""
        return self._scheduler.cleanup_old_backups

    @property
    def list_backups(self) -> Callable[[], List[Dict]]:
        """Get the list_backups function."""
        return self._scheduler.list_backups

    @property
    def get_latest_backup(self) -> Callable[[], Optional[Path]]:
        """Get the get_latest_backup function."""
        return self._scheduler.get_latest_backup

    async def start(self, run_immediately: bool = True) -> None:
        """Start the backup scheduler."""
        await self._scheduler.start(run_immediately)

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        await self._scheduler.stop()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "create_backup",
    "cleanup_old_backups",
    "list_backups",
    "get_latest_backup",
    "BackupScheduler",
    "BACKUP_DIR",
    "DATABASE_PATH",
    "BACKUP_RETENTION_DAYS",
]
