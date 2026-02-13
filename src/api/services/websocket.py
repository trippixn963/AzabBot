"""
AzabBot - WebSocket Manager
===========================

Manages WebSocket connections for real-time dashboard updates.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional, Set
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.core.logger import logger
from src.api.config import get_api_config
from src.api.models.base import WSMessage, WSEventType
from src.utils.async_utils import create_safe_task


# =============================================================================
# Connection Model
# =============================================================================

@dataclass
class WSConnection:
    """Represents an active WebSocket connection."""

    websocket: WebSocket
    user_id: Optional[int] = None
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    subscriptions: Set[str] = field(default_factory=set)

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


# =============================================================================
# WebSocket Manager
# =============================================================================

class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events to connected clients.

    Features:
    - Connection tracking with authentication
    - Subscription-based event filtering
    - Heartbeat monitoring
    - Graceful disconnect handling
    - Event broadcasting to all or specific clients

    Usage:
        # In your bot code when something happens:
        from src.api.services import get_ws_manager
        await get_ws_manager().broadcast_case_created(case_data)
    """

    def __init__(self) -> None:
        self._connections: Dict[str, WSConnection] = {}
        self._user_connections: Dict[int, Set[str]] = {}  # user_id -> connection_ids
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._config = get_api_config()

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(
        self,
        websocket: WebSocket,
        connection_id: str,
        user_id: Optional[int] = None,
    ) -> bool:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
            connection_id: Unique identifier for this connection
            user_id: Optional authenticated user ID

        Returns:
            True if connection was accepted, False if limit reached
        """
        async with self._lock:
            # Check connection limit
            if len(self._connections) >= self._config.ws_max_connections:
                logger.warning("WebSocket Connection Rejected", [
                    ("Reason", "Max connections reached"),
                    ("Current", str(len(self._connections))),
                    ("Max", str(self._config.ws_max_connections)),
                ])
                return False

            await websocket.accept()

            connection = WSConnection(
                websocket=websocket,
                user_id=user_id,
            )
            self._connections[connection_id] = connection

            # Track user connections
            if user_id:
                if user_id not in self._user_connections:
                    self._user_connections[user_id] = set()
                self._user_connections[user_id].add(connection_id)

            logger.tree("WebSocket Connected", [
                ("Connection ID", connection_id[:8]),
                ("User ID", str(user_id) if user_id else "Anonymous"),
                ("Total Connections", str(len(self._connections))),
            ], emoji="🔌")

            # Send welcome message (use unlocked version since we already hold the lock)
            await self._send_to_connection_unlocked(connection_id, WSMessage(
                type=WSEventType.CONNECTED,
                data={
                    "connection_id": connection_id,
                    "authenticated": user_id is not None,
                    "heartbeat_interval": self._config.ws_heartbeat_interval,
                },
            ))

            return True

    async def disconnect(self, connection_id: str) -> None:
        """Remove a connection."""
        async with self._lock:
            if connection_id not in self._connections:
                return

            connection = self._connections.pop(connection_id)

            # Remove from user tracking
            if connection.user_id and connection.user_id in self._user_connections:
                self._user_connections[connection.user_id].discard(connection_id)
                if not self._user_connections[connection.user_id]:
                    self._user_connections.pop(connection.user_id, None)

            logger.tree("WebSocket Disconnected", [
                ("Connection ID", connection_id[:8]),
                ("User ID", str(connection.user_id) if connection.user_id else "Anonymous"),
                ("Total Connections", str(len(self._connections))),
            ], emoji="🔌")

    async def authenticate(self, connection_id: str, user_id: int) -> bool:
        """Authenticate an existing connection."""
        async with self._lock:
            if connection_id not in self._connections:
                return False

            connection = self._connections[connection_id]
            connection.user_id = user_id

            # Track user connection
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(connection_id)

            return True

    # =========================================================================
    # Subscriptions
    # =========================================================================

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        """Subscribe a connection to a channel."""
        async with self._lock:
            if connection_id not in self._connections:
                return False
            self._connections[connection_id].subscriptions.add(channel)
            return True

    async def unsubscribe(self, connection_id: str, channel: str) -> bool:
        """Unsubscribe a connection from a channel."""
        async with self._lock:
            if connection_id not in self._connections:
                return False
            self._connections[connection_id].subscriptions.discard(channel)
            return True

    # =========================================================================
    # Message Sending
    # =========================================================================

    async def _send_to_connection_unlocked(
        self,
        connection_id: str,
        message: WSMessage,
    ) -> bool:
        """Send a message to a specific connection. Caller must hold the lock."""
        if connection_id not in self._connections:
            return False

        connection = self._connections[connection_id]
        try:
            if connection.websocket.client_state == WebSocketState.CONNECTED:
                await connection.websocket.send_json(message.model_dump(mode="json"))
                return True
        except Exception as e:
            logger.debug("WebSocket Send Failed", [
                ("Connection", connection_id[:8]),
                ("Error", str(e)[:50]),
            ])
            # Schedule disconnect (outside lock to avoid deadlock)
            create_safe_task(self.disconnect(connection_id), "WS Disconnect")
        return False

    async def _send_to_connection(self, connection_id: str, message: WSMessage) -> bool:
        """Send a message to a specific connection."""
        async with self._lock:
            return await self._send_to_connection_unlocked(connection_id, message)

    async def send_to_user(self, user_id: int, message: WSMessage) -> int:
        """
        Send a message to all connections for a specific user.

        Returns:
            Number of connections message was sent to
        """
        sent = 0
        connection_ids = self._user_connections.get(user_id, set()).copy()
        for conn_id in connection_ids:
            if await self._send_to_connection(conn_id, message):
                sent += 1
        return sent

    async def broadcast(
        self,
        message: WSMessage,
        channel: Optional[str] = None,
        exclude_connections: Optional[Set[str]] = None,
    ) -> int:
        """
        Broadcast a message to all connected clients.

        Args:
            message: Message to broadcast
            channel: If provided, only send to connections subscribed to this channel
            exclude_connections: Connection IDs to exclude

        Returns:
            Number of connections message was sent to
        """
        exclude = exclude_connections or set()
        sent = 0

        # Get snapshot of connections
        async with self._lock:
            connections = list(self._connections.items())

        for conn_id, connection in connections:
            if conn_id in exclude:
                continue

            # Check channel subscription if specified
            if channel and channel not in connection.subscriptions:
                continue

            if await self._send_to_connection(conn_id, message):
                sent += 1

        return sent

    # =========================================================================
    # Event Broadcasting Helpers
    # =========================================================================

    async def broadcast_case_created(self, case_data: Dict[str, Any]) -> int:
        """Broadcast a new case event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.CASE_CREATED,
            data=case_data,
        ), channel="cases")

    async def broadcast_case_updated(self, case_data: Dict[str, Any]) -> int:
        """Broadcast a case update event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.CASE_UPDATED,
            data=case_data,
        ), channel="cases")

    async def broadcast_case_resolved(self, case_data: Dict[str, Any]) -> int:
        """Broadcast a case resolved event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.CASE_RESOLVED,
            data=case_data,
        ), channel="cases")

    async def broadcast_ticket_created(self, ticket_data: Dict[str, Any]) -> int:
        """Broadcast a new ticket event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.TICKET_CREATED,
            data=ticket_data,
        ), channel="tickets")

    async def broadcast_ticket_claimed(self, ticket_data: Dict[str, Any]) -> int:
        """Broadcast a ticket claimed event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.TICKET_CLAIMED,
            data=ticket_data,
        ), channel="tickets")

    async def broadcast_ticket_closed(self, ticket_data: Dict[str, Any]) -> int:
        """Broadcast a ticket closed event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.TICKET_CLOSED,
            data=ticket_data,
        ), channel="tickets")

    async def broadcast_appeal_submitted(self, appeal_data: Dict[str, Any]) -> int:
        """Broadcast a new appeal event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.APPEAL_SUBMITTED,
            data=appeal_data,
        ), channel="appeals")

    async def broadcast_appeal_resolved(
        self,
        appeal_data: Dict[str, Any],
        approved: bool,
    ) -> int:
        """Broadcast an appeal resolution event."""
        event_type = WSEventType.APPEAL_APPROVED if approved else WSEventType.APPEAL_DENIED
        return await self.broadcast(WSMessage(
            type=event_type,
            data=appeal_data,
        ), channel="appeals")

    async def broadcast_mod_action(self, action_data: Dict[str, Any]) -> int:
        """Broadcast a moderation action event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.MOD_ACTION,
            data=action_data,
        ), channel="moderation")

    async def broadcast_stats_updated(self, stats_data: Dict[str, Any] = None) -> int:
        """Broadcast a stats update event to trigger dashboard refresh."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_UPDATED,
            data=stats_data or {},
        ), channel="stats")

    async def broadcast_stats_leaderboard(self, leaderboard_data: list, period: str) -> int:
        """Broadcast full leaderboard data."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_LEADERBOARD,
            data={"leaderboard": leaderboard_data, "period": period},
        ), channel="stats")

    async def broadcast_stats_personal(self, moderator_id: str, stats_data: Dict[str, Any]) -> int:
        """Broadcast personal stats for a specific moderator."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_PERSONAL,
            data={"moderator_id": moderator_id, "stats": stats_data},
        ), channel="stats")

    async def broadcast_stats_activity(self, activity_data: list, days: int) -> int:
        """Broadcast activity chart data."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_ACTIVITY,
            data={"activity": activity_data, "days": days},
        ), channel="stats")

    async def broadcast_stats_peak_hours(self, moderator_id: str, peak_hours: list) -> int:
        """Broadcast peak hours for a specific moderator."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_PEAK_HOURS,
            data={"moderator_id": moderator_id, "peak_hours": peak_hours},
        ), channel="stats")

    async def broadcast_stats_server_peak_hours(self, peak_hours: list) -> int:
        """Broadcast server-wide peak hours."""
        return await self.broadcast(WSMessage(
            type=WSEventType.STATS_SERVER_PEAK_HOURS,
            data={"peak_hours": peak_hours},
        ), channel="stats")

    async def broadcast_bot_status(self, status_data: Dict[str, Any]) -> int:
        """Broadcast bot status update (latency, CPU, memory)."""
        return await self.broadcast(WSMessage(
            type=WSEventType.BOT_STATUS,
            data=status_data,
        ), channel="bot")

    async def broadcast_bot_log(self, log_data: Dict[str, Any]) -> int:
        """Broadcast a new log entry."""
        return await self.broadcast(WSMessage(
            type=WSEventType.BOT_LOG,
            data=log_data,
        ), channel="bot")

    async def broadcast_command_executed(self, command_data: Dict[str, Any]) -> int:
        """Broadcast a command execution event."""
        return await self.broadcast(WSMessage(
            type=WSEventType.COMMAND_EXECUTED,
            data=command_data,
        ), channel="bot")

    async def broadcast_discord_event(self, event_data: Dict[str, Any]) -> int:
        """Broadcast a Discord event (ban, kick, timeout, etc.) for dashboard."""
        return await self.broadcast(WSMessage(
            type=WSEventType.DISCORD_EVENT,
            data=event_data,
        ), channel="events")

    async def broadcast_user_banned(self, ban_data: Dict[str, Any]) -> int:
        """Broadcast a user banned event for bans page."""
        return await self.broadcast(WSMessage(
            type=WSEventType.USER_BANNED,
            data=ban_data,
        ), channel="bans")

    async def broadcast_user_unbanned(self, unban_data: Dict[str, Any]) -> int:
        """Broadcast a user unbanned event for bans page."""
        return await self.broadcast(WSMessage(
            type=WSEventType.USER_UNBANNED,
            data=unban_data,
        ), channel="bans")

    # =========================================================================
    # Heartbeat
    # =========================================================================

    async def start_heartbeat(self) -> None:
        """Start the heartbeat task."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = create_safe_task(self._heartbeat_loop(), "WS Heartbeat")

    async def stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to all connections."""
        while True:
            try:
                await asyncio.sleep(self._config.ws_heartbeat_interval)
                await self.broadcast(WSMessage(
                    type=WSEventType.HEARTBEAT,
                    data={"connections": len(self._connections)},
                ))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Heartbeat Error", [("Error", str(e)[:50])])

    # =========================================================================
    # Stats
    # =========================================================================

    @property
    def connection_count(self) -> int:
        """Get current number of connections."""
        return len(self._connections)

    @property
    def authenticated_count(self) -> int:
        """Get number of authenticated connections."""
        return sum(1 for c in self._connections.values() if c.is_authenticated)

    def get_stats(self) -> Dict[str, Any]:
        """Get WebSocket statistics."""
        return {
            "total_connections": len(self._connections),
            "authenticated_connections": self.authenticated_count,
            "unique_users": len(self._user_connections),
        }


# =============================================================================
# Singleton
# =============================================================================

_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """Get the WebSocket manager singleton."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager


__all__ = ["WebSocketManager", "WSConnection", "get_ws_manager"]
