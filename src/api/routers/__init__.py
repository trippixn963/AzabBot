"""
AzabBot - API Routers
=====================

Route handlers for the API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .health import router as health_router
from .auth import router as auth_router
from .cases import router as cases_router
from .tickets import router as tickets_router
from .transcripts import router as transcripts_router
from .appeals import router as appeals_router
from .appeal_form import router as appeal_form_router
from .users import router as users_router
from .stats import router as stats_router
from .websocket import router as websocket_router

__all__ = [
    "health_router",
    "auth_router",
    "cases_router",
    "tickets_router",
    "transcripts_router",
    "appeals_router",
    "appeal_form_router",
    "users_router",
    "stats_router",
    "websocket_router",
]
