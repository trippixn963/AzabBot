"""
AzabBot - API Services
======================

Service layer for the API.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .websocket import WebSocketManager, get_ws_manager
from .auth import AuthService, get_auth_service

__all__ = [
    "WebSocketManager",
    "get_ws_manager",
    "AuthService",
    "get_auth_service",
]
