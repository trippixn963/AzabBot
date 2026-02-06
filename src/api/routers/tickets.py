"""
AzabBot - Tickets Router
========================

Support ticket management endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.tickets import (
    TicketBrief,
    TicketDetail,
    TicketMessage,
    TicketStatus,
    TicketPriority,
    TicketStats,
)
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.core.database import get_db


router = APIRouter(prefix="/tickets", tags=["Tickets"])


# =============================================================================
# List & Search
# =============================================================================

@router.get("", response_model=PaginatedResponse[List[TicketBrief]])
async def list_tickets(
    pagination: PaginationParams = Depends(get_pagination),
    status: Optional[TicketStatus] = Query(None, description="Filter by status"),
    priority: Optional[TicketPriority] = Query(None, description="Filter by priority"),
    claimed_by: Optional[int] = Query(None, description="Filter by claimer"),
    user_id: Optional[int] = Query(None, description="Filter by ticket creator"),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[TicketBrief]]:
    """
    List support tickets with optional filters.
    """
    db = get_db()

    # Build query
    conditions = []
    params = []

    if status:
        conditions.append("status = ?")
        params.append(status.value)

    if priority:
        conditions.append("priority = ?")
        params.append(priority.value)

    if claimed_by:
        conditions.append("claimed_by = ?")
        params.append(claimed_by)

    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Get total count
    count_query = f"SELECT COUNT(*) FROM tickets WHERE {where_clause}"
    total = db.fetchone(count_query, params)[0]

    # Get page of results
    query = f"""
        SELECT ticket_id, channel_id, user_id, claimed_by, status, priority,
               subject, created_at, claimed_at, closed_at
        FROM tickets
        WHERE {where_clause}
        ORDER BY
            CASE status
                WHEN 'open' THEN 1
                WHEN 'claimed' THEN 2
                WHEN 'closed' THEN 3
            END,
            created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    # Convert to models
    tickets = []
    for row in rows:
        tickets.append(TicketBrief(
            ticket_id=row["ticket_id"],
            channel_id=row["channel_id"],
            user_id=row["user_id"],
            claimed_by=row["claimed_by"],
            status=TicketStatus(row["status"]) if row["status"] else TicketStatus.OPEN,
            priority=TicketPriority(row["priority"]) if row.get("priority") else None,
            subject=row.get("subject"),
            created_at=datetime.fromtimestamp(row["created_at"]),
            claimed_at=datetime.fromtimestamp(row["claimed_at"]) if row.get("claimed_at") else None,
            closed_at=datetime.fromtimestamp(row["closed_at"]) if row.get("closed_at") else None,
        ))

    logger.debug("Tickets Listed", [
        ("User", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(tickets))),
        ("Total", str(total)),
    ])

    return create_paginated_response(tickets, total, pagination)


