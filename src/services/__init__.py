"""
Azab Discord Bot - Services Package
==================================

External service integrations for the Azab Discord bot.
This package contains integrations with third-party services
like AI providers and other external APIs.

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
    AIService: OpenAI GPT-4o-mini integration for AI-powered responses
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

from .ai_service import AIService
from .mute_scheduler import MuteScheduler
from .case_log import CaseLogService
from .mod_tracker import ModTrackerService
from .logging_service import LoggingService
from .webhook_alerts import WebhookAlertService, get_alert_service


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "AIService",
    "MuteScheduler",
    "CaseLogService",
    "ModTrackerService",
    "LoggingService",
    "WebhookAlertService",
    "get_alert_service",
]
