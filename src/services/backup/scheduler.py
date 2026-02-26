"""
AzabBot - R2 Backup Scheduler
=============================

Hourly backups directly to Cloudflare R2.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os

from src.services.backup.base import R2BackupScheduler


# =============================================================================
# AzabBot Configuration
# =============================================================================

DATABASE_PATH = "data/azab.db"
BOT_NAME = "azab"
R2_BUCKET = "bot-backups"
RETENTION_HOURS = 48  # Keep 2 days of hourly backups


# =============================================================================
# Configured Scheduler
# =============================================================================

class BackupScheduler:
    """R2 Backup Scheduler configured for AzabBot."""

    def __init__(self) -> None:
        self._scheduler = R2BackupScheduler(
            database_path=DATABASE_PATH,
            bot_name=BOT_NAME,
            r2_bucket=R2_BUCKET,
            retention_hours=RETENTION_HOURS,
            webhook_url=os.getenv("BACKUP_WEBHOOK_URL"),
        )

    async def start(self) -> None:
        """Start the hourly backup scheduler."""
        await self._scheduler.start()

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        await self._scheduler.stop()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "BackupScheduler",
    "DATABASE_PATH",
    "BOT_NAME",
    "R2_BUCKET",
    "RETENTION_HOURS",
]
