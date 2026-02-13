"""
AzabBot - Server Info Router
============================

Server information endpoint.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any

from fastapi import APIRouter, Depends

from src.core.logger import logger
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.stats import ServerInfo
from src.api.models.auth import TokenPayload


router = APIRouter(tags=["Statistics"])


@router.get("/server", response_model=APIResponse[ServerInfo])
async def get_server_info(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[ServerInfo]:
    """
    Get Discord server information.
    """
    guild = None
    if bot and hasattr(bot, 'config') and bot.config.main_guild_id:
        guild = bot.get_guild(bot.config.main_guild_id)

    if not guild:
        logger.warning("Server Info Failed", [
            ("User", str(payload.sub)),
            ("Reason", "Guild not found"),
        ])
        return APIResponse(
            success=False,
            message="Guild not found",
            data=ServerInfo(guild_id=0, name="Unknown"),
        )

    # Count channel types
    text_channels = sum(1 for c in guild.channels if hasattr(c, 'send'))
    voice_channels = sum(1 for c in guild.channels if hasattr(c, 'connect'))

    info = ServerInfo(
        guild_id=guild.id,
        name=guild.name,
        icon_url=str(guild.icon.url) if guild.icon else None,
        member_count=guild.member_count,
        online_count=sum(1 for m in guild.members if m.status.value != "offline"),
        bot_latency_ms=int(bot.latency * 1000),
        created_at=guild.created_at,
        total_channels=len(guild.channels),
        text_channels=text_channels,
        voice_channels=voice_channels,
        total_roles=len(guild.roles),
        mod_role_id=bot.config.moderation_role_id if hasattr(bot, 'config') else None,
        muted_role_id=bot.config.muted_role_id if hasattr(bot, 'config') else None,
    )

    logger.debug("Server Info Fetched", [
        ("User", str(payload.sub)),
        ("Guild", guild.name),
        ("Members", str(guild.member_count)),
        ("Latency", f"{int(bot.latency * 1000)}ms"),
    ])

    return APIResponse(success=True, data=info)


__all__ = ["router"]
