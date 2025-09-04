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
- Modular command architecture

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
from src.services.ai_service import AIService
from src.commands import ActivateCommand, DeactivateCommand


class AzabBot(discord.Client):
    """
    Main Discord bot class for Azab.
    
    Handles all Discord API interactions including:
    - Message processing and AI responses
    - Slash command registration and execution
    - User activity logging to database
    - Bot activation/deactivation states
    - Muted user detection and prison monitoring
    - Mute embed processing from logs channel
    
    Attributes:
        db (Database): Database connection for message logging
        ai (AIService): AI service for generating responses
        is_active (bool): Bot activation state (starts as True)
        tree (app_commands.CommandTree): Discord slash command tree
        mute_reasons (dict): Store mute reasons by user ID/name
        allowed_channels (set): Restricted channel IDs for bot operation
        logs_channel_id (int): Channel ID for monitoring mute embeds
        prison_channel_id (int): Channel ID for prison messages
        muted_role_id (int): Role ID for muted users
    """
    
    def __init__(self):
        """
        Initialize the Azab Discord bot.
        
        Sets up Discord intents, initializes services (database, AI),
        and registers slash commands. Bot starts in active state by default.
        Configures channel monitoring for mute detection and prison management.
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
        self.mute_reasons = {}                                  # Store mute reasons {user_id: reason}
        
        # Load channel IDs from environment
        prison_channels = os.getenv('PRISON_CHANNEL_IDS', '')
        self.allowed_channels = {int(ch) for ch in prison_channels.split(',') if ch.strip()}
        if self.allowed_channels:
            logger.info(f"Bot restricted to channels: {self.allowed_channels}")
        
        # Load logs and prison channel IDs for mute detection
        self.logs_channel_id = int(os.getenv('LOGS_CHANNEL_ID', '1404020045876690985'))
        self.prison_channel_id = int(os.getenv('PRISON_CHANNEL_IDS', '1402671536866984067'))
        self.muted_role_id = int(os.getenv('MUTED_ROLE_ID', '1402287996648030249'))
        self.general_channel_id = int(os.getenv('GENERAL_CHANNEL_ID', '1350540215797940245'))
        
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
        # Only check for muted role, ignore Discord timeouts
        if hasattr(member, 'roles'):
            for role in member.roles:
                if role.id == self.muted_role_id:
                    return True
        
        return False
    
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
        
        logger.info("Commands registered: /activate, /deactivate")
    
    async def setup_hook(self):
        """
        Discord.py setup hook - called before bot connects.
        
        Syncs all registered slash commands with Discord's API.
        This ensures commands are available in all connected servers.
        """
        await self.tree.sync()
        logger.success(f"Synced {len(self.tree.get_commands())} commands")
    
    async def on_ready(self):
        """
        Discord bot ready event handler.
        
        Called when bot successfully connects to Discord Gateway.
        Displays bot status information and confirms connection.
        """
        logger.tree("BOT ONLINE", [
            ("Name", self.user.name),
            ("ID", str(self.user.id)),
            ("Servers", str(len(self.guilds))),
            ("Status", "ACTIVE - Ragebaiting enabled")
        ], "🚀")
    
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
            await self._process_mute_embed(message)
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
        
        # Check if user is currently muted (by timeout or role)
        # Checks both Discord timeout and muted role
        is_muted = self.is_user_muted(message.author)
        
        # Generate AI response if conditions are met
        # AI decides whether to respond based on content, mentions, and mute status
        if self.ai.should_respond(message.content, self.user.mentioned_in(message), is_muted):
            async with message.channel.typing():
                # Get mute reason if available
                mute_reason = self.mute_reasons.get(message.author.id) or self.mute_reasons.get(message.author.name.lower())
                
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
                    logger.tree("RAGEBAITED PRISONER", [
                        ("Target", str(message.author)),
                        ("Message", message.content[:50]),
                        ("Response", response[:50])
                    ], "😈")
    
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
            logger.success(f"New prisoner detected: {after.name}")
            await self._handle_new_prisoner(after)
        
        # User just got unmuted (freed from prison)
        elif had_muted_role and not has_muted_role:
            logger.success(f"Prisoner released: {after.name}")
            await self._handle_prisoner_release(after)
    
    async def _handle_new_prisoner(self, member: discord.Member):
        """
        Welcome a newly muted user to prison with savage ragebait.
        
        FIRST scans the logs channel for mute embeds to extract the mute reason,
        THEN generates a contextual AI response to mock the user about
        their specific offense.
        
        Args:
            member (discord.Member): The newly muted Discord member
        """
        try:
            logger.info(f"Handling new prisoner: {member.name} (ID: {member.id})")
            
            # Get required channels
            logs_channel = self.get_channel(self.logs_channel_id)
            prison_channel = self.get_channel(self.prison_channel_id)
            
            logger.info(f"Channels - Logs: {logs_channel}, Prison: {prison_channel}")
            
            # Validate channels exist
            if not logs_channel or not prison_channel:
                logger.error(f"Channels not found - logs: {self.logs_channel_id}, prison: {self.prison_channel_id}")
                return
            
            # FIRST: Extract mute reason from logs channel
            # Wait for the mute embed to appear in logs
            logger.info(f"Waiting for mute embed to appear in logs for {member.name}")
            await asyncio.sleep(5)  # Give enough time for the mute bot to post the embed
            
            # Check if we already have the mute reason stored
            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            if mute_reason:
                logger.info(f"Found stored mute reason for {member.name}: {mute_reason}")
            else:
                # Scan logs channel for mute embed
                logger.info(f"Scanning logs channel for {member.name}'s mute reason...")
                
                messages_checked = 0
                async for message in logs_channel.history(limit=50):  # Check more messages
                    messages_checked += 1
                    if message.embeds:
                        # Process all embeds in this message
                        await self._process_mute_embed(message)
                        
                        # Check if we now have the reason for this specific user
                        mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
                        if mute_reason:
                            logger.success(f"Found mute reason for {member.name}: {mute_reason}")
                            break
                
                logger.info(f"Scanned {messages_checked} messages in logs channel")
            
            if not mute_reason:
                logger.warning(f"Could not find mute reason for {member.name} - will use generic welcome")
            
            # SECOND: Generate contextual welcome message AFTER extracting reason
            logger.info(f"Generating welcome message for {member.name} with reason: {mute_reason or 'None'}")
            
            if mute_reason:
                welcome_prompt = (
                    f"Welcome a prisoner who just got thrown in jail for: '{mute_reason}'. "
                    f"Mock them brutally and specifically about why they got jailed. "
                    f"Make fun of their mute reason. Be savage and reference their specific offense. "
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
            
            # Generate AI response for the welcome
            response = await self.ai.generate_response(
                welcome_prompt,
                member.display_name,
                True,  # They're muted
                mute_reason
            )
            
            # THIRD: Send welcome message to prison channel
            welcome_msg = f"🔒 **NEW PRISONER ARRIVAL** 🔒\n\n{member.mention}\n\n{response}"
            await prison_channel.send(welcome_msg)
            
            # Log the welcome event
            logger.tree("NEW PRISONER WELCOMED", [
                ("Prisoner", str(member)),
                ("Reason", mute_reason[:50] if mute_reason else "Unknown"),
                ("Welcome", response[:50])
            ], "⛓️")
            
        except Exception as e:
            logger.error(f"Failed to welcome prisoner: {e}")
    
    async def _handle_prisoner_release(self, member: discord.Member):
        """
        Send a message when a user gets unmuted (freed from prison).
        
        Sends a sarcastic/mocking message to the general chat when someone
        gets unmuted, making fun of their time in prison.
        
        Args:
            member (discord.Member): The newly unmuted Discord member
        """
        try:
            logger.info(f"Handling prisoner release: {member.name} (ID: {member.id})")
            
            # Get the general channel
            general_channel = self.get_channel(self.general_channel_id)
            
            if not general_channel:
                logger.error(f"General channel not found: {self.general_channel_id}")
                return
            
            # Get their mute reason if we have it
            mute_reason = self.mute_reasons.get(member.id) or self.mute_reasons.get(member.name.lower())
            
            # Generate a release message
            if mute_reason:
                release_prompt = (
                    f"Someone just got released from prison where they were locked up for: '{mute_reason}'. "
                    f"Mock them sarcastically about being freed. Make jokes about their time in jail. "
                    f"Act like they probably didn't learn their lesson. "
                    f"Be sarcastic about them being 'reformed'. Keep it under 50 words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            else:
                release_prompt = (
                    f"Someone just got released from prison. "
                    f"Mock them about finally being free. Be sarcastic about their jail time. "
                    f"Make jokes about them probably going back soon. Keep it under 50 words. "
                    f"IMPORTANT: Do NOT mention their name, just refer to them as 'you' since they will be pinged."
                )
            
            # Generate AI response
            response = await self.ai.generate_response(
                release_prompt,
                member.display_name,
                False,  # They're NOT muted anymore
                mute_reason
            )
            
            # Send release message to general channel - ping once then the message
            release_msg = f"🔓 **PRISONER RELEASED** 🔓\n\n{member.mention} {response}"
            await general_channel.send(release_msg)
            
            # Clear their mute reason since they're free now
            if member.id in self.mute_reasons:
                del self.mute_reasons[member.id]
            if member.name.lower() in self.mute_reasons:
                del self.mute_reasons[member.name.lower()]
            
            # Log the release event
            logger.tree("PRISONER RELEASED", [
                ("Ex-Prisoner", str(member)),
                ("Previous Offense", mute_reason[:50] if mute_reason else "Unknown"),
                ("Release Message", response[:50])
            ], "🔓")
            
        except Exception as e:
            logger.error(f"Failed to handle prisoner release: {e}")
    
    async def _process_mute_embed(self, message: discord.Message):
        """
        Process mute embeds from logs channel to extract reasons.
        
        Monitors the logs channel for mute embeds and extracts:
        - User ID and username from embed fields
        - Mute reason for contextual AI responses
        - Stores information in mute_reasons dict for later use
        
        Args:
            message (discord.Message): Message containing mute embed
        """
        import re
        
        for embed in message.embeds:
            # Debug log the embed structure
            logger.info(f"Processing embed - Title: {embed.title}, Author: {embed.author}")
            
            # Look for mute embeds (check title, author name, or description)
            embed_text = (str(embed.title or '') + str(embed.author.name if embed.author else '') + 
                         str(embed.description or '')).lower()
            
            if 'mute' not in embed_text and 'timeout' not in embed_text:
                continue
            
            logger.info(f"Found mute embed with {len(embed.fields)} fields")
            
            user_id = None
            user_name = None
            reason = None
            
            # First try to extract from description if it exists
            if embed.description:
                # Try to extract user mention from description
                match = re.search(r'<@!?(\d+)>', embed.description)
                if match:
                    user_id = int(match.group(1))
                    logger.info(f"Found user ID in description: {user_id}")
            
            # Extract info from embed fields
            for field in embed.fields:
                field_name_lower = field.name.lower()
                logger.info(f"Field: {field.name} = {field.value[:100]}")
                
                # Check for user field (might be called User, Member, Target, etc.)
                if any(x in field_name_lower for x in ['user', 'member', 'target', 'offender']):
                    # Extract username and/or mention
                    if '<@' in field.value:
                        # Try to extract user mention
                        match = re.search(r'<@!?(\d+)>', field.value)
                        if match:
                            user_id = int(match.group(1))
                            logger.info(f"Extracted user ID: {user_id}")
                    
                    # Also extract username (remove mention part if exists)
                    user_name_match = re.search(r'([^<>@]+?)(?:\s*<@|$)', field.value)
                    if user_name_match:
                        user_name = user_name_match.group(1).strip()
                        logger.info(f"Extracted username: {user_name}")
                    
                # Check for reason field
                elif 'reason' in field_name_lower:
                    reason = field.value.strip()
                    logger.info(f"Extracted reason: {reason}")
            
            # Store the reason if we found it
            if reason:
                if user_id:
                    self.mute_reasons[user_id] = reason
                    logger.success(f"Stored mute reason for user ID {user_id}: {reason}")
                if user_name:
                    # Also store by username for fallback
                    self.mute_reasons[user_name.lower()] = reason
                    logger.success(f"Stored mute reason for username {user_name}: {reason}")
            else:
                logger.warning("Could not extract mute reason from embed")
    
