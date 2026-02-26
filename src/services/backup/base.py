"""
AzabBot - Cloud Backup System
=============================

Hourly SQLite database backups directly to Cloudflare R2.
No local storage - backups go straight to cloud.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp

from src.core.logger import logger
from src.utils.async_utils import create_safe_task


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_RETENTION_HOURS = 48  # Keep 48 hourly backups (2 days)
SECONDS_PER_HOUR = 3600

# Size divisors
KB_DIVISOR = 1024
MB_DIVISOR = 1024 * 1024
GB_DIVISOR = 1024 * 1024 * 1024


# =============================================================================
# Helpers
# =============================================================================

def _format_size(size_bytes: int) -> str:
    """Format file size to appropriate unit (KB, MB, GB)."""
    if size_bytes >= GB_DIVISOR:
        return f"{size_bytes / GB_DIVISOR:.2f} GB"
    elif size_bytes >= MB_DIVISOR:
        return f"{size_bytes / MB_DIVISOR:.1f} MB"
    else:
        return f"{size_bytes / KB_DIVISOR:.1f} KB"


def _get_timezone(timezone_name: Optional[str] = None) -> ZoneInfo:
    """Get timezone, with fallback to default."""
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except (KeyError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _check_database_integrity(db_path: Path) -> tuple[bool, str]:
    """Check SQLite database integrity before backup."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()[0]
        conn.close()
        return (True, "ok") if result == "ok" else (False, result)
    except sqlite3.DatabaseError as e:
        return False, f"Database error: {e}"
    except Exception as e:
        return False, f"Check failed: {e}"


def _format_tree_log(
    title: str,
    items: List[tuple[str, Any]],
    emoji: str = "💾",
    tz: Optional[ZoneInfo] = None,
) -> str:
    """Format a tree log message for webhook."""
    if tz is None:
        tz = ZoneInfo(DEFAULT_TIMEZONE)

    timestamp = datetime.now(tz).strftime("[%I:%M:%S %p %Z]")
    lines = [f"{timestamp} {emoji} {title}"]

    for i, (key, value) in enumerate(items):
        is_last = i == len(items) - 1
        prefix = "└─" if is_last else "├─"
        lines.append(f"  {prefix} {key}: {value}")

    return "\n".join(lines)


# =============================================================================
# Webhook
# =============================================================================

