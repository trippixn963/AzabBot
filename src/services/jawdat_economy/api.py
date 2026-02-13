"""
AzabBot - Jawdat Economy API
============================

HTTP API functions for interacting with JawdatBot's economy system.
Uses shared HTTP session with connection pooling and retry logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Dict, Optional, Tuple

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.utils.http import http_session, FAST_TIMEOUT

from .constants import get_unjail_cost_for_user


# =============================================================================
# API Functions
# =============================================================================

async def deduct_coins(
    user_id: int,
    amount: int,
    reason: str = "Deduction",
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Deduct coins from a user via JawdatBot API.

    Uses shared HTTP session with connection pooling and retry logic.
    Deducts from wallet first, then bank if wallet insufficient.

    Args:
        user_id: Discord user ID.
        amount: Amount of coins to deduct.
        reason: Reason for the deduction (for logging).

    Returns:
        Tuple of (success: bool, data: dict or error info)
        - On success: (True, {wallet/bank breakdown})
        - On insufficient funds: (False, {"error": "insufficient_funds", "total": X, "shortfall": Y})
        - On other error: (False, {"error": "error_type"})
    """
    config = get_config()
    api_key = config.JAWDAT_API_KEY

    if not api_key:
        logger.debug("Coin Deduct Skipped", [("Reason", "No API key configured")])
        return False, {"error": "not_configured"}

    api_url = f"http://127.0.0.1:{config.JAWDAT_API_PORT}/api/jawdat/currency/deduct"

    # Use shared session with retry logic
    response = await http_session.post_with_retry(
        api_url,
        json={
            "user_id": user_id,
            "amount": amount,
            "reason": reason,
        },
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        timeout=FAST_TIMEOUT,
    )

    if response is None:
        # post_with_retry already logged the failure
        return False, {"error": "network_error"}

    try:
        data = await response.json()

        if response.status == 401:
            logger.error("Coin Deduct Auth Failed", [
                ("User ID", str(user_id)),
                ("Status", "401 Unauthorized"),
            ])
            return False, {"error": "unauthorized"}

        if response.status == 400 and data.get("error") == "insufficient_funds":
            # Combined wallet+bank insufficient
            wallet = data.get("wallet", 0)
            bank = data.get("bank", 0)
            total = data.get("total", wallet + bank)
            shortfall = data.get("shortfall", amount - total)

            logger.tree("Coin Deduct Insufficient", [
                ("User ID", str(user_id)),
                ("Wallet", f"{wallet:,}"),
                ("Bank", f"{bank:,}"),
                ("Total", f"{total:,}"),
                ("Requested", f"{amount:,}"),
                ("Shortfall", f"{shortfall:,}"),
            ], emoji="💸")
            return False, {
                "error": "insufficient_funds",
                "wallet": wallet,
                "bank": bank,
                "total": total,
                "shortfall": shortfall,
            }

        if not data.get("success"):
            logger.warning("Coin Deduct Failed", [
                ("User ID", str(user_id)),
                ("Error", data.get("error", "unknown")),
            ])
            return False, {"error": data.get("error", "unknown")}

        # Success - extract wallet/bank breakdown
        old_wallet = data.get("old_wallet", 0)
        old_bank = data.get("old_bank", 0)
        new_wallet = data.get("new_wallet", 0)
        new_bank = data.get("new_bank", 0)
        from_wallet = data.get("from_wallet", 0)
        from_bank = data.get("from_bank", 0)

        old_total = old_wallet + old_bank
        new_total = new_wallet + new_bank

        logger.tree("Coins Deducted", [
            ("User ID", str(user_id)),
            ("Amount", f"-{amount:,}"),
            ("From Wallet", f"-{from_wallet:,}" if from_wallet else "0"),
            ("From Bank", f"-{from_bank:,}" if from_bank else "0"),
            ("Total", f"{old_total:,} → {new_total:,}"),
            ("Reason", reason[:50]),
        ], emoji="💰")

        return True, {
            "old_wallet": old_wallet,
            "old_bank": old_bank,
            "new_wallet": new_wallet,
            "new_bank": new_bank,
            "from_wallet": from_wallet,
            "from_bank": from_bank,
            "old_total": old_total,
            "new_total": new_total,
        }

    except Exception as e:
        logger.error("Coin Deduct Response Error", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:100]),
        ])
        return False, {"error": "parse_error"}


