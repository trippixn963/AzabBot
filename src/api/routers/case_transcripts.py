"""
AzabBot - Case Transcripts Router
=================================

Case transcript endpoints for the dashboard.
Supports both stored transcripts and live fetching from Discord.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import re
import time
from typing import Any, Optional, Dict, List, Tuple

import discord
from fastapi import APIRouter, Depends, Query

from src.api.errors import APIError, ErrorCode

from src.core.logger import logger
from src.core.constants import USER_FETCH_TIMEOUT, CHANNEL_FETCH_TIMEOUT
from src.api.dependencies import require_auth, get_bot
from src.api.models.auth import TokenPayload
from src.api.models.cases import CaseTranscriptResponse
from src.core.database import get_db
from src.utils.mention_resolver import collect_mentions_from_messages, mention_map_to_json


router = APIRouter(prefix="/case-transcripts", tags=["Case Transcripts"])


# =============================================================================
# Caching
# =============================================================================

# Extended user info cache: {user_id: (info_dict, expires_at)}
_extended_user_cache: Dict[int, Tuple[Dict[str, Any], float]] = {}
_USER_CACHE_TTL = 300  # 5 minutes

# Transcript cache: {(case_id, thread_id): (transcript_dict, expires_at)}
_transcript_cache: Dict[Tuple[str, int], Tuple[dict, float]] = {}
_TRANSCRIPT_CACHE_TTL = 30  # 30 seconds for live transcripts


def _get_cached_extended_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Get extended user info from cache if not expired."""
    if user_id in _extended_user_cache:
        info, expires_at = _extended_user_cache[user_id]
        if time.time() < expires_at:
            return info
        try:
            del _extended_user_cache[user_id]
        except KeyError:
            pass
    return None


def _cache_extended_user(user_id: int, info: Dict[str, Any]) -> None:
    """Store extended user info in cache."""
    _extended_user_cache[user_id] = (info, time.time() + _USER_CACHE_TTL)


def _get_cached_transcript(case_id: str, thread_id: int) -> Optional[dict]:
    """Get transcript from cache if not expired."""
    key = (case_id, thread_id)
    if key in _transcript_cache:
        transcript, expires_at = _transcript_cache[key]
        if time.time() < expires_at:
            return transcript
        try:
            del _transcript_cache[key]
        except KeyError:
            pass
    return None


def _cache_transcript(case_id: str, thread_id: int, transcript: dict) -> None:
    """Store transcript in cache."""
    _transcript_cache[(case_id, thread_id)] = (transcript, time.time() + _TRANSCRIPT_CACHE_TTL)


# =============================================================================
# Constants
# =============================================================================

# Message type mapping from Discord to our types
MESSAGE_TYPE_MAP = {
    discord.MessageType.default: "default",
    discord.MessageType.reply: "reply",
    discord.MessageType.thread_starter_message: "thread_starter",
    discord.MessageType.new_member: "join",
    discord.MessageType.pins_add: "pin",
    discord.MessageType.premium_guild_subscription: "boost",
    discord.MessageType.premium_guild_tier_1: "boost",
    discord.MessageType.premium_guild_tier_2: "boost",
    discord.MessageType.premium_guild_tier_3: "boost",
}


# =============================================================================
# User Fetching
# =============================================================================

async def _fetch_extended_user_info(bot: Any, user_id: int, guild: discord.Guild = None) -> Dict[str, Any]:
    """Fetch full user info including member data if available. Uses caching."""
    # Check cache first
    cached = _get_cached_extended_user(user_id)
    if cached:
        return cached

    user_info = {
        "id": str(user_id),
        "username": None,
        "display_name": None,
        "avatar_url": None,
        "joined_at": None,
        "created_at": None,
    }

    try:
        # Try to get as guild member first
        member = None
        if guild:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await asyncio.wait_for(guild.fetch_member(user_id), timeout=USER_FETCH_TIMEOUT)
                except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
                    pass

        if member:
            user_info["username"] = member.name
            user_info["display_name"] = member.display_name
            user_info["avatar_url"] = str(member.display_avatar.url) if member.display_avatar else None
            user_info["joined_at"] = member.joined_at.timestamp() if member.joined_at else None
            user_info["created_at"] = member.created_at.timestamp() if member.created_at else None
        else:
            # Fall back to user fetch
            try:
                user = await asyncio.wait_for(bot.fetch_user(user_id), timeout=USER_FETCH_TIMEOUT)
                user_info["username"] = user.name
                user_info["display_name"] = user.display_name
                user_info["avatar_url"] = str(user.display_avatar.url) if user.display_avatar else None
                user_info["created_at"] = user.created_at.timestamp() if user.created_at else None
            except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
                user_info["username"] = f"User {user_id}"
                user_info["display_name"] = f"User {user_id}"

    except Exception as e:
        logger.warning("User Info Fetch Failed", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:50]),
        ])
        user_info["username"] = f"User {user_id}"
        user_info["display_name"] = f"User {user_id}"

    # Cache the result
    _cache_extended_user(user_id, user_info)
    return user_info


