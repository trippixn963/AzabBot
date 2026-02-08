"""
AzabBot - Events Router
=======================

API endpoints for Discord event logs with filtering and search.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from src.api.dependencies import require_auth
from src.api.models.auth import TokenPayload
from src.api.services.event_storage import get_event_storage, EventType


router = APIRouter(prefix="/events", tags=["Events"])
TIMEZONE = ZoneInfo("America/New_York")


# =============================================================================
# Event Endpoints
# =============================================================================

@router.get("")
async def get_events(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of events"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    event_type: Optional[str] = Query(None, description="Filter by specific event type"),
    category: Optional[str] = Query(None, description="Filter by category: member, message, voice, channel, role, server"),
    actor_id: Optional[str] = Query(None, description="Filter by actor (moderator) ID"),
    target_id: Optional[str] = Query(None, description="Filter by target (user) ID"),
    channel_id: Optional[str] = Query(None, description="Filter by channel ID"),
    search: Optional[str] = Query(None, description="Search in reasons, names, and details"),
    hours: Optional[int] = Query(None, ge=1, le=720, description="Filter events from last N hours"),
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get paginated Discord events with filtering.

    Filters:
    - event_type: Specific event (e.g., "member.ban", "message.delete")
    - category: Event category (member, message, voice, channel, role, server)
    - actor_id: Who performed the action
    - target_id: Who was affected
    - channel_id: Where it happened
    - search: Full-text search
    - hours: Time range
    """
    storage = get_event_storage()

    # Parse IDs
    actor = int(actor_id) if actor_id else None
    target = int(target_id) if target_id else None
    channel = int(channel_id) if channel_id else None

    # Calculate time range
    from_time = None
    if hours:
        from_time = datetime.now(TIMEZONE) - timedelta(hours=hours)

    # Query events
    events, total = storage.get_events(
        limit=limit,
        offset=offset,
        event_type=event_type,
        event_category=category,
        actor_id=actor,
        target_id=target,
        channel_id=channel,
        search=search,
        from_time=from_time,
    )

    return JSONResponse(content={
        "success": True,
        "data": {
            "events": [e.to_dict() for e in events],
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {
                "event_type": event_type,
                "category": category,
                "actor_id": actor_id,
                "target_id": target_id,
                "channel_id": channel_id,
                "search": search,
                "hours": hours,
            },
        },
    })


@router.get("/stats")
async def get_event_stats(
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get event statistics.

    Returns counts by type, category, hour, and top moderators.
    """
    storage = get_event_storage()
    stats = storage.get_stats()

    return JSONResponse(content={
        "success": True,
        "data": stats,
    })


@router.get("/types")
async def get_event_types(
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get all event types with their counts.
    """
    storage = get_event_storage()
    types = storage.get_event_types()

    # Add category info
    categories = EventType.categories()
    type_to_category = {}
    for cat, type_list in categories.items():
        for t in type_list:
            type_to_category[t] = cat

    for t in types:
        t["category"] = type_to_category.get(t["type"], "other")

    return JSONResponse(content={
        "success": True,
        "data": {
            "types": types,
            "categories": list(categories.keys()),
        },
    })


@router.get("/categories")
async def get_event_categories(
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get event categories and their event types.
    """
    return JSONResponse(content={
        "success": True,
        "data": EventType.categories(),
    })


__all__ = ["router"]
