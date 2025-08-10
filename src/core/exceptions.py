"""
SaydnayaBot - Core Exceptions Module
===================================

This module provides a comprehensive exception hierarchy for the SaydnayaBot application.
It defines structured error handling with specific exception types for different
error scenarios, enabling better error tracking, logging, and recovery.

The exception hierarchy follows Python best practices with clear inheritance
structure and proper error context preservation. Each exception type includes
relevant context information to aid in debugging and error handling.

Exception Categories:
- Configuration errors (missing, invalid, etc.)
- Service errors (initialization, availability, AI-specific)
- Discord API errors (permissions, rate limits, etc.)
- Database errors (connection, query, etc.)
- Security errors (authentication, authorization, rate limiting)
- Validation errors (input validation, required fields)

All exceptions inherit from SaydnayaBotException which provides common
functionality for error context and logging.
"""

from typing import Any, Dict, Optional


class SaydnayaBotException(Exception):
    """
    Base exception for all SaydnayaBot-specific errors.
    
    This is the root exception from which all other bot exceptions inherit.
    It provides common functionality for error context, logging, and
    structured error reporting throughout the application.
    
    Attributes:
        message: Human-readable error message
        context: Additional context information about the error (user_id, channel_id, etc.)
        error_code: Optional error code for programmatic handling and categorization
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ):
        """
        Initialize the base exception with error details.
        
        Args:
            message: Human-readable error description
            context: Additional context information (user_id, channel_id, etc.)
            error_code: Optional error code for programmatic handling
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.error_code = error_code

    def __str__(self) -> str:
        """Return string representation of the exception with error code if available."""
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def __repr__(self) -> str:
        """Return detailed representation of the exception for debugging."""
        return f"{self.__class__.__name__}(message='{self.message}', context={self.context}, error_code='{self.error_code}')"


# =============================================================================
# Configuration Exceptions
# =============================================================================


class ConfigurationError(SaydnayaBotException):
    """
    Base exception for configuration-related errors.
    
    Raised when there are issues with application configuration including
    missing required values, invalid settings, or configuration file problems.
    """

    def __init__(self, message: str, config_key: Optional[str] = None, **kwargs):
        """
        Initialize configuration error with context.
        
        Args:
            message: Error description
            config_key: The configuration key that caused the error
        """
        context = kwargs.get("context", {})
        if config_key:
            context["config_key"] = config_key
        super().__init__(message, context, kwargs.get("error_code"))


class MissingConfigurationError(ConfigurationError):
    """
    Raised when required configuration is missing or empty.
    
    This exception is used when a configuration key that is marked as required
    is not found in any configuration source (environment, .env file, etc.).
    """

    def __init__(self, config_key: str, **kwargs):
        """
        Initialize missing configuration error.
        
        Args:
            config_key: The missing configuration key
        """
        message = f"Required configuration key '{config_key}' is missing or empty"
        super().__init__(message, config_key, error_code="MISSING_CONFIG", **kwargs)


class InvalidConfigurationError(ConfigurationError):
    """
    Raised when configuration has invalid values or format.
    
    This exception is used when a configuration value exists but is invalid
    according to the defined validation rules or type requirements.
    """

    def __init__(self, config_key: str, value: Any, expected_type: str, **kwargs):
        """
        Initialize invalid configuration error.

        Args:
            config_key: The configuration key with invalid value
            value: The invalid value
            expected_type: What type was expected
        """
        message = f"Configuration key '{config_key}' has invalid value '{value}', expected {expected_type}"
        context = kwargs.get("context", {})
        context.update({"invalid_value": value, "expected_type": expected_type})
        super().__init__(
            message, config_key, context=context, error_code="INVALID_CONFIG", **kwargs
        )


# =============================================================================
# Service Exceptions
# =============================================================================


class ServiceError(SaydnayaBotException):
    """Base exception for service-related errors."""

    def __init__(self, service_name: str, message: str, **kwargs):
        """
        Initialize service error.

        Args:
            service_name: Name of the service that encountered the error
            message: Error description
        """
        context = kwargs.get("context", {})
        context["service_name"] = service_name
        full_message = f"Service '{service_name}': {message}"
        super().__init__(full_message, context, kwargs.get("error_code"))


class ServiceInitializationError(ServiceError):
    """Raised when a service fails to initialize properly."""

    def __init__(self, service_name: str, reason: str, **kwargs):
        """
        Initialize service initialization error.

        Args:
            service_name: Name of the service that failed to initialize
            reason: Reason for the initialization failure
        """
        message = f"Failed to initialize: {reason}"
        super().__init__(
            service_name, message, error_code="SERVICE_INIT_FAILED", **kwargs
        )


