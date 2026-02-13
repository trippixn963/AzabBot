"""
AzabBot - Appeals Router
========================

Ban/mute appeal management endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.appeals import (
    AppealBrief,
    AppealDetail,
    AppealStatus,
    AppealType,
    AppealStats,
)
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.core.database import get_db


router = APIRouter(prefix="/appeals", tags=["Appeals"])


# =============================================================================
# List & Search
# =============================================================================

@router.get("", response_model=PaginatedResponse[List[AppealBrief]])
async def list_appeals(
    pagination: PaginationParams = Depends(get_pagination),
    status: Optional[AppealStatus] = Query(None, description="Filter by status"),
    appeal_type: Optional[AppealType] = Query(None, description="Filter by appeal type"),
    user_id: Optional[int] = Query(None, description="Filter by appellant"),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[AppealBrief]]:
    """
    List appeals with optional filters.
    """
    db = get_db()

    # Build query
    conditions = []
    params = []

    if status:
        conditions.append("status = ?")
        params.append(status.value)

    if appeal_type:
        conditions.append("action_type = ?")
        params.append(appeal_type.value)

    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    count_query = f"SELECT COUNT(*) FROM appeals WHERE {where_clause}"
    total = db.fetchone(count_query, params)[0]

    # Get page of results
    query = f"""
        SELECT appeal_id, case_id, user_id, action_type, status,
               created_at, resolved_at, resolved_by
        FROM appeals
        WHERE {where_clause}
        ORDER BY
            CASE status
                WHEN 'pending' THEN 1
                WHEN 'under_review' THEN 2
                WHEN 'approved' THEN 3
                WHEN 'denied' THEN 4
            END,
            created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    # Convert to models
    appeals = []
    for row in rows:
        appeals.append(AppealBrief(
            appeal_id=row["appeal_id"],
            case_id=row["case_id"],
            user_id=row["user_id"],
            appeal_type=AppealType(row["action_type"]) if row.get("action_type") else AppealType.BAN,
            status=AppealStatus(row["status"]) if row["status"] else AppealStatus.PENDING,
            created_at=datetime.fromtimestamp(row["created_at"]),
            resolved_at=datetime.fromtimestamp(row["resolved_at"]) if row.get("resolved_at") else None,
            resolved_by=row.get("resolved_by"),
        ))

    logger.debug("Appeals Listed", [
        ("User", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(appeals))),
        ("Total", str(total)),
    ])

    return create_paginated_response(appeals, total, pagination)


@router.get("/stats", response_model=APIResponse[AppealStats])
async def get_appeal_stats(
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[AppealStats]:
    """
    Get aggregate appeal statistics.
    """
    db = get_db()
    today_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0).timestamp()

    # Status counts
    pending_count = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE status = 'pending'"
    )[0]

    under_review_count = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE status = 'under_review'"
    )[0]

    approved_count = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE status = 'approved'"
    )[0]

    denied_count = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE status = 'denied'"
    )[0]

    # Today's appeals
    today_count = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE created_at >= ?",
        (today_start,)
    )[0]

    # Approval rate
    total_resolved = approved_count + denied_count
    approval_rate = (approved_count / total_resolved * 100) if total_resolved > 0 else None

    # Average resolution time
    avg_resolution = db.fetchone(
        """SELECT AVG(resolved_at - created_at) / 3600.0
           FROM appeals WHERE resolved_at IS NOT NULL"""
    )[0]

    stats = AppealStats(
        total_appeals=pending_count + under_review_count + approved_count + denied_count,
        pending_appeals=pending_count,
        under_review_appeals=under_review_count,
        approved_appeals=approved_count,
        denied_appeals=denied_count,
        appeals_today=today_count,
        approval_rate_percent=round(approval_rate, 1) if approval_rate else None,
        avg_resolution_time_hours=round(avg_resolution, 1) if avg_resolution else None,
    )

    logger.debug("Appeal Stats Fetched", [
        ("User", str(payload.sub)),
        ("Pending", str(stats.pending_appeals)),
        ("Total", str(stats.total_appeals)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Individual Appeal
# =============================================================================

@router.get("/{appeal_id}", response_model=APIResponse[AppealDetail])
async def get_appeal(
    appeal_id: str,
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[AppealDetail]:
    """
    Get detailed information about a specific appeal.
    """
    db = get_db()

    row = db.fetchone(
        """SELECT appeal_id, case_id, user_id, action_type, status,
                  reason, created_at, resolved_at,
                  resolved_by, resolution_reason, thread_id
           FROM appeals WHERE appeal_id = ?""",
        (appeal_id,)
    )

    if not row:
        logger.debug("Appeal Not Found", [
            ("Appeal ID", appeal_id),
            ("User", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Appeal {appeal_id} not found",
        )

    # Get user info
    user_info = await _get_user_info(bot, row["user_id"])
    resolver_info = await _get_user_info(bot, row["resolved_by"]) if row.get("resolved_by") else {}

    # Get case info if exists
    case_info = None
    if row["case_id"]:
        case_row = db.fetchone(
            "SELECT action_type, reason, created_at FROM cases WHERE case_id = ?",
            (row["case_id"],)
        )
        if case_row:
            case_info = {
                "case_type": case_row["action_type"],
                "reason": case_row["reason"],
                "created_at": datetime.fromtimestamp(case_row["created_at"]).isoformat(),
            }

    appeal = AppealDetail(
        appeal_id=row["appeal_id"],
        case_id=row["case_id"],
        case_info=case_info,
        user_id=row["user_id"],
        user_name=user_info.get("name"),
        user_avatar=user_info.get("avatar"),
        appeal_type=AppealType(row["action_type"]) if row.get("action_type") else AppealType.BAN,
        status=AppealStatus(row["status"]) if row["status"] else AppealStatus.PENDING,
        reason=row.get("reason"),
        additional_info=None,
        created_at=datetime.fromtimestamp(row["created_at"]),
        resolved_at=datetime.fromtimestamp(row["resolved_at"]) if row.get("resolved_at") else None,
        resolved_by=row.get("resolved_by"),
        resolver_name=resolver_info.get("name"),
        resolution_reason=row.get("resolution_reason"),
        thread_id=row.get("thread_id"),
    )

    logger.debug("Appeal Fetched", [
        ("Appeal ID", appeal_id),
        ("User", str(payload.sub)),
        ("Status", row["status"] or "pending"),
    ])

    return APIResponse(success=True, data=appeal)


# =============================================================================
# Helpers
# =============================================================================

async def _get_user_info(bot: Any, user_id: int) -> dict:
    """Fetch basic user info from Discord."""
    if not user_id:
        return {}
    try:
        user = await bot.fetch_user(user_id)
        return {
            "name": user.name,
            "avatar": str(user.display_avatar.url) if user.display_avatar else None,
        }
    except Exception as e:
        logger.debug("User Info Fetch Failed", [
            ("User ID", str(user_id)),
            ("Error Type", type(e).__name__),
        ])
        return {}


__all__ = ["router"]
