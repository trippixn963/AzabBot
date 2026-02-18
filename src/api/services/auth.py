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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

import discord
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.api.config import get_api_config
from src.api.models.auth import TokenPayload, AuthenticatedUser, DiscordUserInfo
from src.utils.http import http_session, FAST_TIMEOUT


# =============================================================================
# Constants
# =============================================================================

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_TRANSCRIPT = "transcript"

# Login rate limiting
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW = 300  # 5 minutes

# Account lockout
LOCKOUT_THRESHOLD = 5  # consecutive failed attempts
LOCKOUT_DURATION = 900  # 15 minutes


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
    last_login_ip: Optional[str] = None
    last_login_agent: Optional[str] = None
    permissions: List[str] = field(default_factory=list)


@dataclass
class LoginAttempt:
    """Tracks login attempts for rate limiting."""

    count: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class FailedLoginTracker:
    """Tracks consecutive failed logins for account lockout."""

    consecutive_failures: int = 0
    locked_until: Optional[float] = None


class AuthService:
    """
    Handles authentication for the moderation dashboard.

    Features:
    - User registration with PIN
    - JWT token generation and validation
    - Moderator role verification
    - Token blacklisting (for logout) - persisted to database
    - Login rate limiting (per Discord ID)
    - Account lockout after consecutive failures
    """

    def __init__(self) -> None:
        self._config = get_api_config()
        self._blacklisted_token_hashes: Set[str] = set()  # In-memory cache of hashes
        self._login_attempts: Dict[int, LoginAttempt] = {}  # discord_id -> attempts
        self._failed_logins: Dict[int, FailedLoginTracker] = {}  # discord_id -> tracker
        self._load_blacklist_cache()

    # =========================================================================
    # User Management
    # =========================================================================

    def _get_user(self, discord_id: int) -> Optional[RegisteredUser]:
        """Get a user from database by discord_id."""
        try:
            db = get_db()
            row = db.fetchone(
                "SELECT * FROM dashboard_users WHERE discord_id = ?",
                (discord_id,)
            )
            if not row:
                return None
            permissions_str = row["permissions"] or ""
            return RegisteredUser(
                discord_id=row["discord_id"],
                pin_hash=row["pin_hash"],
                created_at=row["created_at"],
                last_login=row["last_login"],
                last_login_ip=row["last_login_ip"],
                last_login_agent=row["last_login_agent"],
                permissions=permissions_str.split(",") if permissions_str else [],
            )
        except Exception as e:
            logger.warning("Failed to Get Dashboard User", [
                ("User ID", str(discord_id)),
                ("Error", str(e)[:50]),
            ])
            return None

    def get_user(self, discord_id: int) -> Optional[RegisteredUser]:
        """Public method to get a user from database."""
        return self._get_user(discord_id)

    def _save_user(self, user: RegisteredUser) -> bool:
        """Save a user to database."""
        try:
            db = get_db()
            db.execute(
                """INSERT OR REPLACE INTO dashboard_users
                   (discord_id, pin_hash, created_at, last_login, last_login_ip, last_login_agent, permissions)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user.discord_id,
                    user.pin_hash,
                    user.created_at,
                    user.last_login,
                    user.last_login_ip,
                    user.last_login_agent,
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
        return self._get_user(discord_id) is not None

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
    # Login Rate Limiting
    # =========================================================================

    def check_login_rate_limit(self, discord_id: int) -> tuple[bool, Optional[int]]:
        """
        Check if login attempts are rate limited for a Discord ID.

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        now = time.time()
        attempt = self._login_attempts.get(discord_id)

        if not attempt:
            return True, None

        # Check if window has expired
        if now - attempt.window_start >= LOGIN_RATE_LIMIT_WINDOW:
            # Reset the window
            self._login_attempts[discord_id] = LoginAttempt(count=0, window_start=now)
            return True, None

        # Check if limit exceeded
        if attempt.count >= LOGIN_RATE_LIMIT_ATTEMPTS:
            retry_after = int(LOGIN_RATE_LIMIT_WINDOW - (now - attempt.window_start))
            return False, max(1, retry_after)

        return True, None

    def record_login_attempt(self, discord_id: int) -> None:
        """Record a login attempt for rate limiting."""
        now = time.time()
        attempt = self._login_attempts.get(discord_id)

        if not attempt or now - attempt.window_start >= LOGIN_RATE_LIMIT_WINDOW:
            # Start new window
            self._login_attempts[discord_id] = LoginAttempt(count=1, window_start=now)
        else:
            attempt.count += 1

    # =========================================================================
    # Account Lockout
    # =========================================================================

    def check_account_locked(self, discord_id: int) -> tuple[bool, Optional[datetime]]:
        """
        Check if an account is locked.

        Returns:
            Tuple of (is_locked, locked_until)
        """
        tracker = self._failed_logins.get(discord_id)
        if not tracker or not tracker.locked_until:
            return False, None

        now = time.time()
        if now >= tracker.locked_until:
            # Lock expired, clear it
            tracker.locked_until = None
            tracker.consecutive_failures = 0
            return False, None

        locked_until = datetime.utcfromtimestamp(tracker.locked_until)
        return True, locked_until

    def record_failed_login(self, discord_id: int) -> tuple[bool, Optional[datetime]]:
        """
        Record a failed login attempt.

        Returns:
            Tuple of (is_now_locked, locked_until)
        """
        tracker = self._failed_logins.get(discord_id)
        if not tracker:
            tracker = FailedLoginTracker()
            self._failed_logins[discord_id] = tracker

        tracker.consecutive_failures += 1

        logger.debug("Failed Login Recorded", [
            ("User ID", str(discord_id)),
            ("Consecutive", str(tracker.consecutive_failures)),
            ("Threshold", str(LOCKOUT_THRESHOLD)),
        ])

        # Check if lockout threshold reached
        if tracker.consecutive_failures >= LOCKOUT_THRESHOLD:
            tracker.locked_until = time.time() + LOCKOUT_DURATION
            locked_until = datetime.utcfromtimestamp(tracker.locked_until)

            logger.warning("Account Locked", [
                ("User ID", str(discord_id)),
                ("Failures", str(tracker.consecutive_failures)),
                ("Locked Until", locked_until.isoformat()),
            ])

            return True, locked_until

        return False, None

    def clear_failed_logins(self, discord_id: int) -> None:
        """Clear failed login tracking after successful login."""
        self._failed_logins.pop(discord_id, None)

    # =========================================================================
    # Discord User Fetch
    # =========================================================================

    async def fetch_discord_user(self, discord_id: int) -> Optional[DiscordUserInfo]:
        """
        Fetch user info from Discord API using bot token.

        Returns:
            DiscordUserInfo if found, None on error
        """
        config = get_config()

        url = f"https://discord.com/api/v10/users/{discord_id}"
        headers = {
            "Authorization": f"Bot {config.discord_token}",
        }

        try:
            async with http_session.get(url, headers=headers, timeout=FAST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Build avatar URL if avatar hash exists
                    avatar_url = None
                    if data.get("avatar"):
                        avatar_hash = data["avatar"]
                        ext = "gif" if avatar_hash.startswith("a_") else "png"
                        avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{ext}"

                    user_info = DiscordUserInfo(
                        discord_id=str(discord_id),
                        username=data.get("username", "Unknown"),
                        display_name=data.get("global_name"),
                        avatar=avatar_url,
                    )

                    logger.debug("Discord User Fetched", [
                        ("User ID", str(discord_id)),
                        ("Username", user_info.username),
                    ])

                    return user_info

                elif resp.status == 404:
                    logger.warning("Discord User Not Found", [
                        ("User ID", str(discord_id)),
                    ])
                    return None
                else:
                    logger.warning("Discord API Error", [
                        ("User ID", str(discord_id)),
                        ("Status", str(resp.status)),
                    ])
                    return None

        except Exception as e:
            logger.error("Discord User Fetch Failed", [
                ("User ID", str(discord_id)),
                ("Error", str(e)[:50]),
            ])
            return None

    # =========================================================================
    # Registration & Login
    # =========================================================================

    async def check_is_moderator(self, bot: Any, discord_id: int) -> bool:
        """Check if a Discord user is a member of the mod server."""
        try:
            config = get_config()

            if not config.mod_server_id:
                logger.warning("Mod Server ID Not Configured", [])
                return False

            guild = bot.get_guild(config.mod_server_id)
            if not guild:
                logger.warning("Mod Guild Not Accessible", [
                    ("Guild ID", str(config.mod_server_id)),
                ])
                return False

            # Check if user is a member of the mod server
            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                except discord.NotFound:
                    return False
                except discord.HTTPException:
                    return False

            return member is not None

        except Exception as e:
            logger.warning("Mod Check Failed", [
                ("User ID", str(discord_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    def register(self, discord_id: int, password: str) -> tuple[bool, str]:
        """
        Register a new dashboard user.

        Returns:
            Tuple of (success, message)
        """
        if self._get_user(discord_id) is not None:
            return False, "User already registered"

        if not password or len(password) < 4:
            return False, "Password must be at least 4 characters"

        user = RegisteredUser(
            discord_id=discord_id,
            pin_hash=self._hash_pin(password),
            created_at=time.time(),
        )

        if self._save_user(user):
            logger.tree("Dashboard User Registered", [
                ("Discord ID", str(discord_id)),
            ], emoji="📝")
            return True, "Registration successful"

        return False, "Failed to save registration"

    def _parse_user_agent(self, user_agent: str) -> str:
        """Parse user agent string to extract browser name."""
        if not user_agent:
            return "Unknown"

        ua_lower = user_agent.lower()

        # Check for common browsers (order matters - check specific first)
        if "edg" in ua_lower:
            return "Edge"
        elif "chrome" in ua_lower and "safari" in ua_lower:
            return "Chrome"
        elif "firefox" in ua_lower:
            return "Firefox"
        elif "safari" in ua_lower:
            return "Safari"
        elif "opera" in ua_lower or "opr" in ua_lower:
            return "Opera"
        elif "msie" in ua_lower or "trident" in ua_lower:
            return "Internet Explorer"

        # Check for mobile
        if "mobile" in ua_lower:
            if "android" in ua_lower:
                return "Android Browser"
            elif "iphone" in ua_lower or "ipad" in ua_lower:
                return "iOS Browser"
            return "Mobile Browser"

        return "Unknown"

    def login(
        self,
        discord_id: int,
        password: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[bool, Optional[str], Optional[datetime]]:
        """
        Authenticate a user and generate tokens.

        Returns:
            Tuple of (success, access_token, expires_at)
        """
        user = self._get_user(discord_id)
        if not user:
            return False, None, None

        if not self._verify_pin(password, user.pin_hash):
            return False, None, None

        # Update last login info
        user.last_login = time.time()
        user.last_login_ip = client_ip
        user.last_login_agent = self._parse_user_agent(user_agent) if user_agent else None
        self._save_user(user)

        # Generate token
        token, expires_at = self._generate_token(discord_id, user.permissions)

        logger.tree("Dashboard Login", [
            ("Discord ID", str(discord_id)),
            ("IP", client_ip or "Unknown"),
            ("Browser", user.last_login_agent or "Unknown"),
        ], emoji="🔐")

        return True, token, expires_at

    def logout(self, token: str) -> bool:
        """Invalidate a token (add to blacklist and persist to database)."""
        try:
            # Get token expiry from payload
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
                options={"verify_exp": False},  # Allow expired tokens to be blacklisted
            )
            expires_at = payload.get("exp", time.time() + 86400)  # Default 24h if no exp

            # Add to in-memory cache
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            self._blacklisted_token_hashes.add(token_hash)

            # Persist to database
            db = get_db()
            db.add_blacklisted_token(token, expires_at)

            return True
        except (KeyError, TypeError):
            # Still add to memory cache even if db fails
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            self._blacklisted_token_hashes.add(token_hash)
            return True

    def _load_blacklist_cache(self) -> None:
        """Load blacklisted token hashes from database into memory cache."""
        try:
            db = get_db()
            self._blacklisted_token_hashes = db.load_blacklisted_token_hashes()
            if self._blacklisted_token_hashes:
                logger.debug("Token Blacklist Loaded", [
                    ("Count", str(len(self._blacklisted_token_hashes))),
                ])
        except Exception as e:
            logger.warning("Failed to Load Token Blacklist", [
                ("Error", str(e)[:50]),
            ])
            self._blacklisted_token_hashes = set()

    # =========================================================================
    # Token Management
    # =========================================================================

    def _generate_token(
        self,
        discord_id: int,
        permissions: List[str],
        token_type: str = TOKEN_TYPE_ACCESS,
    ) -> tuple[str, datetime]:
        """Generate a JWT token."""
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self._config.jwt_expiry_hours)

        payload = {
            "sub": str(discord_id),  # JWT requires sub to be string
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

    def _is_token_blacklisted(self, token: str) -> bool:
        """Check if a token is blacklisted (using hash for security)."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token_hash in self._blacklisted_token_hashes

    def validate_token(self, token: str) -> Optional[int]:
        """
        Validate a token and return the user ID.

        Returns:
            Discord user ID if valid, None otherwise
        """
        if not token or self._is_token_blacklisted(token):
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

            sub = payload.get("sub")
            return int(sub) if sub else None

        except ExpiredSignatureError:
            return None
        except (InvalidTokenError, ValueError, TypeError):
            return None

    def get_token_payload(self, token: str) -> Optional[TokenPayload]:
        """Get the full token payload."""
        if not token or self._is_token_blacklisted(token):
            return None

        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
            )

            return TokenPayload(
                sub=int(payload["sub"]),  # Convert string back to int
                exp=datetime.fromtimestamp(payload["exp"]),
                iat=datetime.fromtimestamp(payload["iat"]),
                type=payload.get("type", "access"),
                permissions=payload.get("permissions", []),
            )

        except (ExpiredSignatureError, InvalidTokenError, ValueError, TypeError):
            return None

    # =========================================================================
    # Transcript Access Tokens
    # =========================================================================

    def generate_transcript_token(self, ticket_id: str) -> str:
        """
        Generate a non-expiring token for transcript access.
        This allows users to view their ticket transcript without logging in.

        Args:
            ticket_id: The ticket ID to generate a token for

        Returns:
            JWT token string for transcript access
        """
        try:
            payload = {
                "sub": ticket_id,
                "iat": datetime.utcnow(),
                "type": TOKEN_TYPE_TRANSCRIPT,
            }

            token = jwt.encode(
                payload,
                self._config.jwt_secret,
                algorithm=self._config.jwt_algorithm,
            )

            logger.debug("Transcript Token Generated", [
                ("Ticket ID", ticket_id),
            ])

            return token

        except Exception as e:
            logger.error("Transcript Token Generation Failed", [
                ("Ticket ID", ticket_id),
                ("Error", str(e)[:50]),
            ])
            raise

    def validate_transcript_token(self, token: str, ticket_id: str) -> bool:
        """
        Validate a transcript access token.

        Args:
            token: The JWT token from the URL
            ticket_id: The ticket ID being accessed

        Returns:
            True if token is valid for this ticket, False otherwise
        """
        if not token:
            return False

        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
                options={"verify_exp": False},  # Transcript tokens don't expire
            )

            # Check token type
            if payload.get("type") != TOKEN_TYPE_TRANSCRIPT:
                logger.debug("Transcript Token Invalid Type", [
                    ("Ticket ID", ticket_id),
                    ("Token Type", payload.get("type", "None")),
                ])
                return False

            # Check ticket ID matches
            if payload.get("sub") != ticket_id:
                logger.debug("Transcript Token ID Mismatch", [
                    ("Expected", ticket_id),
                    ("Token Sub", payload.get("sub", "None")),
                ])
                return False

            logger.debug("Transcript Token Valid", [
                ("Ticket ID", ticket_id),
            ])
            return True

        except InvalidTokenError as e:
            logger.debug("Transcript Token Invalid", [
                ("Ticket ID", ticket_id),
                ("Error", str(e)[:50]),
            ])
            return False
        except (ValueError, TypeError) as e:
            logger.warning("Transcript Token Parse Error", [
                ("Ticket ID", ticket_id),
                ("Error Type", type(e).__name__),
            ])
            return False

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
            registered = self._get_user(discord_id)

            # Convert last_login timestamp to UTC datetime
            last_login_at = None
            if registered and registered.last_login:
                last_login_at = datetime.fromtimestamp(registered.last_login, tz=timezone.utc)

            return AuthenticatedUser(
                discord_id=str(discord_id),
                username=user.name,
                display_name=user.display_name,
                avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
                is_admin=discord_id == bot.config.owner_id if hasattr(bot, 'config') else False,
                permissions=registered.permissions if registered else [],
                last_login_at=last_login_at,
                last_login_ip=registered.last_login_ip if registered else None,
                last_login_agent=registered.last_login_agent if registered else None,
            )
        except (discord.NotFound, discord.HTTPException, AttributeError):
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