async def _send_backup_webhook(
    webhook_url: str,
    title: str,
    items: List[tuple[str, Any]],
    emoji: str = "💾",
    tz: Optional[ZoneInfo] = None,
) -> None:
    """Send backup notification to Discord webhook."""
    if not webhook_url:
        return

    formatted = _format_tree_log(title, items, emoji, tz)
    payload = {
        "content": f"```\n{formatted}\n```",
        "username": "Backups",
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status >= 400:
                    logger.warning("Backup Webhook Failed", [
                        ("Status", str(response.status)),
                    ])
    except Exception as e:
        logger.warning("Backup Webhook Error", [
            ("Error", f"{type(e).__name__}: {str(e)[:50]}"),
        ])


async def send_backup_notification(result: Optional[Dict[str, Any]]) -> None:
    """Send webhook notification for R2 backup events."""
    if result is None:
        return

    webhook_url = result.get("webhook_url")
    if not webhook_url:
        return

    tz = result.get("tz")

    if result.get("success"):
        await _send_backup_webhook(
            webhook_url,
            "R2 Backup Uploaded",
            [
                ("Bot", result["bot_name"]),
                ("Size", result["size"]),
                ("Retention", f"{result['retention_hours']} hours"),
                ("Integrity", "Verified ✓"),
            ],
            emoji="☁️",
            tz=tz,
        )
    elif result.get("error") == "corruption":
        await _send_backup_webhook(
            webhook_url,
            "Backup ABORTED - Corruption",
            [
                ("Bot", result["bot_name"]),
                ("Integrity", result["integrity_msg"]),
                ("Action", "Backup skipped"),
            ],
            emoji="🚨",
            tz=tz,
        )
    elif result.get("error") == "upload_failed":
        await _send_backup_webhook(
            webhook_url,
            "R2 Upload Failed",
            [
                ("Bot", result["bot_name"]),
                ("Error", result.get("error_msg", "Unknown")[:80]),
            ],
            emoji="❌",
            tz=tz,
        )


# =============================================================================
# R2 Backup System
# =============================================================================

class R2BackupScheduler:
    """
    Hourly backup scheduler with direct R2 upload.

    No local storage - creates temp file, uploads to R2, deletes temp file.
    """

    def __init__(
        self,
        database_path: str,
        bot_name: str,
        r2_bucket: str = "bot-backups",
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        webhook_url: Optional[str] = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        """
        Initialize R2 backup scheduler.

        Args:
            database_path: Path to SQLite database
            bot_name: Bot name for backup folder (e.g., "azab")
            r2_bucket: R2 bucket name (rclone remote)
            retention_hours: Hours to keep backups (default 48)
            webhook_url: Discord webhook for notifications
            timezone_name: Timezone for timestamps
        """
        self._db_path = Path(database_path)
        self._bot_name = bot_name.lower()
        self._bot_display = bot_name.capitalize()
        self._r2_bucket = r2_bucket
        self._retention_hours = retention_hours
        self._webhook_url = webhook_url
        self._tz = _get_timezone(timezone_name)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _create_backup_and_upload(self) -> Dict[str, Any]:
        """
        Create backup and upload to R2.

        Returns dict with result info for webhook notification.
        """
        base_result = {
            "bot_name": self._bot_display,
            "webhook_url": self._webhook_url,
            "tz": self._tz,
            "retention_hours": self._retention_hours,
        }

        # Check database exists
        if not self._db_path.exists():
            logger.warning("Backup Skipped - DB Not Found", [
                ("Path", str(self._db_path)),
            ])
            return None

        # Check integrity
        is_healthy, integrity_msg = _check_database_integrity(self._db_path)
        if not is_healthy:
            logger.error("Backup ABORTED - Corruption", [
                ("Bot", self._bot_display),
                ("Integrity", integrity_msg[:100]),
            ])
            return {**base_result, "success": False, "error": "corruption", "integrity_msg": integrity_msg[:100]}

        # Create temp backup file with clean path structure
        # Format: Azab/2026-02-25/8PM.db
        now = datetime.now(self._tz)
        date_folder = now.strftime("%Y-%m-%d")
        hour = now.strftime("%-I%p")  # e.g., "8PM", "12AM"
        backup_filename = f"{hour}.db"
        r2_folder = f"{self._bot_display}/{date_folder}"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / backup_filename

            try:
                # Copy database to temp
                shutil.copy2(self._db_path, temp_path)
                backup_size = temp_path.stat().st_size
                size_str = _format_size(backup_size)

                # Upload to R2 using rclone
                r2_path = f"r2:{self._r2_bucket}/{r2_folder}/{backup_filename}"
                result = subprocess.run(
                    ["rclone", "copyto", str(temp_path), r2_path],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() or "Upload failed"
                    logger.error("R2 Upload Failed", [
                        ("Bot", self._bot_display),
                        ("Error", error_msg[:100]),
                    ])
                    return {**base_result, "success": False, "error": "upload_failed", "error_msg": error_msg}

                logger.tree("R2 Backup Uploaded", [
                    ("Bot", self._bot_display),
                    ("Path", f"{r2_folder}/{backup_filename}"),
                    ("Size", size_str),
                ], emoji="☁️")

                return {**base_result, "success": True, "size": size_str, "filename": backup_filename, "r2_path": f"{r2_folder}/{backup_filename}"}

            except subprocess.TimeoutExpired:
                logger.error("R2 Upload Timeout", [("Bot", self._bot_display)])
                return {**base_result, "success": False, "error": "upload_failed", "error_msg": "Timeout"}
            except Exception as e:
                logger.error("Backup Failed", [
                    ("Bot", self._bot_display),
                    ("Error", str(e)[:100]),
                ])
                return {**base_result, "success": False, "error": "upload_failed", "error_msg": str(e)}

    def _cleanup_old_backups(self) -> int:
        """Remove R2 backups older than retention period."""
        try:
            r2_path = f"r2:{self._r2_bucket}/{self._bot_display}/"
            result = subprocess.run(
                ["rclone", "delete", r2_path, f"--min-age={self._retention_hours}h", "--rmdirs"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                logger.tree("R2 Cleanup Complete", [
                    ("Bot", self._bot_display),
                    ("Retention", f"{self._retention_hours} hours"),
                ], emoji="🧹")
            return 0
        except Exception as e:
            logger.warning("R2 Cleanup Failed", [
                ("Error", str(e)[:50]),
            ])
            return 0

    def _seconds_until_next_hour(self) -> float:
        """Calculate seconds until next hour."""
        now = datetime.now(self._tz)
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return (next_hour - now).total_seconds()

    async def start(self) -> None:
        """Start the hourly backup scheduler."""
        if self._running:
            return

        self._running = True

        # Run initial backup
        try:
            result = await asyncio.to_thread(self._create_backup_and_upload)
            await send_backup_notification(result)
        except Exception as e:
            logger.warning("Initial Backup Failed", [
                ("Error", str(e)),
            ])

        # Start scheduler loop
        self._task = create_safe_task(self._scheduler_loop(), name=f"backup_{self._bot_name}")

        logger.tree("R2 Backup Scheduler Started", [
            ("Bot", self._bot_display),
            ("Schedule", "Every hour"),
            ("Retention", f"{self._retention_hours} hours"),
            ("Bucket", f"{self._r2_bucket}/{self._bot_name}"),
        ], emoji="☁️")

    async def stop(self) -> None:
        """Stop the backup scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scheduler_loop(self) -> None:
        """Main loop - runs every hour on the hour."""
        while self._running:
            try:
                # Wait until next hour
                await asyncio.sleep(self._seconds_until_next_hour())

                if not self._running:
                    break

                # Create backup and upload
                result = await asyncio.to_thread(self._create_backup_and_upload)
                await send_backup_notification(result)

                # Cleanup old backups
                await asyncio.to_thread(self._cleanup_old_backups)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Backup Scheduler Error", [
                    ("Bot", self._bot_display),
                    ("Error", str(e)),
                ])
                await asyncio.sleep(SECONDS_PER_HOUR)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "R2BackupScheduler",
    "send_backup_notification",
    "DEFAULT_RETENTION_HOURS",
    "DEFAULT_TIMEZONE",
]
