"""
Azab Discord Bot - Webhook Alert Service
=========================================

Sends bot status notifications to Discord webhooks with:
- Hourly status reports with health info
- Error alerts (no ping)
- High latency warnings
- Recovery alerts
- Retry with exponential backoff
- Separate webhooks for errors vs status

NOTE: No pings/mentions are sent for any alert type.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import asyncio
import aiohttp
import psutil
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import NY_TZ
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Colors
COLOR_ONLINE = 0x00FF00   # Green
COLOR_OFFLINE = 0xFF0000  # Red
COLOR_WARNING = 0xFFAA00  # Orange

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds

# Thresholds
LATENCY_THRESHOLD_MS = 500  # Alert if latency exceeds this

# Alert throttling (prevent spam for repeated errors)
ERROR_THROTTLE_SECONDS = 300  # 5 minutes between same error type
LATENCY_THROTTLE_SECONDS = 600  # 10 minutes between latency alerts

# Status check interval
STATUS_CHECK_INTERVAL = 60  # seconds

# Progress bar settings
PROGRESS_BAR_WIDTH = 10  # Number of characters in progress bar


# =============================================================================
# Helper Functions
# =============================================================================

def _handle_task_exception(task: asyncio.Task) -> None:
    """Handle exceptions from background asyncio tasks."""
    try:
        if not task.cancelled() and task.exception():
            logger.debug(f"Background Webhook Task Failed: {task.exception()}")
    except asyncio.InvalidStateError:
        pass  # Task not yet done


def _create_background_task(coro) -> asyncio.Task:
    """Create a background task with error handling."""
    task = asyncio.create_task(coro)
    task.add_done_callback(_handle_task_exception)
    return task


def _create_progress_bar(value: float, max_val: float = 100, width: int = PROGRESS_BAR_WIDTH) -> str:
    """
    Create a Unicode progress bar.

    Args:
        value: Current value
        max_val: Maximum value (default 100 for percentages)
        width: Number of characters in the bar

    Returns:
        Unicode progress bar string like "████████░░"
    """
    if max_val <= 0:
        return "░" * width

    ratio = min(value / max_val, 1.0)  # Clamp to 0-1
    filled = int(ratio * width)
    empty = width - filled
    return "█" * filled + "░" * empty


# =============================================================================
# Webhook Alert Service
# =============================================================================

class WebhookAlertService:
    """Webhook alerts with retry, separate channels, and health monitoring."""

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        # Read environment variables at runtime (after load_dotenv has been called)
        self.webhook_url = webhook_url or os.getenv("ALERT_WEBHOOK_URL")  # Hourly status + shutdown
        self._error_webhook_url = os.getenv("ALERT_ERROR_WEBHOOK_URL")  # Error alerts
        self._logging_webhook_url = os.getenv("LOGGING_WEBHOOK_URL")  # General logging (recovery, latency, etc.)
        self.enabled = bool(self.webhook_url)
        self._hourly_task: Optional[asyncio.Task] = None
        self._bot: Optional["AzabBot"] = None
        self._last_error_time: Optional[datetime] = None
        self._last_latency_alert_time: Optional[datetime] = None
        self._start_time: Optional[datetime] = None  # Track start time in service
        # Error throttling - track last time each error type was sent
        self._error_throttle: dict[str, datetime] = {}
        # Recovery tracking - track if we're in a degraded state
        self._latency_degraded: bool = False

        if self.enabled and self.webhook_url:
            webhook_display = self.webhook_url[:50] + "..." if len(self.webhook_url) > 50 else self.webhook_url
            logger.tree("Webhook Alerts", [
                ("Status", "Enabled"),
                ("Schedule", "Every hour (NY time)"),
                ("Status Webhook", webhook_display),
                ("Error Webhook", "Configured" if self._error_webhook_url else "Same as status"),
                ("Logging Webhook", "Configured" if self._logging_webhook_url else "Same as status"),
                ("Latency Threshold", f"{LATENCY_THRESHOLD_MS}ms"),
            ], emoji="🔔")
        else:
            logger.tree("Webhook Alerts Disabled", [
                ("Reason", "ALERT_WEBHOOK_URL not set"),
            ], emoji="🔕")

    def set_bot(self, bot: "AzabBot") -> None:
        """Set bot reference for avatar and uptime."""
        self._bot = bot
        # Capture start time when bot reference is set
        if self._start_time is None:
            self._start_time = datetime.now(NY_TZ)

    def _get_uptime(self) -> str:
        """Get formatted uptime string."""
        # Use service's own start_time (set when set_bot is called)
        if not self._start_time:
            return "`0m`"

        now = datetime.now(NY_TZ)
        delta = now - self._start_time
        total_seconds = int(delta.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        if hours > 0:
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
            # Get bot process memory
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)

            # Get system-wide CPU (non-blocking, returns cached value)
            cpu_percent = psutil.cpu_percent(interval=None)

            # Get system memory
            sys_mem = psutil.virtual_memory()

            # Get disk usage for root partition
            disk = psutil.disk_usage('/')
            disk_used_gb = disk.used / (1024 ** 3)
            disk_total_gb = disk.total / (1024 ** 3)

            return {
                "bot_mem_mb": round(mem_mb, 1),
                "cpu_percent": round(cpu_percent, 1),
                "sys_mem_percent": round(sys_mem.percent, 1),
                "disk_used_gb": round(disk_used_gb, 1),
                "disk_total_gb": round(disk_total_gb, 1),
                "disk_percent": round(disk.percent, 1),
            }
        except Exception:
            return {}

    async def _send_webhook(
        self,
        embed: dict,
        content: Optional[str] = None,
        use_error_webhook: bool = False,
        use_logging_webhook: bool = False
    ) -> bool:
        """Send embed to webhook with retry and exponential backoff."""
        if not self.enabled or not self.webhook_url:
            logger.debug("Webhook Skipped: Not enabled")
            return False

        # Choose webhook URL (guaranteed non-None from check above)
        # Priority: error > logging > status
        webhook_url: str = self.webhook_url
        if use_error_webhook and self._error_webhook_url:
            webhook_url = self._error_webhook_url
        elif use_logging_webhook and self._logging_webhook_url:
            webhook_url = self._logging_webhook_url

        payload = {
            "username": "AzabBot Status",
            "embeds": [embed],
        }
        if content:
            payload["content"] = content

        # Retry with exponential backoff
        for attempt in range(MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 204:
                            logger.tree("Webhook Sent", [
                                ("Title", embed.get("title", "Unknown")),
                                ("Attempt", str(attempt + 1)),
                            ], emoji="📤")
                            return True
                        elif response.status == 429:
                            # Rate limited, wait and retry
                            retry_after = float(response.headers.get("Retry-After", 5))
                            logger.warning(f"Webhook Rate Limited: Retry after {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            logger.warning(f"Webhook Failed: Status {response.status}, {embed.get('title', 'Unknown')}, attempt {attempt + 1}")

            except asyncio.TimeoutError:
                logger.warning(f"Webhook Timeout: {embed.get('title', 'Unknown')}, attempt {attempt + 1}")
            except Exception as e:
                logger.warning(f"Webhook Error: {e}, {embed.get('title', 'Unknown')}, attempt {attempt + 1}")

            # Exponential backoff before retry
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)

        logger.warning(f"Webhook Failed After {MAX_RETRIES} Retries: {embed.get('title', 'Unknown')}")
        return False

    def _get_bot_stats(self) -> dict:
        """Get AzabBot-specific stats."""
        stats = {
            "total_prisoners": 0,
            "active_mutes": 0,
        }

        if not self._bot:
            return stats

        try:
            # Get mute scheduler stats if available
            if hasattr(self._bot, 'mute_scheduler') and self._bot.mute_scheduler:
                scheduler = self._bot.mute_scheduler
                if hasattr(scheduler, 'get_active_count'):
                    stats["active_mutes"] = scheduler.get_active_count()
        except Exception as e:
            logger.debug(f"Failed to get bot stats: {e}")

        return stats

    def _create_status_embed(self, status: str, color: int, include_health: bool = False) -> dict:
        """Create status embed with uptime and optionally health info."""
        now = datetime.now(NY_TZ)

        # Build description with uptime
        description = f"**Uptime:** {self._get_uptime()}"

        # Add health info for hourly status checks
        if include_health and self._bot:
            # Discord latency
            if self._bot.is_ready():
                latency_ms = round(self._bot.latency * 1000)
                latency_indicator = " ⚠️" if latency_ms > LATENCY_THRESHOLD_MS else ""
                description += f"\n**Latency:** `{latency_ms}ms`{latency_indicator}"

            # Guild count
            description += f"\n**Guilds:** `{len(self._bot.guilds)}`"

            # Run ID for restart tracking
            description += f"\n**Run ID:** `{logger.run_id}`"

            # AzabBot-specific stats
            bot_stats = self._get_bot_stats()
            if bot_stats["active_mutes"] > 0:
                description += f"\n\n**Prison Stats**"
                description += f"\nActive Mutes: `{bot_stats['active_mutes']}`"

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

    # =========================================================================
    # Public Alert Methods (NO PINGS)
    # =========================================================================

    async def send_startup_alert(self) -> None:
        """Send startup alert immediately when bot starts."""
        logger.info("Sending Startup Alert")
        embed = self._create_status_embed("Online", COLOR_ONLINE, include_health=True)
        # Await directly to ensure startup alert is sent before continuing
        await self._send_webhook(embed)

    async def send_status_alert(self, status: str = "Online") -> None:
        """Send hourly status alert with health info."""
        logger.tree("Sending Hourly Status Alert", [
            ("Status", status),
        ], emoji="📊")
        color = COLOR_ONLINE if status == "Online" else COLOR_OFFLINE
        embed = self._create_status_embed(status, color, include_health=True)
        _create_background_task(self._send_webhook(embed))

    async def send_error_alert(self, error_type: str, error_message: str) -> None:
        """Send error alert (no ping, 5min cooldown) to error webhook."""
        now = datetime.now(NY_TZ)
        if self._last_error_time:
            elapsed = (now - self._last_error_time).total_seconds()
            if elapsed < ERROR_THROTTLE_SECONDS:
                logger.debug(f"Error Alert Skipped (Cooldown): {error_type}, {int(ERROR_THROTTLE_SECONDS - elapsed)}s remaining")
                return

        logger.warning(f"Sending Error Alert: {error_type} - {error_message[:50]}")
        self._last_error_time = now

        embed = self._create_status_embed("Error", COLOR_OFFLINE)
        embed["description"] = f"**Uptime:** {self._get_uptime()}\n\n**Error:** {error_type}\n```{error_message[:500]}```"

        _create_background_task(self._send_webhook(embed, use_error_webhook=True))

    async def send_shutdown_alert(self) -> None:
        """Send shutdown alert (awaited)."""
        logger.tree("Sending Shutdown Alert", [
            ("Uptime", self._get_uptime()),
        ], emoji="🔴")
        embed = self._create_status_embed("Offline", COLOR_OFFLINE)
        embed["description"] = f"**Uptime:** {self._get_uptime()}\n\nBot is shutting down."
        await self._send_webhook(embed)

    async def send_latency_alert(self, latency_ms: int) -> None:
        """Send high latency alert (10min cooldown)."""
        now = datetime.now(NY_TZ)
        if self._last_latency_alert_time:
            elapsed = (now - self._last_latency_alert_time).total_seconds()
            if elapsed < LATENCY_THROTTLE_SECONDS:
                logger.debug(f"Latency Alert Skipped (Cooldown): {latency_ms}ms, {int(LATENCY_THROTTLE_SECONDS - elapsed)}s remaining")
                return

        logger.warning(f"Sending Latency Alert: {latency_ms}ms (threshold: {LATENCY_THRESHOLD_MS}ms)")
        self._last_latency_alert_time = now

        embed = self._create_status_embed("High Latency", COLOR_WARNING)
        embed["description"] = (
            f"**Uptime:** {self._get_uptime()}\n\n"
            f"**Latency:** `{latency_ms}ms` (threshold: `{LATENCY_THRESHOLD_MS}ms`)\n\n"
            "Discord connection may be experiencing issues."
        )

        _create_background_task(self._send_webhook(embed, use_logging_webhook=True))

    async def send_recovery_alert(self, recovery_type: str) -> None:
        """
        Send recovery alert when bot recovers from a degraded state.

        Args:
            recovery_type: Type of recovery (e.g., "Latency")
        """
        logger.tree("Sending Recovery Alert", [
            ("Type", recovery_type),
        ], emoji="💚")

        embed = self._create_status_embed("Recovered", COLOR_ONLINE)
        embed["description"] = (
            f"**Uptime:** {self._get_uptime()}\n\n"
            f"**{recovery_type}** has recovered and is now healthy."
        )

        _create_background_task(self._send_webhook(embed, use_logging_webhook=True))

    def check_latency(self) -> None:
        """Check latency and send alert if too high, or recovery if normalized."""
        if not self._bot or not self._bot.is_ready():
            return

        latency_ms = round(self._bot.latency * 1000)
        is_high = latency_ms > LATENCY_THRESHOLD_MS

        if is_high:
            logger.warning(f"High Latency Detected: {latency_ms}ms (threshold: {LATENCY_THRESHOLD_MS}ms)")
            self._latency_degraded = True
            _create_background_task(self.send_latency_alert(latency_ms))

        # Detect recovery: was degraded and now normal
        elif self._latency_degraded and not is_high:
            logger.tree("Latency Recovery Detected", [
                ("Latency", f"{latency_ms}ms"),
                ("Threshold", f"{LATENCY_THRESHOLD_MS}ms"),
            ], emoji="💚")
            self._latency_degraded = False
            _create_background_task(self.send_recovery_alert("Latency"))

    # =========================================================================
    # Hourly Scheduler
    # =========================================================================

    async def start_hourly_alerts(self) -> None:
        """Start the hourly alert loop."""
        if not self.enabled:
            return

        # Prevent duplicate task creation
        if self._hourly_task and not self._hourly_task.done():
            logger.debug("Hourly Alerts Already Running: Skipping duplicate start")
            return

        async def hourly_loop():
            while True:
                try:
                    now = datetime.now(NY_TZ)
                    # Calculate seconds until next hour
                    next_hour = now.replace(minute=0, second=0, microsecond=0)
                    next_hour = next_hour.replace(hour=(now.hour + 1) % 24)
                    if next_hour.hour == 0:
                        # Handle day rollover (hour wrapped from 23 to 0)
                        next_hour = next_hour + timedelta(days=1)

                    wait_seconds = (next_hour - now).total_seconds()
                    if wait_seconds < 0:
                        wait_seconds += 3600

                    logger.debug(f"Hourly Alert Scheduled: Next at {next_hour.strftime('%I:%M %p NY')}, wait {int(wait_seconds)}s")

                    await asyncio.sleep(wait_seconds)

                    # Check health before sending status
                    self.check_latency()

                    # Send hourly status
                    await self.send_status_alert("Online")

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Hourly Alert Error: {e}")
                    await asyncio.sleep(STATUS_CHECK_INTERVAL)

        self._hourly_task = create_safe_task(hourly_loop(), "Webhook Hourly Alerts")

    def stop_hourly_alerts(self) -> None:
        """Stop the hourly alert loop."""
        if self._hourly_task and not self._hourly_task.done():
            self._hourly_task.cancel()


# =============================================================================
# Singleton
# =============================================================================

_alert_service: Optional[WebhookAlertService] = None


def get_alert_service() -> WebhookAlertService:
    """Get singleton instance."""
    global _alert_service
    if _alert_service is None:
        _alert_service = WebhookAlertService()
    return _alert_service


__all__ = ["WebhookAlertService", "get_alert_service"]
