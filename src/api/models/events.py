"""
AzabBot - Event Response Models
===============================

Pydantic models for event-related API endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Event Models
# =============================================================================

class EventEntry(BaseModel):
    """Single event entry."""
    id: int = Field(description="Event ID")
    event_type: str = Field(description="Event type (e.g., member.ban)")
    timestamp: str = Field(description="ISO timestamp")
    actor_id: Optional[int] = Field(None, description="Who performed the action")
    actor_name: Optional[str] = Field(None, description="Actor display name")
    target_id: Optional[int] = Field(None, description="Who was affected")
    target_name: Optional[str] = Field(None, description="Target display name")
    channel_id: Optional[int] = Field(None, description="Channel where it happened")
    channel_name: Optional[str] = Field(None, description="Channel name")
    reason: Optional[str] = Field(None, description="Reason for action")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class EventFilters(BaseModel):
    """Applied filters for events query."""
    event_type: Optional[str] = Field(None, description="Event type filter")
    category: Optional[str] = Field(None, description="Category filter")
    actor_id: Optional[str] = Field(None, description="Actor ID filter")
    target_id: Optional[str] = Field(None, description="Target ID filter")
    channel_id: Optional[str] = Field(None, description="Channel ID filter")
    search: Optional[str] = Field(None, description="Search term")
    hours: Optional[int] = Field(None, description="Time range in hours")


# =============================================================================
# Event Type Models
# =============================================================================

class EventTypeInfo(BaseModel):
    """Event type with count."""
    type: str = Field(description="Event type name")
    count: int = Field(description="Number of events")
    category: Optional[str] = Field(None, description="Event category")


# =============================================================================
# Response Data Models
# =============================================================================

class EventListData(BaseModel):
    """Data for events list response."""
    events: List[Dict[str, Any]] = Field(description="List of events")
    total: int = Field(description="Total event count")
    limit: int = Field(description="Requested limit")
    offset: int = Field(description="Offset")
    filters: EventFilters = Field(description="Applied filters")


class EventStatsData(BaseModel):
    """Data for event stats response."""
    total_events: int = Field(description="Total event count")
    by_type: Dict[str, int] = Field(description="Counts by event type")
    by_category: Dict[str, int] = Field(description="Counts by category")
    by_hour: Dict[str, int] = Field(description="Counts by hour")
    top_moderators: List[Dict[str, Any]] = Field(description="Top moderators")


class EventTypesData(BaseModel):
    """Data for event types response."""
    types: List[Dict[str, Any]] = Field(description="Event types with counts")
    categories: List[str] = Field(description="Available categories")


# =============================================================================
# Full Response Models
# =============================================================================

class EventListResponse(BaseModel):
    """Response for GET /events endpoint."""
    success: bool = True
    data: EventListData


class EventStatsResponse(BaseModel):
    """Response for GET /events/stats endpoint."""
    success: bool = True
    data: Dict[str, Any] = Field(description="Event statistics")


class EventTypesResponse(BaseModel):
    """Response for GET /events/types endpoint."""
    success: bool = True
    data: EventTypesData


class EventCategoriesResponse(BaseModel):
    """Response for GET /events/categories endpoint."""
    success: bool = True
    data: Dict[str, List[str]] = Field(description="Categories and their event types")


__all__ = [
    "EventEntry",
    "EventFilters",
    "EventTypeInfo",
    "EventListData",
    "EventStatsData",
    "EventTypesData",
    "EventListResponse",
    "EventStatsResponse",
    "EventTypesResponse",
    "EventCategoriesResponse",
]
