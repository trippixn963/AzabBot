"""
AzabBot - Auth Router
=====================

Authentication endpoints for dashboard access.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_423_LOCKED,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from src.core.config import get_config
from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import (
    CheckModeratorRequest,
    CheckModeratorResponse,
    DiscordUserInfo,
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
    Checks membership in the mod server guild (MODS_GUILD_ID).
    Returns user info if member.
    """
    auth_service = get_auth_service()
    config = get_config()
    client_ip = _get_client_ip(request)

    if not config.mod_server_id:
        logger.error("Mod Server ID Not Configured", [])
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mod server not configured",
        )

    guild = bot.get_guild(config.mod_server_id)
    if not guild:
        logger.error("Mod Guild Not Found", [
            ("Guild ID", str(config.mod_server_id)),
        ])
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mod server not accessible",
        )

    # Check if user is a member of the mod server
    member = guild.get_member(request_body.discord_id)
    if not member:
        try:
            member = await guild.fetch_member(request_body.discord_id)
        except discord.NotFound:
            member = None
        except discord.HTTPException:
            member = None

    is_moderator = member is not None
    is_registered = auth_service.user_exists(request_body.discord_id)

    # Build user info from member if available
    user_info = None
    if member:
        avatar_url = str(member.display_avatar.url) if member.display_avatar else None
        user_info = DiscordUserInfo(
            discord_id=member.id,
            username=member.name,
            display_name=member.display_name,
            avatar=avatar_url,
        )

    logger.tree("Mod Check", [
        ("User ID", str(request_body.discord_id)),
        ("Username", user_info.username if user_info else "Not in mod server"),
        ("Is Mod", "✅" if is_moderator else "❌"),
        ("Registered", "✅" if is_registered else "❌"),
        ("IP", client_ip),
    ], emoji="🔍")

    return APIResponse(
        success=True,
        data=CheckModeratorResponse(
            is_moderator=is_moderator,
            is_registered=is_registered,
            user=user_info,
        ),
    )


@router.post("/register", response_model=APIResponse[AuthTokenResponse])
async def register(
    request_body: RegisterRequest,
    request: Request,
    bot: Any = Depends(get_bot),
) -> APIResponse[AuthTokenResponse]:
    """
    Register a new dashboard user and return access token.

    Requires:
    - User must be a moderator in the Discord server
    - User must not already be registered
    - PIN must be at least 4 characters

    Returns access token on successful registration (auto-login).
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")

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
    success, message = auth_service.register(request_body.discord_id, request_body.password)

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

    # Auto-login after successful registration
    login_success, token, expires_at = auth_service.login(
        request_body.discord_id,
        request_body.password,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    if not login_success or not token:
        # Registration succeeded but auto-login failed (shouldn't happen)
        logger.error("Auto-Login After Register Failed", [
            ("User ID", str(request_body.discord_id)),
            ("IP", client_ip),
        ])
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration succeeded but auto-login failed",
        )

    logger.tree("Dashboard User Registered", [
        ("User ID", str(request_body.discord_id)),
        ("IP", client_ip),
        ("Auto-Login", "✅"),
    ], emoji="📝")

    return APIResponse(
        success=True,
        message=message,
        data=AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            expires_at=expires_at,
        ),
    )


@router.post("/login", response_model=APIResponse[AuthTokenResponse])
async def login(
    request_body: LoginRequest,
    request: Request,
) -> APIResponse[AuthTokenResponse]:
    """
    Authenticate and receive an access token.

    Returns JWT token for subsequent API requests.

    Rate limited: 5 attempts per Discord ID per 5 minutes.
    Account lockout: 5 consecutive failures = 15 minute lock.
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)
    discord_id = request_body.discord_id

    # Check account lockout first
    is_locked, locked_until = auth_service.check_account_locked(discord_id)
    if is_locked:
        logger.warning("Login Blocked (Account Locked)", [
            ("User ID", str(discord_id)),
            ("Locked Until", locked_until.isoformat() if locked_until else "N/A"),
            ("IP", client_ip),
        ])
        return JSONResponse(
            status_code=HTTP_423_LOCKED,
            content={
                "success": False,
                "error": "Account locked",
                "locked_until": locked_until.isoformat() if locked_until else None,
            },
        )

    # Check per-user rate limit
    is_allowed, retry_after = auth_service.check_login_rate_limit(discord_id)
    if not is_allowed:
        logger.warning("Login Blocked (Rate Limited)", [
            ("User ID", str(discord_id)),
            ("Retry After", f"{retry_after}s"),
            ("IP", client_ip),
        ])
        response = JSONResponse(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "error": "Too many login attempts",
                "retry_after": retry_after,
            },
        )
        response.headers["Retry-After"] = str(retry_after)
        return response

    # Record the login attempt (for rate limiting)
    auth_service.record_login_attempt(discord_id)

    # Get user agent for login tracking
    user_agent = request.headers.get("User-Agent", "")

    # Attempt login
    success, token, expires_at = auth_service.login(
        discord_id,
        request_body.password,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    if not success or not token:
        # Record failed login (for account lockout)
        is_now_locked, locked_until = auth_service.record_failed_login(discord_id)

        if is_now_locked:
            logger.warning("Account Locked After Failed Attempts", [
                ("User ID", str(discord_id)),
                ("Locked Until", locked_until.isoformat() if locked_until else "N/A"),
                ("IP", client_ip),
            ])
            return JSONResponse(
                status_code=HTTP_423_LOCKED,
                content={
                    "success": False,
                    "error": "Account locked",
                    "locked_until": locked_until.isoformat() if locked_until else None,
                },
            )

        logger.warning("Dashboard Login Failed", [
            ("User ID", str(discord_id)),
            ("Reason", "Invalid credentials"),
            ("IP", client_ip),
        ])
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Success - clear failed login tracking
    auth_service.clear_failed_logins(discord_id)

    logger.tree("Dashboard Login", [
        ("User ID", str(discord_id)),
        ("IP", client_ip),
        ("Expires", expires_at.strftime("%Y-%m-%d %H:%M") if expires_at else "N/A"),
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

    Requires valid Bearer token in Authorization header.
    Returns new token with extended expiration.
    """
    auth_service = get_auth_service()
    client_ip = _get_client_ip(request)

    # Get user permissions
    registered_user = auth_service.get_user(payload.sub)
    permissions = registered_user.permissions if registered_user else []

    # Generate new token
    token, expires_at = auth_service._generate_token(payload.sub, permissions)

    logger.tree("Dashboard Token Refresh", [
        ("User ID", str(payload.sub)),
        ("IP", client_ip),
        ("New Expiry", expires_at.strftime("%Y-%m-%d %H:%M") if expires_at else "N/A"),
    ], emoji="🔄")

    return APIResponse(
        success=True,
        data=AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            expires_at=expires_at,
        ),
    )


__all__ = ["router"]
