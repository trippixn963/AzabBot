"""
AzabBot - Coin Unjail Button
============================

Persistent button for paying coins to get out of prison.
Uses DynamicItem pattern for persistence across bot restarts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING, Any, Optional

import discord

from src.core.config import get_config
from src.core.logger import logger

from .constants import COINS_EMOJI_NAME, COINS_EMOJI_ID, UNJAIL_BASE_COST, get_unjail_cost_for_user
from .api import process_coin_unjail

if TYPE_CHECKING:
    from src.core.config import Config
    from src.core.database import Database


# Custom emoji for coins button
COINS_EMOJI = discord.PartialEmoji(name=COINS_EMOJI_NAME, id=COINS_EMOJI_ID)


class CoinUnjailButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"coin_unjail:(?P<user_id>\d+):(?P<guild_id>\d+)"
):
    """
    Persistent button on prison intro embed to buy unjail with Jawdat coins.

    Available to all users when:
    - User is muted for >= 1 hour
    - User has enough coins in JawdatBot economy
    - User is not a booster with available free card (boosters see free card instead)

    Cost is tiered based on weekly offense count:
    - 1st offense: 500 coins
    - 2nd offense: 1,000 coins
    - 3rd offense: 2,500 coins
    - 4th+ offense: 5,000 coins
    """

    def __init__(self, user_id: int, guild_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Buy Unjail",
                style=discord.ButtonStyle.secondary,
                custom_id=f"coin_unjail:{user_id}:{guild_id}",
                emoji=COINS_EMOJI,
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "CoinUnjailButton":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle coin unjail button click - deducts coins and removes mute."""
        # Get the tiered cost based on weekly offense count AND duration
        cost, offense_count, breakdown = get_unjail_cost_for_user(self.user_id, self.guild_id)

        log_details = [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Expected User", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
            ("Offense #", str(offense_count)),
        ]

        if breakdown:
            log_details.extend([
                ("Duration", f"{breakdown['duration_hours']:.1f}h ({breakdown['duration_tier']})"),
                ("Multiplier", f"×{breakdown['multiplier']}"),
            ])

        log_details.append(("Cost", f"{cost:,} coins"))

        logger.tree("Coin Unjail Button Clicked", log_details, emoji="🪙")

        # Only the muted user can use this
        if interaction.user.id != self.user_id:
            logger.warning("Coin Unjail Wrong User", [
                ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(self.user_id)),
            ])
            await interaction.response.send_message(
                "You can only use your own Unjail button.",
                ephemeral=True,
            )
            return

        # Ensure we have a Member object (not in DMs)
        if not isinstance(interaction.user, discord.Member):
            logger.warning("Coin Unjail DM Attempt", [
                ("User", f"{interaction.user.name} ({interaction.user.id})"),
                ("Expected User", str(self.user_id)),
            ])
            await interaction.response.send_message(
                "This button can only be used in the server.",
                ephemeral=True,
            )
            return

        member = interaction.user
        await interaction.response.defer(ephemeral=True)

        # Get mute info for logging
        from src.core.database import get_db
        db = get_db()
        mute_record = db.get_active_mute(member.id, self.guild_id)
        mute_reason = mute_record["reason"] if mute_record else None

        # Process payment via jawdat_economy service (cost is tiered)
        success, result = await process_coin_unjail(member, mute_reason)

        # Get cost and offense count from result
        actual_cost = result.get("cost", cost)
        actual_offense = result.get("offense_count", offense_count)

        if not success:
            await self._handle_payment_failure(interaction, member, result, actual_cost)
            return

        # Get new total balance (wallet + bank)
        new_balance = result.get("new_total", 0)

        # Payment succeeded - remove mute
        await self._process_unmute(
            interaction, member, mute_reason, new_balance, actual_cost, actual_offense, db
        )

    async def _handle_payment_failure(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        result: dict[str, Any],
        cost: int,
    ) -> None:
        """Handle payment failure with appropriate user feedback."""
        error = result.get("error", "unknown")

        if error == "insufficient_funds":
            total = result.get("total", 0)
            shortfall = result.get("shortfall", cost)
            breakdown = result.get("breakdown")

            logger.tree("Coin Unjail Payment Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", "Insufficient funds"),
                ("Cost", f"{cost:,}"),
                ("Balance", f"{total:,}"),
                ("Shortfall", f"{shortfall:,}"),
            ], emoji="💸")

            await interaction.followup.send(
                f"<:coins:{COINS_EMOJI_ID}> **Insufficient coins!**\n"
                f"Cost: **{cost:,}** coins\n"
                f"Your balance: **{total:,}** coins\n"
                f"You need **{shortfall:,}** more coins.\n\n"
                f"-# Earn coins by chatting and playing games in Jawdat Casino!",
                ephemeral=True,
            )
        elif error == "not_configured":
            logger.warning("Coin Unjail Payment Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", "Economy API not configured"),
            ])
            await interaction.followup.send(
                "Coin unjail is not available at this time. Please use the appeal button.",
                ephemeral=True,
            )
        elif error == "network_error":
            logger.warning("Coin Unjail Payment Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", "Network error"),
            ])
            await interaction.followup.send(
                "Failed to connect to the economy system. Please try again later.",
                ephemeral=True,
            )
        else:
            logger.warning("Coin Unjail Payment Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", error),
            ])
            await interaction.followup.send(
                f"Failed to process payment: {error}",
                ephemeral=True,
            )

    async def _process_unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        mute_reason: Optional[str],
        new_balance: int,
        cost: int,
        offense_count: int,
        db: "Database",
    ) -> None:
        """Process the unmute after successful payment."""
        config = get_config()
        muted_role = interaction.guild.get_role(config.muted_role_id)

        if not muted_role:
            logger.error("Coin Unjail Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Reason", "Muted role not found"),
                ("Note", "Coins already deducted!"),
            ])
            await interaction.followup.send(
                "Payment processed but failed to unjail - muted role not found.\n"
                "Please contact staff for a manual unmute. Your coins have been charged.",
                ephemeral=True,
            )
            return

        if muted_role not in member.roles:
            logger.warning("Coin Unjail Not Muted", [
                ("User", f"{member.name} ({member.id})"),
                ("Note", "User paid but wasn't muted - coins deducted"),
            ])
            await interaction.followup.send(
                "You're not currently muted! (Payment was processed)",
                ephemeral=True,
            )
            return

        try:
            # Remove the muted role
            await member.remove_roles(
                muted_role,
                reason=f"Coin Unjail purchased by {member.name} ({cost} coins)"
            )

            # Update database
            db.remove_mute(
                user_id=member.id,
                guild_id=self.guild_id,
                moderator_id=member.id,
                reason=f"Coin Unjail ({cost:,} coins)",
            )

            db.log_moderation_action(
                user_id=member.id,
                guild_id=self.guild_id,
                moderator_id=member.id,
                action_type="unmute",
                action_source="coin_unjail",
                reason=f"Coin Unjail ({cost:,} coins)",
                details={"original_reason": mute_reason, "cost": cost},
            )

            logger.tree("Coin Unjail Success", [
                ("User", f"{member.name} ({member.id})"),
                ("Offense #", str(offense_count)),
                ("Cost", f"{cost:,} coins"),
                ("Original Reason", (mute_reason or "None")[:50]),
            ], emoji="🔓")

            await interaction.followup.send(
                f"<:coins:{COINS_EMOJI_ID}> **Unjail Purchased!**\n"
                f"You paid **{cost:,}** coins to get out of jail.\n"
                f"New balance: **{new_balance:,}** coins",
                ephemeral=True,
            )

            # Post to prison channel
            await self._post_prison_announcement(interaction, member, cost, config)

            # Add note to case thread
            await self._post_case_note(interaction, member, cost, db)

            # Update original embed
            await self._update_embed(interaction, member)

            # Send release announcement to general chat
            await self._send_release_announcement(interaction, member, cost)

        except discord.Forbidden:
            logger.error("Coin Unjail Failed (Permissions)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
                ("Note", "Coins already deducted!"),
            ])
            await interaction.followup.send(
                "Payment processed but failed to remove muted role - missing permissions.\n"
                "Please contact staff for a manual unmute. Your coins have been charged.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.error("Coin Unjail Failed (HTTP)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
                ("Error", str(e)[:100]),
                ("Note", "Coins already deducted!"),
            ])
            await interaction.followup.send(
                f"Payment processed but failed to unjail: {e}\n"
                f"Please contact staff. Your coins have been charged.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Coin Unjail Failed (Unexpected)", [
                ("User", f"{member.name} ({member.id})"),
                ("Guild", str(self.guild_id)),
                ("Error", str(e)[:100]),
                ("Note", "Coins may have been deducted!"),
            ])
            try:
                await interaction.followup.send(
                    "An unexpected error occurred. Please contact staff if your coins were charged.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

    async def _post_prison_announcement(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        cost: int,
        config: "Config",
    ) -> None:
        """Post announcement to prison channel."""
        try:
            if not config.prison_channel_ids:
                logger.debug("Prison Announcement Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "No prison channel configured"),
                ])
                return

            prison_channel = interaction.guild.get_channel(
                next(iter(config.prison_channel_ids))
            )

            if not prison_channel:
                logger.warning("Prison Announcement Failed", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "Prison channel not found"),
                ])
                return

            await prison_channel.send(
                f"<:coins:{COINS_EMOJI_ID}> **{member.mention} bought their way out of jail!**\n"
                f"-# They paid {cost:,} coins to be released."
            )

            logger.tree("Prison Announcement Posted", [
                ("User", f"{member.name} ({member.id})"),
                ("Channel", f"#{prison_channel.name}"),
                ("Cost", f"{cost:,} coins"),
            ], emoji="📢")

        except Exception as e:
            logger.warning("Prison Announcement Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])

    async def _post_case_note(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        cost: int,
        db: "Database",
    ) -> None:
        """Add note to case thread."""
        try:
            bot = interaction.client
            if not hasattr(bot, "case_log_service") or not bot.case_log_service:
                logger.debug("Case Note Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "Case log service not available"),
                ])
                return

            # Find the active mute case - check ops guild first, then main guild
            config = get_config()
            case_data = None
            for guild_id in [config.ops_guild_id, config.main_guild_id, self.guild_id]:
                if guild_id:
                    case_data = db.get_active_mute_case(member.id, guild_id)
                    if case_data and case_data.get("thread_id"):
                        break

            if not case_data or not case_data.get("thread_id"):
                logger.debug("Case Note Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "No active case thread found"),
                ])
                return

            # Use the guild_id from the case record itself
            case_guild_id = case_data.get("guild_id")
            case_guild = bot.get_guild(case_guild_id) if case_guild_id else None
            if not case_guild:
                logger.debug("Case Note Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", f"Case guild {case_guild_id} not found"),
                ])
                return

            thread = case_guild.get_thread(case_data["thread_id"])
            if not thread:
                try:
                    thread = await case_guild.fetch_channel(case_data["thread_id"])
                except discord.NotFound:
                    logger.warning("Case Note Failed", [
                        ("User", f"{member.name} ({member.id})"),
                        ("Thread ID", str(case_data["thread_id"])),
                        ("Reason", "Thread not found"),
                    ])
                    return

            if thread:
                await thread.send(
                    f"<:coins:{COINS_EMOJI_ID}> **Coin Unjail Purchased**\n"
                    f"{member.mention} paid **{cost:,}** coins to release themselves from prison."
                )

                logger.tree("Case Note Posted", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Case ID", case_data.get("case_id", "Unknown")),
                    ("Thread", f"#{thread.name}"),
                    ("Cost", f"{cost:,} coins"),
                ], emoji="📝")

        except Exception as e:
            logger.warning("Case Note Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])

    async def _update_embed(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """Update the original embed to show released status."""
        try:
            original_message = interaction.message
            if not original_message:
                logger.debug("Embed Update Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "No original message"),
                ])
                return

            embed = original_message.embeds[0] if original_message.embeds else None
            if not embed:
                logger.debug("Embed Update Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "No embed on message"),
                ])
                return

            embed.title = f"<:coins:{COINS_EMOJI_ID}> Released (Paid Unjail)"
            embed.color = 0x57F287  # Green
            await original_message.edit(embed=embed, view=None)

            logger.tree("Embed Updated", [
                ("User", f"{member.name} ({member.id})"),
                ("New Title", "Released (Paid Unjail)"),
                ("Buttons", "Removed"),
            ], emoji="✏️")

        except Exception as e:
            logger.warning("Embed Update Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])

    async def _send_release_announcement(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        cost: int,
    ) -> None:
        """Send release announcement to general chat."""
        try:
            # Import here to avoid circular import (prison handler imports services)
            from src.handlers.prison import send_release_announcement, ReleaseType

            await send_release_announcement(
                bot=interaction.client,
                member=member,
                release_type=ReleaseType.COIN_UNJAIL,
                cost=cost,
            )
            # Note: send_release_announcement handles its own logging
        except Exception as e:
            logger.warning("Release Announcement Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])
