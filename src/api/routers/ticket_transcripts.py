"""
AzabBot - Ticket Transcripts Router
===================================

Ticket transcript endpoints for the dashboard.
Supports both stored transcripts and live fetching from Discord.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import re
import time
from typing import Any, Optional, Dict, List, Tuple, Set

import discord
from fastapi import APIRouter, Depends, Query, Request

from src.api.errors import APIError, ErrorCode

from src.core.logger import logger
from src.core.constants import USER_FETCH_TIMEOUT, CHANNEL_FETCH_TIMEOUT
from src.api.dependencies import require_auth, get_bot
from src.api.models.auth import TokenPayload
from src.api.models.cases import TicketTranscriptResponse
from src.api.services.auth import get_auth_service
from src.core.database import get_db
from src.utils.mention_resolver import collect_mentions_from_messages, mention_map_to_json


router = APIRouter(prefix="/ticket-transcripts", tags=["Ticket Transcripts"])


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


# =============================================================================
# Caching
# =============================================================================

# User info cache: {user_id: (info_dict, expires_at)}
_user_cache: Dict[int, Tuple[Dict[str, Any], float]] = {}
_USER_CACHE_TTL = 300  # 5 minutes

# Transcript cache: {ticket_id: (transcript_dict, expires_at)}
_transcript_cache: Dict[str, Tuple[dict, float]] = {}
_TRANSCRIPT_CACHE_TTL = 30  # 30 seconds


def _get_cached_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user info from cache if not expired."""
    if user_id in _user_cache:
        info, expires_at = _user_cache[user_id]
        if time.time() < expires_at:
            return info
        try:
            del _user_cache[user_id]
        except KeyError:
            pass
    return None


def _cache_user(user_id: int, info: Dict[str, Any]) -> None:
    """Store user info in cache."""
    _user_cache[user_id] = (info, time.time() + _USER_CACHE_TTL)


def _get_cached_transcript(ticket_id: str) -> Optional[dict]:
    """Get transcript from cache if not expired."""
    if ticket_id in _transcript_cache:
        transcript, expires_at = _transcript_cache[ticket_id]
        if time.time() < expires_at:
            return transcript
        try:
            del _transcript_cache[ticket_id]
        except KeyError:
            pass
    return None


def _cache_transcript(ticket_id: str, transcript: dict) -> None:
    """Store transcript in cache."""
    _transcript_cache[ticket_id] = (transcript, time.time() + _TRANSCRIPT_CACHE_TTL)


# =============================================================================
# User Fetching
# =============================================================================

async def _fetch_user_info(bot: Any, user_id: int) -> Dict[str, Any]:
    """Fetch user info with caching."""
    if not user_id:
        return {"id": None, "name": "Unknown", "avatar_url": None}

    cached = _get_cached_user(user_id)
    if cached:
        return cached

    user_info = {
        "id": user_id,
        "name": f"User {user_id}",
        "display_name": f"User {user_id}",
        "avatar_url": None,
    }

    try:
        user = await asyncio.wait_for(bot.fetch_user(user_id), timeout=USER_FETCH_TIMEOUT)
        user_info["name"] = user.name
        user_info["display_name"] = user.display_name
        user_info["avatar_url"] = str(user.display_avatar.url) if user.display_avatar else None
    except (discord.NotFound, discord.HTTPException, asyncio.TimeoutError):
        pass
    except Exception as e:
        logger.debug("User Fetch Failed", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:50]),
        ])

    _cache_user(user_id, user_info)
    return user_info


def _extract_mention_ids(messages: List[Dict[str, Any]]) -> Set[int]:
    """Extract all user IDs mentioned in message content."""
    mention_pattern = re.compile(r'<@!?(\d+)>')
    mentioned_ids: Set[int] = set()

    for msg in messages:
        content = msg.get("content", "")
        if content:
            for match in mention_pattern.finditer(content):
                try:
                    mentioned_ids.add(int(match.group(1)))
                except ValueError:
                    pass

    return mentioned_ids


