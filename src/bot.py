"""
Azab Discord Bot - Main Bot Class
================================

The core Discord bot class that handles all Discord API interactions,
command processing, and AI-powered responses for the Syria Discord server.

Features:
- Slash command handling (/activate, /deactivate)
- AI-powered message responses
- User message logging and analytics
- Muted user detection and special responses
- Modular command and handler architecture
- Family member privilege system
- Rate limiting for prisoners

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

import discord
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
import os
import json
from typing import Set, Optional, Dict, Any, List
from collections import deque

from src.core.logger import logger
from src.core.database import Database
from src.services.ai_service import AIService
from src.commands import ActivateCommand, DeactivateCommand, IgnoreCommand
from src.handlers import PrisonHandler, MuteHandler, PresenceHandler
from src.utils.error_handler import ErrorHandler
from src.utils.validators import Validators, ValidationError, InputSanitizer


class AzabBot(discord.Client):
    """
    Main Discord bot class for Azab.

    Handles all Discord API interactions including message processing,
    slash commands, user activity logging, and prisoner handling.

    Attributes:
        db: Database connection for message logging
        ai: AI service for generating responses
        is_active: Bot activation state
        tree: Discord slash command tree
        prison_handler: Handler for prisoner operations
        mute_handler: Handler for mute detection
        presence_handler: Handler for rich presence updates
    """

    def __init__(self) -> None:
        """Initialize the Azab Discord bot with all services and handlers."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)

        self.db: Database = Database()
        self.ai: AIService = AIService(os.getenv('OPENAI_API_KEY'))
        self.start_time: datetime = datetime.now()

        self.state_file: str = 'bot_state.json'
        self.ignored_users_file: str = 'ignored_users.json'
        self.is_active: bool = self._load_state()
        self.ignored_users: Set[int] = self._load_ignored_users()

        self.tree: app_commands.CommandTree = app_commands.CommandTree(self)

        prison_channels: Optional[str] = os.getenv('PRISON_CHANNEL_IDS', '')
        self.allowed_channels: Set[int] = {int(ch) for ch in prison_channels.split(',') if ch.strip()}
        if self.allowed_channels:
            logger.info(f"Bot restricted to channels: {self.allowed_channels}")

        logs_channel_id_str: Optional[str] = os.getenv('LOGS_CHANNEL_ID')
        prison_channel_id_str: Optional[str] = os.getenv('PRISON_CHANNEL_IDS')
        muted_role_id_str: Optional[str] = os.getenv('MUTED_ROLE_ID')
        general_channel_id_str: Optional[str] = os.getenv('GENERAL_CHANNEL_ID')
        developer_id_str: Optional[str] = os.getenv('DEVELOPER_ID')

        if not all([logs_channel_id_str, prison_channel_id_str, muted_role_id_str, general_channel_id_str, developer_id_str]):
            missing_vars = []
            if not logs_channel_id_str: missing_vars.append('LOGS_CHANNEL_ID')
            if not prison_channel_id_str: missing_vars.append('PRISON_CHANNEL_IDS')
            if not muted_role_id_str: missing_vars.append('MUTED_ROLE_ID')
            if not general_channel_id_str: missing_vars.append('GENERAL_CHANNEL_ID')
            if not developer_id_str: missing_vars.append('DEVELOPER_ID')

            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("   Please add these to your .env file")
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        self.logs_channel_id: int = int(logs_channel_id_str)
        self.prison_channel_id: int = int(prison_channel_id_str)
        self.muted_role_id: int = int(muted_role_id_str)
        self.general_channel_id: int = int(general_channel_id_str)
        self.developer_id: int = int(developer_id_str)

        uncle_id_str: Optional[str] = os.getenv('UNCLE_ID')
        self.uncle_id: Optional[int] = int(uncle_id_str) if uncle_id_str else None

        brother_id_str: Optional[str] = os.getenv('BROTHER_ID')
        self.brother_id: Optional[int] = int(brother_id_str) if brother_id_str else None

        polls_only_channel_id_str: Optional[str] = os.getenv('POLLS_ONLY_CHANNEL_ID')
        self.polls_only_channel_id: Optional[int] = int(polls_only_channel_id_str) if polls_only_channel_id_str else None

        self.prison_handler: PrisonHandler = PrisonHandler(self, self.ai)
        self.mute_handler: MuteHandler = MuteHandler(self.prison_handler)
        self.presence_handler: PresenceHandler = PresenceHandler(self)

        self.prisoner_cooldowns: Dict[int, datetime] = {}
        self.prisoner_message_buffer: Dict[int, List[str]] = {}
        self.PRISONER_COOLDOWN_SECONDS: int = int(os.getenv('PRISONER_COOLDOWN_SECONDS', '10'))

        self._register_commands()

    def _load_state(self) -> bool:
        """Load bot activation state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    state = data.get('is_active', True)
                    logger.info(f"Loaded bot state: {'ACTIVE' if state else 'INACTIVE'}")
                    return state
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot._load_state",
                critical=False,
                state_file=self.state_file
            )
        return True

    def _save_state(self) -> None:
        """Save bot activation state to file for persistence."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'is_active': self.is_active}, f)
            logger.info(f"Saved bot state: {'ACTIVE' if self.is_active else 'INACTIVE'}")
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot._save_state",
                critical=False,
                state=self.is_active
            )

    def _load_ignored_users(self) -> Set[int]:
        """Load ignored users list from file."""
        try:
            if os.path.exists(self.ignored_users_file):
                with open(self.ignored_users_file, 'r') as f:
                    data = json.load(f)
                    ignored_set = set(data.get('ignored_users', []))
                    if ignored_set:
                        logger.info(f"Loaded {len(ignored_set)} ignored user(s)")
                    return ignored_set
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot._load_ignored_users",
                critical=False,
                file=self.ignored_users_file
            )
        return set()

    def _save_ignored_users(self) -> None:
        """Save ignored users list to file for persistence."""
        try:
            with open(self.ignored_users_file, 'w') as f:
                json.dump({'ignored_users': list(self.ignored_users)}, f, indent=2)
            logger.info(f"Saved {len(self.ignored_users)} ignored user(s)")
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot._save_ignored_users",
                critical=False,
                count=len(self.ignored_users)
            )

    def is_user_muted(self, member: discord.Member) -> bool:
        """Check if a user has the muted role."""
        return self.mute_handler.is_user_muted(member, self.muted_role_id)

    def _register_commands(self) -> None:
        """Register all slash commands with Discord."""
        activate_cmd: ActivateCommand = ActivateCommand(self)
        deactivate_cmd: DeactivateCommand = DeactivateCommand(self)
        ignore_cmd: IgnoreCommand = IgnoreCommand(self)

        self.tree.add_command(activate_cmd.create_command())
        self.tree.add_command(deactivate_cmd.create_command())
        self.tree.add_command(ignore_cmd.create_command())

        logger.info("Commands registered: /activate, /deactivate, /ignore")

    async def setup_hook(self) -> None:
        """Discord.py setup hook - syncs all registered slash commands."""
        await self.tree.sync()
        logger.success(f"Synced {len(self.tree.get_commands())} commands")

    async def on_ready(self) -> None:
        """Discord bot ready event handler."""
        try:
            logger.tree("BOT ONLINE", [
                ("Name", self.user.name),
                ("ID", str(self.user.id)),
                ("Servers", str(len(self.guilds))),
                ("Status", "ACTIVE - Ragebaiting enabled")
            ], "🚀")

            await self.presence_handler.start_presence_loop()
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot.on_ready",
                critical=False,
                bot_name=self.user.name if self.user else "Unknown"
            )

    async def on_message(self, message: discord.Message) -> None:
        """Discord message event handler - Core message processing logic."""
        try:
            if message.channel.id == self.logs_channel_id and message.embeds:
                await self.mute_handler.process_mute_embed(message)
                return

            # Check for polls-only channel enforcement
            if self.polls_only_channel_id and message.channel.id == self.polls_only_channel_id:
                # If message is not a poll, delete it
                if message.poll is None:
                    await message.delete()
                    logger.info(f"🗑️ Deleted non-poll message in polls-only channel from {message.author} (ID: {message.author.id})")
                    return

            if message.author.bot:
                return

            # Check if user is ignored (skip all processing)
            if message.author.id in self.ignored_users:
                return

            if message.content:
                try:
                    validated_content = Validators.validate_message_content(message.content)
                except ValidationError as e:
                    logger.warning(f"Invalid message content from {message.author}: {e}")
                    return
            else:
                return

            is_developer: bool = message.author.id == self.developer_id
            is_uncle: bool = self.uncle_id and message.author.id == self.uncle_id
            is_brother: bool = self.brother_id and message.author.id == self.brother_id
            is_family: bool = is_developer or is_uncle or is_brother

            if not self.is_active and not is_family:
                return

            if not is_family and self.allowed_channels and message.channel.id not in self.allowed_channels:
                return

            if message.guild:
                sanitized = InputSanitizer.sanitize_user_input(
                    user_id=message.author.id,
                    username=str(message.author),
                    message=message.content,
                    channel_id=message.channel.id
                )

                if sanitized.get('user_id') and sanitized.get('channel_id'):
                    await self.db.log_message(
                        sanitized['user_id'],
                        sanitized.get('username', 'Unknown User'),
                        sanitized.get('message', '[Empty]'),
                        sanitized['channel_id'],
                        message.guild.id
                    )

                # Track last 10 messages per user for better AI context
                if message.author.id not in self.prison_handler.last_messages:
                    self.prison_handler.last_messages[message.author.id] = {
                        "messages": deque(maxlen=10),  # Auto-removes oldest when > 10
                        "channel_id": message.channel.id
                    }

                self.prison_handler.last_messages[message.author.id]["messages"].append(message.content)
                self.prison_handler.last_messages[message.author.id]["channel_id"] = message.channel.id

            is_muted: bool = self.is_user_muted(message.author)

            if is_developer or is_uncle or is_brother:
                should_respond = self.user.mentioned_in(message)

                if should_respond:
                    async with message.channel.typing():
                        if is_developer:
                            response: str = await self.ai.generate_developer_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "CREATOR INTERACTION"
                            log_icon = "👑"
                        elif is_uncle:
                            response: str = await self.ai.generate_uncle_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "UNCLE INTERACTION"
                            log_icon = "🎩"
                        else:
                            response: str = await self.ai.generate_brother_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "BROTHER INTERACTION"
                            log_icon = "🤝"

                        await message.reply(response)

                        logger.tree(log_title, [
                            ("Family", str(message.author)),
                            ("Message", message.content[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Response", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
                        ], log_icon)
                    return

            if self.ai.should_respond(message.content, self.user.mentioned_in(message), is_muted):
                if is_muted:
                    user_id = message.author.id
                    current_time = datetime.now()

                    if user_id in self.prisoner_cooldowns:
                        last_response_time = self.prisoner_cooldowns[user_id]
                        time_since_last = (current_time - last_response_time).total_seconds()

                        if time_since_last < self.PRISONER_COOLDOWN_SECONDS:
                            if user_id not in self.prisoner_message_buffer:
                                self.prisoner_message_buffer[user_id] = []
                            self.prisoner_message_buffer[user_id].append(message.content)

                            logger.info(f"Rate limited {message.author.name} - buffering message (total: {len(self.prisoner_message_buffer[user_id])})")
                            return

                    async with message.channel.typing():
                        mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or
                                      self.prison_handler.mute_reasons.get(message.author.name.lower()))

                        combined_context = message.content
                        if user_id in self.prisoner_message_buffer and self.prisoner_message_buffer[user_id]:
                            all_messages = self.prisoner_message_buffer[user_id] + [message.content]
                            combined_context = f"The user sent multiple messages: {' | '.join(all_messages)}"

                            self.prisoner_message_buffer[user_id] = []

                            logger.info(f"Processing {len(all_messages)} messages from {message.author.name}")

                        # Get message history for better AI context
                        message_history = []
                        trigger_msg = None
                        if message.author.id in self.prison_handler.last_messages:
                            messages_deque = self.prison_handler.last_messages[message.author.id].get("messages", deque())
                            message_history = list(messages_deque)  # Convert deque to list
                            if message_history:
                                trigger_msg = message_history[-1]  # Get most recent as trigger

                        mute_duration = await self.db.get_current_mute_duration(message.author.id)

                        response: str = await self.ai.generate_response(
                            combined_context,
                            message.author.display_name,
                            is_muted,
                            mute_reason,
                            trigger_msg,
                            user_id=message.author.id,
                            mute_duration_minutes=mute_duration,
                            message_history=message_history  # Pass full conversation history
                        )
                        await message.reply(response)

                        self.prisoner_cooldowns[user_id] = current_time

                        logger.tree("RAGEBAITED PRISONER", [
                            ("Target", str(message.author)),
                            ("Message", message.content[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Response", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Cooldown", f"{self.PRISONER_COOLDOWN_SECONDS}s")
                        ], "😈")
                else:
                    async with message.channel.typing():
                        mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or
                                      self.prison_handler.mute_reasons.get(message.author.name.lower()))

                        trigger_msg = None
                        if message.author.id in self.prison_handler.last_messages:
                            trigger_msg = self.prison_handler.last_messages[message.author.id].get("content")

                        response: str = await self.ai.generate_response(
                            message.content,
                            message.author.display_name,
                            is_muted,
                            mute_reason,
                            trigger_msg,
                            user_id=message.author.id,
                            mute_duration_minutes=0
                        )
                    await message.reply(response)
        except discord.errors.Forbidden:
            logger.warning(f"No permission to reply in #{message.channel.name}")
        except discord.errors.HTTPException as e:
            logger.error(f"Discord API error in on_message: {e}")
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot.on_message",
                critical=False,
                message=message
            )

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Discord member update event handler - monitors role changes for mute detection."""
        try:
            if not self.is_active:
                return

            had_muted_role: bool = any(role.id == self.muted_role_id for role in before.roles)
            has_muted_role: bool = any(role.id == self.muted_role_id for role in after.roles)

            if not had_muted_role and has_muted_role:
                logger.success(f"New prisoner detected: {after.name}")
                await self.prison_handler.handle_new_prisoner(after)

            elif had_muted_role and not has_muted_role:
                logger.success(f"Prisoner released: {after.name}")
                await self.prison_handler.handle_prisoner_release(after)

                if after.id in self.prisoner_cooldowns:
                    del self.prisoner_cooldowns[after.id]
                if after.id in self.prisoner_message_buffer:
                    del self.prisoner_message_buffer[after.id]
        except discord.errors.Forbidden:
            logger.warning(f"No permission to handle member update for {after.name}")
        except discord.errors.HTTPException as e:
            logger.error(f"Discord API error in on_member_update: {e}")
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot.on_member_update",
                critical=False,
                member=after,
                before_roles=[r.name for r in before.roles],
                after_roles=[r.name for r in after.roles]
            )
