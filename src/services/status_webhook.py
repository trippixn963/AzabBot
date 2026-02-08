"""
Unified Status Webhook Service
==============================

Sends bot status notifications to Discord webhooks with:
- Hourly status reports with health info
- Startup/shutdown alerts
- System resource monitoring
- Optional: latency/voice alerts, recovery notifications

Usage:
    from src.services.status_webhook import get_status_service

    # In setup_hook:
    status_service = get_status_service(webhook_url, bot_name="MyBot")
    status_service.set_bot(bot)
    await status_service.start_hourly_alerts()

    # In on_ready:
    await status_service.send_startup_alert()

    # In close:
    await status_service.send_shutdown_alert()
    status_service.stop_hourly_alerts()

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import aiohttp
import psutil

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

NY_TZ = ZoneInfo("America/New_York")

# Colors
COLOR_ONLINE = 0x00FF00   # Green
COLOR_OFFLINE = 0xFF0000  # Red
COLOR_WARNING = 0xFFAA00  # Orange

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds

# Thresholds
LATENCY_THRESHOLD_MS = 500

# Alert throttling (seconds)
LATENCY_THROTTLE_SECONDS = 600
VOICE_THROTTLE_SECONDS = 300

# Progress bar settings
PROGRESS_BAR_WIDTH = 10


# =============================================================================
# Helper Functions
# =============================================================================

def _create_progress_bar(value: float, max_val: float = 100, width: int = PROGRESS_BAR_WIDTH) -> str:
    """Create a Unicode progress bar."""
    if max_val <= 0:
        return "░" * width

    ratio = min(value / max_val, 1.0)
    filled = int(ratio * width)
    empty = width - filled
    return "█" * filled + "░" * empty


# =============================================================================
# Status Webhook Service
# =============================================================================

class StatusWebhookService:
    """Sends hourly status embeds to Discord webhook."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        bot_name: str = "Bot",
        logging_webhook_url: Optional[str] = None,
    ) -> None:
        """
        Initialize the status webhook service.

        Args:
            webhook_url: Discord webhook URL for status updates
            bot_name: Name of the bot (used in embed titles)
            logging_webhook_url: Optional separate webhook for alerts
        """
        self.webhook_url = webhook_url or os.getenv("STATUS_WEBHOOK_URL") or os.getenv("STATUS_WEBHOOK")
        self._logging_webhook_url = logging_webhook_url or os.getenv("LOG_WEBHOOK_URL")
        self.bot_name = bot_name
        self.enabled = bool(self.webhook_url)

        self._hourly_task: Optional[asyncio.Task] = None
        self._bot: Optional[Any] = None
        self._start_time: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # State tracking for alerts
        self._last_latency_alert_time: Optional[datetime] = None
        self._last_voice_disconnect_time: Optional[datetime] = None
        self._latency_degraded: bool = False
        self._voice_degraded: bool = False

        if self.enabled:
            logger.tree("Status Webhook", [
                ("Status", "Enabled"),
                ("Bot", bot_name),
                ("Schedule", "Every hour (NY time)"),
            ], emoji="🔔")
        else:
            logger.tree("Status Webhook", [
                ("Status", "Disabled"),
                ("Reason", "No webhook URL provided"),
            ], emoji="🔕")

    def set_bot(self, bot: Any) -> None:
        """Set bot reference for stats."""
        self._bot = bot
        if self._start_time is None:
            self._start_time = datetime.now(NY_TZ)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create persistent HTTP session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,
                limit_per_host=5,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    async def close(self) -> None:
        """Close HTTP session on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _get_uptime(self) -> str:
        """Get formatted uptime string."""
        if not self._start_time:
            return "`0m`"

        now = datetime.now(NY_TZ)
        delta = now - self._start_time
        total_seconds = int(delta.total_seconds())

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"`{days}d {hours}h {minutes}m`"
        elif hours > 0:
            return f"`{hours}h {minutes}m`"
        return f"`{minutes}m`"

    def _get_avatar_url(self) -> Optional[str]:
        """Get bot avatar URL."""
        if self._bot and self._bot.user and self._bot.user.display_avatar:
            return str(self._bot.user.display_avatar.url)
        return None

    def _get_system_resources(self) -> dict:
        """Get system CPU, memory, and disk usage."""
        try:
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = psutil.cpu_percent(interval=None)
            sys_mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                "bot_mem_mb": round(mem_mb, 1),
                "cpu_percent": round(cpu_percent, 1),
                "sys_mem_percent": round(sys_mem.percent, 1),
                "disk_used_gb": round(disk.used / (1024 ** 3), 1),
                "disk_total_gb": round(disk.total / (1024 ** 3), 1),
                "disk_percent": round(disk.percent, 1),
            }
        except Exception:
            return {}

    def _create_status_embed(self, status: str, color: int, include_health: bool = False) -> dict:
        """Create status embed with uptime and health info."""
        now = datetime.now(NY_TZ)

        description = f"**Uptime:** {self._get_uptime()}"

        if include_health and self._bot:
            # Discord latency
            if self._bot.is_ready():
                latency_ms = round(self._bot.latency * 1000)
                latency_indicator = " ⚠️" if latency_ms > LATENCY_THRESHOLD_MS else ""
                description += f"\n**Latency:** `{latency_ms}ms`{latency_indicator}"

            # Guild count
            description += f"\n**Guilds:** `{len(self._bot.guilds)}`"

            # System resources with progress bars
            resources = self._get_system_resources()
            if resources:
                cpu_bar = _create_progress_bar(resources['cpu_percent'])
                mem_bar = _create_progress_bar(resources['sys_mem_percent'])
                disk_bar = _create_progress_bar(resources['disk_percent'])

                description += f"\n\n**System Resources**"
                description += f"\n`CPU ` {cpu_bar} `{resources['cpu_percent']:>5.1f}%`"
                description += f"\n`MEM ` {mem_bar} `{resources['sys_mem_percent']:>5.1f}%`"
                description += f"\n`DISK` {disk_bar} `{resources['disk_percent']:>5.1f}%`"
                description += f"\n*Bot: {resources['bot_mem_mb']}MB | Disk: {resources['disk_used_gb']}/{resources['disk_total_gb']}GB*"

        embed = {
            "title": f"{self.bot_name} - {status}",
            "description": description,
            "color": color,
            "timestamp": now.isoformat(),
        }

        avatar = self._get_avatar_url()
        if avatar:
            embed["thumbnail"] = {"url": avatar}

        return embed

    async def _send_webhook(
        self,
        embed: dict,
        content: Optional[str] = None,
        use_logging_webhook: bool = False,
    ) -> bool:
        """Send embed to webhook with retry."""
        if not self.enabled or not self.webhook_url:
            return False

        webhook_url = self.webhook_url
        if use_logging_webhook and self._logging_webhook_url:
            webhook_url = self._logging_webhook_url

        payload = {
            "username": f"{self.bot_name} Status",
            "embeds": [embed],
        }
        if content:
            payload["content"] = content

        start_time = time.monotonic()

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(webhook_url, json=payload) as response:
                    if response.status == 204:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        logger.tree("Status Webhook Sent", [
                            ("Status", embed.get("title", "Unknown")),
                            ("Duration", f"{duration_ms}ms"),
                        ], emoji="📤")
                        return True
                    elif response.status == 429:
                        retry_after = float(response.headers.get("Retry-After", 5))
                        logger.tree("Status Webhook Rate Limited", [
                            ("Retry After", f"{retry_after}s"),
                        ], emoji="⏳")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.tree("Status Webhook Failed", [
                            ("Status Code", str(response.status)),
                            ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                        ], emoji="⚠️")

            except asyncio.TimeoutError:
                logger.tree("Status Webhook Timeout", [
                    ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                ], emoji="⏳")
            except Exception as e:
                logger.tree("Status Webhook Error", [
                    ("Error", str(e)[:50]),
                    ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                ], emoji="❌")

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)

        return False

    # =========================================================================
    # Core Status Methods
    # =========================================================================

    async def send_startup_alert(self) -> None:
        """Send startup alert."""
        logger.tree("Sending Startup Alert", [], emoji="🟢")
        embed = self._create_status_embed("Online", COLOR_ONLINE, include_health=True)
        await self._send_webhook(embed)

    async def send_status_alert(self, status: str = "Online") -> None:
        """Send hourly status alert."""
        logger.tree("Sending Hourly Status", [], emoji="📊")
        embed = self._create_status_embed(status, COLOR_ONLINE, include_health=True)
        await self._send_webhook(embed)

    async def send_shutdown_alert(self) -> None:
        """Send shutdown alert."""
        logger.tree("Sending Shutdown Alert", [
            ("Uptime", self._get_uptime()),
        ], emoji="🔴")
        embed = self._create_status_embed("Offline", COLOR_OFFLINE)
        embed["description"] = f"**Uptime:** {self._get_uptime()}\n\nBot is shutting down."
        await self._send_webhook(embed)

    async def send_alert(self, title: str, message: str) -> None:
        """Send a custom alert (used by send_webhook_alert_safe in retry.py)."""
        embed = {
            "title": f"{self.bot_name} - {title}",
            "description": message,
            "color": COLOR_WARNING,
            "timestamp": datetime.now(NY_TZ).isoformat(),
        }
        avatar = self._get_avatar_url()
        if avatar:
            embed["thumbnail"] = {"url": avatar}
        await self._send_webhook(embed, use_logging_webhook=True)

    # =========================================================================
    # Optional Alert Methods (for monitoring)
    # =========================================================================

    async def send_error_alert(self, error_type: str, error_message: str) -> None:
        """Log error (compatibility method - errors go to tree logger)."""
        logger.warning(f"Error: {error_type}", [
            ("Message", error_message[:100]),
        ])

    async def send_latency_alert(self, latency_ms: int) -> None:
        """Send high latency alert (with throttling)."""
        now = datetime.now(NY_TZ)
        if self._last_latency_alert_time:
            elapsed = (now - self._last_latency_alert_time).total_seconds()
            if elapsed < LATENCY_THROTTLE_SECONDS:
                return

        logger.warning("High Latency Alert", [
            ("Latency", f"{latency_ms}ms"),
            ("Threshold", f"{LATENCY_THRESHOLD_MS}ms"),
        ])
        self._last_latency_alert_time = now

        embed = self._create_status_embed("High Latency", COLOR_WARNING)
        embed["description"] = (
            f"**Uptime:** {self._get_uptime()}\n\n"
            f"**Latency:** `{latency_ms}ms` (threshold: `{LATENCY_THRESHOLD_MS}ms`)"
        )
        await self._send_webhook(embed, use_logging_webhook=True)

    async def send_voice_disconnect_alert(self) -> None:
        """Send voice disconnect alert (with throttling)."""
        now = datetime.now(NY_TZ)
        if self._last_voice_disconnect_time:
            elapsed = (now - self._last_voice_disconnect_time).total_seconds()
            if elapsed < VOICE_THROTTLE_SECONDS:
                return

        logger.warning("Voice Disconnect Alert")
        self._last_voice_disconnect_time = now

        embed = self._create_status_embed("Voice Disconnected", COLOR_WARNING)
        embed["description"] = (
            f"**Uptime:** {self._get_uptime()}\n\n"
            "Voice connection has been lost.\nAttempting to reconnect..."
        )
        await self._send_webhook(embed, use_logging_webhook=True)

    async def send_recovery_alert(self, recovery_type: str) -> None:
        """Send recovery alert."""
        logger.tree("Recovery Alert", [
            ("Type", recovery_type),
        ], emoji="💚")

        embed = self._create_status_embed("Recovered", COLOR_ONLINE)
        embed["description"] = (
            f"**Uptime:** {self._get_uptime()}\n\n"
            f"**{recovery_type}** has recovered and is now healthy."
        )
        await self._send_webhook(embed, use_logging_webhook=True)

    # =========================================================================
    # Health Checks (call in hourly loop if needed)
    # =========================================================================

    def check_latency(self) -> None:
        """Check latency and trigger alert if needed."""
        if not self._bot or not self._bot.is_ready():
            return

        latency_ms = round(self._bot.latency * 1000)
        is_high = latency_ms > LATENCY_THRESHOLD_MS

        if is_high and not self._latency_degraded:
            self._latency_degraded = True
            asyncio.create_task(self.send_latency_alert(latency_ms))
        elif not is_high and self._latency_degraded:
            self._latency_degraded = False
            asyncio.create_task(self.send_recovery_alert("Latency"))

    # =========================================================================
    # Hourly Scheduler
    # =========================================================================

    async def start_hourly_alerts(self) -> None:
        """Start the hourly alert loop."""
        if not self.enabled:
            return

        if self._hourly_task and not self._hourly_task.done():
            return

        async def hourly_loop():
            while True:
                try:
                    now = datetime.now(NY_TZ)
                    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                    wait_seconds = (next_hour - now).total_seconds()

                    logger.tree("Hourly Status Scheduled", [
                        ("Next", next_hour.strftime("%I:%M %p EST")),
                        ("Wait", f"{int(wait_seconds)}s"),
                    ], emoji="⏰")

                    await asyncio.sleep(wait_seconds)
                    await self.send_status_alert()

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Hourly Alert Error", [
                        ("Error", str(e)[:50]),
                    ])
                    await asyncio.sleep(60)

        self._hourly_task = asyncio.create_task(hourly_loop())

    def stop_hourly_alerts(self) -> None:
        """Stop the hourly alert loop."""
        if self._hourly_task and not self._hourly_task.done():
            self._hourly_task.cancel()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self.stop_hourly_alerts()
        await self.close()


# =============================================================================
# Singleton Factory
# =============================================================================

_instances: dict[str, StatusWebhookService] = {}


def get_status_service(
    webhook_url: Optional[str] = None,
    bot_name: str = "Bot",
    logging_webhook_url: Optional[str] = None,
) -> StatusWebhookService:
    """
    Get or create a status service instance for a bot.

    Args:
        webhook_url: Discord webhook URL
        bot_name: Name of the bot (used as instance key)
        logging_webhook_url: Optional separate webhook for alerts

    Returns:
        StatusWebhookService instance
    """
    if bot_name not in _instances:
        _instances[bot_name] = StatusWebhookService(
            webhook_url=webhook_url,
            bot_name=bot_name,
            logging_webhook_url=logging_webhook_url,
        )
    return _instances[bot_name]


# Compatibility aliases
WebhookAlertService = StatusWebhookService
get_alert_service = get_status_service


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "StatusWebhookService",
    "get_status_service",
    # Compatibility aliases
    "WebhookAlertService",
    "get_alert_service",
    # Constants (for customization)
    "COLOR_ONLINE",
    "COLOR_OFFLINE",
    "COLOR_WARNING",
    "LATENCY_THRESHOLD_MS",
]
