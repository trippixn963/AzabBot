"""
AzabBot - Join Info Cleanup Task
================================

Delete old join info records for users who left the server.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Set

from src.core.logger import logger
from src.core.config import NY_TZ
from src.core.constants import LOG_TRUNCATE_SHORT, JOIN_INFO_RETENTION_DAYS
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class JoinInfoCleanupTask(MaintenanceTask):
    """
    Clean up old join info records for users who left.

    Removes user_join_info entries for users who are no longer
    in the guild and whose records are older than the retention period.
    """

    name = "Join Info Cleanup"

    async def should_run(self) -> bool:
        """Check if database is available."""
        return self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Delete old join info for users who left."""
        deleted = 0
        errors = 0

        try:
            cutoff = datetime.now(NY_TZ) - timedelta(days=JOIN_INFO_RETENTION_DAYS)
            cutoff_ts = cutoff.timestamp()

            # Get all current member IDs per guild
            guild_members: Dict[int, Set[int]] = {}
            for guild in self.bot.guilds:
                guild_members[guild.id] = {m.id for m in guild.members}

            # Get old join info records
            rows = self.bot.db.fetchall(
                """SELECT user_id, guild_id
                   FROM user_join_info
                   WHERE joined_at < ?""",
                (cutoff_ts,)
            )

            if not rows:
                return {"success": True, "deleted": 0}

            # Delete records for users not in guild
            for row in rows:
                user_id = row["user_id"]
                guild_id = row["guild_id"]

                # Check if user is still in this guild
                if guild_id in guild_members:
                    if user_id not in guild_members[guild_id]:
                        try:
                            self.bot.db.execute(
                                "DELETE FROM user_join_info WHERE user_id = ? AND guild_id = ?",
                                (user_id, guild_id)
                            )
                            deleted += 1
                        except Exception as e:
                            errors += 1
                            logger.debug("Join Info Delete Error", [("Error", str(e)[:50])])
                else:
                    # Guild not accessible, delete anyway
                    try:
                        self.bot.db.execute(
                            "DELETE FROM user_join_info WHERE user_id = ? AND guild_id = ?",
                            (user_id, guild_id)
                        )
                        deleted += 1
                    except Exception as e:
                        errors += 1

            if deleted > 0:
                logger.tree("Join Info Cleanup Complete", [
                    ("Records Deleted", str(deleted)),
                    ("Retention", f"{JOIN_INFO_RETENTION_DAYS} days"),
                ], emoji="🧹")

            return {
                "success": errors == 0,
                "deleted": deleted,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Join Info Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        deleted = result.get("deleted", 0)
        return f"{deleted} deleted" if deleted > 0 else "clean"


__all__ = ["JoinInfoCleanupTask"]
