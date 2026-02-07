"""
AzabBot - Database Backup System
================================

Wrapper around unified backup system with AzabBot-specific configuration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from pathlib import Path
from typing import Dict, List, Optional

# Import from shared unified backup system
from shared.services.backup import (
    BackupScheduler as _BackupScheduler,
    create_backup_system,
    BACKUP_RETENTION_DAYS,
)


# =============================================================================
# AzabBot-Specific Configuration
# =============================================================================

DATABASE_PATH = Path("data/azab.db")
BACKUP_DIR = Path("data/backups")
BACKUP_PREFIX = "azab"
LOCAL_RETENTION_DAYS = 3  # Local VPS retention (R2 keeps 7 days)


# =============================================================================
# Configured Backup System
# =============================================================================

_backup_system = create_backup_system(
    database_path=str(DATABASE_PATH),
    backup_prefix=BACKUP_PREFIX,
    backup_dir=str(BACKUP_DIR),
    retention_days=LOCAL_RETENTION_DAYS,
)

# Export configured functions
create_backup = _backup_system["create_backup"]
cleanup_old_backups = _backup_system["cleanup_old_backups"]
list_backups = _backup_system["list_backups"]
get_latest_backup = _backup_system["get_latest_backup"]


# =============================================================================
# Configured Backup Scheduler
# =============================================================================

class BackupScheduler(_BackupScheduler):
    """BackupScheduler configured for AzabBot."""

    def __init__(self) -> None:
        super().__init__(
            database_path=str(DATABASE_PATH),
            backup_prefix=BACKUP_PREFIX,
            backup_dir=str(BACKUP_DIR),
            retention_days=LOCAL_RETENTION_DAYS,
        )


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
