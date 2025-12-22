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
    - logger is a global MiniTreeLogger instance

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

from .logger import logger, MiniTreeLogger, TreeSymbols

from .health import HealthCheckServer


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
    "MiniTreeLogger",
    "TreeSymbols",
    # Health
    "HealthCheckServer",
]
