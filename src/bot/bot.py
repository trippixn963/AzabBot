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

        super().__init__(intents=intents)

        # Configuration and services
        self.config = config
        self.logger = get_logger()
        self.ai_service: Optional[AIService] = None
        self.health_monitor: Optional[HealthMonitor] = None

        # Bot metrics and state
        self.metrics = BotMetrics()

        # Rate limiting and cooldowns
        self.user_cooldowns: Dict[int, datetime.datetime] = {}
        self.channel_cooldowns: Dict[int, datetime.datetime] = {}

        # Message batching for better response quality
        self.message_batches: Dict[int, Dict[str, Any]] = {}
        self.batch_delay = 3.0  # seconds

        # Bot state
        self.is_active = False  # Bot starts deactivated
        self.developer_id = config.get("developer_id")  # Developer from config
        if not self.developer_id:
            raise ValueError("DEVELOPER_ID must be set in configuration")

        # Fixed feature settings (not configurable)
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

            # Start background tasks
            self.cleanup_task.start()

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
            # Handle developer commands first (always works, even when deactivated)
            if await self._handle_developer_commands(message):
                return

            # If bot is not active, ignore all other messages
            if not self.is_active:
                return

            # Check if this is a prison channel
            if not self._is_prison_channel(message.channel.name, message.channel.id):
                return

            # Check rate limits (1 minute cooldown per user)
            if not self._check_rate_limits(message):
                return

            # Process message immediately (no batching needed)
            await self._generate_and_send_response([message])

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
            "Feature Flags": [
                ("rage_gifs", self.enable_rage_gifs),
                ("identity_theft", self.enable_identity_theft),
                ("nickname_changes", self.enable_nickname_changes),
                ("micro_timeouts", self.enable_micro_timeouts),
            ]
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
            # Set initial idle status (bot starts deactivated)
            await self.change_presence(activity=None, status=discord.Status.idle)
            self.logger.log_info("Bot started in deactivated state")

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

            # Set status
            activity = discord.Activity(
                type=discord.ActivityType.watching, name="prisoners suffer"
            )
            await self.change_presence(activity=activity, status=discord.Status.dnd)
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

            # Clear status
            await self.change_presence(activity=None, status=discord.Status.idle)
            return True

        return False

    async def _should_respond_to_message(self, message: discord.Message) -> bool:
        """Always respond in prison channels when active."""
        # In prison channels, always respond when bot is active
        return True

    def _check_rate_limits(self, message: discord.Message) -> bool:
        """Simple rate limiting - 1 minute cooldown per user."""
        now = datetime.datetime.now(timezone.utc)
        user_id = message.author.id

        # Check user cooldown (1 minute)
        if user_id in self.user_cooldowns:
            time_since_last = (now - self.user_cooldowns[user_id]).total_seconds()
            if time_since_last < 60:  # 60 seconds cooldown
                return False

        return True

    def _is_prison_channel(self, channel_name: str, channel_id: int) -> bool:
        """Check if channel is designated as prison channel."""
        # Check prison keywords in channel name
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
        if any(keyword in channel_name.lower() for keyword in prison_keywords):
            return True

        # Check explicit prison channel list from config
        prison_channels = self.config.get("prison_channel_ids", [])
        return str(channel_id) in prison_channels

    async def _add_message_to_batch(self, message: discord.Message, security_context):
        """Add message to batch for delayed processing."""
        user_id = message.author.id

        # Initialize batch for new user
        if user_id not in self.message_batches:
            self.message_batches[user_id] = {
                "messages": [],
                "timer": None,
                "security_context": security_context,
            }

        # Add message to batch
        self.message_batches[user_id]["messages"].append(message)

        # Cancel existing timer
        if self.message_batches[user_id]["timer"]:
            self.message_batches[user_id]["timer"].cancel()

        # Start new timer
        self.message_batches[user_id]["timer"] = asyncio.create_task(
            self._process_batch_after_delay(user_id)
        )

    async def _process_batch_after_delay(self, user_id: int):
        """Process message batch after delay."""
        try:
            await asyncio.sleep(self.batch_delay)

            if user_id not in self.message_batches:
                return

            batch_data = self.message_batches[user_id]
            messages = batch_data["messages"]
            security_context = batch_data["security_context"]

            if not messages:
                return

            # Clean up batch
            del self.message_batches[user_id]

            # Process the batch
            await self._generate_and_send_response(messages, security_context)

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
                combined_content = "\n".join(
                    [f"Message {i+1}: {msg.content}" for i, msg in enumerate(messages)]
                )
            else:
                combined_content = messages[0].content

            # Check if prison channel
            is_prison = self._is_prison_channel(
                representative_message.channel.name, representative_message.channel.id
            )

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

                # Send response
                await self._send_formatted_response(
                    representative_message, ai_response, is_prison
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

    # @tasks.loop(hours=1)  # Removed tasks import since it's not used
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

            # Clean message batches
            for user_id in list(self.message_batches.keys()):
                batch = self.message_batches[user_id]
                if batch["timer"] and batch["timer"].done():
                    del self.message_batches[user_id]

            self.logger.log_info("Performed periodic cleanup")

        except Exception as e:
            log_error("Error in cleanup task", exception=e)

    async def close(self):
        """Clean shutdown of the bot."""
        try:
            # Cancel background tasks
            if hasattr(self, "cleanup_task"):
                self.cleanup_task.cancel()

            # Cancel message batch timers
            for batch_data in self.message_batches.values():
                if batch_data["timer"]:
                    batch_data["timer"].cancel()

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
