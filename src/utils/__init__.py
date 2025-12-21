"""
Azab Discord Bot - Utils Package
================================

Utility modules for the Azab Discord bot.
Contains helper functions, validators, and utility classes.

DESIGN:
    Utils are stateless helper functions and classes that can be
    used anywhere in the codebase. They should not have side effects
    or depend on bot state.

    To add new utilities:
    1. Create new_utility.py in this directory
    2. Add import and export below
    3. Use from src.utils import your_function

Available Utilities:
    format_duration: Time formatting (minutes → "1d 2h 30m")
    Validators: Input validation and sanitization
    ErrorHandler: Enhanced error handling with context
    AIUsageMonitor: OpenAI API usage tracking
    Footer: Standardized embed footer with cached avatar

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Utility Imports
# =============================================================================

from .time_format import format_duration
from .validators import Validators, ValidationError, InputSanitizer
from .error_handler import ErrorHandler, ErrorContext, safe_execute
from .ai_monitor import AIUsageMonitor, ai_monitor
from .footer import FOOTER_TEXT, init_footer, refresh_avatar, set_footer


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Time formatting
    "format_duration",
    # Validators
    "Validators",
    "ValidationError",
    "InputSanitizer",
    # Error handling
    "ErrorHandler",
    "ErrorContext",
    "safe_execute",
    # AI monitoring
    "AIUsageMonitor",
    "ai_monitor",
    # Footer
    "FOOTER_TEXT",
    "init_footer",
    "refresh_avatar",
    "set_footer",
]
