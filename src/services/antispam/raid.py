"""
AzabBot - Anti-Spam Raid Detection
==================================

Enhanced raid detection and handling.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import discord

from src.core.config import EmbedColors, NY_TZ
from src.core.logger import logger

from .constants import (
    RAID_ACCOUNT_AGE_HOURS,
    RAID_DEFAULT_AVATAR_WEIGHT,
    RAID_JOIN_LIMIT,
    RAID_SIMILAR_CREATION_WINDOW,
    RAID_SIMILAR_NAME_THRESHOLD,
    RAID_TIME_WINDOW,
)
from .models import JoinRecord

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config


class RaidDetectionMixin:
    """Mixin class providing raid detection functionality."""

    def _init_raid_detection(self) -> None:
        """Initialize raid detection structures."""
        self._recent_joins: Dict[int, List[JoinRecord]] = defaultdict(list)
        self._raid_detection_lock = asyncio.Lock()

    async def check_raid(self, member: discord.Member) -> Tuple[bool, Optional[str]]:
        """
        Check if a member join is part of a raid.

        Args:
            member: The member who joined.

        Returns:
            Tuple of (is_raid, raid_type)
        """
        if not member.guild:
            return False, None

        guild_id = member.guild.id
        now = datetime.now(NY_TZ)

        # Create join record
        account_created = member.created_at.replace(tzinfo=NY_TZ) if member.created_at else now
        has_default = member.avatar is None
        avatar_hash = str(member.avatar.key) if member.avatar else None

        record = JoinRecord(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            account_created=account_created,
            has_default_avatar=has_default,
            avatar_hash=avatar_hash,
            join_time=now,
        )

        # Use lock to prevent race conditions when modifying _recent_joins
        async with self._raid_detection_lock:
            self._recent_joins[guild_id].append(record)

            # Clean old joins
            cutoff = now - timedelta(seconds=RAID_TIME_WINDOW)
            self._recent_joins[guild_id] = [
                j for j in self._recent_joins[guild_id] if j.join_time > cutoff
            ]

            recent = list(self._recent_joins[guild_id])  # Copy for analysis outside lock

        # Basic raid detection: too many new accounts joining
        new_accounts = [
            j for j in recent
            if (now - j.account_created).total_seconds() < RAID_ACCOUNT_AGE_HOURS * 3600
        ]

        # Weight default avatars more heavily
        weighted_count = sum(
            RAID_DEFAULT_AVATAR_WEIGHT if j.has_default_avatar else 1
            for j in new_accounts
        )

        if weighted_count >= RAID_JOIN_LIMIT:
            return True, "new_accounts"

        # Enhanced: Check for similar usernames
        if len(recent) >= 3:
            similar_names = 0
            for i, j1 in enumerate(recent):
                for j2 in recent[i+1:]:
                    name_sim = SequenceMatcher(None, j1.username.lower(), j2.username.lower()).ratio()
                    if name_sim >= RAID_SIMILAR_NAME_THRESHOLD:
                        similar_names += 1

            if similar_names >= 3:
                return True, "similar_names"

        # Enhanced: Check for accounts created at similar times
        if len(new_accounts) >= 3:
            creation_times = sorted([j.account_created for j in new_accounts])
            for i in range(len(creation_times) - 2):
                time_diff = (creation_times[i+2] - creation_times[i]).total_seconds()
                if time_diff <= RAID_SIMILAR_CREATION_WINDOW:
                    return True, "similar_creation"

        # Enhanced: Check for same avatar hash
        if len(recent) >= 3:
            avatar_counts: Dict[str, int] = defaultdict(int)
            for j in recent:
                if j.avatar_hash:
                    avatar_counts[j.avatar_hash] += 1
            for count in avatar_counts.values():
                if count >= 3:
                    return True, "same_avatar"

        return False, None

    async def handle_raid(self, guild: discord.Guild, raid_type: str = "unknown") -> None:
        """Handle a detected raid by alerting mods."""
        bot: "AzabBot" = self.bot  # type: ignore
        config: "Config" = self.config  # type: ignore

        raid_descriptions = {
            "new_accounts": "Multiple new accounts joined rapidly",
            "similar_names": "Multiple accounts with similar usernames joined",
            "similar_creation": "Multiple accounts created at similar times joined",
            "same_avatar": "Multiple accounts with identical avatars joined",
            "unknown": "Suspicious join pattern detected",
        }

        logger.tree("RAID DETECTED", [
            ("Guild", f"{guild.name} ({guild.id})"),
            ("Type", raid_type),
            ("Action", "Alert sent"),
        ], emoji="🚨")

        if bot.logging_service and bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="🚨 Raid Detected",
                    description=raid_descriptions.get(raid_type, "Suspicious activity detected.") +
                                "\nConsider running `/lockdown`.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(name="Type", value=raid_type.replace("_", " ").title(), inline=True)
                embed.add_field(
                    name="Detected",
                    value=f"{RAID_JOIN_LIMIT}+ suspicious joins in {RAID_TIME_WINDOW}s",
                    inline=True,
                )

                await bot.logging_service._send_log(
                    bot.logging_service.LogCategory.ALERTS,
                    embed,
                )

                if config.owner_id:
                    thread = await bot.logging_service._get_or_create_thread(
                        bot.logging_service.LogCategory.ALERTS
                    )
                    if thread:
                        await thread.send(
                            f"<@{config.owner_id}> 🚨 **RAID DETECTED ({raid_type})!** "
                            f"Consider running `/lockdown`."
                        )
            except Exception as e:
                logger.debug(f"Failed to log raid: {e}")

        # Alert in mod channel if configured
        if config.alert_channel_id:
            try:
                alert_channel = bot.get_channel(config.alert_channel_id)
                if alert_channel:
                    embed = discord.Embed(
                        title="🚨 RAID ALERT",
                        description=raid_descriptions.get(raid_type, "Suspicious activity detected."),
                        color=EmbedColors.ERROR,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="Type", value=raid_type.replace("_", " ").title(), inline=True)
                    embed.add_field(name="Action", value="Consider `/lockdown`", inline=True)

                    await alert_channel.send("@everyone", embed=embed)
                    logger.tree("RAID ALERT SENT", [
                        ("Channel", f"#{alert_channel.name}"),
                        ("Type", raid_type),
                    ], emoji="🚨")
            except Exception as e:
                logger.warning("Raid Alert Failed", [
                    ("Channel ID", str(config.alert_channel_id)),
                    ("Error", str(e)[:50]),
                ])

    async def cleanup_raid_records(self, now: datetime) -> None:
        """Clean up old raid join records."""
        cutoff = now - timedelta(seconds=RAID_TIME_WINDOW * 2)
        async with self._raid_detection_lock:
            for guild_id in list(self._recent_joins.keys()):
                self._recent_joins[guild_id] = [
                    j for j in self._recent_joins[guild_id]
                    if j.join_time > cutoff
                ]
                if not self._recent_joins[guild_id]:
                    try:
                        del self._recent_joins[guild_id]
                    except KeyError:
                        pass
