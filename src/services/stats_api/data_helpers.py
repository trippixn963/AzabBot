"""
Stats API - Data Helpers Mixin
==============================

Data fetching and transformation methods.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import psutil

from src.core.config import get_config, NY_TZ
from src.core.constants import GUILD_FETCH_TIMEOUT

if TYPE_CHECKING:
    from .service import AzabAPI


# Avatar cache: {user_id: (name, avatar, is_booster)}
_avatar_cache: Dict[int, tuple[str, Optional[str], bool]] = {}
_avatar_cache_date: Optional[str] = None

BOT_HOME = os.environ.get("BOT_HOME", "/root/AzabBot")


class DataHelpersMixin:
    """Mixin for data helper methods."""

    async def _get_moderation_stats(
        self: "AzabAPI",
        today_start: float,
        today_end: float,
        week_start: float,
        guild_id: Optional[int]
    ) -> Dict[str, Any]:
        """Get moderation statistics."""
        db = self._bot.db

        return {
            "today": {
                "mutes": db.get_mutes_in_range(today_start, today_end, guild_id),
                "bans": db.get_bans_in_range(today_start, today_end, guild_id),
                "warns": db.get_warns_in_range(today_start, today_end, guild_id),
            },
            "weekly": {
                "mutes": db.get_mutes_in_range(week_start, today_end, guild_id),
                "bans": db.get_bans_in_range(week_start, today_end, guild_id),
                "warns": db.get_warns_in_range(week_start, today_end, guild_id),
            },
            "all_time": {
                "total_mutes": db.get_total_mutes(guild_id),
                "total_bans": db.get_total_bans(guild_id),
                "total_warns": db.get_total_warns(guild_id),
                "total_cases": db.get_total_cases(guild_id),
            },
            "active": {
                "prisoners": db.get_active_prisoners_count(guild_id),
                "open_cases": db.get_open_cases_count(guild_id),
            },
        }

    async def _get_top_offenders(self: "AzabAPI", guild_id: Optional[int], limit: int = 10) -> List[Dict]:
        """Get top offenders with avatar data and booster status."""
        offenders = self._bot.db.get_top_offenders(limit=limit, guild_id=guild_id)

        # Enrich with user data
        enriched = []
        for offender in offenders:
            user_id = offender["user_id"]
            name, avatar, is_booster = await self._fetch_user_data(user_id, f"User {user_id}")
            enriched.append({
                "user_id": str(user_id),
                "name": name,
                "mutes": offender["mutes"],
                "bans": offender["bans"],
                "warns": offender["warns"],
                "total": offender["total"],
                "avatar": avatar,
                "is_booster": is_booster,
            })

        return enriched

    async def _get_moderator_leaderboard(self: "AzabAPI", limit: int = 10) -> List[Dict]:
        """Get moderator leaderboard with avatar data and booster status (excludes bot)."""
        bot_user_id = self._bot.user.id if self._bot.user else None
        mods = self._bot.db.get_moderator_leaderboard(limit=limit, exclude_user_id=bot_user_id)

        enriched = []
        for mod in mods:
            mod_id = mod["moderator_id"]
            name, avatar, is_booster = await self._fetch_user_data(mod_id, f"Mod {mod_id}")
            enriched.append({
                "user_id": str(mod_id),
                "name": name,
                "actions": mod.get("total_actions", 0),
                "mutes": mod.get("mutes", 0),
                "bans": mod.get("bans", 0),
                "warns": mod.get("warns", 0),
                "avatar": avatar,
                "is_booster": is_booster,
            })

        return enriched

    async def _get_recent_actions(self: "AzabAPI", guild_id: Optional[int], limit: int = 10) -> List[Dict]:
        """Get recent moderation actions."""
        actions = self._bot.db.get_recent_actions(limit=limit, guild_id=guild_id)

        enriched = []
        for action in actions:
            user_name, _, _ = await self._fetch_user_data(action["user_id"], f"User {action['user_id']}")
            mod_name, _, _ = await self._fetch_user_data(action["moderator_id"], f"Mod {action['moderator_id']}")

            # Format timestamp
            ts = action["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": action["type"],
                "user": user_name,
                "user_id": str(action["user_id"]),
                "moderator": mod_name,
                "moderator_id": str(action["moderator_id"]),
                "reason": (action["reason"] or "No reason")[:100],
                "time": time_str,
                "timestamp": ts,
            })

        return enriched

    async def _get_repeat_offenders(self: "AzabAPI", guild_id: Optional[int], limit: int = 5) -> List[Dict]:
        """Get users with 3+ total punishments (repeat offenders)."""
        offenders = self._bot.db.get_repeat_offenders(min_offenses=3, limit=limit, guild_id=guild_id)

        enriched = []
        for offender in offenders:
            user_id = offender["user_id"]
            name, avatar, is_booster = await self._fetch_user_data(user_id, f"User {user_id}")
            enriched.append({
                "user_id": str(user_id),
                "name": name,
                "mutes": offender["mutes"],
                "bans": offender["bans"],
                "warns": offender["warns"],
                "total": offender["total"],
                "avatar": avatar,
                "is_booster": is_booster,
            })

        return enriched

    async def _get_recent_releases(self: "AzabAPI", guild_id: Optional[int], limit: int = 5) -> List[Dict]:
        """Get recently released prisoners."""
        releases = self._bot.db.get_recent_releases(limit=limit, guild_id=guild_id)

        enriched = []
        for release in releases:
            try:
                user_id = release["user_id"]
                name, avatar, _ = await self._fetch_user_data(user_id, f"User {user_id}")

                # Format duration - cap at reasonable values
                duration_mins = release.get("duration_minutes", 0) or 0
                # Sanity check: cap at 1 year (525600 minutes)
                if duration_mins > 525600:
                    duration_mins = 0

                if duration_mins >= 1440:  # 24 hours
                    duration_str = f"{duration_mins // 1440}d {(duration_mins % 1440) // 60}h"
                elif duration_mins >= 60:
                    duration_str = f"{duration_mins // 60}h {duration_mins % 60}m"
                else:
                    duration_str = f"{duration_mins}m" if duration_mins > 0 else "N/A"

                # Format release time using muted_at (more reliable)
                muted_at = release.get("muted_at")
                if muted_at and muted_at < 2000000000:  # Sanity check: before year 2033
                    muted_time = datetime.fromtimestamp(muted_at, NY_TZ)
                    now = datetime.now(NY_TZ)
                    delta = now - muted_time
                    if delta.days > 0:
                        time_str = f"{delta.days}d ago"
                    elif delta.seconds >= 3600:
                        time_str = f"{delta.seconds // 3600}h ago"
                    elif delta.seconds >= 60:
                        time_str = f"{delta.seconds // 60}m ago"
                    else:
                        time_str = "just now"
                else:
                    time_str = "recently"

                enriched.append({
                    "user_id": str(user_id),
                    "name": name,
                    "avatar": avatar,
                    "time_served": duration_str,
                    "released": time_str,
                })
            except Exception:
                # Skip problematic entries
                continue

        return enriched

    async def _get_moderator_spotlight(self: "AzabAPI", guild_id: Optional[int]) -> Optional[Dict]:
        """Get top moderator of all time (excludes the bot itself)."""
        bot_user_id = self._bot.user.id if self._bot.user else None
        top_mod = self._bot.db.get_all_time_top_moderator(guild_id=guild_id, exclude_user_id=bot_user_id)

        if not top_mod:
            return None

        mod_id = top_mod["moderator_id"]
        name, avatar, _ = await self._fetch_user_data(mod_id, f"Mod {mod_id}")

        return {
            "user_id": str(mod_id),
            "name": name,
            "avatar": avatar,
            "total_actions": top_mod["total_actions"],
            "mutes": top_mod["mutes"],
            "bans": top_mod["bans"],
            "warns": top_mod["warns"],
        }

    async def _get_moderator_recent_actions(
        self: "AzabAPI",
        moderator_id: int,
        guild_id: Optional[int],
        limit: int = 10
    ) -> List[Dict]:
        """Get recent actions by a specific moderator."""
        actions = self._bot.db.get_moderator_actions(moderator_id, limit=limit, guild_id=guild_id)

        enriched = []
        for action in actions:
            target_name, _, _ = await self._fetch_user_data(action["user_id"], f"User {action['user_id']}")

            # Format timestamp
            ts = action["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": action["type"],
                "target": target_name,
                "target_id": str(action["user_id"]),
                "reason": (action["reason"] or "No reason")[:100],
                "time": time_str,
                "timestamp": ts,
            })

        return enriched

    async def _get_user_recent_punishments(
        self: "AzabAPI",
        user_id: int,
        guild_id: Optional[int],
        limit: int = 10
    ) -> List[Dict]:
        """Get recent punishments received by a user."""
        punishments = self._bot.db.get_user_punishments(user_id, limit=limit, guild_id=guild_id)

        enriched = []
        for p in punishments:
            mod_name, _, _ = await self._fetch_user_data(p["moderator_id"], f"Mod {p['moderator_id']}") if p.get("moderator_id") else ("Unknown", None, False)

            # Format timestamp
            ts = p["timestamp"]
            action_time = datetime.fromtimestamp(ts, NY_TZ)
            now = datetime.now(NY_TZ)
            delta = now - action_time

            if delta.days > 0:
                time_str = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_str = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_str = f"{delta.seconds // 60}m ago"
            else:
                time_str = "just now"

            enriched.append({
                "type": p["type"],
                "reason": (p["reason"] or "No reason")[:100],
                "moderator": mod_name,
                "time": time_str,
            })

        return enriched

    def _get_system_resources(self: "AzabAPI") -> Dict[str, float]:
        """Get system resource usage."""
        try:
            process = psutil.Process()
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            return {
                "bot_mem_mb": round(process.memory_info().rss / 1024 / 1024, 1),
                "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
                "mem_percent": round(mem.percent, 1),
                "mem_used_gb": round(mem.used / 1024 / 1024 / 1024, 2),
                "mem_total_gb": round(mem.total / 1024 / 1024 / 1024, 2),
                "disk_percent": round(disk.percent, 1),
                "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            }
        except Exception:
            return {
                "bot_mem_mb": 0,
                "cpu_percent": 0,
                "mem_percent": 0,
                "mem_used_gb": 0,
                "mem_total_gb": 0,
                "disk_percent": 0,
                "disk_used_gb": 0,
                "disk_total_gb": 0,
            }

    async def _get_changelog(self: "AzabAPI", limit: int = 10) -> List[Dict[str, str]]:
        """Get recent git commits."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", f"-{limit}", "--format=%h|%s",
                cwd=BOT_HOME,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=GUILD_FETCH_TIMEOUT)

            changelog = []
            for line in stdout.decode().strip().split("\n"):
                if "|" in line:
                    commit, message = line.split("|", 1)
                    # Determine type
                    msg_lower = message.lower()
                    if any(w in msg_lower for w in ["fix", "bug", "patch"]):
                        commit_type = "fix"
                    elif any(w in msg_lower for w in ["add", "new", "feature", "implement"]):
                        commit_type = "feature"
                    else:
                        commit_type = "improvement"

                    changelog.append({
                        "commit": commit.strip(),
                        "message": message.strip()[:80],
                        "type": commit_type,
                    })

            return changelog

        except Exception:
            return []

    def _format_uptime(self: "AzabAPI") -> str:
        """Format bot uptime as human-readable string."""
        if not self._start_time:
            return "Unknown"

        delta = datetime.now(NY_TZ) - self._start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or not parts:
            parts.append(f"{minutes}m")

        return " ".join(parts)

    # =========================================================================
    # Avatar Fetching
    # =========================================================================

    def _check_cache_refresh(self: "AzabAPI") -> None:
        """Clear avatar cache at midnight EST."""
        global _avatar_cache, _avatar_cache_date
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        if _avatar_cache_date != today:
            _avatar_cache.clear()
            _avatar_cache_date = today

    async def _fetch_user_data(self: "AzabAPI", user_id: int, fallback_name: str) -> tuple[str, Optional[str], bool]:
        """Fetch user name, avatar, and booster status with caching."""
        self._check_cache_refresh()

        # Check cache
        if user_id in _avatar_cache:
            return _avatar_cache[user_id]

        try:
            # Try local cache first
            user = self._bot.get_user(user_id)
            if not user:
                user = await asyncio.wait_for(
                    self._bot.fetch_user(user_id),
                    timeout=2.0
                )

            name = user.display_name
            avatar = user.display_avatar.url if user.display_avatar else None

            # Check booster status via guild member
            is_booster = False
            config = get_config()
            if config.logging_guild_id:
                guild = self._bot.get_guild(config.logging_guild_id)
                if guild:
                    member = guild.get_member(user_id)
                    if member and member.premium_since:
                        is_booster = True

            _avatar_cache[user_id] = (name, avatar, is_booster)
            return name, avatar, is_booster

        except Exception:
            _avatar_cache[user_id] = (fallback_name, None, False)
            return fallback_name, None, False


__all__ = ["DataHelpersMixin"]
