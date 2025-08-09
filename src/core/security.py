# =============================================================================
# SaydnayaBot - Core Security Module
# =============================================================================
# Comprehensive security framework providing authentication, authorization,
# rate limiting, input validation, and security monitoring for the bot.
#
# This module implements security best practices including:
# - Role-based access control
# - Rate limiting with different strategies
# - Input sanitization and validation
# - Security event logging and monitoring
# - Protection against common attack vectors
# =============================================================================

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from src.core.exceptions import (
    AuthorizationError,
    InvalidInputError,
    RateLimitExceededError,
)


class PermissionLevel(Enum):
    """Permission levels for role-based access control."""

    GUEST = "guest"
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"
    OWNER = "owner"


@dataclass
class SecurityContext:
    """Security context for a user interaction."""

    user_id: int
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    permission_level: PermissionLevel = PermissionLevel.GUEST
    roles: List[int] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting rules."""

    max_requests: int
    time_window: int  # seconds
    burst_allowance: int = 0  # extra requests allowed in burst


class RateLimiter:
    """
    Flexible rate limiter with support for different limiting strategies.

    Supports:
    - Token bucket algorithm for burst handling
    - Sliding window rate limiting
    - Per-user and per-channel limits
    - Different limits for different permission levels
    """

    def __init__(self):
        """Initialize the rate limiter."""
        # Format: {limit_key: {user_id: deque of timestamps}}
        self._request_history: Dict[str, Dict[int, deque]] = defaultdict(
            lambda: defaultdict(deque)
        )

        # Token buckets for burst handling
        # Format: {limit_key: {user_id: {'tokens': int, 'last_refill': float}}}
        self._token_buckets: Dict[str, Dict[int, Dict[str, Union[int, float]]]] = (
            defaultdict(lambda: defaultdict(dict))
        )

    def check_rate_limit(
        self,
        user_id: int,
        limit_key: str,
        config: RateLimitConfig,
        context: Optional[SecurityContext] = None,
    ) -> bool:
        """
        Check if user is within rate limits.

        Args:
            user_id: User ID to check
            limit_key: Unique key for this rate limit type
            config: Rate limit configuration
            context: Additional security context

        Returns:
            True if within limits, False if rate limited

        Raises:
            RateLimitExceededError: If rate limit is exceeded
        """
        now = time.time()

        # Clean up old entries first
        self._cleanup_old_entries(limit_key, user_id, config.time_window, now)

        # Get user's request history
        user_history = self._request_history[limit_key][user_id]

        # Check sliding window limit
        if len(user_history) >= config.max_requests:
            retry_after = config.time_window - (now - user_history[0])
            raise RateLimitExceededError(
                user_id=user_id,
                limit_type=limit_key,
                retry_after=retry_after,
                context={"config": config.__dict__},
            )

        # Handle burst allowance with token bucket
        if config.burst_allowance > 0:
            if not self._check_token_bucket(user_id, limit_key, config, now):
                retry_after = self._calculate_token_refill_time(
                    user_id, limit_key, config, now
                )
                raise RateLimitExceededError(
                    user_id=user_id,
                    limit_type=f"{limit_key}_burst",
                    retry_after=retry_after,
                    context={"config": config.__dict__},
                )

        # Record this request
        user_history.append(now)
        return True

    def _cleanup_old_entries(
        self, limit_key: str, user_id: int, time_window: int, now: float
    ):
        """Remove entries older than the time window."""
        user_history = self._request_history[limit_key][user_id]
        cutoff = now - time_window

        while user_history and user_history[0] < cutoff:
            user_history.popleft()

    def _check_token_bucket(
        self, user_id: int, limit_key: str, config: RateLimitConfig, now: float
    ) -> bool:
        """Check and update token bucket for burst handling."""
        bucket = self._token_buckets[limit_key][user_id]

        # Initialize bucket if needed
        if "tokens" not in bucket:
            bucket["tokens"] = config.burst_allowance
            bucket["last_refill"] = now
            return True

        # Refill tokens based on time elapsed
        time_elapsed = now - bucket["last_refill"]
        tokens_to_add = int(time_elapsed * config.burst_allowance / config.time_window)

        if tokens_to_add > 0:
            bucket["tokens"] = min(
                config.burst_allowance, bucket["tokens"] + tokens_to_add
            )
            bucket["last_refill"] = now

        # Check if tokens available
        if bucket["tokens"] > 0:
            bucket["tokens"] -= 1
            return True

        return False

    def _calculate_token_refill_time(
        self, user_id: int, limit_key: str, config: RateLimitConfig, now: float
    ) -> float:
        """Calculate when next token will be available."""
        time_per_token = config.time_window / config.burst_allowance
        return time_per_token

    def reset_user_limits(self, user_id: int, limit_key: Optional[str] = None):
        """Reset rate limits for a user."""
        if limit_key:
            if limit_key in self._request_history:
                self._request_history[limit_key].pop(user_id, None)
            if limit_key in self._token_buckets:
                self._token_buckets[limit_key].pop(user_id, None)
        else:
            # Reset all limits for user
            for key_dict in self._request_history.values():
                key_dict.pop(user_id, None)
            for key_dict in self._token_buckets.values():
                key_dict.pop(user_id, None)


class SecurityValidator:
    """
    Input validation and sanitization for security purposes.

    Provides validation for common input types and protection against
    injection attacks, excessive input sizes, and malformed data.
    """

    def __init__(self):
        """Initialize the security validator."""
        # Patterns for potentially dangerous content
        self.dangerous_patterns = [
            r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>",  # Script tags
            r"javascript:",  # JavaScript URLs
            r"vbscript:",  # VBScript URLs
            r"on\w+\s*=",  # Event handlers
            r"@import",  # CSS imports
            r"expression\s*\(",  # CSS expressions
        ]

    def validate_user_input(
        self,
        input_data: str,
        max_length: int = 1000,
        allow_html: bool = False,
        field_name: str = "input",
    ) -> str:
        """
        Validate and sanitize user input.

        Args:
            input_data: Input to validate
            max_length: Maximum allowed length
            allow_html: Whether to allow HTML content
            field_name: Name of the field for error reporting

        Returns:
            Sanitized input data

        Raises:
            InvalidInputError: If input is invalid or dangerous
        """
        if not isinstance(input_data, str):
            raise InvalidInputError(field_name, input_data, "must be a string")

        # Check length
        if len(input_data) > max_length:
            raise InvalidInputError(
                field_name,
                f"Length: {len(input_data)}",
                f"exceeds maximum length of {max_length} characters",
            )

        # Check for null bytes
        if "\x00" in input_data:
            raise InvalidInputError(field_name, input_data, "contains null bytes")

        # Check for dangerous patterns if HTML not allowed
        if not allow_html:
            import re

            for pattern in self.dangerous_patterns:
                if re.search(pattern, input_data, re.IGNORECASE):
                    raise InvalidInputError(
                        field_name, input_data, "contains potentially dangerous content"
                    )

        # Basic sanitization
        sanitized = input_data.strip()

        # Remove or escape dangerous characters if needed
        if not allow_html:
            # Basic HTML escaping
            sanitized = (
                sanitized.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#x27;")
            )

        return sanitized

    def validate_discord_id(
        self, discord_id: Union[str, int], field_name: str = "discord_id"
    ) -> int:
        """
        Validate Discord ID format.

        Args:
            discord_id: Discord ID to validate
            field_name: Field name for error reporting

        Returns:
            Valid Discord ID as integer

        Raises:
            InvalidInputError: If Discord ID is invalid
        """
        try:
            id_int = int(discord_id)

            # Discord IDs are snowflakes, should be positive and within reasonable range
            if id_int <= 0:
                raise InvalidInputError(field_name, discord_id, "must be positive")

            # Discord snowflakes are 64-bit integers
            if id_int >= 2**63:
                raise InvalidInputError(
                    field_name, discord_id, "exceeds maximum Discord ID value"
                )

            return id_int

        except ValueError:
            raise InvalidInputError(
                field_name, discord_id, "must be a valid integer"
            ) from None

    def validate_permission_level(
        self, level: str, field_name: str = "permission_level"
    ) -> PermissionLevel:
        """
        Validate permission level.

        Args:
            level: Permission level string
            field_name: Field name for error reporting

        Returns:
            Valid PermissionLevel enum

        Raises:
            InvalidInputError: If permission level is invalid
        """
        try:
            return PermissionLevel(level.lower())
        except ValueError:
            valid_levels = [level.value for level in PermissionLevel]
            raise InvalidInputError(
                field_name, level, f"must be one of: {', '.join(valid_levels)}"
            ) from None


class AccessController:
    """
    Role-based access control system.

    Manages user permissions based on Discord roles and provides
    fine-grained access control for bot features.
    """

    def __init__(self):
        """Initialize the access controller."""
        # Role ID to permission level mapping
        self.role_permissions: Dict[int, PermissionLevel] = {}

        # User ID to permission level overrides
        self.user_overrides: Dict[int, PermissionLevel] = {}

        # Feature permission requirements
        self.feature_permissions: Dict[str, PermissionLevel] = {
            # Basic bot interaction
            "use_bot": PermissionLevel.USER,
            # Moderation features (if any)
            "moderate_channels": PermissionLevel.MODERATOR,
            # Administrative features
            "configure_bot": PermissionLevel.ADMIN,
            "manage_permissions": PermissionLevel.ADMIN,
            # Owner-only features
            "shutdown_bot": PermissionLevel.OWNER,
            "manage_security": PermissionLevel.OWNER,
        }

    def set_role_permission(self, role_id: int, permission_level: PermissionLevel):
        """Set permission level for a Discord role."""
        self.role_permissions[role_id] = permission_level

    def set_user_override(self, user_id: int, permission_level: PermissionLevel):
        """Set permission override for a specific user."""
        self.user_overrides[user_id] = permission_level

    def get_user_permission_level(self, context: SecurityContext) -> PermissionLevel:
        """
        Get the permission level for a user based on their roles and overrides.

        Args:
            context: Security context with user information

        Returns:
            User's effective permission level
        """
        # Check for user override first
        if context.user_id in self.user_overrides:
            return self.user_overrides[context.user_id]

        # Check roles for highest permission level
        highest_level = PermissionLevel.GUEST

        for role_id in context.roles:
            if role_id in self.role_permissions:
                role_level = self.role_permissions[role_id]
                if self._is_higher_permission(role_level, highest_level):
                    highest_level = role_level

        return highest_level

    def check_permission(
        self,
        context: SecurityContext,
        feature: str,
        required_level: Optional[PermissionLevel] = None,
    ) -> bool:
        """
        Check if user has permission for a feature.

        Args:
            context: Security context
            feature: Feature name to check
            required_level: Override required permission level

        Returns:
            True if user has permission, False otherwise
        """
        user_level = self.get_user_permission_level(context)

        if required_level:
            required = required_level
        else:
            required = self.feature_permissions.get(feature, PermissionLevel.USER)

        return self._is_permission_sufficient(user_level, required)

    def require_permission(
        self,
        context: SecurityContext,
        feature: str,
        required_level: Optional[PermissionLevel] = None,
    ):
        """
        Require user to have permission for a feature.

        Args:
            context: Security context
            feature: Feature name to check
            required_level: Override required permission level

        Raises:
            AuthorizationError: If user lacks required permission
        """
        if not self.check_permission(context, feature, required_level):
            required = required_level or self.feature_permissions.get(
                feature, PermissionLevel.USER
            )
            raise AuthorizationError(
                user_id=context.user_id,
                required_permission=f"{feature} (requires {required.value})",
            )

    def _is_higher_permission(
        self, level1: PermissionLevel, level2: PermissionLevel
    ) -> bool:
        """Check if level1 is higher than level2."""
        levels_order = [
            PermissionLevel.GUEST,
            PermissionLevel.USER,
            PermissionLevel.MODERATOR,
            PermissionLevel.ADMIN,
            PermissionLevel.OWNER,
        ]
        return levels_order.index(level1) > levels_order.index(level2)

    def _is_permission_sufficient(
        self, user_level: PermissionLevel, required_level: PermissionLevel
    ) -> bool:
        """Check if user level meets or exceeds required level."""
        levels_order = [
            PermissionLevel.GUEST,
            PermissionLevel.USER,
            PermissionLevel.MODERATOR,
            PermissionLevel.ADMIN,
            PermissionLevel.OWNER,
        ]
        return levels_order.index(user_level) >= levels_order.index(required_level)


class SecurityManager:
    """
    Central security manager coordinating all security components.

    Provides a unified interface for all security operations including
    authentication, authorization, rate limiting, and security monitoring.
    """

    def __init__(self):
        """Initialize the security manager."""
        self.rate_limiter = RateLimiter()
        self.validator = SecurityValidator()
        self.access_controller = AccessController()

        # Security event tracking
        self.security_events: List[Dict[str, Any]] = []
        self.max_events = 1000  # Keep last 1000 events

        # Predefined rate limit configurations
        self.rate_limits = {
            "normal_user": RateLimitConfig(
                max_requests=10, time_window=60, burst_allowance=3
            ),
            "prison_user": RateLimitConfig(
                max_requests=20, time_window=60, burst_allowance=5
            ),
            "moderator": RateLimitConfig(
                max_requests=50, time_window=60, burst_allowance=10
            ),
            "admin": RateLimitConfig(
                max_requests=100, time_window=60, burst_allowance=20
            ),
        }

    def create_security_context(
        self,
        user_id: int,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        roles: Optional[List[int]] = None,
    ) -> SecurityContext:
        """
        Create a security context for a user interaction.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            channel_id: Discord channel ID
            roles: List of user's role IDs

        Returns:
            SecurityContext object
        """
        context = SecurityContext(
            user_id=user_id, guild_id=guild_id, channel_id=channel_id, roles=roles or []
        )

        # Determine permission level
        context.permission_level = self.access_controller.get_user_permission_level(
            context
        )

        return context

    def check_interaction_security(
        self,
        context: SecurityContext,
        interaction_type: str,
        user_input: Optional[str] = None,
    ) -> bool:
        """
        Comprehensive security check for user interactions.

        Args:
            context: Security context
            interaction_type: Type of interaction
            user_input: User input to validate (if any)

        Returns:
            True if interaction is allowed

        Raises:
            SecurityError: If interaction is not allowed
        """
        # Validate input if provided
        if user_input:
            self.validator.validate_user_input(user_input, field_name=interaction_type)

        # Check rate limits
        rate_limit_key = self._get_rate_limit_key(context, interaction_type)
        rate_config = self._get_rate_limit_config(context)

        try:
            self.rate_limiter.check_rate_limit(
                user_id=context.user_id,
                limit_key=rate_limit_key,
                config=rate_config,
                context=context,
            )
        except RateLimitExceededError as e:
            self._log_security_event(
                "rate_limit_exceeded",
                context,
                {
                    "interaction_type": interaction_type,
                    "retry_after": e.context.get("retry_after", 0),
                },
            )
            raise

        # Check permissions
        try:
            self.access_controller.require_permission(context, interaction_type)
        except AuthorizationError as e:
            self._log_security_event(
                "permission_denied",
                context,
                {
                    "interaction_type": interaction_type,
                    "required_permission": e.context.get(
                        "required_permission", "unknown"
                    ),
                },
            )
            raise

        # Log successful interaction
        self._log_security_event(
            "interaction_allowed", context, {"interaction_type": interaction_type}
        )

        return True

    def _get_rate_limit_key(
        self, context: SecurityContext, interaction_type: str
    ) -> str:
        """Generate rate limit key based on context."""
        return f"{interaction_type}:{context.guild_id or 'dm'}:{context.channel_id or 'direct'}"

    def _get_rate_limit_config(self, context: SecurityContext) -> RateLimitConfig:
        """Get appropriate rate limit configuration for user."""
        level = context.permission_level

        if level == PermissionLevel.ADMIN or level == PermissionLevel.OWNER:
            return self.rate_limits["admin"]
        elif level == PermissionLevel.MODERATOR:
            return self.rate_limits["moderator"]
        else:
            # Check if this is a prison context (could be based on channel)
            # For now, use normal user limits
            return self.rate_limits["normal_user"]

    def _log_security_event(
        self,
        event_type: str,
        context: SecurityContext,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log security events for monitoring and analysis."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": context.user_id,
            "guild_id": context.guild_id,
            "channel_id": context.channel_id,
            "permission_level": context.permission_level.value,
            "details": details or {},
        }

        self.security_events.append(event)

        # Keep only last N events
        if len(self.security_events) > self.max_events:
            self.security_events = self.security_events[-self.max_events :]

        # Log to main logger for serious events
        if event_type in [
            "permission_denied",
            "rate_limit_exceeded",
            "security_violation",
        ]:
            from src.core.logger import log_warning

            log_warning(
                f"Security event: {event_type}",
                context={"user_id": context.user_id, "details": details},
            )

    def get_security_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get security event summary for the specified time period.

        Args:
            hours: Number of hours to look back

        Returns:
            Security summary dictionary
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent_events = [
            event
            for event in self.security_events
            if datetime.fromisoformat(event["timestamp"]) > cutoff
        ]

        # Count events by type
        event_counts = defaultdict(int)
        for event in recent_events:
            event_counts[event["event_type"]] += 1

        # Count unique users
        unique_users = {event["user_id"] for event in recent_events}

        return {
            "time_period_hours": hours,
            "total_events": len(recent_events),
            "unique_users": len(unique_users),
            "event_counts": dict(event_counts),
            "recent_events": recent_events[-10:],  # Last 10 events
        }


# =============================================================================
# Global Security Manager Instance
# =============================================================================

# Create global security manager
_global_security_manager = SecurityManager()


# Convenience functions for global access
def get_security_manager() -> SecurityManager:
    """Get the global security manager."""
    return _global_security_manager


def create_security_context(
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    roles: Optional[List[int]] = None,
) -> SecurityContext:
    """Create a security context."""
    return _global_security_manager.create_security_context(
        user_id, guild_id, channel_id, roles
    )


def check_interaction_security(
    context: SecurityContext, interaction_type: str, user_input: Optional[str] = None
) -> bool:
    """Check interaction security."""
    return _global_security_manager.check_interaction_security(
        context, interaction_type, user_input
    )
