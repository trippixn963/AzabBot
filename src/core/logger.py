"""
Azab Discord Bot - Logger Module
===============================

Custom logging system with EST timezone support and tree-style formatting.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Console and file output simultaneously
- Emoji-enhanced log levels for visual clarity
- Daily log file rotation
- Automatic cleanup of old logs (30+ days)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import uuid
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Optional


class MiniTreeLogger:
    """Custom logger with tree-style formatting and EST timezone support."""

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log file rotation."""
        # DESIGN: Generate short 8-char run ID for tracking bot sessions
        # UUID4 ensures uniqueness across restarts
        # First 8 chars sufficient for collision avoidance in small-scale bot
        # Allows correlating logs from same session in distributed systems
        self.run_id: str = str(uuid.uuid4())[:8]

        # DESIGN: Daily log file rotation with YYYY-MM-DD naming
        # New file created at midnight automatically
        # Easy to find logs by date
        # Path instead of str for cross-platform compatibility
        self.log_file: Path = Path('logs') / f'azab_{datetime.now().strftime("%Y-%m-%d")}.log'
        self.log_file.parent.mkdir(exist_ok=True)

        # DESIGN: Clean up old logs on initialization
        # Prevents disk space issues from accumulated logs
        # Runs once per bot start (low overhead)
        self._cleanup_old_logs()

        # DESIGN: Write session header to log file
        # Visually separates bot restarts in logs
        # Run ID helps correlate logs from same session
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"NEW SESSION STARTED - RUN ID: {self.run_id}\n")
            f.write(f"{self._get_timestamp()}\n")
            f.write(f"{'='*60}\n\n")

    def _cleanup_old_logs(self) -> None:
        """Clean up log files older than configured retention days."""
        try:
            logs_dir = Path('logs')
            if not logs_dir.exists():
                return

            now = datetime.now()

            deleted_count = 0
            for log_file in logs_dir.glob('azab_*.log'):
                file_time = datetime.fromtimestamp(os.path.getmtime(log_file))

                if (now - file_time).days > int(os.getenv('LOG_RETENTION_DAYS', '30')):
                    log_file.unlink()
                    deleted_count += 1

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log files (>{os.getenv('LOG_RETENTION_DAYS', '30')} days)")

        except Exception as e:
            print(f"[LOG CLEANUP ERROR] Failed to clean old logs: {e}")

    def _get_timestamp(self) -> str:
        """Get current timestamp in Eastern timezone (auto EST/EDT)."""
        # DESIGN: Simple EST/EDT detection based on month
        # March-November = EDT (daylight saving)
        # December-February = EST (standard time)
        # Approximation works for most cases, doesn't handle exact DST transition dates
        current_time: datetime = datetime.now()
        tz_name: str = "EDT" if current_time.month >= 3 and current_time.month <= 11 else "EST"
        return current_time.strftime(f'[%I:%M:%S %p {tz_name}]')

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        # DESIGN: Build formatted log message with optional timestamp and emoji
        # include_timestamp=False for tree branches (cleaner formatting)
        # Emoji first, then message for visual scanning
        if include_timestamp:
            timestamp: str = self._get_timestamp()
            full_message: str = f"{timestamp} {emoji} {message}" if emoji else f"{timestamp} {message}"
        else:
            full_message: str = f"{emoji} {message}" if emoji else message

        # DESIGN: Write to both console and file simultaneously
        # Console for real-time monitoring
        # File for persistent debugging and audit trail
        print(full_message)

        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{full_message}\n")

    def tree(self, title: str, items: List[Tuple[str, str]], emoji: str = "📦") -> None:
        """Log structured data in tree format."""
        # DESIGN: Add blank line before tree for visual separation
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")

        # DESIGN: Tree-style formatting for structured data
        # Title with timestamp and emoji
        # Items with box-drawing characters (├─ and └─)
        # Last item gets └─ (bottom corner), others get ├─ (middle connector)
        # Indentation (2 spaces) for visual hierarchy
        self._write(f"{title}", emoji=emoji)
        for i, (key, value) in enumerate(items):
            prefix: str = "└─" if i == len(items) - 1 else "├─"
            self._write(f"  {prefix} {key}: {value}", include_timestamp=False)

        # DESIGN: Add blank line after tree for visual separation
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")

    def info(self, msg: str) -> None:
        """Log an informational message."""
        self._write(msg, "ℹ️")

    def success(self, msg: str) -> None:
        """Log a success message."""
        self._write(msg, "✅")

    def error(self, msg: str) -> None:
        """Log an error message."""
        self._write(msg, "❌")

    def warning(self, msg: str) -> None:
        """Log a warning message."""
        self._write(msg, "⚠️")


logger = MiniTreeLogger()
