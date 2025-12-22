"""
Azab Discord Bot - Utils Package
================================

Utility modules for the Azab Discord bot.
Contains helper functions and utility classes.

DESIGN:
    Utils are stateless helper functions and classes that can be
    used anywhere in the codebase. They should not have side effects
    or depend on bot state.

Available Utilities:
    Footer: Standardized embed footer with cached avatar
    Metrics: Lightweight performance monitoring
    Views: Persistent button views for moderation

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Utility Imports
# =============================================================================

from .footer import FOOTER_TEXT, init_footer, refresh_avatar, set_footer
from .metrics import (
    MetricsCollector,
    MetricSample,
    MetricStats,
    metrics,
    init_metrics,
    record_metric,
    increment_counter,
    get_metrics_summary,
    SLOW_THRESHOLD_MS,
    LOG_SLOW_OPERATIONS,
)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Footer
    "FOOTER_TEXT",
    "init_footer",
    "refresh_avatar",
    "set_footer",
    # Metrics
    "MetricsCollector",
    "MetricSample",
    "MetricStats",
    "metrics",
    "init_metrics",
    "record_metric",
    "increment_counter",
    "get_metrics_summary",
    "SLOW_THRESHOLD_MS",
    "LOG_SLOW_OPERATIONS",
]
