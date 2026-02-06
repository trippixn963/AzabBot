"""
AzabBot - Database Schema Module
================================

Table definitions and migrations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class SchemaMixin:
    """Mixin for database schema initialization."""

    def _init_tables(self: "DatabaseManager") -> None:
        """
        Initialize all database tables.

        DESIGN: Tables are created if not exist, allowing safe restarts.
        Indexes added for frequently queried columns.
        """
        conn = self._ensure_connection()
        cursor = conn.cursor()

        # -----------------------------------------------------------------
        # Bot State Table (replaces bot_state.json)
        # DESIGN: Key-value store for bot configuration
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Ignored Users Table (replaces ignored_users.json)
        # DESIGN: Users the bot will not respond to
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ignored_users (
                user_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Users Table
        # DESIGN: Tracks all users who have interacted with bot
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                messages_count INTEGER DEFAULT 0,
                is_imprisoned BOOLEAN DEFAULT 0
            )
        """)

        # -----------------------------------------------------------------
        # Messages Table
        # DESIGN: Logs messages for context and history
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                content TEXT,
                channel_id INTEGER,
                guild_id INTEGER,
                timestamp TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_guild_time ON messages(user_id, guild_id, timestamp DESC)"
        )

        # -----------------------------------------------------------------
        # Prisoner History Table
        # DESIGN: Complete history of all mutes/unmutes
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prisoner_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                mute_reason TEXT,
                trigger_message TEXT,
                muted_at TEXT,
                unmuted_at TEXT,
                duration_minutes INTEGER,
                muted_by TEXT,
                unmuted_by TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_prisoner_user ON prisoner_history(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_prisoner_active ON prisoner_history(is_active)"
        )

        # -----------------------------------------------------------------
        # Active Mutes Table
        # DESIGN: Tracks currently muted users for auto-unmute scheduler
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                muted_at REAL NOT NULL,
                expires_at REAL,
                unmuted INTEGER DEFAULT 0,
                UNIQUE(user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_expires ON active_mutes(expires_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_user ON active_mutes(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_mutes_search ON active_mutes(guild_id, unmuted, expires_at)"
        )

        # -----------------------------------------------------------------
        # Mute History Table
        # DESIGN: Complete log of all mute/unmute actions for modlog
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mute_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_user ON mute_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_time ON mute_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_user_time ON mute_history(user_id, guild_id, timestamp DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mute_history_moderator ON mute_history(moderator_id, action)"
        )

        # -----------------------------------------------------------------
        # Case Logs Table
        # DESIGN: Tracks unique case threads per user in mods forum
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_logs (
                user_id INTEGER PRIMARY KEY,
                case_id TEXT UNIQUE NOT NULL,
                thread_id INTEGER NOT NULL,
                mute_count INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                last_mute_at REAL,
                last_unmute_at REAL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_case_logs_case_id ON case_logs(case_id)"
        )

        # Migrations for case_logs
        for col in [
            "ban_count INTEGER DEFAULT 0",
            "last_ban_at REAL",
            "profile_message_id INTEGER",
            "last_mute_duration TEXT",
            "last_mute_moderator_id INTEGER",
            "last_ban_moderator_id INTEGER",
            "last_ban_reason TEXT",
            "warn_count INTEGER DEFAULT 0",
            "last_warn_at REAL",
        ]:
            try:
                cursor.execute(f"ALTER TABLE case_logs ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

        # -----------------------------------------------------------------
        # Cases Table (Per-Action Cases)
        # DESIGN: One case per moderation action (mute/ban/warn)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                evidence TEXT,
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolved_by INTEGER,
                resolved_reason TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status, action_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_thread ON cases(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_case_id ON cases(case_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_guild_status ON cases(guild_id, status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(created_at DESC)"
        )

        # Migrations for cases
        for col in [
            "control_panel_message_id INTEGER",
            "evidence_request_message_id INTEGER",
            "evidence_urls TEXT",
            "approved_at REAL",
            "approved_by INTEGER",
            "transcript TEXT",
        ]:
            try:
                cursor.execute(f"ALTER TABLE cases ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

        # -----------------------------------------------------------------
        # Mod Tracker Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_tracker (
                mod_id INTEGER PRIMARY KEY,
                thread_id INTEGER NOT NULL,
                display_name TEXT,
                avatar_hash TEXT,
                username TEXT,
                created_at REAL NOT NULL
            )
        """)
        for col in ["action_count INTEGER DEFAULT 0", "last_action_at REAL"]:
            try:
                cursor.execute(f"ALTER TABLE mod_tracker ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

        # -----------------------------------------------------------------
        # Mod Hourly Activity Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_hourly_activity (
                mod_id INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (mod_id, hour)
            )
        """)

        # -----------------------------------------------------------------
        # Nickname History Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nickname_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                old_nickname TEXT,
                new_nickname TEXT,
                changed_by INTEGER,
                changed_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_user ON nickname_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_time ON nickname_history(changed_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_nickname_user_guild_time ON nickname_history(user_id, guild_id, changed_at DESC)"
        )

        # -----------------------------------------------------------------
        # Member Activity Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS member_activity (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                join_count INTEGER DEFAULT 0,
                leave_count INTEGER DEFAULT 0,
                first_joined_at REAL,
                last_joined_at REAL,
                last_left_at REAL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        try:
            cursor.execute("ALTER TABLE member_activity ADD COLUMN join_message_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # -----------------------------------------------------------------
        # Pending Reasons Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_reasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                warning_message_id INTEGER NOT NULL,
                embed_message_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                owner_notified INTEGER DEFAULT 0
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_reasons_thread ON pending_reasons(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_reasons_created ON pending_reasons(created_at)"
        )

        # -----------------------------------------------------------------
        # User Join Info Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_join_info (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                invite_code TEXT,
                inviter_id INTEGER,
                joined_at REAL NOT NULL,
                avatar_hash TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_join_inviter ON user_join_info(inviter_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_join_avatar ON user_join_info(avatar_hash)"
        )

        # -----------------------------------------------------------------
        # Mod Notes Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mod_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_notes_user ON mod_notes(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mod_notes_time ON mod_notes(created_at)"
        )
        try:
            cursor.execute("ALTER TABLE mod_notes ADD COLUMN case_id TEXT")
        except sqlite3.OperationalError:
            pass

        # -----------------------------------------------------------------
        # Ban History Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ban_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_user ON ban_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_time ON ban_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_user_time ON ban_history(user_id, guild_id, timestamp DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ban_history_moderator ON ban_history(moderator_id, action)"
        )

        # -----------------------------------------------------------------
        # Username History Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS username_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT,
                guild_id INTEGER,
                changed_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_username_history_user ON username_history(user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_username_history_time ON username_history(changed_at)"
        )

        # -----------------------------------------------------------------
        # Warnings Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                evidence TEXT,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_time ON warnings(created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_user_time ON warnings(user_id, guild_id, created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_warnings_moderator ON warnings(moderator_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # Voice Activity Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voice_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_activity_user ON voice_activity(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_voice_activity_time ON voice_activity(timestamp)"
        )

        # -----------------------------------------------------------------
        # Lockdown State Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_state (
                guild_id INTEGER PRIMARY KEY,
                locked_at REAL NOT NULL,
                locked_by INTEGER NOT NULL,
                reason TEXT,
                channel_count INTEGER DEFAULT 0
            )
        """)

        # -----------------------------------------------------------------
        # Lockdown Permissions Table (Legacy)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_type TEXT NOT NULL,
                original_send_messages INTEGER,
                original_connect INTEGER,
                UNIQUE(guild_id, channel_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_lockdown_perms_guild ON lockdown_permissions(guild_id)"
        )

        # -----------------------------------------------------------------
        # Lockdown Role Permissions Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lockdown_role_permissions (
                guild_id INTEGER PRIMARY KEY,
                send_messages INTEGER,
                connect INTEGER,
                add_reactions INTEGER,
                create_public_threads INTEGER,
                create_private_threads INTEGER,
                send_messages_in_threads INTEGER
            )
        """)

        # -----------------------------------------------------------------
        # Spam Violations Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spam_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                violation_count INTEGER DEFAULT 1,
                last_violation_at REAL NOT NULL,
                last_spam_type TEXT,
                UNIQUE(user_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_spam_violations_user ON spam_violations(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # Snipe Cache Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snipe_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                author_display TEXT NOT NULL,
                author_avatar TEXT,
                content TEXT,
                attachment_names TEXT,
                attachment_urls TEXT,
                attachment_data TEXT,
                sticker_urls TEXT,
                deleted_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_snipe_channel ON snipe_cache(channel_id, deleted_at DESC)"
        )
        for column, col_type in [
            ("attachment_urls", "TEXT"),
            ("sticker_urls", "TEXT"),
            ("message_id", "INTEGER"),
            ("attachment_data", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE snipe_cache ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # -----------------------------------------------------------------
        # Forbid History Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forbid_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                restriction_type TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                created_at REAL NOT NULL,
                expires_at REAL,
                removed_at REAL,
                removed_by INTEGER,
                case_id TEXT,
                UNIQUE(user_id, guild_id, restriction_type)
            )
        """)
        for col in ["expires_at REAL", "case_id TEXT"]:
            try:
                cursor.execute(f"ALTER TABLE forbid_history ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # Column already exists
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_forbid_user ON forbid_history(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # Appeals Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appeal_id TEXT UNIQUE NOT NULL,
                case_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolved_by INTEGER,
                resolution TEXT,
                resolution_reason TEXT,
                email TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_case ON appeals(case_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_user ON appeals(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status)"
        )

        # Migration: Add email column if missing
        try:
            cursor.execute("SELECT email FROM appeals LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE appeals ADD COLUMN email TEXT")

        # Migration: Add attachments column if missing (JSON string of attachment metadata)
        try:
            cursor.execute("SELECT attachments FROM appeals LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE appeals ADD COLUMN attachments TEXT")

        # -----------------------------------------------------------------
        # Linked Messages Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS linked_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                linked_by INTEGER NOT NULL,
                linked_at REAL NOT NULL,
                UNIQUE(message_id, channel_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_linked_messages_member ON linked_messages(member_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # Tickets Table
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                priority TEXT DEFAULT 'normal',
                claimed_by INTEGER,
                assigned_to INTEGER,
                created_at REAL NOT NULL,
                last_activity_at REAL,
                warned_at REAL,
                closed_at REAL,
                closed_by INTEGER,
                close_reason TEXT
            )
        """)
        for col in [
            "last_activity_at REAL",
            "warned_at REAL",
            "claimed_at REAL",
            "transcript_html TEXT",
            "control_panel_message_id INTEGER",
            "transcript TEXT",
            "case_id TEXT",  # For appeal tickets - links to the case being appealed
        ]:
            try:
                cursor.execute(f"ALTER TABLE tickets ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_claimed ON tickets(claimed_by)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_thread ON tickets(thread_id)"
        )

        # -----------------------------------------------------------------
        # Ticket Messages Table (incremental storage for real-time transcripts)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                message_id INTEGER NOT NULL UNIQUE,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                author_display_name TEXT NOT NULL,
                author_avatar_url TEXT,
                content TEXT,
                timestamp REAL NOT NULL,
                is_bot INTEGER DEFAULT 0,
                is_staff INTEGER DEFAULT 0,
                attachments TEXT,
                embeds TEXT,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            )
        """)
        # Add embeds column if missing (migration)
        try:
            cursor.execute("ALTER TABLE ticket_messages ADD COLUMN embeds TEXT")
        except sqlite3.OperationalError:
            pass
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticket_messages_timestamp ON ticket_messages(ticket_id, timestamp)"
        )

        # -----------------------------------------------------------------
        # AI Conversations Table (for ticket AI assistant persistence)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                ticket_id TEXT PRIMARY KEY,
                conversation_data TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        # -----------------------------------------------------------------
        # Message Samples Table (for alt detection writing style)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                avg_word_length REAL NOT NULL,
                emoji_count INTEGER DEFAULT 0,
                caps_ratio REAL DEFAULT 0,
                recorded_at REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_msg_samples_user ON message_samples(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # User Activity Hours Table (for alt detection time patterns)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_activity_hours (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_updated REAL NOT NULL,
                PRIMARY KEY (user_id, guild_id, hour)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_hours_user ON user_activity_hours(user_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # User Interactions Table (for alt detection mutual avoidance)
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_interactions (
                user_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                interaction_count INTEGER DEFAULT 0,
                last_interaction REAL NOT NULL,
                PRIMARY KEY (user_id, target_id, guild_id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_interactions_user ON user_interactions(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_interactions_target ON user_interactions(target_id, guild_id)"
        )

        # -----------------------------------------------------------------
        # Timeout History Table
        # DESIGN: Tracks Discord timeouts applied/removed
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS timeout_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                until_timestamp REAL,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeout_history_user ON timeout_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeout_history_time ON timeout_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeout_history_moderator ON timeout_history(moderator_id)"
        )

        # -----------------------------------------------------------------
        # Kick History Table
        # DESIGN: Tracks kicks performed
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kick_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kick_history_user ON kick_history(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kick_history_time ON kick_history(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kick_history_moderator ON kick_history(moderator_id)"
        )

        # -----------------------------------------------------------------
        # Moderation Audit Log Table (Permanent - Never Decays)
        # DESIGN: Complete audit trail of all moderation actions
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderation_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_source TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                details TEXT,
                case_id TEXT,
                timestamp REAL NOT NULL
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_user ON moderation_audit_log(user_id, guild_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_time ON moderation_audit_log(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON moderation_audit_log(action_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_moderator ON moderation_audit_log(moderator_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_source ON moderation_audit_log(action_source)"
        )

        # -----------------------------------------------------------------
        # Mod Dashboard Users Table
        # DESIGN: Stores credentials for web moderation dashboard
        # -----------------------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_users (
                discord_id INTEGER PRIMARY KEY,
                pin_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_login REAL,
                last_login_ip TEXT,
                last_login_agent TEXT,
                permissions TEXT DEFAULT ''
            )
        """)

        conn.commit()
