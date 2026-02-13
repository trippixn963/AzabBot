"""
AzabBot - WebSocket Router
==========================

WebSocket endpoints for real-time updates.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from src.core.logger import logger
from src.api.services.websocket import get_ws_manager
from src.api.services.auth import get_auth_service
from src.api.services.stats import (
    get_leaderboard_data,
    get_moderator_stats_data,
    get_peak_hours_data,
    get_activity_data,
    get_recent_actions_data,
)
from src.api.dependencies import get_bot
from src.api.models.base import WSMessage, WSEventType

# Timeout for receiving messages (seconds)
# Short timeout to detect dead connections quickly
RECEIVE_TIMEOUT = 15


router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="JWT auth token"),
):
    """
    WebSocket endpoint for real-time dashboard updates.

    Connect with optional token for authentication:
        ws://host/api/azab/ws?token=<jwt_token>

    Events:
    - connected: Initial connection acknowledgment
    - heartbeat: Periodic ping from server
    - case_created/updated/resolved: Case events
    - ticket_created/claimed/closed: Ticket events
    - appeal_submitted/approved/denied: Appeal events
    - mod_action: General moderation action events

    Subscriptions:
    Send {"action": "subscribe", "channel": "cases"} to subscribe to specific channels.
    Available channels: cases, tickets, appeals, moderation
    """
    ws_manager = get_ws_manager()
    connection_id = str(uuid.uuid4())

    # Validate token if provided
    user_id: Optional[int] = None
    if token:
        auth_service = get_auth_service()
        payload = auth_service.get_token_payload(token)
        if payload:
            user_id = payload.sub

    # Accept connection
    accepted = await ws_manager.connect(websocket, connection_id, user_id)
    if not accepted:
        await websocket.close(code=1008, reason="Connection limit reached")
        return

    try:
        while True:
            # Check if connection is still open
            if websocket.client_state != WebSocketState.CONNECTED:
                break

            # Wait for messages from client with timeout
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=RECEIVE_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Send a ping to check if connection is alive
                try:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.HEARTBEAT,
                        data={},
                    ))
                    continue
                except WebSocketDisconnect:
                    break  # Connection dead

            # Handle client actions
            action = data.get("action")

            if action == "subscribe":
                channel = data.get("channel")
                if channel:
                    await ws_manager.subscribe(connection_id, channel)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.SUBSCRIBED,
                        data={"channel": channel},
                    ))

            elif action == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    await ws_manager.unsubscribe(connection_id, channel)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.UNSUBSCRIBED,
                        data={"channel": channel},
                    ))

            elif action == "authenticate":
                # Late authentication
                auth_token = data.get("token")
                if auth_token:
                    auth_service = get_auth_service()
                    payload = auth_service.get_token_payload(auth_token)
                    if payload:
                        await ws_manager.authenticate(connection_id, payload.sub)
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type=WSEventType.AUTHENTICATED,
                            data={"user_id": payload.sub},
                        ))
                    else:
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type=WSEventType.ERROR,
                            data={"message": "Invalid token"},
                        ))

            elif action == "ping":
                # Client ping - respond with pong
                await ws_manager._send_to_connection(connection_id, WSMessage(
                    type=WSEventType.PONG,
                    data={},
                ))

            elif action == "get_leaderboard":
                # Fetch and return leaderboard data
                try:
                    bot = get_bot()
                    period = data.get("period", "month")
                    leaderboard = await get_leaderboard_data(bot, period)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.STATS_LEADERBOARD,
                        data={"leaderboard": leaderboard, "period": period},
                    ))
                except Exception as e:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to fetch leaderboard: {str(e)}"},
                    ))

            elif action == "get_personal_stats":
                # Fetch personal stats for a moderator
                try:
                    bot = get_bot()
                    mod_id = data.get("moderator_id")
                    if not mod_id:
                        mod_id = user_id
                    if mod_id:
                        stats = await get_moderator_stats_data(bot, int(mod_id))
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type=WSEventType.STATS_PERSONAL,
                            data={"moderator_id": str(mod_id), "stats": stats},
                        ))
                except Exception as e:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to fetch personal stats: {str(e)}"},
                    ))

            elif action == "get_peak_hours":
                # Fetch peak hours for a moderator or server-wide
                try:
                    mod_id = data.get("moderator_id")
                    top_n = data.get("top_n", 24)
                    peak_hours = get_peak_hours_data(int(mod_id) if mod_id else None, top_n)
                    if mod_id:
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type=WSEventType.STATS_PEAK_HOURS,
                            data={"moderator_id": str(mod_id), "peak_hours": peak_hours},
                        ))
                    else:
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type=WSEventType.STATS_SERVER_PEAK_HOURS,
                            data={"peak_hours": peak_hours},
                        ))
                except Exception as e:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to fetch peak hours: {str(e)}"},
                    ))

            elif action == "get_activity":
                # Fetch activity chart data
                try:
                    days = data.get("days", 30)
                    activity = get_activity_data(days)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.STATS_ACTIVITY,
                        data={"activity": activity, "days": days},
                    ))
                except Exception as e:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to fetch activity: {str(e)}"},
                    ))

            elif action == "get_recent_actions":
                # Fetch recent actions for a moderator
                try:
                    mod_id = data.get("moderator_id")
                    if not mod_id:
                        mod_id = user_id
                    if mod_id:
                        limit = data.get("limit", 10)
                        actions = get_recent_actions_data(int(mod_id), limit)
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            type="stats.recent_actions",
                            data={"moderator_id": str(mod_id), "actions": actions},
                        ))
                except Exception as e:
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to fetch recent actions: {str(e)}"},
                    ))

    except WebSocketDisconnect:
        pass  # Normal disconnect, handled in finally
    except Exception as e:
        logger.warning("WebSocket Error", [
            ("Connection ID", connection_id[:8]),
            ("Error", f"{type(e).__name__}: {str(e)[:100]}"),
        ])
    finally:
        await ws_manager.disconnect(connection_id)
        logger.tree("WebSocket Disconnected", [
            ("Connection ID", connection_id[:8]),
            ("Remaining", str(len(ws_manager._connections))),
        ], emoji="🔌")


__all__ = ["router"]
