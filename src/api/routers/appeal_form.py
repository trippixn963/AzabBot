"""
AzabBot - Appeal Form Router
============================

Public endpoints for the web-based appeal form.
Uses token-based authentication (not JWT).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.core.logger import logger
from src.core.database import get_db
from src.api.dependencies import get_bot


router = APIRouter(prefix="/appeal-form", tags=["Appeal Form"])


# =============================================================================
# Rate Limiter
# =============================================================================

APPEAL_RATE_LIMIT = 3  # Max appeals per IP per hour
APPEAL_RATE_WINDOW = 3600  # 1 hour

_appeal_submissions: Dict[str, List[float]] = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    """Get client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_appeal_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check if IP is allowed to submit another appeal."""
    now = time.time()
    window_start = now - APPEAL_RATE_WINDOW

    _appeal_submissions[client_ip] = [
        ts for ts in _appeal_submissions[client_ip] if ts > window_start
    ]

    if len(_appeal_submissions[client_ip]) >= APPEAL_RATE_LIMIT:
        oldest = min(_appeal_submissions[client_ip])
        retry_after = int(oldest + APPEAL_RATE_WINDOW - now) + 1
        return False, retry_after

    return True, 0


def _record_appeal_submission(client_ip: str) -> None:
    """Record a successful appeal submission."""
    _appeal_submissions[client_ip].append(time.time())


# =============================================================================
# Request Models
# =============================================================================

class AppealSubmission(BaseModel):
    """Appeal submission request body."""

    reason: str = Field(..., min_length=20, max_length=2000)
    email: Optional[str] = Field(None, max_length=254)
    attachments: List[str] = Field(default_factory=list, max_length=3)


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/{token}")
async def get_appeal_form(token: str, request: Request):
    """
    Validate appeal token and return case info for the form.

    The token is sent to users in ban/mute DMs and contains
    the case_id and user_id encrypted.
    """
    client_ip = _get_client_ip(request)

    if not token:
        return JSONResponse(
            {"error": "Missing appeal token"},
            status_code=400,
        )

    # Validate token
    from src.services.appeals.tokens import validate_appeal_token
    is_valid, payload, error = validate_appeal_token(token)

    if not is_valid:
        logger.warning("Appeal Token Invalid", [
            ("Client IP", client_ip),
            ("Error", error or "Unknown"),
        ])
        return JSONResponse(
            {"error": error or "Invalid appeal link"},
            status_code=401,
        )

    case_id = payload["case_id"]
    user_id = payload["user_id"]

    logger.debug("Appeal Form Requested", [
        ("Case ID", case_id),
        ("User ID", str(user_id)),
        ("Client IP", client_ip),
    ])

    db = get_db()
    bot = get_bot()

    # Get case info
    case = db.get_appealable_case(case_id)
    if not case:
        return JSONResponse(
            {"error": "Case not found"},
            status_code=404,
        )

    # Verify user matches case
    if case["user_id"] != user_id:
        logger.warning("Appeal User Mismatch", [
            ("Case ID", case_id),
            ("Token User", str(user_id)),
            ("Case User", str(case["user_id"])),
        ])
        return JSONResponse(
            {"error": "Invalid appeal link"},
            status_code=403,
        )

    # Check existing appeal
    existing_appeal = db.get_appeal_by_case(case_id)
    appeal_status = None
    if existing_appeal:
        appeal_status = {
            "appeal_id": existing_appeal.get("appeal_id"),
            "status": existing_appeal.get("status", "pending"),
            "submitted_at": existing_appeal.get("created_at"),
            "resolved_at": existing_appeal.get("resolved_at"),
            "resolution": existing_appeal.get("resolution"),
            "resolution_reason": existing_appeal.get("resolution_reason"),
            "appeal_reason": existing_appeal.get("reason"),
        }

    # Check eligibility
    can_appeal = False
    blocked_reason = "Appeal system is not available"
    if bot.appeal_service:
        can_appeal, blocked_reason, _ = bot.appeal_service.can_appeal(case_id)

    # Get moderator name
    mod_id = case.get("moderator_id")
    mod_name = "Unknown Moderator"
    if mod_id:
        try:
            mod = await bot.fetch_user(mod_id)
            mod_name = mod.display_name if mod else f"User {mod_id}"
        except Exception:
            mod_name = f"User {mod_id}"

    response = {
        "case_id": case_id,
        "user_id": str(user_id),
        "action_type": case.get("action_type", "unknown"),
        "reason": case.get("reason", "No reason provided"),
        "moderator": mod_name,
        "created_at": case.get("created_at"),
        "duration_seconds": case.get("duration_seconds"),
        "can_appeal": can_appeal,
        "appeal_blocked_reason": blocked_reason if not can_appeal else None,
        "existing_appeal": appeal_status,
    }

    # Include server invite if appeal was approved
    if appeal_status and appeal_status.get("resolution") == "approved":
        from src.core.config import get_config
        config = get_config()
        if config.server_invite_url:
            response["server_invite_url"] = config.server_invite_url

    return JSONResponse(response)


@router.post("/{token}")
async def submit_appeal_form(token: str, request: Request):
    """
    Submit an appeal via the web form.

    Rate limited to 3 submissions per IP per hour.
    """
    client_ip = _get_client_ip(request)

    # Check rate limit
    allowed, retry_after = _check_appeal_rate_limit(client_ip)
    if not allowed:
        logger.warning("Appeal Rate Limited", [
            ("Client IP", client_ip),
            ("Retry After", f"{retry_after}s"),
        ])
        return JSONResponse(
            {
                "error": f"Too many appeals. Try again in {retry_after // 60} minutes.",
                "retry_after": retry_after,
            },
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    if not token:
        return JSONResponse(
            {"error": "Missing appeal token"},
            status_code=400,
        )

    # Validate token
    from src.services.appeals.tokens import validate_appeal_token
    is_valid, payload, error = validate_appeal_token(token)

    if not is_valid:
        logger.warning("Appeal Submit Token Invalid", [
            ("Client IP", client_ip),
            ("Error", error or "Unknown"),
        ])
        return JSONResponse(
            {"error": error or "Invalid appeal link"},
            status_code=401,
        )

    case_id = payload["case_id"]
    user_id = payload["user_id"]

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid request body"},
            status_code=400,
        )

    appeal_reason = body.get("reason", "").strip()
    appeal_email = body.get("email", "").strip() or None
    raw_attachments = body.get("attachments", [])

    # Validate reason
    if not appeal_reason:
        return JSONResponse({"error": "Appeal reason is required"}, status_code=400)

    if len(appeal_reason) < 20:
        return JSONResponse({"error": "Reason must be at least 20 characters"}, status_code=400)

    if len(appeal_reason) > 2000:
        return JSONResponse({"error": "Reason must be under 2000 characters"}, status_code=400)

    # Process attachments
    attachments = []
    if raw_attachments and isinstance(raw_attachments, list):
        for att in raw_attachments[:3]:
            if isinstance(att, str) and att.startswith("http"):
                attachments.append(att)

    bot = get_bot()

    # Check eligibility
    if bot.appeal_service:
        can_appeal, reason, _ = bot.appeal_service.can_appeal(case_id)
        if not can_appeal:
            return JSONResponse({"error": reason}, status_code=403)
    else:
        return JSONResponse({"error": "Appeal system unavailable"}, status_code=503)

    # Submit appeal
    try:
        success, appeal_id, error_msg = await bot.appeal_service.submit_appeal(
            case_id=case_id,
            user_id=user_id,
            reason=appeal_reason,
            email=appeal_email,
            attachments=attachments,
            client_ip=client_ip,
        )

        if not success:
            return JSONResponse(
                {"error": error_msg or "Failed to submit appeal"},
                status_code=400,
            )

        _record_appeal_submission(client_ip)

        logger.tree("Appeal Submitted", [
            ("Case ID", case_id),
            ("Appeal ID", appeal_id),
            ("User ID", str(user_id)),
            ("Client IP", client_ip),
        ], emoji="📝")

        return JSONResponse({
            "success": True,
            "appeal_id": appeal_id,
            "message": "Your appeal has been submitted successfully.",
        })

    except Exception as e:
        logger.error("Appeal Submit Failed", [
            ("Case ID", case_id),
            ("Error", str(e)[:100]),
        ])
        return JSONResponse(
            {"error": "An error occurred while submitting your appeal"},
            status_code=500,
        )


@router.options("/{token}")
async def appeal_form_options(token: str):
    """CORS preflight handler."""
    return JSONResponse(
        {},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


__all__ = ["router"]
