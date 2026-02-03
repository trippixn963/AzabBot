"""
AzabBot - Gender Role Conflict Resolution Task
==============================================

Scans all members for gender role conflicts and resolves them.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import MAINTENANCE_RATE_LIMIT_DELAY, LOG_TRUNCATE_SHORT
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class GenderRoleTask(MaintenanceTask):
    """
    Resolve conflicts between verified and non-verified gender roles.

    If a member has both a verified and non-verified gender role,
    the non-verified role is automatically removed.
    """

    name = "Gender Roles"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if gender roles are configured."""
        return all([
            self.config.male_role_id,
            self.config.male_verified_role_id,
            self.config.female_role_id,
            self.config.female_verified_role_id,
        ])

    async def run(self) -> Dict[str, Any]:
        """Scan all members and resolve gender role conflicts."""
        conflicts_resolved = 0
        members_scanned = 0
        errors = 0

        # Define role conflict pairs: (verified_role_id, non_verified_role_id, name)
        conflict_pairs = [
            (self.config.male_verified_role_id, self.config.male_role_id, "Male"),
            (self.config.female_verified_role_id, self.config.female_role_id, "Female"),
        ]

        for guild in self.bot.guilds:
            # Verify roles exist in this guild
            roles_exist = True
            for verified_id, non_verified_id, _ in conflict_pairs:
                if not guild.get_role(verified_id) or not guild.get_role(non_verified_id):
                    roles_exist = False
                    break

            if not roles_exist:
                continue

            for member in guild.members:
                if member.bot:
                    continue

                members_scanned += 1
                member_role_ids = {r.id for r in member.roles}

                for verified_id, non_verified_id, gender_name in conflict_pairs:
                    has_verified = verified_id in member_role_ids
                    has_non_verified = non_verified_id in member_role_ids

                    if not (has_verified and has_non_verified):
                        continue

                    non_verified_role = guild.get_role(non_verified_id)
                    verified_role = guild.get_role(verified_id)

                    if not non_verified_role:
                        continue

                    try:
                        await member.remove_roles(
                            non_verified_role,
                            reason=f"Midnight maintenance: {gender_name} Verified role takes precedence"
                        )
                        conflicts_resolved += 1

                        logger.tree("MAINTENANCE: GENDER ROLE CONFLICT RESOLVED", [
                            ("User", f"{member.name} ({member.id})"),
                            ("Gender", gender_name),
                            ("Removed", non_verified_role.name),
                            ("Kept", verified_role.name if verified_role else "Unknown"),
                        ], emoji="🔧")

                        await self._log_resolution(member, gender_name, non_verified_role, verified_role)
                        await asyncio.sleep(MAINTENANCE_RATE_LIMIT_DELAY)

                    except discord.Forbidden:
                        errors += 1
                        logger.warning("Maintenance: Cannot Remove Gender Role", [
                            ("User", f"{member.name} ({member.id})"),
                            ("Role", non_verified_role.name),
                            ("Reason", "Missing permissions"),
                        ])
                    except discord.HTTPException as e:
                        errors += 1
                        logger.error("Maintenance: Gender Role Removal Failed", [
                            ("User", f"{member.name} ({member.id})"),
                            ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                        ])

        if conflicts_resolved > 0 or errors > 0:
            logger.tree("GENDER ROLE MAINTENANCE COMPLETE", [
                ("Members Scanned", str(members_scanned)),
                ("Conflicts Resolved", str(conflicts_resolved)),
                ("Errors", str(errors)),
            ], emoji="🔧")

        return {
            "success": True,
            "fixed": conflicts_resolved,
            "scanned": members_scanned,
            "errors": errors,
        }

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        return f"{result.get('fixed', 0)} fixed"

    async def _log_resolution(
        self,
        member: discord.Member,
        gender_name: str,
        removed_role: discord.Role,
        kept_role: Optional[discord.Role],
    ) -> None:
        """Log gender role resolution to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🔧 Maintenance: Gender Role Conflict Resolved",
                description="Conflict detected during midnight maintenance scan.",
                color=EmbedColors.LOG_INFO,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
            embed.add_field(name="Gender", value=gender_name, inline=True)
            embed.add_field(name="Removed Role", value=f"{removed_role.mention} (non-verified)", inline=True)
            embed.add_field(
                name="Kept Role",
                value=f"{kept_role.mention} (verified)" if kept_role else "Unknown",
                inline=True,
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.AUTOMOD,
                embed,
                user_id=member.id,
            )
        except Exception as e:
            logger.debug(f"Failed to log gender resolution: {e}")


__all__ = ["GenderRoleTask"]
