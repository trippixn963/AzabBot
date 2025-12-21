"""
Azab Discord Bot - Logger Module
=================================

Custom tree-style logging with EST timezone and daily rotation.

DESIGN:
    This logger provides structured, hierarchical output that's easy to scan
    visually. Tree-style formatting groups related information together,
    while EST timestamps ensure consistency with the target user base.

    Key features:
    - Tree-style formatting for structured data visualization
    - EST timezone timestamps (auto EST/EDT handling)
    - Daily log rotation in dated folders
    - 7-day log retention with automatic cleanup
    - Session tracking with unique run IDs
    - Discord webhook integration for error alerts

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import uuid
import aiohttp
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

LOGS_DIR = Path("logs")
"""Directory for all log files, organized by date."""

LOG_RETENTION_DAYS = 7
"""Number of days to retain log directories before cleanup."""

NY_TZ = ZoneInfo("America/New_York")
"""Eastern timezone for consistent timestamps."""


# =============================================================================
# Tree Logger Class
# =============================================================================

class TreeLogger:
    """
    Custom logger with tree-style formatting and EST timezone support.

    DESIGN:
        Uses tree-style output (├─ └─) for visual hierarchy.
        All timestamps in Eastern time for consistency.
        Separate error log file for quick troubleshooting.
        Optional webhook notifications for critical errors.

    Attributes:
        run_id: Unique identifier for this bot session.
        log_file: Path to the main log file.
        error_file: Path to the error-only log file.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """
        Initialize logger with run ID and daily log file.

        Creates dated log directory, initializes log files,
        cleans up old logs, and writes session header.
        """
        self.run_id: str = str(uuid.uuid4())[:8]
        self._webhook_url: Optional[str] = None
        self._bot_name: str = "Azab"

        # Create dated log directory
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        self.log_dir = LOGS_DIR / today
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Log files
        self.log_file = self.log_dir / f"Azab-{today}.log"
        self.error_file = self.log_dir / f"Azab-Errors-{today}.log"

        # Cleanup old logs
        self._cleanup_old_logs()

        # Write session header
        self._write_session_header()

    def set_webhook(self, url: Optional[str]) -> None:
        """
        Set webhook URL for error notifications.

        Args:
            url: Discord webhook URL for error alerts.
        """
        self._webhook_url = url

    # =========================================================================
    # Log Cleanup
    # =========================================================================

    def _cleanup_old_logs(self) -> None:
        """
        Remove log directories older than retention period.

        DESIGN:
            Runs on startup to prevent unbounded log growth.
            Only removes directories matching date format YYYY-MM-DD.
            Silently skips invalid directory names.
        """
        if not LOGS_DIR.exists():
            return

        now = datetime.now()
        deleted = 0

        for item in LOGS_DIR.iterdir():
            if item.is_dir() and item.name != "__pycache__":
                try:
                    dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                    age_days = (now - dir_date).days
                    if age_days > LOG_RETENTION_DAYS:
                        for f in item.iterdir():
                            f.unlink()
                        item.rmdir()
                        deleted += 1
                except ValueError:
                    pass  # Skip non-date directories

        if deleted > 0:
            print(f"[LOG CLEANUP] Removed {deleted} old log directories")

    # =========================================================================
    # Session Header
    # =========================================================================

    def _write_session_header(self) -> None:
        """
        Write session start marker to log file.

        DESIGN:
            Clear visual separator between bot restarts.
            Includes run ID for correlating logs to specific sessions.
        """
        header = f"""
============================================================
NEW SESSION - RUN ID: {self.run_id}
[{datetime.now(NY_TZ).strftime("%I:%M:%S %p %Z")}]
============================================================
"""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(header)

    # =========================================================================
    # Core Logging
    # =========================================================================

    def _get_timestamp(self) -> str:
        """
        Get current timestamp in Eastern timezone.

        Returns:
            Formatted timestamp string like "[02:30:45 PM EST]".
        """
        return datetime.now(NY_TZ).strftime("[%I:%M:%S %p %Z]")

    def _write(
        self,
        message: str,
        emoji: str = "",
        include_timestamp: bool = True,
        is_error: bool = False,
    ) -> None:
        """
        Write log message to console and file.

        DESIGN:
            All logs go to console for immediate visibility.
            Main log captures everything.
            Error log only captures errors for quick troubleshooting.

        Args:
            message: Log message content.
            emoji: Optional emoji prefix.
            include_timestamp: Whether to prepend timestamp.
            is_error: Whether to also write to error log.
        """
        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {message}" if emoji else f"{timestamp} {message}"
        else:
            full_message = f"{emoji} {message}" if emoji else message

        print(full_message)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{full_message}\n")

        if is_error:
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")

    # =========================================================================
    # Tree Formatting
    # =========================================================================

    def tree(
        self,
        title: str,
        items: List[Tuple[str, str]],
        emoji: str = "📦",
    ) -> None:
        """
        Log structured data in tree format.

        DESIGN:
            Visual hierarchy makes logs easy to scan.
            Title on first line, items indented with tree connectors.
            Blank lines before/after for visual separation.

        Args:
            title: Main heading for the tree.
            items: List of (key, value) tuples to display.
            emoji: Emoji prefix for the title.

        Example output:
            [02:30:45 PM EST] 📦 Bot Started
              ├─ Name: Azab
              ├─ Guilds: 5
              └─ Status: Online
        """
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("\n")

        self._write(title, emoji=emoji)

        for i, (key, value) in enumerate(items):
            prefix = "└─" if i == len(items) - 1 else "├─"
            self._write(f"  {prefix} {key}: {value}", include_timestamp=False)

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("\n")

    def tree_nested(
        self,
        title: str,
        sections: List[Tuple[str, List[Tuple[str, str]]]],
        emoji: str = "📦",
    ) -> None:
        """
        Log nested tree structure with sections.

        DESIGN:
            Two-level hierarchy for complex data.
            Outer level for categories, inner level for details.

        Args:
            title: Main heading for the tree.
            sections: List of (section_name, items) tuples.
            emoji: Emoji prefix for the title.

        Example output:
            [02:30:45 PM EST] 📦 Configuration
              ├─ Discord
              │  ├─ Token: ****
              │  └─ Guilds: 5
              └─ AI
                 ├─ Model: gpt-4o-mini
                 └─ Status: Online
        """
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("\n")

        self._write(title, emoji=emoji)

        for i, (section_name, items) in enumerate(sections):
            is_last_section = i == len(sections) - 1
            section_prefix = "└─" if is_last_section else "├─"
            self._write(f"  {section_prefix} {section_name}", include_timestamp=False)

            for j, (key, value) in enumerate(items):
                is_last_item = j == len(items) - 1
                connector = "   " if is_last_section else "│  "
                item_prefix = "└─" if is_last_item else "├─"
                self._write(
                    f"  {connector} {item_prefix} {key}: {value}",
                    include_timestamp=False,
                )

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write("\n")

    # =========================================================================
    # Log Levels
    # =========================================================================

    def debug(self, msg: str) -> None:
        """
        Log debug message (only if DEBUG env var set).

        Args:
            msg: Debug message content.
        """
        if os.getenv("DEBUG"):
            self._write(msg, "🔍")

    def info(self, msg: str) -> None:
        """
        Log informational message.

        Args:
            msg: Info message content.
        """
        self._write(msg, "ℹ️")

    def success(self, msg: str) -> None:
        """
        Log success message.

        Args:
            msg: Success message content.
        """
        self._write(msg, "✅")

    def warning(self, msg: str) -> None:
        """
        Log warning message.

        Args:
            msg: Warning message content.
        """
        self._write(msg, "⚠️")

    def error(
        self,
        msg: str,
        details: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """
        Log error message with optional structured details.

        DESIGN:
            Errors with details use tree format for visibility.
            Automatically sends to webhook if configured.
            Always written to both main and error log files.

        Args:
            msg: Error message or title.
            details: Optional list of (key, value) detail tuples.
        """
        if details:
            self._write("", is_error=True)  # Blank line before
            self._write(msg, "❌", is_error=True)
            for i, (key, value) in enumerate(details):
                prefix = "└─" if i == len(details) - 1 else "├─"
                self._write(
                    f"  {prefix} {key}: {value}",
                    include_timestamp=False,
                    is_error=True,
                )
            self._write("", include_timestamp=False, is_error=True)  # Blank line after

            # Send to webhook
            if self._webhook_url:
                asyncio.create_task(self._send_webhook_error(msg, details))
        else:
            self._write(msg, "❌", is_error=True)

    def critical(self, msg: str) -> None:
        """
        Log critical error message.

        Args:
            msg: Critical error message content.
        """
        self._write(msg, "🚨", is_error=True)

    # =========================================================================
    # Webhook Integration
    # =========================================================================

    async def _send_webhook_error(
        self,
        title: str,
        details: List[Tuple[str, str]],
    ) -> None:
        """
        Send error notification to Discord webhook.

        DESIGN:
            Non-blocking async operation to avoid log delays.
            Includes run ID for session correlation.
            Gracefully handles webhook failures.

        Args:
            title: Error title for the embed.
            details: List of (key, value) detail tuples.
        """
        if not self._webhook_url:
            return

        try:
            description = "\n".join([f"**{k}:** {v}" for k, v in details])
            payload = {
                "embeds": [{
                    "title": f"❌ {title}",
                    "description": description,
                    "color": 0xFF0000,
                    "timestamp": datetime.now(NY_TZ).isoformat(),
                    "footer": {"text": f"Run ID: {self.run_id}"},
                }]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 204:
                        print(f"Webhook error: {resp.status}")

        except Exception as e:
            print(f"Failed to send webhook: {e}")


# =============================================================================
# Global Instance
# =============================================================================

logger = TreeLogger()
"""
Global logger instance for use throughout the application.

DESIGN:
    Single instance created at module import time.
    All modules import and use this same instance.
"""


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "logger",
    "TreeLogger",
]