async def _resolve_mentions(
    bot: Any,
    messages: List[Dict[str, Any]],
    existing_map: Dict[str, str],
    max_lookups: int = 20,
) -> Dict[str, str]:
    """Resolve mentioned user IDs to display names."""
    mention_map = dict(existing_map)

    # Extract all mentioned IDs not already in map
    mentioned_ids = _extract_mention_ids(messages)
    unknown_ids = [uid for uid in mentioned_ids if str(uid) not in mention_map]

    # Limit API lookups
    if len(unknown_ids) > max_lookups:
        unknown_ids = unknown_ids[:max_lookups]

    # Fetch user info in parallel
    if unknown_ids and bot:
        tasks = [_fetch_user_info(bot, uid) for uid in unknown_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for uid, result in zip(unknown_ids, results):
            if isinstance(result, dict) and result.get("display_name"):
                mention_map[str(uid)] = result["display_name"]

    return mention_map


async def _fetch_live_transcript(
    bot: Any,
    channel_id: int,
    ticket_id: str,
    limit: int = 500,
) -> Optional[dict]:
    """
    Fetch transcript live from Discord channel.
    """
    if not bot or not channel_id:
        return None

    # Check cache first
    cached = _get_cached_transcript(ticket_id)
    if cached:
        return cached

    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await asyncio.wait_for(bot.fetch_channel(channel_id), timeout=CHANNEL_FETCH_TIMEOUT)
            except discord.NotFound:
                return None
            except (discord.HTTPException, asyncio.TimeoutError):
                return None

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None

        # Get guild for mention resolution
        guild = channel.guild if hasattr(channel, 'guild') else None

        messages = []
        raw_messages = []  # Store raw Message objects for mention resolution
        async for message in channel.history(limit=limit, oldest_first=True):
            raw_messages.append(message)
            avatar_url = None
            if message.author.display_avatar:
                avatar_url = str(message.author.display_avatar.url)

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
                    "author_icon_url": embed.author.icon_url if embed.author else None,
                    "footer_text": embed.footer.text if embed.footer else None,
                    "footer_icon_url": embed.footer.icon_url if embed.footer else None,
                    "fields": [
                        {"name": f.name, "value": f.value, "inline": f.inline}
                        for f in embed.fields
                    ] if embed.fields else [],
                }
                embeds.append(embed_data)

            messages.append({
                "author_id": message.author.id,
                "author_name": message.author.name,
                "author_display_name": message.author.display_name,
                "author_avatar_url": avatar_url,
                "content": message.content or "",
                "timestamp": message.created_at.timestamp(),
                "attachments": attachments,
                "embeds": embeds,
                "embeds_count": len(embeds),
                "is_pinned": message.pinned,
                "is_bot": message.author.bot,
            })

        # Resolve all mentions before caching
        mention_map = await collect_mentions_from_messages(
            raw_messages, guild, bot, max_api_lookups=20
        )
        mention_map_str = mention_map_to_json(mention_map)

        transcript = {
            "ticket_id": ticket_id,
            "channel_id": channel_id,
            "channel_name": channel.name,
            "message_count": len(messages),
            "messages": messages,
            "mention_map": mention_map_str,
            "is_live": True,
        }

        _cache_transcript(ticket_id, transcript)
        return transcript

    except Exception as e:
        logger.warning("Live Ticket Transcript Fetch Failed", [
            ("Ticket ID", ticket_id),
            ("Channel ID", str(channel_id)),
            ("Error", str(e)[:50]),
        ])
        return None


