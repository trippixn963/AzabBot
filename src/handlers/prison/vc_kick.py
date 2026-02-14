"""
AzabBot - Prisoner VC Kick Handler
==================================

Progressive timeout system for prisoners joining voice channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from datetime import datetime, timedelta
from typing import Dict, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, NY_TZ, EmbedColors
from src.core.constants import CASE_LOG_TIMEOUT
from src.utils.async_utils import create_safe_task
from src.utils.dm_helpers import send_moderation_dm
from src.api.services.event_logger import event_logger

if TYPE_CHECKING:
    from src.bot import AzabBot


async def handle_vc_kick(
    bot: "AzabBot",
    member: discord.Member,
    vc_kick_counts: Dict[int, int],
    state_lock: asyncio.Lock,
) -> None:
    """
    Handle VC kick with progressive timeout.

    DESIGN: Escalating punishment:
    - 1st offense: Warning only
    - 2nd offense: 5 minute timeout
    - 3rd+ offense: 30 minute timeout

    Args:
        bot: Bot instance.
        member: Member to kick from VC.
        vc_kick_counts: Dict tracking kick counts per user.
        state_lock: Lock for thread-safe access to vc_kick_counts.
    """
    if not member.voice or not member.voice.channel:
        return

    config = get_config()
    vc_name = member.voice.channel.name

    logger.tree("Prison Handler: VC Kick Called", [
        ("Member", f"{member.name} ({member.id})"),
        ("VC Channel", vc_name),
        ("Current Kick Count", str(vc_kick_counts.get(member.id, 0))),
    ], emoji="📝")

    try:
        await member.move_to(None)

        # Track kick count (with lock for thread-safety)
        async with state_lock:
            vc_kick_counts[member.id] = vc_kick_counts.get(member.id, 0) + 1
            kick_count = vc_kick_counts[member.id]

        # Determine timeout duration
        timeout_minutes = 0
        if kick_count == 2:
            timeout_minutes = 5
        elif kick_count >= 3:
            timeout_minutes = 30

        # Apply timeout if needed
        if timeout_minutes > 0:
            try:
                await member.timeout(
                    timedelta(minutes=timeout_minutes),
                    reason=f"Prisoner VC violation #{kick_count}"
                )

                # Record timeout to database
                until_ts = (datetime.now(NY_TZ) + timedelta(minutes=timeout_minutes)).timestamp()
                bot.db.add_timeout(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    moderator_id=bot.user.id,
                    reason=f"Prisoner VC violation #{kick_count} (joined #{vc_name})",
                    duration_seconds=timeout_minutes * 60,
                    until_timestamp=until_ts,
                )

                # Log to permanent audit log
                bot.db.log_moderation_action(
                    user_id=member.id,
                    guild_id=member.guild.id,
                    moderator_id=bot.user.id,
                    action_type="timeout",
                    action_source="auto_vc",
                    reason=f"Prisoner VC violation #{kick_count}",
                    duration_seconds=timeout_minutes * 60,
                    details={"vc_channel": vc_name, "kick_count": kick_count},
                )

                logger.tree("Timeout Applied", [
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Duration", f"{timeout_minutes}min"),
                    ("Offense #", str(kick_count)),
                ], emoji="⏱️")

                # Log to dashboard events
                event_logger.log_timeout(
                    guild=member.guild,
                    target=member,
                    moderator=None,
                    reason=f"Prisoner VC violation #{kick_count} (joined #{vc_name})",
                    duration_seconds=timeout_minutes * 60,
                )

                # Create case for the timeout
                if bot.case_log_service and member.guild:
                    try:
                        bot_member = member.guild.get_member(bot.user.id)
                        if bot_member:
                            await asyncio.wait_for(
                                bot.case_log_service.log_mute(
                                    user=member,
                                    moderator=bot_member,
                                    duration=f"{timeout_minutes} minute(s)",
                                    reason=f"Auto-timeout: Prisoner VC violation #{kick_count} (joined #{vc_name})",
                                    is_extension=False,
                                    evidence=None,
                                ),
                                timeout=CASE_LOG_TIMEOUT,
                            )
                    except asyncio.TimeoutError:
                        logger.warning("Case Log Timeout", [
                            ("Action", "Prisoner VC Violation"),
                            ("User", str(member.id)),
                        ])
                    except Exception as e:
                        logger.error("Case Log Failed", [
                            ("Action", "Prisoner VC Violation"),
                            ("User", str(member.id)),
                            ("Error", str(e)[:100]),
                        ])

                # Fire-and-forget DM (no appeal button)
                create_safe_task(send_moderation_dm(
                    user=member,
                    title="You have been timed out",
                    color=EmbedColors.ERROR,
                    guild=member.guild,
                    moderator=None,
                    reason=f"VC violation #{kick_count} - Prisoners cannot join voice channels",
                    fields=[("Duration", f"`{timeout_minutes} minutes`", True)],
                    context="Prisoner VC Violation DM",
                ))
            except discord.Forbidden:
                pass

        # Send VC kick message
        prison_channel = None
        if config.prison_channel_ids:
            prison_channel = bot.get_channel(
                next(iter(config.prison_channel_ids))
            )

        if prison_channel:
            if kick_count == 1:
                msg = f"{member.mention} Got kicked from **#{vc_name}**. No voice privileges. This is your warning."
            elif kick_count == 2:
                msg = f"{member.mention} Kicked from **#{vc_name}** AGAIN. **5 minute timeout.**"
            else:
                msg = f"{member.mention} Kicked from **#{vc_name}**. Offense #{kick_count}. **30 minute timeout.**"

            await prison_channel.send(msg)

        logger.tree("VC Kick", [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("Channel", f"#{vc_name}"),
            ("Offense #", str(kick_count)),
            ("Timeout", f"{timeout_minutes}min" if timeout_minutes else "None"),
        ], emoji="🔇")

    except discord.Forbidden:
        logger.warning("VC Kick Failed (Permissions)", [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("VC", vc_name),
        ])


__all__ = ["handle_vc_kick"]
