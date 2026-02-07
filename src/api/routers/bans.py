"""
AzabBot - Bans Router
=====================

Endpoint for fetching banned users list.
Uses cached ban data from database, synced via Discord events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Any, Optional

import discord
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.api.dependencies import get_bot, require_auth
from src.api.models.auth import TokenPayload


router = APIRouter(prefix="/bans", tags=["Bans"])


# =============================================================================
# Get Banned Users (from database cache)
# =============================================================================

@router.get("")
async def get_banned_users(
    search: Optional[str] = Query(None, description="Search by username or user ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    auth: TokenPayload = Depends(require_auth),
    bot: Any = Depends(get_bot),
) -> JSONResponse:
    """
    Get list of banned users.

    Uses ban_history table for fast queries.
    Only returns users who are currently banned (latest action = 'ban').
    """
    db = get_db()
    config = get_config()
    guild_id = config.logging_guild_id

    offset = (page - 1) * per_page

    # Build query - get users whose most recent ban_history entry is 'ban' (not 'unban')
    # This avoids fetching from Discord API on every request
    if search:
        search_pattern = f"%{search}%"
        # Search by user_id or check user_snapshots for username
        count_row = db.fetchone(
            """
            SELECT COUNT(DISTINCT bh.user_id) as total
            FROM ban_history bh
            WHERE bh.guild_id = ?
            AND bh.id = (
                SELECT MAX(bh2.id) FROM ban_history bh2
                WHERE bh2.user_id = bh.user_id AND bh2.guild_id = bh.guild_id
            )
            AND bh.action = 'ban'
            AND (
                CAST(bh.user_id AS TEXT) LIKE ?
                OR EXISTS (
                    SELECT 1 FROM user_snapshots us
                    WHERE us.user_id = bh.user_id
                    AND (us.username LIKE ? OR us.display_name LIKE ?)
                )
            )
            """,
            (guild_id, search_pattern, search_pattern, search_pattern)
        )
        total = count_row["total"] if count_row else 0

        rows = db.fetchall(
            """
            SELECT
                bh.user_id,
                bh.moderator_id,
                bh.reason,
                bh.timestamp,
                us.username,
                us.display_name,
                us.avatar_url
            FROM ban_history bh
            LEFT JOIN user_snapshots us ON us.user_id = bh.user_id AND us.guild_id = bh.guild_id
            WHERE bh.guild_id = ?
            AND bh.id = (
                SELECT MAX(bh2.id) FROM ban_history bh2
                WHERE bh2.user_id = bh.user_id AND bh2.guild_id = bh.guild_id
            )
            AND bh.action = 'ban'
            AND (
                CAST(bh.user_id AS TEXT) LIKE ?
                OR us.username LIKE ?
                OR us.display_name LIKE ?
            )
            ORDER BY bh.timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (guild_id, search_pattern, search_pattern, search_pattern, per_page, offset)
        )
    else:
        count_row = db.fetchone(
            """
            SELECT COUNT(DISTINCT bh.user_id) as total
            FROM ban_history bh
            WHERE bh.guild_id = ?
            AND bh.id = (
                SELECT MAX(bh2.id) FROM ban_history bh2
                WHERE bh2.user_id = bh.user_id AND bh2.guild_id = bh.guild_id
            )
            AND bh.action = 'ban'
            """,
            (guild_id,)
        )
        total = count_row["total"] if count_row else 0

        rows = db.fetchall(
            """
            SELECT
                bh.user_id,
                bh.moderator_id,
                bh.reason,
                bh.timestamp,
                us.username,
                us.display_name,
                us.avatar_url
            FROM ban_history bh
            LEFT JOIN user_snapshots us ON us.user_id = bh.user_id AND us.guild_id = bh.guild_id
            WHERE bh.guild_id = ?
            AND bh.id = (
                SELECT MAX(bh2.id) FROM ban_history bh2
                WHERE bh2.user_id = bh.user_id AND bh2.guild_id = bh.guild_id
            )
            AND bh.action = 'ban'
            ORDER BY bh.timestamp DESC
            LIMIT ? OFFSET ?
            """,
            (guild_id, per_page, offset)
        )

    # Collect unique moderator IDs for batch lookup
    mod_ids = set()
    for row in rows:
        if row["moderator_id"]:
            mod_ids.add(row["moderator_id"])

    # Batch fetch moderator info from snapshots
    mod_info = {}
    if mod_ids:
        mod_rows = db.fetchall(
            f"""
            SELECT user_id, username, display_name, avatar_url
            FROM user_snapshots
            WHERE user_id IN ({','.join('?' * len(mod_ids))})
            """,
            tuple(mod_ids)
        )
        for mr in mod_rows:
            mod_info[mr["user_id"]] = {
                "id": str(mr["user_id"]),
                "username": mr["username"],
                "display_name": mr["display_name"],
                "avatar_url": mr["avatar_url"],
            }

    # Build response
    bans = []
    guild = bot.get_guild(guild_id) if bot else None

    for row in rows:
        user_id = row["user_id"]

        # Try to get fresh user info from guild cache, fallback to snapshot
        user_data = None
        if guild:
            # Check if we can get the user from bot's cache (unlikely for banned users)
            cached_user = bot.get_user(user_id)
            if cached_user:
                user_data = {
                    "id": str(cached_user.id),
                    "username": cached_user.name,
                    "display_name": cached_user.display_name,
                    "avatar_url": str(cached_user.display_avatar.url) if cached_user.display_avatar else None,
                    "bot": cached_user.bot,
                }

        if not user_data:
            # Use snapshot data
            user_data = {
                "id": str(user_id),
                "username": row["username"] or f"Unknown User",
                "display_name": row["display_name"] or row["username"] or "Unknown",
                "avatar_url": row["avatar_url"],
                "bot": False,
            }

        ban_entry = {
            "user": user_data,
            "reason": row["reason"] or "No reason provided",
            "banned_at": row["timestamp"],
            "moderator_id": str(row["moderator_id"]) if row["moderator_id"] else None,
        }

        # Add moderator info
        if row["moderator_id"]:
            if row["moderator_id"] in mod_info:
                ban_entry["moderator"] = mod_info[row["moderator_id"]]
            elif guild:
                # Try to get from guild
                mod_member = guild.get_member(row["moderator_id"])
                if mod_member:
                    ban_entry["moderator"] = {
                        "id": str(mod_member.id),
                        "username": mod_member.name,
                        "display_name": mod_member.display_name,
                        "avatar_url": str(mod_member.display_avatar.url) if mod_member.display_avatar else None,
                    }

        bans.append(ban_entry)

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    logger.tree("Bans List Fetched", [
        ("Total", str(total)),
        ("Page", f"{page}/{total_pages}"),
        ("Requested By", str(auth.sub)),
    ], emoji="🔨")

    return JSONResponse(content={
        "success": True,
        "data": {
            "bans": bans,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
        },
    })


