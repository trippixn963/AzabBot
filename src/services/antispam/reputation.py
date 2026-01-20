"""
Anti-Spam Reputation System
===========================

User reputation tracking for dynamic spam thresholds.
"""

import time
from collections import defaultdict
from typing import Dict, TYPE_CHECKING

from src.core.logger import logger

from .constants import (
    REP_LOSS_WARNING,
    REPUTATION_MULTIPLIERS,
    REPUTATION_NEW,
    REPUTATION_REGULAR,
    REPUTATION_TRUSTED,
    REPUTATION_VETERAN,
)

if TYPE_CHECKING:
    from src.core.database import Database


class ReputationMixin:
    """Mixin class providing reputation system functionality."""

    def _init_reputation(self) -> None:
        """Initialize reputation tracking structures."""
        self._reputation_cache: Dict[int, Dict[int, float]] = defaultdict(dict)

    def get_user_reputation(self, user_id: int, guild_id: int) -> float:
        """Get user's reputation score."""
        # Check cache first
        if guild_id in self._reputation_cache:
            if user_id in self._reputation_cache[guild_id]:
                return self._reputation_cache[guild_id][user_id]

        # Calculate from database
        reputation = self._calculate_reputation(user_id, guild_id)
        self._reputation_cache[guild_id][user_id] = reputation
        return reputation

    def _calculate_reputation(self, user_id: int, guild_id: int) -> float:
        """Calculate reputation score from database."""
        db: "Database" = self.db  # type: ignore
        reputation = 0.0

        # Base reputation from account/server age
        try:
            user_info = db.get_user_join_info(user_id, guild_id)
            if user_info:
                join_timestamp = user_info.get("joined_at", 0)
                if join_timestamp:
                    days_in_server = (time.time() - join_timestamp) / 86400
                    reputation += min(days_in_server * 0.5, 50)  # Max 50 from tenure
        except Exception as e:
            logger.debug(f"Reputation calculation - join info error: {e}")

        # Subtract for violations
        violations = db.get_spam_violations(user_id, guild_id)
        if violations:
            total_violations = violations.get("total_violations", 0)
            reputation -= total_violations * REP_LOSS_WARNING

        # Get warning count
        try:
            warnings = db.get_user_warnings(user_id, guild_id)
            if warnings:
                reputation -= len(warnings) * REP_LOSS_WARNING
        except Exception as e:
            logger.debug(f"Reputation calculation - warnings error: {e}")

        # Clamp to reasonable range
        return max(0, min(reputation, REPUTATION_VETERAN * 2))

    def get_reputation_multiplier(self, user_id: int, guild_id: int) -> float:
        """Get threshold multiplier based on user reputation."""
        reputation = self.get_user_reputation(user_id, guild_id)

        if reputation >= REPUTATION_VETERAN:
            return REPUTATION_MULTIPLIERS[REPUTATION_VETERAN]
        elif reputation >= REPUTATION_TRUSTED:
            return REPUTATION_MULTIPLIERS[REPUTATION_TRUSTED]
        elif reputation >= REPUTATION_REGULAR:
            return REPUTATION_MULTIPLIERS[REPUTATION_REGULAR]
        else:
            return REPUTATION_MULTIPLIERS[REPUTATION_NEW]

    def update_reputation(self, user_id: int, guild_id: int, delta: float) -> None:
        """Update user's reputation score."""
        current = self.get_user_reputation(user_id, guild_id)
        new_rep = max(0, current + delta)
        self._reputation_cache[guild_id][user_id] = new_rep

    def clear_reputation_cache(self) -> None:
        """Clear the reputation cache (called periodically)."""
        self._reputation_cache.clear()
