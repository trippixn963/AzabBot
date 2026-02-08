"""
AzabBot - Anti-Spam Reputation System
=====================================

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
        """Calculate reputation score from database using single query."""
        db: "Database" = self.db  # type: ignore
        reputation = 0.0

        try:
            # Single query to get all reputation factors
            row = db.fetchone(
                """SELECT
                    (SELECT joined_at FROM user_join_info
                     WHERE user_id = ? AND guild_id = ?) as joined_at,
                    (SELECT COALESCE(violation_count, 0) FROM spam_violations
                     WHERE user_id = ? AND guild_id = ?) as violation_count,
                    (SELECT COUNT(*) FROM warnings
                     WHERE user_id = ? AND guild_id = ?) as warning_count""",
                (user_id, guild_id, user_id, guild_id, user_id, guild_id)
            )

            if row:
                # Base reputation from server tenure
                join_timestamp = row["joined_at"]
                if join_timestamp:
                    days_in_server = (time.time() - join_timestamp) / 86400
                    reputation += min(days_in_server * 0.5, 50)  # Max 50 from tenure

                # Subtract for spam violations
                violation_count = row["violation_count"] or 0
                reputation -= violation_count * REP_LOSS_WARNING

                # Subtract for warnings
                warning_count = row["warning_count"] or 0
                reputation -= warning_count * REP_LOSS_WARNING

        except Exception as e:
            logger.debug("Reputation Calc Error", [("Error", str(e)[:50])])

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


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ReputationMixin"]
