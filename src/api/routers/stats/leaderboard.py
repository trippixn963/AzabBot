"""
AzabBot - Leaderboard Router
============================

Leaderboard and user summary endpoints (public, no auth required).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import Any

import discord
from fastapi import APIRouter, Depends, Query

from src.core.logger import logger
from src.core.config import NY_TZ, has_mod_role
from src.api.dependencies import get_bot, get_pagination, PaginationParams
from src.api.models.base import PaginatedResponse, ModeratorBrief
from src.api.models.stats import LeaderboardEntry, UserSummaryResponse
from src.api.utils.pagination import create_paginated_response
from src.api.utils.discord import batch_fetch_users, format_relative_time
from src.core.database import get_db


router = APIRouter(tags=["Statistics"])


@router.get("/leaderboard", response_model=PaginatedResponse[LeaderboardEntry])
async def get_leaderboard(
    period: str = Query("month", description="Time period: week, month, year, all"),
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
) -> PaginatedResponse[LeaderboardEntry]:
    """
    Get moderator leaderboard rankings (public endpoint).

    Ranked by weighted score of moderation actions.
    Only includes moderators who are currently in the ops server.
    """
    db = get_db()
    now = time.time()

    # Get ops guild for member filtering
    guild = None
    if bot and hasattr(bot, 'config') and bot.config.main_guild_id:
        guild = bot.get_guild(bot.config.main_guild_id)

    # Calculate time range
    period_offsets = {"week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
    start_time = now - period_offsets.get(period, 0) if period in period_offsets else 0

    # Get moderator stats with scoring
    # Weights: ban=5, kick=3, mute=2, warn=1
    all_rows = db.fetchall(
        """
        SELECT
            moderator_id,
            COUNT(*) as total_actions,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
            SUM(CASE WHEN action_type = 'kick' THEN 1 ELSE 0 END) as kicks,
            (SUM(CASE WHEN action_type = 'ban' THEN 5 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'kick' THEN 3 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'mute' THEN 2 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END)) as score
        FROM cases
        WHERE created_at >= ?
        GROUP BY moderator_id
        ORDER BY score DESC
        """,
        (start_time,)
    )

    # Filter to only include users who currently have mod role
    if guild:
        # Build set of user IDs who currently have mod access
        current_mod_ids = {m.id for m in guild.members if has_mod_role(m)}
        all_rows = [row for row in all_rows if row["moderator_id"] in current_mod_ids]

    total = len(all_rows)

    # Paginate
    start_idx = pagination.offset
    end_idx = start_idx + pagination.per_page
    page_rows = all_rows[start_idx:end_idx]

    # Batch fetch moderator info
    mod_ids = [row["moderator_id"] for row in page_rows]
    user_info = await batch_fetch_users(bot, mod_ids)

    # Get tickets closed for all mods on this page in a single query
    if mod_ids:
        placeholders = ",".join("?" * len(mod_ids))
        ticket_rows = db.fetchall(
            f"""
            SELECT claimed_by, COUNT(*) as closed
            FROM tickets
            WHERE claimed_by IN ({placeholders})
              AND status = 'closed'
              AND closed_at >= ?
            GROUP BY claimed_by
            """,
            (*mod_ids, start_time)
        )
        tickets_map = {row["claimed_by"]: row["closed"] for row in ticket_rows}
    else:
        tickets_map = {}

    # Build entries
    entries = []
    for idx, row in enumerate(page_rows, start=start_idx + 1):
        mod_id = row["moderator_id"]
        mod_name, mod_avatar = user_info.get(mod_id, (None, None))
        tickets_closed = tickets_map.get(mod_id, 0)

        # Add ticket score (2 points per ticket)
        final_score = row["score"] + (tickets_closed * 2)

        entries.append(LeaderboardEntry(
            rank=idx,
            moderator=ModeratorBrief(
                discord_id=str(mod_id),
                username=mod_name,
                avatar_url=mod_avatar,
            ),
            total_actions=row["total_actions"],
            mutes=row["mutes"],
            bans=row["bans"],
            tickets_closed=tickets_closed,
            score=final_score,
        ))

    logger.debug("Leaderboard Fetched", [
        ("Period", period),
        ("Page", str(pagination.page)),
        ("Results", str(len(entries))),
        ("Total", str(total)),
    ])

    return create_paginated_response(entries, total, pagination)


@router.get("/user/{user_id}", response_model=UserSummaryResponse)
async def get_public_user_summary(
    user_id: int,
    bot: Any = Depends(get_bot),
) -> UserSummaryResponse:
    """
    Get public user summary for leaderboard user cards.

    Returns basic info, case stats, and moderation status.
    No authentication required.
    """
    db = get_db()
    config = None
    try:
        from src.core.config import get_config
        config = get_config()
    except (ImportError, RuntimeError):
        pass

    now = time.time()
    user = None
    member = None

    # Try to fetch user from Discord
    try:
        user = await bot.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        pass

    # Try to get member from guild
    guild_id = config.main_guild_id if config else None
    if user and guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(user_id)

    # Get case stats
    stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans,
            MIN(created_at) as first_case,
            MAX(created_at) as last_case
        FROM cases
        WHERE user_id = ?
        """,
        (user_id,)
    )

    total_cases = stats[0] or 0
    total_warns = stats[1] or 0
    total_mutes = stats[2] or 0
    total_bans = stats[3] or 0
    first_case_at = stats[4]
    last_case_at = stats[5]

    # Check for active mute
    active_mute = db.fetchone(
        """
        SELECT expires_at FROM active_mutes
        WHERE user_id = ? AND unmuted = 0
        AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY muted_at DESC LIMIT 1
        """,
        (user_id, now)
    )
    is_muted = active_mute is not None
    mute_expires_at = None
    if active_mute and active_mute[0]:
        mute_expires_at = datetime.utcfromtimestamp(active_mute[0]).isoformat() + "Z"

    # Check for active ban
    is_banned = False
    if guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
                is_banned = ban_entry is not None
            except (discord.NotFound, discord.HTTPException):
                pass

    # Get recent cases (last 5)
    recent_rows = db.fetchall(
        """
        SELECT case_id, action_type, reason, moderator_id, created_at
        FROM cases
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (user_id,)
    )

    # Batch fetch moderator names
    mod_ids = [row["moderator_id"] for row in recent_rows if row["moderator_id"]]
    mod_info = await batch_fetch_users(bot, mod_ids)

    recent_cases = []
    for row in recent_rows:
        mod_name, _ = mod_info.get(row["moderator_id"], (None, None))
        recent_cases.append({
            "case_id": row["case_id"],
            "type": row["action_type"],
            "reason": (row["reason"][:80] + "...") if row["reason"] and len(row["reason"]) > 80 else row["reason"],
            "moderator": mod_name or f"Mod {row['moderator_id']}",
            "time": format_relative_time(row["created_at"], now),
        })

    logger.debug("Public User Summary Fetched", [
        ("User ID", str(user_id)),
        ("Username", user.name if user else f"User {user_id}"),
        ("Cases", str(total_cases)),
        ("In Server", str(member is not None)),
    ])

    return UserSummaryResponse(
        user_id=str(user_id),
        username=user.name if user else f"User {user_id}",
        display_name=user.display_name if user else None,
        avatar_url=str(user.display_avatar.url) if user and user.display_avatar else None,
        in_server=member is not None,
        account_created_at=user.created_at.isoformat() + "Z" if user and user.created_at else None,
        joined_server_at=member.joined_at.isoformat() + "Z" if member and member.joined_at else None,
        account_age_days=(datetime.now(NY_TZ) - user.created_at.replace(tzinfo=None)).days if user and user.created_at else 0,
        server_tenure_days=(datetime.now(NY_TZ) - member.joined_at.replace(tzinfo=None)).days if member and member.joined_at else 0,
        is_muted=is_muted,
        is_banned=is_banned,
        mute_expires_at=mute_expires_at,
        total_cases=total_cases,
        total_warns=total_warns,
        total_mutes=total_mutes,
        total_bans=total_bans,
        first_case_at=datetime.utcfromtimestamp(first_case_at).isoformat() + "Z" if first_case_at else None,
        last_case_at=datetime.utcfromtimestamp(last_case_at).isoformat() + "Z" if last_case_at else None,
        recent_cases=recent_cases,
    )


__all__ = ["router"]
