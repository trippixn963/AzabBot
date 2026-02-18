"""
AzabBot - API Error System
==========================

Centralized error codes and exception handling for consistent API responses.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from enum import Enum
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
)


# =============================================================================
# Error Codes
# =============================================================================

class ErrorCode(str, Enum):
    """
    Centralized error codes for the API.

    Format: CATEGORY_SPECIFIC_ERROR

    Categories:
    - AUTH: Authentication/authorization errors
    - CASE: Moderation case errors
    - TICKET: Ticket system errors
    - APPEAL: Appeal system errors
    - USER: User-related errors
    - VALIDATION: Input validation errors
    - RATE_LIMIT: Rate limiting errors
    - SERVER: Server-side errors
    """

    # Authentication errors (401, 403)
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_REVOKED = "AUTH_TOKEN_REVOKED"
    AUTH_MISSING_TOKEN = "AUTH_MISSING_TOKEN"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_INSUFFICIENT_PERMISSIONS"
    AUTH_NOT_MODERATOR = "AUTH_NOT_MODERATOR"
    AUTH_ACCOUNT_LOCKED = "AUTH_ACCOUNT_LOCKED"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_OAUTH_FAILED = "AUTH_OAUTH_FAILED"

    # Case errors (404, 400, 409)
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    CASE_ALREADY_RESOLVED = "CASE_ALREADY_RESOLVED"
    CASE_ALREADY_APPEALED = "CASE_ALREADY_APPEALED"
    CASE_INVALID_TYPE = "CASE_INVALID_TYPE"
    CASE_INVALID_STATUS = "CASE_INVALID_STATUS"
    CASE_THREAD_NOT_FOUND = "CASE_THREAD_NOT_FOUND"
    CASE_TRANSCRIPT_NOT_FOUND = "CASE_TRANSCRIPT_NOT_FOUND"

    # Ticket errors (404, 400, 409)
    TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
    TICKET_ALREADY_CLOSED = "TICKET_ALREADY_CLOSED"
    TICKET_ALREADY_CLAIMED = "TICKET_ALREADY_CLAIMED"
    TICKET_NOT_CLAIMED = "TICKET_NOT_CLAIMED"
    TICKET_COOLDOWN_ACTIVE = "TICKET_COOLDOWN_ACTIVE"
    TICKET_THREAD_NOT_FOUND = "TICKET_THREAD_NOT_FOUND"
    TICKET_TRANSCRIPT_NOT_FOUND = "TICKET_TRANSCRIPT_NOT_FOUND"
    TICKET_INVALID_CATEGORY = "TICKET_INVALID_CATEGORY"

    # Appeal errors (404, 400, 409)
    APPEAL_NOT_FOUND = "APPEAL_NOT_FOUND"
    APPEAL_ALREADY_EXISTS = "APPEAL_ALREADY_EXISTS"
    APPEAL_ALREADY_RESOLVED = "APPEAL_ALREADY_RESOLVED"
    APPEAL_COOLDOWN_ACTIVE = "APPEAL_COOLDOWN_ACTIVE"
    APPEAL_NOT_ELIGIBLE = "APPEAL_NOT_ELIGIBLE"
    APPEAL_CASE_NOT_FOUND = "APPEAL_CASE_NOT_FOUND"

    # User errors (404, 400)
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_NOT_IN_GUILD = "USER_NOT_IN_GUILD"
    USER_NOT_MUTED = "USER_NOT_MUTED"
    USER_NOT_BANNED = "USER_NOT_BANNED"
    USER_ALREADY_MUTED = "USER_ALREADY_MUTED"
    USER_SELF_ACTION = "USER_SELF_ACTION"
    USER_HIGHER_ROLE = "USER_HIGHER_ROLE"

    # Ban errors (404, 400)
    BAN_NOT_FOUND = "BAN_NOT_FOUND"

    # Permission errors (403)
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # Bot errors (503)
    BOT_NOT_INITIALIZED = "BOT_NOT_INITIALIZED"

    # Validation errors (400, 422)
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_INVALID_DURATION = "VALIDATION_INVALID_DURATION"
    VALIDATION_INVALID_REASON = "VALIDATION_INVALID_REASON"
    VALIDATION_INVALID_ID = "VALIDATION_INVALID_ID"
    VALIDATION_MISSING_FIELD = "VALIDATION_MISSING_FIELD"
    VALIDATION_FIELD_TOO_LONG = "VALIDATION_FIELD_TOO_LONG"
    VALIDATION_INVALID_FORMAT = "VALIDATION_INVALID_FORMAT"

    # Rate limit errors (429)
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMIT_LOGIN_ATTEMPTS = "RATE_LIMIT_LOGIN_ATTEMPTS"

    # Server errors (500)
    SERVER_ERROR = "SERVER_ERROR"
    SERVER_DATABASE_ERROR = "SERVER_DATABASE_ERROR"
    SERVER_DISCORD_ERROR = "SERVER_DISCORD_ERROR"
    SERVER_EXTERNAL_API_ERROR = "SERVER_EXTERNAL_API_ERROR"

    # WebSocket errors
    WS_CONNECTION_FAILED = "WS_CONNECTION_FAILED"
    WS_AUTH_REQUIRED = "WS_AUTH_REQUIRED"
    WS_INVALID_MESSAGE = "WS_INVALID_MESSAGE"


# =============================================================================
# Error Messages
# =============================================================================

ERROR_MESSAGES: Dict[ErrorCode, str] = {
    # Auth
    ErrorCode.AUTH_INVALID_TOKEN: "Invalid or malformed authentication token",
    ErrorCode.AUTH_TOKEN_EXPIRED: "Authentication token has expired",
    ErrorCode.AUTH_TOKEN_REVOKED: "Authentication token has been revoked",
    ErrorCode.AUTH_MISSING_TOKEN: "Authentication token is required",
    ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS: "Insufficient permissions for this action",
    ErrorCode.AUTH_NOT_MODERATOR: "This action requires moderator privileges",
    ErrorCode.AUTH_ACCOUNT_LOCKED: "Account is temporarily locked due to failed login attempts",
    ErrorCode.AUTH_INVALID_CREDENTIALS: "Invalid credentials provided",
    ErrorCode.AUTH_OAUTH_FAILED: "Discord OAuth authentication failed",

    # Cases
    ErrorCode.CASE_NOT_FOUND: "Moderation case not found",
    ErrorCode.CASE_ALREADY_RESOLVED: "This case has already been resolved",
    ErrorCode.CASE_ALREADY_APPEALED: "This case already has a pending appeal",
    ErrorCode.CASE_INVALID_TYPE: "Invalid case type specified",
    ErrorCode.CASE_INVALID_STATUS: "Invalid case status specified",
    ErrorCode.CASE_THREAD_NOT_FOUND: "Case thread not found or was deleted",
    ErrorCode.CASE_TRANSCRIPT_NOT_FOUND: "Case transcript not found",

    # Tickets
    ErrorCode.TICKET_NOT_FOUND: "Support ticket not found",
    ErrorCode.TICKET_ALREADY_CLOSED: "This ticket has already been closed",
    ErrorCode.TICKET_ALREADY_CLAIMED: "This ticket has already been claimed by another staff member",
    ErrorCode.TICKET_NOT_CLAIMED: "This ticket has not been claimed yet",
    ErrorCode.TICKET_COOLDOWN_ACTIVE: "Please wait before creating another ticket",
    ErrorCode.TICKET_THREAD_NOT_FOUND: "Ticket thread not found or was deleted",
    ErrorCode.TICKET_TRANSCRIPT_NOT_FOUND: "Ticket transcript not found",
    ErrorCode.TICKET_INVALID_CATEGORY: "Invalid ticket category specified",

    # Appeals
    ErrorCode.APPEAL_NOT_FOUND: "Appeal not found",
    ErrorCode.APPEAL_ALREADY_EXISTS: "An appeal for this case already exists",
    ErrorCode.APPEAL_ALREADY_RESOLVED: "This appeal has already been resolved",
    ErrorCode.APPEAL_COOLDOWN_ACTIVE: "Please wait before submitting another appeal",
    ErrorCode.APPEAL_NOT_ELIGIBLE: "This case is not eligible for appeal",
    ErrorCode.APPEAL_CASE_NOT_FOUND: "The case for this appeal was not found",

    # Users
    ErrorCode.USER_NOT_FOUND: "User not found",
    ErrorCode.USER_NOT_IN_GUILD: "User is not a member of this server",
    ErrorCode.USER_NOT_MUTED: "User is not currently muted",
    ErrorCode.USER_NOT_BANNED: "User is not currently banned",
    ErrorCode.USER_ALREADY_MUTED: "User is already muted",
    ErrorCode.USER_SELF_ACTION: "You cannot perform this action on yourself",
    ErrorCode.USER_HIGHER_ROLE: "Cannot perform this action on a user with equal or higher role",

    # Bans
    ErrorCode.BAN_NOT_FOUND: "Ban record not found",

    # Permissions
    ErrorCode.PERMISSION_DENIED: "You do not have permission to perform this action",

    # Bot
    ErrorCode.BOT_NOT_INITIALIZED: "Bot is not initialized",

    # Validation
    ErrorCode.VALIDATION_FAILED: "Request validation failed",
    ErrorCode.VALIDATION_ERROR: "Request validation failed",
    ErrorCode.VALIDATION_INVALID_DURATION: "Invalid duration specified",
    ErrorCode.VALIDATION_INVALID_REASON: "Invalid or missing reason",
    ErrorCode.VALIDATION_INVALID_ID: "Invalid ID format",
    ErrorCode.VALIDATION_MISSING_FIELD: "Required field is missing",
    ErrorCode.VALIDATION_FIELD_TOO_LONG: "Field exceeds maximum length",
    ErrorCode.VALIDATION_INVALID_FORMAT: "Invalid data format",

    # Rate limiting
    ErrorCode.RATE_LIMIT_EXCEEDED: "Too many requests, please slow down",
    ErrorCode.RATE_LIMIT_LOGIN_ATTEMPTS: "Too many login attempts, please try again later",

    # Server
    ErrorCode.SERVER_ERROR: "An internal server error occurred",
    ErrorCode.SERVER_DATABASE_ERROR: "A database error occurred",
    ErrorCode.SERVER_DISCORD_ERROR: "Failed to communicate with Discord",
    ErrorCode.SERVER_EXTERNAL_API_ERROR: "External API request failed",

    # WebSocket
    ErrorCode.WS_CONNECTION_FAILED: "WebSocket connection failed",
    ErrorCode.WS_AUTH_REQUIRED: "WebSocket authentication required",
    ErrorCode.WS_INVALID_MESSAGE: "Invalid WebSocket message format",
}


# =============================================================================
# Default Status Codes
# =============================================================================

ERROR_STATUS_CODES: Dict[ErrorCode, int] = {
    # Auth - 401/403
    ErrorCode.AUTH_INVALID_TOKEN: HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_TOKEN_EXPIRED: HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_TOKEN_REVOKED: HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_MISSING_TOKEN: HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS: HTTP_403_FORBIDDEN,
    ErrorCode.AUTH_NOT_MODERATOR: HTTP_403_FORBIDDEN,
    ErrorCode.AUTH_ACCOUNT_LOCKED: HTTP_403_FORBIDDEN,
    ErrorCode.AUTH_INVALID_CREDENTIALS: HTTP_401_UNAUTHORIZED,
    ErrorCode.AUTH_OAUTH_FAILED: HTTP_401_UNAUTHORIZED,

    # Cases - 404/409
    ErrorCode.CASE_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.CASE_ALREADY_RESOLVED: HTTP_409_CONFLICT,
    ErrorCode.CASE_ALREADY_APPEALED: HTTP_409_CONFLICT,
    ErrorCode.CASE_INVALID_TYPE: HTTP_400_BAD_REQUEST,
    ErrorCode.CASE_INVALID_STATUS: HTTP_400_BAD_REQUEST,
    ErrorCode.CASE_THREAD_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.CASE_TRANSCRIPT_NOT_FOUND: HTTP_404_NOT_FOUND,

    # Tickets - 404/409
    ErrorCode.TICKET_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.TICKET_ALREADY_CLOSED: HTTP_409_CONFLICT,
    ErrorCode.TICKET_ALREADY_CLAIMED: HTTP_409_CONFLICT,
    ErrorCode.TICKET_NOT_CLAIMED: HTTP_400_BAD_REQUEST,
    ErrorCode.TICKET_COOLDOWN_ACTIVE: HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.TICKET_THREAD_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.TICKET_TRANSCRIPT_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.TICKET_INVALID_CATEGORY: HTTP_400_BAD_REQUEST,

    # Appeals - 404/409
    ErrorCode.APPEAL_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.APPEAL_ALREADY_EXISTS: HTTP_409_CONFLICT,
    ErrorCode.APPEAL_ALREADY_RESOLVED: HTTP_409_CONFLICT,
    ErrorCode.APPEAL_COOLDOWN_ACTIVE: HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.APPEAL_NOT_ELIGIBLE: HTTP_400_BAD_REQUEST,
    ErrorCode.APPEAL_CASE_NOT_FOUND: HTTP_404_NOT_FOUND,

    # Users - 404/400
    ErrorCode.USER_NOT_FOUND: HTTP_404_NOT_FOUND,
    ErrorCode.USER_NOT_IN_GUILD: HTTP_404_NOT_FOUND,
    ErrorCode.USER_NOT_MUTED: HTTP_400_BAD_REQUEST,
    ErrorCode.USER_NOT_BANNED: HTTP_400_BAD_REQUEST,
    ErrorCode.USER_ALREADY_MUTED: HTTP_409_CONFLICT,
    ErrorCode.USER_SELF_ACTION: HTTP_400_BAD_REQUEST,
    ErrorCode.USER_HIGHER_ROLE: HTTP_403_FORBIDDEN,

    # Bans - 404
    ErrorCode.BAN_NOT_FOUND: HTTP_404_NOT_FOUND,

    # Permissions - 403
    ErrorCode.PERMISSION_DENIED: HTTP_403_FORBIDDEN,

    # Bot - 503
    ErrorCode.BOT_NOT_INITIALIZED: 503,

    # Validation - 400/422
    ErrorCode.VALIDATION_FAILED: HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.VALIDATION_ERROR: HTTP_400_BAD_REQUEST,
    ErrorCode.VALIDATION_INVALID_DURATION: HTTP_400_BAD_REQUEST,
    ErrorCode.VALIDATION_INVALID_REASON: HTTP_400_BAD_REQUEST,
    ErrorCode.VALIDATION_INVALID_ID: HTTP_400_BAD_REQUEST,
    ErrorCode.VALIDATION_MISSING_FIELD: HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.VALIDATION_FIELD_TOO_LONG: HTTP_400_BAD_REQUEST,
    ErrorCode.VALIDATION_INVALID_FORMAT: HTTP_400_BAD_REQUEST,

    # Rate limit - 429
    ErrorCode.RATE_LIMIT_EXCEEDED: HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.RATE_LIMIT_LOGIN_ATTEMPTS: HTTP_429_TOO_MANY_REQUESTS,

    # Server - 500
    ErrorCode.SERVER_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.SERVER_DATABASE_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.SERVER_DISCORD_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.SERVER_EXTERNAL_API_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,

    # WebSocket - 400
    ErrorCode.WS_CONNECTION_FAILED: HTTP_400_BAD_REQUEST,
    ErrorCode.WS_AUTH_REQUIRED: HTTP_401_UNAUTHORIZED,
    ErrorCode.WS_INVALID_MESSAGE: HTTP_400_BAD_REQUEST,
}


# =============================================================================
# API Error Exception
# =============================================================================

class APIError(HTTPException):
    """
    Custom API exception with error codes.

    Usage:
        raise APIError(ErrorCode.CASE_NOT_FOUND)
        raise APIError(ErrorCode.VALIDATION_FAILED, details={"field": "reason"})
        raise APIError(ErrorCode.AUTH_ACCOUNT_LOCKED, status_code=423)
        raise APIError(ErrorCode.AUTH_MISSING_TOKEN, headers={"WWW-Authenticate": "Bearer"})
    """

    def __init__(
        self,
        code: ErrorCode,
        status_code: Optional[int] = None,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.error_code = code
        self.error_message = message or ERROR_MESSAGES.get(code, "An error occurred")
        self.error_details = details

        # Use default status code if not provided
        if status_code is None:
            status_code = ERROR_STATUS_CODES.get(code, HTTP_400_BAD_REQUEST)

        super().__init__(
            status_code=status_code,
            detail={
                "success": False,
                "error_code": code.value,
                "message": self.error_message,
                "details": details,
            },
            headers=headers,
        )


# =============================================================================
# Helper Functions
# =============================================================================

def error_response(
    code: ErrorCode,
    status_code: Optional[int] = None,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """
    Create a JSON error response without raising an exception.

    Useful for returning errors in exception handlers.
    """
    if status_code is None:
        status_code = ERROR_STATUS_CODES.get(code, HTTP_400_BAD_REQUEST)

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error_code": code.value,
            "message": message or ERROR_MESSAGES.get(code, "An error occurred"),
            "details": details,
        },
    )


def not_found(resource: str = "Resource") -> APIError:
    """Shorthand for 404 errors."""
    # Map resource name to appropriate error code
    resource_map = {
        "case": ErrorCode.CASE_NOT_FOUND,
        "ticket": ErrorCode.TICKET_NOT_FOUND,
        "appeal": ErrorCode.APPEAL_NOT_FOUND,
        "user": ErrorCode.USER_NOT_FOUND,
    }
    code = resource_map.get(resource.lower(), ErrorCode.CASE_NOT_FOUND)
    return APIError(code)


def forbidden(message: Optional[str] = None) -> APIError:
    """Shorthand for 403 errors."""
    return APIError(
        ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS,
        message=message,
    )


def bad_request(code: ErrorCode = ErrorCode.VALIDATION_FAILED, details: Optional[Dict[str, Any]] = None) -> APIError:
    """Shorthand for 400 errors."""
    return APIError(code, details=details)


__all__ = [
    "ErrorCode",
    "ERROR_MESSAGES",
    "ERROR_STATUS_CODES",
    "APIError",
    "error_response",
    "not_found",
    "forbidden",
    "bad_request",
]
