# =============================================================================
# SaydnayaBot - Main Bot Module
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
from typing import Any, Dict, List, Optional

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


class SaydnayaBot(discord.Client):
    """
    Main bot class implementing the SaydnayaBot Discord client.

    This bot provides AI-powered responses with different modes for different
    channel types, including enhanced harassment capabilities for designated
    prison channels.

    The bot is built using a service-oriented architecture with proper
    dependency injection, health monitoring, and comprehensive logging.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the SaydnayaBot.

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
        self.name = "SaydnayaBot"  # Service identifier
        self.ai_service: Optional[AIService] = None
        self.health_monitor: Optional[HealthMonitor] = None

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
        self.is_active = True  # Bot is always active
        self.prison_mode = True  # Prison mode enabled by default
        self.developer_id = config.get("DEVELOPER_ID")  # Developer from config
        if not self.developer_id:
            raise ValueError("DEVELOPER_ID must be set in configuration")
        
        # Presence management
        self.current_prisoners = set()  # Track prisoners in jail
        self.presence_rotation_task = None
        self.presence_index = 0

        # Bot behavior settings
        self.response_probability = 0.7  # High probability for prison channels

        self.logger.log_info("SaydnayaBot initialized", "🤖")

    async def setup_hook(self):
        """Set up the bot after login but before ready event."""
        try:
            # Resolve services from DI container
            self.ai_service = await resolve("AIService")
            self.health_monitor = await resolve("HealthMonitor")

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
            from src.bot.commands import create_activate_command, create_deactivate_command, create_status_command
            
            self.tree.add_command(create_activate_command(self))
            self.tree.add_command(create_deactivate_command(self))
            self.tree.add_command(create_status_command(self))
            
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
        # Ignore bot messages
        if message.author.bot:
            return

        # Update metrics
        self.metrics.messages_seen += 1

        try:
            # Debug logging
            self.logger.log_info(
                f"DEBUG: 📥 Message received from {message.author} in #{message.channel.name}"
            )
            
            # Handle developer commands first (always works, even when deactivated)
            if await self._handle_developer_commands(message):
                return

            # Bot is always active - removed activation check

            # Check if user has the target role from config
            target_role_id = self.config.get("TARGET_ROLE_ID")
            user_has_role = False
            if target_role_id:
                if hasattr(message.author, 'roles'):
                    user_has_role = any(str(role.id) == str(target_role_id) for role in message.author.roles)
                    self.logger.log_info(
                        f"DEBUG: User roles: {[role.id for role in message.author.roles]}, Target role: {target_role_id}, Has role: {user_has_role}"
                    )
            
            # Check if this is a prison channel
            is_prison_channel = self._is_prison_channel(message.channel.name, message.channel.id)
            self.logger.log_info(
                f"DEBUG: Channel ID: {message.channel.id}, Is prison channel: {is_prison_channel}"
            )
            
            # Bot only responds if: user has target role AND in prison channel
            if not (is_prison_channel and user_has_role):
                self.logger.log_info(
                    f"DEBUG: Conditions not met - Prison channel: {is_prison_channel}, Has role: {user_has_role}"
                )
                return
            
            self.logger.log_info("DEBUG: ✅ All conditions met, processing message")

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
                        "message_content": message.content[:100]
                    }
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

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member updates to detect new prisoners."""
        try:
            # Debug logging for member updates
            self.logger.log_info(
                f"DEBUG: Member update detected - {after.display_name} (ID: {after.id})"
            )
            
            # Bot is always active - no need to check
            
            # Get the target role ID from config
            target_role_id = self.config.get("TARGET_ROLE_ID")
            if not target_role_id:
                self.logger.log_warning("No TARGET_ROLE_ID configured, cannot detect prisoners")
                return
            
            # Check if member just got the muted role
            had_role = any(str(role.id) == str(target_role_id) for role in before.roles)
            has_role = any(str(role.id) == str(target_role_id) for role in after.roles)
            
            self.logger.log_info(
                f"DEBUG: Role check - Had role: {had_role}, Has role: {has_role}, Target: {target_role_id}"
            )
            
            # If they just got the muted role
            if not had_role and has_role:
                self.logger.log_info(f"🚨 New prisoner detected: {after.display_name} just got muted!")
                
                # Add to current prisoners set
                self.current_prisoners.add(after.display_name)
                
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
                        context={"guild_id": after.guild.id, "user_id": after.id}
                    )
                    return
                
                # Wait a moment for them to be moved to the channel
                await asyncio.sleep(2)
                
                # Check if this is a returning prisoner using memory service
                is_returning = False
                previous_visits = 0
                
                # Try to check user history
                try:
                    # Check database for previous interactions
                    import sqlite3
                    conn = sqlite3.connect("data/memory.db")
                    cursor = conn.cursor()
                    cursor.execute("SELECT total_interactions FROM user_memories WHERE user_id = ?", (str(after.id),))
                    result = cursor.fetchone()
                    conn.close()
                    
                    if result and result[0] > 0:
                        is_returning = True
                        previous_visits = result[0]
                        self.logger.log_info(f"🔄 RETURNING PRISONER: {after.display_name} has {previous_visits} previous interactions!")
                except Exception as e:
                    self.logger.log_warning(f"Could not check prisoner history: {e}")
                
                # Generate appropriate message based on history
                if is_returning:
                    # Messages for returning prisoners - mention their history!
                    returning_messages = [
                        f"LOOK WHO'S BACK! {after.mention}, this is your {previous_visits + 1}th visit to Sednaya. You never learn, do you?",
                        f"{after.mention} AGAIN?! I KNEW you'd be back. What did you do this time?",
                        f"Welcome back to Sednaya, {after.mention}! Missed me? I still remember everything from last time...",
                        f"Hahaha {after.mention} returns! Visit number {previous_visits + 1}. You're becoming a regular!",
                        f"Oh {after.mention}, back so soon? I was just telling someone about you. Same cell as before?",
                        f"{after.mention} can't stay away! This is what, your {previous_visits + 1}th time here? What's your excuse now?",
                        f"I TOLD YOU that you'd be back, {after.mention}! Welcome home to Sednaya, again.",
                    ]
                    message = random.choice(returning_messages)
                else:
                    # Messages for first-time prisoners
                    welcome_messages = [
                        f"Well well well, look who just joined us. Welcome to your new home, {after.mention}.",
                        f"Fresh meat! {after.mention}, hope you're ready for your stay here.",
                        f"{after.mention} Welcome to Sednaya! What did you do to end up here?",
                        f"Another one! {after.mention}, tell me - what rule did you break?",
                        f"Oh {after.mention}, you're here now? This should be interesting...",
                        f"New arrival! {after.mention}, confess your crimes immediately.",
                        f"{after.mention} just got locked up! Time to learn about gardening and cooking.",
                    ]
                    message = random.choice(welcome_messages)
                try:
                    await channel.send(message)
                    self.logger.log_info(
                        f"✅ Sent welcome message to new prisoner {after.display_name} in #{channel.name}"
                    )
                except discord.Forbidden:
                    log_error(
                        "No permission to send message in prison channel",
                        context={"channel_id": channel.id, "channel_name": channel.name}
                    )
                except discord.HTTPException as e:
                    log_error(
                        "Failed to send welcome message",
                        exception=e,
                        context={"user_id": after.id, "channel_id": channel.id}
                    )
                
                # Log the event
                log_system_event(
                    "new_prisoner",
                    f"New prisoner detected: {after.display_name}",
                    {"user_id": after.id, "username": after.display_name}
                )
            
            # If they just got unmuted (role removed)
            elif had_role and not has_role:
                self.logger.log_info(f"🔓 Prisoner released: {after.display_name} was unmuted")
                
                # Remove from current prisoners set
                self.current_prisoners.discard(after.display_name)
                
                # Find the prison channel to announce release
                prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
                if prison_channel_id:
                    channel = after.guild.get_channel(int(prison_channel_id))
                    if channel:
                        release_messages = [
                            f"{after.display_name} has been released. They survived... this time.",
                            f"Prisoner {after.display_name} served their time. Don't come back!",
                            f"{after.display_name} is free to go. We'll miss the entertainment.",
                        ]
                        await channel.send(random.choice(release_messages))
                
        except Exception as e:
            log_error(
                "Error in on_member_update event",
                exception=e,
                context={
                    "before_user": before.display_name if before else "Unknown",
                    "after_user": after.display_name if after else "Unknown",
                    "guild_id": after.guild.id if after and after.guild else None,
                }
            )

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
        features = {
            "Feature Flags": []
        }

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
            # Set initial online status with default presence
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name="⛓ Sednaya"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
            self.logger.log_info("Bot started in active state")
            
            # Scan for current prisoners on startup
            await self._scan_for_prisoners()
            
            # Start presence rotation task
            if self.presence_rotation_task:
                self.presence_rotation_task.cancel()
            self.presence_rotation_task = asyncio.create_task(self._rotate_presence())

        except Exception as e:
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
                self.logger.log_info(
                    f"DEBUG: Rate limited - User {user_id} cooldown: {time_since_last:.1f}s < {cooldown_seconds}s"
                )
                return False

        return True

    def _is_prison_channel(self, channel_name: str, channel_id: int) -> bool:
        """Check if channel is designated as prison channel."""
        # Check explicit prison channel from config FIRST
        prison_channel_id = self.config.get("PRISON_CHANNEL_IDS", "")
        self.logger.log_info(
            f"DEBUG: Prison channel from config: {prison_channel_id}, Type: {type(prison_channel_id)}"
        )
        if prison_channel_id:
            is_prison = str(channel_id) == str(prison_channel_id)
            self.logger.log_info(
                f"DEBUG: Checking prison channel: {prison_channel_id}, Current: {channel_id}, Match: {is_prison}"
            )
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
        has_keyword = any(keyword in channel_name.lower() for keyword in prison_keywords)
        if has_keyword:
            self.logger.log_info(f"DEBUG: Channel name '{channel_name}' contains prison keyword")
        return has_keyword

    async def _add_message_to_batch(self, message: discord.Message):
        """Add message to batch for delayed processing."""
        user_id = message.author.id
        
        self.logger.log_info(
            f"DEBUG: Adding message to batch - User: {message.author.display_name}, Channel: #{message.channel.name}"
        )

        # Initialize batch for new user
        if user_id not in self.message_batches:
            self.message_batches[user_id] = []

        # Add message to batch
        self.message_batches[user_id].append(message)
        self.logger.log_info(f"DEBUG: Added message to batch for user {user_id}, batch size: {len(self.message_batches[user_id])}")

        # Cancel existing timer
        if user_id in self.batch_timers:
            try:
                self.batch_timers[user_id].cancel()
                self.logger.log_info(f"DEBUG: Cancelled existing timer for user {user_id}")
            except Exception as e:
                self.logger.log_warning(f"Failed to cancel timer for user {user_id}: {e}")

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

            self.logger.log_info(f"DEBUG: Processing batch of {len(messages)} messages for user {user_id}")

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
                        "channel_id": messages[0].channel.id if messages else None
                    }
                )

        except asyncio.CancelledError:
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
                self.logger.log_info(f"DEBUG: Combined {len(messages)} messages into single context")
            else:
                combined_content = messages[0].content

            # Check if prison channel OR user has target role
            target_role_id = self.config.get("TARGET_ROLE_ID")
            user_has_role = False
            if target_role_id and hasattr(representative_message.author, 'roles'):
                user_has_role = any(role.id == int(target_role_id) for role in representative_message.author.roles)
            is_prison = self._is_prison_channel(
                representative_message.channel.name, representative_message.channel.id
            ) or user_has_role

            # Show typing indicator
            async with representative_message.channel.typing():
                # Generate AI response
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
                except Exception as e:
                    log_error(
                        "Failed to send AI response",
                        exception=e,
                        context={
                            "user_id": representative_message.author.id,
                            "channel_id": representative_message.channel.id,
                            "is_prison": is_prison,
                            "response_length": len(ai_response) if ai_response else 0
                        }
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

        except Exception as e:
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
                        pass

        except Exception as e:
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

    async def _update_mocking_status(self, user: discord.Member):
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
            await self.change_presence(activity=activity, status=discord.Status.dnd)

            self.logger.log_info(f"Set mocking status about {user.display_name}")

            # Reset status after 2-5 minutes
            asyncio.create_task(self._reset_status_later(random.randint(120, 300)))

        except Exception as e:
            log_error("Failed to update mocking status", exception=e)

    async def _reset_status_later(self, delay_seconds: int):
        """Reset bot status after delay."""
        await asyncio.sleep(delay_seconds)
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching, name="prisoners suffer"
            )
            await self.change_presence(activity=activity, status=discord.Status.online)
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

    async def _rotate_presence(self):
        """Rotate presence between prisoners or show default."""
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
                # Rotate between prisoners
                prisoners_list = list(self.current_prisoners)
                self.presence_index = self.presence_index % len(prisoners_list)
                prisoner_name = prisoners_list[self.presence_index]
                
                activity = discord.Activity(
                    type=discord.ActivityType.playing,
                    name=f"with {prisoner_name}"
                )
                await self.change_presence(activity=activity, status=discord.Status.dnd)
                
                self.presence_index += 1
                self.logger.log_info(f"Updated presence: Playing with {prisoner_name}")
            else:
                # Default presence when no prisoners
                activity = discord.Activity(
                    type=discord.ActivityType.watching,
                    name="⛓ Sednaya"
                )
                await self.change_presence(activity=activity, status=discord.Status.dnd)
                self.logger.log_info("Updated presence: Watching ⛓ Sednaya")
                
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
                        if any(str(role.id) == str(target_role_id) for role in member.roles):
                            self.current_prisoners.add(member.display_name)
                    
                    if self.current_prisoners:
                        self.logger.log_info(
                            f"Found {len(self.current_prisoners)} prisoners in jail: {', '.join(self.current_prisoners)}"
                        )
                    break
                    
        except Exception as e:
            log_error("Failed to scan for prisoners", exception=e)

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
