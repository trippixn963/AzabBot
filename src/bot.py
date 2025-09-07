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

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from datetime import datetime, timedelta
import asyncio
import os
import json
from typing import Set, Optional, Dict, Any, List

from src.core.logger import logger
from src.core.database import Database
from src.services.ai_service import AIService
from src.commands import ActivateCommand, DeactivateCommand, CreditsCommand
from src.handlers import PrisonHandler, MuteHandler, PresenceHandler


class AzabBot(discord.Client):
    """
    Main Discord bot class for Azab.
    
    Handles all Discord API interactions including:
    - Message processing and AI responses
    - Slash command registration and execution
    - User activity logging to database
    - Bot activation/deactivation states
    - Delegating prisoner handling to specialized handlers
    
    Attributes:
        db (Database): Database connection for message logging
        ai (AIService): AI service for generating responses
        is_active (bool): Bot activation state (starts as True)
        tree (app_commands.CommandTree): Discord slash command tree
        prison_handler (PrisonHandler): Handler for prisoner operations
        mute_handler (MuteHandler): Handler for mute detection
        presence_handler (PresenceHandler): Handler for rich presence updates
    """
    
    def __init__(self) -> None:
        """
        Initialize the Azab Discord bot.
        
        Sets up Discord intents, initializes services (database, AI),
        registers slash commands, and initializes handlers.
        Bot starts in active state by default.
        """
        # Configure Discord intents for required permissions
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read message content
        intents.members = True          # Required for member information
        super().__init__(intents=intents)
        
        # Initialize core services
        self.db: Database = Database()                                    # Message logging database
        self.ai: AIService = AIService(os.getenv('OPENAI_API_KEY'))       # AI response generation
        self.start_time: datetime = datetime.now()                        # Track bot start time for uptime
        
        # Load activation state from file (persistent across restarts)
        self.state_file: str = 'bot_state.json'
        self.is_active: bool = self._load_state()                     # Load saved state or default to True
        
        self.tree: app_commands.CommandTree = app_commands.CommandTree(self)             # Discord slash command tree
        
        # Load channel IDs from environment
        prison_channels: Optional[str] = os.getenv('PRISON_CHANNEL_IDS', '')
        self.allowed_channels: Set[int] = {int(ch) for ch in prison_channels.split(',') if ch.strip()}
        if self.allowed_channels:
            logger.info(f"Bot restricted to channels: {self.allowed_channels}")
        
        # Load channel and role IDs for mute detection
        # These must be set in .env file - no hardcoded defaults
        logs_channel_id_str: Optional[str] = os.getenv('LOGS_CHANNEL_ID')
        prison_channel_id_str: Optional[str] = os.getenv('PRISON_CHANNEL_IDS')
        muted_role_id_str: Optional[str] = os.getenv('MUTED_ROLE_ID')
        general_channel_id_str: Optional[str] = os.getenv('GENERAL_CHANNEL_ID')
        developer_id_str: Optional[str] = os.getenv('DEVELOPER_ID')
        
        # Validate required environment variables
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
        
        # Initialize handlers
        self.prison_handler: PrisonHandler = PrisonHandler(self, self.ai)
        self.mute_handler: MuteHandler = MuteHandler(self.prison_handler)
        self.presence_handler: PresenceHandler = PresenceHandler(self)
        
        # Rate limiting for prisoners (10 seconds per user)
        self.prisoner_cooldowns: Dict[int, datetime] = {}  # {user_id: last_response_time}
        self.prisoner_message_buffer: Dict[int, List[str]] = {}  # {user_id: [messages]}
        self.PRISONER_COOLDOWN_SECONDS: int = 10
        
        # Register all slash commands
        self._register_commands()
    
    def _load_state(self) -> bool:
        """
        Load bot activation state from file.
        
        Returns:
            bool: Saved activation state, or True if no saved state exists
        """
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    state = data.get('is_active', True)
                    logger.info(f"Loaded bot state: {'ACTIVE' if state else 'INACTIVE'}")
                    return state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
        return True  # Default to active
    
    def _save_state(self) -> None:
        """Save bot activation state to file for persistence."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'is_active': self.is_active}, f)
            logger.info(f"Saved bot state: {'ACTIVE' if self.is_active else 'INACTIVE'}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def is_user_muted(self, member: discord.Member) -> bool:
        """
        Check if a user has the muted role.
        
        Args:
            member: Discord member to check
            
        Returns:
            bool: True if user has muted role, False otherwise
        """
        return self.mute_handler.is_user_muted(member, self.muted_role_id)
    
    def _register_commands(self) -> None:
        """
        Register all slash commands with Discord.
        
        Creates command instances from separate files and adds them
        to the Discord command tree for slash command functionality.
        """
        # Create command instances from modular command files
        activate_cmd: ActivateCommand = ActivateCommand(self)      # Bot activation command
        deactivate_cmd: DeactivateCommand = DeactivateCommand(self)  # Bot deactivation command
        credits_cmd: CreditsCommand = CreditsCommand(self)       # Credits and info command
        
        # Add commands to Discord's command tree
        self.tree.add_command(activate_cmd.create_command())
        self.tree.add_command(deactivate_cmd.create_command())
        self.tree.add_command(credits_cmd.create_command())
        
        logger.info("Commands registered: /activate, /deactivate, /credits")
    
    async def setup_hook(self) -> None:
        """
        Discord.py setup hook - called before bot connects.
        
        Syncs all registered slash commands with Discord's API.
        This ensures commands are available in all connected servers.
        """
        await self.tree.sync()
        logger.success(f"Synced {len(self.tree.get_commands())} commands")
    
    async def on_ready(self) -> None:
        """
        Discord bot ready event handler.
        
        Called when bot successfully connects to Discord Gateway.
        Displays bot status information and confirms connection.
        Starts the presence update loop.
        """
        logger.tree("BOT ONLINE", [
            ("Name", self.user.name),
            ("ID", str(self.user.id)),
            ("Servers", str(len(self.guilds))),
            ("Status", "ACTIVE - Ragebaiting enabled")
        ], "🚀")
        
        # Start presence updates
        await self.presence_handler.start_presence_loop()
    
    async def on_message(self, message: discord.Message) -> None:
        """
        Discord message event handler.
        
        Processes all incoming messages when bot is active:
        1. Logs message to database for analytics
        2. Checks if user is muted/timed out
        3. Generates AI response if conditions are met
        4. Special handling for muted users (ragebait responses)
        
        Args:
            message (discord.Message): The Discord message object
        """
        # Check if this is a mute embed in logs channel
        if message.channel.id == self.logs_channel_id and message.embeds:
            await self.mute_handler.process_mute_embed(message)
            return
        
        # Ignore messages from bots
        if message.author.bot:
            return
        
        # Check if message is from the developer/creator - bypass all restrictions
        is_developer: bool = message.author.id == self.developer_id
        
        # If bot is inactive and user is not developer, ignore
        if not self.is_active and not is_developer:
            return
        
        # Check if message is in allowed channel (if restrictions are set)
        # Developer bypasses channel restrictions
        if not is_developer and self.allowed_channels and message.channel.id not in self.allowed_channels:
            return
        
        # Log message to database for analytics (guild messages only)
        if message.guild:
            await self.db.log_message(
                message.author.id,
                str(message.author),
                message.content,
                message.channel.id,
                message.guild.id
            )
        
        # Check if user is currently muted (by role)
        is_muted: bool = self.is_user_muted(message.author)
        
        # Check if message is from the developer/creator
        if is_developer and self.user.mentioned_in(message):
            async with message.channel.typing():
                # Generate friendly, human response for the creator
                response: str = await self.ai.generate_developer_response(
                    message.content,
                    message.author.display_name
                )
                await message.reply(response)
                logger.tree("CREATOR INTERACTION", [
                    ("Father", str(message.author)),
                    ("Message", message.content[:50]),
                    ("Response", response[:50])
                ], "👑")
            return
        
        # Generate AI response if conditions are met
        # AI decides whether to respond based on content, mentions, and mute status
        if self.ai.should_respond(message.content, self.user.mentioned_in(message), is_muted):
            # Rate limiting for muted users only
            if is_muted:
                user_id = message.author.id
                current_time = datetime.now()
                
                # Check if user is on cooldown
                if user_id in self.prisoner_cooldowns:
                    last_response_time = self.prisoner_cooldowns[user_id]
                    time_since_last = (current_time - last_response_time).total_seconds()
                    
                    if time_since_last < self.PRISONER_COOLDOWN_SECONDS:
                        # User is on cooldown - buffer their message
                        if user_id not in self.prisoner_message_buffer:
                            self.prisoner_message_buffer[user_id] = []
                        self.prisoner_message_buffer[user_id].append(message.content)
                        
                        # Don't respond yet
                        logger.info(f"Rate limited {message.author.name} - buffering message (total: {len(self.prisoner_message_buffer[user_id])})")
                        return
                
                # User is not on cooldown - prepare response
                async with message.channel.typing():
                    # Get mute reason if available
                    mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or 
                                  self.prison_handler.mute_reasons.get(message.author.name.lower()))
                    
                    # Check if there are buffered messages
                    combined_context = message.content
                    if user_id in self.prisoner_message_buffer and self.prisoner_message_buffer[user_id]:
                        # Combine all buffered messages with the current one
                        all_messages = self.prisoner_message_buffer[user_id] + [message.content]
                        combined_context = f"The user sent multiple messages: {' | '.join(all_messages)}"
                        
                        # Clear the buffer
                        self.prisoner_message_buffer[user_id] = []
                        
                        logger.info(f"Processing {len(all_messages)} messages from {message.author.name}")
                    
                    # Generate contextual AI response with all messages considered
                    response: str = await self.ai.generate_response(
                        combined_context,
                        message.author.display_name,
                        is_muted,
                        mute_reason
                    )
                    await message.reply(response)
                    
                    # Update cooldown
                    self.prisoner_cooldowns[user_id] = current_time
                    
                    # Special logging for muted users (ragebait responses)
                    logger.tree("RAGEBAITED PRISONER", [
                        ("Target", str(message.author)),
                        ("Message", message.content[:50]),
                        ("Response", response[:50]),
                        ("Cooldown", f"{self.PRISONER_COOLDOWN_SECONDS}s")
                    ], "😈")
            else:
                # Non-muted users don't have rate limiting
                async with message.channel.typing():
                    # Get mute reason if available
                    mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or 
                                  self.prison_handler.mute_reasons.get(message.author.name.lower()))
                    
                    # Generate contextual AI response
                    response: str = await self.ai.generate_response(
                        message.content,
                        message.author.display_name,
                        is_muted,
                        mute_reason
                    )
                    await message.reply(response)
    
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """
        Discord member update event handler.
        
        Monitors member role changes to detect when users get the muted role
        or get unmuted, and sends appropriate messages.
        
        Args:
            before (discord.Member): Member state before update
            after (discord.Member): Member state after update
        """
        # Only process if bot is active
        if not self.is_active:
            return
        
        # Check if user just got the muted role
        had_muted_role: bool = any(role.id == self.muted_role_id for role in before.roles)
        has_muted_role: bool = any(role.id == self.muted_role_id for role in after.roles)
        
        # User just got muted (new prisoner)
        if not had_muted_role and has_muted_role:
            logger.success(f"New prisoner detected: {after.name}")
            await self.prison_handler.handle_new_prisoner(after)
        
        # User just got unmuted (freed from prison)
        elif had_muted_role and not has_muted_role:
            logger.success(f"Prisoner released: {after.name}")
            await self.prison_handler.handle_prisoner_release(after)
            
            # Clear rate limiting for this user
            if after.id in self.prisoner_cooldowns:
                del self.prisoner_cooldowns[after.id]
            if after.id in self.prisoner_message_buffer:
                del self.prisoner_message_buffer[after.id]