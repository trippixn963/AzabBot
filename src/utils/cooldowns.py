"""
Command Cooldown System for AzabBot
====================================

Prevents spam and rate limiting for commands.
"""

import asyncio
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from src.core.logger import get_logger

class CooldownManager:
    """Manages command cooldowns to prevent spam."""
    
    def __init__(self):
        """Initialize cooldown manager."""
        self.cooldowns: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.logger = get_logger()
        self._lock = asyncio.Lock()
        
        # Default cooldown settings (in seconds)
        self.default_cooldowns = {
            "torture": 5.0,
            "profile": 3.0,
            "leaderboard": 10.0,
            "stats": 5.0,
            "help": 2.0,
            "about": 2.0,
            "confess": 10.0,
            "resist": 10.0,
            "ai": 3.0,
            "gpt": 3.0,
            "admin": 1.0,  # Admin commands have minimal cooldown
        }
        
        # User-specific rate limits
        self.rate_limits = {
            "commands_per_minute": 20,
            "commands_per_hour": 200,
        }
        
        # Track command usage
        self.command_history: Dict[int, List[float]] = defaultdict(list)
        
        # Penalty system for spammers
        self.penalties: Dict[int, float] = {}
        self.penalty_multiplier = 2.0
        self.penalty_decay = 300  # 5 minutes
    
    async def check_cooldown(
        self, 
        command: str, 
        user_id: int,
        bypass_for_admin: bool = False
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if a command is on cooldown for a user.
        
        Args:
            command: Command name
            user_id: Discord user ID
            bypass_for_admin: Whether to bypass for admins
            
        Returns:
            Tuple of (can_execute, remaining_seconds)
        """
        async with self._lock:
            current_time = time.time()
            
            # Check rate limits first
            if not await self._check_rate_limits(user_id, current_time):
                penalty_time = self._apply_penalty(user_id, current_time)
                return False, penalty_time
            
            # Get cooldown time for command
            cooldown_time = self.default_cooldowns.get(
                command, 
                2.0  # Default 2 second cooldown
            )
            
            # Apply penalty multiplier if user has penalties
            if user_id in self.penalties:
                penalty_expire = self.penalties[user_id]
                if current_time < penalty_expire:
                    cooldown_time *= self.penalty_multiplier
                else:
                    del self.penalties[user_id]
            
            # Check if on cooldown
            command_key = f"{command}:{user_id}"
            if command in self.cooldowns and user_id in self.cooldowns[command]:
                last_use = self.cooldowns[command][user_id]
                elapsed = current_time - last_use
                
                if elapsed < cooldown_time:
                    remaining = cooldown_time - elapsed
                    self.logger.log_debug(
                        f"Command {command} on cooldown for user {user_id}",
                        context={
                            "remaining": f"{remaining:.1f}s",
                            "cooldown": cooldown_time
                        }
                    )
                    return False, remaining
            
            # Update last use time
            self.cooldowns[command][user_id] = current_time
            self.command_history[user_id].append(current_time)
            
            return True, None
    
    async def _check_rate_limits(self, user_id: int, current_time: float) -> bool:
        """Check if user is within rate limits."""
        if user_id not in self.command_history:
            return True
        
        history = self.command_history[user_id]
        
        # Clean old entries
        minute_ago = current_time - 60
        hour_ago = current_time - 3600
        history = [t for t in history if t > hour_ago]
        self.command_history[user_id] = history
        
        # Check per-minute limit
        recent_minute = [t for t in history if t > minute_ago]
        if len(recent_minute) >= self.rate_limits["commands_per_minute"]:
            self.logger.log_warning(
                f"User {user_id} hit per-minute rate limit",
                context={
                    "commands": len(recent_minute),
                    "limit": self.rate_limits["commands_per_minute"]
                }
            )
            return False
        
        # Check per-hour limit
        if len(history) >= self.rate_limits["commands_per_hour"]:
            self.logger.log_warning(
                f"User {user_id} hit per-hour rate limit",
                context={
                    "commands": len(history),
                    "limit": self.rate_limits["commands_per_hour"]
                }
            )
            return False
        
        return True
    
    def _apply_penalty(self, user_id: int, current_time: float) -> float:
        """Apply penalty to spammer."""
        penalty_expire = current_time + self.penalty_decay
        self.penalties[user_id] = penalty_expire
        
        self.logger.log_warning(
            f"Applied spam penalty to user {user_id}",
            context={
                "duration": f"{self.penalty_decay}s",
                "multiplier": self.penalty_multiplier
            }
        )
        
        return self.penalty_decay
    
    async def reset_cooldown(self, command: str, user_id: int):
        """Reset cooldown for a specific command and user."""
        async with self._lock:
            if command in self.cooldowns and user_id in self.cooldowns[command]:
                del self.cooldowns[command][user_id]
                self.logger.log_debug(
                    f"Reset cooldown for command {command} user {user_id}"
                )
    
    async def reset_all_cooldowns(self, user_id: int):
        """Reset all cooldowns for a user."""
        async with self._lock:
            for command in self.cooldowns:
                if user_id in self.cooldowns[command]:
                    del self.cooldowns[command][user_id]
            
            if user_id in self.command_history:
                del self.command_history[user_id]
            
            if user_id in self.penalties:
                del self.penalties[user_id]
            
            self.logger.log_info(f"Reset all cooldowns for user {user_id}")
    
    async def set_cooldown(self, command: str, duration: float):
        """Update cooldown duration for a command."""
        self.default_cooldowns[command] = duration
        self.logger.log_info(
            f"Updated cooldown for {command} to {duration}s"
        )
    
    async def cleanup_old_entries(self):
        """Remove old cooldown entries to save memory."""
        async with self._lock:
            current_time = time.time()
            cleaned = 0
            
            # Clean cooldowns
            for command in list(self.cooldowns.keys()):
                for user_id in list(self.cooldowns[command].keys()):
                    last_use = self.cooldowns[command][user_id]
                    cooldown_time = self.default_cooldowns.get(command, 2.0)
                    
                    # Remove if cooldown expired more than 5 minutes ago
                    if current_time - last_use > cooldown_time + 300:
                        del self.cooldowns[command][user_id]
                        cleaned += 1
                
                # Remove empty command entries
                if not self.cooldowns[command]:
                    del self.cooldowns[command]
            
            # Clean command history
            hour_ago = current_time - 3600
            for user_id in list(self.command_history.keys()):
                self.command_history[user_id] = [
                    t for t in self.command_history[user_id] 
                    if t > hour_ago
                ]
                
                if not self.command_history[user_id]:
                    del self.command_history[user_id]
                    cleaned += 1
            
            # Clean expired penalties
            for user_id in list(self.penalties.keys()):
                if current_time >= self.penalties[user_id]:
                    del self.penalties[user_id]
                    cleaned += 1
            
            if cleaned > 0:
                self.logger.log_debug(f"Cleaned {cleaned} old cooldown entries")
            
            return cleaned
    
    def get_stats(self) -> Dict:
        """Get cooldown statistics."""
        return {
            "active_cooldowns": sum(
                len(users) for users in self.cooldowns.values()
            ),
            "users_tracked": len(self.command_history),
            "users_penalized": len(self.penalties),
            "commands_tracked": len(self.cooldowns),
        }

class BucketCooldown:
    """Token bucket algorithm for more flexible rate limiting."""
    
    def __init__(
        self, 
        rate: float, 
        per: float, 
        bucket_size: Optional[int] = None
    ):
        """
        Initialize bucket cooldown.
        
        Args:
            rate: Number of uses allowed
            per: Time period in seconds
            bucket_size: Maximum tokens in bucket (defaults to rate)
        """
        self.rate = rate
        self.per = per
        self.bucket_size = bucket_size or rate
        self.buckets: Dict[int, Tuple[float, float]] = {}
        self.logger = get_logger()
    
    async def acquire(self, user_id: int) -> Tuple[bool, Optional[float]]:
        """
        Try to acquire a token from the bucket.
        
        Returns:
            Tuple of (success, retry_after_seconds)
        """
        current = time.time()
        
        if user_id in self.buckets:
            tokens, last_update = self.buckets[user_id]
            
            # Calculate tokens regenerated
            elapsed = current - last_update
            tokens = min(
                self.bucket_size,
                tokens + (elapsed * self.rate / self.per)
            )
        else:
            tokens = self.bucket_size
        
        if tokens >= 1:
            # Consume a token
            tokens -= 1
            self.buckets[user_id] = (tokens, current)
            return True, None
        else:
            # Calculate retry time
            retry_after = (1 - tokens) * self.per / self.rate
            return False, retry_after

# Global cooldown manager instance
_cooldown_manager = CooldownManager()

def get_cooldown_manager() -> CooldownManager:
    """Get global cooldown manager."""
    return _cooldown_manager