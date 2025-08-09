"""Tests for security module."""

import time

import pytest

from src.core.exceptions import (
    AuthorizationError,
    InvalidInputError,
    RateLimitExceededError,
)
from src.core.security import (
    AccessController,
    PermissionLevel,
    RateLimitConfig,
    RateLimiter,
    SecurityContext,
    SecurityManager,
    SecurityValidator,
    get_security_manager,
)


class TestRateLimiter:
    """Test cases for RateLimiter class."""

    def test_rate_limiter_basic(self):
        """Test basic rate limiting functionality."""
        limiter = RateLimiter()
        config = RateLimitConfig(max_requests=3, time_window=60)

        # First 3 requests should succeed
        for i in range(3):
            assert limiter.check_rate_limit(123, "test_limit", config) is True

        # 4th request should fail
        with pytest.raises(RateLimitExceededError):
            limiter.check_rate_limit(123, "test_limit", config)

    def test_rate_limiter_time_window(self):
        """Test rate limiter respects time window."""
        limiter = RateLimiter()
        config = RateLimitConfig(
            max_requests=1, time_window=1
        )  # 1 req per second

        # First request succeeds
        assert limiter.check_rate_limit(456, "test_limit", config) is True

        # Immediate second request fails
        with pytest.raises(RateLimitExceededError):
            limiter.check_rate_limit(456, "test_limit", config)

        # After waiting, request succeeds
        time.sleep(1.1)
        assert limiter.check_rate_limit(456, "test_limit", config) is True

    def test_rate_limiter_burst_allowance(self):
        """Test rate limiter burst functionality."""
        limiter = RateLimiter()
        config = RateLimitConfig(
            max_requests=2, time_window=60, burst_allowance=3
        )

        # Burst allows extra requests initially
        for i in range(3):  # burst_allowance tokens
            assert limiter.check_rate_limit(789, "burst_test", config) is True

        # Next request should fail
        with pytest.raises(RateLimitExceededError):
            limiter.check_rate_limit(789, "burst_test", config)

    def test_rate_limiter_reset(self):
        """Test rate limiter reset functionality."""
        limiter = RateLimiter()
        config = RateLimitConfig(max_requests=1, time_window=60)

        # Use up the limit
        limiter.check_rate_limit(111, "reset_test", config)

        # Should be rate limited
        with pytest.raises(RateLimitExceededError):
            limiter.check_rate_limit(111, "reset_test", config)

        # Reset limits
        limiter.reset_user_limits(111)

        # Should work again
        assert limiter.check_rate_limit(111, "reset_test", config) is True


class TestSecurityValidator:
    """Test cases for SecurityValidator class."""

    def test_validate_user_input_basic(self):
        """Test basic input validation."""
        validator = SecurityValidator()

        # Valid input
        result = validator.validate_user_input("Hello World", max_length=100)
        assert result == "Hello World"

        # Input with whitespace
        result = validator.validate_user_input("  Hello  ", max_length=100)
        assert result == "Hello"

    def test_validate_user_input_length(self):
        """Test input length validation."""
        validator = SecurityValidator()

        with pytest.raises(InvalidInputError, match="exceeds maximum length"):
            validator.validate_user_input("a" * 101, max_length=100)

    def test_validate_user_input_null_bytes(self):
        """Test null byte detection."""
        validator = SecurityValidator()

        with pytest.raises(InvalidInputError, match="contains null bytes"):
            validator.validate_user_input("Hello\x00World")

    def test_validate_user_input_html_escaping(self):
        """Test HTML escaping."""
        validator = SecurityValidator()

        result = validator.validate_user_input("<script>alert('xss')</script>")
        assert "&lt;script&gt;" in result
        assert "&lt;/script&gt;" in result
        assert "<script>" not in result

    def test_validate_discord_id(self):
        """Test Discord ID validation."""
        validator = SecurityValidator()

        # Valid ID
        assert (
            validator.validate_discord_id("123456789012345678")
            == 123456789012345678
        )
        assert (
            validator.validate_discord_id(123456789012345678)
            == 123456789012345678
        )

        # Invalid IDs
        with pytest.raises(InvalidInputError, match="must be positive"):
            validator.validate_discord_id("-123")

        with pytest.raises(InvalidInputError, match="must be a valid integer"):
            validator.validate_discord_id("not_a_number")

        with pytest.raises(InvalidInputError, match="exceeds maximum"):
            validator.validate_discord_id(2**63)

    def test_validate_permission_level(self):
        """Test permission level validation."""
        validator = SecurityValidator()

        # Valid levels
        assert (
            validator.validate_permission_level("admin")
            == PermissionLevel.ADMIN
        )
        assert (
            validator.validate_permission_level("USER") == PermissionLevel.USER
        )

        # Invalid level
        with pytest.raises(InvalidInputError, match="must be one of"):
            validator.validate_permission_level("superadmin")


