"""
AzabBot - API Dependencies
==========================

FastAPI dependency injection utilities.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

from fastapi import Depends, HTTPException, Request

if TYPE_CHECKING:
    from src.bot import AzabBot
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from src.api.services.auth import get_auth_service, AuthService
from src.api.models.auth import TokenPayload


# =============================================================================
# Security
# =============================================================================

security = HTTPBearer(auto_error=False)


# =============================================================================
# Bot Reference
# =============================================================================

_bot_instance: Optional["AzabBot"] = None


def set_bot(bot: "AzabBot") -> None:
    """Set the bot instance for dependency injection."""
    global _bot_instance
    _bot_instance = bot


def get_bot() -> "AzabBot":
    """Get the bot instance."""
    if _bot_instance is None:
        raise HTTPException(
            status_code=503,
            detail="Bot not initialized",
        )
    return _bot_instance


# =============================================================================
# Authentication Dependencies
# =============================================================================

async def get_token_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenPayload]:
    """
    Get the token payload if a valid token is provided.
    Returns None if no token or invalid token.
    """
    if credentials is None:
        return None

    auth_service = get_auth_service()
    return auth_service.get_token_payload(credentials.credentials)


async def get_current_user_id(
    payload: Optional[TokenPayload] = Depends(get_token_payload),
) -> Optional[int]:
    """Get the current user's Discord ID if authenticated."""
    if payload is None:
        return None
    return payload.sub


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenPayload:
    """
    Require a valid authentication token.
    Raises 401 if not authenticated.
    """
    if credentials is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_service = get_auth_service()
    payload = auth_service.get_token_payload(credentials.credentials)

    if payload is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_permission(permission: str):
    """
    Factory for permission-based authorization.

    Usage:
        @router.get("/admin")
        async def admin_endpoint(
            payload: TokenPayload = Depends(require_permission("admin")),
        ):
            ...
    """
    async def dependency(
        payload: TokenPayload = Depends(require_auth),
    ) -> TokenPayload:
        if permission not in payload.permissions and "admin" not in payload.permissions:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return payload

    return dependency


async def get_request_id(request: Request) -> str:
    """Get the request ID from the logging middleware."""
    return getattr(request.state, "request_id", "unknown")


# =============================================================================
# Pagination Dependencies
# =============================================================================

class PaginationParams:
    """Standard pagination parameters."""

    def __init__(
        self,
        page: int = 1,
        per_page: int = 20,
    ):
        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 1
        if per_page > 100:
            per_page = 100

        self.page = page
        self.per_page = per_page
        self.offset = (page - 1) * per_page


def get_pagination(
    page: int = 1,
    per_page: int = 20,
) -> PaginationParams:
    """Get pagination parameters from query string."""
    return PaginationParams(page=page, per_page=per_page)


__all__ = [
    "security",
    "set_bot",
    "get_bot",
    "get_token_payload",
    "get_current_user_id",
    "require_auth",
    "require_permission",
    "get_request_id",
    "PaginationParams",
    "get_pagination",
]
