"""
AzabBot - Frontend Logs Router
==============================

Endpoint for receiving logs from the dashboard frontend.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from src.core.logger import logger
from src.api.models.auth import TokenPayload


router = APIRouter(prefix="/logs", tags=["Frontend Logs"])


# =============================================================================
# Rate Limiting & Deduplication
# =============================================================================

# Per-IP rate limiting: {ip: [(timestamp, count)]}
_rate_limit_tracker: Dict[str, List[float]] = {}
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 30  # max logs per window per IP

# Error deduplication: {(ip, message_hash): last_seen_timestamp}
_recent_errors: Dict[Tuple[str, int], float] = {}
_ERROR_DEDUP_WINDOW = 60  # Don't log same error from same IP within 60s


def _check_rate_limit(ip: str) -> bool:
    """Check if IP is within rate limit. Returns True if allowed."""
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW

    # Clean old entries
    if ip in _rate_limit_tracker:
        _rate_limit_tracker[ip] = [t for t in _rate_limit_tracker[ip] if t > cutoff]
    else:
        _rate_limit_tracker[ip] = []

    # Check limit
    if len(_rate_limit_tracker[ip]) >= _RATE_LIMIT_MAX:
        return False

    # Record this request
    _rate_limit_tracker[ip].append(now)
    return True


def _is_duplicate_error(ip: str, message: str) -> bool:
    """Check if this is a duplicate error within dedup window."""
    now = time.time()
    key = (ip, hash(message))

    # Clean old entries periodically (every 100th check)
    if len(_recent_errors) > 1000:
        cutoff = now - _ERROR_DEDUP_WINDOW
        keys_to_remove = [k for k, v in _recent_errors.items() if v < cutoff]
        for k in keys_to_remove:
            try:
                del _recent_errors[k]
            except KeyError:
                pass

    # Check if duplicate
    if key in _recent_errors:
        if now - _recent_errors[key] < _ERROR_DEDUP_WINDOW:
            return True

    _recent_errors[key] = now
    return False


# =============================================================================
# Models
# =============================================================================

class FrontendLogRequest(BaseModel):
    """Frontend log entry with validation."""
    level: Literal["info", "warn", "error"] = Field(..., description="Log level")
    category: Literal["api", "auth", "error", "action", "navigation"] = Field(..., description="Log category")
    message: str = Field(..., min_length=1, max_length=500, description="Log message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional context data")
    timestamp: Optional[str] = Field(None, max_length=30, description="ISO timestamp from frontend")
    session_id: Optional[str] = Field(None, max_length=50, description="Frontend session ID")
    user_agent: Optional[str] = Field(None, max_length=300, description="Browser user agent")

    @field_validator("data")
    @classmethod
    def validate_data_size(cls, v: Optional[Dict]) -> Optional[Dict]:
        """Limit data payload size."""
        if v is None:
            return v
        # Limit to 10 keys max
        if len(v) > 10:
            return dict(list(v.items())[:10])
        # Truncate string values
        for key, value in v.items():
            if isinstance(value, str) and len(value) > 200:
                v[key] = value[:200] + "..."
        return v


# =============================================================================
# Helpers
# =============================================================================

def _get_client_ip(request: Request) -> str:
    """Get client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def get_current_user_optional(request: Request) -> Optional[TokenPayload]:
    """Try to get current user from auth header, return None if not authenticated."""
    from src.api.services.auth import get_auth_service

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    auth_service = get_auth_service()

    try:
        payload = auth_service.verify_token(token)
        return payload
    except Exception:
        return None


# =============================================================================
# Endpoint
# =============================================================================

@router.post("/frontend")
async def log_frontend_event(
    log_entry: FrontendLogRequest,
    request: Request,
) -> Dict[str, bool]:
    """
    Receive and process frontend log entries.

    Features:
    - Rate limited: 30 logs per minute per IP
    - Error deduplication: Same error from same IP throttled for 60s
    - Field size limits: Prevents payload abuse
    - Optional auth: Logs authenticated user if token provided
    """
    client_ip = _get_client_ip(request)

    # Rate limit check
    if not _check_rate_limit(client_ip):
        return {"logged": False, "reason": "rate_limited"}

    # Deduplicate errors
    if log_entry.level == "error":
        if _is_duplicate_error(client_ip, log_entry.message):
            return {"logged": False, "reason": "duplicate"}

    # Try to get authenticated user
    auth_user = await get_current_user_optional(request)
    auth_user_id = auth_user.sub if auth_user else None

    # Extract user_id from data (may differ from auth user)
    data_user_id = None
    page = None
    if log_entry.data:
        data_user_id = log_entry.data.get("user_id")
        page = log_entry.data.get("page")

    # Use auth user if available, otherwise use data user_id
    user_id = auth_user_id or data_user_id

    # Build log details
    details: List[Tuple[str, str]] = [
        ("Category", log_entry.category),
        ("Message", log_entry.message[:100]),
    ]

    if user_id:
        details.append(("User", str(user_id)))
    if page:
        details.append(("Page", str(page)[:50]))
    if log_entry.session_id:
        details.append(("Session", log_entry.session_id[:8]))
    details.append(("IP", client_ip))

    # Log based on level
    if log_entry.level == "error":
        logger.error("Frontend Error", details)
    elif log_entry.level == "warn":
        logger.warning("Frontend Warning", details)
    else:
        logger.info("Frontend", details)

    return {"logged": True}


__all__ = ["router"]
