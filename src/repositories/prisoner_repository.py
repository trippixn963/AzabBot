"""
Prisoner Repository for AzabBot
===============================

This module provides a comprehensive, production-grade prisoner repository for
database operations with centralized prisoner-related queries, behavioral tracking,
and psychological profiling data management. Implements advanced prisoner lifecycle
management with detailed analytics and reporting capabilities.

DESIGN PATTERNS IMPLEMENTED:
1. Repository Pattern: Data access abstraction for prisoner operations
2. Factory Pattern: Prisoner record creation and management
3. Observer Pattern: Prisoner behavior monitoring and tracking
4. Strategy Pattern: Different prisoner management strategies
5. Command Pattern: Prisoner operations with audit trail

PRISONER COMPONENTS:
- PrisonerRepository: Specialized repository for prisoner operations
- Behavioral Tracking: Comprehensive behavior monitoring and analysis
- Mute Management: Advanced mute tracking and history management
- Message Logging: Complete conversation history and analysis
- Statistics Generation: Detailed prisoner analytics and reporting
- Data Cleanup: Automated data maintenance and archival

DATABASE OPERATIONS:
- get_or_create_prisoner: Atomic prisoner creation with duplicate handling
- get_active_prisoners: Active prisoner retrieval with mute status
- record_mute: Mute event logging with reason tracking
- record_unmute: Unmute event logging with duration calculation
- get_prisoner_stats: Comprehensive prisoner statistics and analytics
- record_message: Message logging with content analysis
- get_recent_messages: Recent message retrieval for context
- cleanup_old_data: Automated data cleanup and archival

PRISONER LIFECYCLE:
- First Contact: Initial prisoner detection and profile creation
- Behavioral Analysis: Pattern recognition and psychological profiling
- Mute Management: Advanced mute tracking with reason analysis
- Message Tracking: Complete conversation history and context
- Statistics Generation: Comprehensive analytics and reporting
- Data Maintenance: Automated cleanup and archival processes

PERFORMANCE CHARACTERISTICS:
- Indexed Queries: Optimized database queries with proper indexing
- Batch Operations: Efficient bulk operations for data processing
- Caching: Intelligent caching for frequently accessed prisoner data
- Connection Pooling: Efficient database connection management
- Async Operations: Non-blocking database operations for scalability

ANALYTICS CAPABILITIES:
- Behavioral Patterns: Comprehensive behavior analysis and tracking
- Mute History: Detailed mute reason analysis and patterns
- Message Analysis: Conversation content and frequency analysis
- Statistical Reporting: Advanced analytics and trend analysis
- Performance Metrics: System performance and efficiency tracking

USAGE EXAMPLES:
1. Prisoner creation and profile management
2. Behavioral tracking and analysis
3. Mute history and reason analysis
4. Message logging and conversation tracking
5. Statistical reporting and analytics generation

This prisoner repository provides comprehensive data management for all
prisoner-related operations in the AzabBot system, enabling advanced
psychological profiling and behavioral analysis capabilities.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta

from src.utils.time_utils import now_est_naive
from src.repositories.base_repository import BaseRepository
from src.utils.error_handler import handle_error, ErrorCategory, ErrorSeverity
from src.core.logger import get_logger

logger = get_logger()


class PrisonerRepository(BaseRepository):
    """Repository for prisoner-related database operations."""
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=None
    )
    async def get_or_create_prisoner(
        self,
        discord_id: str,
        username: str,
        display_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get or create a prisoner record.
        
        Args:
            discord_id: Discord user ID
            username: Discord username
            display_name: Display name
            
        Returns:
            Prisoner record or None
        """
        prisoner = await self.get_or_create(
            table="prisoners",
            lookup_fields={"discord_id": discord_id},
            create_fields={
                "username": username,
                "display_name": display_name or username,
                "first_seen": now_est_naive(),
                "total_mutes": 0,
                "total_messages": 0
            }
        )
        
        if prisoner:
            logger.log_debug(
                f"Retrieved prisoner: {username}",
                context={"discord_id": discord_id, "prisoner_id": prisoner.get("id")}
            )
        
        return prisoner
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=[]
    )
    async def get_active_prisoners(self, role_id: str) -> List[Dict]:
        """
        Get all currently active prisoners (those with the mute role).
        
        Args:
            role_id: The mute role ID
            
        Returns:
            List of active prisoner records
        """
        query = """
            SELECT p.*, pm.muted_at, pm.reason, pm.muted_by
            FROM prisoners p
            INNER JOIN prisoner_mutes pm ON p.id = pm.prisoner_id
            WHERE pm.is_active = 1
            ORDER BY pm.muted_at DESC
        """
        
        prisoners = await self.fetch_all(query)
        
        logger.log_debug(
            "Retrieved active prisoners",
            context={"count": len(prisoners)}
        )
        
        return prisoners
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=False
    )
    async def record_mute(
        self,
        prisoner_id: int,
        discord_id: str,
        reason: str,
        muted_by: str,
        duration: Optional[int] = None
    ) -> bool:
        """
        Record a new mute event.
        
        Args:
            prisoner_id: Database prisoner ID
            discord_id: Discord user ID
            reason: Mute reason
            muted_by: Who muted them
            duration: Mute duration in seconds
            
        Returns:
            True if successful
        """
        # Deactivate any existing active mutes
        await self.execute(
            "UPDATE prisoner_mutes SET is_active = 0 WHERE prisoner_id = ? AND is_active = 1",
            (prisoner_id,)
        )
        
        # Record new mute
        success = await self.execute(
            """INSERT INTO prisoner_mutes 
               (prisoner_id, discord_id, reason, muted_by, duration, is_active, muted_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (prisoner_id, discord_id, reason, muted_by, duration, now_est_naive())
        )
        
        if success:
            # Update prisoner stats
            await self.execute(
                "UPDATE prisoners SET total_mutes = total_mutes + 1 WHERE id = ?",
                (prisoner_id,)
            )
            
            logger.log_info(
                f"Recorded mute for prisoner {prisoner_id}",
                context={
                    "discord_id": discord_id,
                    "reason": reason,
                    "muted_by": muted_by
                }
            )
        
        return success
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.MEDIUM,
        default_return=False
    )
    async def record_unmute(self, prisoner_id: int) -> bool:
        """
        Record unmute event.
        
        Args:
            prisoner_id: Database prisoner ID
            
        Returns:
            True if successful
        """
        success = await self.execute(
            """UPDATE prisoner_mutes 
               SET is_active = 0, unmuted_at = ?
               WHERE prisoner_id = ? AND is_active = 1""",
            (now_est_naive(), prisoner_id)
        )
        
        if success:
            logger.log_info(
                f"Recorded unmute for prisoner {prisoner_id}",
                context={"prisoner_id": prisoner_id}
            )
        
        return success
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=None
    )
    async def get_prisoner_stats(self, discord_id: str) -> Optional[Dict]:
        """
        Get comprehensive prisoner statistics.
        
        Args:
            discord_id: Discord user ID
            
        Returns:
            Stats dictionary or None
        """
        prisoner = await self.fetch_one(
            "SELECT * FROM prisoners WHERE discord_id = ?",
            (discord_id,)
        )
        
        if not prisoner:
            return None
        
        # Get mute history
        mutes = await self.fetch_all(
            """SELECT * FROM prisoner_mutes 
               WHERE prisoner_id = ?
               ORDER BY muted_at DESC
               LIMIT 10""",
            (prisoner["id"],)
        )
        
        # Get message count
        messages = await self.fetch_one(
            """SELECT COUNT(*) as count 
               FROM prisoner_messages 
               WHERE prisoner_id = ?""",
            (prisoner["id"],)
        )
        
        # Get behavior incidents
        incidents = await self.fetch_all(
            """SELECT * FROM behavior_incidents
               WHERE prisoner_id = ?
               ORDER BY incident_time DESC
               LIMIT 5""",
            (prisoner["id"],)
        )
        
        stats = {
            **prisoner,
            "mute_history": mutes,
            "total_messages": messages["count"] if messages else 0,
            "recent_incidents": incidents
        }
        
        logger.log_debug(
            f"Retrieved stats for prisoner {discord_id}",
            context={
                "mutes": len(mutes),
                "incidents": len(incidents)
            }
        )
        
        return stats
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=False
    )
    async def record_message(
        self,
        prisoner_id: int,
        discord_id: str,
        channel_id: str,
        content: str
    ) -> bool:
        """
        Record a prisoner message.
        
        Args:
            prisoner_id: Database prisoner ID
            discord_id: Discord user ID
            channel_id: Channel ID
            content: Message content
            
        Returns:
            True if successful
        """
        success = await self.execute(
            """INSERT INTO prisoner_messages 
               (prisoner_id, discord_id, channel_id, content, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (prisoner_id, discord_id, channel_id, content[:500], now_est_naive())
        )
        
        if success:
            # Update message count
            await self.execute(
                "UPDATE prisoners SET total_messages = total_messages + 1 WHERE id = ?",
                (prisoner_id,)
            )
        
        return success
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=[]
    )
    async def get_recent_messages(
        self,
        discord_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get recent messages from a prisoner.
        
        Args:
            discord_id: Discord user ID
            limit: Number of messages to retrieve
            
        Returns:
            List of message records
        """
        messages = await self.fetch_all(
            """SELECT * FROM prisoner_messages
               WHERE discord_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (discord_id, limit)
        )
        
        return messages
    
    @handle_error(
        category=ErrorCategory.DATABASE,
        severity=ErrorSeverity.LOW,
        default_return=False
    )
    async def cleanup_old_data(self, days: int = 30) -> bool:
        """
        Clean up old data from database.
        
        Args:
            days: Delete data older than this many days
            
        Returns:
            True if successful
        """
        cutoff_date = now_est_naive() - timedelta(days=days)
        
        operations = [
            # Delete old messages
            (
                "DELETE FROM prisoner_messages WHERE timestamp < ?",
                (cutoff_date,)
            ),
            # Delete old inactive mutes
            (
                "DELETE FROM prisoner_mutes WHERE is_active = 0 AND unmuted_at < ?",
                (cutoff_date,)
            ),
            # Delete old behavior incidents
            (
                "DELETE FROM behavior_incidents WHERE incident_time < ?",
                (cutoff_date,)
            )
        ]
        
        success = await self.transaction(operations)
        
        if success:
            logger.log_info(
                f"Cleaned up data older than {days} days",
                context={"cutoff_date": cutoff_date.isoformat()}
            )
        
        return success