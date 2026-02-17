"""
AzabBot - Bot Status Router
===========================

Bot status, system info, and log streaming endpoints for the dashboard.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import platform
import time
from datetime import datetime
from typing import Any, Optional

import discord
import psutil
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth
from src.api.models.auth import TokenPayload
from src.api.services.log_storage import get_log_storage
from src.api.services.health_tracker import get_health_tracker


router = APIRouter(prefix="/bot", tags=["Bot Status"])


# =============================================================================
# Bot Status
# =============================================================================

@router.get("/status")
async def get_bot_status(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get comprehensive bot status and system information.

    Returns uptime, latency, resource usage, and version info.
    """
    now = time.time()
    bot_online = bot is not None and bot.is_ready() if bot else False

    # Calculate uptime
    uptime_seconds = 0
    started_at = None
    if bot and hasattr(bot, 'start_time') and bot.start_time:
        uptime_seconds = int(now - bot.start_time.timestamp())
        started_at = bot.start_time.isoformat() + "Z"

    # Get latency
    latency_ms = int(bot.latency * 1000) if bot and bot_online else 0

    # Get guild and user counts
    guild_count = len(bot.guilds) if bot and bot_online else 0
    user_count = 0
    if bot and bot_online:
        for guild in bot.guilds:
            user_count += guild.member_count or 0

    # Get version
    version = "2.0.0"
    if bot and hasattr(bot, 'config') and hasattr(bot.config, 'version'):
        version = bot.config.version

    # System information
    cpu_percent = psutil.cpu_percent(interval=None)

    memory = psutil.virtual_memory()
    memory_used_mb = memory.used / (1024 * 1024)
    memory_total_mb = memory.total / (1024 * 1024)

    disk = psutil.disk_usage('/')
    disk_used_gb = disk.used / (1024 * 1024 * 1024)
    disk_total_gb = disk.total / (1024 * 1024 * 1024)

    # Get Python and discord.py versions
    python_version = platform.python_version()
    discord_py_version = discord.__version__

    # Get shard info (shard_id can be None for non-sharded bots)
    shard_id = (bot.shard_id or 0) if bot and hasattr(bot, 'shard_id') else 0
    shard_count = (bot.shard_count or 1) if bot and hasattr(bot, 'shard_count') else 1

    # Get health tracker data
    health_tracker = get_health_tracker()
    health_summary = health_tracker.get_health_summary()

    # Record current latency
    if latency_ms > 0:
        health_tracker.record_latency(latency_ms)

    response = {
        "success": True,
        "data": {
            "online": bot_online,
            "uptime_seconds": uptime_seconds,
            "started_at": started_at,
            "latency_ms": latency_ms,
            "guild_count": guild_count,
            "user_count": user_count,
            "version": version,
            "system": {
                "cpu_percent": round(cpu_percent, 1),
                "memory_used_mb": round(memory_used_mb, 1),
                "memory_total_mb": round(memory_total_mb, 1),
                "disk_used_gb": round(disk_used_gb, 1),
                "disk_total_gb": round(disk_total_gb, 1),
                "python_version": python_version,
                "discord_py_version": discord_py_version,
            },
            "health": {
                "shard_id": shard_id,
                "shard_count": shard_count or 1,
                "reconnect_count": health_summary["reconnect_count"],
                "rate_limit_hits": health_summary["rate_limit_hits"],
                "avg_latency_ms": health_summary["avg_latency_ms"],
            },
        },
    }

    logger.debug("Bot Status Fetched", [
        ("User", str(payload.sub)),
        ("Online", str(bot_online)),
        ("Uptime", f"{uptime_seconds}s"),
        ("Latency", f"{latency_ms}ms"),
    ])

    return JSONResponse(content=response)


# =============================================================================
# Bot Logs
# =============================================================================

@router.get("/logs")
async def get_bot_logs(
    limit: int = Query(100, ge=1, le=500, description="Maximum number of logs"),
    level: str = Query("all", description="Filter by level: all, info, warning, error"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    search: Optional[str] = Query(None, description="Search in log messages"),
    module: Optional[str] = Query(None, description="Filter by module"),
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get paginated bot logs from persistent SQLite storage.

    Returns recent log entries with optional level filtering and search.
    Logs persist for 7 days across bot restarts.
    """
    log_storage = get_log_storage()
    logs, total = log_storage.get_logs(
        limit=limit,
        offset=offset,
        level=level if level.lower() != "all" else None,
        search=search,
        module=module,
    )

    response = {
        "success": True,
        "data": {
            "logs": [log.to_dict() for log in logs],
            "total": total,
            "limit": limit,
            "offset": offset,
            "level": level,
        },
    }

    logger.debug("Bot Logs Fetched", [
        ("User", str(payload.sub)),
        ("Count", str(len(logs))),
        ("Level", level),
        ("Limit", str(limit)),
    ])

    return JSONResponse(content=response)


# =============================================================================
# Latency History
# =============================================================================

@router.get("/latency-history")
async def get_latency_history(
    payload: TokenPayload = Depends(require_auth),
) -> JSONResponse:
    """
    Get latency history for graphing.

    Returns up to 60 latency measurements (last ~1 hour).
    """
    health_tracker = get_health_tracker()
    history = health_tracker.get_latency_history()

    return JSONResponse(content={
        "success": True,
        "data": {
            "history": history,
            "count": len(history),
        },
    })


__all__ = ["router"]
