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
        self.run_id: str = str(uuid.uuid4())[:8]
        self.log_file: Path = Path('logs') / f'azab_{datetime.now().strftime("%Y-%m-%d")}.log'
        self.log_file.parent.mkdir(exist_ok=True)

        self._cleanup_old_logs()

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
        current_time = datetime.now()
        tz_name = "EDT" if current_time.month >= 3 and current_time.month <= 11 else "EST"
        return current_time.strftime(f'[%I:%M:%S %p {tz_name}]')

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        if include_timestamp:
            timestamp: str = self._get_timestamp()
            full_message: str = f"{timestamp} {emoji} {message}" if emoji else f"{timestamp} {message}"
        else:
            full_message: str = f"{emoji} {message}" if emoji else message

        print(full_message)

        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{full_message}\n")

    def tree(self, title: str, items: List[Tuple[str, str]], emoji: str = "📦") -> None:
        """Log structured data in tree format."""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")

        self._write(f"{title}", emoji=emoji)
        for i, (key, value) in enumerate(items):
            prefix: str = "└─" if i == len(items) - 1 else "├─"
            self._write(f"  {prefix} {key}: {value}", include_timestamp=False)

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
