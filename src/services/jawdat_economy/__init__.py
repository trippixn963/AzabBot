"""
AzabBot - Jawdat Economy Service
================================

Integrates with JawdatBot's economy system for coin-based features.
Currently supports coin unjail (pay to get out of prison).

Unjail Cost Tiers (based on weekly offense count):
- 1st offense: 500 coins
- 2nd offense: 1,000 coins
- 3rd offense: 2,500 coins
- 4th+ offense: 5,000 coins

Resets every Sunday at midnight EST (same as XP drain).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .constants import (
    UNJAIL_COST_TIERS,
    UNJAIL_OFFENSE_TIERS,
    UNJAIL_BASE_COST,
    COINS_EMOJI_NAME,
    COINS_EMOJI_ID,
    get_unjail_cost,
    get_offense_base_cost,
    get_duration_multiplier,
    calculate_unjail_cost,
    get_unjail_cost_for_user,
)
from .api import (
    deduct_coins,
    get_user_balance,
    process_coin_unjail,
)
from .button import CoinUnjailButton

if TYPE_CHECKING:
    from src.bot import AzabBot


def setup_jawdat_economy(bot: "AzabBot") -> None:
    """Register jawdat economy dynamic items."""
    bot.add_dynamic_items(CoinUnjailButton)


__all__ = [
    # Setup
    "setup_jawdat_economy",
    # Constants
    "UNJAIL_COST_TIERS",
    "UNJAIL_OFFENSE_TIERS",
    "UNJAIL_BASE_COST",
    "COINS_EMOJI_NAME",
    "COINS_EMOJI_ID",
    # Functions
    "get_unjail_cost",
    "get_offense_base_cost",
    "get_duration_multiplier",
    "calculate_unjail_cost",
    "get_unjail_cost_for_user",
    "deduct_coins",
    "get_user_balance",
    "process_coin_unjail",
    # Button
    "CoinUnjailButton",
]
