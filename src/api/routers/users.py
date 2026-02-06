"""
AzabBot - Users Router
======================

User profile and moderation history endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime
from typing import Any, List, Optional

import discord
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.status import HTTP_404_NOT_FOUND

from src.core.logger import logger
from src.core.config import get_config
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.users import UserProfile, UserSearchResult, ModerationNote
from src.api.models.cases import CaseBrief, CaseType, CaseStatus
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.core.database import get_db


router = APIRouter(prefix="/users", tags=["Users"])


# =============================================================================
# Lookup Cache
# =============================================================================

LOOKUP_CACHE_TTL = 60  # 1 minute cache


class LookupCache:
    """Simple TTL cache for user lookups."""

    def __init__(self):
        self._cache: dict[int, tuple[float, dict]] = {}  # user_id -> (timestamp, data)

    def get(self, user_id: int) -> Optional[dict]:
        """Get cached data if still valid."""
        if user_id not in self._cache:
            return None
        cached_at, data = self._cache[user_id]
        if time.time() - cached_at > LOOKUP_CACHE_TTL:
            del self._cache[user_id]
            return None
        return data

    def set(self, user_id: int, data: dict) -> None:
        """Cache lookup result."""
        self._cache[user_id] = (time.time(), data)

    def invalidate(self, user_id: int) -> None:
        """Remove cached data."""
        self._cache.pop(user_id, None)


_lookup_cache = LookupCache()


# =============================================================================
# Lookup Models
# =============================================================================

class UserPunishment(BaseModel):
    """A punishment/case in user's history."""

    case_id: str = Field(description="Case ID")
    action_type: str = Field(description="Type: warn, mute, ban, kick")
    reason: Optional[str] = Field(None, description="Reason for punishment")
    moderator_id: str = Field(description="Moderator Discord ID")
    moderator_name: Optional[str] = Field(None, description="Moderator username")
    created_at: str = Field(description="ISO timestamp")
    expires_at: Optional[str] = Field(None, description="ISO timestamp if temporary")
    is_active: bool = Field(False, description="Whether punishment is currently active")


