"""
AzabBot - Prison View Builders
==============================

Functions for building button views for prison embeds.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.services.appeals.constants import MIN_APPEALABLE_MUTE_DURATION

if TYPE_CHECKING:
    from src.bot import AzabBot
    from sqlite3 import Row


async def build_appeal_view(
    bot: "AzabBot",
    member: discord.Member,
    mute_record: Optional["Row"],
) -> Optional[discord.ui.View]:
    """
    Build view for prison intro embed with appeal and unjail buttons.

    Includes:
    - Booster Unjail button: If member is a booster with daily card available
    - Coin Unjail button: Pay to get out of jail
    - Appeal button: If mute >= 1 hour or permanent, and case exists

    Args:
        bot: Bot instance.
        member: The muted member.
        mute_record: Active mute record from database.

    Returns:
        View with buttons, or None if no buttons apply.
    """
    view = discord.ui.View(timeout=None)
    has_buttons = False

    # -----------------------------------------------------------------
    # Check Mute Duration First (required for all buttons)
    # Unjail, Coin Unjail, and Appeal only show for mutes >= 1 hour or permanent
    # -----------------------------------------------------------------
    if not mute_record:
        logger.tree("Buttons Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "No mute record found"),
        ], emoji="ℹ️")
        return None

    is_permanent = mute_record["expires_at"] is None
    is_long_enough = False

    if not is_permanent and mute_record["expires_at"] and mute_record["muted_at"]:
        # Ensure both values are floats (database may store as string)
        expires_at = float(mute_record["expires_at"])
        muted_at = float(mute_record["muted_at"])
        duration_seconds = int(expires_at - muted_at)
        is_long_enough = duration_seconds >= MIN_APPEALABLE_MUTE_DURATION

    # Short mutes (< 1 hour) don't get any buttons
    if not is_permanent and not is_long_enough:
        logger.tree("Buttons Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", f"Mute < {MIN_APPEALABLE_MUTE_DURATION // 3600}h"),
        ], emoji="ℹ️")
        return None

    # -----------------------------------------------------------------
    # Booster Unjail Button (daily "Get Out of Jail Free" card)
    # Only for mutes >= 1 hour or permanent
    # -----------------------------------------------------------------
    is_booster = member.premium_since is not None

    if is_booster:
        try:
            from src.services.tickets import BoosterUnjailButton

            # Check if daily card is available
            can_use = bot.db.can_use_unjail_card(member.id, member.guild.id)

            if can_use:
                unjail_btn = BoosterUnjailButton(member.id, member.guild.id)
                view.add_item(unjail_btn)

                logger.tree("Unjail Button Added", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Booster Since", str(member.premium_since.date())),
                    ("Mute Type", "Permanent" if is_permanent else f">= {MIN_APPEALABLE_MUTE_DURATION // 3600}h"),
                    ("Appeal Button", "Skipped (can self-unjail)"),
                ], emoji="🔓")

                # Booster can self-unjail, no appeal button needed
                return view
            else:
                # Card already used today - fall through to appeal button
                reset_at = bot.db.get_unjail_card_cooldown(member.id, member.guild.id)
                logger.tree("Unjail Button Skipped", [
                    ("User", f"{member.name} ({member.id})"),
                    ("Reason", "Daily card already used"),
                    ("Resets At", f"<t:{int(reset_at)}:R>" if reset_at else "Unknown"),
                ], emoji="ℹ️")

        except ImportError as e:
            logger.error("Unjail Button Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Location", "Import BoosterUnjailButton"),
                ("Error", str(e)[:100]),
            ])
        except Exception as e:
            logger.error("Unjail Button Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Location", "Button creation"),
                ("Error", str(e)[:100]),
            ])

    # -----------------------------------------------------------------
    # Coin Unjail Button (pay to get out of jail)
    # Shows for: non-boosters OR boosters who used their daily card
    # If user can afford it, skip the appeal button (pay or wait)
    # -----------------------------------------------------------------
    can_afford_unjail = False

    try:
        from src.services.jawdat_economy import CoinUnjailButton, get_unjail_cost_for_user, get_user_balance

        # Get tiered cost based on weekly offense count and duration
        cost, offense_count, breakdown = get_unjail_cost_for_user(member.id, member.guild.id)

        # Check if user can afford the unjail cost
        user_balance = await get_user_balance(member.id)
        can_afford_unjail = user_balance is not None and user_balance >= cost

        coin_btn = CoinUnjailButton(member.id, member.guild.id)
        view.add_item(coin_btn)
        has_buttons = True

        logger.tree("Coin Unjail Button Added", [
            ("User", f"{member.name} ({member.id})"),
            ("Offense #", str(offense_count)),
            ("Cost", f"{cost:,} coins"),
            ("Balance", f"{user_balance:,}" if user_balance is not None else "Unknown"),
            ("Can Afford", "Yes" if can_afford_unjail else "No"),
            ("Mute Type", "Permanent" if is_permanent else f">= {MIN_APPEALABLE_MUTE_DURATION // 3600}h"),
        ], emoji="🪙")

        # If user can afford to pay, no appeal button needed
        if can_afford_unjail:
            logger.tree("Appeal Button Skipped", [
                ("User", f"{member.name} ({member.id})"),
                ("Reason", "Can afford coin unjail"),
                ("Cost", f"{cost:,}"),
                ("Balance", f"{user_balance:,}"),
            ], emoji="💰")
            return view

    except ImportError as e:
        logger.error("Coin Unjail Button Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Location", "Import CoinUnjailButton"),
            ("Error", str(e)[:100]),
        ])
    except Exception as e:
        logger.error("Coin Unjail Button Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Location", "Button creation"),
            ("Error", str(e)[:100]),
        ])

    # -----------------------------------------------------------------
    # Appeal Button (for long/permanent mutes when other options not available)
    # -----------------------------------------------------------------
    # Mute duration already validated above, just need case_id
    is_permanent = mute_record["expires_at"] is None
    is_long_enough = False

    if not is_permanent and mute_record["expires_at"] and mute_record["muted_at"]:
        # Ensure both values are floats (database may store as string)
        expires_at = float(mute_record["expires_at"])
        muted_at = float(mute_record["muted_at"])
        duration_seconds = int(expires_at - muted_at)
        is_long_enough = duration_seconds >= MIN_APPEALABLE_MUTE_DURATION

    if not is_permanent and not is_long_enough:
        logger.tree("Appeal Button Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", f"Mute < {MIN_APPEALABLE_MUTE_DURATION // 3600}h"),
        ], emoji="ℹ️")
        return view if has_buttons else None

    # Get case_id from cases table
    try:
        case_data = bot.db.get_active_mute_case(member.id, member.guild.id)
    except Exception as e:
        logger.error("Appeal Button Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Location", "get_active_mute_case"),
            ("Error", str(e)[:100]),
        ])
        return view if has_buttons else None

    if not case_data or not case_data.get("case_id"):
        logger.warning("Appeal Button Skipped", [
            ("User", f"{member.name} ({member.id})"),
            ("Reason", "No active case found"),
        ])
        return view if has_buttons else None

    case_id: str = case_data["case_id"]

    # Add appeal button
    try:
        from src.services.tickets import MuteAppealButton

        appeal_btn = MuteAppealButton(case_id, member.id)
        view.add_item(appeal_btn)
        has_buttons = True

        logger.tree("Appeal Button Added", [
            ("User", f"{member.name} ({member.id})"),
            ("Case ID", case_id),
            ("Mute Type", "Permanent" if is_permanent else "Timed"),
            ("Action", "Opens ticket"),
        ], emoji="📝")

    except ImportError as e:
        logger.error("Appeal Button Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Location", "Import MuteAppealButton"),
            ("Error", str(e)[:100]),
        ])
    except Exception as e:
        logger.error("Appeal Button Failed", [
            ("User", f"{member.name} ({member.id})"),
            ("Location", "Button creation"),
            ("Error", str(e)[:100]),
        ])

    return view if has_buttons else None


__all__ = ["build_appeal_view"]