def _build_transcript_from_db(db, ticket_id: str) -> Optional[dict]:
    """Build transcript from stored ticket_messages table."""
    rows = db.fetchall(
        """
        SELECT message_id, author_id, author_name, author_display_name,
               author_avatar_url, content, timestamp, is_bot, is_staff,
               attachments, embeds
        FROM ticket_messages
        WHERE ticket_id = ?
        ORDER BY timestamp ASC
        LIMIT 1000
        """,
        (ticket_id,)
    )

    if not rows:
        return None

    messages = []
    mention_map = {}

    for row in rows:
        attachments = []
        embeds = []

        if row["attachments"]:
            try:
                attachments = json.loads(row["attachments"])
            except (json.JSONDecodeError, TypeError):
                pass

        if row["embeds"]:
            try:
                embeds = json.loads(row["embeds"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Build mention_map from message authors
        author_id = row["author_id"]
        if author_id and author_id not in mention_map:
            mention_map[str(author_id)] = row["author_display_name"] or row["author_name"]

        messages.append({
            "author_id": author_id,
            "author_name": row["author_name"],
            "author_display_name": row["author_display_name"],
            "author_avatar_url": row["author_avatar_url"],
            "content": row["content"] or "",
            "timestamp": row["timestamp"],
            "attachments": attachments,
            "embeds": embeds,
            "embeds_count": len(embeds),
            "is_pinned": False,
            "is_bot": bool(row["is_bot"]),
        })

    return {
        "ticket_id": ticket_id,
        "message_count": len(messages),
        "messages": messages,
        "mention_map": mention_map,
        "is_live": False,
    }


@router.get("/{ticket_id}", response_model=TicketTranscriptResponse)
async def get_ticket_transcript(
    ticket_id: str,
    request: Request,
    token: Optional[str] = Query(None, description="Transcript access token (bypasses auth)"),
    bot: Any = Depends(get_bot),
) -> TicketTranscriptResponse:
    """
    Get ticket transcript for the dedicated transcript view.

    Tries to fetch live from Discord first, falls back to stored messages.
    Supports transcript access token for staff/users to view without login.
    """
    ticket_id = ticket_id.upper()

    # Check for transcript token access (no auth required)
    has_transcript_access = verify_transcript_access(ticket_id, token)

    # If no transcript token, require normal auth
    if not has_transcript_access:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise APIError(ErrorCode.AUTH_MISSING_TOKEN, message="Authentication required")

        jwt_token = auth_header.split(" ", 1)[1]
        auth_service = get_auth_service()
        payload = auth_service.get_token_payload(jwt_token)

        if payload is None:
            raise APIError(ErrorCode.AUTH_INVALID_TOKEN, message="Invalid or expired token")

    db = get_db()

    row = db.fetchone(
        """SELECT ticket_id, thread_id, user_id, claimed_by, closed_by,
                  status, priority, subject, category,
                  created_at, claimed_at, closed_at, close_reason, transcript
           FROM tickets WHERE ticket_id = ?""",
        (ticket_id,)
    )

    if not row:
        raise APIError(ErrorCode.TICKET_NOT_FOUND, message=f"Ticket {ticket_id} not found")

    # Fetch user info in parallel
    user_ids = [row["user_id"]]
    if row["claimed_by"]:
        user_ids.append(row["claimed_by"])
    if row["closed_by"]:
        user_ids.append(row["closed_by"])

    user_tasks = [_fetch_user_info(bot, uid) for uid in user_ids]
    user_results = await asyncio.gather(*user_tasks)

    user_info = user_results[0]
    claimer_info = user_results[1] if len(user_results) > 1 and row["claimed_by"] else None
    closer_info = None
    if row["closed_by"]:
        closer_info = user_results[-1] if row["closed_by"] != row["claimed_by"] else claimer_info

    # Try to fetch live transcript from Discord (thread_id > 0 means channel exists)
    transcript = None
    thread_id = row["thread_id"] or 0
    if thread_id > 0:
        transcript = await _fetch_live_transcript(bot, thread_id, ticket_id)

    # Fall back to stored messages
    if not transcript:
        transcript = _build_transcript_from_db(db, ticket_id)

    # Fall back to JSON transcript field
    if not transcript:
        json_str = row["transcript"]
        if json_str:
            try:
                stored = json.loads(json_str)
                transcript = {
                    "ticket_id": ticket_id,
                    "message_count": len(stored.get("messages", [])),
                    "messages": stored.get("messages", []),
                    "mention_map": stored.get("mention_map", {}),
                    "is_live": False,
                }
            except (json.JSONDecodeError, TypeError):
                pass

    # Build final transcript with ticket metadata
    ticket_status = row["status"] or "closed"
    if transcript:
        transcript.update({
            "ticket_id": row["ticket_id"],
            "thread_id": thread_id if thread_id > 0 else None,
            "thread_name": f"Ticket {row['ticket_id']}",
            "category": row["category"] or "Support",
            "subject": row["subject"] or f"Ticket {row['ticket_id']}",
            "status": ticket_status,
            "created_at": row["created_at"],
            "closed_at": row["closed_at"],
            "user_id": row["user_id"],
            "user_name": user_info.get("display_name") or user_info.get("name"),
            "claimed_by_id": row["claimed_by"],
            "claimed_by_name": claimer_info.get("display_name") if claimer_info else None,
            "closed_by_id": row["closed_by"],
            "closed_by_name": closer_info.get("display_name") if closer_info else None,
        })

        # Resolve mentioned users that aren't in the mention_map
        if transcript.get("messages"):
            existing_map = transcript.get("mention_map") or {}
            resolved_map = await _resolve_mentions(
                bot,
                transcript["messages"],
                existing_map,
                max_lookups=20,
            )
            transcript["mention_map"] = resolved_map

    logger.debug("Ticket Transcript Fetched", [
        ("Ticket ID", ticket_id),
        ("Access", "transcript_token" if has_transcript_access else "authenticated"),
        ("Messages", str(transcript["message_count"]) if transcript else "0"),
        ("Source", "live" if transcript and transcript.get("is_live") else "stored"),
    ])

    return TicketTranscriptResponse(
        ticket_id=row["ticket_id"],
        user_id=row["user_id"],
        category=row["category"] or "Support",
        subject=row["subject"] or f"Ticket {row['ticket_id']}",
        status=row["status"] or "closed",
        claimed_by=row["claimed_by"],
        closed_by=row["closed_by"],
        closed_at=row["closed_at"],
        created_at=row["created_at"],
        transcript=transcript,
    )


__all__ = ["router"]
