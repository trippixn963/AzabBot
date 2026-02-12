"""
AzabBot - Ban Sync Task
=======================

Synchronize bans from Discord to the database cache.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.core.constants import LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class BanSyncTask(MaintenanceTask):
    """
    Synchronize bans from Discord to database.

    This ensures the ban_history table stays in sync with Discord's
    actual ban list. Useful for:
    - Catching bans made outside the bot
    - Recovering from missed events
    - Initial population of ban data

    The /api/azab/bans endpoint relies on this cached data for
    fast queries without hitting Discord's API.
    """

    name = "Ban Sync"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if logging guild is configured and database available."""
        return bool(self.config.main_guild_id) and self.bot.db is not None

    async def run(self) -> Dict[str, Any]:
        """Sync bans from Discord to database."""
        synced: int = 0
        already_tracked: int = 0
        snapshots_created: int = 0
        unbans_detected: int = 0
        errors: int = 0

        guild_id: int = self.config.main_guild_id

        guild: Optional[discord.Guild] = self.bot.get_guild(guild_id)
        if not guild:
            logger.warning("Ban Sync Skipped", [
                ("Reason", "Guild not accessible"),
                ("Guild ID", str(guild_id)),
            ])
            return {"success": False, "error": "Guild not accessible"}

        try:
            db = self.bot.db
            banned_in_db: Set[int] = set()
            actually_banned: Set[int] = set()

            # =================================================================
            # Get current ban state from database
            # =================================================================
            try:
                db_bans = db.fetchall(
                    """SELECT DISTINCT user_id FROM ban_history bh
                       WHERE guild_id = ?
                       AND bh.id = (
                           SELECT MAX(bh2.id) FROM ban_history bh2
                           WHERE bh2.user_id = bh.user_id AND bh2.guild_id = bh.guild_id
                       )
                       AND action = 'ban'""",
                    (guild_id,)
                )
                for row in db_bans:
                    banned_in_db.add(row["user_id"])

                logger.debug("Ban Sync Starting", [
                    ("Guild", guild.name),
                    ("Tracked In DB", str(len(banned_in_db))),
                ])

            except Exception as e:
                errors += 1
                logger.error("Ban Sync DB Query Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Iterate through Discord bans
            # =================================================================
            try:
                async for ban_entry in guild.bans(limit=None):
                    user: discord.User = ban_entry.user
                    reason: Optional[str] = ban_entry.reason
                    actually_banned.add(user.id)

                    # Check if we already have a ban record for this user
                    try:
                        existing = db.fetchone(
                            """SELECT id, action FROM ban_history
                               WHERE user_id = ? AND guild_id = ?
                               ORDER BY timestamp DESC LIMIT 1""",
                            (user.id, guild_id)
                        )

                        if existing and existing["action"] == "ban":
                            already_tracked += 1
                            continue

                        # Either no record or last action was unban - add ban record
                        db.execute(
                            """INSERT INTO ban_history
                               (user_id, guild_id, moderator_id, action, reason, timestamp)
                               VALUES (?, ?, ?, 'ban', ?, ?)""",
                            (user.id, guild_id, self.bot.user.id, reason, time.time())
                        )
                        synced += 1

                        logger.debug("Ban Synced", [
                            ("User", f"{user.name} ({user.id})"),
                            ("Reason", (reason or "None")[:LOG_TRUNCATE_SHORT]),
                        ])

                        # Create user snapshot if we don't have one
                        try:
                            snapshot_exists = db.fetchone(
                                "SELECT 1 FROM user_snapshots WHERE user_id = ? AND guild_id = ?",
                                (user.id, guild_id)
                            )

                            if not snapshot_exists:
                                avatar_url: Optional[str] = (
                                    str(user.display_avatar.url) if user.display_avatar else None
                                )
                                db.execute(
                                    """INSERT INTO user_snapshots
                                       (user_id, guild_id, username, display_name, avatar_url,
                                        snapshot_reason, created_at, updated_at)
                                       VALUES (?, ?, ?, ?, ?, 'ban_sync', ?, ?)""",
                                    (user.id, guild_id, user.name, user.display_name,
                                     avatar_url, time.time(), time.time())
                                )
                                snapshots_created += 1
                        except Exception:
                            pass  # Snapshot is optional

                    except Exception as e:
                        errors += 1
                        logger.debug("Ban Sync Insert Error", [
                            ("User ID", str(user.id)),
                            ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                        ])

            except discord.HTTPException as e:
                errors += 1
                logger.error("Ban Sync Discord API Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Detect unbans (users in DB as banned but not on Discord)
            # =================================================================
            try:
                unbanned_users: Set[int] = banned_in_db - actually_banned

                for user_id in unbanned_users:
                    try:
                        last_action = db.fetchone(
                            """SELECT action FROM ban_history
                               WHERE user_id = ? AND guild_id = ?
                               ORDER BY timestamp DESC LIMIT 1""",
                            (user_id, guild_id)
                        )

                        if last_action and last_action["action"] == "ban":
                            db.execute(
                                """INSERT INTO ban_history
                                   (user_id, guild_id, moderator_id, action, reason, timestamp)
                                   VALUES (?, ?, ?, 'unban', 'Detected during sync', ?)""",
                                (user_id, guild_id, self.bot.user.id, time.time())
                            )
                            unbans_detected += 1

                            logger.debug("Unban Detected", [
                                ("User ID", str(user_id)),
                                ("Note", "Was banned in DB but not on Discord"),
                            ])

                    except Exception as e:
                        errors += 1
                        logger.debug("Unban Sync Error", [
                            ("User ID", str(user_id)),
                            ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                        ])

            except Exception as e:
                errors += 1
                logger.error("Unban Detection Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Log results
            # =================================================================
            total_on_discord: int = len(actually_banned)

            if synced > 0 or unbans_detected > 0:
                logger.tree("Ban Sync Complete", [
                    ("Discord Bans", str(total_on_discord)),
                    ("Already Tracked", str(already_tracked)),
                    ("New Bans Synced", str(synced)),
                    ("Unbans Detected", str(unbans_detected)),
                    ("Snapshots Created", str(snapshots_created)),
                    ("Errors", str(errors)),
                ], emoji="🔨")
            else:
                logger.debug("Ban Sync Complete", [
                    ("Discord Bans", str(total_on_discord)),
                    ("Result", "All in sync"),
                ])

            return {
                "success": errors == 0,
                "discord_bans": total_on_discord,
                "already_tracked": already_tracked,
                "synced": synced,
                "unbans_detected": unbans_detected,
                "snapshots": snapshots_created,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Ban Sync Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        if not result.get("success"):
            return "failed"

        synced: int = result.get("synced", 0)
        unbans: int = result.get("unbans_detected", 0)
        total: int = result.get("discord_bans", 0)

        if synced > 0 or unbans > 0:
            parts: List[str] = []
            if synced > 0:
                parts.append(f"{synced} synced")
            if unbans > 0:
                parts.append(f"{unbans} unbans")
            return ", ".join(parts)

        return f"{total} tracked"


__all__ = ["BanSyncTask"]