async def _batch_fetch_extended_users(
    bot: Any,
    user_ids: List[int],
    guild: discord.Guild = None
) -> Dict[int, Dict[str, Any]]:
    """Fetch multiple users in parallel with caching."""
    if not bot or not user_ids:
        return {}

    results: Dict[int, Dict[str, Any]] = {}
    to_fetch: List[int] = []

    # Check cache first
    for uid in user_ids:
        cached = _get_cached_extended_user(uid)
        if cached:
            results[uid] = cached
        else:
            to_fetch.append(uid)

    if not to_fetch:
        return results

    # Fetch remaining in parallel
    fetch_tasks = [_fetch_extended_user_info(bot, uid, guild) for uid in to_fetch]
    fetched = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    for uid, result in zip(to_fetch, fetched):
        if isinstance(result, dict):
            results[uid] = result
        else:
            # On error, return placeholder
            results[uid] = {
                "id": str(uid),
                "username": f"User {uid}",
                "display_name": f"User {uid}",
                "avatar_url": None,
                "joined_at": None,
                "created_at": None,
            }

    return results


async def _fetch_live_transcript(
    bot: Any,
    thread_id: int,
    case_id: str,
    limit: int = 500,
    offset: int = 0,
    use_cache: bool = True,
) -> Optional[dict]:
    """
    Fetch transcript live from Discord thread.
    Uses short-term caching to reduce Discord API calls.

    Args:
        bot: Discord bot instance
        thread_id: Discord thread ID
        case_id: Case identifier
        limit: Max messages to return (after offset)
        offset: Number of messages to skip from start
        use_cache: Whether to use transcript cache (default True)
    """
    if not bot or not thread_id:
        return None

    # Check cache first (only if not paginating)
    if use_cache and offset == 0:
        cached = _get_cached_transcript(case_id, thread_id)
        if cached:
            # Apply limit to cached result
            if limit < len(cached.get("messages", [])):
                result = cached.copy()
                result["messages"] = result["messages"][:limit]
                result["message_count"] = len(result["messages"])
                return result
            return cached

    try:
        # Get the thread
        thread = bot.get_channel(thread_id)
        if not thread:
            try:
                thread = await asyncio.wait_for(bot.fetch_channel(thread_id), timeout=CHANNEL_FETCH_TIMEOUT)
            except discord.NotFound:
                return None
            except (discord.HTTPException, asyncio.TimeoutError):
                return None

        if not isinstance(thread, discord.Thread):
            return None

        # Get guild for member lookups
        guild = thread.guild

        # Cache for referenced messages (for reply threading)
        referenced_messages: Dict[int, discord.Message] = {}

        # Collect raw messages for mention resolution
        raw_messages: List[discord.Message] = []

        # Fetch all messages (we need full list for proper offset handling)
        messages = []
        async for message in thread.history(limit=1000, oldest_first=True):
            raw_messages.append(message)

            avatar_url = None
            if message.author.display_avatar:
                avatar_url = str(message.author.display_avatar.url)

            # Get author role color
            author_role_color = None
            if message.author and hasattr(message.author, 'color') and message.author.color:
                if message.author.color.value != 0:  # 0 is default/no color
                    author_role_color = f"#{message.author.color.value:06x}"

            # Process embeds
            embeds = []
            for embed in message.embeds:
                embed_data = {
                    "title": embed.title,
                    "description": embed.description,
                    "color": embed.color.value if embed.color else None,
                    "url": embed.url,
                    "image_url": embed.image.url if embed.image else None,
                    "thumbnail_url": embed.thumbnail.url if embed.thumbnail else None,
                    "author_name": embed.author.name if embed.author else None,
                    "footer_text": embed.footer.text if embed.footer else None,
                    "fields": [
                        {"name": f.name, "value": f.value, "inline": f.inline}
                        for f in embed.fields
                    ] if embed.fields else [],
                }
                embeds.append(embed_data)

            # Process attachments
            attachments = [
                {
                    "filename": a.filename,
                    "url": a.url,
                    "content_type": a.content_type,
                    "size": a.size,
                }
                for a in message.attachments
            ]

            # Process reactions
            reactions = []
            for reaction in message.reactions:
                emoji_data = {
                    "emoji": str(reaction.emoji),
                    "emoji_id": str(reaction.emoji.id) if hasattr(reaction.emoji, 'id') and reaction.emoji.id else None,
                    "emoji_name": reaction.emoji.name if hasattr(reaction.emoji, 'name') else None,
                    "count": reaction.count,
                }
                reactions.append(emoji_data)

            # Process reply threading
            reply_to = None
            if message.reference and message.reference.message_id:
                ref_id = message.reference.message_id
                # Try to get from cache or fetch
                ref_msg = referenced_messages.get(ref_id)
                if not ref_msg:
                    try:
                        ref_msg = await thread.fetch_message(ref_id)
                        referenced_messages[ref_id] = ref_msg
                    except (discord.NotFound, discord.HTTPException):
                        pass

                if ref_msg:
                    reply_to = {
                        "message_id": str(ref_id),
                        "author_name": ref_msg.author.display_name if ref_msg.author else "Unknown",
                        "content": (ref_msg.content[:100] + "...") if len(ref_msg.content) > 100 else ref_msg.content,
                    }

            # Determine message type
            msg_type = MESSAGE_TYPE_MAP.get(message.type, "default")

            # Check if edited
            is_edited = message.edited_at is not None
            edited_at = message.edited_at.timestamp() if message.edited_at else None

            messages.append({
                "message_id": str(message.id),
                "author_id": message.author.id,
                "author_name": message.author.name,
                "author_display_name": message.author.display_name,
                "author_avatar_url": avatar_url,
                "author_role_color": author_role_color,
                "content": message.content or "",
                "timestamp": message.created_at.timestamp(),
                "attachments": attachments,
                "embeds": embeds,
                "embeds_count": len(embeds),
                "is_pinned": message.pinned,
                "reactions": reactions,
                "reply_to": reply_to,
                "is_edited": is_edited,
                "edited_at": edited_at,
                "type": msg_type,
            })

        # Use shared utility to collect and resolve mentions
        mention_map = await collect_mentions_from_messages(
            raw_messages, guild, bot, max_api_lookups=10
        )
        mention_map_str = mention_map_to_json(mention_map)

        # Build full transcript for caching
        full_transcript = {
            "case_id": case_id,
            "thread_id": thread_id,
            "thread_name": thread.name,
            "created_at": thread.created_at.timestamp() if thread.created_at else None,
            "total_messages": len(messages),
            "message_count": len(messages),
            "messages": messages,
            "mention_map": mention_map_str,
            "is_live": True,
        }

        # Cache the full transcript
        if use_cache:
            _cache_transcript(case_id, thread_id, full_transcript)

        # Apply pagination
        if offset > 0 or limit < len(messages):
            paginated_messages = messages[offset:offset + limit]
            return {
                **full_transcript,
                "messages": paginated_messages,
                "message_count": len(paginated_messages),
                "offset": offset,
                "has_more": offset + limit < len(messages),
            }

        return full_transcript

    except Exception as e:
        logger.warning("Live Transcript Fetch Failed", [
            ("Case ID", case_id),
            ("Thread ID", str(thread_id)),
            ("Error", str(e)[:50]),
        ])
        return None