class ServiceUnavailableError(ServiceError):
    """Raised when a service is temporarily unavailable."""

    def __init__(
        self,
        service_name: str,
        reason: str = "Service temporarily unavailable",
        **kwargs,
    ):
        """
        Initialize service unavailable error.

        Args:
            service_name: Name of the unavailable service
            reason: Reason for unavailability
        """
        super().__init__(
            service_name, reason, error_code="SERVICE_UNAVAILABLE", **kwargs
        )


# =============================================================================
# AI Service Exceptions
# =============================================================================


class AIServiceError(ServiceError):
    """Base exception for AI service-related errors."""

    def __init__(self, message: str, **kwargs):
        """Initialize AI service error."""
        super().__init__("AIService", message, **kwargs)


class ExternalServiceError(ServiceError):
    """External service communication errors."""

    def __init__(self, service: str, operation: str, message: str):
        self.service = service
        self.operation = operation
        super().__init__(
            f"External service error in {service} during {operation}: {message}"
        )


class AIGenerationError(AIServiceError):
    """Raised when AI response generation fails."""

    def __init__(self, reason: str, user_input: Optional[str] = None, **kwargs):
        """
        Initialize AI generation error.

        Args:
            reason: Reason for generation failure
            user_input: The input that caused the failure
        """
        message = f"Failed to generate AI response: {reason}"
        context = kwargs.get("context", {})
        if user_input:
            context["user_input"] = user_input[:100]  # Limit for privacy
        super().__init__(
            message, context=context, error_code="AI_GENERATION_FAILED", **kwargs
        )


class AIQuotaExceededError(AIServiceError):
    """Raised when AI service quota is exceeded."""

    def __init__(self, **kwargs):
        """Initialize AI quota exceeded error."""
        message = "AI service quota exceeded"
        super().__init__(message, error_code="AI_QUOTA_EXCEEDED", **kwargs)


class AIInappropriateContentError(AIServiceError):
    """Raised when AI service refuses to generate content due to policy violations."""

    def __init__(self, content_type: str = "content", **kwargs):
        """
        Initialize AI inappropriate content error.

        Args:
            content_type: Type of content that was inappropriate
        """
        message = (
            f"AI service refused to generate {content_type} due to policy violations"
        )
        super().__init__(message, error_code="AI_CONTENT_POLICY_VIOLATION", **kwargs)


# =============================================================================
# Discord API Exceptions
# =============================================================================


class DiscordAPIError(SaydnayaBotException):
    """Base exception for Discord API-related errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, **kwargs):
        """
        Initialize Discord API error.

        Args:
            message: Error description
            status_code: HTTP status code if applicable
        """
        context = kwargs.get("context", {})
        if status_code:
            context["status_code"] = status_code
        super().__init__(
            f"Discord API Error: {message}", context, kwargs.get("error_code")
        )


class DiscordPermissionError(DiscordAPIError):
    """Raised when bot lacks required Discord permissions."""

    def __init__(
        self,
        permission: str,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        **kwargs,
    ):
        """
        Initialize Discord permission error.

        Args:
            permission: The missing permission
            guild_id: Guild where permission is missing
            channel_id: Channel where permission is missing
        """
        message = f"Missing permission: {permission}"
        context = kwargs.get("context", {})
        if guild_id:
            context["guild_id"] = guild_id
        if channel_id:
            context["channel_id"] = channel_id
        super().__init__(
            message, context=context, error_code="DISCORD_PERMISSION_DENIED", **kwargs
        )


class DiscordRateLimitError(DiscordAPIError):
    """Raised when Discord rate limits are hit."""

    def __init__(self, retry_after: float, **kwargs):
        """
        Initialize Discord rate limit error.

        Args:
            retry_after: Seconds to wait before retrying
        """
        message = f"Rate limited, retry after {retry_after} seconds"
        context = kwargs.get("context", {})
        context["retry_after"] = retry_after
        super().__init__(
            message,
            status_code=429,
            context=context,
            error_code="DISCORD_RATE_LIMITED",
            **kwargs,
        )


# =============================================================================
# Database Exceptions
# =============================================================================


class DatabaseError(SaydnayaBotException):
    """Base exception for database-related errors."""

    def __init__(self, message: str, operation: Optional[str] = None, **kwargs):
        """
        Initialize database error.

        Args:
            message: Error description
            operation: Database operation that failed
        """
        context = kwargs.get("context", {})
        if operation:
            context["operation"] = operation
        super().__init__(
            f"Database Error: {message}", context, kwargs.get("error_code")
        )


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails."""

    def __init__(self, reason: str, **kwargs):
        """
        Initialize database connection error.

        Args:
            reason: Reason for connection failure
        """
        message = f"Failed to connect to database: {reason}"
        super().__init__(message, error_code="DB_CONNECTION_FAILED", **kwargs)


