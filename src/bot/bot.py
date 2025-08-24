# =============================================================================
# AzabBot - Main Bot Module
# =============================================================================
# Professional Discord bot implementation with clean architecture, proper
# service integration, and comprehensive error handling. This is the main
# bot class that orchestrates all services and handles Discord events.
#
# Features:
# - Service-oriented architecture with dependency injection
# - Proper error handling and recovery mechanisms
# - Health monitoring and metrics collection
# - Structured logging with context
# - Rate limiting and security controls
# - Modular command system
# =============================================================================

import asyncio
import datetime
import random
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Optional, Union

import discord
from discord import app_commands

from src.core.di_container import resolve
from src.core.logger import get_logger, log_error, log_system_event
from src.monitoring.health_monitor import HealthMonitor
from src.services.ai_service import AIService
from src.utils.embed_builder import EmbedBuilder


@dataclass
class BotMetrics:
    """Bot operational metrics."""

    messages_seen: int = 0
    responses_generated: int = 0
    commands_processed: int = 0
    errors_handled: int = 0
    uptime_start: datetime.datetime = None
    daily_responses: int = 0
    last_response_date: Optional[datetime.date] = None

    def __post_init__(self):
        if self.uptime_start is None:
            self.uptime_start = datetime.datetime.now(timezone.utc)


