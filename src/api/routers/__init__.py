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
from .case_transcripts import router as case_transcripts_router
from .appeals import router as appeals_router
from .appeal_form import router as appeal_form_router
from .users import router as users_router
from .stats import router as stats_router
from .websocket import router as websocket_router
from .server import router as server_router
from .dashboard import router as dashboard_router
from .bans import router as bans_router

__all__ = [
    "health_router",
    "auth_router",
    "cases_router",
    "tickets_router",
    "transcripts_router",
    "case_transcripts_router",
    "appeals_router",
    "appeal_form_router",
    "users_router",
    "stats_router",
    "websocket_router",
    "server_router",
    "dashboard_router",
    "bans_router",
]
