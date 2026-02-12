"""
AzabBot - API Models
====================

Pydantic models for request/response validation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .base import *
from .auth import *
from .cases import *
from .tickets import *
from .appeals import *
from .users import *
from .stats import *


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # base.py
    "APIResponse",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationMeta",
    "HealthResponse",
    "DiscordStatus",
    "UserBrief",
    "ModeratorBrief",
    "WSMessage",
    "WSEventType",
    # auth.py
    "CheckModeratorRequest",
    "RegisterRequest",
    "LoginRequest",
    "CheckModeratorResponse",
    "DiscordUserInfo",
    "AuthTokenResponse",
    "AuthenticatedUser",
    "GuildInfo",
    "TokenPayload",
    # cases.py
    "CaseType",
    "CaseStatus",
    "CaseBrief",
    # tickets.py
    "TicketStatus",
    "TicketPriority",
    "TicketCategory",
    "TicketBrief",
    "TicketDetail",
    "TicketMessage",
    "TicketStats",
    # appeals.py
    "AppealStatus",
    "AppealType",
    "AppealBrief",
    "AppealDetail",
    "AppealFormData",
    "AppealStats",
    # users.py
    "UserProfile",
    "UserSearchResult",
    "ModerationNote",
    # stats.py
    "DashboardStats",
    "ModeratorStats",
    "LeaderboardEntry",
    "ActivityChartData",
    "ServerInfo",
    "SystemHealth",
]
