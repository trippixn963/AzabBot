"""
Prison Management Service
Handles Solitary Confinement, Good Behavior, and Prison Break Detection
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import discord
from src.services.base_service import BaseService
from src.core.logger import get_logger

log_info = get_logger().log_info
log_warning = get_logger().log_warning
log_error = get_logger().log_error


class PrisonService(BaseService):
    """Service for managing advanced prison features."""
    
    def __init__(self, container):
        """Initialize prison service."""
        super().__init__(container)
        self.db_service = None
        self.ai_service = None
        
        # Tracking dictionaries
        self.solitary_prisoners: Dict[str, dict] = {}
        self.good_behavior_tracking: Dict[str, dict] = {}
        self.escape_attempts: Dict[str, list] = {}
        
        # Configuration
        self.solitary_threshold = 3  # Offenses before solitary
        self.good_behavior_quiet_time = 300  # 5 minutes of quiet for good behavior
        self.harassment_reduction_per_level = 0.15  # 15% reduction per good behavior level
        
    async def initialize(self):
        """Initialize the prison service."""
        try:
            await super().initialize()
            
            # Get services
            self.db_service = self.container.get("DatabaseService")
            self.ai_service = self.container.get("AIService")
            
            # Initialize database tables
            await self._initialize_database()
            
            # Load existing data
            await self._load_prison_data()
            
            log_info("🔒 Prison service initialized")
            
        except Exception as e:
            log_error(f"Failed to initialize prison service: {e}")
            raise
    
    async def _initialize_database(self):
        """Initialize prison feature tables."""
        try:
            # Read and execute the schema
            with open("data/prison_features.sql", "r") as f:
                schema = f.read()
            
            # Execute each statement separately
            statements = [s.strip() for s in schema.split(';') if s.strip()]
            for statement in statements:
                await self.db_service.execute(statement + ';')
            
            log_info("Prison feature tables initialized")
            
        except Exception as e:
            log_error(f"Failed to initialize prison tables: {e}")
    
    async def _load_prison_data(self):
        """Load existing prison data from database."""
        try:
            # Load solitary confinement data
            solitary_data = await self.db_service.fetch_all(
                "SELECT * FROM solitary_confinement WHERE in_solitary = 1"
            )
            for row in solitary_data:
                self.solitary_prisoners[row['discord_id']] = dict(row)
            
            # Load good behavior data
            behavior_data = await self.db_service.fetch_all(
                "SELECT * FROM good_behavior WHERE behavior_score > 0"
            )
            for row in behavior_data:
                self.good_behavior_tracking[row['discord_id']] = dict(row)
            
            log_info(f"Loaded {len(self.solitary_prisoners)} in solitary, "
                    f"{len(self.good_behavior_tracking)} with good behavior")
            
        except Exception as e:
            log_warning(f"Could not load prison data: {e}")
    
    # ============= SOLITARY CONFINEMENT =============
    
    async def check_solitary_confinement(self, user_id: str, username: str) -> Tuple[bool, int]:
        """
        Check if user should be in solitary confinement.
        Returns (is_in_solitary, severity_level)
        """
        try:
            # Check existing solitary status
            result = await self.db_service.fetch_one(
                """SELECT * FROM solitary_confinement 
                   WHERE discord_id = ? AND in_solitary = 1""",
                (user_id,)
            )
            
            if result:
                return True, result['severity_level']
            
            # Check offense count
            result = await self.db_service.fetch_one(
                """SELECT offense_count, severity_level 
                   FROM solitary_confinement 
                   WHERE discord_id = ?""",
                (user_id,)
            )
            
            if result and result['offense_count'] >= self.solitary_threshold:
                # Put them in solitary
                await self.enter_solitary_confinement(user_id, username)
                return True, min(result['severity_level'] + 1, 5)
            
            return False, 0
            
        except Exception as e:
            log_error(f"Error checking solitary confinement: {e}")
            return False, 0
    
    async def enter_solitary_confinement(self, user_id: str, username: str):
        """Place a prisoner in solitary confinement."""
        try:
            now = datetime.utcnow()
            
            # Update database
            existing = await self.db_service.fetch_one(
                "SELECT * FROM solitary_confinement WHERE discord_id = ?",
                (user_id,)
            )
            
            if existing:
                # Update existing record
                new_severity = min(existing['severity_level'] + 1, 5)
                await self.db_service.execute(
                    """UPDATE solitary_confinement 
                       SET in_solitary = 1, 
                           solitary_start = ?,
                           severity_level = ?,
                           offense_count = offense_count + 1
                       WHERE discord_id = ?""",
                    (now, new_severity, user_id)
                )
                severity = new_severity
            else:
                # Create new record
                prisoner_id = await self._get_or_create_prisoner_id(user_id, username)
                await self.db_service.execute(
                    """INSERT INTO solitary_confinement 
                       (prisoner_id, discord_id, in_solitary, solitary_start, severity_level)
                       VALUES (?, ?, 1, ?, 1)""",
                    (prisoner_id, user_id, now)
                )
                severity = 1
            
            # Update tracking
            self.solitary_prisoners[user_id] = {
                'start_time': now,
                'severity_level': severity
            }
            
            log_info(f"🔒 {username} entered solitary confinement (Level {severity})")
            
        except Exception as e:
            log_error(f"Error entering solitary confinement: {e}")
    
    async def release_from_solitary(self, user_id: str):
        """Release a prisoner from solitary confinement."""
        try:
            now = datetime.utcnow()
            
            # Update database
            await self.db_service.execute(
                """UPDATE solitary_confinement 
                   SET in_solitary = 0, 
                       solitary_end = ?,
                       total_time_in_solitary = total_time_in_solitary + 
                           (CAST((julianday(?) - julianday(solitary_start)) * 1440 AS INTEGER))
                   WHERE discord_id = ? AND in_solitary = 1""",
                (now, now, user_id)
            )
            
            # Remove from tracking
            if user_id in self.solitary_prisoners:
                del self.solitary_prisoners[user_id]
            
            log_info(f"🔓 Released {user_id} from solitary confinement")
            
        except Exception as e:
            log_error(f"Error releasing from solitary: {e}")
    
    def get_solitary_harassment_multiplier(self, user_id: str) -> float:
        """Get harassment multiplier for solitary confinement."""
        if user_id not in self.solitary_prisoners:
            return 1.0
        
        severity = self.solitary_prisoners[user_id].get('severity_level', 1)
        # Each severity level increases harassment by 50%
        return 1.0 + (severity * 0.5)
    
    # ============= GOOD BEHAVIOR SYSTEM =============
    
    async def track_good_behavior(self, user_id: str, username: str, is_quiet: bool):
        """Track prisoner's behavior (quiet = good)."""
        try:
            now = datetime.utcnow()
            
            if user_id not in self.good_behavior_tracking:
                # Initialize tracking
                prisoner_id = await self._get_or_create_prisoner_id(user_id, username)
                self.good_behavior_tracking[user_id] = {
                    'prisoner_id': prisoner_id,
                    'behavior_score': 0,
                    'quiet_minutes': 0,
                    'last_message': now,
                    'quiet_start': now if is_quiet else None
                }
                
                # Create database record
                await self.db_service.execute(
                    """INSERT OR IGNORE INTO good_behavior 
                       (prisoner_id, discord_id, last_message)
                       VALUES (?, ?, ?)""",
                    (prisoner_id, user_id, now)
                )
            
            tracking = self.good_behavior_tracking[user_id]
            
            if is_quiet:
                # Check if they've been quiet long enough
                if tracking.get('quiet_start'):
                    quiet_duration = (now - tracking['quiet_start']).total_seconds()
                    
                    if quiet_duration >= self.good_behavior_quiet_time:
                        # Award good behavior points
                        await self._award_good_behavior(user_id, quiet_duration)
                else:
                    tracking['quiet_start'] = now
            else:
                # They spoke, reset quiet timer
                tracking['quiet_start'] = None
                tracking['last_message'] = now
                
                # Update database
                await self.db_service.execute(
                    """UPDATE good_behavior 
                       SET last_message = ?
                       WHERE discord_id = ?""",
                    (now, user_id)
                )
            
        except Exception as e:
            log_error(f"Error tracking good behavior: {e}")
    
    async def _award_good_behavior(self, user_id: str, quiet_duration: float):
        """Award good behavior points."""
        try:
            points = int(quiet_duration / 60)  # 1 point per minute quiet
            
            # Update tracking
            self.good_behavior_tracking[user_id]['behavior_score'] += points
            self.good_behavior_tracking[user_id]['quiet_minutes'] += int(quiet_duration / 60)
            
            # Update database
            await self.db_service.execute(
                """UPDATE good_behavior 
                   SET behavior_score = behavior_score + ?,
                       quiet_minutes = quiet_minutes + ?,
                       consecutive_quiet_sessions = consecutive_quiet_sessions + 1,
                       harassment_reduction = MIN(0.75, harassment_reduction + ?)
                   WHERE discord_id = ?""",
                (points, int(quiet_duration / 60), self.harassment_reduction_per_level, user_id)
            )
            
            log_info(f"✅ Awarded {points} good behavior points to {user_id}")
            
        except Exception as e:
            log_error(f"Error awarding good behavior: {e}")
    
    async def reset_good_behavior(self, user_id: str, reason: str = "bad behavior"):
        """Reset good behavior score for bad behavior."""
        try:
            # Update database
            await self.db_service.execute(
                """UPDATE good_behavior 
                   SET behavior_score = 0,
                       consecutive_quiet_sessions = 0,
                       harassment_reduction = 0,
                       good_behavior_streak = 0,
                       last_reset = ?
                   WHERE discord_id = ?""",
                (datetime.utcnow(), user_id)
            )
            
            # Update tracking
            if user_id in self.good_behavior_tracking:
                self.good_behavior_tracking[user_id]['behavior_score'] = 0
            
            log_info(f"❌ Reset good behavior for {user_id}: {reason}")
            
        except Exception as e:
            log_error(f"Error resetting good behavior: {e}")
    
    def get_good_behavior_reduction(self, user_id: str) -> float:
        """Get harassment reduction for good behavior (0.0 to 0.75)."""
        if user_id not in self.good_behavior_tracking:
            return 0.0
        
        score = self.good_behavior_tracking[user_id].get('behavior_score', 0)
        # Max 75% reduction, 5% per 10 points
        reduction = min(0.75, (score / 10) * 0.05)
        return reduction
    
    # ============= PRISON BREAK DETECTION =============
    
    async def detect_prison_break(self, user_id: str, username: str, 
                                 attempt_type: str, was_muted: bool = True):
        """Detect and record prison break attempts."""
        try:
            now = datetime.utcnow()
            
            # Track the attempt
            if user_id not in self.escape_attempts:
                self.escape_attempts[user_id] = []
            
            self.escape_attempts[user_id].append({
                'type': attempt_type,
                'time': now,
                'was_muted': was_muted
            })
            
            # Get prisoner ID
            prisoner_id = await self._get_or_create_prisoner_id(user_id, username)
            
            # Record in database
            await self.db_service.execute(
                """INSERT INTO prison_breaks 
                   (prisoner_id, discord_id, attempt_type, attempt_time, was_muted)
                   VALUES (?, ?, ?, ?, ?)""",
                (prisoner_id, user_id, attempt_type, now, was_muted)
            )
            
            # Escalate punishment
            await self._escalate_punishment(user_id, username, "prison_break")
            
            # Reset good behavior
            await self.reset_good_behavior(user_id, "prison break attempt")
            
            # Check if they should go to solitary
            attempt_count = len(self.escape_attempts[user_id])
            if attempt_count >= 2:  # 2 attempts = solitary
                await self.enter_solitary_confinement(user_id, username)
            
            log_warning(f"🚨 PRISON BREAK ATTEMPT: {username} tried {attempt_type}")
            
            return True
            
        except Exception as e:
            log_error(f"Error detecting prison break: {e}")
            return False
    
    async def _escalate_punishment(self, user_id: str, username: str, reason: str):
        """Escalate punishment level for bad behavior."""
        try:
            prisoner_id = await self._get_or_create_prisoner_id(user_id, username)
            
            # Check existing escalation
            result = await self.db_service.fetch_one(
                "SELECT * FROM punishment_escalation WHERE discord_id = ?",
                (user_id,)
            )
            
            if result:
                # Increase level
                new_level = min(result['current_level'] + 1, 10)
                await self.db_service.execute(
                    """UPDATE punishment_escalation 
                       SET current_level = ?,
                           total_offenses = total_offenses + 1,
                           break_attempts = break_attempts + ?,
                           bad_behavior_incidents = bad_behavior_incidents + ?,
                           last_escalation = ?
                       WHERE discord_id = ?""",
                    (new_level, 
                     1 if reason == "prison_break" else 0,
                     1 if reason == "bad_behavior" else 0,
                     datetime.utcnow(), user_id)
                )
            else:
                # Create new escalation record
                await self.db_service.execute(
                    """INSERT INTO punishment_escalation 
                       (prisoner_id, discord_id, current_level, total_offenses)
                       VALUES (?, ?, 1, 1)""",
                    (prisoner_id, user_id)
                )
            
        except Exception as e:
            log_error(f"Error escalating punishment: {e}")
    
    async def _get_or_create_prisoner_id(self, user_id: str, username: str) -> int:
        """Get or create prisoner ID."""
        try:
            # Check if prisoner exists
            result = await self.db_service.fetch_one(
                "SELECT id FROM prisoners WHERE discord_id = ?",
                (user_id,)
            )
            
            if result:
                return result['id']
            
            # Create new prisoner
            await self.db_service.execute(
                """INSERT INTO prisoners (discord_id, username, display_name)
                   VALUES (?, ?, ?)""",
                (user_id, username, username)
            )
            
            # Get the new ID
            result = await self.db_service.fetch_one(
                "SELECT id FROM prisoners WHERE discord_id = ?",
                (user_id,)
            )
            
            return result['id'] if result else 0
            
        except Exception as e:
            log_error(f"Error getting prisoner ID: {e}")
            return 0
    
    # ============= ANALYSIS METHODS =============
    
    async def get_prisoner_status(self, user_id: str) -> dict:
        """Get comprehensive prisoner status."""
        try:
            status = {
                'in_solitary': user_id in self.solitary_prisoners,
                'solitary_level': 0,
                'good_behavior_score': 0,
                'harassment_reduction': 0.0,
                'escape_attempts': 0,
                'punishment_level': 1
            }
            
            # Check solitary
            if status['in_solitary']:
                status['solitary_level'] = self.solitary_prisoners[user_id].get('severity_level', 1)
            
            # Check good behavior
            if user_id in self.good_behavior_tracking:
                status['good_behavior_score'] = self.good_behavior_tracking[user_id].get('behavior_score', 0)
                status['harassment_reduction'] = self.get_good_behavior_reduction(user_id)
            
            # Check escape attempts
            if user_id in self.escape_attempts:
                status['escape_attempts'] = len(self.escape_attempts[user_id])
            
            # Check punishment level
            result = await self.db_service.fetch_one(
                "SELECT current_level FROM punishment_escalation WHERE discord_id = ?",
                (user_id,)
            )
            if result:
                status['punishment_level'] = result['current_level']
            
            return status
            
        except Exception as e:
            log_error(f"Error getting prisoner status: {e}")
            return {}
    
    def calculate_harassment_intensity(self, user_id: str) -> float:
        """Calculate overall harassment intensity based on all factors."""
        base_intensity = 1.0
        
        # Solitary confinement increases intensity
        solitary_mult = self.get_solitary_harassment_multiplier(user_id)
        
        # Good behavior reduces intensity
        good_behavior_reduction = self.get_good_behavior_reduction(user_id)
        
        # Calculate final intensity
        intensity = base_intensity * solitary_mult * (1.0 - good_behavior_reduction)
        
        # Ensure it's between 0.25 and 5.0
        return max(0.25, min(5.0, intensity))
    
    async def shutdown(self):
        """Shutdown the prison service."""
        try:
            log_info("Prison service shutting down...")
            await super().shutdown()
        except Exception as e:
            log_error(f"Error shutting down prison service: {e}")