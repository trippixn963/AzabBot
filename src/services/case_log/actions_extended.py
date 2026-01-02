"""
Case Log Extended Actions
=========================

Additional log_* action methods (timeout, ban, unban, forbid, unforbid).
These methods are mixed into CaseLogService.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Optional, List

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.retry import safe_send

from .utils import (
    format_duration_precise,
    format_age,
    has_valid_media_evidence,
)
from .embeds import (
    build_timeout_embed,
    build_forbid_embed,
    build_unforbid_embed,
)


class CaseLogExtendedActionsMixin:
    """Mixin class containing extended action methods."""

    # =========================================================================
    # Timeout Logging
    # =========================================================================

    async def log_timeout(
        self,
        user: discord.Member,
        moderator_id: int,
        until: datetime,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> Optional[dict]:
        """Log a timeout action to the user's case thread."""
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)
            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            guild = user.guild
            moderator = guild.get_member(moderator_id)
            mod_name = moderator.display_name if moderator else f"Mod ({moderator_id})"

            now = datetime.now(NY_TZ)
            until_aware = until.replace(tzinfo=NY_TZ) if until.tzinfo is None else until
            delta = until_aware - now
            if delta.days > 0:
                duration = f"{delta.days}d {delta.seconds // 3600}h"
            elif delta.seconds >= 3600:
                duration = f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
            else:
                duration = f"{delta.seconds // 60}m"

            if case.get("just_created"):
                mute_count = 1
            else:
                mute_count = self.db.increment_mute_count(user.id)

            evidence_message_url = None
            if evidence and has_valid_media_evidence(evidence):
                try:
                    evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                    if evidence_msg:
                        evidence_message_url = evidence_msg.jump_url
                except Exception as e:
                    logger.error(f"Evidence storage failed: {e}")

            embed = build_timeout_embed(
                user, mod_name, duration, until, reason,
                mute_count, moderator, evidence_message_url
            )
            # Action embeds no longer have buttons - control panel handles all controls
            embed_message = await safe_send(case_thread, embed=embed)

            if moderator and not reason and embed_message:
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ {moderator.mention} No reason was provided for this timeout.\n\n"
                    f"**Reply to this message** with the reason."
                )
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator_id,
                        target_user_id=user.id,
                        action_type="timeout",
                    )

            logger.tree("Case Log: Timeout Logged", [
                ("User", user.name),
                ("Case ID", case['case_id']),
                ("Duration", duration),
                ("Mute #", str(mute_count)),
            ], emoji="⏰")

            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Timeout", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Ban Logging
    # =========================================================================

    async def log_ban(
        self,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Log a ban action - creates a NEW per-action case."""
        if not self.enabled:
            return None

        try:
            case = await self._create_action_case(
                user=user,
                moderator=moderator,
                action_type="ban",
                reason=reason,
                evidence=evidence,
            )

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            now = datetime.now(NY_TZ)

            evidence_message_url = None
            if evidence and has_valid_media_evidence(evidence):
                try:
                    evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                    if evidence_msg:
                        evidence_message_url = evidence_msg.jump_url
                except Exception as e:
                    logger.error(f"Evidence storage failed: {e}")

            ban_count = self.db.get_user_ban_count(user.id, user.guild.id)

            if ban_count > 0:
                title = f"🔨 User Banned (Ban #{ban_count + 1})"
            else:
                title = "🔨 User Banned"

            embed = discord.Embed(
                title=title,
                color=EmbedColors.ERROR,
                timestamp=now,
            )
            embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Banned By", value=f"`{moderator.display_name}`", inline=True)

            created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
            account_age_days = (now - created_at).days
            age_str = format_age(created_at, now)

            if account_age_days < 7:
                embed.add_field(name="Account Age", value=f"`{age_str}` ⚠️", inline=True)
            elif account_age_days < 30:
                embed.add_field(name="Account Age", value=f"`{age_str}` ⚡", inline=True)
            else:
                embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

            if hasattr(user, "joined_at") and user.joined_at:
                embed.add_field(name="Server Joined", value=f"<t:{int(user.joined_at.timestamp())}:R>", inline=True)

            if ban_count > 0:
                embed.add_field(name="Previous Bans", value=f"`{ban_count}`", inline=True)

            if reason:
                embed.add_field(name="Reason", value=f"```{reason}```", inline=False)
            else:
                embed.add_field(name="Reason", value="```No reason provided```", inline=False)

            if evidence_message_url:
                embed.add_field(name="Evidence", value=f"[View Evidence]({evidence_message_url})", inline=False)

            embed.set_footer(text=f"Ban • ID: {user.id}")

            # Action embeds no longer have buttons - control panel handles all controls
            embed_message = await safe_send(case_thread, embed=embed)

            if not reason and embed_message:
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ {moderator.mention} No reason was provided for this ban.\n\n"
                    f"**Reply to this message** with the reason."
                )
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type="ban",
                    )

            logger.tree("Case Log: Ban Case Created", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case['case_id']),
            ], emoji="🔨")

            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Ban", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:200]),
            ])
            return None

    # =========================================================================
    # Unban Logging
    # =========================================================================

    async def log_unban(
        self,
        user_id: int,
        username: str,
        moderator: discord.Member,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Log an unban action - finds active ban case and resolves it."""
        if not self.enabled:
            return None

        try:
            guild_id = moderator.guild.id
            active_ban_case = self.db.get_active_ban_case(user_id, guild_id)

            if active_ban_case:
                case_thread = await self._get_case_thread(active_ban_case["thread_id"])

                if not case_thread:
                    return {"case_id": active_ban_case["case_id"], "thread_id": active_ban_case["thread_id"]}

                now = datetime.now(NY_TZ)

                time_banned = None
                if active_ban_case.get("created_at"):
                    banned_at = active_ban_case["created_at"]
                    time_banned_seconds = now.timestamp() - banned_at
                    time_banned = format_duration_precise(time_banned_seconds)

                original_moderator_name = None
                original_mod_id = active_ban_case.get("moderator_id")
                if original_mod_id and moderator.guild:
                    original_mod = moderator.guild.get_member(original_mod_id)
                    if original_mod:
                        original_moderator_name = original_mod.display_name

                original_reason = active_ban_case.get("reason")

                embed = discord.Embed(
                    title="🔓 User Unbanned",
                    color=EmbedColors.SUCCESS,
                    timestamp=now,
                )
                embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
                embed.add_field(name="Unbanned By", value=f"`{moderator.display_name}`", inline=True)

                if time_banned:
                    embed.add_field(name="Banned For", value=f"`{time_banned}`", inline=True)

                if original_moderator_name:
                    embed.add_field(name="Originally Banned By", value=f"`{original_moderator_name}`", inline=True)

                if original_reason:
                    embed.add_field(name="Original Reason", value=f"```{original_reason[:200]}```", inline=False)

                if reason:
                    embed.add_field(name="Unban Reason", value=f"```{reason}```", inline=False)

                embed.set_footer(text=f"Case Resolved • ID: {user_id}")

                # Action embeds no longer have buttons - control panel handles all controls
                await safe_send(case_thread, embed=embed)

                # Update control panel to show resolved status
                await self._update_control_panel(
                    case_id=active_ban_case["case_id"],
                    case_thread=case_thread,
                    new_status="resolved",
                    moderator=moderator,
                )

                self.db.resolve_case(
                    case_id=active_ban_case["case_id"],
                    resolved_by=moderator.id,
                    reason=reason,
                )

                logger.tree("Case Log: Ban Case Resolved (Unban)", [
                    ("User", f"{username} ({user_id})"),
                    ("Case ID", active_ban_case["case_id"]),
                    ("Banned For", time_banned or "Unknown"),
                ], emoji="🔓")

                return {"case_id": active_ban_case["case_id"], "thread_id": active_ban_case["thread_id"]}

            # Legacy fallback
            return await self._log_unban_legacy(user_id, username, moderator, reason, source_message_url)

        except Exception as e:
            logger.error("Case Log: Failed To Log Unban", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _log_unban_legacy(
        self,
        user_id: int,
        username: str,
        moderator: discord.Member,
        reason: Optional[str],
        source_message_url: Optional[str],
    ) -> Optional[dict]:
        """Legacy unban logging for backward compatibility."""
        case = self.db.get_case_log(user_id)
        if not case:
            return None

        last_ban_info = self.db.get_last_ban_info(user_id)

        time_banned = None
        original_moderator_name = None
        original_reason = None

        if last_ban_info and last_ban_info.get("last_ban_at"):
            banned_at = last_ban_info["last_ban_at"]
            now_ts = datetime.now(NY_TZ).timestamp()
            time_banned_seconds = now_ts - banned_at
            time_banned = format_duration_precise(time_banned_seconds)
            original_reason = last_ban_info.get("last_ban_reason")

            original_mod_id = last_ban_info.get("last_ban_moderator_id")
            if original_mod_id and moderator.guild:
                original_mod = moderator.guild.get_member(original_mod_id)
                if original_mod:
                    original_moderator_name = original_mod.display_name

        case_thread = await self._get_case_thread(case["thread_id"])

        if case_thread:
            now = datetime.now(NY_TZ)

            embed = discord.Embed(
                title="🔓 User Unbanned",
                color=EmbedColors.SUCCESS,
                timestamp=now,
            )
            embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
            embed.add_field(name="Unbanned By", value=f"`{moderator.display_name}`", inline=True)

            if time_banned:
                embed.add_field(name="Banned For", value=f"`{time_banned}`", inline=True)

            if original_moderator_name:
                embed.add_field(name="Originally Banned By", value=f"`{original_moderator_name}`", inline=True)

            if original_reason:
                embed.add_field(name="Original Reason", value=f"```{original_reason[:200]}```", inline=False)

            if reason:
                embed.add_field(name="Unban Reason", value=f"```{reason}```", inline=False)

            embed.set_footer(text=f"Unban • ID: {user_id}")

            # Action embeds no longer have buttons - control panel handles all controls
            await safe_send(case_thread, embed=embed)

            logger.tree("Case Log: Unban Logged (Legacy)", [
                ("User", f"{username} ({user_id})"),
                ("Case ID", case['case_id']),
            ], emoji="🔓")

        return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

    # =========================================================================
    # Forbid Logging
    # =========================================================================

    async def log_forbid(
        self,
        user: discord.Member,
        moderator: discord.Member,
        restrictions: List[str],
        reason: Optional[str] = None,
        duration: Optional[str] = None,
    ) -> Optional[dict]:
        """Log a forbid action - creates a case for the restriction."""
        if not self.enabled:
            return None

        if not restrictions:
            return None

        try:
            case = await self._create_action_case(
                user=user,
                moderator=moderator,
                action_type="forbid",
                reason=reason or f"Restrictions: {', '.join(restrictions)}",
            )

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            embed = build_forbid_embed(user, moderator, restrictions, reason, duration)
            # Action embeds no longer have buttons - control panel handles all controls
            await safe_send(case_thread, embed=embed)

            logger.tree("Case Log: Forbid", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case['case_id']),
                ("Restrictions", ", ".join(restrictions)),
            ], emoji="🚫")

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Forbid", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Unforbid Logging
    # =========================================================================

    async def log_unforbid(
        self,
        user: discord.Member,
        moderator: discord.Member,
        restrictions: List[str],
    ) -> Optional[dict]:
        """Log an unforbid action - creates a case for the removal."""
        if not self.enabled:
            return None

        if not restrictions:
            return None

        try:
            case = await self._create_action_case(
                user=user,
                moderator=moderator,
                action_type="unforbid",
                reason=f"Removed: {', '.join(restrictions)}",
            )

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            embed = build_unforbid_embed(user, moderator, restrictions)
            # Action embeds no longer have buttons - control panel handles all controls
            await safe_send(case_thread, embed=embed)

            # Update control panel to show resolved status
            await self._update_control_panel(
                case_id=case["case_id"],
                case_thread=case_thread,
                new_status="resolved",
                moderator=moderator,
            )

            logger.tree("Case Log: Unforbid", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case['case_id']),
                ("Removed", ", ".join(restrictions)),
            ], emoji="✅")

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unforbid", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None


__all__ = ["CaseLogExtendedActionsMixin"]
