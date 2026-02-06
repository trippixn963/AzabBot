"""
AzabBot - Case Log Actions
==========================

All log_* action methods for the case log service.
These methods are mixed into CaseLogService.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.retry import safe_send, safe_fetch_message
from src.utils.discord_rate_limit import log_http_error

from .constants import REPEAT_MUTE_THRESHOLD, REPEAT_WARN_THRESHOLD
from .utils import (
    format_duration_precise,
    format_age,
    parse_duration_to_seconds,
    has_valid_media_evidence,
)
from .embeds import (
    build_mute_embed,
    build_warn_embed,
    build_unmute_embed,
    build_expired_embed,
    build_mute_evasion_embed,
    build_vc_violation_embed,
    build_member_left_embed,
)


class CaseLogActionsMixin:
    """Mixin class containing all log_* action methods."""

    # =========================================================================
    # Mute Logging
    # =========================================================================

    async def log_mute(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
        is_extension: bool = False,
        evidence: Optional[str] = None,
    ) -> Optional[dict]:
        """Log a mute action - creates NEW case/thread for each mute."""
        if not self.enabled:
            return None

        logger.tree("Case Log: log_mute Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Duration", duration),
            ("Is Extension", str(is_extension)),
        ], emoji="📝")

        try:
            duration_seconds = parse_duration_to_seconds(duration)
            guild_id = moderator.guild.id

            if is_extension:
                active_case = self.db.get_active_mute_case(user.id, guild_id)
                if not active_case:
                    logger.warning("Mute Extension - No Active Case", [
                        ("User ID", str(user.id)),
                        ("Action", "Creating new case"),
                    ])
                    is_extension = False
                else:
                    case = active_case

            if not is_extension:
                case = await self._create_action_case(
                    user=user,
                    moderator=moderator,
                    action_type="mute",
                    reason=reason,
                    duration_seconds=duration_seconds,
                    evidence=evidence,
                )

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                logger.warning("Mute Log Thread Not Found", [
                    ("Thread ID", str(case["thread_id"])),
                ])
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            case_counts = self.db.get_user_case_counts(user.id, guild_id)
            mute_count = case_counts.get("mute_count", 1)

            expires_at = None
            if duration_seconds:
                expires_at = datetime.now(NY_TZ) + timedelta(seconds=duration_seconds)

            evidence_message_url = None
            if evidence and has_valid_media_evidence(evidence):
                try:
                    evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                    if evidence_msg:
                        evidence_message_url = evidence_msg.jump_url
                except Exception as e:
                    logger.error("Evidence Storage Failed", [
                        ("Case ID", case["case_id"]),
                        ("Error", str(e)[:100]),
                    ])

            embed = build_mute_embed(
                user, moderator, duration, reason, mute_count,
                is_extension, evidence_message_url, expires_at
            )
            # Action embeds no longer have buttons - control panel handles all controls
            embed_message = await safe_send(case_thread, embed=embed)

            # Skip "no reason" warning for developer/owner
            is_owner = self.config.owner_id and moderator.id == self.config.owner_id
            if not reason and embed_message and not is_owner:
                action_type = "extension" if is_extension else "mute"
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ No reason was provided for this {action_type}.\n\n"
                    f"**Reply to this message** with the reason."
                )
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type=action_type,
                    )

            # Request evidence if none was provided (not for extensions)
            if not is_extension and not evidence:
                await self._send_evidence_request(
                    case_id=case["case_id"],
                    thread=case_thread,
                    moderator=moderator,
                    action_type="mute",
                )

            if not is_extension and mute_count >= REPEAT_MUTE_THRESHOLD:
                is_permanent = duration.lower() in ("permanent", "perm", "forever")
                if not is_permanent:
                    alert_embed = discord.Embed(
                        title="⚠️ Repeat Offender Alert",
                        color=EmbedColors.WARNING,
                        description=f"**{user.display_name}** has been muted **{mute_count} times**.",
                    )
                    await safe_send(case_thread, embed=alert_embed)

            log_type = "Mute Extended" if is_extension else "Mute Case Created"
            logger.tree(f"Case Log: {log_type}", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case['case_id']),
                ("Duration", duration),
            ], emoji="🔇")

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:200]),
            ])
            return None

    # =========================================================================
    # Warning Logging
    # =========================================================================

    async def log_warn(
        self,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        active_warns: int = 1,
        total_warns: int = 1,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Log a warning action - creates a NEW per-action case."""
        if not self.enabled:
            return None

        logger.tree("Case Log: log_warn Called", [
            ("User", f"{user.name} ({user.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Active Warns", str(active_warns)),
        ], emoji="📝")

        try:
            case = await self._create_action_case(
                user=user,
                moderator=moderator,
                action_type="warn",
                reason=reason,
                evidence=evidence,
            )

            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            self.db.increment_warn_count(user.id, moderator.id)

            evidence_message_url = None
            if evidence and has_valid_media_evidence(evidence):
                try:
                    evidence_msg = await safe_send(case_thread, f"📎 **Evidence:**\n{evidence}")
                    if evidence_msg:
                        evidence_message_url = evidence_msg.jump_url
                except Exception as e:
                    logger.error("Evidence Storage Failed", [
                        ("Case ID", case["case_id"]),
                        ("Error", str(e)[:100]),
                    ])

            # Get mute/ban counts for context
            case_log = self.db.get_case_log(user.id)
            mute_count = case_log.get("mute_count", 0) if case_log else 0
            ban_count = case_log.get("ban_count", 0) if case_log else 0

            embed = build_warn_embed(
                user, moderator, reason, active_warns, total_warns,
                evidence_message_url, mute_count, ban_count
            )
            # Action embeds no longer have buttons - control panel handles all controls
            embed_message = await safe_send(case_thread, embed=embed)

            # Skip "no reason" warning for developer/owner
            is_owner = self.config.owner_id and moderator.id == self.config.owner_id
            if not reason and embed_message and not is_owner:
                warning_message = await safe_send(
                    case_thread,
                    f"⚠️ No reason was provided for this warning.\n\n"
                    f"**Reply to this message** with the reason."
                )
                if warning_message:
                    self.db.create_pending_reason(
                        thread_id=case_thread.id,
                        warning_message_id=warning_message.id,
                        embed_message_id=embed_message.id,
                        moderator_id=moderator.id,
                        target_user_id=user.id,
                        action_type="warn",
                    )

            # Request evidence if none was provided
            if not evidence:
                await self._send_evidence_request(
                    case_id=case["case_id"],
                    thread=case_thread,
                    moderator=moderator,
                    action_type="warn",
                )

            if active_warns >= REPEAT_WARN_THRESHOLD:
                alert_embed = discord.Embed(
                    title="⚠️ Repeat Offender Alert",
                    color=EmbedColors.WARNING,
                    description=f"**{user.display_name}** has **{active_warns} active warnings**.",
                )
                await safe_send(case_thread, embed=alert_embed)

            logger.tree("Case Log: Warning Case Created", [
                ("User", user.name),
                ("Case ID", case['case_id']),
                ("Active Warnings", str(active_warns)),
            ], emoji="⚠️")

            updated_case = self.db.get_case_log(user.id)
            if updated_case:
                self._schedule_profile_update(user.id, updated_case)

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Warning", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:200]),
            ])
            return None

    # =========================================================================
    # Unmute Logging
    # =========================================================================

    async def log_unmute(
        self,
        user_id: int,
        moderator: discord.Member,
        display_name: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
        user_avatar_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Log an unmute action to the active mute case thread."""
        if not self.enabled:
            return None

        logger.tree("Case Log: log_unmute Called", [
            ("User", f"{display_name} ({user_id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
        ], emoji="📝")

        try:
            guild_id = moderator.guild.id

            active_case = self.db.get_active_mute_case(user_id, guild_id)
            if not active_case:
                legacy_case = self.db.get_case_log(user_id)
                if legacy_case:
                    return await self._log_unmute_legacy(
                        user_id, moderator, display_name, reason,
                        source_message_url, user_avatar_url, legacy_case
                    )
                return None

            time_served = None
            original_duration = None
            original_moderator_name = None

            if active_case.get("created_at"):
                muted_at = active_case["created_at"]
                now = datetime.now(NY_TZ).timestamp()
                time_served_seconds = now - muted_at
                time_served = format_duration_precise(time_served_seconds)

                duration_seconds = active_case.get("duration_seconds")
                if duration_seconds:
                    original_duration = format_duration_precise(duration_seconds)
                else:
                    original_duration = "Permanent"

                original_mod_id = active_case.get("moderator_id")
                if original_mod_id and moderator.guild:
                    original_mod = moderator.guild.get_member(original_mod_id)
                    if original_mod:
                        original_moderator_name = original_mod.display_name

            case_thread = await self._get_case_thread(active_case["thread_id"])

            if not case_thread:
                return {"case_id": active_case["case_id"], "thread_id": active_case["thread_id"]}

            # Check if thread is locked (approved case) - unlock it temporarily
            was_locked = case_thread.locked
            if was_locked:
                try:
                    await case_thread.edit(locked=False)
                except discord.HTTPException as e:
                    log_http_error(e, "Thread Unlock", [("Thread", str(case_thread.id))])

            embed = build_unmute_embed(
                moderator, reason, user_avatar_url, time_served,
                original_duration, original_moderator_name
            )
            # Action embeds no longer have buttons - control panel handles all controls
            embed_message = await safe_send(case_thread, embed=embed)

            # Check if unmute was early (before duration expired) and no reason provided
            duration_seconds = active_case.get("duration_seconds")
            is_early_unmute = False
            if duration_seconds and active_case.get("created_at"):
                muted_at = active_case["created_at"]
                now = datetime.now(NY_TZ).timestamp()
                time_served_seconds = now - muted_at
                is_early_unmute = time_served_seconds < duration_seconds

            # No longer warn for early unmutes without reason

            # Update control panel to show resolved status
            # Note: Don't pass moderator - preserve original moderator who took action
            await self._update_control_panel(
                case_id=active_case["case_id"],
                case_thread=case_thread,
                new_status="resolved",
            )

            # Re-lock the thread if it was locked
            if was_locked:
                try:
                    await case_thread.edit(locked=True)
                except discord.HTTPException as e:
                    log_http_error(e, "Thread Re-lock", [("Thread", str(case_thread.id))])

            self.db.resolve_case(
                case_id=active_case["case_id"],
                resolved_by=moderator.id,
                reason=reason,
            )

            logger.tree("Case Log: Mute Case Resolved (Unmute)", [
                ("User", f"{display_name} ({user_id})"),
                ("Case ID", active_case["case_id"]),
                ("Time Served", time_served or "Unknown"),
            ], emoji="🔊")

            return {"case_id": active_case["case_id"], "thread_id": active_case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unmute", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _log_unmute_legacy(
        self,
        user_id: int,
        moderator: discord.Member,
        display_name: str,
        reason: Optional[str],
        source_message_url: Optional[str],
        user_avatar_url: Optional[str],
        case: dict,
    ) -> Optional[dict]:
        """Legacy unmute logging for backward compatibility."""
        last_mute_info = self.db.get_last_mute_info(user_id)

        time_served = None
        original_duration = None
        original_moderator_name = None

        if last_mute_info and last_mute_info.get("last_mute_at"):
            muted_at = last_mute_info["last_mute_at"]
            now_ts = datetime.now(NY_TZ).timestamp()
            time_served_seconds = now_ts - muted_at
            time_served = format_duration_precise(time_served_seconds)
            original_duration = last_mute_info.get("last_mute_duration") or "Unknown"

            original_mod_id = last_mute_info.get("last_mute_moderator_id")
            if original_mod_id and moderator.guild:
                original_mod = moderator.guild.get_member(original_mod_id)
                if original_mod:
                    original_moderator_name = original_mod.display_name

        case_thread = await self._get_case_thread(case["thread_id"])

        if case_thread:
            embed = build_unmute_embed(
                moderator, reason, user_avatar_url, time_served,
                original_duration, original_moderator_name
            )
            # Action embeds no longer have buttons - control panel handles all controls
            await safe_send(case_thread, embed=embed)

            self.db.update_last_unmute(user_id)

            logger.tree("Case Log: Unmute Logged (Legacy)", [
                ("User", f"{display_name} ({user_id})"),
                ("Case ID", case['case_id']),
            ], emoji="🔊")

        return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

    # =========================================================================
    # Mute Expired
    # =========================================================================

    async def log_mute_expired(
        self,
        user_id: int,
        display_name: str,
        user_avatar_url: Optional[str] = None,
        guild_id: Optional[int] = None,
    ) -> None:
        """Log an auto-unmute (expired mute)."""
        if not self.enabled:
            return

        logger.tree("Case Log: log_mute_expired Called", [
            ("User", f"{display_name} ({user_id})"),
            ("Guild ID", str(guild_id) if guild_id else "None"),
        ], emoji="📝")

        try:
            if guild_id:
                active_case = self.db.get_active_mute_case(user_id, guild_id)
                if active_case:
                    case_thread = await self._get_case_thread(active_case["thread_id"])
                    if case_thread:
                        embed = build_expired_embed(user_avatar_url)
                        await safe_send(case_thread, embed=embed)

                        self.db.resolve_case(
                            case_id=active_case["case_id"],
                            resolved_by=None,
                            reason="Mute expired",
                        )

                        logger.tree("Case Log: Mute Case Expired", [
                            ("User", f"{display_name} ({user_id})"),
                            ("Case ID", active_case["case_id"]),
                        ], emoji="⏰")
                        return

            # Legacy fallback
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = build_expired_embed(user_avatar_url)
                await safe_send(case_thread, embed=embed)

                logger.tree("Case Log: Mute Expired (Legacy)", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Expired", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Member Left While Muted
    # =========================================================================

    async def log_member_left_muted(
        self,
        user_id: int,
        display_name: str,
        muted_at: Optional[float] = None,
        avatar_url: Optional[str] = None,
    ) -> None:
        """Log when a member leaves while muted."""
        if not self.enabled:
            return

        logger.tree("Case Log: log_member_left_muted Called", [
            ("User", f"{display_name} ({user_id})"),
        ], emoji="📝")

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                duration_str = None
                if muted_at:
                    now_ts = datetime.now(NY_TZ).timestamp()
                    muted_seconds = now_ts - muted_at
                    duration_str = format_duration_precise(muted_seconds)

                embed = build_member_left_embed(display_name, duration_str, avatar_url)
                await safe_send(case_thread, embed=embed)

                logger.tree("Case Log: Member Left While Muted", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Left After", duration_str or "Unknown"),
                ], emoji="🚪")

        except Exception as e:
            logger.error("Case Log: Failed To Log Member Left", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Mute Evasion Return
    # =========================================================================

    async def log_mute_evasion_return(
        self,
        member: discord.Member,
        moderator_ids: list,
    ) -> None:
        """Log when a muted user rejoins the server."""
        if not self.enabled:
            return

        logger.tree("Case Log: log_mute_evasion_return Called", [
            ("User", f"{member.name} ({member.id})"),
            ("Mods To Ping", str(len(moderator_ids))),
        ], emoji="📝")

        try:
            case = self.db.get_case_log(member.id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = build_mute_evasion_embed(member)
                # Action embeds no longer have buttons - control panel handles all controls
                await safe_send(case_thread, embed=embed)

                logger.tree("Case Log: Mute Evasion Return", [
                    ("User", member.name),
                    ("ID", str(member.id)),
                ], emoji="⚠️")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Evasion", [
                ("User ID", str(member.id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Muted VC Violation
    # =========================================================================

    async def log_muted_vc_violation(
        self,
        user_id: int,
        display_name: str,
        channel_name: str,
        avatar_url: Optional[str] = None,
    ) -> None:
        """Log when a muted user attempts to join voice."""
        if not self.enabled:
            return

        logger.tree("Case Log: log_muted_vc_violation Called", [
            ("User", f"{display_name} ({user_id})"),
            ("Channel", channel_name),
        ], emoji="📝")

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = build_vc_violation_embed(display_name, channel_name, avatar_url)
                # Action embeds no longer have buttons - control panel handles all controls
                await safe_send(case_thread, embed=embed)

                logger.tree("Case Log: VC Violation", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Channel", channel_name),
                    ("Case ID", case['case_id']),
                ], emoji="🔇")

        except Exception as e:
            logger.error("Case Log: Failed To Log VC Violation", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])


__all__ = ["CaseLogActionsMixin"]
