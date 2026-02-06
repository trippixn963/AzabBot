"""
AzabBot - Cases Router
======================

Moderation case management endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.cases import CaseBrief, CaseDetail, CaseStats, CaseType, CaseStatus
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.core.database import get_db


router = APIRouter(prefix="/cases", tags=["Cases"])


# =============================================================================
# List & Search
# =============================================================================

@router.get("", response_model=PaginatedResponse[List[CaseBrief]])
async def list_cases(
    request: Request,
    pagination: PaginationParams = Depends(get_pagination),
    case_type: Optional[CaseType] = Query(None, description="Filter by case type"),
    status: Optional[CaseStatus] = Query(None, description="Filter by status"),
    moderator_id: Optional[int] = Query(None, description="Filter by moderator"),
    user_id: Optional[int] = Query(None, description="Filter by target user"),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[CaseBrief]]:
    """
    List moderation cases with optional filters.

    Supports filtering by type, status, moderator, and target user.
    """
    db = get_db()

    # Build query
    conditions = []
    params = []

    if case_type:
        conditions.append("action_type = ?")
        params.append(case_type.value)

    if status:
        if status == CaseStatus.ACTIVE:
            conditions.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(datetime.utcnow().timestamp())
        elif status == CaseStatus.EXPIRED:
            conditions.append("expires_at IS NOT NULL AND expires_at <= ?")
            params.append(datetime.utcnow().timestamp())
        elif status == CaseStatus.APPEALED:
            conditions.append("case_id IN (SELECT case_id FROM appeals)")
        elif status == CaseStatus.REVERSED:
            conditions.append("reversed = 1")

    if moderator_id:
        conditions.append("moderator_id = ?")
        params.append(moderator_id)

    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    count_query = f"SELECT COUNT(*) FROM cases WHERE {where_clause}"
    total = db.fetchone(count_query, params)[0]

    # Get page of results
    query = f"""
        SELECT case_id, user_id, moderator_id, action_type, reason, created_at, expires_at
        FROM cases
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    # Convert to models
    cases = []
    for row in rows:
        expires_at = datetime.fromtimestamp(row["expires_at"]) if row["expires_at"] else None
        status = _determine_case_status(row, expires_at)

        cases.append(CaseBrief(
            case_id=row["case_id"],
            user_id=row["user_id"],
            moderator_id=row["moderator_id"],
            case_type=CaseType(row["action_type"]),
            reason=row["reason"][:100] if row["reason"] else None,
            created_at=datetime.fromtimestamp(row["created_at"]),
            expires_at=expires_at,
            status=status,
        ))

    logger.debug("Cases Listed", [
        ("User", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(cases))),
        ("Total", str(total)),
    ])

    return create_paginated_response(cases, total, pagination)


@router.get("/stats", response_model=APIResponse[CaseStats])
async def get_case_stats(
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[CaseStats]:
    """
    Get aggregate case statistics.
    """
    db = get_db()
    now = datetime.utcnow().timestamp()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()

    # Total counts by type
    type_counts = db.fetchall(
        "SELECT action_type, COUNT(*) as count FROM cases GROUP BY action_type"
    )
    type_map = {row["action_type"]: row["count"] for row in type_counts}

    # Active punishments
    active_mutes = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE action_type = 'mute' AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    )[0]

    active_bans = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE action_type = 'ban' AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    )[0]

    # Cases today
    today_count = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ?",
        (today_start,)
    )[0]

    # Appealed cases
    appealed = db.fetchone("SELECT COUNT(DISTINCT case_id) FROM appeals")[0]

    stats = CaseStats(
        total_cases=sum(type_map.values()),
        total_mutes=type_map.get("mute", 0),
        total_bans=type_map.get("ban", 0),
        total_warns=type_map.get("warn", 0),
        total_kicks=type_map.get("kick", 0),
        active_mutes=active_mutes,
        active_bans=active_bans,
        cases_today=today_count,
        appealed_cases=appealed,
    )

    logger.debug("Case Stats Fetched", [
        ("User", str(payload.sub)),
        ("Total Cases", str(stats.total_cases)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Individual Case
# =============================================================================

@router.get("/{case_id}", response_model=APIResponse[CaseDetail])
async def get_case(
    case_id: int,
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[CaseDetail]:
    """
    Get detailed information about a specific case.
    """
    db = get_db()

    row = db.fetchone(
        """SELECT case_id, user_id, moderator_id, action_type, reason,
                  created_at, expires_at, log_message_id, evidence
           FROM cases WHERE case_id = ?""",
        (case_id,)
    )

    if not row:
        logger.debug("Case Not Found", [
            ("Case ID", str(case_id)),
            ("User", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Case #{case_id} not found",
        )

    expires_at = datetime.fromtimestamp(row["expires_at"]) if row["expires_at"] else None
    status = _determine_case_status(row, expires_at)

    # Get user info from bot
    user_info = await _get_user_info(bot, row["user_id"])
    mod_info = await _get_user_info(bot, row["moderator_id"])

    # Check for appeal
    appeal = db.fetchone(
        "SELECT appeal_id, status FROM appeals WHERE case_id = ? ORDER BY created_at DESC LIMIT 1",
        (case_id,)
    )

    case = CaseDetail(
        case_id=row["case_id"],
        user_id=row["user_id"],
        user_name=user_info.get("name"),
        user_avatar=user_info.get("avatar"),
        moderator_id=row["moderator_id"],
        moderator_name=mod_info.get("name"),
        case_type=CaseType(row["action_type"]),
        reason=row["reason"],
        created_at=datetime.fromtimestamp(row["created_at"]),
        expires_at=expires_at,
        status=status,
        log_message_id=row["log_message_id"],
        evidence=row["evidence"].split(",") if row["evidence"] else None,
        appeal_id=appeal["appeal_id"] if appeal else None,
        appeal_status=appeal["status"] if appeal else None,
    )

    logger.debug("Case Fetched", [
        ("Case ID", str(case_id)),
        ("User", str(payload.sub)),
        ("Type", row["action_type"]),
    ])

    return APIResponse(success=True, data=case)


# =============================================================================
# Helpers
# =============================================================================

def _determine_case_status(row: dict, expires_at: Optional[datetime]) -> CaseStatus:
    """Determine the current status of a case."""
    if row.get("reversed"):
        return CaseStatus.REVERSED

    if expires_at:
        if expires_at <= datetime.utcnow():
            return CaseStatus.EXPIRED

    return CaseStatus.ACTIVE


async def _get_user_info(bot: Any, user_id: int) -> dict:
    """Fetch basic user info from Discord."""
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
        return {"name": None, "avatar": None}


__all__ = ["router"]
