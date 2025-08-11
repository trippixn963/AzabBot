# =============================================================================
# AzabBot - Prison Management Service
# =============================================================================
# Handles Solitary Confinement, Good Behavior, and Prison Break Detection
# for advanced prison management and psychological torture operations.
# =============================================================================

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import discord

from src.services.base_service import BaseService
from src.utils.time_utils import now_est_naive
from src.repositories.prisoner_repository import PrisonerRepository
from src.utils.error_handler import (
    handle_error, ErrorCategory, ErrorSeverity, AzabBotError
)
from src.utils.logging_utils import (
    log_service_init, log_service_ready, log_service_error,
    log_database_operation, log_state_change, LogContext
)
from src.core.logger import get_logger

logger = get_logger()


class PrisonService(BaseService):
    """Service for managing advanced prison features."""
    
    def __init__(self, name: str = "PrisonService"):
        """Initialize prison service."""
        super().__init__(name, dependencies=["DatabaseService", "AIService"])
        self.container = None
        self.db_service = None
        self.ai_service = None
        self.repository = None
        
        # Tracking dictionaries
        self.solitary_prisoners: Dict[str, dict] = {}
        self.good_behavior_tracking: Dict[str, dict] = {}
        self.escape_attempts: Dict[str, list] = {}
        
        # Configuration
        self.solitary_threshold = 3  # Offenses before solitary
        self.good_behavior_quiet_time = 300  # 5 minutes of quiet for good behavior
        self.harassment_reduction_per_level = 0.15  # 15% reduction per good behavior level
    
    @handle_error(
        category=ErrorCategory.GENERAL,
        severity=ErrorSeverity.HIGH,
        max_retries=1
    )
    async def initialize(self, config: dict, **kwargs):
        """Initialize the prison service."""
        log_service_init("PrisonService")
        
        await super().initialize(config, **kwargs)
        
        # Services are passed as kwargs from DI container
        self.db_service = kwargs.get("DatabaseService")
        self.ai_service = kwargs.get("AIService")
        
        if not self.db_service:
            raise AzabBotError(
                "Database service not available for prison service",
                category=ErrorCategory.CONFIGURATION,
                severity=ErrorSeverity.HIGH
            )
        
        # Initialize repository
        self.repository = PrisonerRepository(self.db_service)
        
        # Initialize database tables
        await self._initialize_database()
        
        # Load existing data
        await self._load_prison_data()
        
        log_service_ready("PrisonService", {
            "solitary_count": len(self.solitary_prisoners),
            "good_behavior_count": len(self.good_behavior_tracking)
        })
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=False
    )
    async def _initialize_database(self) -> bool:
        """Initialize prison feature tables."""
        async with LogContext("initialize_prison_tables"):
            # For now, skip complex schema initialization
            logger.log_info("Prison feature tables initialization skipped - using existing database")
            return True
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=None
    )
    async def _load_prison_data(self):
        """Load existing prison data from database."""
        async with LogContext("load_prison_data"):
            # Load solitary confinement data
            solitary_data = await self.repository.fetch_all(
                "SELECT * FROM solitary_confinement WHERE in_solitary = 1"
            )
            for row in solitary_data:
                self.solitary_prisoners[row['discord_id']] = dict(row)
            
            # Load good behavior data
            behavior_data = await self.repository.fetch_all(
                "SELECT * FROM good_behavior WHERE behavior_score > 0"
            )
            for row in behavior_data:
                self.good_behavior_tracking[row['discord_id']] = dict(row)
            
            logger.log_info(
                f"Loaded {len(self.solitary_prisoners)} in solitary, "
                f"{len(self.good_behavior_tracking)} with good behavior"
            )
    
    # ============= SOLITARY CONFINEMENT =============
    
    @handle_error(
        category=ErrorCategory.GENERAL,
        severity=ErrorSeverity.LOW,
        default_return=(False, 0)
    )
    async def check_solitary_confinement(self, user_id: str, username: str) -> Tuple[bool, int]:
        """
        Check if user should be in solitary confinement.
        Returns (is_in_solitary, severity_level)
        """
        if user_id in self.solitary_prisoners:
            data = self.solitary_prisoners[user_id]
            # Check if still in solitary period
            if data.get('release_time'):
                release_time = datetime.fromisoformat(data['release_time'])
                if now_est_naive() < release_time:
                    return True, data.get('severity', 1)
                else:
                    # Release from solitary
                    await self.release_from_solitary(user_id, username)
                    return False, 0
            return True, data.get('severity', 1)
        return False, 0
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM
    )
    async def place_in_solitary(self, user_id: str, username: str, 
                               reason: str, duration_hours: int = 24,
                               severity: int = 1):
        """Place a prisoner in solitary confinement."""
        async with LogContext("place_in_solitary", user_id=user_id, username=username):
            prisoner = await self.repository.get_or_create_prisoner(
                user_id, username, username
            )
            
            if not prisoner:
                raise AzabBotError(
                    f"Failed to get/create prisoner record for {username}",
                    category=ErrorCategory.DATABASE,
                    severity=ErrorSeverity.MEDIUM
                )
            
            release_time = now_est_naive() + timedelta(hours=duration_hours)
            
            # Record in database
            await self.repository.execute(
                """INSERT OR REPLACE INTO solitary_confinement 
                   (prisoner_id, discord_id, in_solitary, placed_at, 
                    release_time, reason, severity)
                   VALUES (?, ?, 1, ?, ?, ?, ?)""",
                (prisoner['id'], user_id, now_est_naive(),
                 release_time, reason, severity)
            )
            
            # Update in-memory tracking
            self.solitary_prisoners[user_id] = {
                'prisoner_id': prisoner['id'],
                'discord_id': user_id,
                'in_solitary': True,
                'placed_at': now_est_naive().isoformat(),
                'release_time': release_time.isoformat(),
                'reason': reason,
                'severity': severity
            }
            
            log_state_change(
                "solitary_status",
                old_state="free",
                new_state="solitary",
                reason=reason
            )
            
            logger.log_info(f"🔒 {username} placed in solitary confinement for {duration_hours} hours")
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW
    )
    async def release_from_solitary(self, user_id: str, username: str):
        """Release a prisoner from solitary confinement."""
        async with LogContext("release_from_solitary", user_id=user_id):
            if user_id in self.solitary_prisoners:
                # Update database
                await self.repository.execute(
                    """UPDATE solitary_confinement 
                       SET in_solitary = 0, released_at = ?
                       WHERE discord_id = ? AND in_solitary = 1""",
                    (now_est_naive(), user_id)
                )
                
                # Remove from tracking
                del self.solitary_prisoners[user_id]
                
                log_state_change(
                    "solitary_status",
                    old_state="solitary",
                    new_state="released",
                    reason="time_served"
                )
                
                logger.log_info(f"🔓 {username} released from solitary confinement")
    
    # ============= GOOD BEHAVIOR SYSTEM =============
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW
    )
    async def track_good_behavior(self, user_id: str, username: str, quiet_duration: float):
        """Track good behavior for potential rewards."""
        async with LogContext("track_good_behavior", user_id=user_id, duration=quiet_duration):
            if quiet_duration >= self.good_behavior_quiet_time:
                # Initialize or update good behavior
                if user_id not in self.good_behavior_tracking:
                    self.good_behavior_tracking[user_id] = {
                        'behavior_score': 0,
                        'last_good_behavior': now_est_naive().isoformat(),
                        'consecutive_good_days': 0
                    }
                
                # Increment behavior score
                data = self.good_behavior_tracking[user_id]
                data['behavior_score'] += 1
                data['last_good_behavior'] = now_est_naive().isoformat()
                
                # Check for consecutive days
                last_behavior = datetime.fromisoformat(data.get('last_good_behavior', now_est_naive().isoformat()))
                if (now_est_naive() - last_behavior).days <= 1:
                    data['consecutive_good_days'] += 1
                else:
                    data['consecutive_good_days'] = 1
                
                # Save to database
                prisoner = await self.repository.get_or_create_prisoner(
                    user_id, username, username
                )
                
                if prisoner:
                    await self.repository.execute(
                        """INSERT OR REPLACE INTO good_behavior 
                           (prisoner_id, discord_id, behavior_score, 
                            last_good_behavior, consecutive_good_days)
                           VALUES (?, ?, ?, ?, ?)""",
                        (prisoner['id'], user_id, data['behavior_score'],
                         data['last_good_behavior'], data['consecutive_good_days'])
                    )
                
                logger.log_info(f"👼 Good behavior tracked for {username}")
    
    def calculate_harassment_reduction(self, user_id: str) -> float:
        """Calculate harassment reduction based on good behavior."""
        if user_id not in self.good_behavior_tracking:
            return 1.0  # No reduction
        
        data = self.good_behavior_tracking[user_id]
        behavior_score = data.get('behavior_score', 0)
        
        # Each point of good behavior reduces harassment
        reduction = 1.0 - (behavior_score * self.harassment_reduction_per_level)
        return max(0.3, reduction)  # Minimum 30% harassment
    
    # ============= ESCAPE DETECTION =============
    
    @handle_error(
        category=ErrorCategory.GENERAL,
        severity=ErrorSeverity.LOW,
        default_return=False
    )
    async def detect_escape_attempt(self, user_id: str, message: str) -> bool:
        """Detect if a prisoner is attempting to escape."""
        escape_patterns = [
            "!unmute", "unmute me", "let me out",
            "remove role", "!free", "escape",
            "break out", "bypass", "evade"
        ]
        
        message_lower = message.lower()
        for pattern in escape_patterns:
            if pattern in message_lower:
                # Track escape attempt
                if user_id not in self.escape_attempts:
                    self.escape_attempts[user_id] = []
                
                self.escape_attempts[user_id].append({
                    'attempt_time': now_est_naive().isoformat(),
                    'message': message[:100]
                })
                
                logger.log_warning(
                    f"🚨 Escape attempt detected from {user_id}",
                    context={
                        "user_id": user_id,
                        "pattern_matched": pattern,
                        "attempt_count": len(self.escape_attempts[user_id])
                    }
                )
                
                return True
        
        return False
    
    @handle_error(
        category=ErrorCategory.GENERAL,
        severity=ErrorSeverity.LOW,
        default_return=""
    )
    async def generate_punishment_response(self, user_id: str, offense_type: str) -> str:
        """Generate punishment response based on offense."""
        if not self.ai_service:
            return "Your pathetic attempts amuse me."
        
        # Check if in solitary
        in_solitary, severity = await self.check_solitary_confinement(user_id, "prisoner")
        
        context = {
            "offense_type": offense_type,
            "in_solitary": in_solitary,
            "severity": severity,
            "escape_attempts": len(self.escape_attempts.get(user_id, []))
        }
        
        prompt = f"""Generate a harsh punishment response for a prisoner who {offense_type}.
        Context: {json.dumps(context)}
        Be cruel but creative. Maximum 2 sentences."""
        
        response = await self.ai_service.generate_response(
            prompt=prompt,
            user_id=user_id,
            username="prisoner",
            channel_name="prison"
        )
        
        return response or "Your suffering has only just begun."
    
    # ============= ANALYSIS METHODS =============
    
    @handle_error(
        category=ErrorCategory.GENERAL,
        severity=ErrorSeverity.LOW,
        default_return={}
    )
    async def get_prisoner_status(self, user_id: str) -> dict:
        """Get comprehensive prisoner status."""
        status = {
            'in_solitary': False,
            'solitary_severity': 0,
            'good_behavior_score': 0,
            'harassment_reduction': 1.0,
            'escape_attempts': 0
        }
        
        # Check solitary
        in_solitary, severity = await self.check_solitary_confinement(user_id, "prisoner")
        status['in_solitary'] = in_solitary
        status['solitary_severity'] = severity
        
        # Check good behavior
        if user_id in self.good_behavior_tracking:
            status['good_behavior_score'] = self.good_behavior_tracking[user_id].get('behavior_score', 0)
            status['harassment_reduction'] = self.calculate_harassment_reduction(user_id)
        
        # Check escape attempts
        status['escape_attempts'] = len(self.escape_attempts.get(user_id, []))
        
        return status
    
    async def start(self):
        """Start the prison service."""
        logger.log_info("Prison service started")
    
    async def stop(self):
        """Stop the prison service."""
        logger.log_info("Prison service stopped")
    
    async def health_check(self):
        """Health check for the prison service."""
        from src.services.base_service import HealthCheckResult, ServiceStatus
        
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message="Prison service operational",
            details={
                "solitary_prisoners": len(self.solitary_prisoners),
                "good_behavior_tracking": len(self.good_behavior_tracking),
                "escape_attempts": len(self.escape_attempts)
            }
        )
    
    async def shutdown(self):
        """Shutdown the prison service."""
        logger.log_info("Prison service shutting down...")
        await super().shutdown()