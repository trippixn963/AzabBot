"""
AzabBot - Appeal Tokens
=======================

JWT token generation and validation for web-based appeal links.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, Tuple
import jwt

from src.core.config import get_config
from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

TOKEN_EXPIRY = 7 * 24 * 3600  # 7 days in seconds
ALGORITHM = "HS256"


# =============================================================================
# Token Functions
# =============================================================================

def generate_appeal_token(case_id: str, user_id: int) -> Optional[str]:
    """
    Generate a JWT token for an appeal link.

    Args:
        case_id: The case ID being appealed.
        user_id: The Discord user ID of the banned user.

    Returns:
        JWT token string, or None if token secret is not configured.
    """
    config = get_config()
    secret = config.appeal_token_secret

    if not secret:
        logger.warning("Appeal Token Secret Not Configured", [
            ("Case ID", case_id),
            ("User ID", str(user_id)),
        ])
        return None

    payload = {
        "case_id": case_id,
        "user_id": user_id,
        "exp": time.time() + TOKEN_EXPIRY,
        "iat": time.time(),
    }

    try:
        token = jwt.encode(payload, secret, algorithm=ALGORITHM)
        logger.debug(f"Appeal Token Generated: case_id={case_id}, user_id={user_id}")
        return token
    except Exception as e:
        logger.error("Appeal Token Generation Failed", [
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Error", str(e)[:100]),
        ])
        return None


def validate_appeal_token(token: str) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    Validate a JWT appeal token.

    Args:
        token: The JWT token string to validate.

    Returns:
        Tuple of (is_valid, payload, error_message).
        - is_valid: True if token is valid.
        - payload: Dict with case_id, user_id if valid, None otherwise.
        - error_message: Human-readable error if invalid, None if valid.
    """
    config = get_config()
    secret = config.appeal_token_secret

    if not secret:
        logger.warning("Appeal Token Validation Failed: Secret Not Configured")
        return (False, None, "Appeal system is not configured")

    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])

        # Validate required fields
        if "case_id" not in payload or "user_id" not in payload:
            logger.warning("Appeal Token Missing Fields", [
                ("Has case_id", str("case_id" in payload)),
                ("Has user_id", str("user_id" in payload)),
            ])
            return (False, None, "Invalid appeal link")

        return (True, payload, None)

    except jwt.ExpiredSignatureError:
        logger.debug("Appeal Token Expired")
        return (False, None, "This appeal link has expired. Please contact a moderator for a new link.")

    except jwt.InvalidTokenError as e:
        logger.warning("Appeal Token Invalid", [("Error", str(e)[:100])])
        return (False, None, "Invalid appeal link")

    except Exception as e:
        logger.error("Appeal Token Validation Error", [("Error", str(e)[:100])])
        return (False, None, "Failed to validate appeal link")


__all__ = ["generate_appeal_token", "validate_appeal_token", "TOKEN_EXPIRY"]
