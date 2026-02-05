"""
Moderation Dashboard Authentication
====================================

Simple token-based authentication for the moderation dashboard.

Features:
- Password validation against environment variable
- Random token generation with 24-hour expiry
- Maximum 10 active sessions (FIFO eviction)
- In-memory token storage

Author: John Hamwi
"""

import secrets
import time
from dataclasses import dataclass
from typing import Optional

from src.core.config import get_config
from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
MAX_ACTIVE_SESSIONS = 10
TOKEN_LENGTH = 32


# =============================================================================
# Token Data
# =============================================================================

@dataclass
class TokenData:
    """Data associated with an authentication token."""
    token: str
    created_at: float
    expires_at: float


# =============================================================================
# Token Manager
# =============================================================================

class ModAuthManager:
    """
    Manages authentication tokens for the moderation dashboard.

    Tokens are stored in memory with automatic expiration.
    Maximum 10 active sessions - oldest tokens are evicted when limit is reached.
    """

    def __init__(self):
        self._tokens: dict[str, TokenData] = {}

    def verify_password(self, password: str) -> bool:
        """
        Verify the provided password against the configured password.

        Args:
            password: Password to verify.

        Returns:
            True if password matches, False otherwise.
        """
        config = get_config()
        if not config.mod_dashboard_password:
            logger.warning("Mod dashboard password not configured")
            return False

        # Use secrets.compare_digest for timing-safe comparison
        return secrets.compare_digest(
            password.encode('utf-8'),
            config.mod_dashboard_password.encode('utf-8')
        )

    def create_token(self) -> str:
        """
        Create a new authentication token.

        Handles session limit by evicting oldest token if necessary.

        Returns:
            The generated token string.
        """
        # Clean up expired tokens first
        self._cleanup_expired()

        # Evict oldest if at capacity
        while len(self._tokens) >= MAX_ACTIVE_SESSIONS:
            oldest_token = min(
                self._tokens.keys(),
                key=lambda t: self._tokens[t].created_at
            )
            del self._tokens[oldest_token]
            logger.info(f"Evicted oldest mod dashboard session (limit: {MAX_ACTIVE_SESSIONS})")

        # Generate new token
        token = secrets.token_urlsafe(TOKEN_LENGTH)
        now = time.time()

        self._tokens[token] = TokenData(
            token=token,
            created_at=now,
            expires_at=now + TOKEN_EXPIRY_SECONDS
        )

        logger.tree("Mod Dashboard Login", [
            ("Token", f"{token[:8]}..."),
            ("Expires", f"{TOKEN_EXPIRY_SECONDS // 3600}h"),
            ("Active Sessions", str(len(self._tokens))),
        ], emoji="🔐")

        return token

    def validate_token(self, token: str) -> bool:
        """
        Validate an authentication token.

        Args:
            token: Token to validate.

        Returns:
            True if token is valid and not expired, False otherwise.
        """
        if not token:
            return False

        token_data = self._tokens.get(token)
        if not token_data:
            return False

        # Check expiration
        if time.time() > token_data.expires_at:
            del self._tokens[token]
            return False

        return True

    def revoke_token(self, token: str) -> bool:
        """
        Revoke an authentication token (logout).

        Args:
            token: Token to revoke.

        Returns:
            True if token was revoked, False if it didn't exist.
        """
        if token in self._tokens:
            del self._tokens[token]
            logger.info("Mod dashboard session revoked")
            return True
        return False

    def extend_token(self, token: str) -> bool:
        """
        Extend a token's expiration time (refresh on activity).

        Args:
            token: Token to extend.

        Returns:
            True if token was extended, False if invalid.
        """
        if not self.validate_token(token):
            return False

        self._tokens[token].expires_at = time.time() + TOKEN_EXPIRY_SECONDS
        return True

    def _cleanup_expired(self) -> None:
        """Remove all expired tokens from storage."""
        now = time.time()
        expired = [
            token for token, data in self._tokens.items()
            if now > data.expires_at
        ]
        for token in expired:
            del self._tokens[token]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired mod dashboard sessions")

    def get_active_session_count(self) -> int:
        """Get the number of active sessions."""
        self._cleanup_expired()
        return len(self._tokens)


# =============================================================================
# Global Instance
# =============================================================================

_auth_manager: Optional[ModAuthManager] = None


def get_auth_manager() -> ModAuthManager:
    """Get the global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = ModAuthManager()
    return _auth_manager


# =============================================================================
# Helper Functions
# =============================================================================

def extract_bearer_token(authorization_header: Optional[str]) -> Optional[str]:
    """
    Extract token from Authorization header.

    Args:
        authorization_header: The Authorization header value (e.g., "Bearer token123").

    Returns:
        The extracted token, or None if header is invalid.
    """
    if not authorization_header:
        return None

    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "ModAuthManager",
    "get_auth_manager",
    "extract_bearer_token",
    "TOKEN_EXPIRY_SECONDS",
    "MAX_ACTIVE_SESSIONS",
]
