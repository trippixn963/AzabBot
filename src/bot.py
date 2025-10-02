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

from src.core.logger import logger
from src.core.database import Database
from src.services.ai_service import AIService
from src.commands import ActivateCommand, DeactivateCommand
from src.handlers import PrisonHandler, MuteHandler, PresenceHandler
from src.utils.error_handler import ErrorHandler
from src.utils.validators import Validators, ValidationError, InputSanitizer


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
        
        Process Flow:
        1. Configure Discord intents for required permissions
        2. Initialize core services (database, AI, logging)
        3. Load persistent state from bot_state.json
        4. Load and validate environment variables
        5. Initialize handlers (prison, mute, presence)
        6. Set up rate limiting for prisoners
        7. Register slash commands
        """
        # === STEP 1: Configure Discord Intents ===
        # Intents control what events Discord sends to the bot
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read message text (privileged intent)
        intents.members = True          # Required for member role changes and info (privileged intent)
        super().__init__(intents=intents)
        
        # === STEP 2: Initialize Core Services ===
        self.db: Database = Database()                                    # SQLite database for message/mute logging
        self.ai: AIService = AIService(os.getenv('OPENAI_API_KEY'))      # OpenAI GPT-3.5-turbo integration
        self.start_time: datetime = datetime.now()                        # Bot start time for uptime tracking
        
        # === STEP 3: Load Persistent State ===
        # Bot activation state persists across restarts via JSON file
        # This allows bot to remember if it was active/inactive before shutdown
        self.state_file: str = 'bot_state.json'
        self.is_active: bool = self._load_state()  # Load from file, default to True if file missing
        
        # Initialize Discord slash command tree
        # This manages all /commands for the bot
        self.tree: app_commands.CommandTree = app_commands.CommandTree(self)
        
        # === STEP 4: Load Channel Restrictions ===
        # Optional: Restrict bot to specific channels only
        # If PRISON_CHANNEL_IDS is set, bot only responds in those channels
        prison_channels: Optional[str] = os.getenv('PRISON_CHANNEL_IDS', '')
        self.allowed_channels: Set[int] = {int(ch) for ch in prison_channels.split(',') if ch.strip()}
        if self.allowed_channels:
            logger.info(f"Bot restricted to channels: {self.allowed_channels}")
        
        # === STEP 5: Load and Validate Required Environment Variables ===
        # These IDs are REQUIRED for bot operation - bot will crash if missing
        # Load as strings first for validation before converting to int
        logs_channel_id_str: Optional[str] = os.getenv('LOGS_CHANNEL_ID')          # Where mod bot posts mute logs
        prison_channel_id_str: Optional[str] = os.getenv('PRISON_CHANNEL_IDS')     # Where muted users can talk
        muted_role_id_str: Optional[str] = os.getenv('MUTED_ROLE_ID')              # Discord role for muted users
        general_channel_id_str: Optional[str] = os.getenv('GENERAL_CHANNEL_ID')    # Main chat for release messages
        developer_id_str: Optional[str] = os.getenv('DEVELOPER_ID')                # Bot creator's Discord ID
        
        # Validate all required variables are present before proceeding
        # If any are missing, log clearly and raise error (bot can't function without these)
        if not all([logs_channel_id_str, prison_channel_id_str, muted_role_id_str, general_channel_id_str, developer_id_str]):
            # Build list of missing variables for clear error message
            missing_vars = []
            if not logs_channel_id_str: missing_vars.append('LOGS_CHANNEL_ID')
            if not prison_channel_id_str: missing_vars.append('PRISON_CHANNEL_IDS')
            if not muted_role_id_str: missing_vars.append('MUTED_ROLE_ID')
            if not general_channel_id_str: missing_vars.append('GENERAL_CHANNEL_ID')
            if not developer_id_str: missing_vars.append('DEVELOPER_ID')
            
            # Log error with details about what's missing
            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("   Please add these to your .env file")
            # Crash bot with clear error (better than running with incorrect config)
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Convert validated strings to integers for Discord API usage
        self.logs_channel_id: int = int(logs_channel_id_str)
        self.prison_channel_id: int = int(prison_channel_id_str)
        self.muted_role_id: int = int(muted_role_id_str)
        self.general_channel_id: int = int(general_channel_id_str)
        self.developer_id: int = int(developer_id_str)

        # === Load Optional Family Member IDs ===
        # These are optional - bot will work without them but won't have special family responses
        uncle_id_str: Optional[str] = os.getenv('UNCLE_ID')
        self.uncle_id: Optional[int] = int(uncle_id_str) if uncle_id_str else None

        brother_id_str: Optional[str] = os.getenv('BROTHER_ID')
        self.brother_id: Optional[int] = int(brother_id_str) if brother_id_str else None

        # === STEP 6: Initialize Specialized Handlers ===
        # Each handler manages a specific aspect of bot functionality
        self.prison_handler: PrisonHandler = PrisonHandler(self, self.ai)    # Handles welcome/release messages
        self.mute_handler: MuteHandler = MuteHandler(self.prison_handler)    # Extracts mute reasons from logs
        self.presence_handler: PresenceHandler = PresenceHandler(self)       # Manages Discord rich presence
        
        # === STEP 7: Set Up Rate Limiting for Prisoners ===
        # Prevents prisoners from spamming and getting rapid responses
        # Maps user ID to last response time for cooldown tracking
        self.prisoner_cooldowns: Dict[int, datetime] = {}  # {user_id: last_response_time}
        # Buffers messages from prisoners during cooldown for batch processing
        self.prisoner_message_buffer: Dict[int, List[str]] = {}  # {user_id: [buffered_messages]}
        # Cooldown duration in seconds (default 10s, configurable via .env)
        self.PRISONER_COOLDOWN_SECONDS: int = int(os.getenv('PRISONER_COOLDOWN_SECONDS', '10'))
        
        # === STEP 8: Register Slash Commands ===
        # Register /activate and /deactivate commands with Discord
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
            ErrorHandler.handle(
                e,
                location="Bot._load_state",
                critical=False,
                state_file=self.state_file
            )
        return True  # Default to active
    
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

        # Add commands to Discord's command tree
        self.tree.add_command(activate_cmd.create_command())
        self.tree.add_command(deactivate_cmd.create_command())

        logger.info("Commands registered: /activate, /deactivate")
    
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
        try:
            logger.tree("BOT ONLINE", [
                ("Name", self.user.name),
                ("ID", str(self.user.id)),
                ("Servers", str(len(self.guilds))),
                ("Status", "ACTIVE - Ragebaiting enabled")
            ], "🚀")

            # Start presence updates
            await self.presence_handler.start_presence_loop()
        except Exception as e:
            ErrorHandler.handle(
                e,
                location="Bot.on_ready",
                critical=False,
                bot_name=self.user.name if self.user else "Unknown"
            )
            # Bot can still function without presence updates
    
    async def on_message(self, message: discord.Message) -> None:
        """
        Discord message event handler - Core message processing logic.

        Processes all incoming messages with complex decision tree:
        1. Check for mute embeds in logs channel (extract mute reasons)
        2. Validate and sanitize message content
        3. Identify user type (family/regular/prisoner)
        4. Apply appropriate response logic based on user status
        5. Handle rate limiting for prisoners
        6. Log everything to database

        Process Flow:
        - Mute embeds → Extract reason and store
        - Bot messages → Ignore
        - Invalid content → Reject
        - Family members → Require mention, bypass restrictions
        - Inactive bot → Only respond to family
        - Muted users → Ragebait with rate limiting
        - Regular users → No response (muted-only mode)

        Args:
            message (discord.Message): The Discord message object from event
        """
        try:
            # === PRIORITY CHECK: Mute Embed Processing ===
            # If message is in logs channel and contains embeds, it might be a mute notification
            # Process it to extract mute reasons for contextual roasting
            if message.channel.id == self.logs_channel_id and message.embeds:
                await self.mute_handler.process_mute_embed(message)
                return  # Don't process mute embeds as regular messages

            # === FILTER: Ignore Bot Messages ===
            # Prevent bot-to-bot interactions and infinite loops
            if message.author.bot:
                return

            # === VALIDATION: Sanitize Message Content ===
            # Validate message content for security (SQL injection, XSS, etc.)
            if message.content:
                try:
                    validated_content = Validators.validate_message_content(message.content)
                except ValidationError as e:
                    logger.warning(f"Invalid message content from {message.author}: {e}")
                    return  # Reject invalid messages
            else:
                return  # Skip empty messages (images-only, embeds-only, etc.)
            
            # === USER IDENTIFICATION: Determine User Type ===
            # Check if user is a family member (dev, uncle, brother)
            # Family members get special privileges and different response styles
            is_developer: bool = message.author.id == self.developer_id     # Bot creator (full access)
            is_uncle: bool = self.uncle_id and message.author.id == self.uncle_id  # Uncle (special responses)
            is_brother: bool = self.brother_id and message.author.id == self.brother_id  # Brother (sibling dynamic)
            is_family: bool = is_developer or is_uncle or is_brother  # Combined family check

            # === ACCESS CONTROL: Bot Activation State ===
            # If bot is deactivated, only respond to family members
            # Regular users and prisoners get ignored when bot is sleeping
            if not self.is_active and not is_family:
                return  # Bot is inactive, user is not family - ignore message

            # === ACCESS CONTROL: Channel Restrictions ===
            # If channel restrictions are configured, enforce them
            # Family members bypass all channel restrictions (can interact anywhere)
            if not is_family and self.allowed_channels and message.channel.id not in self.allowed_channels:
                return  # Message in non-allowed channel from non-family - ignore
            
            # === DATABASE LOGGING: Store Message for Analytics ===
            # Log all guild messages to database for statistics and tracking
            # DM messages are not logged (guild-only)
            if message.guild:
                # Sanitize all inputs to prevent SQL injection and data corruption
                # This validates user IDs, usernames, message content, and channel IDs
                sanitized = InputSanitizer.sanitize_user_input(
                    user_id=message.author.id,
                    username=str(message.author),
                    message=message.content,
                    channel_id=message.channel.id
                )

                # Only log if we have valid user ID and channel ID after sanitization
                if sanitized.get('user_id') and sanitized.get('channel_id'):
                    await self.db.log_message(
                        sanitized['user_id'],
                        sanitized.get('username', 'Unknown User'),
                        sanitized.get('message', '[Empty]'),
                        sanitized['channel_id'],
                        message.guild.id
                    )

                # Store last message from each user in memory
                # Used to track what message triggered a mute (for contextual roasting)
                self.prison_handler.last_messages[message.author.id] = message.content

            # === MUTE STATUS CHECK ===
            # Determine if user currently has the muted role
            # This controls whether we use ragebait responses or ignore them
            is_muted: bool = self.is_user_muted(message.author)
            
            # === FAMILY MEMBER RESPONSE LOGIC ===
            # Family members (dev, uncle, brother) get special treatment
            # They must mention/ping the bot to get a response (prevents spam)
            if is_developer or is_uncle or is_brother:
                # Check if bot was mentioned/pinged in the message
                # Family members MUST ping the bot to get a response
                # This prevents the bot from responding to every family message
                should_respond = self.user.mentioned_in(message)

                if should_respond:
                    # Show typing indicator while generating response (better UX)
                    async with message.channel.typing():
                        # === Generate Family-Specific Response ===
                        # Each family member gets a different AI personality/style
                        if is_developer:
                            # Developer (Dad) - Intelligent, conversational, helpful responses
                            # Can query database, get stats, have deep conversations
                            response: str = await self.ai.generate_developer_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "CREATOR INTERACTION"
                            log_icon = "👑"  # Crown for the creator
                        elif is_uncle:
                            # Uncle - Respectful but friendly, uncle-nephew dynamic
                            # Casual conversations with respect
                            response: str = await self.ai.generate_uncle_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "UNCLE INTERACTION"
                            log_icon = "🎩"  # Top hat for uncle
                        else:  # is_brother
                            # Brother - Sibling dynamic, playful banter
                            # More casual and brotherly interactions
                            response: str = await self.ai.generate_brother_response(
                                message.content,
                                message.author.display_name
                            )
                            log_title = "BROTHER INTERACTION"
                            log_icon = "🤝"  # Handshake for brother

                        # Send response as a reply to their message
                        await message.reply(response)
                        
                        # Log family interaction to console for monitoring
                        logger.tree(log_title, [
                            ("Family", str(message.author)),
                            ("Message", message.content[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Response", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))])
                        ], log_icon)
                    return  # Exit after handling family message
            
            # === RESPONSE DECISION: Check if Bot Should Respond ===
            # AI service determines if conditions are met for a response
            # Currently configured to only respond to muted users (prisoners)
            if self.ai.should_respond(message.content, self.user.mentioned_in(message), is_muted):
                # === PRISONER RATE LIMITING SYSTEM ===
                # Muted users get rate-limited to prevent spam and save API costs
                # Regular users would go here too if we enabled non-muted responses
                if is_muted:
                    user_id = message.author.id
                    current_time = datetime.now()
                    
                    # === Check Cooldown Status ===
                    # See if this prisoner is currently on cooldown from a recent response
                    if user_id in self.prisoner_cooldowns:
                        # Get when we last responded to this prisoner
                        last_response_time = self.prisoner_cooldowns[user_id]
                        # Calculate how much time has passed since last response
                        time_since_last = (current_time - last_response_time).total_seconds()
                        
                        # === Cooldown Active: Buffer Message ===
                        # If they're still on cooldown, don't respond yet but save their message
                        # We'll process all buffered messages when cooldown expires
                        if time_since_last < self.PRISONER_COOLDOWN_SECONDS:
                            # Initialize buffer list if this is their first buffered message
                            if user_id not in self.prisoner_message_buffer:
                                self.prisoner_message_buffer[user_id] = []
                            # Add current message to buffer
                            self.prisoner_message_buffer[user_id].append(message.content)
                            
                            # Log rate limiting for monitoring
                            logger.info(f"Rate limited {message.author.name} - buffering message (total: {len(self.prisoner_message_buffer[user_id])})")
                            return  # Exit without responding (save for later)
                    
                    # === Cooldown Expired: Generate Response ===
                    # User is not on cooldown anymore - time to respond with savage roast
                    async with message.channel.typing():
                        # === Gather Context for AI Response ===
                        # Get mute reason from prison handler (extracted from logs channel)
                        # Try both user ID and username for maximum reliability
                        mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or 
                                      self.prison_handler.mute_reasons.get(message.author.name.lower()))
                        
                        # === Process Buffered Messages ===
                        # Check if prisoner sent multiple messages during cooldown
                        # If so, combine all of them into one context for AI to roast
                        combined_context = message.content
                        if user_id in self.prisoner_message_buffer and self.prisoner_message_buffer[user_id]:
                            # Combine all buffered messages with current message
                            # This prevents missing context from rapid-fire messages
                            all_messages = self.prisoner_message_buffer[user_id] + [message.content]
                            combined_context = f"The user sent multiple messages: {' | '.join(all_messages)}"
                            
                            # Clear buffer after processing
                            self.prisoner_message_buffer[user_id] = []
                            
                            # Log batch processing for monitoring
                            logger.info(f"Processing {len(all_messages)} messages from {message.author.name}")
                        
                        # === Get Additional Context ===
                        # Get the message that triggered their mute (if available)
                        # This helps AI reference what got them in trouble
                        trigger_msg = self.prison_handler.last_messages.get(message.author.id)

                        # Get how long they've been muted for time-based roasting
                        # AI adjusts intensity based on duration (fresh vs veteran prisoners)
                        mute_duration = await self.db.get_current_mute_duration(message.author.id)

                        # === Generate AI Roast ===
                        # Call AI service with full context:
                        # - Combined/buffered messages
                        # - Mute reason
                        # - Trigger message
                        # - Mute duration
                        # - User profile data
                        response: str = await self.ai.generate_response(
                            combined_context,
                            message.author.display_name,
                            is_muted,
                            mute_reason,
                            trigger_msg,
                            user_id=message.author.id,
                            mute_duration_minutes=mute_duration
                        )
                        # Send roast as reply to prisoner's message
                        await message.reply(response)
                        
                        # === Update Rate Limit Timer ===
                        # Record current time as last response time
                        # Prisoner must wait PRISONER_COOLDOWN_SECONDS before next response
                        self.prisoner_cooldowns[user_id] = current_time
                        
                        # === Log Successful Ragebait ===
                        # Log prisoner interaction for monitoring and statistics
                        logger.tree("RAGEBAITED PRISONER", [
                            ("Target", str(message.author)),
                            ("Message", message.content[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Response", response[:int(os.getenv('LOG_TRUNCATE_LENGTH', '50'))]),
                            ("Cooldown", f"{self.PRISONER_COOLDOWN_SECONDS}s")
                        ], "😈")
                else:
                    # Non-muted users don't have rate limiting
                    async with message.channel.typing():
                        # Get mute reason if available
                        mute_reason: Optional[str] = (self.prison_handler.mute_reasons.get(message.author.id) or 
                                      self.prison_handler.mute_reasons.get(message.author.name.lower()))
                        
                        # Get trigger message from prison handler
                        trigger_msg = self.prison_handler.last_messages.get(message.author.id)

                        # Generate contextual AI response
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
            # Continue processing other messages

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """
        Discord member update event handler.

        Monitors member role changes to detect when users get the muted role
        or get unmuted, and sends appropriate messages.

        Args:
            before (discord.Member): Member state before update
            after (discord.Member): Member state after update
        """
        try:
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
            # Continue processing other events