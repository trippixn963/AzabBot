"""
AzabBot - Auth Service
======================

JWT-based authentication service for the API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass, field

import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from src.core.logger import logger
from src.core.database import get_db
from src.api.config import get_api_config
from src.api.models.auth import TokenPayload, AuthenticatedUser


# =============================================================================
# Constants
# =============================================================================

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


# =============================================================================
# Auth Service
# =============================================================================

@dataclass
class RegisteredUser:
    """A registered dashboard user."""

    discord_id: int
    pin_hash: str
    created_at: float
    last_login: Optional[float] = None
    permissions: list[str] = field(default_factory=list)


class AuthService:
    """
    Handles authentication for the moderation dashboard.

    Features:
    - User registration with PIN
    - JWT token generation and validation
    - Moderator role verification
    - Token blacklisting (for logout)
    """

    def __init__(self):
        self._config = get_api_config()
        self._users: dict[int, RegisteredUser] = {}  # discord_id -> user
        self._blacklisted_tokens: set[str] = set()
        self._load_users()

    # =========================================================================
    # User Management
    # =========================================================================

    def _load_users(self) -> None:
        """Load registered users from database."""
        try:
            db = get_db()
            rows = db.fetchall("SELECT * FROM dashboard_users")
            for row in rows:
                user = RegisteredUser(
                    discord_id=row["discord_id"],
                    pin_hash=row["pin_hash"],
                    created_at=row["created_at"],
                    last_login=row.get("last_login"),
                    permissions=row.get("permissions", "").split(",") if row.get("permissions") else [],
                )
                self._users[user.discord_id] = user
            logger.debug("Dashboard Users Loaded", [("Count", str(len(self._users)))])
        except Exception as e:
            logger.warning("Failed to Load Dashboard Users", [("Error", str(e)[:50])])

    def _save_user(self, user: RegisteredUser) -> bool:
        """Save a user to database."""
        try:
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO dashboard_users
                   (discord_id, pin_hash, created_at, last_login, permissions)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    user.discord_id,
                    user.pin_hash,
                    user.created_at,
                    user.last_login,
                    ",".join(user.permissions),
                )
            )
            return True
        except Exception as e:
            logger.error("Failed to Save Dashboard User", [
                ("User ID", str(user.discord_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    def user_exists(self, discord_id: int) -> bool:
        """Check if a user is registered."""
        return discord_id in self._users

    def _hash_pin(self, pin: str, salt: Optional[str] = None) -> str:
        """Hash a PIN with salt."""
        if salt is None:
            salt = secrets.token_hex(16)
        combined = f"{salt}:{pin}"
        hashed = hashlib.sha256(combined.encode()).hexdigest()
        return f"{salt}:{hashed}"

    def _verify_pin(self, pin: str, stored_hash: str) -> bool:
        """Verify a PIN against stored hash."""
        try:
            salt, _ = stored_hash.split(":", 1)
            new_hash = self._hash_pin(pin, salt)
            return secrets.compare_digest(new_hash, stored_hash)
        except ValueError:
            return False

    # =========================================================================
    # Registration & Login
    # =========================================================================

    async def check_is_moderator(self, bot: Any, discord_id: int) -> bool:
        """Check if a Discord user has the moderator role."""
        try:
            from src.core.config import get_config
            config = get_config()

            if not config.logging_guild_id:
                return False

            guild = bot.get_guild(config.logging_guild_id)
            if not guild:
                return False

            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                except Exception:
                    return False

            # Check for mod role
            if config.moderation_role_id:
                for role in member.roles:
                    if role.id == config.moderation_role_id:
                        return True

            # Check for admin permission
            if member.guild_permissions.administrator:
                return True

            # Check owner
            if discord_id == config.owner_id:
                return True

            return False

        except Exception as e:
            logger.warning("Mod Check Failed", [
                ("User ID", str(discord_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    def register(self, discord_id: int, pin: str) -> tuple[bool, str]:
        """
        Register a new dashboard user.

        Returns:
            Tuple of (success, message)
        """
        if discord_id in self._users:
            return False, "User already registered"

        if not pin or len(pin) < 4:
            return False, "PIN must be at least 4 characters"

        user = RegisteredUser(
            discord_id=discord_id,
            pin_hash=self._hash_pin(pin),
            created_at=time.time(),
        )

        if self._save_user(user):
            self._users[discord_id] = user
            logger.tree("Dashboard User Registered", [
                ("Discord ID", str(discord_id)),
            ], emoji="📝")
            return True, "Registration successful"

        return False, "Failed to save registration"

    def login(self, discord_id: int, pin: str) -> tuple[bool, Optional[str], Optional[datetime]]:
        """
        Authenticate a user and generate tokens.

        Returns:
            Tuple of (success, access_token, expires_at)
        """
        if discord_id not in self._users:
            return False, None, None

        user = self._users[discord_id]

        if not self._verify_pin(pin, user.pin_hash):
            return False, None, None

        # Update last login
        user.last_login = time.time()
        self._save_user(user)

        # Generate token
        token, expires_at = self._generate_token(discord_id, user.permissions)

        logger.tree("Dashboard Login", [
            ("Discord ID", str(discord_id)),
        ], emoji="🔐")

        return True, token, expires_at

    def logout(self, token: str) -> bool:
        """Invalidate a token (add to blacklist)."""
        self._blacklisted_tokens.add(token)
        return True

    # =========================================================================
    # Token Management
    # =========================================================================

    def _generate_token(
        self,
        discord_id: int,
        permissions: list[str],
        token_type: str = TOKEN_TYPE_ACCESS,
    ) -> tuple[str, datetime]:
        """Generate a JWT token."""
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self._config.jwt_expiry_hours)

        payload = {
            "sub": discord_id,
            "iat": now,
            "exp": expires_at,
            "type": token_type,
            "permissions": permissions,
        }

        token = jwt.encode(
            payload,
            self._config.jwt_secret,
            algorithm=self._config.jwt_algorithm,
        )

        return token, expires_at

    def validate_token(self, token: str) -> Optional[int]:
        """
        Validate a token and return the user ID.

        Returns:
            Discord user ID if valid, None otherwise
        """
        if not token or token in self._blacklisted_tokens:
            return None

        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
            )

            # Check token type
            if payload.get("type") != TOKEN_TYPE_ACCESS:
                return None

            return payload.get("sub")

        except ExpiredSignatureError:
            return None
        except InvalidTokenError:
            return None

    def get_token_payload(self, token: str) -> Optional[TokenPayload]:
        """Get the full token payload."""
        if not token or token in self._blacklisted_tokens:
            return None

        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
            )

            return TokenPayload(
                sub=payload["sub"],
                exp=datetime.fromtimestamp(payload["exp"]),
                iat=datetime.fromtimestamp(payload["iat"]),
                type=payload.get("type", "access"),
                permissions=payload.get("permissions", []),
            )

        except (ExpiredSignatureError, InvalidTokenError):
            return None

    # =========================================================================
    # User Info
    # =========================================================================

    async def get_authenticated_user(
        self,
        bot: Any,
        discord_id: int,
    ) -> Optional[AuthenticatedUser]:
        """Get authenticated user info from Discord."""
        try:
            user = await bot.fetch_user(discord_id)
            registered = self._users.get(discord_id)

            return AuthenticatedUser(
                discord_id=discord_id,
                username=user.name,
                display_name=user.display_name,
                avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
                is_admin=discord_id == bot.config.owner_id if hasattr(bot, 'config') else False,
                permissions=registered.permissions if registered else [],
            )
        except Exception:
            return None


# =============================================================================
# Singleton
# =============================================================================

_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the auth service singleton."""
    global _service
    if _service is None:
        _service = AuthService()
    return _service


__all__ = ["AuthService", "get_auth_service", "RegisteredUser"]
