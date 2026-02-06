"""
AzabBot - Users Router
======================

User profile and moderation history endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, List, Optional

import aiohttp
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
from src.services.user_snapshots import save_user_snapshot as save_snapshot


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

# SyriaBot API for activity stats
SYRIABOT_API_URL = "http://localhost:8088/api/syria/user"


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


class ChannelActivity(BaseModel):
    """User's activity in a channel."""

    channel_id: str = Field(description="Channel ID")
    channel_name: str = Field(description="Channel name")
    message_count: int = Field(0, description="Messages in this channel")


class UserRole(BaseModel):
    """User's role info."""

    id: str = Field(description="Role ID")
    name: str = Field(description="Role name")
    color: str = Field(description="Role color hex")
    position: int = Field(description="Role position")


class UserLookupResult(BaseModel):
    """Full user lookup result."""

    # Basic info
    discord_id: str = Field(description="Discord user ID as string")
    username: str = Field(description="Discord username")
    display_name: str = Field(description="Display name")
    nickname: Optional[str] = Field(None, description="Server-specific nickname")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")

    # Data source indicator
    is_cached: bool = Field(False, description="True if data is from cache (user left/banned)")
    cached_at: Optional[str] = Field(None, description="When the cache was last updated")
    in_server: bool = Field(True, description="Whether user is currently in server")

    # Banner (Nitro feature)
    banner_url: Optional[str] = Field(None, description="Profile banner image URL (Nitro users)")
    banner_color: Optional[str] = Field(None, description="Accent color hex (fallback if no banner)")

    # Account info
    joined_server_at: Optional[str] = Field(None, description="ISO timestamp")
    account_created_at: Optional[str] = Field(None, description="ISO timestamp")
    account_age_days: int = Field(0, description="Account age in days")
    server_tenure_days: int = Field(0, description="Days in server")
    last_seen_at: Optional[str] = Field(None, description="Last activity timestamp")

    # Moderation status
    is_muted: bool = Field(False, description="Currently muted")
    is_banned: bool = Field(False, description="Currently banned")
    mute_expires_at: Optional[str] = Field(None, description="ISO timestamp")

    # Case stats
    total_cases: int = Field(0, description="Total cases")
    total_warns: int = Field(0, description="Total warnings")
    total_mutes: int = Field(0, description="Total mutes")
    total_bans: int = Field(0, description="Total bans")

    # Activity stats (from SyriaBot)
    total_messages: int = Field(0, description="Total messages")
    messages_this_week: int = Field(0, description="Messages in last 7 days")
    messages_this_month: int = Field(0, description="Messages in last 30 days")
    voice_time_seconds: int = Field(0, description="Total voice time in seconds")
    voice_time_formatted: str = Field("0h 0m", description="Formatted voice time")

    # Risk assessment
    risk_score: int = Field(0, description="Risk score 0-100")
    risk_flags: List[str] = Field(default_factory=list, description="Risk indicators")

    # Invite info
    invite_code: Optional[str] = Field(None, description="Invite code used to join")
    invited_by: Optional[str] = Field(None, description="Who invited them (username)")
    invited_by_id: Optional[str] = Field(None, description="Inviter's Discord ID")

    # Roles
    roles: List[UserRole] = Field(default_factory=list, description="User's roles")

    # History
    previous_usernames: List[str] = Field(default_factory=list, description="Previous usernames")
    most_active_channels: List[ChannelActivity] = Field(default_factory=list, description="Top channels")

    # Punishment history
    punishments: List[UserPunishment] = Field(default_factory=list, description="Punishment history")


# =============================================================================
# Lookup Helpers
# =============================================================================

async def _fetch_syriabot_data(user_id: int) -> Optional[dict]:
    """Fetch user activity data from SyriaBot API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SYRIABOT_API_URL}/{user_id}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.warning("SyriaBot API Fetch Failed", [
            ("User ID", str(user_id)),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
    return None


def _get_previous_usernames(db, user_id: int, limit: int = 10) -> List[str]:
    """Get user's previous usernames from history."""
    rows = db.fetchall(
        """
        SELECT DISTINCT username FROM username_history
        WHERE user_id = ? AND username IS NOT NULL
        ORDER BY changed_at DESC
        LIMIT ?
        """,
        (user_id, limit)
    )
    return [row[0] for row in rows if row[0]]


