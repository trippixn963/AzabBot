"""
Azab Discord Bot - Alt Detection Service
=========================================

Detects potential alt accounts when a user is banned.

DESIGN:
    Analyzes multiple signals to identify accounts that may belong
    to the same person as a banned user. Confidence scoring based
    on signal strength and combination.

Signals:
    - Account age (new accounts more suspicious)
    - Username similarity (SequenceMatcher ratio)
    - Join timing (joined near banned user)
    - Same inviter (invited by same person)
    - Avatar hash match (same profile picture)
    - Nickname history overlap
    - Join count patterns (rejoiners)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Optional, List, Dict, Tuple

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.retry import safe_send, safe_fetch_channel

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Signal Weights
# =============================================================================

class SignalWeights:
    """Point values for each detection signal."""

    # Account age signals
    ACCOUNT_AGE_UNDER_7_DAYS = 30
    ACCOUNT_AGE_UNDER_30_DAYS = 15
    ACCOUNT_AGE_UNDER_90_DAYS = 5

    # Username similarity (0-100% match scaled)
    USERNAME_EXACT_MATCH = 50
    USERNAME_HIGH_SIMILARITY = 35  # > 80% similar
    USERNAME_MEDIUM_SIMILARITY = 20  # > 60% similar

    # Join timing
    JOINED_WITHIN_1_HOUR = 40
    JOINED_WITHIN_6_HOURS = 25
    JOINED_WITHIN_24_HOURS = 15
    JOINED_WITHIN_7_DAYS = 5

    # Same inviter
    SAME_INVITER = 35

    # Avatar match
    SAME_AVATAR = 45

    # Nickname overlap
    NICKNAME_OVERLAP = 25

    # High join count (rejoiner behavior)
    JOIN_COUNT_3_PLUS = 20
    JOIN_COUNT_5_PLUS = 35

    # Account creation proximity
    CREATED_WITHIN_1_HOUR = 45
    CREATED_WITHIN_24_HOURS = 30
    CREATED_WITHIN_7_DAYS = 15

    # Bio/status match
    SAME_BIO = 40
    SIMILAR_BIO = 20  # > 70% similar

    # Punishment history
    BOTH_PREVIOUSLY_PUNISHED = 25
    BOTH_PUNISHED_SAME_DAY = 40


# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    'HIGH': 80,    # 80+ points
    'MEDIUM': 50,  # 50-79 points
    'LOW': 30,     # 30-49 points
}


# =============================================================================
# Alt Detection Service
# =============================================================================

class AltDetectionService:
    """
    Service for detecting potential alt accounts.

    DESIGN:
        Triggered after a ban, analyzes server members against
        the banned user using multiple signals. Results posted
        to case log thread as alerts.
    """

    # Maximum members to analyze per ban (performance limit)
    MAX_MEMBERS_TO_SCAN = 1000

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

    @property
    def enabled(self) -> bool:
        """Check if alt detection is enabled (requires case log)."""
        return self.config.case_log_forum_id is not None

    # =========================================================================
    # Main Detection Entry Point
    # =========================================================================

    async def detect_alts_for_ban(
        self,
        banned_user: discord.Member,
        guild: discord.Guild,
        case_thread_id: int,
    ) -> List[Dict]:
        """
        Analyze server for potential alts of a banned user.

        Args:
            banned_user: The user who was banned.
            guild: The guild where the ban occurred.
            case_thread_id: Thread ID to post alerts to.

        Returns:
            List of detected potential alts with confidence scores.
        """
        if not self.enabled:
            return []

        try:
            # Get banned user's data for comparison
            banned_data = await self._gather_user_data(banned_user, guild)

            # Scan guild members
            potential_alts = []
            member_count = 0

            for member in guild.members:
                if member.id == banned_user.id:
                    continue
                if member.bot:
                    continue
                if member_count >= self.MAX_MEMBERS_TO_SCAN:
                    break

                member_count += 1

                # Analyze this member against banned user
                result = await self._analyze_potential_alt(
                    banned_data=banned_data,
                    candidate=member,
                    guild=guild,
                )

                if result and result['total_score'] >= CONFIDENCE_THRESHOLDS['LOW']:
                    potential_alts.append(result)

            # Sort by score (highest first)
            potential_alts.sort(key=lambda x: x['total_score'], reverse=True)

            # Save to database and post alerts
            if potential_alts:
                await self._save_and_alert(
                    banned_user=banned_user,
                    guild=guild,
                    case_thread_id=case_thread_id,
                    potential_alts=potential_alts,
                )

            logger.tree("Alt Detection Complete", [
                ("Banned User", f"{banned_user} ({banned_user.id})"),
                ("Members Scanned", str(member_count)),
                ("Potential Alts Found", str(len(potential_alts))),
            ], emoji="🔍")

            return potential_alts

        except Exception as e:
            logger.error("Alt Detection Failed", [
                ("Banned User", str(banned_user.id)),
                ("Error", str(e)[:100]),
            ])
            return []

    # =========================================================================
    # Data Gathering
    # =========================================================================

    async def _gather_user_data(
        self,
        user: discord.Member,
        guild: discord.Guild,
    ) -> Dict:
        """Gather all available data about a user for comparison."""
        # Get join info from database
        join_info = self.db.get_user_join_info(user.id, guild.id)

        # Get member activity
        activity = self.db.get_member_activity(user.id, guild.id)

        # Get nickname history
        nicknames = self.db.get_all_nicknames(user.id, guild.id)

        # Get avatar hash
        avatar_hash = None
        if user.avatar:
            avatar_hash = user.avatar.key

        # Get bio/custom status
        bio = None
        for act in user.activities:
            if hasattr(act, 'state') and act.state:
                bio = act.state.lower()
                break

        # Get punishment history
        punishment_dates = []
        mute_history = self.db.get_user_mute_history(user.id, guild.id)
        if mute_history:
            for mute in mute_history:
                if mute['timestamp']:
                    punishment_dates.append(mute['timestamp'])

        return {
            'user_id': user.id,
            'username': user.name.lower(),
            'display_name': user.display_name.lower(),
            'created_at': user.created_at,
            'joined_at': user.joined_at,
            'avatar_hash': avatar_hash,
            'invite_code': join_info.get('invite_code') if join_info else None,
            'inviter_id': join_info.get('inviter_id') if join_info else None,
            'join_count': activity.get('join_count', 1) if activity else 1,
            'nicknames': set(n.lower() for n in nicknames) if nicknames else set(),
            'bio': bio,
            'punishment_dates': punishment_dates,
        }

    # =========================================================================
    # Analysis Functions
    # =========================================================================

    async def _analyze_potential_alt(
        self,
        banned_data: Dict,
        candidate: discord.Member,
        guild: discord.Guild,
    ) -> Optional[Dict]:
        """
        Analyze a candidate member for alt signals.

        Returns dict with signals and score, or None if no signals match.
        """
        candidate_data = await self._gather_user_data(candidate, guild)

        signals = {}
        total_score = 0

        # Signal 1: Account Age
        age_score, age_signal = self._check_account_age(candidate)
        if age_score > 0:
            signals['account_age'] = age_signal
            total_score += age_score

        # Signal 2: Username Similarity
        name_score, name_signal = self._check_username_similarity(
            banned_data, candidate_data
        )
        if name_score > 0:
            signals['username_similarity'] = name_signal
            total_score += name_score

        # Signal 3: Join Timing
        timing_score, timing_signal = self._check_join_timing(
            banned_data, candidate_data
        )
        if timing_score > 0:
            signals['join_timing'] = timing_signal
            total_score += timing_score

        # Signal 4: Same Inviter
        if banned_data.get('inviter_id') and candidate_data.get('inviter_id'):
            if banned_data['inviter_id'] == candidate_data['inviter_id']:
                signals['same_inviter'] = f"Both invited by <@{banned_data['inviter_id']}>"
                total_score += SignalWeights.SAME_INVITER

        # Signal 5: Avatar Match
        if banned_data.get('avatar_hash') and candidate_data.get('avatar_hash'):
            if banned_data['avatar_hash'] == candidate_data['avatar_hash']:
                signals['same_avatar'] = "Identical profile picture"
                total_score += SignalWeights.SAME_AVATAR

        # Signal 6: Nickname Overlap
        if banned_data['nicknames'] and candidate_data['nicknames']:
            overlap = banned_data['nicknames'] & candidate_data['nicknames']
            if overlap:
                signals['nickname_overlap'] = f"Shared nicknames: {', '.join(list(overlap)[:3])}"
                total_score += SignalWeights.NICKNAME_OVERLAP

        # Signal 7: High Join Count
        join_count = candidate_data.get('join_count', 1)
        if join_count >= 5:
            signals['high_join_count'] = f"Joined {join_count} times"
            total_score += SignalWeights.JOIN_COUNT_5_PLUS
        elif join_count >= 3:
            signals['high_join_count'] = f"Joined {join_count} times"
            total_score += SignalWeights.JOIN_COUNT_3_PLUS

        # Signal 8: Account Creation Proximity
        creation_score, creation_signal = self._check_creation_proximity(
            banned_data, candidate_data
        )
        if creation_score > 0:
            signals['creation_proximity'] = creation_signal
            total_score += creation_score

        # Signal 9: Bio/Status Match
        bio_score, bio_signal = self._check_bio_similarity(
            banned_data, candidate_data
        )
        if bio_score > 0:
            signals['bio_match'] = bio_signal
            total_score += bio_score

        # Signal 10: Punishment History Correlation
        punishment_score, punishment_signal = self._check_punishment_correlation(
            banned_data, candidate_data
        )
        if punishment_score > 0:
            signals['punishment_correlation'] = punishment_signal
            total_score += punishment_score

        if not signals:
            return None

        # Determine confidence level
        if total_score >= CONFIDENCE_THRESHOLDS['HIGH']:
            confidence = 'HIGH'
        elif total_score >= CONFIDENCE_THRESHOLDS['MEDIUM']:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        return {
            'user_id': candidate.id,
            'username': candidate.name,
            'display_name': candidate.display_name,
            'total_score': total_score,
            'confidence': confidence,
            'signals': signals,
        }

    def _check_account_age(self, member: discord.Member) -> Tuple[int, str]:
        """Check account age signal."""
        now = datetime.now(NY_TZ)
        created = member.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=NY_TZ)
        age = now - created

        if age.days < 7:
            return SignalWeights.ACCOUNT_AGE_UNDER_7_DAYS, f"Account is {age.days} days old"
        elif age.days < 30:
            return SignalWeights.ACCOUNT_AGE_UNDER_30_DAYS, f"Account is {age.days} days old"
        elif age.days < 90:
            return SignalWeights.ACCOUNT_AGE_UNDER_90_DAYS, f"Account is {age.days} days old"

        return 0, ""

    def _check_username_similarity(
        self,
        banned_data: Dict,
        candidate_data: Dict,
    ) -> Tuple[int, str]:
        """Check username similarity using SequenceMatcher."""
        names_to_check = [
            (banned_data['username'], candidate_data['username']),
            (banned_data['display_name'], candidate_data['display_name']),
            (banned_data['username'], candidate_data['display_name']),
            (banned_data['display_name'], candidate_data['username']),
        ]

        best_ratio = 0
        best_pair = ("", "")

        for name1, name2 in names_to_check:
            if name1 and name2:
                ratio = SequenceMatcher(None, name1, name2).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_pair = (name1, name2)

        if best_ratio >= 1.0:
            return SignalWeights.USERNAME_EXACT_MATCH, f"Exact name match: '{best_pair[0]}'"
        elif best_ratio >= 0.8:
            return SignalWeights.USERNAME_HIGH_SIMILARITY, f"{int(best_ratio*100)}% name similarity"
        elif best_ratio >= 0.6:
            return SignalWeights.USERNAME_MEDIUM_SIMILARITY, f"{int(best_ratio*100)}% name similarity"

        return 0, ""

    def _check_join_timing(
        self,
        banned_data: Dict,
        candidate_data: Dict,
    ) -> Tuple[int, str]:
        """Check if accounts joined around the same time."""
        banned_joined = banned_data.get('joined_at')
        candidate_joined = candidate_data.get('joined_at')

        if not banned_joined or not candidate_joined:
            return 0, ""

        # Make both timezone-aware
        if banned_joined.tzinfo is None:
            banned_joined = banned_joined.replace(tzinfo=NY_TZ)
        if candidate_joined.tzinfo is None:
            candidate_joined = candidate_joined.replace(tzinfo=NY_TZ)

        diff = abs((banned_joined - candidate_joined).total_seconds())

        if diff <= 3600:  # 1 hour
            return SignalWeights.JOINED_WITHIN_1_HOUR, "Joined within 1 hour of banned user"
        elif diff <= 21600:  # 6 hours
            return SignalWeights.JOINED_WITHIN_6_HOURS, "Joined within 6 hours of banned user"
        elif diff <= 86400:  # 24 hours
            return SignalWeights.JOINED_WITHIN_24_HOURS, "Joined within 24 hours of banned user"
        elif diff <= 604800:  # 7 days
            return SignalWeights.JOINED_WITHIN_7_DAYS, "Joined within 7 days of banned user"

        return 0, ""

    def _check_creation_proximity(
        self,
        banned_data: Dict,
        candidate_data: Dict,
    ) -> Tuple[int, str]:
        """Check if accounts were created around the same time."""
        banned_created = banned_data.get('created_at')
        candidate_created = candidate_data.get('created_at')

        if not banned_created or not candidate_created:
            return 0, ""

        # Make both timezone-aware
        if banned_created.tzinfo is None:
            banned_created = banned_created.replace(tzinfo=NY_TZ)
        if candidate_created.tzinfo is None:
            candidate_created = candidate_created.replace(tzinfo=NY_TZ)

        diff = abs((banned_created - candidate_created).total_seconds())

        if diff <= 3600:  # 1 hour
            return SignalWeights.CREATED_WITHIN_1_HOUR, "Accounts created within 1 hour"
        elif diff <= 86400:  # 24 hours
            return SignalWeights.CREATED_WITHIN_24_HOURS, "Accounts created within 24 hours"
        elif diff <= 604800:  # 7 days
            return SignalWeights.CREATED_WITHIN_7_DAYS, "Accounts created within 7 days"

        return 0, ""

    def _check_bio_similarity(
        self,
        banned_data: Dict,
        candidate_data: Dict,
    ) -> Tuple[int, str]:
        """Check if accounts have similar bio/status."""
        banned_bio = banned_data.get('bio')
        candidate_bio = candidate_data.get('bio')

        if not banned_bio or not candidate_bio:
            return 0, ""

        # Exact match
        if banned_bio == candidate_bio:
            return SignalWeights.SAME_BIO, f"Identical status: '{banned_bio[:30]}...'" if len(banned_bio) > 30 else f"Identical status: '{banned_bio}'"

        # Similarity check
        ratio = SequenceMatcher(None, banned_bio, candidate_bio).ratio()
        if ratio >= 0.7:
            return SignalWeights.SIMILAR_BIO, f"{int(ratio*100)}% status similarity"

        return 0, ""

    def _check_punishment_correlation(
        self,
        banned_data: Dict,
        candidate_data: Dict,
    ) -> Tuple[int, str]:
        """Check if both accounts have correlated punishment history."""
        banned_dates = banned_data.get('punishment_dates', [])
        candidate_dates = candidate_data.get('punishment_dates', [])

        if not banned_dates or not candidate_dates:
            return 0, ""

        # Check if punished on same day
        for b_date in banned_dates:
            for c_date in candidate_dates:
                # Compare timestamps (within 24 hours = same day punishment)
                if abs(b_date - c_date) <= 86400:
                    return SignalWeights.BOTH_PUNISHED_SAME_DAY, "Both punished within 24 hours of each other"

        # Both have punishment history
        return SignalWeights.BOTH_PREVIOUSLY_PUNISHED, "Both have previous punishments"

    # =========================================================================
    # Alert & Persistence
    # =========================================================================

    async def _save_and_alert(
        self,
        banned_user: discord.Member,
        guild: discord.Guild,
        case_thread_id: int,
        potential_alts: List[Dict],
    ) -> None:
        """Save alt links to database and post alert to case thread."""

        # Save to database
        for alt in potential_alts:
            self.db.save_alt_link(
                banned_user_id=banned_user.id,
                potential_alt_id=alt['user_id'],
                guild_id=guild.id,
                confidence=alt['confidence'],
                total_score=alt['total_score'],
                signals=alt['signals'],
            )

        # Get case thread
        thread = await safe_fetch_channel(self.bot, case_thread_id)
        if not thread:
            return

        # Build alert embed
        embed = self._build_alt_alert_embed(banned_user, potential_alts)

        # Ping owner
        owner_ping = f"<@{self.config.developer_id}>"

        # Send to case thread
        await safe_send(thread, content=owner_ping, embed=embed)

    def _build_alt_alert_embed(
        self,
        banned_user: discord.Member,
        potential_alts: List[Dict],
    ) -> discord.Embed:
        """Build the alt detection alert embed."""
        embed = discord.Embed(
            title="🔍 Potential Alt Accounts Detected",
            description=(
                f"The following accounts may belong to **{banned_user.display_name}**.\n"
                f"Review these accounts and take action if needed."
            ),
            color=EmbedColors.WARNING,
            timestamp=datetime.now(NY_TZ),
        )

        # Group by confidence
        high_conf = [a for a in potential_alts if a['confidence'] == 'HIGH']
        medium_conf = [a for a in potential_alts if a['confidence'] == 'MEDIUM']
        low_conf = [a for a in potential_alts if a['confidence'] == 'LOW']

        # Add high confidence alts
        if high_conf:
            value = self._format_alt_list(high_conf[:5])
            embed.add_field(
                name="🔴 High Confidence",
                value=value,
                inline=False,
            )

        # Add medium confidence alts
        if medium_conf:
            value = self._format_alt_list(medium_conf[:5])
            embed.add_field(
                name="🟡 Medium Confidence",
                value=value,
                inline=False,
            )

        # Add low confidence alts (limit to 3)
        if low_conf:
            value = self._format_alt_list(low_conf[:3])
            embed.add_field(
                name="🟢 Low Confidence",
                value=value,
                inline=False,
            )

        set_footer(embed)

        return embed

    def _format_alt_list(self, alts: List[Dict]) -> str:
        """Format list of alts for embed field."""
        lines = []
        for alt in alts:
            signals_str = ", ".join(alt['signals'].keys())
            lines.append(
                f"<@{alt['user_id']}> (`{alt['username']}`)\n"
                f"└ Score: **{alt['total_score']}** | {signals_str}"
            )
        return "\n".join(lines) or "None"


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AltDetectionService"]