class AzabBot(discord.Client):
    """
    Main bot class implementing the AzabBot Discord client.

    This bot provides AI-powered responses with different modes for different
    channel types, including enhanced harassment capabilities for designated
    prison channels.

    The bot is built using a service-oriented architecture with proper
    dependency injection, health monitoring, and comprehensive logging.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AzabBot.

        Args:
            config: Bot configuration dictionary
        """
        # Discord intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True  # Need this to track member updates

        super().__init__(intents=intents)

        # Set up the command tree for slash commands
        self.tree = app_commands.CommandTree(self)

        # Configuration and services
        self.config = config
        self.logger = get_logger()
        self.name = "AzabBot"  # Service identifier
        self.ai_service: Optional[AIService] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.memory_service = None  # Will be set later if available
        self.prison_service = None  # Enhanced prison features
        self.psychological_service = None  # Psychological profiling and grudges

        # Bot metrics and state
        self.metrics = BotMetrics()

        # Rate limiting and cooldowns
        self.user_cooldowns: Dict[int, datetime.datetime] = {}
        self.channel_cooldowns: Dict[int, datetime.datetime] = {}

        # Message batching for better response quality
        self.message_batches: Dict[int, List[discord.Message]] = {}
        self.batch_timers: Dict[int, asyncio.Task] = {}
        self.batch_delay = 2.0  # Collect messages for 2 seconds before responding

        # Bot state
        self.is_active = False  # Bot starts inactive, requires /activate
        self.prison_mode = True  # Prison mode enabled by default
        self.developer_id = config.get("DEVELOPER_ID")  # Developer from config
        if not self.developer_id:
            raise ValueError("DEVELOPER_ID must be set in configuration")
        
        # Ignore list for users the bot should not respond to
        self.ignored_users: set[int] = set()

        # Presence management
        self.current_prisoners: set[str] = set()  # Track prisoners in jail
        self.presence_rotation_task = None
        self.presence_index = 0

        # Bot behavior settings
        self.response_probability = 0.7  # High probability for prison channels
        
        # Track start time for uptime calculation
        self.start_time = datetime.datetime.now()

        self.logger.log_info("AzabBot initialized", "🤖")

    async def setup_hook(self) -> None:
        """Set up the bot after login but before ready event."""
        try:
            # Resolve services from DI container
            self.ai_service = await resolve("AIService")
            self.health_monitor = await resolve("HealthMonitor")
            
            # Start health monitor's monitoring tasks
            if self.health_monitor:
                await self.health_monitor.start()
                self.logger.log_info("Health monitor tasks started")
            
            # Try to resolve prison service (optional)
            try:
                self.prison_service = await resolve("PrisonService")
                self.logger.log_info("Prison service loaded successfully")
            except Exception as e:
                self.logger.log_warning(f"Prison service not available: {e}")
                self.prison_service = None
            
            # Try to resolve psychological service (optional)
            try:
                self.psychological_service = await resolve("PsychologicalService")
                self.logger.log_info("Psychological service loaded successfully")
            except Exception as e:
                self.logger.log_warning(f"Psychological service not available: {e}")
                self.psychological_service = None
            
            # Try to resolve dashboard service (optional)
            try:
                if self.config.get("DASHBOARD_ENABLED", "false").lower() == "true":
                    self.dashboard_service = await resolve("DashboardService")
                    if self.dashboard_service:
                        self.dashboard_service.bot = self
                        await self.dashboard_service.start()
                        self.logger.log_info("Dashboard service connected")
                else:
                    self.dashboard_service = None
            except Exception as e:
                self.logger.log_warning(f"Dashboard service not available: {e}")
                self.dashboard_service = None

            # Register bot for health monitoring
            if self.health_monitor:
                self.health_monitor.register_service(self)
                
            # Reset daily counter if new day
            today = datetime.date.today()
            if self.metrics.last_response_date != today:
                self.metrics.daily_responses = 0
                self.metrics.last_response_date = today

            # Background tasks initialization would go here if needed

            # Register slash commands
            from src.bot.commands import (create_activate_command,
                                          create_deactivate_command,
                                          create_ignore_command)

            self.tree.add_command(create_activate_command(self))
            self.tree.add_command(create_deactivate_command(self))
            self.tree.add_command(create_ignore_command(self))

            # Sync slash commands
            await self.tree.sync()
            self.logger.log_info("Slash commands synced")

            self.logger.log_info("Bot setup completed", "✅")

        except Exception as e:
            log_error("Failed to set up bot", exception=e)
            raise

    async def on_ready(self):
        """Called when the bot is ready and connected to Discord."""
        try:
            await self._setup_bot_identity()
            await self._log_connection_info()
            await self._restore_startup_identity()

            log_system_event(
                "bot_ready",
                f"Bot connected as {self.user}",
                {
                    "user_id": self.user.id,
                    "guild_count": len(self.guilds),
                    "user_count": sum(guild.member_count for guild in self.guilds),
                },
            )

        except Exception as e:
            log_error("Error in on_ready event", exception=e)

    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        import time
        start_time = time.perf_counter()
        
        # Ignore bot messages
        if message.author.bot:
            return

        # Update metrics
        self.metrics.messages_seen += 1

        try:
            # Handle developer commands first (always works, even when deactivated)
            if await self._handle_developer_commands(message):
                return

            # Check if user has the target role from config
            target_role_id = self.config.get("TARGET_ROLE_ID")
            user_has_role = False
            if target_role_id:
                if hasattr(message.author, "roles"):
                    user_has_role = any(
                        str(role.id) == str(target_role_id)
                        for role in message.author.roles
                    )

            # Check if this is a prison channel
            is_prison_channel = self._is_prison_channel(
                message.channel.name, message.channel.id
            )

            # Debug logging with tree structure
            debug_context = {
                "author": str(message.author),
                "channel": f"#{message.channel.name}",
                "channel_id": str(message.channel.id),
                "is_prison": is_prison_channel,
                "is_active": self.is_active,
                "has_target_role": user_has_role,
                "user_roles": [str(role.id) for role in message.author.roles] if hasattr(message.author, "roles") else [],
                "target_role": str(target_role_id) if target_role_id else "None"
            }
            
            # ALWAYS store and learn from messages for context
            # Store message in memory service for learning
            if self.memory_service:
                try:
                    await self.memory_service.store_message(
                        message.author.id,
                        message.content,
                        message.channel.id,
                        message.guild.id if message.guild else None
                    )
                    self.logger.log_info(
                        f"📚 Stored message from {message.author.display_name} for learning"
                    )
                except Exception as e:
                    self.logger.log_warning(f"Failed to store message in memory: {e}")

            # Check if user is in ignore list
            user_is_ignored = message.author.id in self.ignored_users
            
            # Check if bot should respond
            should_respond = (
                self.is_active and  # Bot must be activated
                is_prison_channel and  # Must be in prison channel
                user_has_role and  # User must have the target role
                not user_is_ignored  # User must not be in ignore list
            )

            if not should_respond:
                reason = f"Active={self.is_active}, Prison={is_prison_channel}, Role={user_has_role}, Ignored={user_is_ignored}"
                debug_context["decision"] = "NOT RESPONDING"
                debug_context["reason"] = reason
                debug_context["user_ignored"] = user_is_ignored
                
                # Log specifically if user is ignored
                if user_is_ignored:
                    self.logger.log_info(f"🤐 Ignoring message from {message.author.display_name} (user is in ignore list)")
                
                self.logger.log_debug(
                    f"📥 Message received - {message.author} in #{message.channel.name}",
                    context=debug_context
                )
                return

            debug_context["decision"] = "PROCESSING"
            self.logger.log_debug(
                f"📥 Message received - {message.author} in #{message.channel.name}",
                context=debug_context
            )

            # Check rate limits
            if not self._check_rate_limits(message):
                # If rate limited, still add to batch for context
                if message.author.id not in self.message_batches:
                    self.message_batches[message.author.id] = []
                self.message_batches[message.author.id].append(message)
                return

            # Add message to batch and process after delay
            try:
                await self._add_message_to_batch(message)
            except Exception as e:
                log_error(
                    "Failed to add message to batch",
                    exception=e,
                    context={
                        "user_id": message.author.id,
                        "channel_id": message.channel.id,
                        "message_content": message.content[:100],
                    },
                )

        except Exception as e:
            self.metrics.errors_handled += 1
            log_error(
                "Error processing message",
                exception=e,
                context={
                    "user_id": message.author.id,
                    "channel_id": message.channel.id,
                    "guild_id": message.guild.id if message.guild else None,
                },
            )

            # Send error embed only to developer
            if message.author.id == self.developer_id:
                embed = EmbedBuilder.create_error_embed(
                    error_message="Failed to process message",
                    error_type=type(e).__name__,
                    additional_info=str(e)[:200],
                )
                try:
                    await message.reply(embed=embed)
                except Exception:
                    pass  # Ignore errors when sending error embeds
        finally:
            # Log processing time
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > 100:  # Only log if it took more than 100ms
                self.logger.log_debug(
                    f"Message processed in {elapsed_ms:.1f}ms | "
                    f"Channel: #{message.channel.name} | "
                    f"User: {message.author.name}"
                )

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member updates to detect new prisoners."""
        try:
            # Member updates are always monitored regardless of bot active state

            # Get the target role ID from config
            target_role_id = self.config.get("TARGET_ROLE_ID")
            if not target_role_id:
                self.logger.log_warning(
                    "No TARGET_ROLE_ID configured, cannot detect prisoners"
                )
                return

            # Check if member just got the muted role
            had_role = any(str(role.id) == str(target_role_id) for role in before.roles)
            has_role = any(str(role.id) == str(target_role_id) for role in after.roles)
            
            # Debug logging with tree structure
            if had_role != has_role:  # Only log if role changed
                debug_context = {
                    "member": after.display_name,
                    "member_id": str(after.id),
                    "had_target_role": had_role,
                    "has_target_role": has_role,
                    "target_role_id": str(target_role_id),
                    "action": "UNMUTED" if had_role and not has_role else "MUTED" if has_role else "UNKNOWN"
                }
                self.logger.log_debug(
                    f"👤 Member role update - {after.display_name}",
                    context=debug_context
                )

            # If they just got UNMUTED (had role before, doesn't have it now)
            if had_role and not has_role:
                self.logger.log_info(
                    f"🔓 Prisoner released: {after.display_name} just got unmuted!"
                )
                
                # Remove from current prisoners set
                self.current_prisoners.discard(after.display_name)
                
                # Only send release message if bot is active
                if self.is_active:
                    # Send message in general chat
                    general_channel_id = self.config.get("GENERAL_CHANNEL_ID")
                    if not general_channel_id:
                        self.logger.log_warning("GENERAL_CHANNEL_ID not configured, skipping release announcement")
                        return
                        
                    self.logger.log_info(f"Using general channel ID: {general_channel_id}")
                    general_channel = after.guild.get_channel(general_channel_id)
                    self.logger.log_info(f"General channel object: {general_channel}")
                    
                    if general_channel:
                        try:
                            # Generate AI-based release message based on their history
                            release_message = await self._generate_release_message(after)
                            
                            # Send the personalized message
                            await general_channel.send(release_message)
                            
                            self.logger.log_info(
                                f"✅ Posted unmute notification for {after.display_name} in #{general_channel.name} (ID: {general_channel.id})"
                            )
                        except Exception as e:
                            self.logger.log_error(
                                f"Failed to send unmute message: {e}"
                            )
                    else:
                        self.logger.log_error(f"Could not find general channel with ID {general_channel_id}")
                else:
                    self.logger.log_debug(
                        f"Bot is inactive, skipping release announcement for {after.display_name}"
                    )
                        
            # If they just got the muted role
            elif not had_role and has_role:
                # Check if we already processed this prisoner recently (prevent duplicates)
                if after.display_name in self.current_prisoners:
                    self.logger.log_debug(
                        f"Skipping duplicate prisoner event for {after.display_name}",
                        context={"user": after.display_name, "action": "skip_duplicate"}
                    )
                    return
                    
                self.logger.log_info(
                    f"🚨 New prisoner detected: {after.display_name} just got muted!"
                )

                # Add to current prisoners set
                self.current_prisoners.add(after.display_name)
                
                # Try to extract mute reason from audit logs (for Sapphire)
                mute_reason = None
                muted_by = None
                mute_duration = 0
                if self.psychological_service and after.guild:
                    mute_info = await self.psychological_service.extract_mute_reason_from_audit(
                        after.guild, str(after.id)
                    )
                    
                    if mute_info:
                        mute_reason = mute_info.get('reason', 'Unknown')
                        muted_by = mute_info.get('muted_by', 'Unknown')
                        mute_duration = mute_info.get('duration', 0)
                        
                        # Track the crime with duration
                        await self.psychological_service.track_crime(
                            str(after.id),
                            after.display_name,
                            {
                                'type': 'mute',
                                'reason': mute_reason,
                                'muted_by': muted_by,
                                'description': f"Muted for: {mute_reason}",
                                'duration': mute_duration,
                                'severity': 5
                            }
                        )
                        
                        # Format duration for logging
                        duration_str = ""
                        if mute_duration > 0:
                            hours = mute_duration // 3600
                            minutes = (mute_duration % 3600) // 60
                            if hours > 0:
                                duration_str = f" for {hours}h {minutes}m"
                            else:
                                duration_str = f" for {minutes}m"
                        
                        self.logger.log_info(
                            f"📝 Captured mute reason for {after.display_name}: {mute_reason}{duration_str}"
                        )

                # Find the prison channel
                prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
                if not prison_channel_id:
                    return

                # Get the prison channel
                try:
                    channel = after.guild.get_channel(int(prison_channel_id))
                    if not channel:
                        self.logger.log_warning(
                            f"Prison channel {prison_channel_id} not found in guild {after.guild.name}"
                        )
                        return
                except (ValueError, TypeError) as e:
                    log_error(
                        f"Invalid prison channel ID: {prison_channel_id}",
                        exception=e,
                        context={"guild_id": after.guild.id, "user_id": after.id},
                    )
                    return

                # Wait a moment for them to be moved to the channel
                await asyncio.sleep(2)

                # Check if this is a returning prisoner using memory service
                is_returning = False
                previous_visits = 0

                # Try to check user history using memory service
                try:
                    if self.memory_service:
                        user_memory = await self.memory_service.get_user_memory(after.id)
                        if user_memory and user_memory.get("total_interactions", 0) > 0:
                            is_returning = True
                            previous_visits = user_memory.get("total_interactions", 0)
                            self.logger.log_info(
                                f"🔄 RETURNING PRISONER: {after.display_name} has {previous_visits} previous interactions!"
                            )
                except Exception as e:
                    self.logger.log_warning(f"Could not check prisoner history: {e}")

                # Format duration string for messages
                duration_msg = ""
                if mute_duration > 0:
                    hours = mute_duration // 3600
                    minutes = (mute_duration % 3600) // 60
                    days = hours // 24
                    remaining_hours = hours % 24
                    
                    if days > 0:
                        duration_msg = f" for **{days} days**"
                    elif hours > 0:
                        duration_msg = f" for **{hours} hours**"
                    elif minutes > 0:
                        duration_msg = f" for **{minutes} minutes**"
                    else:
                        duration_msg = f" for **{mute_duration} seconds**"
                
                # Generate appropriate message based on history AND mute reason
                if is_returning:
                    # Messages for returning prisoners - mention their history and reason!
                    if mute_reason and mute_reason != 'Unknown':
                        returning_messages = [
                            f"LOOK WHO'S BACK! {after.mention}, this is your {previous_visits + 1}th visit to Sednaya. This time for: **{mute_reason}**{duration_msg}",
                            f"{after.mention} AGAIN?! I KNEW you'd be back. So you got muted{duration_msg} for **{mute_reason}** this time?",
                            f"Welcome back to Sednaya, {after.mention}! Visit #{previous_visits + 1} for **{mute_reason}**{duration_msg}. You never learn!",
                            f"Hahaha {after.mention} returns! **{mute_reason}**{duration_msg} really? That's what brought you back?",
                            f"Oh {after.mention}, back so soon? **{mute_reason}** this time{duration_msg}? Same cell as before!",
                            f"{after.mention} can't stay away! Visit #{previous_visits + 1} because of **{mute_reason}**{duration_msg}. Classic.",
                        ]
                    else:
                        returning_messages = [
                            f"LOOK WHO'S BACK! {after.mention}, this is your {previous_visits + 1}th visit to Sednaya. You never learn, do you?",
                            f"{after.mention} AGAIN?! I KNEW you'd be back. What did you do this time?",
                            f"Welcome back to Sednaya, {after.mention}! Missed me? I still remember everything from last time...",
                            f"Hahaha {after.mention} returns! Visit number {previous_visits + 1}. You're becoming a regular!",
                        ]
                    message = random.choice(returning_messages)
                else:
                    # Messages for first-time prisoners - include reason if we know it
                    if mute_reason and mute_reason != 'Unknown':
                        welcome_messages = [
                            f"Well well well, {after.mention}. I know exactly why you're here - **{mute_reason}**{duration_msg}. Welcome to Sednaya!",
                            f"Fresh meat! {after.mention}, you committed **{mute_reason}** and got locked up{duration_msg}. Hope you're ready for what's coming.",
                            f"{after.mention} Welcome to Sednaya! So you're the one who committed **{mute_reason}**{duration_msg}?",
                            f"Another prisoner! {after.mention}, you got caught for **{mute_reason}** and sentenced{duration_msg}. You'll fit right in with the others!",
                            f"Oh {after.mention}, so you're the one who committed **{mute_reason}**{duration_msg}? This should be interesting...",
                            f"New arrival! {after.mention}, you committed **{mute_reason}** and got{duration_msg}. Now confess - was it worth it?",
                            f"{after.mention}, locked up{duration_msg} for **{mute_reason}**! Time to teach you about gardening and proper cooking.",
                            f"I see everything, {after.mention}. You committed **{mute_reason}** and now you're mine{duration_msg}.",
                            f"Welcome {after.mention}! Your crime of **{mute_reason}** has earned you a special place here{duration_msg}.",
                            f"Ah {after.mention}, finally here{duration_msg} for **{mute_reason}**. I've been expecting you.",
                        ]
                    else:
                        welcome_messages = [
                            f"Well well well, look who just joined us. Welcome to your new home, {after.mention}.",
                            f"Fresh meat! {after.mention}, hope you're ready for your stay here.",
                            f"{after.mention} Welcome to Sednaya! What did you do to end up here?",
                            f"Another one! {after.mention}, tell me - what rule did you break?",
                            f"Oh {after.mention}, you're here now? This should be interesting...",
                            f"New arrival! {after.mention}, confess your crimes immediately.",
                        ]
                    message = random.choice(welcome_messages)
                
                # Only send welcome message if bot is active
                if self.is_active:
                    try:
                        await channel.send(message)
                        self.logger.log_info(
                            f"✅ Sent welcome message to new prisoner {after.display_name} in #{channel.name}"
                        )
                    except discord.Forbidden:
                        log_error(
                            "No permission to send message in prison channel",
                            context={
                                "channel_id": channel.id,
                                "channel_name": channel.name,
                            },
                        )
                    except discord.HTTPException as e:
                        log_error(
                            "Failed to send welcome message",
                            exception=e,
                            context={"user_id": after.id, "channel_id": channel.id},
                        )
                else:
                    self.logger.log_debug(
                        f"Bot is inactive, skipping welcome message for {after.display_name}"
                    )

                # Log the event
                log_system_event(
                    "new_prisoner",
                    f"New prisoner detected: {after.display_name}",
                    {"user_id": after.id, "username": after.display_name},
                )

            # NOTE: Unmute handling is already done above (lines 332-367)
            # This elif block was causing duplicate messages
            # elif had_role and not has_role:
            #     # This code was moved/merged with the earlier unmute handler

        except Exception as e:
            log_error(
                "Error in on_member_update event",
                exception=e,
                context={
                    "before_user": before.display_name if before else "Unknown",
                    "after_user": after.display_name if after else "Unknown",
                    "guild_id": after.guild.id if after and after.guild else None,
                },
            )

    async def on_member_join(self, member: discord.Member):
        """Handle when a member joins the server."""
        try:
            # Check if they have recent prison break attempts
            if self.prison_service:
                # Check database for recent escape attempts
                user_status = await self.prison_service.get_prisoner_status(str(member.id))
                
                if user_status.get('escape_attempts', 0) > 0:
                    # They tried to escape before!
                    await self.prison_service.detect_prison_break(
                        str(member.id),
                        member.display_name,
                        "rejoin_server",
                        was_muted=False  # We don't know if they were muted
                    )
                    
                    self.logger.log_warning(
                        f"🚨 ESCAPED PRISONER RETURNED: {member.display_name} rejoined after escape!"
                    )
                    
                    # Send alert to prison channel
                    prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
                    if prison_channel_id:
                        channel = member.guild.get_channel(int(prison_channel_id))
                        if channel:
                            await channel.send(
                                f"⚠️ **ALERT**: Escaped prisoner {member.mention} has returned! "
                                f"They thought they could escape justice! 🚨"
                            )
        except Exception as e:
            self.logger.log_error(f"Error in on_member_join: {e}")
    
    async def on_member_remove(self, member: discord.Member):
        """Handle when a member leaves the server."""
        try:
            # Check if they were muted (trying to escape)
            target_role_id = self.config.get("TARGET_ROLE_ID")
            was_muted = False
            
            if target_role_id:
                was_muted = any(str(role.id) == str(target_role_id) for role in member.roles)
            
            # Detect prison break attempt if they were muted
            if was_muted and self.prison_service:
                await self.prison_service.detect_prison_break(
                    str(member.id), 
                    member.display_name,
                    "leave_server",
                    was_muted=True
                )
                self.logger.log_warning(
                    f"🚨 ESCAPE ATTEMPT: {member.display_name} left while muted!"
                )
            
            # Remove from current prisoners if they were in jail
            if member.display_name in self.current_prisoners:
                self.current_prisoners.discard(member.display_name)
                self.logger.log_info(
                    f"🚪 Removed {member.display_name} from prisoners list (left server)"
                )
        except Exception as e:
            self.logger.log_error(f"Error in on_member_remove: {e}")

    async def on_error(self, event: str, *args, **kwargs):
        """Handle Discord client errors."""
        self.metrics.errors_handled += 1

        log_error(
            f"Discord event error: {event}",
            context={
                "event": event,
                "args": str(args)[:200],
                "kwargs": str(kwargs)[:200],
            },
        )

    async def _setup_bot_identity(self):
        """Set up bot's identity information."""
        # Bot always uses its default identity, no identity theft
        pass

    async def _log_connection_info(self):
        """Log comprehensive connection information."""
        # Basic connection info
        connection_info = [
            ("bot_user", f"{self.user} (ID: {self.user.id})"),
            ("guild_count", len(self.guilds)),
            ("response_probability", f"{self.response_probability:.1%}"),
            ("prison_mode", self.prison_mode),
        ]

        # Feature flags
        features = {"Feature Flags": []}

        # Channel information
        channels_info = []
        target_channels = self.config.get("target_channel_ids", [])
        prison_channels = self.config.get("prison_channel_ids", [])

        for guild in self.guilds:
            for channel in guild.text_channels:
                is_target = str(channel.id) in target_channels
                is_prison = str(channel.id) in prison_channels

                if is_target or is_prison:
                    status = []
                    if is_target:
                        status.append("TARGET")
                    if is_prison:
                        status.append("PRISON")

                    channels_info.append(
                        (
                            f"#{channel.name}",
                            f"{channel.guild.name} | {' | '.join(status)}",
                        )
                    )

        if channels_info:
            features["Target Channels"] = channels_info[:10]  # Limit display

        # Log structured information
        from src.utils.tree_log import log_perfect_tree_section

        log_perfect_tree_section("Bot Connected", connection_info, "🚀", features)

    async def _restore_startup_identity(self):
        """Set initial bot status."""
        try:
            if self.is_active:
                # Set initial online status with default presence
                activity = discord.Activity(
                    type=discord.ActivityType.watching, name="⛓ Sednaya"
                )
                await self.change_presence(activity=activity, status=discord.Status.online)
                self.logger.log_info("Bot started in active state")
                
                # Scan for current prisoners on startup
                await self._scan_for_prisoners()
                
                # Process only the MOST RECENT prisoner message on startup
                await self._process_recent_prisoner_messages()
                
                # Start presence rotation task
                if self.presence_rotation_task:
                    self.presence_rotation_task.cancel()
                self.presence_rotation_task = asyncio.create_task(self._rotate_presence())
            else:
                # Bot starts inactive - waiting for activation
                activity = discord.Activity(
                    type=discord.ActivityType.watching, name="💤 Inactive"
                )
                await self.change_presence(activity=activity, status=discord.Status.idle)
                self.logger.log_info("Bot started in INACTIVE state - waiting for /activate command", "⚠️")

        except discord.HTTPException as e:
            log_error("Failed to set startup status", exception=e)

    async def _handle_developer_commands(self, message: discord.Message) -> bool:
        """
        Handle developer-only commands (activate/deactivate).

        Args:
            message: Discord message

        Returns:
            True if message was a developer command
        """
        # Only developer can use commands
        if message.author.id != self.developer_id:
            return False

        content = message.content.lower()

        # Activate command
        if content == "/activate":
            self.is_active = True
            await message.add_reaction("✅")

            # Create status embed
            embed = EmbedBuilder.create_status_embed(
                status="Active",
                stats={
                    "prisoners": self.metrics.daily_responses,
                    "messages": self.metrics.messages_seen,
                    "confusion": random.randint(75, 95),
                },
                bot_avatar_url=self.user.avatar.url if self.user.avatar else None,
            )
            await message.reply(embed=embed)

            log_system_event(
                "bot_activated",
                "Bot activated by developer",
                {"developer_id": self.developer_id},
            )

            # Scan for current prisoners and update presence
            await self._scan_for_prisoners()
            await self._update_presence()
            return True

        # Deactivate command
        elif content == "/deactivate":
            self.is_active = False
            await message.add_reaction("🛑")

            # Create status embed
            embed = EmbedBuilder.create_status_embed(
                status="Inactive",
                stats={
                    "prisoners": self.metrics.daily_responses,
                    "messages": self.metrics.messages_seen,
                    "confusion": 0,
                },
                bot_avatar_url=self.user.avatar.url if self.user.avatar else None,
            )
            await message.reply(embed=embed)

            log_system_event(
                "bot_deactivated",
                "Bot deactivated by developer",
                {"developer_id": self.developer_id},
            )

            # Clear status when deactivated
            await self.change_presence(activity=None, status=discord.Status.idle)
            return True

        return False

    async def _should_respond_to_message(self, message: discord.Message) -> bool:
        """Always respond in prison channels when active."""
        # In prison channels, always respond when bot is active
        return True

    def _check_rate_limits(self, message: discord.Message) -> bool:
        """Simple rate limiting - 10 second cooldown for all channels."""
        now = datetime.datetime.now(timezone.utc)
        user_id = message.author.id

        # 10 second cooldown for all channels to prevent spam
        cooldown_seconds = 10

        # Check user cooldown
        if user_id in self.user_cooldowns:
            time_since_last = (now - self.user_cooldowns[user_id]).total_seconds()
            if time_since_last < cooldown_seconds:
                self.logger.log_debug(
                    f"⏱️ Rate limited user {user_id}",
                    context={
                        "user_id": str(user_id),
                        "time_since_last": f"{time_since_last:.1f}s",
                        "cooldown_required": f"{cooldown_seconds}s",
                        "remaining": f"{cooldown_seconds - time_since_last:.1f}s"
                    }
                )
                return False

        return True

    def _is_prison_channel(self, channel_name: str, channel_id: int) -> bool:
        """Check if channel is designated as prison channel."""
        # Check explicit prison channel from config FIRST
        prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
        if prison_channel_id:
            is_prison = str(channel_id) == str(prison_channel_id)
            if is_prison:
                return True

        # Check prison keywords in channel name as fallback
        prison_keywords = [
            "prison",
            "jail",
            "timeout",
            "punishment",
            "mute",
            "ban",
            "solitary",
            "cage",
            "cell",
        ]
        has_keyword = any(
            keyword in channel_name.lower() for keyword in prison_keywords
        )
        if has_keyword:
            self.logger.log_debug(
                f" Channel name '{channel_name}' contains prison keyword",
                context={"channel": channel_name, "has_keyword": True}
            )
        return has_keyword

    async def _add_message_to_batch(self, message: discord.Message):
        """Add message to batch for delayed processing."""
        user_id = message.author.id

        self.logger.log_debug(
            f" Adding message to batch - User: {message.author.display_name}, Channel: #{message.channel.name}",
            context={"user": message.author.display_name, "channel": message.channel.name, "action": "add_to_batch"}
        )

        # Initialize batch for new user
        if user_id not in self.message_batches:
            self.message_batches[user_id] = []

        # Add message to batch
        self.message_batches[user_id].append(message)
        self.logger.log_debug(
            f" Added message to batch for user {user_id}, batch size: {len(self.message_batches[user_id])}",
            context={"user_id": str(user_id), "batch_size": len(self.message_batches[user_id]), "action": "batch_updated"}
        )

        # Cancel existing timer
        if user_id in self.batch_timers:
            try:
                self.batch_timers[user_id].cancel()
                self.logger.log_debug(
                    f"Cancelled existing timer for user {user_id}",
                    context={"user_id": str(user_id), "action": "timer_cancelled"}
                )
            except Exception as e:
                self.logger.log_warning(
                    f"Failed to cancel timer for user {user_id}: {e}"
                )

        # Start new timer to process batch after delay
        self.batch_timers[user_id] = asyncio.create_task(
            self._process_batch_after_delay(user_id)
        )

    async def _process_batch_after_delay(self, user_id: int):
        """Process message batch after delay."""
        try:
            await asyncio.sleep(self.batch_delay)

            if user_id not in self.message_batches:
                return

            messages = self.message_batches[user_id]
            if not messages:
                return

            self.logger.log_debug(
                f" Processing batch of {len(messages)} messages for user {user_id}",
                context={"user_id": str(user_id), "message_count": len(messages), "action": "process_batch"}
            )

            # Clean up batch and timer
            del self.message_batches[user_id]
            if user_id in self.batch_timers:
                del self.batch_timers[user_id]

            # Process the batch with error handling
            try:
                await self._generate_and_send_response(messages)
            except Exception as e:
                log_error(
                    f"Failed to process message batch for user {user_id}",
                    exception=e,
                    context={
                        "message_count": len(messages),
                        "user_id": user_id,
                        "channel_id": messages[0].channel.id if messages else None,
                    },
                )

        except asyncio.CancelledError:
            # Task cancelled during shutdown - this is expected
            pass
        except Exception as e:
            log_error("Error processing message batch", exception=e)

    async def _generate_and_send_response(self, messages: List[discord.Message]):
        """Generate and send AI response to message batch."""
        if not self.ai_service:
            return

        try:
            # Use the last message as representative
            representative_message = messages[-1]

            # Combine message contents for context
            if len(messages) > 1:
                # Combine all messages into a single context
                combined_content = "\n".join([msg.content for msg in messages])
                self.logger.log_debug(
                    f"Combined {len(messages)} messages into single context",
                    context={"message_count": len(messages), "action": "combine_messages"}
                )
            else:
                combined_content = messages[0].content

            # Check if prison channel OR user has target role
            target_role_id = self.config.get("TARGET_ROLE_ID")
            user_has_role = False
            if target_role_id and hasattr(representative_message.author, "roles"):
                user_has_role = any(
                    role.id == int(target_role_id)
                    for role in representative_message.author.roles
                )
            is_prison = (
                self._is_prison_channel(
                    representative_message.channel.name,
                    representative_message.channel.id,
                )
                or user_has_role
            )

            # Check prison service features if available
            harassment_intensity = 1.0
            prisoner_status: dict[str, Any] = {}
            psychological_context: dict[str, Any] = {}
            
            if self.prison_service and is_prison:
                user_id = str(representative_message.author.id)
                username = representative_message.author.display_name
                
                # Get prisoner status
                prisoner_status = await self.prison_service.get_prisoner_status(user_id)
                
                # Check for solitary confinement
                in_solitary, severity = await self.prison_service.check_solitary_confinement(
                    user_id, username
                )
                
                # Track good behavior (quiet = good)
                is_quiet = len(messages) == 1 and len(combined_content) < 50
                await self.prison_service.track_good_behavior(user_id, username, is_quiet)
                
                # Calculate harassment intensity (reduction is inverse of intensity)
                harassment_reduction = self.prison_service.calculate_harassment_reduction(user_id)
                harassment_intensity = 2.0 - harassment_reduction  # Convert reduction to intensity
                
                self.logger.log_info(
                    f"Prison Status - User: {username}, Solitary: {in_solitary}, "
                    f"Intensity: {harassment_intensity:.2f}, Good Behavior: {prisoner_status.get('good_behavior_score', 0)}"
                )
            
            # Check psychological service features if available
            if self.psychological_service and is_prison:
                user_id = str(representative_message.author.id)
                username = representative_message.author.display_name
                
                # Get prisoner dossier
                dossier = await self.psychological_service.get_prisoner_dossier(user_id)
                
                # If no crimes tracked yet, try to extract mute reason from audit logs
                if not dossier.get('crimes'):
                    mute_data = await self.psychological_service.extract_mute_reason_from_audit(
                        representative_message.guild, user_id
                    )
                    if mute_data:
                        # Track the mute as a crime
                        await self.psychological_service.track_crime(user_id, username, {
                            'type': 'mute',
                            'description': f"Muted for: {mute_data.get('reason', 'Unknown reason')}",
                            'reason': mute_data.get('reason', 'Unknown reason'),
                            'muted_by': mute_data.get('muted_by', 'Unknown'),
                            'duration': mute_data.get('duration', 0),
                            'severity': 5
                        })
                        self.logger.log_info(
                            f"📝 Extracted mute reason for {username}: {mute_data.get('reason', 'Unknown')}"
                        )
                
                # Check for talking back (increase grudge)
                if any(word in combined_content.lower() for word in ['shut up', 'fuck off', 'leave me alone', 'stop']):
                    await self.psychological_service.add_grudge(user_id, username, "Talked back", severity=1)
                
                # Build/update psychological profile
                await self.psychological_service.build_psychological_profile(
                    user_id, username, [msg.content for msg in messages]
                )
                
                # Get grudge level
                grudge_level, grudge_desc = self.psychological_service.get_grudge_level(user_id)
                
                # Get the latest crime's duration if available
                mute_duration = 0
                if dossier.get('crimes'):
                    latest_crime = dossier['crimes'][-1]
                    mute_duration = latest_crime.get('mute_duration', 0)
                
                # Check if they're asking about their mute time
                remaining_time = None
                asks_about_mute: bool = any(word in combined_content.lower() for word in [
                    'when', 'mute', 'unmute', 'free', 'release', 'how long', 'how much',
                    'time left', 'get out', 'role gone', 'leave', 'escape', 'duration'
                ])
                
                if asks_about_mute and representative_message.guild:
                    remaining_time = await self.psychological_service.get_remaining_mute_time(
                        representative_message.guild, user_id
                    )
                    if remaining_time:
                        self.logger.log_info(
                            f"⏰ {username} asked about mute time: {remaining_time['formatted']} left"
                        )
                
                psychological_context = {
                    'crimes': dossier.get('crimes', [])[-3:],  # Last 3 crimes
                    'personality': dossier.get('profile', {}).get('personality_type', 'unknown'),
                    'triggers': dossier.get('profile', {}).get('triggers', []),
                    'grudge_level': grudge_level,
                    'grudge_description': grudge_desc,
                    'past_memories': dossier.get('memories', [])[-2:],  # Last 2 memorable conversations
                    'mute_duration': mute_duration,
                    'remaining_time': remaining_time
                }
                
                self.logger.log_info(
                    f"Psychological: {username} - Type: {psychological_context['personality']}, "
                    f"Grudge: {grudge_desc} ({grudge_level}/5)"
                )
            
            # Show typing indicator
            async with representative_message.channel.typing():
                # Generate AI response with prison context
                ai_response = await self.ai_service.generate_response(
                    combined_content,
                    representative_message.author.display_name,
                    representative_message.channel.name,
                    representative_message.channel.id,
                    (
                        representative_message.guild.id
                        if representative_message.guild
                        else None
                    ),
                    additional_context={
                        "is_prison": is_prison,
                        "batch_size": len(messages),
                        "user_id": representative_message.author.id,  # Pass actual user ID
                        "harassment_intensity": harassment_intensity,
                        "in_solitary": prisoner_status.get('in_solitary', False),
                        "solitary_level": prisoner_status.get('solitary_level', 0),
                        "good_behavior_score": prisoner_status.get('good_behavior_score', 0),
                        "escape_attempts": prisoner_status.get('escape_attempts', 0),
                        "psychological_profile": psychological_context,
                        "crimes": psychological_context.get('crimes', []),
                        "grudge_level": psychological_context.get('grudge_level', 0),
                        "personality_type": psychological_context.get('personality', 'unknown'),
                        "mute_duration": psychological_context.get('mute_duration', 0),
                        "remaining_time": psychological_context.get('remaining_time', None),
                        "asks_about_mute": asks_about_mute,
                    },
                )

                if not ai_response:
                    return

                # Apply prison channel special actions
                if is_prison:
                    await self._apply_prison_actions(representative_message)

                # Send response with error handling
                try:
                    await self._send_formatted_response(
                        representative_message, ai_response, is_prison
                    )
                    
                    # Remember significant conversations
                    if self.psychological_service and is_prison:
                        # Determine if this conversation is memorable
                        memory_type = "memorable"
                        if psychological_context.get('grudge_level', 0) > 0:
                            memory_type = "rebellious"
                        elif "please" in combined_content.lower() or "sorry" in combined_content.lower():
                            memory_type = "pathetic"
                        elif len(ai_response) > 200:  # Long response = probably funny
                            memory_type = "funny"
                        
                        # Save the conversation
                        await self.psychological_service.remember_conversation(
                            user_id,
                            username,
                            combined_content[:500],  # Limit message length
                            ai_response[:500],  # Limit response length
                            memory_type
                        )
                except Exception as e:
                    log_error(
                        "Failed to send AI response",
                        exception=e,
                        context={
                            "user_id": representative_message.author.id,
                            "channel_id": representative_message.channel.id,
                            "is_prison": is_prison,
                            "response_length": len(ai_response) if ai_response else 0,
                        },
                    )

                # Update metrics and cooldowns
                self._update_metrics_and_cooldowns(representative_message)

        except Exception as e:
            log_error("Failed to generate and send response", exception=e)

    async def _apply_prison_actions(self, message: discord.Message):
        """Apply special actions for prison channels."""
        try:
            # Status mocking
            if random.random() < 0.15:
                await self._update_mocking_status(message.author)

        except (discord.HTTPException, discord.Forbidden) as e:
            log_error("Error applying prison actions", exception=e)

    async def _send_formatted_response(
        self, message: discord.Message, response_text: str, is_prison: bool
    ):
        """Send formatted response with reactions."""
        try:
            # Send response (no embeds for Azab's responses - keep them raw)
            if is_prison:
                # Prison: Reply with mention
                await message.reply(
                    f"<@{message.author.id}> {response_text}", mention_author=True
                )
            else:
                # Normal: Just send to channel
                await message.channel.send(response_text)

            # Add reactions in prison channels
            if is_prison:
                prison_reactions = ["🤡", "🧢", "💀", "🙄", "😤", "🔥", "🗑️", "📉"]
                reaction_count = random.randint(1, 3)
                selected_reactions = random.sample(prison_reactions, reaction_count)

                for reaction in selected_reactions:
                    try:
                        await message.add_reaction(reaction)
                        await asyncio.sleep(0.5)
                    except discord.HTTPException:
                        # Reaction failed - likely missing permissions or message deleted
                        continue

        except (discord.HTTPException, discord.Forbidden, discord.NotFound) as e:
            log_error("Error sending formatted response", exception=e)

    def _update_metrics_and_cooldowns(self, message: discord.Message):
        """Update bot metrics and set cooldowns."""
        now = datetime.datetime.now(timezone.utc)

        # Update metrics
        self.metrics.responses_generated += 1
        self.metrics.daily_responses += 1

        # Set cooldowns
        self.user_cooldowns[message.author.id] = now
        self.channel_cooldowns[message.channel.id] = now

        # Clean old cooldowns
        if len(self.user_cooldowns) > 100:
            oldest_users = sorted(self.user_cooldowns.items(), key=lambda x: x[1])[:50]
            for user_id, _ in oldest_users:
                del self.user_cooldowns[user_id]

    async def _update_mocking_status(self, user: Union[discord.User, discord.Member]):
        """Update bot status to mock user."""
        try:
            mocking_statuses = [
                f"Watching {user.display_name} cry 😭",
                f"Listening to {user.display_name}'s screams 🔊",
                f"Breaking {user.display_name}'s spirit 💔",
                f"Enjoying {user.display_name}'s suffering 😂",
                f"Azab is confusing {user.display_name}",
                f"Teaching {user.display_name} about gardening",
                f"Discussing recipes with {user.display_name}",
            ]

            status_text = random.choice(mocking_statuses)
            activity = discord.Activity(
                type=discord.ActivityType.watching, name=status_text
            )
            await self.change_presence(activity=activity, status=discord.Status.online)

            self.logger.log_info(f"Set mocking status about {user.display_name}")

            # Reset status after 2-5 minutes
            asyncio.create_task(self._reset_status_later(random.randint(120, 300)))

        except Exception as e:
            log_error("Failed to update mocking status", exception=e)

    async def _reset_status_later(self, delay_seconds: int):
        """Reset bot status after delay."""
        await asyncio.sleep(delay_seconds)
        try:
            # Just go back to default presence
            await self._update_presence()
        except Exception as e:
            log_error("Failed to reset status", exception=e)

    def _format_bot_stats(self) -> str:
        """Format bot statistics for display."""
        uptime = datetime.datetime.now(timezone.utc) - self.metrics.uptime_start

        return f"""Bot Statistics:
Uptime: {uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds % 3600) // 60}m
Messages Seen: {self.metrics.messages_seen:,}
Responses Generated: {self.metrics.responses_generated:,}
Daily Responses: {self.metrics.daily_responses}
Commands Processed: {self.metrics.commands_processed:,}
Errors Handled: {self.metrics.errors_handled:,}
Guild Count: {len(self.guilds)}
Response Rate: {(self.metrics.responses_generated /
                 max(1, self.metrics.messages_seen)) * 100:.1f}%
"""

    async def get_health_status(self):
        """Get health status for health monitoring."""
        from src.services.base_service import HealthCheckResult, ServiceStatus
        
        try:
            # Check if bot is connected to Discord
            is_connected = self.is_ready() and not self.is_closed()
            
            # Calculate uptime
            uptime = datetime.datetime.now(timezone.utc) - self.metrics.uptime_start
            uptime_str = f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds % 3600) // 60}m"
            
            # Get service statuses
            services_healthy = []
            if self.ai_service:
                services_healthy.append("AI")
            if self.memory_service:
                services_healthy.append("Memory")
            if self.personality_service:
                services_healthy.append("Personality")
            if self.prison_service:
                services_healthy.append("Prison")
            
            # Determine overall status
            if is_connected and len(self.guilds) > 0:
                status = ServiceStatus.HEALTHY
                message = "Bot is running normally"
            elif is_connected:
                status = ServiceStatus.DEGRADED
                message = "Bot is connected but not in any guilds"
            else:
                status = ServiceStatus.UNHEALTHY
                message = "Bot is not connected to Discord"
            
            return HealthCheckResult(
                status=status,
                message=message,
                details={
                    "healthy": is_connected and len(self.guilds) > 0,
                    "connected": is_connected,
                    "guilds": len(self.guilds),
                    "users": sum(g.member_count for g in self.guilds),
                    "uptime": uptime_str,
                    "latency_ms": round(self.latency * 1000, 2),
                    "active": self.is_active,
                    "messages_seen": self.metrics.messages_seen,
                    "responses_generated": self.metrics.responses_generated,
                    "services": services_healthy,
                    "prisoners": len(self.current_prisoners)
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Error getting health status: {str(e)}",
                details={
                    "healthy": False,
                    "error": str(e),
                    "connected": False
                }
            )
    
    async def cleanup_task(self):
        """Periodic cleanup task."""
        try:
            # Clean old cooldowns
            now = datetime.datetime.now(timezone.utc)
            cutoff = now - datetime.timedelta(hours=1)

            # Clean user cooldowns
            old_users = [
                uid
                for uid, timestamp in self.user_cooldowns.items()
                if timestamp < cutoff
            ]
            for uid in old_users:
                del self.user_cooldowns[uid]

            # Clean channel cooldowns
            old_channels = [
                cid
                for cid, timestamp in self.channel_cooldowns.items()
                if timestamp < cutoff
            ]
            for cid in old_channels:
                del self.channel_cooldowns[cid]

            # Clean message batches and timers
            for user_id in list(self.batch_timers.keys()):
                timer = self.batch_timers[user_id]
                if timer and timer.done():
                    del self.batch_timers[user_id]
                    if user_id in self.message_batches:
                        del self.message_batches[user_id]

            self.logger.log_info("Performed periodic cleanup")

        except Exception as e:
            log_error("Error in cleanup task", exception=e)

    async def _generate_release_message(self, member: discord.Member) -> str:
        """Generate a personalized release message based on prisoner's history."""
        try:
            # Get AI service to generate personalized message
            if not self.ai_service:
                return f"🔓 {member.mention} has been released from prison. The guards got tired of you."
            
            # Get prisoner's psychological profile and conversation history
            conversation_summary = ""
            crime_summary = ""
            personality_info = ""
            
            # Try to get info from psychological service
            if self.psychological_service:
                try:
                    user_id = str(member.id)
                    dossier = await self.psychological_service.get_prisoner_dossier(user_id)
                    
                    # Get crimes
                    if dossier.get('crimes'):
                        crimes = dossier['crimes'][-3:]  # Last 3 crimes
                        crime_descriptions = [crime.get('description', crime.get('reason', 'Unknown')) for crime in crimes]
                        crime_summary = "Their crimes: " + ", ".join(crime_descriptions)
                    
                    # Get personality
                    if dossier.get('profile'):
                        profile = dossier['profile']
                        personality_info = f"Personality: {profile.get('personality_type', 'unknown')}"
                        if profile.get('triggers'):
                            personality_info += f", Triggers: {', '.join(profile['triggers'][:2])}"
                    
                    # Get memorable conversations
                    if dossier.get('memories'):
                        memories = dossier['memories'][-2:]  # Last 2 memorable conversations
                        if memories:
                            conversation_summary = "Their memorable quotes: " + " | ".join([
                                f'"{mem.get("message", "")[:40]}"' for mem in memories
                            ])
                    
                except Exception as e:
                    self.logger.log_warning(f"Could not fetch psychological profile: {e}")
            
            # Try to get conversation from prisoners database
            if not conversation_summary:
                try:
                    import sqlite3
                    conn = sqlite3.connect("data/prisoners.db")
                    cursor = conn.cursor()
                    
                    # Get recent conversations
                    cursor.execute("""
                        SELECT prisoner_message, azab_response 
                        FROM conversation_memories 
                        WHERE discord_id = ? 
                        ORDER BY created_at DESC 
                        LIMIT 3
                    """, (str(member.id),))
                    
                    recent_convos = cursor.fetchall()
                    conn.close()
                    
                    if recent_convos:
                        conversation_summary = "They said: " + " | ".join([
                            f'"{msg[0][:30]}"' for msg in recent_convos
                        ])
                        
                except Exception as e:
                    self.logger.log_warning(f"Could not fetch prisoner conversations: {e}")
            
            # Build context for AI
            context_info = f"""
Prisoner: {member.display_name}
{crime_summary}
{personality_info}
{conversation_summary}
""".strip()
            
            # If we have no info, mention it's their first time
            if not (crime_summary or personality_info or conversation_summary):
                context_info = f"Prisoner: {member.display_name} - First time prisoner, no history recorded"
            
            # Create the prompt for release message
            release_prompt = f"""You are a sarcastic prison guard announcing a prisoner's release.

{context_info}

Generate a SHORT (1-2 sentences max) release announcement that:
1. Is sarcastic and mocking based on what you know about them
2. References their specific crimes or behavior if known
3. Predicts they'll be back soon
4. Is funny but not too harsh

Keep it under 200 characters. Be specific to this person based on the context.
The prisoner is: {member.display_name}"""
            
            # Generate response using AI service
            response = await self.ai_service.generate_response(
                message_content=release_prompt,
                user_name="System",
                channel_name="release-announcement",
                channel_id=0,
                guild_id=member.guild.id if member.guild else None,
                additional_context={
                    "is_release_message": True,
                    "prisoner_name": member.display_name,
                    "context_info": context_info
                }
            )
            
            if response:
                # Add emoji and mention
                final_message = f"🔓 {member.mention} "
                
                # Clean up the response and add it
                response = response.replace(member.display_name, "").replace(member.mention, "").strip()
                final_message += response
                
                # Ensure it's not too long
                if len(final_message) > 300:
                    final_message = final_message[:297] + "..."
                    
                return final_message
            else:
                # Fallback if AI fails
                return f"🔓 {member.mention} has been released. The guards needed a break from your nonsense."
            
        except Exception as e:
            self.logger.log_error(f"Failed to generate AI release message: {e}")
            # Fallback to a simple message if AI fails
            fallback_messages = [
                f"🔓 {member.mention} has been released. The guards got tired of you.",
                f"🔓 {member.mention} is free... for now. We know you'll be back.",
                f"🔓 {member.mention} has been released. Even Sednaya couldn't handle you.",
                f"🔓 {member.mention} escaped... just kidding, we let you go. See you soon.",
            ]
            import random
            return random.choice(fallback_messages)

    async def _rotate_presence(self):
        """Rotate presence between prisoners or show default."""
        # Log presence rotation start
        from src.utils.tree_log import log_perfect_tree_section
        rotation_items = [
            ("interval", "Every 10 seconds"),
            ("status", "Active rotation"),
            ("prisoners", str(len(self.current_prisoners)) if self.current_prisoners else "0")
        ]
        log_perfect_tree_section("Presence Rotation", rotation_items, emoji="🔄")
        
        while True:
            try:
                await asyncio.sleep(10)  # Rotate every 10 seconds
                if self.is_active:
                    await self._update_presence()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_warning(f"Error in presence rotation: {e}")
                await asyncio.sleep(30)  # Wait longer on error

    async def _update_presence(self):
        """Update bot presence based on current prisoners."""
        try:
            if not self.is_active:
                return

            if self.current_prisoners:
                # Clean up prisoners who are no longer in any guild
                valid_prisoners = []
                for prisoner_name in self.current_prisoners:
                    # Check if this user is still in any guild
                    member_exists = False
                    for guild in self.guilds:
                        if discord.utils.get(guild.members, display_name=prisoner_name):
                            member_exists = True
                            break
                    
                    if member_exists:
                        valid_prisoners.append(prisoner_name)
                    else:
                        # Use tree logging for prisoner removal
                        from src.utils.tree_log import log_status
                        log_status(f"Removing {prisoner_name} from presence (not in server)", emoji="🧹")
                
                # Update the current_prisoners set
                self.current_prisoners = set(valid_prisoners)
                
                if valid_prisoners:
                    # Rotate between valid prisoners
                    self.presence_index = self.presence_index % len(valid_prisoners)
                    prisoner_name = valid_prisoners[self.presence_index]

                    activity = discord.Activity(
                        type=discord.ActivityType.playing, name=f"with {prisoner_name}"
                    )
                    await self.change_presence(activity=activity, status=discord.Status.online)

                    self.presence_index += 1
                    # Use tree logging for presence updates
                    from src.utils.tree_log import log_status
                    log_status(f"Updated presence: Playing with {prisoner_name}", emoji="🎮")
                    return
            
            # If we get here, either no prisoners or all were invalid
            # Default presence when no prisoners
            activity = discord.Activity(
                type=discord.ActivityType.watching, name="⛓ Sednaya"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
            # Use tree logging for default presence
            from src.utils.tree_log import log_status
            log_status("Updated presence: Watching ⛓ Sednaya", emoji="👁️")

        except Exception as e:
            log_error("Failed to update presence", exception=e)

    async def _scan_for_prisoners(self):
        """Scan prison channel for current prisoners."""
        try:
            prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
            target_role_id = self.config.get("TARGET_ROLE_ID")

            if not prison_channel_id or not target_role_id:
                return

            # Find the prison channel in any guild
            for guild in self.guilds:
                channel = guild.get_channel(int(prison_channel_id))
                if channel:
                    # Clear and rebuild prisoner list
                    self.current_prisoners.clear()

                    # Check all members in the channel
                    for member in channel.members:
                        if any(
                            str(role.id) == str(target_role_id) for role in member.roles
                        ):
                            self.current_prisoners.add(member.display_name)

                    if self.current_prisoners:
                        # Use enhanced tree logging for prisoner scan
                        from src.utils.tree_log import log_enhanced_tree_section_global as log_enhanced_tree_section
                        import time
                        
                        scan_start = time.perf_counter()
                        prisoner_items = [
                            ("count", str(len(self.current_prisoners))),
                            ("prisoners", ", ".join(self.current_prisoners)),
                            ("channel", prison_channel_id)
                        ]
                        
                        performance_metrics = {
                            "scan_time_ms": round((time.perf_counter() - scan_start) * 1000, 2),
                            "prisoners_found": len(self.current_prisoners),
                            "guilds_scanned": len(self.guilds)
                        }
                        
                        context_data = {
                            "target_role_id": target_role_id,
                            "prison_channel_id": prison_channel_id,
                            "scan_timestamp": str(datetime.datetime.now())
                        }
                        
                        log_enhanced_tree_section("Prisoner Scan", prisoner_items, 
                                                performance_metrics=performance_metrics,
                                                context_data=context_data, emoji="🔍")
                    break

        except Exception as e:
            log_error("Failed to scan for prisoners", exception=e)
    
    async def _process_recent_prisoner_messages(self):
        """Process recent messages from current prisoners upon activation."""
        try:
            prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
            target_role_id = self.config.get("TARGET_ROLE_ID")
            
            if not prison_channel_id or not target_role_id:
                return
            
            # Use enhanced tree logging for message checking
            from src.utils.tree_log import log_enhanced_tree_section_global as log_enhanced_tree_section
            import time
            
            check_start = time.perf_counter()
            check_items = [
                ("action", "Scanning for recent messages"),
                ("channel", prison_channel_id),
                ("timeframe", "Last 24 hours"),
                ("target", "Unanswered prisoner messages")
            ]
            
            performance_metrics = {
                "check_time_ms": round((time.perf_counter() - check_start) * 1000, 2),
                "messages_scanned": 0,  # Will be updated during scan
                "bot_responses_found": 0  # Will be updated during scan
            }
            
            context_data = {
                "prison_channel_id": prison_channel_id,
                "target_role_id": target_role_id,
                "scan_limit": 100
            }
            
            log_enhanced_tree_section("Message Check", check_items, 
                                    performance_metrics=performance_metrics,
                                    context_data=context_data, emoji="🔍")
            
            # Find the prison channel
            prison_channel = None
            for guild in self.guilds:
                channel = guild.get_channel(int(prison_channel_id))
                if channel:
                    prison_channel = channel
                    break
            
            if not prison_channel:
                return
            
            # Fetch recent messages (last 50 messages or 24 hours)
            messages_to_process = []
            bot_responses = set()  # Track messages the bot has responded to
            
            # First pass: collect bot's response message references
            async for message in prison_channel.history(limit=100):
                if message.author == self.user and message.reference:
                    # This is a bot reply - store the message it replied to
                    bot_responses.add(message.reference.message_id)
            
            # Second pass: find prisoner messages that haven't been responded to
            async for message in prison_channel.history(limit=50):
                # Skip bot messages
                if message.author.bot:
                    continue
                
                # Skip if bot already responded to this message
                if message.id in bot_responses:
                    self.logger.log_debug(
                        f"Skipping message from {message.author.display_name} - already responded",
                        context={"message_id": str(message.id), "author": message.author.display_name}
                    )
                    continue
                    
                # Get the member object to check current roles
                member = prison_channel.guild.get_member(message.author.id)
                if not member:
                    continue
                    
                # Check if author CURRENTLY has the muted role
                if hasattr(member, 'roles'):
                    has_muted_role = any(
                        str(role.id) == str(target_role_id) 
                        for role in member.roles
                    )
                    
                    if has_muted_role:
                        # Check if message is recent (within last 24 hours)
                        time_diff = discord.utils.utcnow() - message.created_at
                        if time_diff.total_seconds() < 86400:  # 24 hours
                            messages_to_process.append(message)
            
            # Only respond to the SINGLE most recent prisoner message
            most_recent_message = None
            for msg in messages_to_process:
                # Check if there's a bot message after this one (conversation already happened)
                has_bot_reply_after = False
                async for check_msg in prison_channel.history(limit=10, after=msg):
                    if check_msg.author == self.user:
                        # Bot sent a message after this - likely already had a conversation
                        has_bot_reply_after = True
                        break
                
                if has_bot_reply_after:
                    self.logger.log_debug(
                        f"Skipping {msg.author.display_name}'s message - bot already active in conversation after",
                        context={"message_id": str(msg.id)}
                    )
                    continue
                
                # Keep only the most recent unanswered message overall
                if not most_recent_message or msg.created_at > most_recent_message.created_at:
                    most_recent_message = msg
            
            if most_recent_message:
                # Use tree logging for message processing
                from src.utils.tree_log import log_perfect_tree_section, log_status
                message_items = [
                    ("found", "1 recent prisoner message"),
                    ("author", most_recent_message.author.display_name),
                    ("content", most_recent_message.content[:50] + "..." if len(most_recent_message.content) > 50 else most_recent_message.content),
                    ("timestamp", str(most_recent_message.created_at))
                ]
                log_perfect_tree_section("Message Processing", message_items, emoji="📨")
                
                # Process only the most recent prisoner message
                message = most_recent_message
                try:
                    # Add a small delay before responding
                    await asyncio.sleep(2)
                    
                    # Log processing
                    log_status(f"Processing message from {message.author.display_name}", emoji="💬")
                    
                    # Add to batch for processing
                    await self._add_message_to_batch(message)
                    
                except Exception as e:
                    self.logger.log_error(f"Failed to process message from {message.author}: {e}")
            else:
                # Use tree logging for no messages found
                from src.utils.tree_log import log_perfect_tree_section
                no_message_items = [
                    ("result", "No unanswered messages found"),
                    ("scan_complete", "All messages processed"),
                    ("status", "Ready for new interactions")
                ]
                log_perfect_tree_section("Message Check Result", no_message_items, emoji="✅")
                
        except Exception as e:
            self.logger.log_error(f"Error processing recent prisoner messages: {e}")

    async def close(self):
        """Clean shutdown of the bot."""
        try:
            # Cancel presence rotation task
            if self.presence_rotation_task and not self.presence_rotation_task.done():
                self.presence_rotation_task.cancel()

            # Cancel background tasks
            if hasattr(self, "cleanup_task") and hasattr(self.cleanup_task, "cancel"):
                self.cleanup_task.cancel()

            # Cancel message batch timers
            for timer in self.batch_timers.values():
                if timer and not timer.done():
                    timer.cancel()

            # Log final stats
            uptime = datetime.datetime.now(timezone.utc) - self.metrics.uptime_start
            log_system_event(
                "bot_shutdown",
                "Bot shutting down",
                {
                    "uptime_seconds": uptime.total_seconds(),
                    "messages_seen": self.metrics.messages_seen,
                    "responses_generated": self.metrics.responses_generated,
                },
            )

            await super().close()

        except Exception as e:
            log_error("Error during bot shutdown", exception=e)
