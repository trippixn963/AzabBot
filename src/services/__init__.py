"""
AzabBot - Services Package
==========================

External service integrations for the Azab Discord bot.
This package contains integrations with third-party services
and background tasks.

DESIGN:
    Services are standalone classes that handle external API calls.
    They should:
    - Be async-compatible for non-blocking I/O
    - Handle their own error cases gracefully
    - Provide fallback behavior when APIs are unavailable

    To add a new service:
    1. Create new_service.py in this directory
    2. Follow the existing service pattern
    3. Add import and export below
    4. Initialize in bot.py and pass to handlers as needed

Available Services:
    MuteScheduler: Background service for automatic mute expiration
    CaseLogService: Forum thread logging for moderation cases
    ModTrackerService: Mod activity tracking in forum threads
    LoggingService: Server activity logging with categorized forum threads

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Service Imports
# =============================================================================

from .mute_scheduler import MuteScheduler
from .case_log import CaseLogService
from .mod_tracker import ModTrackerService
from .server_logs import LoggingService
from .status_webhook import StatusWebhookService, get_status_service
from .maintenance import MaintenanceService
# Compatibility aliases
from .status_webhook import WebhookAlertService, get_alert_service


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "MuteScheduler",
    "CaseLogService",
    "ModTrackerService",
    "LoggingService",
    "StatusWebhookService",
    "get_status_service",
    "MaintenanceService",
    # Compatibility aliases
    "WebhookAlertService",
    "get_alert_service",
]
