"""
Azab Discord Bot - Logger
==========================

Custom logging system with tree-style formatting and EST timezone support.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Nested tree support for hierarchical data
- Console and file output simultaneously
- Emoji-enhanced log levels for visual clarity
- Daily log folders with separate log and error files
- Automatic cleanup of old logs (7+ days)
- Smart spacing between tree logs

Log Structure:
    logs/
    ├── 2025-12-06/
    │   ├── Azab-2025-12-06.log
    │   └── Azab-Errors-2025-12-06.log
    ├── 2025-12-07/
    │   ├── Azab-2025-12-07.log
    │   └── Azab-Errors-2025-12-07.log
    └── ...

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import re
import shutil
import uuid
import traceback
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

# Log retention period in days
LOG_RETENTION_DAYS = 7

# Regex to match emojis
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "\U00002300-\U000023FF"  # misc technical
    "]+",
    flags=re.UNICODE
)


# =============================================================================
# Tree Symbols
# =============================================================================

class TreeSymbols:
    """Box-drawing characters for tree formatting."""
    BRANCH = "├─"      # Middle item connector
    LAST = "└─"        # Last item connector
    PIPE = "│ "        # Vertical continuation
    SPACE = "  "       # Empty space for alignment
    HEADER = "┌─"      # Tree header
    FOOTER = "└─"      # Tree footer


# =============================================================================
# MiniTreeLogger
# =============================================================================

class MiniTreeLogger:
    """Custom logger with tree-style formatting and EST timezone support."""

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log folder rotation."""
        self.run_id: str = str(uuid.uuid4())[:8]

        # Timezone for date calculations
        self._timezone = ZoneInfo("America/New_York")

        # Track last log type for spacing between trees
        self._last_was_tree: bool = False

        # Live logs Discord webhook streaming (from env var)
        self._live_logs_webhook_url: str = os.getenv("LIVE_LOGS_WEBHOOK_URL", "")
        self._live_logs_enabled: bool = bool(self._live_logs_webhook_url)

        # Error webhook (from env var)
        self._error_webhook_url: str = os.getenv("ERROR_WEBHOOK_URL", "")

        # Base logs directory
        self.logs_base_dir = Path(__file__).parent.parent.parent / "logs"
        self.logs_base_dir.mkdir(exist_ok=True)

        # Get current date in EST timezone
        self.current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

        # Create daily folder (e.g., logs/2025-12-06/)
        self.log_dir = self.logs_base_dir / self.current_date
        self.log_dir.mkdir(exist_ok=True)

        # Create log files inside daily folder
        self.log_file: Path = self.log_dir / f"Azab-{self.current_date}.log"
        self.error_file: Path = self.log_dir / f"Azab-Errors-{self.current_date}.log"

        # Clean up old log folders (older than 7 days)
        self._cleanup_old_logs()

        # Write session header
        self._write_session_header()

    # =========================================================================
    # Private Methods - Setup
    # =========================================================================

    def _cleanup_old_logs(self) -> None:
        """Clean up log folders older than retention period (7 days).

        OPTIMIZATION: Uses glob pattern matching (????-??-??) to only
        find date-formatted folders, avoiding iteration over non-date items.
        Then calculates cutoff date once and compares directly.
        """
        try:
            now = datetime.now(self._timezone)
            cutoff_date = now - timedelta(days=LOG_RETENTION_DAYS)
            deleted_count = 0

            # Use glob pattern to only match date-formatted folders (YYYY-MM-DD)
            for folder in self.logs_base_dir.glob("????-??-??"):
                if not folder.is_dir():
                    continue

                try:
                    folder_date = datetime.strptime(folder.name, "%Y-%m-%d")
                    folder_date = folder_date.replace(tzinfo=self._timezone)

                    # Direct date comparison is cleaner than days calculation
                    if folder_date < cutoff_date:
                        shutil.rmtree(folder)
                        deleted_count += 1
                except ValueError:
                    # Folder name matched pattern but isn't valid date
                    continue

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log folders (>{LOG_RETENTION_DAYS} days)")
        except Exception as e:
            print(f"[LOG CLEANUP ERROR] {type(e).__name__}: {e}")

    def _check_date_rotation(self) -> None:
        """Check if date has changed and rotate to new log folder if needed."""
        current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

        if current_date != self.current_date:
            # Date has changed - rotate to new folder
            self.current_date = current_date
            self.log_dir = self.logs_base_dir / self.current_date
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = self.log_dir / f"Azab-{self.current_date}.log"
            self.error_file = self.log_dir / f"Azab-Errors-{self.current_date}.log"

            # Write continuation header to new log files
            header = (
                f"\n{'='*60}\n"
                f"LOG ROTATION - Continuing session {self.run_id}\n"
                f"{self._get_timestamp()}\n"
                f"{'='*60}\n\n"
            )
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(header)
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(header)
            except (OSError, IOError):
                pass

    def _write_session_header(self) -> None:
        """Write session header to both log file and error log file."""
        header = (
            f"\n{'='*60}\n"
            f"NEW SESSION - RUN ID: {self.run_id}\n"
            f"{self._get_timestamp()}\n"
            f"{'='*60}\n\n"
        )
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header)
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(header)
        except (OSError, IOError):
            pass

    def _send_error_webhook(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌"
    ) -> None:
        """Send error to dedicated error webhook as tree format."""
        if not self._error_webhook_url:
            return

        # Format as tree (same as live logs)
        formatted = self._format_tree_for_live(title, items, emoji)
        payload = {
            "content": f"```\n{formatted}\n```",
            "username": "AzabBot Errors",
        }

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_send_webhook(payload, self._error_webhook_url))
        except RuntimeError:
            pass

    async def _async_send_webhook(self, payload: dict, webhook_url: str) -> None:
        """Send webhook payload asynchronously."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    pass
        except Exception:
            pass

    # =========================================================================
    # Live Logs - Discord Webhook Streaming
    # =========================================================================

    def _send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook immediately."""
        if not self._live_logs_enabled:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_send_live_log(formatted_tree))
        except RuntimeError:
            # No event loop running yet
            pass

    async def _async_send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook."""
        payload = {
            "content": f"```\n{formatted_tree}\n```",
            "username": "AzabBot Logs",
        }
        try:
            await self._async_send_webhook(payload, self._live_logs_webhook_url)
        except Exception:
            pass

    def _format_tree_for_live(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> str:
        """Format a tree log for the live buffer."""
        timestamp = self._get_timestamp()
        lines = [f"{timestamp} {emoji} {self._strip_emojis(title)}"]

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            lines.append(f"  {prefix} {key}: {value}")

        return "\n".join(lines)

    # =========================================================================
    # Private Methods - Formatting
    # =========================================================================

    def _get_timestamp(self) -> str:
        """Get current timestamp in Eastern timezone (auto EST/EDT)."""
        try:
            current_time = datetime.now(self._timezone)
            tz_name = current_time.strftime("%Z")
            return current_time.strftime(f"[%I:%M:%S %p {tz_name}]")
        except Exception:
            return datetime.now().strftime("[%I:%M:%S %p]")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis from text to avoid duplicate emojis in output."""
        return EMOJI_PATTERN.sub("", text).strip()

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _write_raw(self, message: str, also_to_error: bool = False) -> None:
        """Write raw message without timestamp (for tree branches)."""
        print(message)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{message}\n")
            if also_to_error:
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(f"{message}\n")
        except (OSError, IOError):
            pass

    def _write_error(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write error message to both main log and error log file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _tree_error(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌",
    ) -> None:
        """Log structured error data in tree format to both log files and live logs."""
        if not self._last_was_tree:
            self._write_raw("", also_to_error=True)

        self._write_error(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}", also_to_error=True)

        # Add empty line after error tree for readability
        self._write_raw("", also_to_error=True)
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

        # Also send to dedicated error webhook
        self._send_error_webhook(title, items, emoji)

    # =========================================================================
    # Public Methods - Log Levels
    # =========================================================================

    def info(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an informational message."""
        if details:
            self.tree(msg, details, emoji="ℹ️")
        else:
            self._write(msg, "ℹ️")
            self._last_was_tree = False

    def success(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a success message."""
        if details:
            self.tree(msg, details, emoji="✅")
        else:
            self._write(msg, "✅")
            self._last_was_tree = False

    def error(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(msg, details, emoji="❌")
        else:
            self._write_error(msg, "❌")
            self._last_was_tree = False

    def warning(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a warning message (also writes to error log and live logs)."""
        if details:
            self._tree_error(msg, details, emoji="⚠️")
        else:
            self._write_error(msg, "⚠️")
            self._last_was_tree = False

    def debug(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a debug message (only if DEBUG env var is set)."""
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            if details:
                self.tree(msg, details, emoji="🔍")
            else:
                self._write(msg, "🔍")
                self._last_was_tree = False

    def critical(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a critical/fatal error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(msg, details, emoji="🚨")
        else:
            self._write_error(msg, "🚨")
            self._last_was_tree = False

    def exception(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an exception with full traceback (also writes to error log and live logs)."""
        if details:
            self._tree_error(msg, details, emoji="💥")
        else:
            self._write_error(msg, "💥")
        try:
            tb = traceback.format_exc()
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
        except (OSError, IOError):
            pass

    # =========================================================================
    # Public Methods - Tree Formatting
    # =========================================================================

    def tree(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> None:
        """
        Log structured data in tree format.

        Example output:

            [12:00:00 PM EST] 📦 Bot Ready
              ├─ Bot ID: 123456789
              ├─ Guilds: 5
              └─ Latency: 50ms

        Args:
            title: Tree title/header
            items: List of (key, value) tuples
            emoji: Emoji prefix for title
        """
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}")

        self._write_raw("")
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

    def tree_nested(
        self,
        title: str,
        data: Dict[str, Any],
        emoji: str = "📦",
        indent: int = 0
    ) -> None:
        """
        Log nested/hierarchical data in tree format.

        Example output:
            [12:00:00 PM EST] 📦 Service Status
              ├─ Discord
              │   ├─ Connected: True
              │   └─ Guilds: 2
              └─ Database
                  ├─ Path: /data/azab.db
                  └─ Status: OK

        Args:
            title: Tree title/header
            data: Nested dictionary
            emoji: Emoji prefix for title
            indent: Current indentation level
        """
        if indent == 0:
            if not self._last_was_tree:
                self._write_raw("")
            self._write(title, emoji)

        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * (indent + 1)

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}{prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}{prefix} {key}: {value}")

        if indent == 0:
            self._last_was_tree = True

    def _render_nested(self, data: Dict[str, Any], indent: int, parent_is_last: bool) -> None:
        """Recursively render nested tree data."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * indent

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}  {prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}  {prefix} {key}: {value}")

    def tree_list(
        self,
        title: str,
        items: List[str],
        emoji: str = "📋"
    ) -> None:
        """
        Log a simple list in tree format.

        Example output:
            [12:00:00 PM EST] 📋 Active Services
              ├─ AI Service
              ├─ Mod Tracker
              └─ Health Server

        Args:
            title: Tree title/header
            items: List of string items
            emoji: Emoji prefix for title
        """
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {item}")

        self._last_was_tree = True

    def tree_section(
        self,
        title: str,
        sections: Dict[str, List[Tuple[str, Any]]],
        emoji: str = "📊"
    ) -> None:
        """
        Log multiple sections in tree format.

        Example output:
            [12:00:00 PM EST] 📊 Bot Stats
              ├─ Services
              │   ├─ AI: Online
              │   └─ Mod Tracker: Enabled
              └─ System
                  ├─ Uptime: 2h
                  └─ Memory: 50MB

        Args:
            title: Tree title/header
            sections: Dict of section_name -> [(key, value), ...]
            emoji: Emoji prefix for title
        """
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        section_names = list(sections.keys())
        for si, section_name in enumerate(section_names):
            section_is_last = si == len(section_names) - 1
            section_prefix = TreeSymbols.LAST if section_is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {section_prefix} {section_name}")

            items = sections[section_name]
            for ii, (key, value) in enumerate(items):
                item_is_last = ii == len(items) - 1
                item_prefix = TreeSymbols.LAST if item_is_last else TreeSymbols.BRANCH
                continuation = TreeSymbols.SPACE if section_is_last else TreeSymbols.PIPE
                self._write_raw(f"  {continuation} {item_prefix} {key}: {value}")

        self._last_was_tree = True

    def error_tree(
        self,
        title: str,
        error: Exception,
        context: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log an error with context in tree format.

        Example output:
            [12:00:00 PM EST] ❌ Database Error
              ├─ Type: ConnectionError
              ├─ Message: Failed to connect
              ├─ User ID: 123456
              └─ Action: record_mute

        Args:
            title: Error title/description
            error: The exception that occurred
            context: Additional context as (key, value) tuples
        """
        items: List[Tuple[str, Any]] = [
            ("Type", type(error).__name__),
            ("Message", str(error)),
        ]

        if context:
            items.extend(context)

        self._tree_error(title, items, emoji="❌")

    def startup_tree(
        self,
        bot_name: str,
        bot_id: int,
        guilds: int,
        latency: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log bot startup information in tree format.

        Args:
            bot_name: Name of the bot
            bot_id: Discord bot ID
            guilds: Number of guilds
            latency: WebSocket latency in ms
            extra: Additional startup info
        """
        items: List[Tuple[str, Any]] = [
            ("Bot ID", bot_id),
            ("Guilds", guilds),
            ("Latency", f"{latency:.0f}ms"),
            ("Run ID", self.run_id),
        ]

        if extra:
            items.extend(extra)

        self.tree(f"Bot Ready: {bot_name}", items, emoji="🤖")

    def mute_tree(
        self,
        action: str,
        user: str,
        moderator: str,
        duration: str,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log mute events in a standardized tree format.

        Example output:
            [12:00:00 PM EST] 🔇 User Muted
              ├─ User: @someone
              ├─ Moderator: @mod
              ├─ Duration: 1h
              └─ Reason: Spam

        Args:
            action: What happened (User Muted, User Unmuted, etc.)
            user: Target user
            moderator: Mod who performed action
            duration: Mute duration
            extra: Additional context
        """
        items: List[Tuple[str, Any]] = [
            ("User", user),
            ("Moderator", moderator),
            ("Duration", duration),
        ]

        if extra:
            items.extend(extra)

        self.tree(action, items, emoji="🔇")


# =============================================================================
# Module Export
# =============================================================================

logger = MiniTreeLogger()

__all__ = ["logger", "MiniTreeLogger", "TreeSymbols"]
