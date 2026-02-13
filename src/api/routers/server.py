"""
AzabBot - Server Router
=======================

Server/guild information endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any

from fastapi import APIRouter, Depends

from src.core.config import get_config
from src.core.logger import logger
from src.api.dependencies import get_bot
from src.api.models.base import APIResponse
from src.api.models.auth import GuildInfo
from src.api.errors import APIError, ErrorCode


router = APIRouter(tags=["Server"])


@router.get("/guild-info", response_model=APIResponse[GuildInfo])
async def get_guild_info(
    bot: Any = Depends(get_bot),
) -> APIResponse[GuildInfo]:
    """
    Get mod server guild information.

    Returns guild name, icon, and member count.
    Used by frontend to display server branding.
    """
    config = get_config()

    if not config.mod_server_id:
        logger.error("Mod Server ID Not Configured", [])
        raise APIError(ErrorCode.SERVER_ERROR, message="Mod server not configured")

    guild = bot.get_guild(config.mod_server_id)
    if not guild:
        logger.warning("Mod Guild Not Found", [
            ("Guild ID", str(config.mod_server_id)),
        ])
        raise APIError(ErrorCode.SERVER_DISCORD_ERROR, message="Mod server not accessible")

    icon_url = str(guild.icon.url) if guild.icon else None

    return APIResponse(
        success=True,
        data=GuildInfo(
            id=guild.id,
            name=guild.name,
            icon=icon_url,
            member_count=guild.member_count,
        ),
    )


__all__ = ["router"]
