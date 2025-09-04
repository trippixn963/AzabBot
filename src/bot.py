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
from datetime import datetime
import asyncio
import os

from src.core.logger import logger
from src.core.database import Database
from src.utils.version import Version
from src.services.ai_service import AIService
from src.commands import ActivateCommand, DeactivateCommand
from src.handlers import PrisonHandler, MuteHandler


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
    """
    
    def __init__(self):
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
        self.db = Database()                                    # Message logging database
        self.ai = AIService(os.getenv('OPENAI_API_KEY'))       # AI response generation
        self.is_active = True                                   # Bot starts in active state
        self.tree = app_commands.CommandTree(self)             # Discord slash command tree
        
        # Load channel IDs from environment
        prison_channels = os.getenv('PRISON_CHANNEL_IDS', '')
        self.allowed_channels = {int(ch) for ch in prison_channels.split(',') if ch.strip()}
        if self.allowed_channels:
            logger.service_status("Channel Restriction", f"{len(self.allowed_channels)} channels")
        
        # Load channel and role IDs for mute detection
        self.logs_channel_id = int(os.getenv('LOGS_CHANNEL_ID', '1404020045876690985'))
        self.prison_channel_id = int(os.getenv('PRISON_CHANNEL_IDS', '1402671536866984067'))
        self.muted_role_id = int(os.getenv('MUTED_ROLE_ID', '1402287996648030249'))
        self.general_channel_id = int(os.getenv('GENERAL_CHANNEL_ID', '1350540215797940245'))
        
        # Initialize handlers
        self.prison_handler = PrisonHandler(self, self.ai)
        self.mute_handler = MuteHandler(self.prison_handler)
        
        # Register all slash commands
        self._register_commands()
    
    def is_user_muted(self, member: discord.Member) -> bool:
        """
        Check if a user has the muted role.
        
        Args:
            member: Discord member to check
            
        Returns:
            bool: True if user has muted role, False otherwise
        """
        return self.mute_handler.is_user_muted(member, self.muted_role_id)
    
    def _register_commands(self):
        """
        Register all slash commands with Discord.
        
        Creates command instances from separate files and adds them
        to the Discord command tree for slash command functionality.
        """
        # Create command instances from modular command files
        activate_cmd = ActivateCommand(self)      # Bot activation command
        deactivate_cmd = DeactivateCommand(self)  # Bot deactivation command
        
        # Add commands to Discord's command tree
        self.tree.add_command(activate_cmd.create_command())
        self.tree.add_command(deactivate_cmd.create_command())
        
        logger.service_status("Commands", "2 slash commands registered")
    
    async def setup_hook(self):
        """
        Discord.py setup hook - called before bot connects.
        
        Syncs all registered slash commands with Discord's API.
        This ensures commands are available in all connected servers.
        """
        await self.tree.sync()
        logger.service_status("Discord Sync", f"{len(self.tree.get_commands())} commands synced")
    
    async def on_ready(self):
        """
        Discord bot ready event handler.
        
        Called when bot successfully connects to Discord Gateway.
        Displays bot status information and confirms connection.
        """
        # Get version information for status display
        version_info = Version.get_full_info()
        
        logger.bot_ready(
            f"{self.user.name} ({version_info['version']})", 
            str(self.user.id), 
            len(self.guilds)
        )
    
    async def on_message(self, message: discord.Message):
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
        
        # Ignore messages from bots or when bot is inactive
        if message.author.bot or not self.is_active:
            return
        
        # Check if message is in allowed channel (if restrictions are set)
        if self.allowed_channels and message.channel.id not in self.allowed_channels:
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
        is_muted = self.is_user_muted(message.author)
        
        # Generate AI response if conditions are met
        # AI decides whether to respond based on content, mentions, and mute status
        if self.ai.should_respond(message.content, self.user.mentioned_in(message), is_muted):
            async with message.channel.typing():
                # Get mute reason if available
                mute_reason = (self.prison_handler.mute_reasons.get(message.author.id) or 
                              self.prison_handler.mute_reasons.get(message.author.name.lower()))
                
                # Generate contextual AI response
                response = await self.ai.generate_response(
                    message.content,
                    message.author.display_name,
                    is_muted,
                    mute_reason
                )
                await message.reply(response)
                
                # Special logging for muted users (ragebait responses)
                if is_muted:
                    logger.ragebait_sent(str(message.author))
    
    async def on_member_update(self, before: discord.Member, after: discord.Member):
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
        had_muted_role = any(role.id == self.muted_role_id for role in before.roles)
        has_muted_role = any(role.id == self.muted_role_id for role in after.roles)
        
        # User just got muted (new prisoner)
        if not had_muted_role and has_muted_role:
            logger.prisoner_event("DETECTED", after.name)
            await self.prison_handler.handle_new_prisoner(after)
        
        # User just got unmuted (freed from prison)
        elif had_muted_role and not has_muted_role:
            logger.prisoner_event("RELEASED", after.name)
            await self.prison_handler.handle_prisoner_release(after)