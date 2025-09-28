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
        Initialize database tables.
        
        Creates the users and messages tables if they don't exist.
        Sets up proper indexes and constraints for optimal performance.
        """
        conn: sqlite3.Connection = sqlite3.connect(self.db_path)
        
        # Users table: Store user information and statistics
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            messages_count INTEGER DEFAULT 0,
            is_imprisoned BOOLEAN DEFAULT 0
        )''')
        
        # Messages table: Store individual message logs
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            channel_id INTEGER,
            guild_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Prisoner history table: Track all mute events
        conn.execute('''CREATE TABLE IF NOT EXISTS prisoner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            mute_reason TEXT,
            muted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            unmuted_at TIMESTAMP,
            duration_minutes INTEGER,
            muted_by TEXT,
            unmuted_by TEXT,
            is_active BOOLEAN DEFAULT 1
        )''')
        
        # Create indexes for faster queries
        conn.execute('CREATE INDEX IF NOT EXISTS idx_prisoner_user ON prisoner_history(user_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_prisoner_active ON prisoner_history(is_active)')
        
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
        def _log() -> None:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # Update or insert user information
            conn.execute('INSERT OR REPLACE INTO users (user_id, username) VALUES (?, ?)',
                        (user_id, username))
            
            # Insert message log with EST timestamp
            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            est_timestamp: str = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute('INSERT INTO messages (user_id, content, channel_id, guild_id, timestamp) VALUES (?, ?, ?, ?, ?)',
                        (user_id, content[:int(os.getenv('MESSAGE_CONTENT_MAX_LENGTH', '500'))], channel_id, guild_id, est_timestamp))
            
            # Increment user's message count
            conn.execute('UPDATE users SET messages_count = messages_count + 1 WHERE user_id = ?',
                        (user_id,))
            
            conn.commit()
            conn.close()
        
        # Run database operations in thread pool to avoid blocking
        await asyncio.to_thread(_log)
    
    async def record_mute(self, user_id: int, username: str, reason: str, muted_by: Optional[str] = None) -> None:
        """
        Record a new mute event in prisoner history.
        
        Args:
            user_id: Discord user ID
            username: Discord username
            reason: Reason for mute
            muted_by: Who issued the mute (moderator name)
        """
        def _record() -> None:
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # First, mark any existing active mutes as inactive (in case of re-mute)
            conn.execute('UPDATE prisoner_history SET is_active = 0 WHERE user_id = ? AND is_active = 1',
                        (user_id,))
            
            # Insert new mute record
            conn.execute('''INSERT INTO prisoner_history 
                           (user_id, username, mute_reason, muted_by, is_active) 
                           VALUES (?, ?, ?, ?, 1)''',
                        (user_id, username, reason, muted_by))
            
            # Update user's imprisoned status
            conn.execute('UPDATE users SET is_imprisoned = 1 WHERE user_id = ?', (user_id,))
            
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
            conn: sqlite3.Connection = sqlite3.connect(self.db_path)
            
            # Get EST timezone for timestamp
            est: timezone = timezone(timedelta(hours=int(os.getenv('TIMEZONE_OFFSET_HOURS', '-5'))))
            current_time: str = datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')
            
            # Update the active mute record
            conn.execute('''UPDATE prisoner_history
                           SET unmuted_at = ?,
                               unmuted_by = ?,
                               is_active = 0,
                               duration_minutes = ABS(ROUND((JULIANDAY(?) - JULIANDAY(muted_at)) * 24 * 60))
                           WHERE user_id = ? AND is_active = 1''',
                        (current_time, unmuted_by, current_time, user_id))
            
            # Update user's imprisoned status
            conn.execute('UPDATE users SET is_imprisoned = 0 WHERE user_id = ?', (user_id,))
            
            conn.commit()
            conn.close()
        
        await asyncio.to_thread(_record)
    
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