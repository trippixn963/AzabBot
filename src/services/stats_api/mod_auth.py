"""
Moderation Dashboard Authentication
====================================

Per-user authentication for the moderation dashboard.
Users must have the moderator role to register/login.

Author: John Hamwi
"""

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.core.database import get_db
from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
MAX_ACTIVE_SESSIONS = 50
TOKEN_LENGTH = 32


# =============================================================================
# Password Hashing
# =============================================================================

def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, hashed = stored_hash.split(":")
        check_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return secrets.compare_digest(hashed, check_hash)
    except ValueError:
        return False


# =============================================================================
# Token Data
# =============================================================================

@dataclass
class TokenData:
    """Data associated with an authentication token."""
    token: str
    discord_id: int
    created_at: float
    expires_at: float


# =============================================================================
# Token Manager
# =============================================================================

class ModAuthManager:
    """
    Manages authentication for the moderation dashboard.

    - Users register with Discord ID + password
    - Backend verifies they have moderator role before allowing registration
    - Tokens stored in memory with 24h expiry
    """

    def __init__(self):
        self._tokens: dict[str, TokenData] = {}

    async def check_is_moderator(self, bot: "AzabBot", discord_id: int) -> bool:
        """
        Check if a user has the moderator role in the Syrian server.

        Args:
            bot: The Discord bot instance.
            discord_id: The user's Discord ID.

        Returns:
            True if user has moderator role, False otherwise.
        """
        from src.core.config import get_config
        config = get_config()

        # Get the main guild
        guild_id = config.logging_guild_id
        if not guild_id:
            logger.warning("No logging_guild_id configured for mod dashboard auth")
            return False

        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"Could not find guild {guild_id} for mod dashboard auth")
            return False

        # Get the member
        try:
            member = guild.get_member(discord_id)
            if not member:
                member = await guild.fetch_member(discord_id)
        except Exception as e:
            logger.debug(f"Could not fetch member {discord_id}: {e}")
            return False

        if not member:
            return False

        # Check if they have mod role or are admin/owner
        from src.core.config import has_mod_role
        return has_mod_role(member)

    def user_exists(self, discord_id: int) -> bool:
        """Check if a user has registered."""
        db = get_db()
        row = db.fetchone(
            "SELECT 1 FROM mod_dashboard_users WHERE discord_id = ?",
            (discord_id,)
        )
        return row is not None

    def register_user(self, discord_id: int, password: str) -> bool:
        """
        Register a new user.

        Args:
            discord_id: The user's Discord ID.
            password: The password to set.

        Returns:
            True if registered, False if already exists.
        """
        if self.user_exists(discord_id):
            return False

        db = get_db()
        password_hash = hash_password(password)

        db.execute(
            "INSERT INTO mod_dashboard_users (discord_id, password_hash, created_at) VALUES (?, ?, ?)",
            (discord_id, password_hash, time.time())
        )

        logger.tree("Mod Dashboard User Registered", [
            ("Discord ID", str(discord_id)),
        ], emoji="🔐")

        return True

    def verify_user(self, discord_id: int, password: str) -> bool:
        """
        Verify a user's password.

        Args:
            discord_id: The user's Discord ID.
            password: The password to verify.

        Returns:
            True if password is correct, False otherwise.
        """
        db = get_db()
        row = db.fetchone(
            "SELECT password_hash FROM mod_dashboard_users WHERE discord_id = ?",
            (discord_id,)
        )

        if not row:
            return False

        return verify_password(password, row["password_hash"])

    def create_token(self, discord_id: int) -> str:
        """
        Create a new authentication token for a user.

        Args:
            discord_id: The user's Discord ID.

        Returns:
            The generated token string.
        """
        # Clean up expired tokens first
        self._cleanup_expired()

        # Evict oldest if at capacity
        while len(self._tokens) >= MAX_ACTIVE_SESSIONS:
            try:
                oldest_token = min(
                    self._tokens.keys(),
                    key=lambda t: self._tokens[t].created_at
                )
                del self._tokens[oldest_token]
            except (KeyError, ValueError):
                break  # Dict modified or empty

        # Generate new token
        token = secrets.token_urlsafe(TOKEN_LENGTH)
        now = time.time()

        self._tokens[token] = TokenData(
            token=token,
            discord_id=discord_id,
            created_at=now,
            expires_at=now + TOKEN_EXPIRY_SECONDS
        )

        logger.tree("Mod Dashboard Login", [
            ("Discord ID", str(discord_id)),
            ("Token", f"{token[:8]}..."),
            ("Expires", f"{TOKEN_EXPIRY_SECONDS // 3600}h"),
        ], emoji="🔐")

        return token

    def validate_token(self, token: str) -> Optional[int]:
        """
        Validate an authentication token.

        Args:
            token: Token to validate.

        Returns:
            Discord ID if valid, None otherwise.
        """
        if not token:
            return None

        token_data = self._tokens.get(token)
        if not token_data:
            return None

        # Check expiration
        if time.time() > token_data.expires_at:
            try:
                del self._tokens[token]
            except KeyError:
                pass  # Already removed
            return None

        return token_data.discord_id

    def revoke_token(self, token: str) -> bool:
        """Revoke an authentication token (logout)."""
        try:
            del self._tokens[token]
            return True
        except KeyError:
            return False

    def _cleanup_expired(self) -> None:
        """Remove all expired tokens from storage."""
        now = time.time()
        expired = [
            token for token, data in self._tokens.items()
            if now > data.expires_at
        ]
        for token in expired:
            try:
                del self._tokens[token]
            except KeyError:
                pass  # Already removed


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
    """Extract token from Authorization header."""
    if not authorization_header:
        return None

    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


__all__ = [
    "ModAuthManager",
    "get_auth_manager",
    "extract_bearer_token",
]