async def get_user_balance(user_id: int) -> Optional[int]:
    """
    Get a user's total coin balance (wallet + bank) via JawdatBot API.

    Args:
        user_id: Discord user ID.

    Returns:
        Total balance as int, or None if unavailable.
    """
    config = get_config()

    if not config.JAWDAT_API_KEY:
        logger.debug("Get Balance Skipped", [
            ("User ID", str(user_id)),
            ("Reason", "No API key configured"),
        ])
        return None

    api_url = f"http://127.0.0.1:{config.JAWDAT_API_PORT}/api/jawdat/user/{user_id}"

    response = await http_session.get_with_retry(
        api_url,
        timeout=FAST_TIMEOUT,
    )

    if response is None:
        logger.warning("Get Balance Failed", [
            ("User ID", str(user_id)),
            ("Reason", "Network error or timeout"),
        ])
        return None

    try:
        if response.status == 200:
            data = await response.json()
            wallet = data.get("wallet", 0)
            bank = data.get("bank", 0)
            total = wallet + bank
            logger.debug("Balance Retrieved", [
                ("User ID", str(user_id)),
                ("Wallet", f"{wallet:,}"),
                ("Bank", f"{bank:,}"),
                ("Total", f"{total:,}"),
            ])
            return total

        logger.warning("Get Balance Failed", [
            ("User ID", str(user_id)),
            ("Status", str(response.status)),
        ])
        return None

    except Exception as e:
        logger.error("Get Balance Parse Error", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:100]),
        ])
        return None


# =============================================================================
# Main Entry Point
# =============================================================================

async def process_coin_unjail(
    member: discord.Member,
    mute_reason: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Process coin payment for unjail.

    Cost is calculated as: OFFENSE_BASE × DURATION_MULTIPLIER

    Offense Tiers:
    - 1st offense: 2,000 base
    - 2nd offense: 5,000 base
    - 3rd offense: 10,000 base
    - 4th+ offense: 25,000 base

    Duration Multipliers:
    - 1-3h: ×1.0 | 4-12h: ×1.5 | 12-24h: ×2.0
    - 1-3d: ×3.0 | 3-7d: ×5.0 | 7d+: ×10.0

    This is the main entry point called from the CoinUnjailButton.

    Args:
        member: Discord member who wants to unjail.
        mute_reason: Original mute reason (for logging).

    Returns:
        Tuple of (success: bool, data: dict with balance info, cost, breakdown)
    """
    # Get tiered cost based on weekly offense count AND mute duration
    cost, offense_count, breakdown = get_unjail_cost_for_user(member.id, member.guild.id)

    # Build log details
    log_details = [
        ("User", f"{member.name} ({member.id})"),
        ("Offense #", str(offense_count)),
    ]

    if breakdown:
        log_details.extend([
            ("Duration", f"{breakdown['duration_hours']:.1f}h ({breakdown['duration_tier']})"),
            ("Base", f"{breakdown['base_cost']:,}"),
            ("Multiplier", f"×{breakdown['multiplier']}"),
        ])

    log_details.append(("Total Cost", f"{cost:,} coins"))

    logger.tree("Coin Unjail Processing", log_details, emoji="🪙")

    # Build reason with details
    reason_parts = [f"Prison unjail fee (offense #{offense_count}"]
    if breakdown:
        reason_parts.append(f", {breakdown['duration_tier']} mute, ×{breakdown['multiplier']}")
    reason_parts.append(")")
    reason = "".join(reason_parts)

    success, result = await deduct_coins(
        user_id=member.id,
        amount=cost,
        reason=reason,
    )

    # Add cost breakdown to result for UI
    result["cost"] = cost
    result["offense_count"] = offense_count
    if breakdown:
        result["breakdown"] = breakdown

    return success, result
