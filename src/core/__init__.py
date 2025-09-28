"""
Azab Discord Bot - Core Package
==============================

Core components and utilities for the Azab Discord bot.
This package contains essential services like database management,
logging systems, and other core functionality.

Components:
- database.py: SQLite database wrapper for message logging
- logger.py: Custom logging system with EST timezone support

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.4.0
"""

from .database import Database
from .logger import logger

__all__ = ['Database', 'logger']