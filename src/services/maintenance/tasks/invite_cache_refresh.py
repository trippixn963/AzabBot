"""
AzabBot - Invite Cache Refresh Task
===================================

Refresh the invite tracking cache for accurate invite attribution.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Any, Dict

import discord

from src.core.logger import logger
from src.core.constants import LOG_TRUNCATE_SHORT
from src.utils.discord_rate_limit import log_http_error
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class InviteCacheRefreshTask(MaintenanceTask):
    """
    Refresh the invite tracking cache.

    Re-fetches all guild invites to ensure the cache is accurate
    for tracking which invite was used when members join.
    """

    name = "Invite Cache"

    async def should_run(self) -> bool:
        """Check if invite cache exists."""
        return hasattr(self.bot, '_invite_cache')

    async def run(self) -> Dict[str, Any]:
        """Refresh invite cache for all guilds."""
        guilds_refreshed = 0
        total_invites = 0
        errors = 0

        try:
            for guild in self.bot.guilds:
                try:
                    invites = await guild.invites()
                    self.bot._invite_cache[guild.id] = {
                        invite.code: invite.uses for invite in invites
                    }
                    guilds_refreshed += 1
                    total_invites += len(invites)
                except discord.Forbidden:
                    # Bot doesn't have permission to view invites
                    pass
                except discord.HTTPException as e:
                    errors += 1
                    log_http_error(e, "Invite Cache Refresh", [("Guild", guild.name)])

            if guilds_refreshed > 0:
                logger.tree("Invite Cache Refreshed", [
                    ("Guilds", str(guilds_refreshed)),
                    ("Invites Cached", str(total_invites)),
                ], emoji="🔗")

            return {
                "success": True,
                "refreshed": guilds_refreshed,
                "invites": total_invites,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Invite Cache Refresh Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        invites = result.get("invites", 0)
        return f"{invites} cached"


__all__ = ["InviteCacheRefreshTask"]
