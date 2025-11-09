"""
Azab Discord Bot - Core Package
==============================

Core components and utilities for the Azab Discord bot.
This package contains essential services like database management,
logging systems, and other core functionality.

Components:
- Database: SQLite database wrapper for message logging and analytics
- logger: Custom logging system with EST/EDT timezone support

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .database import Database
from .logger import logger

__all__ = ['Database', 'logger']