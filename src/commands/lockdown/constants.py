"""
AzabBot - Lockdown Constants
============================

Constants and data classes for the lockdown command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from dataclasses import dataclass
from typing import List


# Maximum concurrent channel operations (Discord rate limit friendly)
MAX_CONCURRENT_OPS: int = 10

# Delay between batches to avoid rate limits (seconds)
BATCH_DELAY: float = 0.5


@dataclass
class LockdownResult:
    """Result of a lockdown/unlock operation."""
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    errors: List[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


__all__ = ["MAX_CONCURRENT_OPS", "BATCH_DELAY", "LockdownResult"]
