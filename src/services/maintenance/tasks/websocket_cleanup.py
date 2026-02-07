"""
AzabBot - WebSocket Cleanup Task
================================

Clean up stale WebSocket connections.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT, WS_STALE_CONNECTION_THRESHOLD
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.api.services.websocket import WSConnection


class WebSocketCleanupTask(MaintenanceTask):
    """
    Clean up stale WebSocket connections.

    Connections may become stale if:
    - Client disconnects without proper close (network issues)
    - Client browser crashes or is force-closed
    - Mobile devices go to sleep without graceful disconnect

    This task finds connections that haven't had a heartbeat response
    in a while and removes them from tracking.
    """

    name = "WebSocket Cleanup"

    async def should_run(self) -> bool:
        """Check if WebSocket manager is available."""
        try:
            from src.api.services.websocket import get_ws_manager
            return get_ws_manager() is not None
        except ImportError:
            return False

    async def run(self) -> Dict[str, Any]:
        """Clean up stale WebSocket connections."""
        disconnected: int = 0
        errors: int = 0

        try:
            from src.api.services.websocket import get_ws_manager, WSConnection
            from starlette.websockets import WebSocketState

            ws_manager = get_ws_manager()
            now: datetime = datetime.utcnow()

            # Get connection stats before cleanup
            connections_before: int = len(ws_manager._connections)
            users_before: int = len(ws_manager._user_connections)

            # Use set for O(1) duplicate checking
            stale_conn_ids: Set[str] = set()
            stale_connections: List[Tuple[str, "WSConnection", float]] = []

            # =================================================================
            # Find stale connections
            # =================================================================
            try:
                async with ws_manager._lock:
                    for conn_id, connection in list(ws_manager._connections.items()):
                        heartbeat_age: float = (now - connection.last_heartbeat).total_seconds()
                        is_stale: bool = False

                        # Check last heartbeat time
                        if heartbeat_age > WS_STALE_CONNECTION_THRESHOLD:
                            is_stale = True

                        # Check for connections in disconnected state
                        if not is_stale:
                            try:
                                if connection.websocket.client_state != WebSocketState.CONNECTED:
                                    is_stale = True
                            except Exception:
                                # Can't check state - might be stale
                                is_stale = True

                        if is_stale and conn_id not in stale_conn_ids:
                            stale_conn_ids.add(conn_id)
                            stale_connections.append((conn_id, connection, heartbeat_age))

            except Exception as e:
                errors += 1
                logger.error("WebSocket Scan Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Disconnect stale connections (outside lock to avoid deadlock)
            # =================================================================
            for conn_id, connection, age in stale_connections:
                try:
                    await ws_manager.disconnect(conn_id)
                    disconnected += 1

                    logger.debug("Stale WebSocket Removed", [
                        ("Connection ID", conn_id[:8]),
                        ("User ID", str(connection.user_id) if connection.user_id else "Anonymous"),
                        ("Last Heartbeat", f"{age:.0f}s ago"),
                    ])

                except Exception as e:
                    errors += 1
                    logger.debug("WebSocket Disconnect Error", [
                        ("Connection ID", conn_id[:8]),
                        ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                    ])

            # =================================================================
            # Log results
            # =================================================================
            connections_after: int = len(ws_manager._connections)
            users_after: int = len(ws_manager._user_connections)

            if disconnected > 0:
                logger.tree("WebSocket Cleanup Complete", [
                    ("Stale Connections", f"{disconnected} removed"),
                    ("Active Connections", f"{connections_before} → {connections_after}"),
                    ("Unique Users", f"{users_before} → {users_after}"),
                    ("Threshold", f"{WS_STALE_CONNECTION_THRESHOLD}s no heartbeat"),
                    ("Errors", str(errors)),
                ], emoji="🔌")

            return {
                "success": errors == 0,
                "disconnected": disconnected,
                "connections_before": connections_before,
                "connections_after": connections_after,
                "errors": errors,
            }

        except ImportError:
            logger.debug("WebSocket Cleanup Skipped", [("Reason", "API not available")])
            return {"success": True, "disconnected": 0, "skipped": True}

        except Exception as e:
            logger.error("WebSocket Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        if result.get("skipped"):
            return "skipped"
        if not result.get("success"):
            return "failed"

        disconnected: int = result.get("disconnected", 0)
        if disconnected > 0:
            return f"{disconnected} cleaned"

        connections: int = result.get("connections_after", 0)
        return f"{connections} active"


__all__ = ["WebSocketCleanupTask"]