class UserLookupResult(BaseModel):
    """Full user lookup result."""

    discord_id: str = Field(description="Discord user ID as string")
    username: str = Field(description="Discord username")
    display_name: str = Field(description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    joined_server_at: Optional[str] = Field(None, description="ISO timestamp")
    account_created_at: Optional[str] = Field(None, description="ISO timestamp")
    is_muted: bool = Field(False, description="Currently muted")
    is_banned: bool = Field(False, description="Currently banned")
    mute_expires_at: Optional[str] = Field(None, description="ISO timestamp")
    total_cases: int = Field(0, description="Total cases")
    total_warns: int = Field(0, description="Total warnings")
    total_mutes: int = Field(0, description="Total mutes")
    total_bans: int = Field(0, description="Total bans")
    punishments: List[UserPunishment] = Field(default_factory=list, description="Punishment history")


# =============================================================================
# Lookup Helpers
# =============================================================================

async def _batch_fetch_moderators(bot: Any, mod_ids: set[int]) -> dict[int, str]:
    """
    Batch fetch moderator names. Returns dict of mod_id -> username.
    Uses bot cache first, then fetches missing ones concurrently.
    """
    result = {}
    to_fetch = []

    # First pass: check bot cache
    for mod_id in mod_ids:
        cached = bot.get_user(mod_id)
        if cached:
            result[mod_id] = cached.name
        else:
            to_fetch.append(mod_id)

    # Fetch missing ones concurrently (max 10 at a time to avoid rate limits)
    if to_fetch:
        async def fetch_one(uid: int) -> tuple[int, Optional[str]]:
            try:
                user = await bot.fetch_user(uid)
                return (uid, user.name if user else None)
            except Exception:
                return (uid, None)

        # Batch in groups of 10
        for i in range(0, len(to_fetch), 10):
            batch = to_fetch[i:i+10]
            fetched = await asyncio.gather(*[fetch_one(uid) for uid in batch])
            for uid, name in fetched:
                if name:
                    result[uid] = name

    return result


# =============================================================================
# Lookup
# =============================================================================

@router.get("/lookup", response_model=APIResponse[UserLookupResult])
async def lookup_user(
    query: str = Query(..., min_length=1, description="Discord ID or username"),
    refresh: bool = Query(False, description="Bypass cache"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[UserLookupResult]:
    """
    Look up a user by Discord ID or username.

    Returns comprehensive user info including punishment history.
    Use ?refresh=true to bypass cache.
    """
    db = get_db()
    config = get_config()
    user: Optional[discord.User] = None
    member: Optional[discord.Member] = None
    user_id: Optional[int] = None

    # Try to parse as Discord ID first
    try:
        user_id = int(query)
    except ValueError:
        pass

    # Check cache if we have a user_id and not refreshing
    if user_id and not refresh:
        cached = _lookup_cache.get(user_id)
        if cached:
            logger.debug("User Lookup Cache Hit", [
                ("User ID", str(user_id)),
            ])
            return APIResponse(success=True, data=UserLookupResult(**cached))

    # Fetch user by ID
    if user_id:
        try:
            user = await bot.fetch_user(user_id)
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            logger.warning("User Lookup Fetch Failed", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:50]),
            ])

    # If not found by ID, search guild members by name
    if not user and config.logging_guild_id:
        guild = bot.get_guild(config.logging_guild_id)
        if guild:
            query_lower = query.lower()
            # Use discord.utils.find for cleaner search
            member = discord.utils.find(
                lambda m: (query_lower in m.name.lower() or
                          query_lower in m.display_name.lower()),
                guild.members
            )
            if member:
                user = member
                user_id = member.id

    if not user:
        logger.debug("User Lookup Not Found", [
            ("Query", query[:30]),
            ("Requested By", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"User not found: {query}",
        )

    user_id = user.id
    now = datetime.utcnow().timestamp()

    # Get member from guild if not already fetched
    if not member and config.logging_guild_id:
        guild = bot.get_guild(config.logging_guild_id)
        if guild:
            member = guild.get_member(user_id)

    # Get all case stats in one optimized query
    stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans
        FROM cases
        WHERE user_id = ?
        """,
        (user_id,)
    )

    total_cases = stats[0] or 0
    total_warns = stats[1] or 0
    total_mutes = stats[2] or 0
    total_bans = stats[3] or 0

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
        mute_expires_at = datetime.utcfromtimestamp(active_mute[0]).isoformat()

    # Check for active ban
    is_banned = False
    if config.logging_guild_id:
        guild = bot.get_guild(config.logging_guild_id)
        if guild:
            try:
                ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
                is_banned = ban_entry is not None
            except discord.NotFound:
                is_banned = False
            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass

    # Get punishment history (last 50 cases)
    case_rows = db.fetchall(
        """
        SELECT case_id, action_type, reason, moderator_id, created_at,
               duration_seconds, resolved_at
        FROM cases
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (user_id,)
    )

    # Batch fetch all moderator names (instead of N+1 queries)
    mod_ids = {row[3] for row in case_rows if row[3]}
    mod_names = await _batch_fetch_moderators(bot, mod_ids)

    # Build punishments list
    punishments = []
    for row in case_rows:
        created_ts = row[4]
        duration = row[5]
        resolved_at = row[6]
        mod_id = row[3]

        # Calculate expiry and active status
        expires_at = None
        is_active = False
        if duration and created_ts:
            expires_ts = created_ts + duration
            expires_at = datetime.utcfromtimestamp(expires_ts).isoformat()
            is_active = expires_ts > now and resolved_at is None
        elif resolved_at is None and row[1] in ('mute', 'ban'):
            is_active = True

        punishments.append(UserPunishment(
            case_id=row[0],
            action_type=row[1],
            reason=row[2],
            moderator_id=str(mod_id),
            moderator_name=mod_names.get(mod_id),
            created_at=datetime.utcfromtimestamp(created_ts).isoformat(),
            expires_at=expires_at,
            is_active=is_active,
        ))

    # Build result
    result = UserLookupResult(
        discord_id=str(user.id),
        username=user.name,
        display_name=user.display_name or user.name,
        avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
        joined_server_at=member.joined_at.isoformat() if member and member.joined_at else None,
        account_created_at=user.created_at.isoformat() if user.created_at else None,
        is_muted=is_muted,
        is_banned=is_banned,
        mute_expires_at=mute_expires_at,
        total_cases=total_cases,
        total_warns=total_warns,
        total_mutes=total_mutes,
        total_bans=total_bans,
        punishments=punishments,
    )

    # Cache the result
    _lookup_cache.set(user_id, result.model_dump())

    logger.debug("User Lookup", [
        ("Query", query[:20]),
        ("User ID", str(user_id)),
        ("Cases", str(total_cases)),
        ("Muted", str(is_muted)),
        ("Banned", str(is_banned)),
        ("Requested By", str(payload.sub)),
    ])

    return APIResponse(success=True, data=result)


# =============================================================================
# Search
# =============================================================================

@router.get("/search", response_model=APIResponse[List[UserSearchResult]])
async def search_users(
    query: str = Query(..., min_length=1, description="Search query (name or ID)"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[List[UserSearchResult]]:
    """
    Search for users by name or Discord ID.

    Returns up to 10 matching users from the bot's cache and database.
    """
    results = []
    db = get_db()

    # Try to parse as user ID
    try:
        user_id = int(query)
        user = await bot.fetch_user(user_id)
        if user:
            # Get case count for this user
            case_count = db.fetchone(
                "SELECT COUNT(*) FROM cases WHERE user_id = ?",
                (user_id,)
            )[0]

            results.append(UserSearchResult(
                discord_id=user.id,
                username=user.name,
                display_name=user.display_name,
                avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
                case_count=case_count,
            ))
    except ValueError:
        pass

    # Search in database for users with cases
    if len(results) < 10:
        # Search in cases table by user name if we have cached names
        # For now, just return users with cases matching the query
        case_users = db.fetchall(
            """SELECT DISTINCT user_id, COUNT(*) as case_count
               FROM cases
               GROUP BY user_id
               ORDER BY case_count DESC
               LIMIT 20"""
        )

        for row in case_users:
            if len(results) >= 10:
                break

            user_id = row["user_id"]

            # Skip if already in results
            if any(r.discord_id == user_id for r in results):
                continue

            try:
                user = await bot.fetch_user(user_id)
                if user and (query.lower() in user.name.lower() or query.lower() in user.display_name.lower()):
                    results.append(UserSearchResult(
                        discord_id=user.id,
                        username=user.name,
                        display_name=user.display_name,
                        avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
                        case_count=row["case_count"],
                    ))
            except Exception:
                continue

    logger.debug("User Search", [
        ("User", str(payload.sub)),
        ("Query", query[:20]),
        ("Results", str(len(results))),
    ])

    return APIResponse(success=True, data=results)


# =============================================================================
# User Profile
# =============================================================================

@router.get("/{user_id}", response_model=APIResponse[UserProfile])
async def get_user_profile(
    user_id: int,
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[UserProfile]:
    """
    Get a user's moderation profile.

    Includes case counts, active punishments, and notes.
    """
    db = get_db()

    # Fetch user from Discord
    try:
        user = await bot.fetch_user(user_id)
    except Exception:
        logger.debug("User Profile Not Found", [
            ("User ID", str(user_id)),
            ("Requested By", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    now = datetime.utcnow().timestamp()

    # Get case counts by type
    case_counts = db.fetchall(
        "SELECT action_type, COUNT(*) as count FROM cases WHERE user_id = ? GROUP BY action_type",
        (user_id,)
    )
    count_map = {row["action_type"]: row["count"] for row in case_counts}

    # Check for active punishments
    active_mute = db.fetchone(
        """SELECT case_id, expires_at FROM cases
           WHERE user_id = ? AND action_type = 'mute'
           AND (expires_at IS NULL OR expires_at > ?)
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, now)
    )

    active_ban = db.fetchone(
        """SELECT case_id, expires_at FROM cases
           WHERE user_id = ? AND action_type = 'ban'
           AND (expires_at IS NULL OR expires_at > ?)
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, now)
    )

    # Get pending appeal
    pending_appeal = db.fetchone(
        "SELECT appeal_id FROM appeals WHERE user_id = ? AND status = 'pending' LIMIT 1",
        (user_id,)
    )

    # Get notes count
    notes_count = db.fetchone(
        "SELECT COUNT(*) FROM moderation_notes WHERE user_id = ?",
        (user_id,)
    )[0]

    # Get tickets count
    tickets_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE user_id = ?",
        (user_id,)
    )[0]

    # First seen (oldest case)
    first_case = db.fetchone(
        "SELECT MIN(created_at) FROM cases WHERE user_id = ?",
        (user_id,)
    )
    first_seen = datetime.fromtimestamp(first_case[0]) if first_case and first_case[0] else None

    profile = UserProfile(
        discord_id=user.id,
        username=user.name,
        display_name=user.display_name,
        avatar_url=str(user.display_avatar.url) if user.display_avatar else None,
        created_at=user.created_at,
        total_cases=sum(count_map.values()),
        total_warns=count_map.get("warn", 0),
        total_mutes=count_map.get("mute", 0),
        total_bans=count_map.get("ban", 0),
        total_kicks=count_map.get("kick", 0),
        is_muted=active_mute is not None,
        mute_expires_at=datetime.fromtimestamp(active_mute["expires_at"]) if active_mute and active_mute["expires_at"] else None,
        is_banned=active_ban is not None,
        ban_expires_at=datetime.fromtimestamp(active_ban["expires_at"]) if active_ban and active_ban["expires_at"] else None,
        has_pending_appeal=pending_appeal is not None,
        notes_count=notes_count,
        tickets_count=tickets_count,
        first_seen=first_seen,
    )

    logger.debug("User Profile Fetched", [
        ("User ID", str(user_id)),
        ("Requested By", str(payload.sub)),
        ("Cases", str(profile.total_cases)),
        ("Muted", str(profile.is_muted)),
        ("Banned", str(profile.is_banned)),
    ])

    return APIResponse(success=True, data=profile)


# =============================================================================
# User Cases
# =============================================================================

@router.get("/{user_id}/cases", response_model=PaginatedResponse[List[CaseBrief]])
async def get_user_cases(
    user_id: int,
    pagination: PaginationParams = Depends(get_pagination),
    case_type: Optional[CaseType] = Query(None, description="Filter by case type"),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[CaseBrief]]:
    """
    Get a user's moderation case history.
    """
    db = get_db()

    # Build query
    conditions = ["user_id = ?"]
    params = [user_id]

    if case_type:
        conditions.append("action_type = ?")
        params.append(case_type.value)

    where_clause = " AND ".join(conditions)

    # Get total count
    total = db.fetchone(
        f"SELECT COUNT(*) FROM cases WHERE {where_clause}",
        params
    )[0]

    # Get cases
    query = f"""
        SELECT case_id, user_id, moderator_id, action_type, reason, created_at, expires_at
        FROM cases
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([pagination.per_page, pagination.offset])
    rows = db.fetchall(query, params)

    cases = []
    for row in rows:
        expires_at = datetime.fromtimestamp(row["expires_at"]) if row["expires_at"] else None
        status = CaseStatus.ACTIVE
        if expires_at and expires_at <= datetime.utcnow():
            status = CaseStatus.EXPIRED

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

    logger.debug("User Cases Fetched", [
        ("User ID", str(user_id)),
        ("Requested By", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(cases))),
        ("Total", str(total)),
    ])

    return create_paginated_response(cases, total, pagination)


# =============================================================================
# User Notes
# =============================================================================

@router.get("/{user_id}/notes", response_model=PaginatedResponse[List[ModerationNote]])
async def get_user_notes(
    user_id: int,
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[ModerationNote]]:
    """
    Get moderation notes for a user.
    """
    db = get_db()

    # Get total count
    total = db.fetchone(
        "SELECT COUNT(*) FROM moderation_notes WHERE user_id = ?",
        (user_id,)
    )[0]

    # Get notes
    rows = db.fetchall(
        """SELECT note_id, author_id, content, created_at
           FROM moderation_notes
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, pagination.per_page, pagination.offset)
    )

    notes = []
    for row in rows:
        # Get author info
        author_name = None
        try:
            author = await bot.fetch_user(row["author_id"])
            author_name = author.name
        except Exception:
            pass

        notes.append(ModerationNote(
            note_id=row["note_id"],
            user_id=user_id,
            author_id=row["author_id"],
            author_name=author_name,
            content=row["content"],
            created_at=datetime.fromtimestamp(row["created_at"]),
        ))

    logger.debug("User Notes Fetched", [
        ("User ID", str(user_id)),
        ("Requested By", str(payload.sub)),
        ("Page", str(pagination.page)),
        ("Results", str(len(notes))),
        ("Total", str(total)),
    ])

    return create_paginated_response(notes, total, pagination)


__all__ = ["router"]
