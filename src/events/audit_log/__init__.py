"""
Azab Discord Bot - Audit Log Events Package
============================================

Handles audit log entries and routes them to mod_tracker and logging_service.

Structure:
    - antinuke.py: Anti-nuke detection routing
    - mod_tracker.py: Mod tracker routing with helper methods
    - logging.py: Logging service routing with helper methods
    - cog.py: Main AuditLogEvents cog with event listeners

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .cog import AuditLogEvents

__all__ = ["AuditLogEvents"]
