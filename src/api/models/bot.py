"""
AzabBot - Bot Status Response Models
====================================

Pydantic models for bot status API endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# System Info Models
# =============================================================================

class SystemInfo(BaseModel):
    """System resource information."""
    cpu_percent: float = Field(description="CPU usage percentage")
    memory_used_mb: float = Field(description="Memory used in MB")
    memory_total_mb: float = Field(description="Total memory in MB")
    disk_used_gb: float = Field(description="Disk used in GB")
    disk_total_gb: float = Field(description="Total disk in GB")
    python_version: str = Field(description="Python version")
    discord_py_version: str = Field(description="discord.py version")


class HealthInfo(BaseModel):
    """Bot health information."""
    shard_id: int = Field(description="Current shard ID")
    shard_count: int = Field(description="Total shard count")
    reconnect_count: int = Field(description="Number of reconnects")
    rate_limit_hits: int = Field(description="Rate limit hits")
    avg_latency_ms: Optional[float] = Field(None, description="Average latency in ms")


# =============================================================================
# Bot Status Data
# =============================================================================

class BotStatusData(BaseModel):
    """Comprehensive bot status data."""
    online: bool = Field(description="Whether bot is online")
    uptime_seconds: int = Field(description="Uptime in seconds")
    started_at: Optional[str] = Field(None, description="ISO timestamp when bot started")
    latency_ms: int = Field(description="Current latency in ms")
    guild_count: int = Field(description="Number of guilds")
    user_count: int = Field(description="Total user count across guilds")
    version: str = Field(description="Bot version")
    system: SystemInfo = Field(description="System resource info")
    health: HealthInfo = Field(description="Health metrics")


# =============================================================================
# Log Models
# =============================================================================

class LogEntry(BaseModel):
    """Single log entry."""
    id: int = Field(description="Log entry ID")
    timestamp: str = Field(description="ISO timestamp")
    level: str = Field(description="Log level")
    module: str = Field(description="Module name")
    message: str = Field(description="Log message")
    details: Optional[List[Dict[str, Any]]] = Field(None, description="Additional details")


class BotLogsData(BaseModel):
    """Data for bot logs response."""
    logs: List[Dict[str, Any]] = Field(description="Log entries")
    total: int = Field(description="Total log count")
    limit: int = Field(description="Requested limit")
    offset: int = Field(description="Offset")
    level: str = Field(description="Filtered level")


# =============================================================================
# Latency Models
# =============================================================================

class LatencyPoint(BaseModel):
    """Single latency measurement point."""
    timestamp: float = Field(description="Unix timestamp")
    discord_ms: int = Field(description="Discord latency in ms")
    api_ms: Optional[int] = Field(None, description="API latency in ms")


class LatencyData(BaseModel):
    """Data for latency response."""
    period: str = Field(description="Time period")
    points: List[Dict[str, Any]] = Field(description="Latency data points")
    count: int = Field(description="Number of points")
    aggregated: bool = Field(description="Whether data is aggregated")


class LatencyStatsData(BaseModel):
    """Latency statistics."""
    current_ms: Optional[int] = Field(None, description="Current latency")
    avg_24h: Optional[float] = Field(None, description="24h average")
    min_24h: Optional[int] = Field(None, description="24h minimum")
    max_24h: Optional[int] = Field(None, description="24h maximum")
    total_points: int = Field(description="Total data points")


class LatencyReportData(BaseModel):
    """Data for latency report response."""
    recorded: bool = Field(description="Whether recording was successful")
    id: int = Field(description="Record ID")
    discord_ms: int = Field(description="Discord latency")
    api_ms: int = Field(description="API latency")


class LatencyHistoryData(BaseModel):
    """Legacy latency history data."""
    history: List[Dict[str, Any]] = Field(description="Latency history")
    count: int = Field(description="Number of entries")


# =============================================================================
# Full Response Models
# =============================================================================

class BotStatusResponse(BaseModel):
    """Response for GET /bot/status endpoint."""
    success: bool = True
    data: BotStatusData


class BotLogsResponse(BaseModel):
    """Response for GET /bot/logs endpoint."""
    success: bool = True
    data: BotLogsData


class LatencyResponse(BaseModel):
    """Response for GET /bot/latency endpoint."""
    success: bool = True
    data: LatencyData


class LatencyStatsResponse(BaseModel):
    """Response for GET /bot/latency/stats endpoint."""
    success: bool = True
    data: Dict[str, Any] = Field(description="Latency statistics")


class LatencyReportResponse(BaseModel):
    """Response for POST /bot/latency/report endpoint."""
    success: bool = True
    data: LatencyReportData


class LatencyHistoryResponse(BaseModel):
    """Response for GET /bot/latency-history endpoint."""
    success: bool = True
    data: LatencyHistoryData


__all__ = [
    "SystemInfo",
    "HealthInfo",
    "BotStatusData",
    "LogEntry",
    "BotLogsData",
    "LatencyPoint",
    "LatencyData",
    "LatencyStatsData",
    "LatencyReportData",
    "LatencyHistoryData",
    "BotStatusResponse",
    "BotLogsResponse",
    "LatencyResponse",
    "LatencyStatsResponse",
    "LatencyReportResponse",
    "LatencyHistoryResponse",
]
