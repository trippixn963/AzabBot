"""
AzabBot - User Risk Assessment
==============================

Risk score calculation for user moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import List, Optional, Tuple

import discord


def calculate_risk_score(
    user: discord.User,
    member: Optional[discord.Member],
    total_cases: int,
    total_messages: int,
    days_in_server: int,
) -> Tuple[int, List[str]]:
    """
    Calculate risk score (0-100) and flags for a user.

    Risk factors:
    - New account (<30 days): +20
    - No avatar: +15
    - New to server (<7 days): +15
    - Low activity (<10 messages): +10
    - Previous cases: +5 per case (max +30)
    - No roles (besides @everyone): +10
    """
    score = 0
    flags = []

    now = datetime.utcnow()

    # Account age
    if user.created_at:
        account_age = (now - user.created_at.replace(tzinfo=None)).days
        if account_age < 7:
            score += 25
            flags.append("very_new_account")
        elif account_age < 30:
            score += 15
            flags.append("new_account")

    # No avatar
    if user.avatar is None:
        score += 15
        flags.append("no_avatar")

    # Server tenure
    if days_in_server < 3:
        score += 20
        flags.append("just_joined")
    elif days_in_server < 7:
        score += 10
        flags.append("new_member")

    # Low activity
    if total_messages < 5:
        score += 15
        flags.append("no_activity")
    elif total_messages < 20:
        score += 5
        flags.append("low_activity")

    # Previous cases
    if total_cases > 0:
        case_penalty = min(total_cases * 5, 30)
        score += case_penalty
        if total_cases >= 5:
            flags.append("repeat_offender")
        elif total_cases >= 2:
            flags.append("previous_cases")

    # No roles
    if member and len([r for r in member.roles if r.name != "@everyone"]) == 0:
        score += 10
        flags.append("no_roles")

    return min(score, 100), flags


__all__ = ["calculate_risk_score"]
