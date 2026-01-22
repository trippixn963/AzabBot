"""
Azab Discord Bot - Core Package
==============================

Core components and utilities for the Azab Discord bot.
This package contains essential services like database management,
configuration, logging, and health monitoring.

DESIGN:
    Core modules are designed as singletons or global instances
    to ensure consistent state across the application:
    - get_config() returns the same Config instance
    - get_db() returns the same Database instance
    - logger is a global Logger instance

    All core modules are imported here for convenient access.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Core Imports
# =============================================================================

from .config import (
    Config,
    ConfigValidationError,
    EmbedColors,
    NY_TZ,
    get_config,
    is_developer,
    is_moderator,
)

from .database import Database, get_db

from .logger import logger, Logger, TreeSymbols

from .health import HealthCheckServer

from .constants import (
    # Time
    SECONDS_PER_MINUTE,
    SECONDS_PER_HOUR,
    SECONDS_PER_DAY,
    SECONDS_PER_WEEK,
    # Network
    HEALTH_CHECK_PORT,
    STATS_API_PORT,
    # Intervals
    MUTE_CHECK_INTERVAL,
    PRESENCE_UPDATE_INTERVAL,
    # Cooldowns
    COMMAND_COOLDOWN,
    PRISONER_COOLDOWN,
    # Moderation
    WARNING_DECAY_DAYS,
    SNIPE_MAX_AGE,
    SNIPE_LIMIT,
    MAX_PURGE_AMOUNT,
    BULK_DELETE_LIMIT,
    # Colors
    COLOR_GREEN,
    COLOR_RED,
    COLOR_ORANGE,
    COLOR_BLUE,
)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Config
    "Config",
    "ConfigValidationError",
    "EmbedColors",
    "NY_TZ",
    "get_config",
    "is_developer",
    "is_moderator",
    # Database
    "Database",
    "get_db",
    # Logger
    "logger",
    "Logger",
    "TreeSymbols",
    # Health
    "HealthCheckServer",
    # Constants (commonly used)
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "SECONDS_PER_WEEK",
    "HEALTH_CHECK_PORT",
    "STATS_API_PORT",
    "MUTE_CHECK_INTERVAL",
    "PRESENCE_UPDATE_INTERVAL",
    "COMMAND_COOLDOWN",
    "PRISONER_COOLDOWN",
    "WARNING_DECAY_DAYS",
    "SNIPE_MAX_AGE",
    "SNIPE_LIMIT",
    "MAX_PURGE_AMOUNT",
    "BULK_DELETE_LIMIT",
    "COLOR_GREEN",
    "COLOR_RED",
    "COLOR_ORANGE",
    "COLOR_BLUE",
]
