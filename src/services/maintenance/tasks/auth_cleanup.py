"""
AzabBot - Auth Cleanup Task
===========================

Clean up stale authentication state from memory.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Set

from src.core.logger import logger
from src.core.constants import (
    LOG_TRUNCATE_SHORT,
    AUTH_TOKEN_CLEANUP_AGE,
    AUTH_RATE_LIMIT_CLEANUP_AGE,
    AUTH_LOCKOUT_CLEANUP_AGE,
)
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class AuthCleanupTask(MaintenanceTask):
    """
    Clean up stale authentication state from memory.

    Cleans:
    - Blacklisted tokens (from logouts) that are past expiry
    - Login rate limit tracking data for old windows
    - Failed login trackers for expired lockouts

    These grow indefinitely without periodic cleanup since they're
    stored in memory, not database.
    """

    name = "Auth Cleanup"

    async def should_run(self) -> bool:
        """Check if API auth service is available."""
        try:
            from src.api.services.auth import get_auth_service
            return get_auth_service() is not None
        except ImportError:
            return False

    async def run(self) -> Dict[str, Any]:
        """Run auth state cleanup."""
        tokens_removed: int = 0
        attempts_removed: int = 0
        failed_removed: int = 0
        errors: int = 0

        try:
            from src.api.services.auth import get_auth_service
            import jwt

            auth_service = get_auth_service()
            now: float = time.time()

            # Track stats before cleanup
            tokens_before: int = len(auth_service._blacklisted_tokens)
            attempts_before: int = len(auth_service._login_attempts)
            failed_before: int = len(auth_service._failed_logins)

            # =================================================================
            # Clean blacklisted tokens
            # =================================================================
            try:
                tokens_to_remove: Set[str] = set()

                for token in auth_service._blacklisted_tokens:
                    try:
                        # Decode without verification to get expiry
                        payload = jwt.decode(
                            token,
                            options={"verify_signature": False, "verify_exp": False}
                        )
                        exp: float = payload.get("exp", 0)

                        # If token expired more than cleanup age ago, safe to remove
                        if exp and now - exp > AUTH_TOKEN_CLEANUP_AGE:
                            tokens_to_remove.add(token)
                    except Exception:
                        # Can't decode - corrupted token, remove it
                        tokens_to_remove.add(token)

                for token in tokens_to_remove:
                    try:
                        auth_service._blacklisted_tokens.discard(token)
                        tokens_removed += 1
                    except (KeyError, ValueError):
                        pass

            except Exception as e:
                errors += 1
                logger.error("Token Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Clean login attempt trackers
            # =================================================================
            try:
                attempts_to_remove: List[int] = []

                for discord_id, attempt in auth_service._login_attempts.items():
                    if now - attempt.window_start > AUTH_RATE_LIMIT_CLEANUP_AGE:
                        attempts_to_remove.append(discord_id)

                for discord_id in attempts_to_remove:
                    try:
                        del auth_service._login_attempts[discord_id]
                        attempts_removed += 1
                    except (KeyError, ValueError):
                        pass

            except Exception as e:
                errors += 1
                logger.error("Login Attempt Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Clean failed login trackers
            # =================================================================
            try:
                failed_to_remove: List[int] = []

                for discord_id, tracker in auth_service._failed_logins.items():
                    should_remove = False

                    if tracker.locked_until is not None:
                        # Was locked - remove if lock expired and grace period passed
                        if now > tracker.locked_until + AUTH_LOCKOUT_CLEANUP_AGE:
                            should_remove = True
                    else:
                        # Never locked - these are cleared on successful login
                        # Remove stale entries with 0 failures (already cleared)
                        if tracker.consecutive_failures == 0:
                            should_remove = True

                    if should_remove:
                        failed_to_remove.append(discord_id)

                for discord_id in failed_to_remove:
                    try:
                        del auth_service._failed_logins[discord_id]
                        failed_removed += 1
                    except (KeyError, ValueError):
                        pass

            except Exception as e:
                errors += 1
                logger.error("Failed Login Cleanup Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

            # =================================================================
            # Log results
            # =================================================================
            total_removed: int = tokens_removed + attempts_removed + failed_removed

            if total_removed > 0:
                logger.tree("Auth Cleanup Complete", [
                    ("Blacklisted Tokens", f"{tokens_removed} removed ({tokens_before} → {tokens_before - tokens_removed})"),
                    ("Login Attempts", f"{attempts_removed} removed ({attempts_before} → {attempts_before - attempts_removed})"),
                    ("Failed Logins", f"{failed_removed} removed ({failed_before} → {failed_before - failed_removed})"),
                    ("Total Cleaned", str(total_removed)),
                    ("Errors", str(errors)),
                ], emoji="🔐")

            return {
                "success": errors == 0,
                "tokens_removed": tokens_removed,
                "attempts_removed": attempts_removed,
                "failed_removed": failed_removed,
                "total": total_removed,
                "errors": errors,
            }

        except ImportError:
            logger.debug("Auth Cleanup Skipped", [("Reason", "API not available")])
            return {"success": True, "total": 0, "skipped": True}

        except Exception as e:
            logger.error("Auth Cleanup Failed", [
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
            ])
            return {"success": False, "error": str(e)[:LOG_TRUNCATE_SHORT]}

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        if result.get("skipped"):
            return "skipped"
        if not result.get("success"):
            return "failed"

        total: int = result.get("total", 0)
        if total > 0:
            return f"{total} cleaned"
        return "clean"


__all__ = ["AuthCleanupTask"]
