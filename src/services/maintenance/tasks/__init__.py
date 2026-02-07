"""
AzabBot - Maintenance Tasks Package
===================================

Individual maintenance task implementations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .gender_roles import GenderRoleTask
from .guild_protection import GuildProtectionTask
from .mute_overwrites import MuteOverwritesTask
from .mod_tracker_scan import ModTrackerScanTask
from .mod_inactivity import ModInactivityTask
from .log_retention import LogRetentionTask
from .prison_cleanup import PrisonCleanupTask
from .polls_cleanup import PollsCleanupTask
from .forbid_overwrites import ForbidOverwritesTask
from .prisoner_tracking import PrisonerTrackingTask
from .database_optimization import DatabaseOptimizationTask
from .stale_mute_cleanup import StaleMuteCleanupTask
from .history_cleanup import HistoryCleanupTask
from .invite_cache_refresh import InviteCacheRefreshTask
from .case_thread_validation import CaseThreadValidationTask
from .join_info_cleanup import JoinInfoCleanupTask
from .snapshot_cleanup import SnapshotCleanupTask
from .auth_cleanup import AuthCleanupTask
from .ban_sync import BanSyncTask
from .websocket_cleanup import WebSocketCleanupTask
from .resolved_case_cleanup import ResolvedCaseCleanupTask

__all__ = [
    "GenderRoleTask",
    "GuildProtectionTask",
    "MuteOverwritesTask",
    "ModTrackerScanTask",
    "ModInactivityTask",
    "LogRetentionTask",
    "PrisonCleanupTask",
    "PollsCleanupTask",
    "ForbidOverwritesTask",
    "PrisonerTrackingTask",
    "DatabaseOptimizationTask",
    "StaleMuteCleanupTask",
    "HistoryCleanupTask",
    "InviteCacheRefreshTask",
    "CaseThreadValidationTask",
    "JoinInfoCleanupTask",
    "SnapshotCleanupTask",
    "AuthCleanupTask",
    "BanSyncTask",
    "WebSocketCleanupTask",
    "ResolvedCaseCleanupTask",
]
