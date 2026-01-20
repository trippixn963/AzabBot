"""
AzabBot - Status Webhook Service
================================

Sends bot status notifications to Discord webhooks with:
- Hourly status reports with health info
- Startup/shutdown alerts
- System resource monitoring

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

import aiohttp
import psutil

from src.core.logger import logger
from src.core.config import NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Colors
COLOR_ONLINE = 0x00FF00   # Green
COLOR_OFFLINE = 0xFF0000  # Red

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds

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

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self.webhook_url = webhook_url or os.getenv("STATUS_WEBHOOK")
        self.enabled = bool(self.webhook_url)
        self._hourly_task: Optional[asyncio.Task] = None
        self._bot: Optional["AzabBot"] = None
        self._start_time: Optional[datetime] = None

        if self.enabled:
            logger.tree("Status Webhook", [
                ("Status", "Enabled"),
                ("Schedule", "Every hour (NY time)"),
            ], emoji="🔔")
        else:
            logger.tree("Status Webhook", [
                ("Status", "Disabled"),
                ("Reason", "No webhook URL provided"),
            ], emoji="🔕")

    def set_bot(self, bot: "AzabBot") -> None:
        """Set bot reference for stats."""
        self._bot = bot
        if self._start_time is None:
            self._start_time = datetime.now(NY_TZ)

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
        if self._bot and self._bot.user:
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
                latency_indicator = " ⚠️" if latency_ms > 500 else ""
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
            "title": f"AzabBot - {status}",
            "description": description,
            "color": color,
            "timestamp": now.isoformat(),
        }

        avatar = self._get_avatar_url()
        if avatar:
            embed["thumbnail"] = {"url": avatar}

        return embed

    async def _send_webhook(self, embed: dict) -> bool:
        """Send embed to webhook with retry."""
        if not self.enabled or not self.webhook_url:
            return False

        payload = {
            "username": "AzabBot Status",
            "embeds": [embed],
        }

        start_time = time.monotonic()

        for attempt in range(MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.webhook_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
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

    async def send_startup_alert(self) -> None:
        """Send startup alert."""
        logger.tree("Sending Startup Alert", [], emoji="🟢")
        embed = self._create_status_embed("Online", COLOR_ONLINE, include_health=True)
        await self._send_webhook(embed)

    async def send_status_alert(self, status: str = "Online") -> None:
        """Send hourly status alert."""
        logger.tree("Sending Hourly Status", [], emoji="📊")
        embed = self._create_status_embed("Online", COLOR_ONLINE, include_health=True)
        await self._send_webhook(embed)

    async def send_shutdown_alert(self) -> None:
        """Send shutdown alert."""
        logger.tree("Sending Shutdown Alert", [
            ("Uptime", self._get_uptime()),
        ], emoji="🔴")
        embed = self._create_status_embed("Offline", COLOR_OFFLINE)
        embed["description"] = f"**Uptime:** {self._get_uptime()}\n\nBot is shutting down."
        await self._send_webhook(embed)

    # =========================================================================
    # Compatibility Methods (no-op, errors handled by logger)
    # =========================================================================

    async def send_error_alert(self, error_type: str, error_message: str) -> None:
        """Log error (compatibility method - errors handled by tree logger)."""
        logger.warning(f"Error: {error_type}", [
            ("Message", error_message[:100]),
        ])

    async def send_latency_alert(self, latency_ms: int) -> None:
        """Log high latency (compatibility method)."""
        logger.warning("High Latency", [
            ("Latency", f"{latency_ms}ms"),
        ])

    async def send_recovery_alert(self, recovery_type: str) -> None:
        """Log recovery (compatibility method)."""
        logger.tree("Recovery", [
            ("Type", recovery_type),
        ], emoji="💚")

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
                    # Calculate seconds until next hour
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


# =============================================================================
# Singleton
# =============================================================================

_status_service: Optional[StatusWebhookService] = None


def get_status_service(webhook_url: Optional[str] = None) -> StatusWebhookService:
    """Get singleton instance."""
    global _status_service
    if _status_service is None:
        _status_service = StatusWebhookService(webhook_url)
    return _status_service


# Compatibility alias
WebhookAlertService = StatusWebhookService
get_alert_service = get_status_service


__all__ = [
    "StatusWebhookService",
    "get_status_service",
    # Compatibility aliases
    "WebhookAlertService",
    "get_alert_service",
]