@router.get("/sync")
async def sync_bans(
    auth: TokenPayload = Depends(require_auth),
    bot: Any = Depends(get_bot),
) -> JSONResponse:
    """
    Sync bans from Discord to database.

    Use this to populate initial ban data or resync after issues.
    This is an admin operation that may take time for large ban lists.
    """
    config = get_config()
    db = get_db()

    guild_id = config.logging_guild_id
    if not guild_id:
        raise HTTPException(status_code=500, detail="Guild not configured")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPException(status_code=500, detail="Guild not found")

    synced = 0
    errors = 0

    try:
        async for ban_entry in guild.bans(limit=None):
            user = ban_entry.user
            reason = ban_entry.reason

            # Check if we have a ban record for this user
            existing = db.fetchone(
                """SELECT id FROM ban_history
                   WHERE user_id = ? AND guild_id = ? AND action = 'ban'
                   ORDER BY timestamp DESC LIMIT 1""",
                (user.id, guild_id)
            )

            if not existing:
                # Add ban record (we don't know who banned or when, so use defaults)
                try:
                    db.execute(
                        """INSERT INTO ban_history
                           (user_id, guild_id, moderator_id, action, reason, timestamp)
                           VALUES (?, ?, ?, 'ban', ?, ?)""",
                        (user.id, guild_id, bot.user.id, reason, time.time())
                    )
                    synced += 1
                except Exception:
                    errors += 1

            # Also save user snapshot if we don't have one
            snapshot_exists = db.fetchone(
                "SELECT 1 FROM user_snapshots WHERE user_id = ? AND guild_id = ?",
                (user.id, guild_id)
            )
            if not snapshot_exists:
                try:
                    db.execute(
                        """INSERT INTO user_snapshots
                           (user_id, guild_id, username, display_name, avatar_url,
                            snapshot_reason, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, 'ban_sync', ?, ?)""",
                        (user.id, guild_id, user.name, user.display_name,
                         str(user.display_avatar.url) if user.display_avatar else None,
                         time.time(), time.time())
                    )
                except Exception:
                    pass  # Snapshot is optional

        logger.tree("Bans Synced", [
            ("Synced", str(synced)),
            ("Errors", str(errors)),
            ("Requested By", str(auth.sub)),
        ], emoji="🔄")

        return JSONResponse(content={
            "success": True,
            "data": {
                "synced": synced,
                "errors": errors,
            },
        })

    except Exception as e:
        logger.error("Ban sync failed", [("Error", str(e)[:100])])
        raise HTTPException(status_code=500, detail="Sync failed")


