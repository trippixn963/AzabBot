"""
AzabBot - State Operations Mixin
================================

Bot state and ignored users operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
from typing import TYPE_CHECKING, Any, Set

from src.core.logger import logger

if TYPE_CHECKING:
    from .manager import DatabaseManager


class StateMixin:
    """Mixin for bot state and ignored users operations."""

    # =========================================================================
    # Bot State Operations
    # =========================================================================

    def get_bot_state(self: "DatabaseManager", key: str, default: Any = None) -> Any:
        """
        Get a bot state value.

        Args:
            key: State key to retrieve
            default: Default value if key not found

        Returns:
            Stored value or default
        """
        row = self.fetchone("SELECT value FROM bot_state WHERE key = ?", (key,))
        if row:
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return row["value"]
        return default

    def set_bot_state(self: "DatabaseManager", key: str, value: Any) -> None:
        """
        Set a bot state value.

        Args:
            key: State key to set
            value: Value to store (will be JSON encoded)
        """
        value_str = json.dumps(value) if not isinstance(value, str) else value
        self.execute(
            "INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value_str, time.time())
        )

    def is_active(self: "DatabaseManager") -> bool:
        """Check if bot is active (not disabled)."""
        return self.get_bot_state("is_active", True)

    def set_active(self: "DatabaseManager", active: bool) -> None:
        """
        Set bot active state.

        Args:
            active: True to enable, False to disable
        """
        self.set_bot_state("is_active", active)
        logger.tree("Bot State Changed", [
            ("Active", str(active)),
        ], emoji="⚙️")

    # =========================================================================
    # Ignored Users Operations
    # =========================================================================

    def get_ignored_users(self: "DatabaseManager") -> Set[int]:
        """Get set of ignored user IDs."""
        rows = self.fetchall("SELECT user_id FROM ignored_users")
        return {row["user_id"] for row in rows}

    def add_ignored_user(self: "DatabaseManager", user_id: int) -> None:
        """Add a user to ignored list."""
        self.execute(
            "INSERT OR IGNORE INTO ignored_users (user_id, added_at) VALUES (?, ?)",
            (user_id, time.time())
        )
        logger.tree("User Added to Ignore List", [
            ("User ID", str(user_id)),
        ], emoji="🚫")

    def remove_ignored_user(self: "DatabaseManager", user_id: int) -> None:
        """Remove a user from ignored list."""
        self.execute("DELETE FROM ignored_users WHERE user_id = ?", (user_id,))
        logger.tree("User Removed from Ignore List", [
            ("User ID", str(user_id)),
        ], emoji="✅")

    def is_user_ignored(self: "DatabaseManager", user_id: int) -> bool:
        """Check if a user is ignored."""
        row = self.fetchone(
            "SELECT 1 FROM ignored_users WHERE user_id = ?",
            (user_id,)
        )
        return row is not None


__all__ = ["StateMixin"]
