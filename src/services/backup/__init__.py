"""
AzabBot - R2 Backup Package
===========================

Hourly backups directly to Cloudflare R2.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .scheduler import (
    BackupScheduler,
    DATABASE_PATH,
    BOT_NAME,
    R2_BUCKET,
    RETENTION_HOURS,
)

from .base import (
    R2BackupScheduler,
    send_backup_notification,
)

__all__ = [
    "BackupScheduler",
    "R2BackupScheduler",
    "send_backup_notification",
    "DATABASE_PATH",
    "BOT_NAME",
    "R2_BUCKET",
    "RETENTION_HOURS",
]
