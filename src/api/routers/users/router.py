"""
AzabBot - Users Router
======================

User profile and moderation history endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, List, Optional

import discord
from fastapi import APIRouter, Depends, Query

from src.api.errors import APIError, ErrorCode

from src.core.logger import logger
from src.core.config import get_config
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.utils.async_utils import create_safe_task
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.users import UserProfile, UserSearchResult, UserSuggestion, ModerationNote
from src.api.models.cases import CaseBrief, CaseType, CaseStatus
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.core.database import get_db
from src.services.user_snapshots import save_user_snapshot as save_snapshot

from .models import UserLookupResult, UserPunishment, ChannelActivity, InvitedUser
from .cache import lookup_cache
from .helpers import (
    fetch_syriabot_data,
    get_previous_usernames,
    get_invite_info,
    get_user_roles,
    roles_from_snapshot,
    batch_fetch_moderators,
)
from .risk import calculate_risk_score


router = APIRouter(prefix="/users", tags=["Users"])


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
        cached = lookup_cache.get(user_id)
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
    guild_id = config.main_guild_id
    if not user and guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            query_lower = query.lower()
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
        raise APIError(ErrorCode.USER_NOT_FOUND, message=f"User not found: {query}")

    # Set user_id from user or snapshot
    if user:
        user_id = user.id
    elif snapshot:
        user_id = snapshot["user_id"]

    now = datetime.utcnow()
    now_ts = now.timestamp()

    # Get member from guild if not already fetched
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

    # Fetch SyriaBot activity data (async - fire and forget with safe task)
    syriabot_task = create_safe_task(fetch_syriabot_data(user_id), "SyriaBot Data Fetch")

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

    # Batch fetch all moderator names
    mod_ids = {row[3] for row in case_rows if row[3]}
    mod_names = await batch_fetch_moderators(bot, mod_ids)

    # Build punishments list
    punishments = []
    for row in case_rows:
        created_ts = row[4]
        duration = row[5]
        resolved_at = row[6]
        mod_id = row[3]

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

    # Get additional data
    previous_usernames = get_previous_usernames(db, user_id)
    invite_code, inviter_id = get_invite_info(db, user_id, guild_id) if guild_id else (None, None)

    # Get roles from member or snapshot
    if member:
        roles = get_user_roles(member)
    elif snapshot:
        roles = roles_from_snapshot(snapshot)
    else:
        roles = []

    # Fetch inviter username
    invited_by_name = None
    if inviter_id:
        try:
            inviter = await bot.fetch_user(inviter_id)
            invited_by_name = inviter.name if inviter else None
        except (discord.NotFound, discord.HTTPException):
            pass

    # Always fetch from SyriaBot - it retains data for inactive users
    syriabot_data = await syriabot_task

    # Extract activity stats
    total_messages = 0
    messages_this_week = 0
    messages_this_month = 0
    voice_time_seconds = 0
    last_seen_at = None
    most_active_channels: List[ChannelActivity] = []

    if syriabot_data:
        total_messages = syriabot_data.get("total_messages", 0)
        messages_per_day = syriabot_data.get("messages_per_day", 0)
        messages_this_week = int(messages_per_day * 7)
        messages_this_month = int(messages_per_day * 30)
        voice_time_seconds = syriabot_data.get("voice_minutes", 0) * 60
        last_active_ts = syriabot_data.get("last_active_at")
        if last_active_ts and last_active_ts > 0:
            last_seen_at = datetime.utcfromtimestamp(last_active_ts).isoformat() + "Z"

        # Build channel activity list from SyriaBot data
        for ch in syriabot_data.get("channels", []):
            most_active_channels.append(ChannelActivity(
                channel_id=ch.get("channel_id", "0"),
                channel_name=ch.get("channel_name", "Unknown"),
                message_count=ch.get("message_count", 0),
            ))

    # Format voice time
    voice_hours = voice_time_seconds // 3600
    voice_minutes = (voice_time_seconds % 3600) // 60
    voice_time_formatted = f"{voice_hours}h {voice_minutes}m"

    # Calculate risk score
    risk_score, risk_flags = calculate_risk_score(
        user=user,
        member=member,
        total_cases=total_cases,
        total_messages=total_messages,
        days_in_server=server_tenure_days,
    )

    # Save snapshot for live users
    if user and member and guild_id:
        save_snapshot(user, member, guild_id, reason="lookup")

    # Extract banner info
    banner_url = None
    banner_color = None
    if user:
        if hasattr(user, 'banner') and user.banner:
            banner_url = str(user.banner.url)
        elif hasattr(user, 'accent_color') and user.accent_color:
            banner_color = f"#{user.accent_color.value:06x}"

    # Online status
    online_status = "offline"
    if member and hasattr(member, 'status'):
        status_str = str(member.status)
        if status_str in ("online", "idle", "dnd", "offline"):
            online_status = status_str

    # Booster status
    is_booster = False
    boosting_since = None
    if member and member.premium_since:
        is_booster = True
        boosting_since = member.premium_since.isoformat()

    # Discord badges from public flags
    badges: List[str] = []
    if user and hasattr(user, 'public_flags') and user.public_flags:
        flags = user.public_flags
        if flags.staff:
            badges.append("staff")
        if flags.partner:
            badges.append("partner")
        if flags.hypesquad:
            badges.append("hypesquad")
        if flags.bug_hunter:
            badges.append("bug_hunter")
        if flags.bug_hunter_level_2:
            badges.append("bug_hunter_level_2")
        if flags.hypesquad_bravery:
            badges.append("hypesquad_bravery")
        if flags.hypesquad_brilliance:
            badges.append("hypesquad_brilliance")
        if flags.hypesquad_balance:
            badges.append("hypesquad_balance")
        if flags.early_supporter:
            badges.append("early_supporter")
        if flags.verified_bot_developer:
            badges.append("verified_bot_developer")
        if flags.discord_certified_moderator:
            badges.append("certified_moderator")
        if flags.active_developer:
            badges.append("active_developer")

    # Nitro detection (animated avatar or banner indicates Nitro)
    if user:
        has_nitro_features = False
        # Check for animated avatar
        if user.avatar and user.avatar.is_animated():
            has_nitro_features = True
        # Check for profile banner
        if hasattr(user, 'banner') and user.banner:
            has_nitro_features = True
        if has_nitro_features:
            badges.append("nitro")

    # Boost badge based on boost duration
    if member and member.premium_since:
        boost_days = (now - member.premium_since.replace(tzinfo=None)).days
        if boost_days >= 730:  # 24 months
            badges.append("boost_24")
        elif boost_days >= 540:  # 18 months
            badges.append("boost_18")
        elif boost_days >= 450:  # 15 months
            badges.append("boost_15")
        elif boost_days >= 365:  # 12 months
            badges.append("boost_12")
        elif boost_days >= 270:  # 9 months
            badges.append("boost_9")
        elif boost_days >= 180:  # 6 months
            badges.append("boost_6")
        elif boost_days >= 90:  # 3 months
            badges.append("boost_3")
        elif boost_days >= 60:  # 2 months
            badges.append("boost_2")
        else:
            badges.append("boost_1")

    # Activity percentile (from SyriaBot data only - no estimates)
    activity_percentile = 0
    if syriabot_data and syriabot_data.get("percentile"):
        activity_percentile = syriabot_data.get("percentile", 0)

    # Join position (permanent historical position from database)
    # Only read from database - positions are assigned by backfill or on_member_join
    join_position = 0
    if user_id and guild_id:
        stored_position = db.get_join_position(user_id, guild_id)
        if stored_position:
            join_position = stored_position
        # If no position found, return 0 - backfill needs to run first

    # Users invited by this person
    users_invited: List[InvitedUser] = []
    if guild_id:
        try:
            invited_rows = db.fetchall(
                """
                SELECT user_id, joined_at FROM user_invites
                WHERE guild_id = ? AND inviter_id = ?
                ORDER BY joined_at DESC
                LIMIT 10
                """,
                (guild_id, user_id)
            )
        except Exception:
            # Table may not exist
            invited_rows = []
        for row in invited_rows:
            invited_user_id = row[0]
            invited_joined_at = row[1]
            # Try to get user info
            invited_member = None
            if guild:
                invited_member = guild.get_member(invited_user_id)
            if invited_member:
                users_invited.append(InvitedUser(
                    discord_id=str(invited_user_id),
                    username=invited_member.name,
                    display_name=invited_member.display_name,
                    avatar_url=str(invited_member.display_avatar.url) if invited_member.display_avatar else None,
                    joined_at=datetime.utcfromtimestamp(invited_joined_at).isoformat() if invited_joined_at else None,
                ))
            else:
                # Try to get from snapshot
                inv_snapshot = db.get_user_snapshot(invited_user_id, guild_id)
                if inv_snapshot:
                    users_invited.append(InvitedUser(
                        discord_id=str(invited_user_id),
                        username=inv_snapshot.get("username", "Unknown"),
                        display_name=inv_snapshot.get("display_name", "Unknown"),
                        avatar_url=inv_snapshot.get("avatar_url"),
                        joined_at=datetime.utcfromtimestamp(invited_joined_at).isoformat() if invited_joined_at else None,
                    ))

    # Build result
    if user:
        discord_id = str(user.id)
        username = user.name
        display_name = user.display_name or user.name
        nickname = member.nick if member else None
        avatar_url = str(user.display_avatar.url) if user.display_avatar else None
        joined_server_at = member.joined_at.isoformat() if member and member.joined_at else None
        account_created_at = user.created_at.isoformat() if user.created_at else None
    else:
        discord_id = str(snapshot["user_id"])
        username = snapshot.get("username", "Unknown")
        display_name = snapshot.get("display_name", username)
        nickname = snapshot.get("nickname")
        avatar_url = snapshot.get("avatar_url")
        joined_server_at = datetime.utcfromtimestamp(snapshot["joined_at"]).isoformat() if snapshot.get("joined_at") else None
        account_created_at = datetime.utcfromtimestamp(snapshot["account_created_at"]).isoformat() if snapshot.get("account_created_at") else None

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
        online_status=online_status,
        is_booster=is_booster,
        boosting_since=boosting_since,
        badges=badges,
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
        activity_percentile=activity_percentile,
        join_position=join_position,
        risk_score=risk_score,
        risk_flags=risk_flags,
        invite_code=invite_code,
        invited_by=invited_by_name,
        invited_by_id=str(inviter_id) if inviter_id else None,
        users_invited=users_invited,
        roles=roles,
        previous_usernames=previous_usernames,
        most_active_channels=most_active_channels,
        punishments=punishments,
    )

    lookup_cache.set(user_id, result.model_dump())

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
# Suggestions (Server Members)
# =============================================================================

@router.get("/suggest", response_model=APIResponse[List[UserSuggestion]])
async def suggest_users(
    q: str = Query(..., min_length=1, max_length=50, description="Search query"),
    limit: int = Query(10, ge=1, le=20, description="Max results"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[List[UserSuggestion]]:
    """
    Get user suggestions from server members.

    Uses Discord's query_members API for efficient server-side search.
    Searches by username, display name, or nickname prefix.
    """
    config = get_config()
    guild_id = config.main_guild_id

    if not guild_id:
        return APIResponse(success=True, data=[])

    guild = bot.get_guild(guild_id)
    if not guild:
        return APIResponse(success=True, data=[])

    db = get_db()

    try:
        # Use Discord's server-side member search (efficient for large guilds)
        members = await guild.query_members(query=q, limit=limit)

        # Batch fetch case counts for all members
        member_ids = [member.id for member in members]
        case_counts: dict[int, int] = {}

        if member_ids:
            placeholders = ",".join("?" * len(member_ids))
            rows = db.execute(
                f"SELECT user_id, COUNT(*) as count FROM cases WHERE user_id IN ({placeholders}) GROUP BY user_id",
                member_ids,
            ).fetchall()
            case_counts = {row["user_id"]: row["count"] for row in rows}

        results = [
            UserSuggestion(
                discord_id=str(member.id),
                username=member.name,
                display_name=member.display_name,
                avatar_url=str(member.display_avatar.url) if member.display_avatar else None,
                case_count=case_counts.get(member.id, 0),
            )
            for member in members
        ]

        return APIResponse(success=True, data=results)

    except discord.HTTPException as e:
        logger.warning("User Suggest Failed", [("Error", str(e)[:50])])
        return APIResponse(success=True, data=[])


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
            except (discord.NotFound, discord.HTTPException):
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

    try:
        user = await bot.fetch_user(user_id)
    except (discord.NotFound, discord.HTTPException):
        logger.debug("User Profile Not Found", [
            ("User ID", str(user_id)),
            ("Requested By", str(payload.sub)),
        ])
        raise APIError(ErrorCode.USER_NOT_FOUND, message=f"User {user_id} not found")

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

    pending_appeal = db.fetchone(
        "SELECT appeal_id FROM appeals WHERE user_id = ? AND status = 'pending' LIMIT 1",
        (user_id,)
    )

    notes_count = db.fetchone(
        "SELECT COUNT(*) FROM moderation_notes WHERE user_id = ?",
        (user_id,)
    )[0]

    tickets_count = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE user_id = ?",
        (user_id,)
    )[0]

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

    conditions = ["user_id = ?"]
    params = [user_id]

    if case_type:
        conditions.append("action_type = ?")
        params.append(case_type.value)

    where_clause = " AND ".join(conditions)

    total = db.fetchone(
        f"SELECT COUNT(*) FROM cases WHERE {where_clause}",
        params
    )[0]

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

    total = db.fetchone(
        "SELECT COUNT(*) FROM moderation_notes WHERE user_id = ?",
        (user_id,)
    )[0]

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
        author_name = None
        try:
            author = await bot.fetch_user(row["author_id"])
            author_name = author.name
        except (discord.NotFound, discord.HTTPException):
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


# =============================================================================
# Admin: Backfill Join Positions
# =============================================================================

@router.post("/backfill-join-positions", response_model=APIResponse[dict])
async def backfill_join_positions(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[dict]:
    """
    Backfill historical join positions for all current guild members.

    This populates the member_join_positions table with positions based on
    members' original join dates. Run this once to migrate existing members.
    New members will have positions recorded automatically on join.

    Returns count of positions backfilled.
    """
    config = get_config()
    db = get_db()
    guild_id = config.main_guild_id

    if not guild_id:
        raise APIError(ErrorCode.SERVER_ERROR, message="Guild ID not configured")

    guild = bot.get_guild(guild_id)
    if not guild:
        raise APIError(ErrorCode.SERVER_ERROR, message="Guild not found")

    # Get all members with their join dates, sorted by join time
    members_data = []
    for member in guild.members:
        if member.joined_at:
            members_data.append((member.id, member.joined_at.timestamp()))

    # Sort by join time (oldest first)
    members_data.sort(key=lambda x: x[1])

    # Backfill positions
    backfilled = db.backfill_join_positions(guild_id, members_data)

    total_tracked = db.get_total_join_positions(guild_id)
    next_position = db.get_next_join_position(guild_id)

    logger.tree("JOIN POSITIONS BACKFILLED", [
        ("Guild", guild.name),
        ("Members Processed", str(len(members_data))),
        ("Newly Assigned", str(backfilled)),
        ("Total Tracked", str(total_tracked)),
        ("Next Position", str(next_position)),
        ("Requested By", str(payload.sub)),
    ], emoji="📊")

    return APIResponse(success=True, data={
        "members_processed": len(members_data),
        "positions_backfilled": backfilled,
        "total_tracked": total_tracked,
        "next_position": next_position,
    })


__all__ = ["router"]
