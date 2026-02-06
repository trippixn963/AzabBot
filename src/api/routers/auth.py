"""
AzabBot - Auth Router
=====================

Authentication endpoints for dashboard access.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import (
    CheckModeratorRequest,
    CheckModeratorResponse,
    LoginRequest,
    RegisterRequest,
    AuthTokenResponse,
    TokenPayload,
    AuthenticatedUser,
)
from src.api.services.auth import get_auth_service


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _get_client_ip(request: Request) -> str:
    """Get client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/check-moderator", response_model=APIResponse[CheckModeratorResponse])
async def check_moderator(
    request_body: CheckModeratorRequest,
    request: Request,
    bot: Any = Depends(get_bot),
) -> APIResponse[CheckModeratorResponse]:
    """
    Check if a Discord user is a moderator.

    Used during registration flow to verify eligibility.
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)

    is_moderator = await auth_service.check_is_moderator(bot, request_body.discord_id)
    is_registered = auth_service.user_exists(request_body.discord_id)

    logger.debug("Mod Check", [
        ("User ID", str(request_body.discord_id)),
        ("Is Mod", str(is_moderator)),
        ("Registered", str(is_registered)),
        ("IP", client_ip),
    ])

    return APIResponse(
        success=True,
        data=CheckModeratorResponse(
            is_moderator=is_moderator,
            is_registered=is_registered,
        ),
    )


@router.post("/register", response_model=APIResponse[dict])
async def register(
    request_body: RegisterRequest,
    request: Request,
    bot: Any = Depends(get_bot),
) -> APIResponse[dict]:
    """
    Register a new dashboard user.

    Requires:
    - User must be a moderator in the Discord server
    - User must not already be registered
    - PIN must be at least 4 characters
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)

    # Verify moderator status
    is_moderator = await auth_service.check_is_moderator(bot, request_body.discord_id)
    if not is_moderator:
        logger.warning("Dashboard Register Denied", [
            ("User ID", str(request_body.discord_id)),
            ("Reason", "Not a moderator"),
            ("IP", client_ip),
        ])
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Only moderators can register for the dashboard",
        )

    # Attempt registration
    success, message = auth_service.register(request_body.discord_id, request_body.pin)

    if not success:
        logger.warning("Dashboard Register Failed", [
            ("User ID", str(request_body.discord_id)),
            ("Reason", message),
            ("IP", client_ip),
        ])
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=message,
        )

    logger.tree("Dashboard User Registered", [
        ("User ID", str(request_body.discord_id)),
        ("IP", client_ip),
    ], emoji="📝")

    return APIResponse(
        success=True,
        message=message,
        data={"registered": True},
    )


@router.post("/login", response_model=APIResponse[AuthTokenResponse])
async def login(
    request_body: LoginRequest,
    request: Request,
) -> APIResponse[AuthTokenResponse]:
    """
    Authenticate and receive an access token.

    Returns JWT token for subsequent API requests.
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)

    success, token, expires_at = auth_service.login(request_body.discord_id, request_body.pin)

    if not success or not token:
        logger.warning("Dashboard Login Failed", [
            ("User ID", str(request_body.discord_id)),
            ("Reason", "Invalid credentials"),
            ("IP", client_ip),
        ])
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    logger.tree("Dashboard Login", [
        ("User ID", str(request_body.discord_id)),
        ("IP", client_ip),
    ], emoji="🔐")

    return APIResponse(
        success=True,
        data=AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            expires_at=expires_at,
        ),
    )


@router.post("/logout", response_model=APIResponse[dict])
async def logout(
    request: Request,
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[dict]:
    """
    Logout and invalidate the current token.
    """
    client_ip = _get_client_ip(request)

    logger.debug("Dashboard Logout", [
        ("User ID", str(payload.sub)),
        ("IP", client_ip),
    ])

    return APIResponse(
        success=True,
        message="Logged out successfully",
        data={"logged_out": True},
    )


@router.get("/me", response_model=APIResponse[AuthenticatedUser])
async def get_current_user(
    payload: TokenPayload = Depends(require_auth),
    bot: Any = Depends(get_bot),
) -> APIResponse[AuthenticatedUser]:
    """
    Get the currently authenticated user's information.
    """
    auth_service = get_auth_service()

    user = await auth_service.get_authenticated_user(bot, payload.sub)

    if not user:
        logger.warning("Dashboard User Not Found", [
            ("User ID", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return APIResponse(success=True, data=user)


@router.post("/refresh", response_model=APIResponse[AuthTokenResponse])
async def refresh_token(
    request: Request,
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[AuthTokenResponse]:
    """
    Refresh the current token to extend the session.
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)

    # Get user permissions
    registered_user = auth_service._users.get(payload.sub)
    permissions = registered_user.permissions if registered_user else []

    # Generate new token
    token, expires_at = auth_service._generate_token(payload.sub, permissions)

    logger.debug("Dashboard Token Refresh", [
        ("User ID", str(payload.sub)),
        ("IP", client_ip),
    ])

    return APIResponse(
        success=True,
        data=AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            expires_at=expires_at,
        ),
    )


__all__ = ["router"]
