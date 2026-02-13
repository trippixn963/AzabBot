"""
AzabBot - Tickets Router
========================

Support ticket management endpoints.
Optimized with request-scoped caching and consolidated queries.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.auth import TokenPayload
from src.api.models.tickets import (
    TicketListResponse,
    TicketStatsResponse,
    TicketDetailResponse,
    TicketMessagesResponse,
)
from src.api.services.auth import get_auth_service
from src.api.errors import APIError, ErrorCode
from src.core.database import get_db


router = APIRouter(prefix="/tickets", tags=["Tickets"])


def verify_transcript_access(ticket_id: str, token: Optional[str]) -> bool:
    """
    Verify transcript token for unauthenticated access.

    Args:
        ticket_id: The ticket being accessed
        token: The transcript token from query params

    Returns:
        True if token is valid for this ticket
    """
    if not token:
        return False

    auth_service = get_auth_service()
    return auth_service.validate_transcript_token(token, ticket_id.upper())


def _to_iso(ts: float) -> str:
    """Convert timestamp to ISO string."""
    return datetime.fromtimestamp(ts).isoformat()


class UserInfoCache:
    """Request-scoped cache for Discord user info lookups."""

    def __init__(self, bot: Any):
        self.bot = bot
        self._cache: dict[int, dict] = {}

    async def get(self, user_id: int) -> dict:
        """Get user info, using cache if available."""
        if not user_id:
            return {}

        if user_id in self._cache:
            return self._cache[user_id]

        try:
            user = await self.bot.fetch_user(user_id)
            info = {
                "name": user.name,
                "avatar": str(user.display_avatar.url) if user.display_avatar else None,
            }
        except Exception as e:
            logger.debug("User Info Fetch Failed", [
                ("User ID", str(user_id)),
                ("Error Type", type(e).__name__),
            ])
            info = {}

        self._cache[user_id] = info
        return info

    async def prefetch(self, user_ids: list[int]) -> None:
        """Prefetch multiple users into cache."""
        for uid in user_ids:
            if uid and uid not in self._cache:
                await self.get(uid)


# =============================================================================
# List & Search
# =============================================================================

@router.get("", response_model=TicketListResponse)
async def list_tickets(
    pagination: PaginationParams = Depends(get_pagination),
    status: Optional[str] = Query(None, description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    claimed_by: Optional[int] = Query(None, description="Filter by claimer"),
    user_id: Optional[int] = Query(None, description="Filter by ticket creator"),
    search: Optional[str] = Query(None, description="Search ticket ID, subject, or user"),
    time_range: Optional[str] = Query(None, description="Filter by time: today, week, month"),
    sort_by: Optional[str] = Query("created_at", description="Sort field"),
    sort_dir: Optional[str] = Query("desc", description="Sort direction: asc or desc"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> TicketListResponse:
    """List support tickets with optional filters."""
    db = get_db()
    user_cache = UserInfoCache(bot)

    # Build query conditions
    conditions = []
    params = []

    if status:
        conditions.append("status = ?")
        params.append(status)

    if category:
        conditions.append("category = ?")
        params.append(category)

    if claimed_by:
        conditions.append("claimed_by = ?")
        params.append(claimed_by)

    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)

    if search:
        search_term = f"%{search}%"
        conditions.append("(ticket_id LIKE ? OR subject LIKE ?)")
        params.extend([search_term, search_term])

    if time_range:
        now = datetime.now(NY_TZ)
        if time_range == "today":
            start = now.replace(hour=0, minute=0, second=0).timestamp()
        elif time_range == "week":
            start = (now - timedelta(days=7)).timestamp()
        elif time_range == "month":
            start = (now - timedelta(days=30)).timestamp()
        else:
            start = None
        if start:
            conditions.append("created_at >= ?")
            params.append(start)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort field
    valid_sort_fields = {"ticket_id", "status", "created_at", "category", "claimed_at", "closed_at"}
    if sort_by not in valid_sort_fields:
        sort_by = "created_at"
    sort_direction = "ASC" if sort_dir == "asc" else "DESC"

    # Get total count
    count_query = f"SELECT COUNT(*) FROM tickets WHERE {where_clause}"
    total = db.fetchone(count_query, params)[0]

    # Get page of results
    query = f"""
        SELECT ticket_id, thread_id, user_id, claimed_by, status,
               subject, category, created_at, claimed_at, closed_at
        FROM tickets
        WHERE {where_clause}
        ORDER BY {sort_by} {sort_direction}
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    # Collect unique user IDs and prefetch
    user_ids = set()
    for row in rows:
        if row["user_id"]:
            user_ids.add(row["user_id"])
        if row["claimed_by"]:
            user_ids.add(row["claimed_by"])
    await user_cache.prefetch(list(user_ids))

    # Build response with cached user info
    tickets = []
    for row in rows:
        user_info = await user_cache.get(row["user_id"])
        claimer_info = await user_cache.get(row["claimed_by"]) if row["claimed_by"] else {}
        tickets.append({
            "ticket_id": row["ticket_id"],
            "channel_id": row["thread_id"],
            "user_id": row["user_id"],
            "user_name": user_info.get("name"),
            "user_avatar": user_info.get("avatar"),
            "claimed_by": row["claimed_by"],
            "claimer_name": claimer_info.get("name"),
            "claimer_avatar": claimer_info.get("avatar"),
            "status": row["status"] or "open",
            "subject": row["subject"],
            "category": row["category"],
            "created_at": _to_iso(row["created_at"]),
            "claimed_at": _to_iso(row["claimed_at"]) if row["claimed_at"] else None,
            "closed_at": _to_iso(row["closed_at"]) if row["closed_at"] else None,
        })

    total_pages = (total + pagination.per_page - 1) // pagination.per_page

    logger.debug("Tickets Listed", [
        ("User", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(tickets))),
        ("Total", str(total)),
    ])

    return TicketListResponse(
        data=tickets,
        total=total,
        total_pages=total_pages,
        page=pagination.page,
        per_page=pagination.per_page,
    )


