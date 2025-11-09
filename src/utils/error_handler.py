"""
Azab Discord Bot - Enhanced Error Handler
=========================================

Provides detailed error context and improved logging for better debugging.

Features:
- Detailed error context with stack traces
- User-friendly error messages
- Error categorization (Discord, API, Database, AI)
- Automatic error recovery suggestions
- Discord-specific context capture
- Critical error file logging
- Safe execution decorator

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import traceback
import sys
from typing import Optional, Dict, Any
from datetime import datetime
import discord

from src.core.logger import logger


class ErrorContext:
    """Captures and formats detailed error context"""

    @staticmethod
    def get_full_context(e: Exception, location: str, **kwargs) -> Dict[str, Any]:
        """
        Get comprehensive error context.

        Args:
            e: The exception
            location: Where the error occurred
            **kwargs: Additional context (user, message, etc.)

        Returns:
            Dictionary with full error context
        """
        context = {
            'timestamp': datetime.now().isoformat(),
            'location': location,
            'error_type': type(e).__name__,
            'error_message': str(e),
            'traceback': traceback.format_exc(),
            'python_version': sys.version,
            'additional_context': kwargs
        }

        # Add Discord-specific context if available
        if 'message' in kwargs and isinstance(kwargs['message'], discord.Message):
            msg = kwargs['message']
            context['discord_context'] = {
                'guild': msg.guild.name if msg.guild else 'DM',
                'channel': msg.channel.name if hasattr(msg.channel, 'name') else str(msg.channel),
                'author': str(msg.author),
                'author_id': msg.author.id,
                'content': msg.content[:100] if msg.content else None
            }

        if 'member' in kwargs and isinstance(kwargs['member'], discord.Member):
            member = kwargs['member']
            context['member_context'] = {
                'name': str(member),
                'id': member.id,
                'roles': [role.name for role in member.roles],
                'joined_at': member.joined_at.isoformat() if member.joined_at else None
            }

        return context


class ErrorHandler:
    """Enhanced error handling with context and recovery"""

    ERROR_CATEGORIES = {
        'discord': [
            discord.errors.Forbidden,
            discord.errors.HTTPException,
            discord.errors.NotFound
        ],
        'api': [
            ConnectionError,
            TimeoutError,
            OSError
        ],
        'database': [
            'sqlite3.Error',
            'sqlite3.OperationalError',
            'sqlite3.IntegrityError'
        ],
        'ai': [
            'openai.error',
            'RateLimitError',
            'APIError'
        ]
    }

    @classmethod
    def categorize_error(cls, e: Exception) -> str:
        """
        Categorize the error type.

        Args:
            e: The exception

        Returns:
            Error category string
        """
        error_type = type(e)

        for category, error_types in cls.ERROR_CATEGORIES.items():
            if any(isinstance(e, err_type) if isinstance(err_type, type) else
                   err_type in str(type(e)) for err_type in error_types):
                return category

        return 'general'

    @classmethod
    def get_recovery_suggestion(cls, e: Exception, category: str) -> str:
        """
        Get recovery suggestion based on error type.

        Args:
            e: The exception
            category: Error category

        Returns:
            Recovery suggestion string
        """
        suggestions = {
            'discord': {
                discord.errors.Forbidden: "Check bot permissions in server settings",
                discord.errors.HTTPException: "Discord API issue - will retry automatically",
                discord.errors.NotFound: "Resource not found - check IDs and channels"
            },
            'api': {
                ConnectionError: "Network connection issue - check internet connection",
                TimeoutError: "Request timed out - will retry automatically",
                OSError: "System resource issue - check disk space and permissions"
            },
            'database': {
                'OperationalError': "Database locked - will retry automatically",
                'IntegrityError': "Database constraint violation - check data validity",
                'Error': "General database error - check database file"
            },
            'ai': {
                'RateLimitError': "OpenAI rate limit - will use fallback responses",
                'APIError': "OpenAI API error - check API key and quota",
                'error': "AI service error - using fallback responses"
            }
        }

        if category in suggestions:
            for error_type, suggestion in suggestions[category].items():
                if isinstance(error_type, type) and isinstance(e, error_type):
                    return suggestion
                elif isinstance(error_type, str) and error_type in str(type(e)):
                    return suggestion

        return "Unexpected error - check logs for details"

    @classmethod
    def handle(cls, e: Exception, location: str, critical: bool = False, **context) -> None:
        """
        Handle an error with full context.

        Args:
            e: The exception
            location: Where the error occurred
            critical: Whether this error should stop execution
            **context: Additional context
        """
        # Get error details
        category = cls.categorize_error(e)
        suggestion = cls.get_recovery_suggestion(e, category)
        full_context = ErrorContext.get_full_context(e, location, **context)

        # Format error message
        error_msg = f"[{category.upper()}] in {location}"

        # Log with appropriate level
        if critical:
            logger.error(f"💥 CRITICAL ERROR {error_msg}: {full_context['error_type']} - {full_context['error_message']} | Recovery: {suggestion}")

            # Log full traceback for critical errors
            logger.info(f"Traceback:\n{full_context['traceback']}")

            # If Discord context available, log it
            if 'discord_context' in full_context:
                dc = full_context['discord_context']
                logger.info(f"Discord Context: Guild={dc['guild']}, Channel={dc['channel']}, User={dc['author']}")
        else:
            logger.warning(f"⚠️ ERROR {error_msg}: {full_context['error_type']} - {str(e)[:100]} | Recovery: {suggestion}")

        # Store error for analysis (could be sent to monitoring service)
        if critical:
            cls._store_critical_error(full_context)

    @staticmethod
    def _store_critical_error(context: Dict[str, Any]) -> None:
        """
        Store critical error for later analysis.

        Args:
            context: Full error context
        """
        try:
            import json
            from pathlib import Path

            error_dir = Path('logs/errors')
            error_dir.mkdir(exist_ok=True, parents=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            error_file = error_dir / f"error_{timestamp}.json"

            with open(error_file, 'w') as f:
                json.dump(context, f, indent=2, default=str)

            logger.info(f"Critical error saved to {error_file}")
        except Exception as save_error:
            logger.info(f"Failed to save error details: {save_error}")


def safe_execute(func):
    """
    Decorator for safe function execution with error handling.

    Usage:
        @safe_execute
        async def my_function():
            # function code
    """
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            ErrorHandler.handle(
                e,
                location=f"{func.__module__}.{func.__name__}",
                critical=False,
                function_args=str(args)[:100],
                function_kwargs=str(kwargs)[:100]
            )
            return None

    return wrapper