@router.get("/{case_id}", response_model=CaseTranscriptResponse)
async def get_case_transcript(
    case_id: str,
    limit: int = Query(500, ge=1, le=1000, description="Max messages to return"),
    offset: int = Query(0, ge=0, description="Messages to skip from start"),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> CaseTranscriptResponse:
    """
    Get case transcript for the dedicated transcript view.

    Always fetches live from Discord for real-time updates.
    Falls back to archived transcript if thread no longer exists.

    Supports pagination via limit/offset parameters.
    """
    db = get_db()

    row = db.fetchone(
        """SELECT case_id, user_id, moderator_id, action_type, reason,
                  created_at, evidence, evidence_urls, transcript, thread_id, guild_id
           FROM cases WHERE case_id = ?""",
        (case_id,)
    )

    if not row:
        raise APIError(ErrorCode.CASE_NOT_FOUND, message=f"Case #{case_id} not found")

    # Get guild for user lookups
    guild = None
    if bot and row["guild_id"]:
        guild = bot.get_guild(row["guild_id"])

    # Fetch target user and moderator info in parallel
    user_ids = [row["user_id"], row["moderator_id"]]
    user_info = await _batch_fetch_extended_users(bot, user_ids, guild)
    target_user = user_info.get(row["user_id"], {"id": str(row["user_id"]), "username": f"User {row['user_id']}"})
    moderator = user_info.get(row["moderator_id"], {"id": str(row["moderator_id"]), "username": f"Mod {row['moderator_id']}"})

    # Parse evidence URLs
    evidence = []
    if row["evidence_urls"]:
        urls = row["evidence_urls"].split(",") if isinstance(row["evidence_urls"], str) else []
        for url in urls:
            url = url.strip()
            if url:
                evidence.append(url)

    # Always try to fetch live from Discord first (for real-time updates)
    transcript = None
    if row["thread_id"]:
        transcript = await _fetch_live_transcript(
            bot, row["thread_id"], case_id,
            limit=limit, offset=offset
        )

    # Fall back to stored transcript if live fetch failed (thread deleted, etc.)
    if not transcript and row["transcript"]:
        try:
            transcript_data = json.loads(row["transcript"])
            all_messages = []
            for msg in transcript_data.get("messages", []):
                all_messages.append({
                    "message_id": msg.get("message_id"),
                    "author_id": msg.get("author_id"),
                    "author_name": msg.get("author_name"),
                    "author_display_name": msg.get("author_display_name"),
                    "author_avatar_url": msg.get("author_avatar_url"),
                    "author_role_color": msg.get("author_role_color"),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp"),
                    "attachments": msg.get("attachments", []),
                    "embeds": msg.get("embeds", []),
                    "embeds_count": len(msg.get("embeds", [])),
                    "is_pinned": msg.get("is_pinned", False),
                    "reactions": msg.get("reactions", []),
                    "reply_to": msg.get("reply_to"),
                    "is_edited": msg.get("is_edited", False),
                    "edited_at": msg.get("edited_at"),
                    "type": msg.get("type", "default"),
                })

            # Apply pagination
            total_messages = len(all_messages)
            paginated_messages = all_messages[offset:offset + limit]

            # Get stored mention_map or build from authors
            stored_mention_map = transcript_data.get("mention_map", {})
            if not stored_mention_map:
                # Fallback: build from message authors
                for msg in all_messages:
                    if msg.get("author_id"):
                        stored_mention_map[str(msg["author_id"])] = msg.get("author_display_name", msg.get("author_name", "Unknown"))

            transcript = {
                "case_id": transcript_data.get("case_id"),
                "thread_id": transcript_data.get("thread_id"),
                "thread_name": transcript_data.get("thread_name"),
                "created_at": transcript_data.get("created_at"),
                "total_messages": total_messages,
                "message_count": len(paginated_messages),
                "messages": paginated_messages,
                "mention_map": stored_mention_map,
                "offset": offset,
                "has_more": offset + limit < total_messages,
                "is_live": False,
            }
        except (json.JSONDecodeError, TypeError):
            pass

    logger.debug("Case Transcript Fetched", [
        ("Case ID", str(case_id)),
        ("User", str(payload.sub)),
        ("Messages", str(transcript["message_count"]) if transcript else "0"),
        ("Source", "live" if transcript and transcript.get("is_live") else "archived"),
    ])

    return CaseTranscriptResponse(
        case_id=row["case_id"],
        user_id=row["user_id"],
        action_type=row["action_type"],
        reason=row["reason"],
        moderator_id=row["moderator_id"],
        created_at=row["created_at"],
        evidence=evidence,
        transcript=transcript,
        target_user=target_user,
        moderator=moderator,
    )


__all__ = ["router"]
