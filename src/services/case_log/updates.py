"""
AzabBot - Profile & Control Panel Updates
=========================================

Mixin for profile stats and control panel updates.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.core.constants import PREVIOUS_NAMES_LIMIT
from src.utils.retry import safe_fetch_message, safe_edit
from src.utils.async_utils import create_safe_task

from .constants import PROFILE_UPDATE_DEBOUNCE
from .views import CaseControlPanelView
from .embeds import build_control_panel_embed

if TYPE_CHECKING:
    from .service import CaseLogService


class CaseLogUpdatesMixin:
    """Mixin for profile stats and control panel updates."""

    # =========================================================================
    # Profile Updates (Debounced)
    # =========================================================================

    def _schedule_profile_update(self: "CaseLogService", user_id: int, case: dict) -> None:
        """Schedule a debounced profile stats update."""
        self._pending_profile_updates[user_id] = case

        if self._profile_update_task is None or self._profile_update_task.done():
            self._profile_update_task = create_safe_task(
                self._process_profile_updates(), "Case Log Profile Updates"
            )

    async def _process_profile_updates(self: "CaseLogService") -> None:
        """Process all pending profile updates after debounce delay."""
        await asyncio.sleep(PROFILE_UPDATE_DEBOUNCE)

        pending = self._pending_profile_updates.copy()
        self._pending_profile_updates.clear()

        if not pending:
            return

        success_count = 0
        fail_count = 0
        for user_id, case in pending.items():
            try:
                await self._update_profile_stats(user_id, case)
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.warning("Profile Stats Update Failed", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)[:50]),
                ])

        if success_count > 0 or fail_count > 0:
            logger.tree("PROFILE STATS UPDATED", [
                ("Processed", str(success_count)),
                ("Failed", str(fail_count)),
            ], emoji="📊")

    async def _update_profile_stats(self: "CaseLogService", user_id: int, case: dict) -> None:
        """Update the pinned profile message with current stats."""
        try:
            case_thread = await self._get_case_thread(case["thread_id"])
            if not case_thread:
                return

            profile_msg = None

            if case.get("profile_message_id"):
                profile_msg = await safe_fetch_message(case_thread, case["profile_message_id"])

            if not profile_msg:
                try:
                    pinned = await case_thread.pins()
                    for msg in pinned:
                        if msg.embeds and msg.embeds[0].title == "📋 User Profile":
                            profile_msg = msg
                            self.db.set_profile_message_id(user_id, msg.id)
                            break
                except Exception:
                    pass

            if not profile_msg:
                return

            main_guild_id = self.config.logging_guild_id
            guild = self.bot.get_guild(main_guild_id) if main_guild_id else case_thread.guild
            member = guild.get_member(user_id) if guild else None

            embed = discord.Embed(
                title="📋 User Profile",
                color=EmbedColors.INFO,
                timestamp=datetime.now(NY_TZ),
            )

            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="Username", value=f"{member.name}", inline=True)
                embed.add_field(name="Display Name", value=f"{member.display_name}", inline=True)
            else:
                try:
                    user = await self.bot.fetch_user(user_id)
                    embed.set_thumbnail(url=user.display_avatar.url)
                    embed.add_field(name="Username", value=f"{user.name}", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ Left Server", inline=True)
                except discord.NotFound:
                    embed.add_field(name="Username", value=f"Unknown", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ User Not Found", inline=True)

            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

            mute_count = case.get("mute_count", 0)
            ban_count = case.get("ban_count", 0)

            embed.add_field(name="Total Mutes", value=f"`{mute_count}`", inline=True)
            embed.add_field(name="Total Bans", value=f"`{ban_count}`", inline=True)

            last_mute = case.get("last_mute_at")
            last_ban = case.get("last_ban_at")
            if last_mute or last_ban:
                last_action = max(filter(None, [last_mute, last_ban]))
                embed.add_field(
                    name="Last Action",
                    value=f"<t:{int(last_action)}:R>",
                    inline=True,
                )

            if mute_count >= 3 or ban_count >= 2:
                warnings = []
                if mute_count >= 3:
                    warnings.append(f"{mute_count} mutes")
                if ban_count >= 2:
                    warnings.append(f"{ban_count} bans")
                embed.add_field(
                    name="⚠️ Repeat Offender",
                    value=f"{', '.join(warnings)}",
                    inline=False,
                )

            previous_names = self.db.get_previous_names(user_id, limit=PREVIOUS_NAMES_LIMIT)
            if previous_names:
                names_str = ", ".join(f"`{name}`" for name in previous_names)
                embed.add_field(name="Previous Names", value=names_str, inline=False)

            await safe_edit(profile_msg, embed=embed)

        except Exception as e:
            logger.warning("Profile Stats Update Failed", [
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Control Panel Updates
    # =========================================================================

    async def _update_control_panel(
        self: "CaseLogService",
        case_id: str,
        case_thread: discord.Thread,
        new_status: Optional[str] = None,
        user: Optional[discord.Member] = None,
        moderator: Optional[discord.Member] = None,
        transcript_url: Optional[str] = None,
    ) -> bool:
        """
        Update the control panel message in place.

        Args:
            case_id: The case ID.
            case_thread: The case thread.
            new_status: New status (open, resolved, expired, approved).
            user: The target user.
            moderator: The moderator.
            transcript_url: URL to the transcript (for approved cases).

        Returns:
            True if updated successfully.
        """
        try:
            # Get case data
            case = self.db.get_case(case_id)
            if not case:
                logger.warning("Control Panel Update - Case Not Found", [
                    ("Case ID", case_id),
                ])
                return False

            control_panel_msg_id = case.get("control_panel_message_id")
            if not control_panel_msg_id:
                # No control panel, try to find it in pinned messages
                try:
                    pinned = await case_thread.pins()
                    for msg in pinned:
                        if msg.embeds and msg.embeds[0].title and "Control Panel" in msg.embeds[0].title:
                            control_panel_msg_id = msg.id
                            self.db.set_case_control_panel_message(case_id, msg.id)
                            logger.tree("Control Panel Found In Pins", [
                                ("Case ID", case_id),
                                ("Message ID", str(msg.id)),
                            ], emoji="📌")
                            break
                except Exception as e:
                    logger.warning("Control Panel Pin Search Failed", [
                        ("Case ID", case_id),
                        ("Error", str(e)[:50]),
                    ])

            if not control_panel_msg_id:
                logger.warning("Control Panel Not Found", [
                    ("Case ID", case_id),
                    ("Thread ID", str(case_thread.id)),
                ])
                return False

            # Fetch the message
            control_msg = await safe_fetch_message(case_thread, control_panel_msg_id)
            if not control_msg:
                logger.warning("Control Panel Message Fetch Failed", [
                    ("Case ID", case_id),
                    ("Message ID", str(control_panel_msg_id)),
                ])
                return False

            # Determine status
            status = new_status or case.get("status", "active")

            # Build updated embed
            control_embed = build_control_panel_embed(
                case=case,
                user=user,
                moderator=moderator,
                status=status,
            )

            # Build updated view
            action_type = case.get("action_type", "")
            is_mute = action_type in ("mute", "timeout")

            # Check if evidence exists for this case
            evidence_urls = self.db.get_case_evidence(case_id)
            has_evidence = len(evidence_urls) > 0

            # Build transcript URL if approved and not provided
            final_transcript_url = transcript_url
            if status == "approved" and not final_transcript_url:
                if self.config.case_transcript_base_url:
                    final_transcript_url = f"{self.config.case_transcript_base_url}/{case_id}"

            control_view = CaseControlPanelView(
                user_id=case.get("user_id"),
                guild_id=case.get("guild_id"),
                case_id=case_id,
                case_thread_id=case_thread.id,
                status=status,
                is_mute=is_mute,
                has_evidence=has_evidence,
                transcript_url=final_transcript_url,
            )

            # Edit the message
            await safe_edit(control_msg, embed=control_embed, view=control_view)

            logger.tree("Control Panel Updated", [
                ("Case ID", case_id),
                ("Status", status),
                ("Transcript URL", "Yes" if final_transcript_url else "No"),
            ], emoji="🎛️")

            return True

        except Exception as e:
            logger.warning("Control Panel Update Failed", [
                ("Case ID", case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])
            return False


__all__ = ["CaseLogUpdatesMixin"]
