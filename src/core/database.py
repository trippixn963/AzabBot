"""
Azab Discord Bot - Database Module
=================================

SQLite database wrapper for storing user messages and analytics.
Provides async database operations for logging Discord interactions
and maintaining user statistics.

Features:
- User message logging and counting
- Message content storage with timestamps
- User imprisonment status tracking
- Async database operations

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.2.0
"""

import sqlite3
import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple, Optional
from .logger import logger


class Database:
    """
    SQLite database wrapper for Azab Discord bot.
    
    Handles all database operations including:
    - User information storage and updates
    - Message logging with timestamps
    - User statistics tracking
    - Async database operations for performance
    
    Database Schema:
    - users: User information and message counts
    - messages: Individual message logs with metadata
    """
    
    def __init__(self) -> None:
        """
        Initialize the database connection and create tables.
        
        Creates the database file in data/ directory and initializes
        required tables for user and message storage.
        """
        self.db_path: Path = Path('data/azab.db')
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """
        Initialize database tables and indexes.
        
        Creates the database schema with three main tables:
        1. users: User information and statistics
        2. messages: Individual message logs for analytics
        3. prisoner_history: Complete mute/unmute event tracking
        
        Sets up proper indexes for optimal query performance.
        """
        conn: sqlite3.Connection = sqlite3.connect(self.db_path)
        
        # Users table: Core user information and denormalized statistics
        # user_id: Discord user ID (primary key for fast lookups)
        # username: Current Discord username (updated on each message)
        # messages_count: Denormalized counter for analytics (updated incrementally)
        # is_imprisoned: Denormalized status flag for quick mute checks
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            messages_count INTEGER DEFAULT 0,
            is_imprisoned BOOLEAN DEFAULT 0
        )''')
        
        # Messages table: Individual message logs for analytics and debugging
        # id: Auto-incrementing primary key for message ordering
        # user_id: Foreign key reference to users table
        # content: Message text (truncated to prevent bloat)
        # channel_id/guild_id: Discord channel and server identifiers
        # timestamp: EST timestamp for consistent logging across timezones
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            channel_id INTEGER,
            guild_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Prisoner history table: Complete audit trail of all mute/unmute events
        # id: Auto-incrementing primary key for event ordering
        # user_id: Discord user ID (indexed for fast user lookups)
        # username: Username at time of mute (preserved for historical accuracy)
        # mute_reason: Reason for mute (extracted from moderation bot embeds)
        # muted_at: Timestamp when mute was applied
        # unmuted_at: Timestamp when mute was removed (NULL if still active)
        # duration_minutes: Calculated duration in minutes (NULL if still active)
        # muted_by/unmuted_by: Moderator who applied/removed mute
        # is_active: Boolean flag for quick active mute lookups (indexed)
        # trigger_message: The message content that led to the mute
        conn.execute('''CREATE TABLE IF NOT EXISTS prisoner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            mute_reason TEXT,
            trigger_message TEXT,
            muted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            unmuted_at TIMESTAMP,
            duration_minutes INTEGER,
            muted_by TEXT,
            unmuted_by TEXT,
            is_active BOOLEAN DEFAULT 1
        )''')
        
        # Create indexes for optimal query performance
        # Index on user_id for fast prisoner history lookups
        conn.execute('CREATE INDEX IF NOT EXISTS idx_prisoner_user ON prisoner_history(user_id)')
        # Index on is_active for fast active mute queries
        conn.execute('CREATE INDEX IF NOT EXISTS idx_prisoner_active ON prisoner_history(is_active)')

        # Add trigger_message column if it doesn't exist (migration)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(prisoner_history)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'trigger_message' not in columns:
            conn.execute('ALTER TABLE prisoner_history ADD COLUMN trigger_message TEXT')
            logger.info("Added trigger_message column to prisoner_history table")

        # Create roast_history table for tracking AI responses to avoid repetition
        conn.execute('''CREATE TABLE IF NOT EXISTS roast_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            roast_text TEXT,
            roast_category TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mute_session_id INTEGER,
            FOREIGN KEY (mute_session_id) REFERENCES prisoner_history(id)
        )''')

        # Create user_profiles table for building behavioral patterns
        conn.execute('''CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            favorite_excuse TEXT,
            most_used_words TEXT,
            personality_type TEXT,
            total_roasts_received INTEGER DEFAULT 0,
            last_roast_time TIMESTAMP,
            callback_references TEXT
        )''')

        # Indexes for roast history
        conn.execute('CREATE INDEX IF NOT EXISTS idx_roast_user ON roast_history(user_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_roast_session ON roast_history(mute_session_id)')

        # Commit schema changes and close connection
        conn.commit()
        conn.close()
    
    async def log_message(self, user_id: int, username: str, content: str, channel_id: int, guild_id: int) -> None:
        """
        Log a Discord message to the database.

        Stores the message content, user information, and metadata.
        Updates user statistics including message count.

        Args:
            user_id (int): Discord user ID
            username (str): Discord username
            content (str): Message content (truncated to 500 chars)
            channel_id (int): Discord channel ID
            guild_id (int): Discord guild/server ID
        """
        # Import validators here to avoid circular import
        from src.utils.validators import Validators, ValidationError

        # Validate and sanitize inputs
        try:
            user_id = Validators.validate_discord_id(user_id)
            username = Validators.validate_username(username) or "Unknown User"
            content = Validators.validate_message_content(content, 500)
            channel_id = Validators.validate_channel_id(channel_id)
            guild_id = Validators.validate_discord_id(guild_id, "guild_id")
        except ValidationError as e:
            logger.warning(f"Validation error in log_message: {e}")
            return
        def _log() -> None:
            """
            Internal function to log message to database.
            Runs in thread pool to avoid blocking the main event loop.
            
            Database Operations:
            1. UPSERT user information (insert new or update existing)
            2. Insert message with EST timestamp for consistent logging
            3. Increment user's message count for analytics
            """
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # UPSERT user information (insert new user or update existing username)
            # This ensures we always have current username even if user changes it
            conn.execute('INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)',
                        (user_id, username))
            
            # Insert message log with EST timestamp for consistent timezone logging
            # Convert to EST timezone to maintain consistency across different server locations
            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            est_timestamp: str = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
            
            # Truncate message content to prevent database bloat and respect limits
            truncated_content = content[:int(os.getenv('MESSAGE_CONTENT_MAX_LENGTH', '500'))]
            conn.execute('INSERT INTO messages (user_id, content, channel_id, guild_id, timestamp) VALUES (?, ?, ?, ?, ?)',
                        (user_id, truncated_content, channel_id, guild_id, est_timestamp))
            
            # Increment user's message count for analytics and statistics
            # This provides data for user activity tracking and bot usage metrics
            conn.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?',
                        (user_id,))
            
            # Commit transaction to ensure data persistence
            conn.commit()
            conn.close()
        
        # Run database operations in thread pool to avoid blocking
        await asyncio.to_thread(_log)
    
    async def record_mute(self, user_id: int, username: str, reason: str, muted_by: Optional[str] = None, trigger_message: Optional[str] = None) -> None:
        """
        Record a new mute event in prisoner history.

        Args:
            user_id: Discord user ID
            username: Discord username
            reason: Reason for mute
            muted_by: Who issued the mute (moderator name)
            trigger_message: The message content that triggered the mute
        """
        # Import validators here to avoid circular import
        from src.utils.validators import Validators, ValidationError

        # Validate and sanitize inputs
        try:
            user_id = Validators.validate_discord_id(user_id)
            username = Validators.validate_username(username) or "Unknown User"
            reason = Validators.validate_mute_reason(reason)
            if muted_by:
                muted_by = Validators.validate_username(muted_by, allow_none=True)
            if trigger_message:
                trigger_message = Validators.validate_message_content(trigger_message, 500)
        except ValidationError as e:
            logger.error(f"Validation error in record_mute: {e}")
            return
        def _record() -> None:
            """
            Internal function to record a new mute event in the database.
            Handles re-mute scenarios by deactivating previous mutes first.
            
            Database Operations:
            1. Deactivate any existing active mutes for this user (re-mute scenario)
            2. Insert new mute record with current timestamp
            3. Update user's imprisoned status for quick lookups
            """
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # Handle re-mute scenario: deactivate any existing active mutes first
            # This prevents multiple active mutes for the same user and maintains data integrity
            conn.execute('UPDATE prisoner_history SET is_active = 0 WHERE user_id = ? AND is_active = 1',
                        (user_id,))
            
            # Insert new mute record with current timestamp and active status
            # is_active = 1 indicates this is the current active mute for the user
            conn.execute('''INSERT INTO prisoner_history
                           (user_id, username, mute_reason, muted_by, trigger_message, is_active)
                           VALUES (?, ?, ?, ?, ?, 1)''',
                        (user_id, username, reason, muted_by, trigger_message))
            
            # Update user's imprisoned status for quick lookups without querying history
            # This denormalized field improves performance for frequent status checks
            conn.execute('UPDATE users SET is_imprisoned = 1 WHERE user_id = ?', (user_id,))
            
            # Commit transaction to ensure all changes are persisted atomically
            conn.commit()
            conn.close()
        
        await asyncio.to_thread(_record)
    
    async def record_unmute(self, user_id: int, unmuted_by: Optional[str] = None) -> None:
        """
        Record unmute event and calculate imprisonment duration.
        
        Args:
            user_id: Discord user ID
            unmuted_by: Who removed the mute
        """
        def _record() -> None:
            """
            Internal function to record an unmute event and calculate imprisonment duration.
            Updates the active mute record with release information and duration.
            
            Database Operations:
            1. Calculate mute duration using SQLite's JULIANDAY function
            2. Update active mute record with unmute timestamp and duration
            3. Update user's imprisoned status for quick lookups
            """
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # Get EST timezone for consistent timestamp logging
            # Convert to EST to maintain consistency with mute timestamps
            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            current_time: str = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
            
            # Update the active mute record with release information and duration calculation
            # JULIANDAY function calculates precise duration in minutes between mute and unmute
            # ABS() ensures positive duration even if timestamps are somehow reversed
            # ROUND() converts fractional minutes to whole minutes for cleaner data
            conn.execute('''UPDATE prisoner_history
                           SET unmuted_at = ?,
                               unmuted_by = ?,
                               is_active = 0,
                               duration_minutes = ABS(ROUND((JULIANDAY(?) - JULIANDAY(muted_at)) * 24 * 60))
                           WHERE user_id = ? AND is_active = 1''',
                        (current_time, unmuted_by, current_time, user_id))
            
            # Update user's imprisoned status for quick lookups without querying history
            # This denormalized field improves performance for frequent status checks
            conn.execute('UPDATE users SET is_imprisoned = 0 WHERE user_id = ?', (user_id,))
            
            # Commit transaction to ensure all changes are persisted atomically
            conn.commit()
            conn.close()
        
        await asyncio.to_thread(_record)
    
    async def get_current_mute_duration(self, user_id: int) -> int:
        """
        Get the duration of the current active mute session in minutes.

        Args:
            user_id: Discord user ID

        Returns:
            Duration in minutes of the current mute, 0 if not found
        """
        def _get_duration() -> int:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()

            # Get the current active mute and calculate duration from muted_at to now
            cursor.execute('''SELECT
                                ABS(ROUND((JULIANDAY('now') - JULIANDAY(muted_at)) * 24 * 60)) as duration
                             FROM prisoner_history
                             WHERE user_id = ? AND is_active = 1''', (user_id,))

            row = cursor.fetchone()
            conn.close()

            return row[0] if row and row[0] else 0

        return await asyncio.to_thread(_get_duration)

    async def get_prisoner_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive stats about a prisoner's history.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Dictionary with prisoner statistics
        """
        def _get_stats() -> Dict[str, Any]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()
            
            # Get all mute history
            cursor.execute('''SELECT COUNT(*) as total_mutes,
                                    SUM(duration_minutes) as total_minutes,
                                    MAX(muted_at) as last_mute,
                                    COUNT(DISTINCT mute_reason) as unique_reasons
                             FROM prisoner_history 
                             WHERE user_id = ?''', (user_id,))
            
            row: Optional[Tuple] = cursor.fetchone()
            
            # Get all reasons
            cursor.execute('''SELECT mute_reason, COUNT(*) as count 
                             FROM prisoner_history 
                             WHERE user_id = ? 
                             GROUP BY mute_reason
                             ORDER BY count DESC''', (user_id,))
            reasons: List[Tuple] = cursor.fetchall()
            
            # Check if currently muted
            cursor.execute('SELECT is_active, mute_reason FROM prisoner_history WHERE user_id = ? AND is_active = 1',
                          (user_id,))
            current: Optional[Tuple] = cursor.fetchone()
            
            conn.close()
            
            return {
                'total_mutes': row[0] or 0,
                'total_minutes': row[1] or 0,
                'last_mute': row[2],
                'unique_reasons': row[3] or 0,
                'reason_counts': {reason: count for reason, count in reasons},
                'is_currently_muted': bool(current),
                'current_reason': current[1] if current else None
            }
        
        return await asyncio.to_thread(_get_stats)
    
    async def get_top_prisoners(self, limit: int = None) -> List[Tuple]:
        """
        Get the most frequently muted users (repeat offenders).

        Args:
            limit: Number of top prisoners to return

        Returns:
            List of tuples (username, total_mutes, total_minutes)
        """
        if limit is None:
            limit = int(os.getenv('TOP_PRISONERS_DEFAULT_LIMIT', '10'))

        def _get_top() -> List[Tuple]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()
            
            cursor.execute('''SELECT username, 
                                    COUNT(*) as total_mutes,
                                    SUM(duration_minutes) as total_minutes
                             FROM prisoner_history
                             GROUP BY user_id
                             ORDER BY total_mutes DESC
                             LIMIT ?''', (limit,))
            
            results: List[Tuple] = cursor.fetchall()
            conn.close()
            return results
        
        return await asyncio.to_thread(_get_top)

    async def get_current_prisoners(self) -> List[Dict[str, Any]]:
        """
        Get all currently muted users.

        Returns:
            List of dictionaries with current prisoner information
        """
        def _get_current() -> List[Dict[str, Any]]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()

            cursor.execute('''SELECT user_id, username, mute_reason, muted_at, muted_by
                             FROM prisoner_history
                             WHERE is_active = 1
                             ORDER BY muted_at DESC''')

            results = []
            for row in cursor.fetchall():
                results.append({
                    'user_id': row[0],
                    'username': row[1],
                    'reason': row[2],
                    'muted_at': row[3],
                    'muted_by': row[4]
                })

            conn.close()
            return results

        return await asyncio.to_thread(_get_current)

    async def get_longest_sentence(self) -> Optional[Dict[str, Any]]:
        """
        Get the longest prison sentence ever served.

        Returns:
            Dictionary with longest sentence information
        """
        def _get_longest() -> Optional[Dict[str, Any]]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()

            cursor.execute('''SELECT username, duration_minutes, mute_reason, muted_at, unmuted_at
                             FROM prisoner_history
                             WHERE duration_minutes IS NOT NULL
                             ORDER BY duration_minutes DESC
                             LIMIT 1''')

            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'username': row[0],
                    'duration_minutes': row[1],
                    'reason': row[2],
                    'muted_at': row[3],
                    'unmuted_at': row[4]
                }
            return None

        return await asyncio.to_thread(_get_longest)

    async def get_prison_stats(self) -> Dict[str, Any]:
        """
        Get overall prison statistics.

        Returns:
            Dictionary with comprehensive prison statistics
        """
        def _get_stats() -> Dict[str, Any]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()

            # Total mutes ever
            cursor.execute('SELECT COUNT(*) FROM prisoner_history')
            total_mutes = cursor.fetchone()[0]

            # Currently muted
            cursor.execute('SELECT COUNT(*) FROM prisoner_history WHERE is_active = 1')
            current_prisoners = cursor.fetchone()[0]

            # Total unique prisoners
            cursor.execute('SELECT COUNT(DISTINCT user_id) FROM prisoner_history')
            unique_prisoners = cursor.fetchone()[0]

            # Total time served
            cursor.execute('SELECT SUM(duration_minutes) FROM prisoner_history WHERE duration_minutes IS NOT NULL')
            total_time = cursor.fetchone()[0] or 0

            # Most common reason
            cursor.execute('''SELECT mute_reason, COUNT(*) as count
                             FROM prisoner_history
                             WHERE mute_reason IS NOT NULL
                             GROUP BY mute_reason
                             ORDER BY count DESC
                             LIMIT 1''')
            top_reason = cursor.fetchone()

            conn.close()

            return {
                'total_mutes': total_mutes,
                'current_prisoners': current_prisoners,
                'unique_prisoners': unique_prisoners,
                'total_time_minutes': total_time,
                'most_common_reason': top_reason[0] if top_reason else None,
                'most_common_reason_count': top_reason[1] if top_reason else 0
            }

        return await asyncio.to_thread(_get_stats)

    async def search_prisoner_by_name(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Search for a prisoner by username (partial match).

        Args:
            username: Username to search for

        Returns:
            Dictionary with prisoner information or None
        """
        def _search() -> Optional[Dict[str, Any]]:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            cursor: sqlite3.Cursor = conn.cursor()

            # Search for user (case insensitive, partial match)
            cursor.execute('''SELECT user_id, username,
                                    COUNT(*) as total_mutes,
                                    SUM(duration_minutes) as total_minutes,
                                    GROUP_CONCAT(DISTINCT mute_reason) as reasons
                             FROM prisoner_history
                             WHERE LOWER(username) LIKE LOWER(?)
                             GROUP BY user_id
                             ORDER BY total_mutes DESC
                             LIMIT 1''', (f'%{username}%',))

            row = cursor.fetchone()

            if row:
                # Check if currently muted
                cursor.execute('SELECT mute_reason, muted_at FROM prisoner_history WHERE user_id = ? AND is_active = 1',
                              (row[0],))
                current = cursor.fetchone()

                # Get last mute date if not currently muted
                if not current:
                    cursor.execute('SELECT MAX(muted_at) FROM prisoner_history WHERE user_id = ?', (row[0],))
                    last_mute = cursor.fetchone()[0]
                else:
                    last_mute = None

                conn.close()

                return {
                    'user_id': row[0],
                    'username': row[1],
                    'total_mutes': row[2],
                    'total_minutes': row[3] or 0,
                    'reasons': row[4].split(',') if row[4] else [],
                    'is_currently_muted': bool(current),
                    'current_reason': current[0] if current else None,
                    'currently_muted_since': current[1] if current else None,
                    'last_mute_date': last_mute
                }

            conn.close()
            return None

        return await asyncio.to_thread(_search)

    async def save_roast(self, user_id: int, roast_text: str, category: str = "general", session_id: int = None) -> None:
        """
        Save a roast to history to avoid repetition.

        Args:
            user_id: Discord user ID
            roast_text: The roast that was delivered
            category: Type of roast (welcome, time_based, response, etc.)
            session_id: Current mute session ID from prisoner_history
        """
        def _save():
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO roast_history (user_id, roast_text, roast_category, mute_session_id) VALUES (?, ?, ?, ?)",
                (user_id, roast_text[:500], category, session_id)
            )

            # Update user profile
            conn.execute(
                """INSERT INTO user_profiles (user_id, total_roasts_received, last_roast_time)
                   VALUES (?, 1, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                   total_roasts_received = total_roasts_received + 1,
                   last_roast_time = CURRENT_TIMESTAMP"""
                , (user_id,)
            )
            conn.commit()
            conn.close()

        await asyncio.to_thread(_save)

    async def get_recent_roasts(self, user_id: int, limit: int = 5) -> List[str]:
        """
        Get recent roasts for a user to avoid repetition.

        Args:
            user_id: Discord user ID
            limit: Number of recent roasts to retrieve

        Returns:
            List of recent roast texts
        """
        def _get():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT roast_text FROM roast_history
                   WHERE user_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (user_id, limit)
            )
            roasts = [row[0] for row in cursor.fetchall()]
            conn.close()
            return roasts

        return await asyncio.to_thread(_get)

    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user profile with behavioral patterns.

        Args:
            user_id: Discord user ID

        Returns:
            User profile dict or None if not found
        """
        def _get():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT favorite_excuse, most_used_words, personality_type,
                          total_roasts_received, last_roast_time, callback_references
                   FROM user_profiles WHERE user_id = ?""",
                (user_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'favorite_excuse': row[0],
                    'most_used_words': row[1],
                    'personality_type': row[2],
                    'total_roasts_received': row[3],
                    'last_roast_time': row[4],
                    'callback_references': row[5]
                }
            return None

        return await asyncio.to_thread(_get)

    async def update_user_profile(self, user_id: int, message_content: str) -> None:
        """
        Update user profile based on their messages.

        Args:
            user_id: Discord user ID
            message_content: Their latest message to analyze
        """
        import re
        from collections import Counter

        def _update():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get existing profile
            cursor.execute("SELECT most_used_words, callback_references FROM user_profiles WHERE user_id = ?", (user_id,))
            existing = cursor.fetchone()

            # Extract words (excluding common ones)
            words = re.findall(r'\b\w+\b', message_content.lower())
            common_words = {'the', 'is', 'at', 'which', 'on', 'a', 'an', 'as', 'are', 'was', 'were', 'to', 'for', 'of', 'with', 'in'}
            meaningful_words = [w for w in words if w not in common_words and len(w) > 2]

            # Update most used words
            if existing and existing[0]:
                old_words = existing[0].split(',') if existing[0] else []
                all_words = old_words + meaningful_words
                word_counts = Counter(all_words)
                most_common = ','.join([w for w, _ in word_counts.most_common(10)])
            else:
                most_common = ','.join(meaningful_words[:10])

            # Detect personality type based on message patterns
            personality = "standard"
            if any(word in message_content.lower() for word in ['sorry', 'please', 'apologize', 'didnt mean']):
                personality = "apologetic"
            elif any(word in message_content.lower() for word in ['unfair', 'why me', 'not fair', 'bullshit']):
                personality = "victim_complex"
            elif any(word in message_content.lower() for word in ['fuck', 'shit', 'damn', 'hell']):
                personality = "aggressive"
            elif '?' in message_content:
                personality = "questioning"

            # Store memorable quotes for callbacks
            if len(message_content) > 20 and len(message_content) < 100:
                callbacks = existing[1] if existing and existing[1] else ""
                if callbacks:
                    callbacks = callbacks.split('|||')[-4:] # Keep last 4
                    callbacks.append(message_content)
                    callbacks = '|||'.join(callbacks)
                else:
                    callbacks = message_content

                conn.execute(
                    """INSERT INTO user_profiles (user_id, most_used_words, personality_type, callback_references)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET
                       most_used_words = ?,
                       personality_type = ?,
                       callback_references = ?""",
                    (user_id, most_common, personality, callbacks, most_common, personality, callbacks)
                )
            else:
                conn.execute(
                    """INSERT INTO user_profiles (user_id, most_used_words, personality_type)
                       VALUES (?, ?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET
                       most_used_words = ?,
                       personality_type = ?""",
                    (user_id, most_common, personality, most_common, personality)
                )

            conn.commit()
            conn.close()

        await asyncio.to_thread(_update)

    async def get_current_mute_session_id(self, user_id: int) -> Optional[int]:
        """
        Get the current active mute session ID for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Session ID or None if not muted
        """
        def _get():
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM prisoner_history WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None

        return await asyncio.to_thread(_get)