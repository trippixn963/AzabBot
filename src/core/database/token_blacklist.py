"""
AzabBot - Token Blacklist Database Mixin
========================================

Database operations for JWT token blacklist persistence.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import hashlib
import time
from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class TokenBlacklistMixin:
    """Mixin for token blacklist database operations."""

    def add_blacklisted_token(self: "DatabaseManager", token: str, expires_at: float) -> bool:
        """
        Add a token to the blacklist.

        Args:
            token: The JWT token to blacklist
            expires_at: Unix timestamp when the token expires

        Returns:
            True if added successfully
        """
        try:
            # Store hash of token for security (don't store actual token)
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO token_blacklist
                   (token_hash, expires_at, blacklisted_at)
                   VALUES (?, ?, ?)""",
                (token_hash, expires_at, time.time())
            )
            conn.commit()
            return True
        except Exception:
            return False

    def is_token_blacklisted(self: "DatabaseManager", token: str) -> bool:
        """
        Check if a token is blacklisted.

        Args:
            token: The JWT token to check

        Returns:
            True if token is in blacklist
        """
        try:
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM token_blacklist WHERE token_hash = ?",
                (token_hash,)
            )
            return cursor.fetchone() is not None
        except Exception:
            return False

    def load_blacklisted_token_hashes(self: "DatabaseManager") -> Set[str]:
        """
        Load all non-expired blacklisted token hashes.

        Returns:
            Set of token hashes that are still blacklisted
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT token_hash FROM token_blacklist WHERE expires_at > ?",
                (time.time(),)
            )
            return {row[0] for row in cursor.fetchall()}
        except Exception:
            return set()

    def cleanup_expired_blacklist(self: "DatabaseManager") -> int:
        """
        Remove expired tokens from blacklist.

        Returns:
            Number of tokens removed
        """
        try:
            conn = self._ensure_connection()
            cursor = conn.cursor()

            # Remove tokens that expired more than 1 day ago
            cutoff = time.time() - 86400  # 24 hours buffer

            cursor.execute(
                "DELETE FROM token_blacklist WHERE expires_at < ?",
                (cutoff,)
            )
            conn.commit()
            return cursor.rowcount
        except Exception:
            return 0


__all__ = ["TokenBlacklistMixin"]
