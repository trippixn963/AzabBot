"""
AzabBot - Stats Router Module
=============================

Combines all stats sub-routers into a single router.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from fastapi import APIRouter

from .public import router as public_router
from .leaderboard import router as leaderboard_router
from .dashboard import router as dashboard_router
from .moderators import router as moderators_router
from .activity import router as activity_router
from .server import router as server_router


# Main stats router that combines all sub-routers
router = APIRouter(prefix="/stats", tags=["Statistics"])

# Include all sub-routers (order matters for route matching)
# Public routes first (no auth)
router.include_router(public_router)      # GET /stats
router.include_router(leaderboard_router) # GET /stats/leaderboard, /stats/user/{id}

# Authenticated routes
router.include_router(dashboard_router)   # GET /stats/dashboard
router.include_router(moderators_router)  # GET /stats/peak-hours, /stats/moderators/*
router.include_router(activity_router)    # GET /stats/activity
router.include_router(server_router)      # GET /stats/server


__all__ = ["router"]