class DatabaseQueryError(DatabaseError):
    """Raised when database query execution fails."""

    def __init__(self, query: str, reason: str, **kwargs):
        """
        Initialize database query error.

        Args:
            query: The query that failed (sanitized)
            reason: Reason for query failure
        """
        message = f"Query execution failed: {reason}"
        context = kwargs.get("context", {})
        context["query"] = query[:200]  # Limit query length for logging
        super().__init__(
            message, context=context, error_code="DB_QUERY_FAILED", **kwargs
        )


# =============================================================================
# Security Exceptions
# =============================================================================


class SecurityError(SaydnayaBotException):
    """Base exception for security-related errors."""

    def __init__(
        self, message: str, security_context: Optional[Dict[str, Any]] = None, **kwargs
    ):
        """
        Initialize security error.

        Args:
            message: Error description
            security_context: Security-related context (user_id, IP, etc.)
        """
        context = kwargs.get("context", {})
        if security_context:
            context.update(security_context)
        super().__init__(
            f"Security Error: {message}", context, kwargs.get("error_code")
        )


class AuthenticationError(SecurityError):
    """Raised when authentication fails."""

    def __init__(self, user_id: Optional[int] = None, **kwargs):
        """
        Initialize authentication error.

        Args:
            user_id: User ID that failed authentication
        """
        message = "Authentication failed"
        security_context = {}
        if user_id:
            security_context["user_id"] = user_id
        super().__init__(message, security_context, error_code="AUTH_FAILED", **kwargs)


class AuthorizationError(SecurityError):
    """Raised when authorization fails."""

    def __init__(self, user_id: int, required_permission: str, **kwargs):
        """
        Initialize authorization error.

        Args:
            user_id: User ID that lacks permission
            required_permission: Permission that was required
        """
        message = f"User lacks required permission: {required_permission}"
        security_context = {
            "user_id": user_id,
            "required_permission": required_permission,
        }
        super().__init__(
            message, security_context, error_code="AUTHORIZATION_DENIED", **kwargs
        )


class RateLimitExceededError(SecurityError):
    """Raised when user exceeds rate limits."""

    def __init__(self, user_id: int, limit_type: str, retry_after: float, **kwargs):
        """
        Initialize rate limit exceeded error.

        Args:
            user_id: User ID that exceeded the limit
            limit_type: Type of rate limit exceeded
            retry_after: Seconds until user can try again
        """
        message = (
            f"Rate limit exceeded for {limit_type}, retry after {retry_after} seconds"
        )
        security_context = {
            "user_id": user_id,
            "limit_type": limit_type,
            "retry_after": retry_after,
        }
        super().__init__(
            message, security_context, error_code="RATE_LIMIT_EXCEEDED", **kwargs
        )


# =============================================================================
# Validation Exceptions
# =============================================================================


class ValidationError(SaydnayaBotException):
    """Base exception for validation-related errors."""

    def __init__(
        self, message: str, field: Optional[str] = None, value: Any = None, **kwargs
    ):
        """
        Initialize validation error.

        Args:
            message: Error description
            field: Field that failed validation
            value: Value that failed validation
        """
        context = kwargs.get("context", {})
        if field:
            context["field"] = field
        if value is not None:
            context["value"] = str(value)[:100]  # Limit for privacy
        super().__init__(
            f"Validation Error: {message}", context, kwargs.get("error_code")
        )


class InvalidInputError(ValidationError):
    """Raised when user input is invalid."""

    def __init__(self, field: str, value: Any, reason: str, **kwargs):
        """
        Initialize invalid input error.

        Args:
            field: Field with invalid input
            value: Invalid value
            reason: Why the value is invalid
        """
        message = f"Invalid {field}: {reason}"
        super().__init__(message, field, value, error_code="INVALID_INPUT", **kwargs)


class RequiredFieldError(ValidationError):
    """Raised when required field is missing."""

    def __init__(self, field: str, **kwargs):
        """
        Initialize required field error.

        Args:
            field: Required field that is missing
        """
        message = f"Required field '{field}' is missing"
        super().__init__(message, field, error_code="REQUIRED_FIELD_MISSING", **kwargs)
