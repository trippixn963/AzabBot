"""
AzabBot - API Services
======================

Service layer for the API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# WebSocket
from .websocket import WebSocketManager, get_ws_manager

# Authentication
from .auth import AuthService, get_auth_service

# Event logging (Discord events for dashboard)
from .event_storage import EventStorage, EventType, get_event_storage
from .event_logger import EventLogger, event_logger

# System logs
from .log_storage import LogStorage, get_log_storage
from .log_buffer import LogBuffer, get_log_buffer

# Status broadcasting
from .status_broadcaster import StatusBroadcaster, get_status_broadcaster

# Server snapshots
from .snapshots import SnapshotService, get_snapshot_service

__all__ = [
    # WebSocket
    "WebSocketManager",
    "get_ws_manager",
    # Auth
    "AuthService",
    "get_auth_service",
    # Events
    "EventStorage",
    "EventType",
    "get_event_storage",
    "EventLogger",
    "event_logger",
    # Logs
    "LogStorage",
    "get_log_storage",
    "LogBuffer",
    "get_log_buffer",
    # Status
    "StatusBroadcaster",
    "get_status_broadcaster",
    # Snapshots
    "SnapshotService",
    "get_snapshot_service",
]