def _get_invite_info(db, user_id: int, guild_id: int) -> tuple[Optional[str], Optional[int]]:
    """Get invite code and inviter ID for a user."""
    row = db.fetchone(
        """
        SELECT invite_code, inviter_id FROM user_join_info
        WHERE user_id = ? AND guild_id = ?
        """,
        (user_id, guild_id)
    )
    if row:
        return row[0], row[1]
    return None, None


def _get_user_roles(member: Optional[discord.Member]) -> List[UserRole]:
    """Get user's roles sorted by position."""
    if not member:
        return []

    roles = []
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.name == "@everyone":
            continue
        color_hex = f"#{role.color.value:06x}" if role.color.value else "#99aab5"
        roles.append(UserRole(
            id=str(role.id),
            name=role.name,
            color=color_hex,
            position=role.position,
        ))
    return roles


def _roles_from_snapshot(snapshot: dict) -> List[UserRole]:
    """Convert snapshot roles to UserRole list."""
    roles = []
    for role_data in snapshot.get("roles", []):
        roles.append(UserRole(
            id=role_data.get("id", "0"),
            name=role_data.get("name", "Unknown"),
            color=role_data.get("color", "#99aab5"),
            position=role_data.get("position", 0),
        ))
    return roles


def _calculate_risk_score(
    user: discord.User,
    member: Optional[discord.Member],
    total_cases: int,
    total_messages: int,
    days_in_server: int,
) -> tuple[int, List[str]]:
    """
    Calculate risk score (0-100) and flags for a user.

    Risk factors:
    - New account (<30 days): +20
    - No avatar: +15
    - New to server (<7 days): +15
    - Low activity (<10 messages): +10
    - Previous cases: +5 per case (max +30)
    - No roles (besides @everyone): +10
    """
    score = 0
    flags = []

    now = datetime.utcnow()

    # Account age
    if user.created_at:
        account_age = (now - user.created_at.replace(tzinfo=None)).days
        if account_age < 7:
            score += 25
            flags.append("very_new_account")
        elif account_age < 30:
            score += 15
            flags.append("new_account")

    # No avatar
    if user.avatar is None:
        score += 15
        flags.append("no_avatar")

    # Server tenure
    if days_in_server < 3:
        score += 20
        flags.append("just_joined")
    elif days_in_server < 7:
        score += 10
        flags.append("new_member")

    # Low activity
    if total_messages < 5:
        score += 15
        flags.append("no_activity")
    elif total_messages < 20:
        score += 5
        flags.append("low_activity")

    # Previous cases
    if total_cases > 0:
        case_penalty = min(total_cases * 5, 30)
        score += case_penalty
        if total_cases >= 5:
            flags.append("repeat_offender")
        elif total_cases >= 2:
            flags.append("previous_cases")

    # No roles
    if member and len([r for r in member.roles if r.name != "@everyone"]) == 0:
        score += 10
        flags.append("no_roles")

    return min(score, 100), flags


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

    If the user has left or been banned, returns cached snapshot data
    with is_cached=true and in_server=false.
    """
    db = get_db()
    config = get_config()
    user: Optional[discord.User] = None
    member: Optional[discord.Member] = None
    user_id: Optional[int] = None
    snapshot: Optional[dict] = None
    is_cached = False
    in_server = True

    # Try to parse as Discord ID first
    try:
        user_id = int(query)
    except ValueError:
        pass

    # Check in-memory cache if we have a user_id and not refreshing
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
    guild_id = config.logging_guild_id
    if not user and guild_id:
        guild = bot.get_guild(guild_id)
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

    # If user not found via Discord API, try database snapshot
    if not user and user_id and guild_id:
        snapshot = db.get_user_snapshot(user_id, guild_id)
        if snapshot:
            is_cached = True
            in_server = False
            logger.debug("User Lookup Using Snapshot", [
                ("User ID", str(user_id)),
                ("Snapshot Reason", snapshot.get("snapshot_reason", "unknown")),
            ])

    if not user and not snapshot:
        logger.debug("User Lookup Not Found", [
            ("Query", query[:30]),
            ("Requested By", str(payload.sub)),
        ])
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"User not found: {query}",
        )

    # Set user_id from user or snapshot
    if user:
        user_id = user.id
    elif snapshot:
        user_id = snapshot["user_id"]

    now = datetime.utcnow()
    now_ts = now.timestamp()

    # Get member from guild if not already fetched (only if user exists)
    if user and not member and guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(user_id)
            if not member:
                in_server = False

    # Calculate account and server tenure
    account_age_days = 0
    server_tenure_days = 0

    if user and user.created_at:
        account_age_days = (now - user.created_at.replace(tzinfo=None)).days
    elif snapshot and snapshot.get("account_created_at"):
        created_dt = datetime.utcfromtimestamp(snapshot["account_created_at"])
        account_age_days = (now - created_dt).days

    if member and member.joined_at:
        server_tenure_days = (now - member.joined_at.replace(tzinfo=None)).days
    elif snapshot and snapshot.get("joined_at"):
        joined_dt = datetime.utcfromtimestamp(snapshot["joined_at"])
        server_tenure_days = (now - joined_dt).days

    # Fetch SyriaBot activity data (async)
    syriabot_task = asyncio.create_task(_fetch_syriabot_data(user_id))

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
        (user_id, now_ts)
    )
    is_muted = active_mute is not None
    mute_expires_at = None
    if active_mute and active_mute[0]:
        mute_expires_at = datetime.utcfromtimestamp(active_mute[0]).isoformat()

    # Check for active ban
    is_banned = False
    if guild_id:
        guild = bot.get_guild(guild_id)
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
            is_active = expires_ts > now_ts and resolved_at is None
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

    # Get additional data from AzabBot database
    previous_usernames = _get_previous_usernames(db, user_id)
    invite_code, inviter_id = _get_invite_info(db, user_id, guild_id) if guild_id else (None, None)

    # Get roles from member or snapshot
    if member:
        roles = _get_user_roles(member)
    elif snapshot:
        roles = _roles_from_snapshot(snapshot)
    else:
        roles = []

    # Fetch inviter username if we have an inviter ID
    invited_by_name = None
    if inviter_id:
        try:
            inviter = await bot.fetch_user(inviter_id)
            invited_by_name = inviter.name if inviter else None
        except Exception:
            pass

    # Await SyriaBot data
    syriabot_data = await syriabot_task

    # Extract activity stats from SyriaBot
    # SyriaBot API returns fields at root level (no data wrapper)
    total_messages = 0
    messages_this_week = 0
    messages_this_month = 0
    voice_time_seconds = 0
    last_seen_at = None
    most_active_channels: List[ChannelActivity] = []

    if syriabot_data:
        total_messages = syriabot_data.get("total_messages", 0)
        # SyriaBot tracks messages_per_day - estimate weekly/monthly
        messages_per_day = syriabot_data.get("messages_per_day", 0)
        messages_this_week = int(messages_per_day * 7)
        messages_this_month = int(messages_per_day * 30)
        # voice_minutes is in minutes, convert to seconds
        voice_time_seconds = syriabot_data.get("voice_minutes", 0) * 60
        # last_active_at is a Unix timestamp - convert to ISO format with Z suffix for UTC
        last_active_ts = syriabot_data.get("last_active_at")
        if last_active_ts and last_active_ts > 0:
            last_seen_at = datetime.utcfromtimestamp(last_active_ts).isoformat() + "Z"

    # Format voice time
    voice_hours = voice_time_seconds // 3600
    voice_minutes = (voice_time_seconds % 3600) // 60
    voice_time_formatted = f"{voice_hours}h {voice_minutes}m"

    # Calculate risk score
    risk_score, risk_flags = _calculate_risk_score(
        user=user,
        member=member,
        total_cases=total_cases,
        total_messages=total_messages,
        days_in_server=server_tenure_days,
    )

    # Save snapshot for live users with member data (for future fallback)
    if user and member and guild_id:
        save_snapshot(user, member, guild_id, reason="lookup")

    # Extract banner info (requires fetched user, not member)
    banner_url = None
    banner_color = None
    if user:
        # Check for custom banner image (Nitro users)
        if hasattr(user, 'banner') and user.banner:
            banner_url = str(user.banner.url)
        # Fallback to accent color
        elif hasattr(user, 'accent_color') and user.accent_color:
            banner_color = f"#{user.accent_color.value:06x}"

    # Build result - use live data if available, otherwise snapshot
    if user:
        discord_id = str(user.id)
        username = user.name
        display_name = user.display_name or user.name
        nickname = member.nick if member else None
        avatar_url = str(user.display_avatar.url) if user.display_avatar else None
        joined_server_at = member.joined_at.isoformat() if member and member.joined_at else None
        account_created_at = user.created_at.isoformat() if user.created_at else None
    else:
        # Using snapshot data
        discord_id = str(snapshot["user_id"])
        username = snapshot.get("username", "Unknown")
        display_name = snapshot.get("display_name", username)
        nickname = snapshot.get("nickname")
        avatar_url = snapshot.get("avatar_url")
        joined_server_at = datetime.utcfromtimestamp(snapshot["joined_at"]).isoformat() if snapshot.get("joined_at") else None
        account_created_at = datetime.utcfromtimestamp(snapshot["account_created_at"]).isoformat() if snapshot.get("account_created_at") else None

    # Cached timestamp for snapshot data
    cached_at = None
    if is_cached and snapshot:
        cached_at = datetime.utcfromtimestamp(snapshot["updated_at"]).isoformat() + "Z"

    result = UserLookupResult(
        discord_id=discord_id,
        username=username,
        display_name=display_name,
        nickname=nickname,
        avatar_url=avatar_url,
        banner_url=banner_url,
        banner_color=banner_color,
        is_cached=is_cached,
        cached_at=cached_at,
        in_server=in_server,
        joined_server_at=joined_server_at,
        account_created_at=account_created_at,
        account_age_days=account_age_days,
        server_tenure_days=server_tenure_days,
        last_seen_at=last_seen_at,
        is_muted=is_muted,
        is_banned=is_banned,
        mute_expires_at=mute_expires_at,
        total_cases=total_cases,
        total_warns=total_warns,
        total_mutes=total_mutes,
        total_bans=total_bans,
        total_messages=total_messages,
        messages_this_week=messages_this_week,
        messages_this_month=messages_this_month,
        voice_time_seconds=voice_time_seconds,
        voice_time_formatted=voice_time_formatted,
        risk_score=risk_score,
        risk_flags=risk_flags,
        invite_code=invite_code,
        invited_by=invited_by_name,
        invited_by_id=str(inviter_id) if inviter_id else None,
        roles=roles,
        previous_usernames=previous_usernames,
        most_active_channels=most_active_channels,
        punishments=punishments,
    )

    # Cache the result
    _lookup_cache.set(user_id, result.model_dump())

    logger.tree("User Lookup", [
        ("Query", query[:20]),
        ("User ID", str(user_id)),
        ("Username", username),
        ("In Server", str(in_server)),
        ("From Cache", str(is_cached)),
        ("Cases", str(total_cases)),
        ("Messages", str(total_messages)),
        ("Risk Score", str(risk_score)),
        ("Muted", str(is_muted)),
        ("Banned", str(is_banned)),
        ("SyriaBot Data", "Yes" if syriabot_data else "No"),
        ("Requested By", str(payload.sub)),
    ], emoji="🔍")

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