@router.get("/stats", response_model=APIResponse[TicketStats])
async def get_ticket_stats(
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[TicketStats]:
    """
    Get aggregate ticket statistics.
    """
    db = get_db()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()

    # Status counts
    open_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status = 'open'"
    )[0]

    claimed_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status = 'claimed'"
    )[0]

    closed_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status = 'closed'"
    )[0]

    # Today's tickets
    today_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE created_at >= ?",
        (today_start,)
    )[0]

    # Average response time (time from creation to claim)
    avg_response = db.fetchone(
        """SELECT AVG(claimed_at - created_at) / 60.0
           FROM tickets WHERE claimed_at IS NOT NULL"""
    )[0]

    # Average resolution time (time from creation to close)
    avg_resolution = db.fetchone(
        """SELECT AVG(closed_at - created_at) / 60.0
           FROM tickets WHERE closed_at IS NOT NULL"""
    )[0]

    stats = TicketStats(
        total_tickets=open_count + claimed_count + closed_count,
        open_tickets=open_count,
        claimed_tickets=claimed_count,
        closed_tickets=closed_count,
        tickets_today=today_count,
        avg_response_time_minutes=round(avg_response, 1) if avg_response else None,
        avg_resolution_time_minutes=round(avg_resolution, 1) if avg_resolution else None,
    )

    logger.debug("Ticket Stats Fetched", [
        ("User", str(payload.sub)),
        ("Open", str(stats.open_tickets)),
        ("Claimed", str(stats.claimed_tickets)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Individual Ticket
# =============================================================================

@router.get("/{ticket_id}", response_model=APIResponse[TicketDetail])
async def get_ticket(
    ticket_id: str,
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[TicketDetail]:
    """
    Get detailed information about a specific ticket.
    """
    db = get_db()
    ticket_id = ticket_id.upper()

    row = db.fetchone(
        """SELECT ticket_id, channel_id, user_id, claimed_by, status, priority,
                  subject, created_at, claimed_at, closed_at, close_reason
           FROM tickets WHERE ticket_id = ?""",
        (ticket_id,)
    )

    if not row:
        logger.debug("Ticket Not Found", [
            ("Ticket ID", ticket_id),
            ("User", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} not found",
        )

    # Get user info
    user_info = await _get_user_info(bot, row["user_id"])
    claimer_info = await _get_user_info(bot, row["claimed_by"]) if row["claimed_by"] else {}

    # Get message count
    message_count = db.fetchone(
        "SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = ?",
        (ticket_id,)
    )[0]

    ticket = TicketDetail(
        ticket_id=row["ticket_id"],
        channel_id=row["channel_id"],
        user_id=row["user_id"],
        user_name=user_info.get("name"),
        user_avatar=user_info.get("avatar"),
        claimed_by=row["claimed_by"],
        claimer_name=claimer_info.get("name"),
        status=TicketStatus(row["status"]) if row["status"] else TicketStatus.OPEN,
        priority=TicketPriority(row["priority"]) if row.get("priority") else None,
        subject=row.get("subject"),
        created_at=datetime.fromtimestamp(row["created_at"]),
        claimed_at=datetime.fromtimestamp(row["claimed_at"]) if row.get("claimed_at") else None,
        closed_at=datetime.fromtimestamp(row["closed_at"]) if row.get("closed_at") else None,
        close_reason=row.get("close_reason"),
        message_count=message_count,
    )

    logger.debug("Ticket Fetched", [
        ("Ticket ID", ticket_id),
        ("User", str(payload.sub)),
        ("Status", row["status"] or "open"),
    ])

    return APIResponse(success=True, data=ticket)


@router.get("/{ticket_id}/messages", response_model=PaginatedResponse[List[TicketMessage]])
async def get_ticket_messages(
    ticket_id: str,
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[TicketMessage]]:
    """
    Get messages for a specific ticket.
    """
    db = get_db()
    ticket_id = ticket_id.upper()

    # Verify ticket exists
    ticket = db.fetchone("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,))
    if not ticket:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Ticket {ticket_id} not found",
        )

    # Get total count
    total = db.fetchone(
        "SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = ?",
        (ticket_id,)
    )[0]

    # Get messages
    rows = db.fetchall(
        """SELECT message_id, author_id, content, created_at, is_staff
           FROM ticket_messages
           WHERE ticket_id = ?
           ORDER BY created_at ASC
           LIMIT ? OFFSET ?""",
        (ticket_id, pagination.per_page, pagination.offset)
    )

    messages = []
    for row in rows:
        author_info = await _get_user_info(bot, row["author_id"])
        messages.append(TicketMessage(
            message_id=row["message_id"],
            author_id=row["author_id"],
            author_name=author_info.get("name"),
            author_avatar=author_info.get("avatar"),
            content=row["content"],
            created_at=datetime.fromtimestamp(row["created_at"]),
            is_staff=bool(row.get("is_staff")),
        ))

    logger.debug("Ticket Messages Fetched", [
        ("Ticket ID", ticket_id),
        ("User", str(payload.sub)),
        ("Messages", str(len(messages))),
    ])

    return create_paginated_response(messages, total, pagination)


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
    except Exception:
        return {}


__all__ = ["router"]