class TestAccessController:
    """Test cases for AccessController class."""

    def test_role_permissions(self):
        """Test role-based permissions."""
        controller = AccessController()

        # Set role permissions
        controller.set_role_permission(100, PermissionLevel.MODERATOR)
        controller.set_role_permission(200, PermissionLevel.ADMIN)

        # Test permission retrieval
        context = SecurityContext(user_id=1, roles=[100])
        assert (
            controller.get_user_permission_level(context)
            == PermissionLevel.MODERATOR
        )

        # Test higher role takes precedence
        context = SecurityContext(user_id=2, roles=[100, 200])
        assert (
            controller.get_user_permission_level(context)
            == PermissionLevel.ADMIN
        )

    def test_user_overrides(self):
        """Test user permission overrides."""
        controller = AccessController()

        # Set role and override
        controller.set_role_permission(100, PermissionLevel.USER)
        controller.set_user_override(123, PermissionLevel.ADMIN)

        # Override should take precedence
        context = SecurityContext(user_id=123, roles=[100])
        assert (
            controller.get_user_permission_level(context)
            == PermissionLevel.ADMIN
        )

    def test_feature_permissions(self):
        """Test feature permission checking."""
        controller = AccessController()
        controller.set_role_permission(100, PermissionLevel.MODERATOR)

        context = SecurityContext(user_id=1, roles=[100])

        # Should have access to user features
        assert controller.check_permission(context, "use_bot") is True

        # Should have access to moderator features
        assert (
            controller.check_permission(context, "moderate_channels") is True
        )

        # Should not have access to admin features
        assert controller.check_permission(context, "configure_bot") is False

        # Should not have access to owner features
        assert controller.check_permission(context, "shutdown_bot") is False

    def test_require_permission(self):
        """Test permission requirement enforcement."""
        controller = AccessController()
        context = SecurityContext(
            user_id=1, permission_level=PermissionLevel.USER
        )

        # Should succeed for user-level feature
        controller.require_permission(context, "use_bot")

        # Should raise for admin-level feature
        with pytest.raises(AuthorizationError):
            controller.require_permission(context, "configure_bot")


class TestSecurityManager:
    """Test cases for SecurityManager class."""

    def test_security_manager_creation(self):
        """Test SecurityManager initialization."""
        manager = SecurityManager()
        assert manager.rate_limiter is not None
        assert manager.validator is not None
        assert manager.access_controller is not None
        assert len(manager.rate_limits) > 0

    def test_create_security_context(self):
        """Test security context creation."""
        manager = SecurityManager()

        context = manager.create_security_context(
            user_id=123, guild_id=456, channel_id=789, roles=[100, 200]
        )

        assert context.user_id == 123
        assert context.guild_id == 456
        assert context.channel_id == 789
        assert len(context.roles) == 2

    def test_check_interaction_security_success(self):
        """Test successful security check."""
        manager = SecurityManager()

        # Set up permissions
        manager.access_controller.set_role_permission(
            100, PermissionLevel.USER
        )

        context = manager.create_security_context(user_id=123, roles=[100])

        # Should succeed
        assert (
            manager.check_interaction_security(context, "use_bot", "Hello bot")
            is True
        )

    def test_check_interaction_security_rate_limit(self):
        """Test security check with rate limiting."""
        manager = SecurityManager()

        # Set up permissions
        manager.access_controller.set_role_permission(
            100, PermissionLevel.USER
        )
        context = manager.create_security_context(user_id=123, roles=[100])

        # Use up rate limit
        for i in range(10):
            manager.check_interaction_security(context, "use_bot")

        # Next should fail
        with pytest.raises(RateLimitExceededError):
            manager.check_interaction_security(context, "use_bot")

    def test_check_interaction_security_invalid_input(self):
        """Test security check with invalid input."""
        manager = SecurityManager()
        context = manager.create_security_context(user_id=123)

        # Invalid input should fail
        with pytest.raises(InvalidInputError):
            manager.check_interaction_security(
                context, "test", "Hello\x00World"
            )

    def test_security_event_logging(self):
        """Test security event logging."""
        manager = SecurityManager()

        # Generate some events
        context = manager.create_security_context(user_id=123)

        # This will log an authorization failure
        try:
            manager.check_interaction_security(context, "configure_bot")
        except AuthorizationError:
            pass

        # Check events were logged
        assert len(manager.security_events) > 0

        # Check event structure
        event = manager.security_events[-1]
        assert event["event_type"] == "permission_denied"
        assert event["user_id"] == 123

    def test_security_summary(self):
        """Test security summary generation."""
        manager = SecurityManager()

        # Generate some events
        context1 = manager.create_security_context(user_id=123)
        context2 = manager.create_security_context(user_id=456)

        manager._log_security_event("test_event", context1)
        manager._log_security_event("test_event", context2)

        # Get summary
        summary = manager.get_security_summary(hours=24)

        assert summary["total_events"] >= 2
        assert summary["unique_users"] >= 2
        assert "test_event" in summary["event_counts"]

    def test_global_security_manager(self):
        """Test global security manager instance."""
        manager1 = get_security_manager()
        manager2 = get_security_manager()

        assert manager1 is manager2  # Should be same instance
