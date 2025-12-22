"""
Azab Discord Bot - Database Tests
==================================

Tests for the database layer to ensure data integrity.
"""

import time
import pytest


class TestBotState:
    """Tests for bot state operations."""

    def test_set_and_get_bot_state_string(self, test_db):
        """Test setting and getting a string value."""
        test_db.set_bot_state("test_key", "test_value")
        result = test_db.get_bot_state("test_key")
        assert result == "test_value"

    def test_set_and_get_bot_state_bool(self, test_db):
        """Test setting and getting a boolean value."""
        test_db.set_bot_state("is_enabled", True)
        result = test_db.get_bot_state("is_enabled")
        assert result is True

        test_db.set_bot_state("is_enabled", False)
        result = test_db.get_bot_state("is_enabled")
        assert result is False

    def test_set_and_get_bot_state_dict(self, test_db):
        """Test setting and getting a dict value."""
        data = {"key1": "value1", "key2": 123}
        test_db.set_bot_state("config", data)
        result = test_db.get_bot_state("config")
        assert result == data

    def test_get_bot_state_default(self, test_db):
        """Test getting a non-existent key returns default."""
        result = test_db.get_bot_state("nonexistent", "default_value")
        assert result == "default_value"

    def test_is_active_default(self, test_db):
        """Test is_active returns True by default."""
        assert test_db.is_active() is True

    def test_set_active(self, test_db):
        """Test setting active state."""
        test_db.set_active(False)
        assert test_db.is_active() is False

        test_db.set_active(True)
        assert test_db.is_active() is True


class TestIgnoredUsers:
    """Tests for ignored users operations."""

    def test_add_ignored_user(self, test_db):
        """Test adding a user to ignore list."""
        test_db.add_ignored_user(123456789)
        assert test_db.is_user_ignored(123456789) is True

    def test_remove_ignored_user(self, test_db):
        """Test removing a user from ignore list."""
        test_db.add_ignored_user(123456789)
        test_db.remove_ignored_user(123456789)
        assert test_db.is_user_ignored(123456789) is False

    def test_get_ignored_users(self, test_db):
        """Test getting all ignored users."""
        test_db.add_ignored_user(111)
        test_db.add_ignored_user(222)
        test_db.add_ignored_user(333)

        users = test_db.get_ignored_users()
        assert users == {111, 222, 333}

    def test_is_user_ignored_not_ignored(self, test_db):
        """Test checking a non-ignored user."""
        assert test_db.is_user_ignored(999999) is False

    def test_add_ignored_user_duplicate(self, test_db):
        """Test adding same user twice doesn't error."""
        test_db.add_ignored_user(123)
        test_db.add_ignored_user(123)  # Should not raise
        assert test_db.is_user_ignored(123) is True


