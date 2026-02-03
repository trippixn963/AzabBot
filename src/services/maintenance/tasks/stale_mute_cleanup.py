"""
AzabBot - Stale Mute Cleanup Task
=================================

Remove mute records for users who are no longer in the server.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import LOG_TRUNCATE_SHORT, STALE_MUTE_RETENTION_DAYS
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class StaleMuteCleanupTask(MaintenanceTask):
    """
    Clean up mute records for users who left the server.

    Removes active_mutes entries for users no longer in the guild,
    and cleans old mute_history records beyond retention period.
    """

    name = "Stale Mute Cleanup"

    async def should_run(self) -> bool:
        """Check if database is available."""
        return self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Clean up stale mute records."""
        cleaned_active = 0
        cleaned_history = 0
        errors = 0

        try:
            # Clean up active_mutes for users not in their guild
            try:
                rows = self.bot.db.fetchall(
                    "SELECT user_id, guild_id FROM active_mutes"
                )
                for row in rows or []:
                    user_id = row["user_id"]
                    guild_id = row["guild_id"]

                    # Check if user is in this specific guild
                    guild = self.bot.get_guild(guild_id)
                    if guild and not guild.get_member(user_id):
                        # User not in guild, remove active mute
                        self.bot.db.execute(
                            "DELETE FROM active_mutes WHERE user_id = ? AND guild_id = ?",
                            (user_id, guild_id)
                        )
                        cleaned_active += 1
            except Exception as e:
                errors += 1
                logger.error("Active Mute Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # Clean old mute_history records for users who left long ago
            try:
                cutoff = datetime.now(NY_TZ) - timedelta(days=STALE_MUTE_RETENTION_DAYS)
                cutoff_ts = cutoff.timestamp()

                # Delete old history for users not currently in any guild
                result = self.bot.db.execute(
                    """DELETE FROM mute_history
                       WHERE timestamp < ?
                       AND user_id NOT IN (
                           SELECT DISTINCT user_id FROM active_mutes
                       )""",
                    (cutoff_ts,)
                )
                if result:
                    cleaned_history = result.rowcount
            except Exception as e:
                errors += 1
                logger.error("Mute History Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            if cleaned_active > 0 or cleaned_history > 0:
                logger.tree("Stale Mute Cleanup Complete", [
                    ("Active Mutes Removed", str(cleaned_active)),
                    ("History Records Removed", str(cleaned_history)),
                ], emoji="🧹")

            return {
                "success": errors == 0,
                "cleaned": cleaned_active + cleaned_history,
                "active_removed": cleaned_active,
                "history_removed": cleaned_history,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Stale Mute Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        cleaned = result.get("cleaned", 0)
        return f"{cleaned} cleaned" if cleaned > 0 else "clean"


__all__ = ["StaleMuteCleanupTask"]
