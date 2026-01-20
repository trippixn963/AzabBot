"""
Azab Discord Bot - Stats API Package
=====================================

HTTP API server exposing moderation statistics for the dashboard.

Structure:
    - middleware.py: Rate limiting, caching, and middleware functions
    - handlers.py: HTTP endpoint handlers
    - data_helpers.py: Data fetching and transformation methods
    - service.py: Main AzabAPI class

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import AzabAPI

__all__ = ["AzabAPI"]
