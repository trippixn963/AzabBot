"""
AzabBot - Health Router
=======================

Health check and system status endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends

from src.core.logger import logger
from src.api.dependencies import get_bot
from src.api.models.base import APIResponse
from src.api.models.stats import SystemHealth
from src.api.services.websocket import get_ws_manager


router = APIRouter(prefix="/health", tags=["Health"])

# Track startup time
_start_time = time.time()


@router.get("", response_model=APIResponse[dict])
async def health_check() -> APIResponse[dict]:
    """
    Basic health check endpoint.

    Returns simple status for load balancers and monitoring.
    """
    return APIResponse(
        success=True,
        data={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@router.get("/detailed", response_model=APIResponse[SystemHealth])
async def detailed_health(bot: Any = Depends(get_bot)) -> APIResponse[SystemHealth]:
    """
    Detailed system health including Discord connection status.

    Requires bot to be running for full metrics.
    """
    import psutil

    process = psutil.Process(os.getpid())

    # Calculate uptime
    uptime = int(time.time() - _start_time)

    # Get memory usage
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / (1024 * 1024)

    # Get CPU usage
    cpu_percent = process.cpu_percent(interval=0.1)

    # Discord status
    discord_connected = bot.is_ready() if bot else False
    discord_latency = int(bot.latency * 1000) if bot and bot.latency else 0
    guilds = len(bot.guilds) if bot else 0

    # Database status
    db_connected = True
    db_size: Optional[float] = None
    try:
        from src.core.database import get_db
        db = get_db()
        # Simple query to check connection
        db.fetchone("SELECT 1")

        # Get database file size
        if hasattr(db, "_db_path"):
            db_path = db._db_path
            if os.path.exists(db_path):
                db_size = os.path.getsize(db_path) / (1024 * 1024)
    except Exception:
        db_connected = False

    # WebSocket connections
    ws_manager = get_ws_manager()
    ws_connections = ws_manager.connection_count

    health = SystemHealth(
        status="healthy" if discord_connected and db_connected else "degraded",
        uptime_seconds=uptime,
        memory_mb=round(memory_mb, 2),
        cpu_percent=round(cpu_percent, 2),
        discord_connected=discord_connected,
        discord_latency_ms=discord_latency,
        guilds_connected=guilds,
        db_connected=db_connected,
        db_size_mb=round(db_size, 2) if db_size else None,
        ws_connections=ws_connections,
    )

    logger.debug("Health Check (Detailed)", [
        ("Status", health.status),
        ("Memory", f"{health.memory_mb}MB"),
        ("CPU", f"{health.cpu_percent}%"),
        ("Discord", "Connected" if discord_connected else "Disconnected"),
        ("WS Clients", str(ws_connections)),
    ])

    return APIResponse(success=True, data=health)


@router.get("/ready")
async def readiness_check(bot: Any = Depends(get_bot)) -> APIResponse[dict]:
    """
    Readiness check for Kubernetes/orchestrators.

    Returns 200 only if bot is fully ready to serve requests.
    """
    is_ready = bot.is_ready() if bot else False

    return APIResponse(
        success=is_ready,
        data={
            "ready": is_ready,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


__all__ = ["router"]
