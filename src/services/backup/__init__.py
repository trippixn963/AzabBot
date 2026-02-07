"""
AzabBot - Database Backup Package
=================================

Wrapper around unified backup system with AzabBot-specific configuration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .scheduler import (
    BackupScheduler,
    create_backup,
    cleanup_old_backups,
    list_backups,
    get_latest_backup,
    BACKUP_DIR,
    DATABASE_PATH,
    BACKUP_RETENTION_DAYS,
)

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
