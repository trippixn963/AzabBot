"""
AzabBot - Database Base Module
==============================

Helper functions for database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from typing import Optional, Any

from src.core.logger import logger


# =============================================================================
# Helper Functions
# =============================================================================

def _safe_json_loads(value: Optional[str], default: Any = None) -> Any:
    """Safely parse JSON, returning default on error."""
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Corrupted JSON In Database", [("Value", value[:50] if len(value) > 50 else value)])
        return default if default is not None else []
