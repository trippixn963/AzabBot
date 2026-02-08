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
from src.api.models.base import WSMessage, WSEventType

# Timeout for receiving messages (seconds)
RECEIVE_TIMEOUT = 60


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
                        event=WSEventType.HEARTBEAT,
                        data={},
                    ))
                    continue
                except Exception:
                    break  # Connection dead

            # Handle client actions
            action = data.get("action")

            if action == "subscribe":
                channel = data.get("channel")
                if channel:
                    await ws_manager.subscribe(connection_id, channel)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        event=WSEventType.SUBSCRIBED,
                        data={"channel": channel},
                    ))

            elif action == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    await ws_manager.unsubscribe(connection_id, channel)
                    await ws_manager._send_to_connection(connection_id, WSMessage(
                        event=WSEventType.UNSUBSCRIBED,
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
                            event=WSEventType.AUTHENTICATED,
                            data={"user_id": payload.sub},
                        ))
                    else:
                        await ws_manager._send_to_connection(connection_id, WSMessage(
                            event=WSEventType.ERROR,
                            data={"message": "Invalid token"},
                        ))

            elif action == "ping":
                # Client ping - respond with pong
                await ws_manager._send_to_connection(connection_id, WSMessage(
                    event=WSEventType.PONG,
                    data={},
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