@router.get("/{user_id}")
async def get_ban_details(
    user_id: int,
    auth: TokenPayload = Depends(require_auth),
    bot: Any = Depends(get_bot),
) -> JSONResponse:
    """
    Get ban history for a specific user.
    """
    config = get_config()
    db = get_db()
    guild_id = config.logging_guild_id

    # Get all ban history for this user
    history = db.fetchall(
        """SELECT moderator_id, reason, timestamp, action
           FROM ban_history
           WHERE user_id = ? AND guild_id = ?
           ORDER BY timestamp DESC""",
        (user_id, guild_id)
    )

    if not history:
        raise HTTPException(status_code=404, detail="No ban history found")

    # Get user snapshot
    user_snapshot = db.fetchone(
        "SELECT * FROM user_snapshots WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id)
    )

    # Try to get fresh user info
    user_data = None
    if bot:
        cached_user = bot.get_user(user_id)
        if cached_user:
            user_data = {
                "id": str(cached_user.id),
                "username": cached_user.name,
                "display_name": cached_user.display_name,
                "avatar_url": str(cached_user.display_avatar.url) if cached_user.display_avatar else None,
            }

    if not user_data and user_snapshot:
        user_data = {
            "id": str(user_id),
            "username": user_snapshot["username"] or "Unknown",
            "display_name": user_snapshot["display_name"] or "Unknown",
            "avatar_url": user_snapshot["avatar_url"],
        }
    elif not user_data:
        user_data = {
            "id": str(user_id),
            "username": "Unknown User",
            "display_name": "Unknown",
            "avatar_url": None,
        }

    # Check if currently banned (latest action is 'ban')
    is_banned = history[0]["action"] == "ban" if history else False

    # Build history with moderator info
    history_list = []
    guild = bot.get_guild(guild_id) if bot else None

    for record in history:
        entry = {
            "action": record["action"],
            "reason": record["reason"] or "No reason",
            "timestamp": record["timestamp"],
            "moderator_id": str(record["moderator_id"]) if record["moderator_id"] else None,
        }

        if record["moderator_id"] and guild:
            mod = guild.get_member(record["moderator_id"])
            if mod:
                entry["moderator"] = {
                    "id": str(mod.id),
                    "username": mod.name,
                    "display_name": mod.display_name,
                }

        history_list.append(entry)

    return JSONResponse(content={
        "success": True,
        "data": {
            "user": user_data,
            "is_banned": is_banned,
            "history": history_list,
        },
    })


__all__ = ["router"]
