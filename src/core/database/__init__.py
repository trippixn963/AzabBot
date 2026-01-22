"""
AzabBot - Database Module
=========================

Centralized database management for AzabBot.

This module provides a modular database interface while maintaining
backward compatibility with existing code.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# For backward compatibility, import everything from the original database module
# This allows gradual migration to the modular structure
from src.core.database.manager import (
    DatabaseManager,
    get_db,
    DATA_DIR,
    DB_PATH,
)
from src.core.database.base import _safe_json_loads

# Backward compatibility alias
Database = DatabaseManager

# Export type definitions
from src.core.database.models import (
    MuteRecord,
    CaseLogRecord,
    TrackedModRecord,
    AltLinkRecord,
    JoinInfoRecord,
    ModNoteRecord,
    UsernameHistoryRecord,
    AppealRecord,
    MemberActivityRecord,
    PendingReasonRecord,
    TicketRecord,
)

__all__ = [
    # Main interface
    "DatabaseManager",
    "Database",  # Backward compatibility alias
    "get_db",

    # Helpers
    "_safe_json_loads",
    "DATA_DIR",
    "DB_PATH",

    # Type definitions
    "MuteRecord",
    "CaseLogRecord",
    "TrackedModRecord",
    "AltLinkRecord",
    "JoinInfoRecord",
    "ModNoteRecord",
    "UsernameHistoryRecord",
    "AppealRecord",
    "MemberActivityRecord",
    "PendingReasonRecord",
    "TicketRecord",
]