class TestMuteOperations:
    """Tests for mute tracking operations."""

    def test_add_mute(self, test_db):
        """Test adding a mute."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        row_id = test_db.add_mute(
            user_id=user_id,
            guild_id=guild_id,
            moderator_id=mod_id,
            reason="Test mute",
            duration_seconds=3600,
        )

        assert row_id > 0
        assert test_db.is_user_muted(user_id, guild_id) is True

    def test_remove_mute(self, test_db):
        """Test removing a mute."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        test_db.add_mute(user_id, guild_id, mod_id, "Test", 3600)
        result = test_db.remove_mute(user_id, guild_id, mod_id, "Unmute reason")

        assert result is True
        assert test_db.is_user_muted(user_id, guild_id) is False

    def test_remove_mute_not_muted(self, test_db):
        """Test removing a mute for user not muted returns False."""
        result = test_db.remove_mute(999999, 987654321, 111222333)
        assert result is False

    def test_get_active_mute(self, test_db):
        """Test getting active mute details."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        test_db.add_mute(user_id, guild_id, mod_id, "Test reason", 3600)
        mute = test_db.get_active_mute(user_id, guild_id)

        assert mute is not None
        assert mute["user_id"] == user_id
        assert mute["moderator_id"] == mod_id
        assert mute["reason"] == "Test reason"

    def test_get_expired_mutes(self, test_db):
        """Test getting expired mutes."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        # Add mute with 0 duration (already expired)
        test_db.add_mute(user_id, guild_id, mod_id, "Expired", 0)

        # Manually set expires_at to past
        test_db.execute(
            "UPDATE active_mutes SET expires_at = ? WHERE user_id = ?",
            (time.time() - 100, user_id)
        )

        expired = test_db.get_expired_mutes()
        assert len(expired) >= 1
        assert any(m["user_id"] == user_id for m in expired)

    def test_permanent_mute_not_in_expired(self, test_db):
        """Test permanent mutes don't appear in expired."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        # Add permanent mute (no duration)
        test_db.add_mute(user_id, guild_id, mod_id, "Permanent", None)

        expired = test_db.get_expired_mutes()
        assert not any(m["user_id"] == user_id for m in expired)

    def test_get_user_mute_count(self, test_db):
        """Test counting user mutes."""
        user_id = 123456789
        guild_id = 987654321
        mod_id = 111222333

        # Add 3 mutes
        for i in range(3):
            test_db.add_mute(user_id, guild_id, mod_id, f"Mute {i}", 3600)
            test_db.remove_mute(user_id, guild_id, mod_id)

        count = test_db.get_user_mute_count(user_id, guild_id)
        assert count == 3

    def test_get_mute_moderator_ids(self, test_db):
        """Test getting all moderators who muted a user."""
        user_id = 123456789
        guild_id = 987654321

        # Different mods mute the user
        test_db.add_mute(user_id, guild_id, 111, "Mute 1", 3600)
        test_db.remove_mute(user_id, guild_id, 111)
        test_db.add_mute(user_id, guild_id, 222, "Mute 2", 3600)
        test_db.remove_mute(user_id, guild_id, 222)
        test_db.add_mute(user_id, guild_id, 111, "Mute 3", 3600)  # Same mod again

        mod_ids = test_db.get_mute_moderator_ids(user_id, guild_id)
        assert set(mod_ids) == {111, 222}


class TestCaseLogOperations:
    """Tests for case log operations."""

    def test_get_next_case_id_format(self, test_db):
        """Test case ID format is 4 alphanumeric chars."""
        case_id = test_db.get_next_case_id()
        assert len(case_id) == 4
        assert case_id.isalnum()
        assert case_id.isupper() or case_id.replace("0123456789", "").isupper()

    def test_get_next_case_id_unique(self, test_db):
        """Test case IDs are unique."""
        ids = set()
        for _ in range(100):
            case_id = test_db.get_next_case_id()
            assert case_id not in ids
            ids.add(case_id)
            # Create the case so ID is taken
            test_db.create_case_log(len(ids), case_id, len(ids) * 1000)

    def test_create_case_log(self, test_db):
        """Test creating a case log."""
        user_id = 123456789
        case_id = "ABCD"
        thread_id = 555666777

        test_db.create_case_log(user_id, case_id, thread_id)
        case = test_db.get_case_log(user_id)

        assert case is not None
        assert case["case_id"] == case_id
        assert case["thread_id"] == thread_id
        assert case["mute_count"] == 1

    def test_get_case_log_not_exists(self, test_db):
        """Test getting case for user with no case."""
        case = test_db.get_case_log(999999)
        assert case is None

    def test_increment_mute_count(self, test_db):
        """Test incrementing mute count."""
        user_id = 123456789
        test_db.create_case_log(user_id, "ABCD", 555666777)

        new_count = test_db.increment_mute_count(user_id)
        assert new_count == 2

        new_count = test_db.increment_mute_count(user_id)
        assert new_count == 3

    def test_update_last_unmute(self, test_db):
        """Test updating last unmute timestamp."""
        user_id = 123456789
        test_db.create_case_log(user_id, "ABCD", 555666777)

        before = test_db.get_case_log(user_id)
        assert before["last_unmute_at"] is None

        test_db.update_last_unmute(user_id)

        after = test_db.get_case_log(user_id)
        assert after["last_unmute_at"] is not None

    def test_increment_ban_count(self, test_db):
        """Test incrementing ban count."""
        user_id = 123456789
        test_db.create_case_log(user_id, "ABCD", 555666777)

        new_count = test_db.increment_ban_count(user_id)
        assert new_count == 1

        new_count = test_db.increment_ban_count(user_id)
        assert new_count == 2

    def test_set_profile_message_id(self, test_db):
        """Test setting profile message ID."""
        user_id = 123456789
        test_db.create_case_log(user_id, "ABCD", 555666777)

        test_db.set_profile_message_id(user_id, 888999000)

        case = test_db.get_case_log(user_id)
        assert case["profile_message_id"] == 888999000


class TestPendingReasons:
    """Tests for pending reason operations."""

    def test_create_pending_reason(self, test_db):
        """Test creating a pending reason."""
        result = test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111222333,
            embed_message_id=444555666,
            moderator_id=123456789,
            target_user_id=987654321,
            action_type="mute",
        )
        # Returns cursor, check pending reason exists
        pending = test_db.get_pending_reason_by_thread(555666777, 123456789)
        assert pending is not None
        assert pending["action_type"] == "mute"

    def test_get_pending_reason_by_thread(self, test_db):
        """Test getting pending reason by thread and moderator."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="ban",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123)
        assert pending is not None
        assert pending["warning_message_id"] == 111
        assert pending["embed_message_id"] == 222

    def test_get_pending_reason_wrong_moderator(self, test_db):
        """Test getting pending reason with wrong moderator returns None."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 999)
        assert pending is None

    def test_get_expired_pending_reasons(self, test_db):
        """Test getting expired pending reasons."""
        # Create a pending reason
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="mute",
        )

        # Manually backdate it
        test_db.execute(
            "UPDATE pending_reasons SET created_at = ? WHERE thread_id = ?",
            (time.time() - 7200, 555666777)  # 2 hours ago
        )

        expired = test_db.get_expired_pending_reasons(max_age_seconds=3600)
        assert len(expired) == 1
        assert expired[0]["thread_id"] == 555666777

    def test_mark_pending_reason_notified(self, test_db):
        """Test marking pending reason as notified."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123)
        test_db.mark_pending_reason_notified(pending["id"])

        # Should not return notified pending reasons
        pending_after = test_db.get_pending_reason_by_thread(555666777, 123)
        assert pending_after is None

    def test_delete_pending_reason(self, test_db):
        """Test deleting a pending reason."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123)
        test_db.delete_pending_reason(pending["id"])

        pending_after = test_db.get_pending_reason_by_thread(555666777, 123)
        assert pending_after is None

    def test_cleanup_old_pending_reasons(self, test_db):
        """Test cleaning up old notified pending reasons."""
        # Create and notify a pending reason
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111,
            embed_message_id=222,
            moderator_id=123,
            target_user_id=456,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123)
        test_db.mark_pending_reason_notified(pending["id"])

        # Backdate it
        test_db.execute(
            "UPDATE pending_reasons SET created_at = ? WHERE id = ?",
            (time.time() - 100000, pending["id"])  # Very old
        )

        # Cleanup should delete it
        test_db.cleanup_old_pending_reasons(max_age_seconds=86400)

        # Verify it's gone by checking count
        rows = test_db.fetchall("SELECT * FROM pending_reasons WHERE id = ?", (pending["id"],))
        assert len(rows) == 0


class TestMemberActivity:
    """Tests for member activity tracking."""

    def test_record_member_join(self, test_db):
        """Test recording member join."""
        user_id = 123456789
        guild_id = 987654321

        count = test_db.record_member_join(user_id, guild_id)
        assert count == 1

        count = test_db.record_member_join(user_id, guild_id)
        assert count == 2

    def test_record_member_leave(self, test_db):
        """Test recording member leave."""
        user_id = 123456789
        guild_id = 987654321

        count = test_db.record_member_leave(user_id, guild_id)
        assert count == 1

        count = test_db.record_member_leave(user_id, guild_id)
        assert count == 2

    def test_get_member_activity(self, test_db):
        """Test getting member activity."""
        user_id = 123456789
        guild_id = 987654321

        # Join twice, leave once
        test_db.record_member_join(user_id, guild_id)
        test_db.record_member_join(user_id, guild_id)
        test_db.record_member_leave(user_id, guild_id)

        activity = test_db.get_member_activity(user_id, guild_id)
        assert activity is not None
        assert activity["join_count"] == 2
        assert activity["leave_count"] == 1

    def test_get_member_activity_not_exists(self, test_db):
        """Test getting activity for unknown member."""
        activity = test_db.get_member_activity(999999, 987654321)
        assert activity is None


class TestNicknameHistory:
    """Tests for nickname history tracking."""

    def test_save_nickname_change(self, test_db):
        """Test saving nickname change."""
        user_id = 123456789
        guild_id = 987654321

        test_db.save_nickname_change(
            user_id=user_id,
            guild_id=guild_id,
            old_nickname=None,
            new_nickname="NewNick",
            changed_by=111222333,
        )

        history = test_db.get_nickname_history(user_id, guild_id)
        assert len(history) == 1
        assert history[0]["new_nickname"] == "NewNick"

    def test_get_nickname_history_order(self, test_db):
        """Test nickname history is ordered newest first."""
        user_id = 123456789
        guild_id = 987654321

        test_db.save_nickname_change(user_id, guild_id, None, "First")
        test_db.save_nickname_change(user_id, guild_id, "First", "Second")
        test_db.save_nickname_change(user_id, guild_id, "Second", "Third")

        history = test_db.get_nickname_history(user_id, guild_id)
        assert len(history) == 3
        assert history[0]["new_nickname"] == "Third"
        assert history[2]["new_nickname"] == "First"

    def test_get_all_nicknames(self, test_db):
        """Test getting all unique nicknames."""
        user_id = 123456789
        guild_id = 987654321

        test_db.save_nickname_change(user_id, guild_id, None, "Nick1")
        test_db.save_nickname_change(user_id, guild_id, "Nick1", "Nick2")
        test_db.save_nickname_change(user_id, guild_id, "Nick2", "Nick1")  # Back to Nick1

        nicknames = test_db.get_all_nicknames(user_id, guild_id)
        assert "Nick1" in nicknames
        assert "Nick2" in nicknames


class TestModTracker:
    """Tests for mod tracker operations."""

    def test_add_tracked_mod(self, test_db):
        """Test adding a tracked mod."""
        mod_id = 111222333
        thread_id = 555666777

        test_db.add_tracked_mod(
            mod_id=mod_id,
            thread_id=thread_id,
            display_name="Mod Name",
            username="moduser",
            avatar_hash="abc123",
        )

        mod = test_db.get_tracked_mod(mod_id)
        assert mod is not None
        assert mod["thread_id"] == thread_id
        assert mod["display_name"] == "Mod Name"

    def test_remove_tracked_mod(self, test_db):
        """Test removing a tracked mod."""
        mod_id = 111222333
        test_db.add_tracked_mod(mod_id, 555666777, "Mod", "mod", None)

        result = test_db.remove_tracked_mod(mod_id)
        assert result is True

        mod = test_db.get_tracked_mod(mod_id)
        assert mod is None

    def test_remove_tracked_mod_not_exists(self, test_db):
        """Test removing non-existent mod returns False."""
        result = test_db.remove_tracked_mod(999999)
        assert result is False

    def test_get_all_tracked_mods(self, test_db):
        """Test getting all tracked mods."""
        test_db.add_tracked_mod(111, 1001, "Mod1", "mod1", None)
        test_db.add_tracked_mod(222, 1002, "Mod2", "mod2", None)
        test_db.add_tracked_mod(333, 1003, "Mod3", "mod3", None)

        mods = test_db.get_all_tracked_mods()
        assert len(mods) == 3

    def test_update_mod_info(self, test_db):
        """Test updating mod info."""
        mod_id = 111222333
        test_db.add_tracked_mod(mod_id, 555666777, "Old Name", "olduser", "oldhash")

        test_db.update_mod_info(
            mod_id=mod_id,
            display_name="New Name",
            avatar_hash="newhash",
        )

        mod = test_db.get_tracked_mod(mod_id)
        assert mod["display_name"] == "New Name"
        assert mod["avatar_hash"] == "newhash"
        assert mod["username"] == "olduser"  # Unchanged
