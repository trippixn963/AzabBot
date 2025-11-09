"""
Azab Discord Bot - Prison Handler
=================================

Handles prisoner welcome and release functionality for muted users.
Manages the prison channel interactions and general channel release messages.

Features:
- Welcome messages for newly muted users with reason context
- Release messages when users are unmuted
- Mute reason extraction from logs channel
- AI-powered contextual responses
- Prisoner statistics and history tracking
- Repeat offender detection and roasting
- Rich embeds with prisoner records
- Automatic database logging

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from collections import deque

from src.core.logger import logger
from src.services.ai_service import AIService
from src.utils import format_duration
from src.utils.error_handler import ErrorHandler


class PrisonHandler:
    """
    Manages prisoner (muted user) welcome and release operations.

    Handles:
    - Detecting when users get muted/unmuted
    - Sending welcome messages to prison channel
    - Sending release messages to general channel
    - Tracking mute reasons for contextual responses
    """

    def __init__(self, bot: Any, ai_service: AIService) -> None:
        """
        Initialize the prison handler.

        Args:
            bot: The Discord bot instance
            ai_service: AI service for generating responses
        """
        self.bot: Any = bot
        self.ai: AIService = ai_service
        self.mute_reasons: Dict[int, str] = {}
        # Store last 10 messages per user: {user_id: {"messages": deque([msg1, msg2, ...]), "channel_id": int}}
        self.last_messages: Dict[int, Dict[str, Any]] = {}

        # Start daily cleanup loop
        asyncio.create_task(self._daily_cleanup_loop())

    async def handle_new_prisoner(self, member: discord.Member) -> None:
        """
        Welcome a newly muted user to prison with savage ragebait.

        This is the main prisoner onboarding function. It executes a multi-step process:
        1. Extract mute reason from logs channel embeds
        2. Gather prisoner statistics (repeat offender data)
        3. Generate contextual AI roast based on their offense
        4. Create rich embed with prisoner info
        5. Send welcome message to prison channel
        6. Update presence to show new prisoner
        7. Log mute to database

        FIRST scans the logs channel for mute embeds to extract the mute reason,
        THEN generates a contextual AI response to mock the user about
        their specific offense.

        Args:
            member (discord.Member): The newly muted Discord member
        """
        try:
            logger.info(f"Handling new prisoner: {member.name} (ID: {member.id})")

            logs_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.logs_channel_id)
            prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.prison_channel_id)

            logger.info(f"Channels - Logs: {logs_channel}, Prison: {prison_channel}")

            if not logs_channel or not prison_channel:
                logger.error(f"Channels not found - logs: {self.bot.logs_channel_id}, prison: {self.bot.prison_channel_id}")
                return

            # Send mute notification to the channel where they got muted (or general chat as fallback)
            mute_channel_id: Optional[int] = None
            if member.id in self.last_messages:
                mute_channel_id = self.last_messages[member.id].get("channel_id")
                logger.info(f"Found last message channel for {member.name}: {mute_channel_id}")
            else:
                logger.warning(f"No last message found for {member.name} - defaulting to general chat")
                mute_channel_id = self.bot.general_channel_id

            if mute_channel_id:
                mute_channel: Optional[discord.TextChannel] = self.bot.get_channel(mute_channel_id)
                if not mute_channel:
                    logger.error(f"Could not find channel {mute_channel_id} to send mute notification")
                else:
                    logger.info(f"Sending mute notification to #{mute_channel.name} (ID: {mute_channel_id})")
                if mute_channel:
                    # Generate savage message about getting muted
                    mute_announcement: str = await self.ai.generate_response(
                        f"Someone just got muted and thrown in prison. Mock them briefly about getting muted. "
                        f"Be savage but concise - max {os.getenv('MAX_RESPONSE_LENGTH', '150')} characters. "
                        f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged.",
                        member.display_name,
                        False,
                        None
                    )

                    embed = discord.Embed(
                        title="⚠️ USER MUTED",
                        description=f"{member.mention} has been sent to prison.",
                        color=int(os.getenv('EMBED_COLOR_ERROR', '0xFF0000'), 16)
                    )

                    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

                    developer = await self.bot.fetch_user(self.bot.developer_id)
                    developer_avatar = developer.avatar.url if developer and developer.avatar else None
                    embed.set_footer(
                        text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}",
                        icon_url=developer_avatar
                    )

                    try:
                        await mute_channel.send(f"{member.mention} {mute_announcement}", embed=embed)
                        logger.info(f"Sent mute notification to #{mute_channel.name}")
                    except Exception as e:
                        logger.warning(f"Failed to send mute notification: {str(e)[:100]}")

            logger.info(f"Waiting for mute embed to appear in logs for {member.name}")
            await asyncio.sleep(int(os.getenv('MUTE_EMBED_WAIT_TIME', '5')))

            mute_reason: Optional[str] = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())

            prisoner_stats: Dict[str, Any] = await self.bot.db.get_prisoner_stats(member.id)

            if mute_reason:
                logger.info(f"Found stored mute reason for {member.name}: {mute_reason}")
            else:
                logger.info(f"Scanning logs channel for {member.name}'s mute reason...")

                messages_checked: int = 0
                async for message in logs_channel.history(limit=int(os.getenv('LOG_CHANNEL_SCAN_LIMIT', '50'))):
                    messages_checked += 1
                    if message.embeds:
                        await self.bot.mute_handler.process_mute_embed(message)

                        mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
                        if mute_reason:
                            logger.success(f"Found mute reason for {member.name}: {mute_reason}")
                            break

                logger.info(f"Scanned {messages_checked} messages in logs channel")

            if not mute_reason:
                logger.warning(f"Could not find mute reason for {member.name} - will use generic welcome")

            logger.info(f"Generating welcome message for {member.name} with reason: {mute_reason or 'None'}")

            welcome_prompt: str
            if mute_reason:
                welcome_prompt = (
                    f"Welcome a prisoner who just got thrown in jail for: '{mute_reason}'. "
                    f"Mock them brutally and specifically about why they got jailed. "
                )

                if prisoner_stats['total_mutes'] > 0:
                    total_time = format_duration(prisoner_stats['total_minutes'] or 0)
                    welcome_prompt += (
                        f"This is their {prisoner_stats['total_mutes'] + 1}th time in prison! "
                        f"They've spent {total_time} locked up before. "
                        f"Mock them for being a repeat offender who never learns. "
                    )

                welcome_prompt += (
                    f"Be savage and reference their specific offense. "
                    f"Tell them they're stuck in prison now with you, the prison bot. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                welcome_prompt = (
                    f"Welcome a prisoner to jail. "
                    f"Mock them for getting locked up. Be savage about being stuck in prison. "
                    f"Make jokes about them being trapped here with you. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )

            response: str = await self.ai.generate_response(
                welcome_prompt,
                member.display_name,
                True,
                mute_reason
            )

            embed = discord.Embed(
                title="🔒 NEW PRISONER ARRIVAL",
                description=f"{member.mention}\n",
                color=int(os.getenv('EMBED_COLOR_ERROR', '0xFF0000'), 16)
            )

            if mute_reason:
                embed.add_field(
                    name="Reason",
                    value=f"{mute_reason[:int(os.getenv('MUTE_REASON_MAX_LENGTH', '100'))]}",
                    inline=False
                )

            if prisoner_stats['total_mutes'] > 0:
                embed.add_field(
                    name="Prison Record",
                    value=f"Visit #{prisoner_stats['total_mutes'] + 1}",
                    inline=True
                )
                total_time = format_duration(prisoner_stats['total_minutes'] or 0)
                embed.add_field(
                    name="Total Time Served",
                    value=total_time,
                    inline=True
                )

            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

            developer = await self.bot.fetch_user(self.bot.developer_id)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(
                text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}",
                icon_url=developer_avatar
            )

            await prison_channel.send(f"{member.mention} {response}", embed=embed)

            total_mutes = prisoner_stats.get('total_mutes', 1) if prisoner_stats else 1
            asyncio.create_task(self.bot.presence_handler.show_prisoner_arrived(
                username=member.name,
                reason=mute_reason,
                mute_count=total_mutes
            ))

            # Get the most recent message (last in the deque) as trigger message
            trigger_message = None
            if member.id in self.last_messages and "messages" in self.last_messages[member.id]:
                messages = self.last_messages[member.id]["messages"]
                if messages:
                    trigger_message = messages[-1]  # Get the most recent message

            await self.bot.db.record_mute(
                user_id=member.id,
                username=member.name,
                reason=mute_reason or "Unknown",
                muted_by=None,
                trigger_message=trigger_message
            )

            logger.tree("NEW PRISONER WELCOMED", [
                ("Prisoner", str(member)),
                ("Reason", mute_reason[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))] if mute_reason else "Unknown"),
                ("Times Muted", str(prisoner_stats['total_mutes'] + 1)),
                ("Welcome", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            ], "⛓️")

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler.handle_new_prisoner",
                critical=False,
                member=member.name,
                member_id=member.id
            )

    async def handle_prisoner_release(self, member: discord.Member) -> None:
        """
        Send a message when a user gets unmuted (freed from prison).

        Sends a sarcastic/mocking message to the general chat when someone
        gets unmuted, making fun of their time in prison.

        Args:
            member (discord.Member): The newly unmuted Discord member
        """
        try:
            logger.info(f"Handling prisoner release: {member.name} (ID: {member.id})")

            general_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.general_channel_id)

            if not general_channel:
                logger.error(f"General channel not found: {self.bot.general_channel_id}")
                return

            mute_reason: Optional[str] = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())

            prisoner_stats: Dict[str, Any] = await self.bot.db.get_prisoner_stats(member.id)

            current_session_duration: int = await self.bot.db.get_current_mute_duration(member.id)

            release_prompt: str
            if mute_reason:
                release_prompt = (
                    f"Someone just got released from prison where they were locked up for: '{mute_reason}'. "
                    f"Mock them sarcastically about being freed. Make jokes about their time in jail. "
                    f"Act like they probably didn't learn their lesson. "
                    f"Be sarcastic about them being 'reformed'. Keep it under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                release_prompt = (
                    f"Someone just got released from prison. "
                    f"Mock them about finally being free. Be sarcastic about their jail time. "
                    f"Make jokes about them probably going back soon. Keep it under {os.getenv('RELEASE_PROMPT_WORD_LIMIT', '50')} words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )

            response: str = await self.ai.generate_response(
                release_prompt,
                member.display_name,
                False,
                mute_reason
            )

            embed = discord.Embed(
                title="🔓 PRISONER RELEASED",
                description=f"{member.mention}\n",
                color=int(os.getenv('EMBED_COLOR_RELEASE', '0x00FF00'), 16)
            )

            if mute_reason:
                embed.add_field(
                    name="Released From",
                    value=f"{mute_reason[:int(os.getenv('MUTE_REASON_MAX_LENGTH', '100'))]}",
                    inline=False
                )

            if prisoner_stats['total_mutes'] > 0:
                embed.add_field(
                    name="Total Visits",
                    value=str(prisoner_stats['total_mutes']),
                    inline=True
                )
                if current_session_duration > 0:
                    session_time = format_duration(current_session_duration)
                    embed.add_field(
                        name="Time Served",
                        value=session_time,
                        inline=True
                    )
                else:
                    embed.add_field(
                        name="Time Served",
                        value="< 1 minute",
                        inline=True
                    )

            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

            developer = await self.bot.fetch_user(self.bot.developer_id)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
            embed.set_footer(text=f"Developed By: {os.getenv('DEVELOPER_NAME', 'حَـــــنَّـــــا')}", icon_url=developer_avatar)

            await general_channel.send(f"{member.mention} {response}", embed=embed)

            asyncio.create_task(self.bot.presence_handler.show_prisoner_released(
                username=member.name,
                duration_minutes=current_session_duration
            ))

            await self.bot.db.record_unmute(
                user_id=member.id,
                unmuted_by=None
            )

            if member.id in self.mute_reasons:
                del self.mute_reasons[member.id]
            if member.name.lower() in self.mute_reasons:
                del self.mute_reasons[member.name.lower()]

            # Schedule message cleanup for 1 hour later (background task)
            asyncio.create_task(self._delayed_message_cleanup(member))

            logger.tree("PRISONER RELEASED", [
                ("Ex-Prisoner", str(member)),
                ("Previous Offense", mute_reason[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))] if mute_reason else "Unknown"),
                ("Total Times Muted", str(prisoner_stats['total_mutes'])),
                ("Cleanup Scheduled", "In 1 hour"),
                ("Release Message", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
            ], "🔓")

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler.handle_prisoner_release",
                critical=False,
                member=member.name,
                member_id=member.id
            )

    async def _delayed_message_cleanup(self, member: discord.Member) -> None:
        """
        Wait 1 hour before deleting prisoner messages.

        This gives people time to see the conversation history before cleanup.
        Runs as a background task so it doesn't block the release process.

        Args:
            member (discord.Member): The released prisoner whose messages will be deleted
        """
        try:
            # Wait 1 hour (3600 seconds) before cleaning up
            logger.info(f"⏰ Scheduled cleanup for {member.name} in 1 hour")
            await asyncio.sleep(3600)

            # Now delete the messages
            deleted_count: int = await self._delete_prisoner_messages(member)

            logger.tree("DELAYED CLEANUP COMPLETED", [
                ("Ex-Prisoner", str(member)),
                ("Messages Deleted", str(deleted_count)),
                ("Delay", "1 hour")
            ], "🧹")

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler._delayed_message_cleanup",
                critical=False,
                member=member.name,
                member_id=member.id
            )

    async def _delete_prisoner_messages(self, member: discord.Member) -> int:
        """
        Delete all messages from a prisoner in the prison channel.

        This method scans the prison channel's message history and deletes all
        messages sent by the specified member. Uses Discord's bulk delete feature
        for recent messages (< 14 days) and individual deletion for older messages.

        Args:
            member (discord.Member): The member whose messages should be deleted

        Returns:
            int: Number of messages successfully deleted
        """
        try:
            prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(self.bot.prison_channel_id)

            if not prison_channel:
                logger.error(f"Prison channel not found: {self.bot.prison_channel_id}")
                return 0

            logger.info(f"Deleting messages from {member.name} in prison channel...")

            messages_to_delete: List[discord.Message] = []
            old_messages: List[discord.Message] = []
            deleted_count: int = 0

            two_weeks_ago: datetime = datetime.now(timezone.utc) - timedelta(days=14)

            async for message in prison_channel.history(limit=int(os.getenv('PRISON_MESSAGE_SCAN_LIMIT', '500'))):
                # Delete prisoner's own messages
                if message.author.id == member.id:
                    if message.created_at > two_weeks_ago:
                        messages_to_delete.append(message)
                    else:
                        old_messages.append(message)
                # Also delete bot's replies to the prisoner
                elif message.author.id == self.bot.user.id and message.reference:
                    # Check if this is a reply to the prisoner
                    if message.reference.resolved and message.reference.resolved.author.id == member.id:
                        if message.created_at > two_weeks_ago:
                            messages_to_delete.append(message)
                        else:
                            old_messages.append(message)

            if messages_to_delete:
                try:
                    await prison_channel.delete_messages(messages_to_delete)
                    deleted_count += len(messages_to_delete)
                    logger.info(f"Bulk deleted {len(messages_to_delete)} recent messages from {member.name}")
                except discord.HTTPException as e:
                    logger.warning(f"Bulk delete failed, falling back to individual deletion: {str(e)[:100]}")
                    for message in messages_to_delete:
                        try:
                            await message.delete()
                            deleted_count += 1
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

            for message in old_messages:
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

            if deleted_count > 0:
                logger.success(f"Deleted {deleted_count} messages from {member.name} in prison channel")
            else:
                logger.info(f"No messages found from {member.name} in prison channel")

            return deleted_count

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler._delete_prisoner_messages",
                critical=False,
                member=member.name,
                member_id=member.id
            )
            return 0

    async def _daily_cleanup_loop(self) -> None:
        """
        Background task that clears the entire prison channel daily at midnight.

        This loop runs continuously and:
        1. Calculates time until next midnight (or configured cleanup time)
        2. Sleeps until that time
        3. Deletes ALL messages in the prison channel
        4. Logs the cleanup action
        5. Repeats daily

        Cleanup time can be configured via PRISON_CLEANUP_HOUR env variable (0-23).
        Default is midnight (0).
        """
        try:
            # Wait for bot to be fully ready before starting cleanup loop
            await self.bot.wait_until_ready()

            logger.info("🔄 Daily Prison Cleanup Loop Started")

            while not self.bot.is_closed():
                try:
                    # Get cleanup time from environment (default midnight)
                    cleanup_hour: int = int(os.getenv('PRISON_CLEANUP_HOUR', '0'))
                    timezone_offset: int = int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))
                    est: timezone = timezone(timedelta(hours=timezone_offset))

                    # Get current time in EST
                    now: datetime = datetime.now(est)

                    # Calculate next cleanup time (midnight or configured hour)
                    next_cleanup: datetime = now.replace(
                        hour=cleanup_hour,
                        minute=0,
                        second=0,
                        microsecond=0
                    )

                    # If cleanup time already passed today, schedule for tomorrow
                    if next_cleanup <= now:
                        next_cleanup += timedelta(days=1)

                    # Calculate sleep duration
                    sleep_seconds: float = (next_cleanup - now).total_seconds()

                    logger.info(
                        f"⏰ Next prison cleanup scheduled for: "
                        f"{next_cleanup.strftime('%Y-%m-%d %I:%M %p EST')} "
                        f"(in {sleep_seconds/3600:.1f} hours)"
                    )

                    # Sleep until cleanup time
                    await asyncio.sleep(sleep_seconds)

                    # Execute cleanup
                    prison_channel: Optional[discord.TextChannel] = self.bot.get_channel(
                        self.bot.prison_channel_id
                    )

                    if not prison_channel:
                        logger.error(
                            f"Prison channel not found: {self.bot.prison_channel_id} "
                            f"- skipping daily cleanup"
                        )
                        continue

                    logger.info(f"🧹 Starting daily prison cleanup in #{prison_channel.name}")

                    deleted_count: int = 0
                    messages_to_delete: List[discord.Message] = []
                    old_messages: List[discord.Message] = []

                    two_weeks_ago: datetime = datetime.now(timezone.utc) - timedelta(days=14)

                    # Collect all messages
                    async for message in prison_channel.history(
                        limit=int(os.getenv('DAILY_CLEANUP_SCAN_LIMIT', '1000'))
                    ):
                        if message.created_at > two_weeks_ago:
                            messages_to_delete.append(message)
                        else:
                            old_messages.append(message)

                    # Bulk delete recent messages
                    if messages_to_delete:
                        try:
                            # Discord allows max 100 messages per bulk delete
                            for i in range(0, len(messages_to_delete), 100):
                                batch = messages_to_delete[i:i + 100]
                                await prison_channel.delete_messages(batch)
                                deleted_count += len(batch)
                                await asyncio.sleep(1)  # Rate limit protection

                            logger.info(f"Bulk deleted {deleted_count} recent messages")
                        except discord.HTTPException as e:
                            logger.warning(
                                f"Bulk delete failed, falling back to individual deletion: "
                                f"{str(e)[:100]}"
                            )
                            for message in messages_to_delete:
                                try:
                                    await message.delete()
                                    deleted_count += 1
                                    await asyncio.sleep(0.5)
                                except Exception:
                                    pass

                    # Delete old messages individually
                    for message in old_messages:
                        try:
                            await message.delete()
                            deleted_count += 1
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

                    logger.tree("DAILY PRISON CLEANUP COMPLETED", [
                        ("Channel", f"#{prison_channel.name}"),
                        ("Messages Deleted", str(deleted_count)),
                        ("Time", datetime.now(est).strftime('%I:%M %p EST')),
                        ("Next Cleanup", next_cleanup.strftime('%I:%M %p EST'))
                    ], "🧹")

                except Exception as loop_error:
                    ErrorHandler.handle(
                        loop_error,
                        location="PrisonHandler._daily_cleanup_loop (iteration)",
                        critical=False
                    )
                    # Wait 1 hour before retrying on error
                    await asyncio.sleep(3600)

        except Exception as e:
            ErrorHandler.handle(
                e,
                location="PrisonHandler._daily_cleanup_loop (setup)",
                critical=True
            )
