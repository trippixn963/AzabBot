"""
AzabBot - Log Buffer Service
============================

In-memory circular buffer for capturing bot logs for the dashboard API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

MAX_BUFFER_SIZE = 1000
TIMEZONE = ZoneInfo("America/New_York")


# =============================================================================
# Log Entry Model
# =============================================================================

@dataclass
class LogEntry:
    """A single log entry."""

    timestamp: datetime
    level: str
    message: str
    module: str = "bot"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "level": self.level,
            "message": self.message,
            "module": self.module,
        }


# =============================================================================
# Log Buffer
# =============================================================================

class LogBuffer:
    """
    Circular buffer for capturing bot logs.

    Uses a fixed-size deque to prevent memory growth.
    The buffer stores logs for the REST API endpoint only.
    WebSocket streaming is handled separately by StatusBroadcaster.
    """

    def __init__(self, max_size: int = MAX_BUFFER_SIZE) -> None:
        self._buffer: Deque[LogEntry] = deque(maxlen=max_size)
        self._registered = False

    def add(self, level: str, message: str, module: str = "bot") -> LogEntry:
        """Add a log entry to the buffer."""
        entry = LogEntry(
            timestamp=datetime.now(TIMEZONE).replace(tzinfo=None),
            level=level,
            message=message,
            module=module,
        )
        self._buffer.append(entry)
        return entry

    def get_logs(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Get logs from the buffer.

        Args:
            limit: Maximum number of logs to return
            level: Filter by level (INFO, WARNING, ERROR, or None for all)
            offset: Number of entries to skip

        Returns:
            List of log entries as dictionaries (newest first)
        """
        logs = list(reversed(self._buffer))

        if level and level.upper() != "ALL":
            level_upper = level.upper()
            logs = [log for log in logs if log.level == level_upper]

        return [log.to_dict() for log in logs[offset:offset + limit]]

    def register_with_logger(self) -> None:
        """Register this buffer to receive logs from the logger."""
        if self._registered:
            return

        from src.core.logger import logger
        logger.on_log(lambda level, msg, module: self.add(level, msg, module))
        self._registered = True

    @property
    def size(self) -> int:
        """Get current buffer size."""
        return len(self._buffer)


# =============================================================================
# Singleton
# =============================================================================

_buffer: Optional[LogBuffer] = None


def get_log_buffer() -> LogBuffer:
    """Get the log buffer singleton."""
    global _buffer
    if _buffer is None:
        _buffer = LogBuffer()
        _buffer.register_with_logger()
    return _buffer


__all__ = ["LogBuffer", "LogEntry", "get_log_buffer"]