@router.get("/stats", response_model=TicketStatsResponse)
async def get_ticket_stats(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> TicketStatsResponse:
    """Get aggregate ticket statistics with moderator data."""
    db = get_db()
    user_cache = UserInfoCache(bot)
    now = datetime.now(NY_TZ)
    today_start = now.replace(hour=0, minute=0, second=0).timestamp()
    week_start = (now - timedelta(days=7)).timestamp()
    last_week_start = (now - timedelta(days=14)).timestamp()
    week_ago = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0).timestamp()

    # Query 1: All counts and averages in one query
    counts_row = db.fetchone("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
            SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END) as claimed_count,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed_count,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as today_count,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as week_count,
            SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) as last_week_count,
            AVG(CASE WHEN claimed_at IS NOT NULL THEN (claimed_at - created_at) / 60.0 END) as avg_response,
            AVG(CASE WHEN closed_at IS NOT NULL AND claimed_at IS NOT NULL
                THEN (closed_at - claimed_at) / 60.0 END) as avg_handle
        FROM tickets
    """, (today_start, week_start, last_week_start, week_start))

    total_tickets = counts_row["total"] or 0
    open_count = counts_row["open_count"] or 0
    claimed_count = counts_row["claimed_count"] or 0
    closed_count = counts_row["closed_count"] or 0
    today_count = counts_row["today_count"] or 0
    week_count = counts_row["week_count"] or 0
    last_week_count = counts_row["last_week_count"] or 0
    avg_response = counts_row["avg_response"]
    avg_handle = counts_row["avg_handle"]

    # Weekly trend percentage
    if last_week_count > 0:
        weekly_trend_pct = round(((week_count - last_week_count) / last_week_count) * 100, 1)
    else:
        weekly_trend_pct = 100.0 if week_count > 0 else 0.0

    # Query 2: Daily activity (single query with grouping)
    daily_rows = db.fetchall("""
        SELECT DATE(created_at, 'unixepoch', 'localtime') as day_date, COUNT(*) as cnt
        FROM tickets
        WHERE created_at >= ?
        GROUP BY day_date
        ORDER BY day_date ASC
    """, (week_ago,))

    daily_map = {row["day_date"]: row["cnt"] for row in daily_rows}
    daily_activity = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        daily_activity.append({
            "day": day.strftime("%a"),
            "date": day_str,
            "count": daily_map.get(day_str, 0),
        })

    # Query 3: Category breakdown
    category_rows = db.fetchall("""
        SELECT COALESCE(category, 'Uncategorized') as cat, COUNT(*) as cnt
        FROM tickets
        GROUP BY category
        ORDER BY cnt DESC
    """)
    category_breakdown = [{"name": row["cat"], "count": row["cnt"]} for row in category_rows]

    # Query 4: Top 3 moderators
    mod_rows = db.fetchall("""
        SELECT
            claimed_by,
            COUNT(*) as total_claimed,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as total_closed,
            AVG(CASE WHEN closed_at IS NOT NULL AND claimed_at IS NOT NULL
                THEN (closed_at - claimed_at) / 60.0 END) as avg_handle
        FROM tickets
        WHERE claimed_by IS NOT NULL
        GROUP BY claimed_by
        ORDER BY total_closed DESC
        LIMIT 3
    """)

    # Query 5: All moderator categories in one query
    mod_ids = [row["claimed_by"] for row in mod_rows]
    mod_categories_map: dict[int, list] = {mid: [] for mid in mod_ids}

    if mod_ids:
        placeholders = ",".join("?" * len(mod_ids))
        mod_cat_rows = db.fetchall(f"""
            SELECT claimed_by, COALESCE(category, 'Uncategorized') as cat, COUNT(*) as cnt
            FROM tickets
            WHERE claimed_by IN ({placeholders})
            GROUP BY claimed_by, category
            ORDER BY claimed_by, cnt DESC
        """, mod_ids)

        for row in mod_cat_rows:
            mod_categories_map[row["claimed_by"]].append({
                "name": row["cat"],
                "count": row["cnt"],
            })

    # Prefetch user info for moderators
    await user_cache.prefetch(mod_ids)

    # Get guild for online status (using correct config attribute)
    guild = None
    if hasattr(bot, 'config') and bot.config.main_guild_id:
        guild = bot.get_guild(bot.config.main_guild_id)

    top_moderators = []
    for row in mod_rows:
        user_id = row["claimed_by"]
        user_info = await user_cache.get(user_id)

        # Check online status
        is_online = False
        if guild:
            member = guild.get_member(user_id)
            if member:
                is_online = member.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)

        top_moderators.append({
            "user_id": user_id,
            "user_name": user_info.get("name", f"User {user_id}"),
            "user_avatar": user_info.get("avatar"),
            "total_claimed": row["total_claimed"],
            "total_closed": row["total_closed"],
            "avg_handle_minutes": round(row["avg_handle"], 1) if row["avg_handle"] else None,
            "is_online": is_online,
            "categories": mod_categories_map.get(user_id, []),
        })

    stats = {
        "total_tickets": total_tickets,
        "open_tickets": open_count,
        "claimed_tickets": claimed_count,
        "closed_tickets": closed_count,
        "tickets_today": today_count,
        "tickets_this_week": week_count,
        "tickets_last_week": last_week_count,
        "weekly_trend_pct": weekly_trend_pct,
        "avg_response_time_minutes": round(avg_response, 1) if avg_response else None,
        "avg_handle_time_minutes": round(avg_handle, 1) if avg_handle else None,
        "daily_activity": daily_activity,
        "category_breakdown": category_breakdown,
        "top_moderators": top_moderators,
    }

    logger.debug("Ticket Stats Fetched", [
        ("User", str(payload.sub)),
        ("Total", str(total_tickets)),
        ("Top Mods", str(len(top_moderators))),
    ])

    return TicketStatsResponse(data=stats)


# =============================================================================
# Individual Ticket
# =============================================================================

@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: str,
    request: "Request",
    token: Optional[str] = Query(None, description="Transcript access token (bypasses auth)"),
    bot: Any = Depends(get_bot),
) -> TicketDetailResponse:
    """Get detailed information about a specific ticket."""
    from fastapi.security import HTTPBearer
    ticket_id = ticket_id.upper()

    # Check for transcript token access (no auth required)
    has_transcript_access = verify_transcript_access(ticket_id, token)

    # If no transcript token, require normal auth
    if not has_transcript_access:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise APIError(ErrorCode.AUTH_MISSING_TOKEN)

        jwt_token = auth_header.split(" ", 1)[1]
        auth_service = get_auth_service()
        payload = auth_service.get_token_payload(jwt_token)

        if payload is None:
            raise APIError(ErrorCode.AUTH_INVALID_TOKEN)

    db = get_db()
    user_cache = UserInfoCache(bot)

    row = db.fetchone(
        """SELECT ticket_id, thread_id, user_id, claimed_by, status, priority,
                  subject, category, created_at, claimed_at, closed_at, close_reason
           FROM tickets WHERE ticket_id = ?""",
        (ticket_id,)
    )

    if not row:
        logger.debug("Ticket Not Found", [
            ("Ticket ID", ticket_id),
            ("Access", "transcript_token" if has_transcript_access else "authenticated"),
        ])
        raise APIError(ErrorCode.TICKET_NOT_FOUND)

    # Prefetch both users
    await user_cache.prefetch([row["user_id"], row["claimed_by"]] if row["claimed_by"] else [row["user_id"]])

    user_info = await user_cache.get(row["user_id"])
    claimer_info = await user_cache.get(row["claimed_by"]) if row["claimed_by"] else {}

    message_count = db.fetchone(
        "SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = ?",
        (ticket_id,)
    )[0]

    ticket = {
        "ticket_id": row["ticket_id"],
        "channel_id": row["thread_id"],
        "user_id": row["user_id"],
        "user_name": user_info.get("name"),
        "user_avatar": user_info.get("avatar"),
        "claimed_by": row["claimed_by"],
        "claimer_name": claimer_info.get("name"),
        "status": row["status"] or "open",
        "priority": row["priority"],
        "subject": row["subject"],
        "category": row["category"],
        "created_at": _to_iso(row["created_at"]),
        "claimed_at": _to_iso(row["claimed_at"]) if row["claimed_at"] else None,
        "closed_at": _to_iso(row["closed_at"]) if row["closed_at"] else None,
        "close_reason": row["close_reason"],
        "message_count": message_count,
    }

    logger.debug("Ticket Fetched", [
        ("Ticket ID", ticket_id),
        ("Access", "transcript_token" if has_transcript_access else "authenticated"),
    ])

    return TicketDetailResponse(data=ticket)


@router.get("/{ticket_id}/messages", response_model=TicketMessagesResponse)
async def get_ticket_messages(
    ticket_id: str,
    request: Request,
    token: Optional[str] = Query(None, description="Transcript access token (bypasses auth)"),
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
) -> TicketMessagesResponse:
    """Get messages for a specific ticket."""
    ticket_id = ticket_id.upper()

    # Check for transcript token access (no auth required)
    has_transcript_access = verify_transcript_access(ticket_id, token)

    # If no transcript token, require normal auth
    if not has_transcript_access:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise APIError(ErrorCode.AUTH_MISSING_TOKEN)

        jwt_token = auth_header.split(" ", 1)[1]
        auth_service = get_auth_service()
        payload = auth_service.get_token_payload(jwt_token)

        if payload is None:
            raise APIError(ErrorCode.AUTH_INVALID_TOKEN)

    db = get_db()
    user_cache = UserInfoCache(bot)

    # Verify ticket exists
    ticket = db.fetchone("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,))
    if not ticket:
        raise APIError(ErrorCode.TICKET_NOT_FOUND)

    total = db.fetchone(
        "SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = ?",
        (ticket_id,)
    )[0]

    rows = db.fetchall(
        """SELECT message_id, author_id, content, created_at, is_staff
           FROM ticket_messages
           WHERE ticket_id = ?
           ORDER BY created_at ASC
           LIMIT ? OFFSET ?""",
        (ticket_id, pagination.per_page, pagination.offset)
    )

    # Prefetch all authors
    author_ids = [row["author_id"] for row in rows if row["author_id"]]
    await user_cache.prefetch(author_ids)

    messages = []
    for row in rows:
        author_info = await user_cache.get(row["author_id"])
        messages.append({
            "message_id": row["message_id"],
            "author_id": row["author_id"],
            "author_name": author_info.get("name"),
            "author_avatar": author_info.get("avatar"),
            "content": row["content"],
            "created_at": _to_iso(row["created_at"]),
            "is_staff": bool(row["is_staff"]) if row["is_staff"] else False,
        })

    total_pages = (total + pagination.per_page - 1) // pagination.per_page

    logger.debug("Ticket Messages Fetched", [
        ("Ticket ID", ticket_id),
        ("Messages", str(len(messages))),
    ])

    return TicketMessagesResponse(
        data=messages,
        total=total,
        total_pages=total_pages,
        page=pagination.page,
        per_page=pagination.per_page,
    )


__all__ = ["router"]
