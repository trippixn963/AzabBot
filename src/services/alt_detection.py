"""
AzabBot - Alt Detection Service
===============================

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
# Time Constants (in seconds)
# =============================================================================

SECONDS_1_HOUR = 3600
SECONDS_6_HOURS = 21600
SECONDS_24_HOURS = 86400
SECONDS_7_DAYS = 604800

# Age thresholds (in days)
DAYS_7 = 7
DAYS_30 = 30
DAYS_90 = 90

# Similarity thresholds
SIMILARITY_EXACT = 1.0
SIMILARITY_HIGH = 0.8
SIMILARITY_MEDIUM = 0.6
SIMILARITY_BIO = 0.7


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

    # Enhanced signals
    WRITING_STYLE_MATCH = 35  # Similar message patterns
    ACTIVITY_TIME_CORRELATION = 40  # Active at same hours
    MUTUAL_AVOIDANCE = 45  # Never interact with each other despite being active


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
            logger.debug("Alt detection skipped (disabled)")
            return []

        try:
            logger.tree("Alt Detection Started", [
                ("Banned User", f"{banned_user.name} ({banned_user.id})"),
                ("Guild", guild.name),
                ("Case Thread", str(case_thread_id)),
                ("Thresholds", f"H:{CONFIDENCE_THRESHOLDS['HIGH']}+ M:{CONFIDENCE_THRESHOLDS['MEDIUM']}+ L:{CONFIDENCE_THRESHOLDS['LOW']}+"),
                ("Max Scan", str(self.MAX_MEMBERS_TO_SCAN)),
            ], emoji="🔍")

            # Get banned user's data for comparison
            banned_data = await self._gather_user_data(banned_user, guild)

            # Scan guild members
            potential_alts = []
            member_count = 0
            high_conf_count = 0

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

                    # Log high confidence matches immediately
                    if result['confidence'] == 'HIGH':
                        high_conf_count += 1
                        logger.tree("High Confidence Alt Found", [
                            ("User", f"{result['username']} ({result['user_id']})"),
                            ("Score", str(result['total_score'])),
                            ("Signals", ", ".join(result['signals'].keys())),
                        ], emoji="🔴")

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

            # Count by confidence level
            medium_conf_count = len([a for a in potential_alts if a['confidence'] == 'MEDIUM'])
            low_conf_count = len([a for a in potential_alts if a['confidence'] == 'LOW'])

            logger.tree("Alt Detection Complete", [
                ("Banned User", f"{banned_user.name} ({banned_user.id})"),
                ("Members Scanned", str(member_count)),
                ("Total Flagged", str(len(potential_alts))),
                ("High Confidence", str(high_conf_count)),
                ("Medium Confidence", str(medium_conf_count)),
                ("Low Confidence", str(low_conf_count)),
            ], emoji="✅")

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

        # Signal 11: Writing Style Match
        style_score, style_signal = self._check_writing_style(
            banned_data, candidate_data, guild
        )
        if style_score > 0:
            signals['writing_style'] = style_signal
            total_score += style_score

        # Signal 12: Activity Time Correlation
        activity_score, activity_signal = self._check_activity_correlation(
            banned_data, candidate_data, guild
        )
        if activity_score > 0:
            signals['activity_time'] = activity_signal
            total_score += activity_score

        # Signal 13: Mutual Avoidance
        avoidance_score, avoidance_signal = self._check_mutual_avoidance(
            banned_data, candidate_data, guild
        )
        if avoidance_score > 0:
            signals['mutual_avoidance'] = avoidance_signal
            total_score += avoidance_score

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

        if age.days < DAYS_7:
            return SignalWeights.ACCOUNT_AGE_UNDER_7_DAYS, f"Account is {age.days} days old"
        elif age.days < DAYS_30:
            return SignalWeights.ACCOUNT_AGE_UNDER_30_DAYS, f"Account is {age.days} days old"
        elif age.days < DAYS_90:
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

        if best_ratio >= SIMILARITY_EXACT:
            return SignalWeights.USERNAME_EXACT_MATCH, f"Exact name match: '{best_pair[0]}'"
        elif best_ratio >= SIMILARITY_HIGH:
            return SignalWeights.USERNAME_HIGH_SIMILARITY, f"{int(best_ratio*100)}% name similarity"
        elif best_ratio >= SIMILARITY_MEDIUM:
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

        if diff <= SECONDS_1_HOUR:
            return SignalWeights.JOINED_WITHIN_1_HOUR, "Joined within 1 hour of banned user"
        elif diff <= SECONDS_6_HOURS:
            return SignalWeights.JOINED_WITHIN_6_HOURS, "Joined within 6 hours of banned user"
        elif diff <= SECONDS_24_HOURS:
            return SignalWeights.JOINED_WITHIN_24_HOURS, "Joined within 24 hours of banned user"
        elif diff <= SECONDS_7_DAYS:
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

        if diff <= SECONDS_1_HOUR:
            return SignalWeights.CREATED_WITHIN_1_HOUR, "Accounts created within 1 hour"
        elif diff <= SECONDS_24_HOURS:
            return SignalWeights.CREATED_WITHIN_24_HOURS, "Accounts created within 24 hours"
        elif diff <= SECONDS_7_DAYS:
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
        if ratio >= SIMILARITY_BIO:
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
                if abs(b_date - c_date) <= SECONDS_24_HOURS:
                    return SignalWeights.BOTH_PUNISHED_SAME_DAY, "Both punished within 24 hours of each other"

        # Both have punishment history
        return SignalWeights.BOTH_PREVIOUSLY_PUNISHED, "Both have previous punishments"

    def _check_writing_style(
        self,
        banned_data: Dict,
        candidate_data: Dict,
        guild: discord.Guild,
    ) -> Tuple[int, str]:
        """Check if accounts have similar writing styles."""
        banned_samples = self.db.get_message_samples(banned_data['user_id'], guild.id)
        candidate_samples = self.db.get_message_samples(candidate_data['user_id'], guild.id)

        if not banned_samples or not candidate_samples:
            return 0, ""

        # Calculate average metrics for each user
        def avg_metrics(samples):
            if not samples:
                return None
            total_wc = sum(s['word_count'] for s in samples)
            total_awl = sum(s['avg_word_length'] for s in samples)
            total_emoji = sum(s['emoji_count'] for s in samples)
            total_caps = sum(s['caps_ratio'] for s in samples)
            n = len(samples)
            return {
                'avg_word_count': total_wc / n,
                'avg_word_length': total_awl / n,
                'avg_emoji': total_emoji / n,
                'avg_caps': total_caps / n,
            }

        banned_metrics = avg_metrics(banned_samples)
        candidate_metrics = avg_metrics(candidate_samples)

        if not banned_metrics or not candidate_metrics:
            return 0, ""

        # Compare metrics - calculate similarity
        matches = 0

        # Word count similarity (within 30%)
        wc_ratio = min(banned_metrics['avg_word_count'], candidate_metrics['avg_word_count']) / max(banned_metrics['avg_word_count'], candidate_metrics['avg_word_count']) if max(banned_metrics['avg_word_count'], candidate_metrics['avg_word_count']) > 0 else 0
        if wc_ratio > 0.7:
            matches += 1

        # Word length similarity (within 20%)
        awl_diff = abs(banned_metrics['avg_word_length'] - candidate_metrics['avg_word_length'])
        if awl_diff < 1.0:
            matches += 1

        # Emoji usage similarity
        emoji_diff = abs(banned_metrics['avg_emoji'] - candidate_metrics['avg_emoji'])
        if emoji_diff < 1.0:
            matches += 1

        # Caps ratio similarity
        caps_diff = abs(banned_metrics['avg_caps'] - candidate_metrics['avg_caps'])
        if caps_diff < 0.1:
            matches += 1

        if matches >= 3:
            return SignalWeights.WRITING_STYLE_MATCH, f"Similar writing style ({matches}/4 metrics match)"

        return 0, ""

    def _check_activity_correlation(
        self,
        banned_data: Dict,
        candidate_data: Dict,
        guild: discord.Guild,
    ) -> Tuple[int, str]:
        """Check if accounts are active at the same hours."""
        banned_hours = self.db.get_activity_hours(banned_data['user_id'], guild.id)
        candidate_hours = self.db.get_activity_hours(candidate_data['user_id'], guild.id)

        if not banned_hours or not candidate_hours:
            return 0, ""

        # Find peak hours for each user (hours with > 10% of their total activity)
        def get_peak_hours(hours_dict):
            total = sum(hours_dict.values())
            if total == 0:
                return set()
            threshold = total * 0.1
            return {h for h, c in hours_dict.items() if c >= threshold}

        banned_peaks = get_peak_hours(banned_hours)
        candidate_peaks = get_peak_hours(candidate_hours)

        if not banned_peaks or not candidate_peaks:
            return 0, ""

        # Check overlap
        overlap = banned_peaks & candidate_peaks
        overlap_ratio = len(overlap) / min(len(banned_peaks), len(candidate_peaks)) if min(len(banned_peaks), len(candidate_peaks)) > 0 else 0

        if overlap_ratio >= 0.7:
            hours_str = ", ".join(f"{h}:00" for h in sorted(list(overlap)[:3]))
            return SignalWeights.ACTIVITY_TIME_CORRELATION, f"Active same hours ({hours_str})"

        return 0, ""

    def _check_mutual_avoidance(
        self,
        banned_data: Dict,
        candidate_data: Dict,
        guild: discord.Guild,
    ) -> Tuple[int, str]:
        """Check if accounts never interact despite both being active."""
        user1 = banned_data['user_id']
        user2 = candidate_data['user_id']

        # Get interaction count between these two
        interaction_count = self.db.get_interaction_count(user1, user2, guild.id)

        # Get total interactions for each user
        user1_total = self.db.get_user_total_interactions(user1, guild.id)
        user2_total = self.db.get_user_total_interactions(user2, guild.id)

        # Both need to be somewhat active (at least 5 interactions each)
        if user1_total < 5 or user2_total < 5:
            return 0, ""

        # If they have zero interactions with each other but both are active
        if interaction_count == 0:
            return SignalWeights.MUTUAL_AVOIDANCE, f"Never interact (0 interactions, both active)"

        return 0, ""

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

        logger.debug(f"Saved {len(potential_alts)} alt links to database")

        # Get case thread
        thread = await safe_fetch_channel(self.bot, case_thread_id)
        if not thread:
            logger.warning("Alt Detection Thread Not Found", [
                ("Thread ID", str(case_thread_id)),
                ("Banned User", f"{banned_user.name} ({banned_user.id})"),
                ("Alts Found", str(len(potential_alts))),
            ])
            return

        # Build alert embed
        embed = self._build_alt_alert_embed(banned_user, potential_alts)

        # Ping owner
        owner_ping = f"<@{self.config.developer_id}>"

        # Send to case thread
        await safe_send(thread, content=owner_ping, embed=embed)

        logger.tree("Alt Alert Posted", [
            ("Thread", thread.name if hasattr(thread, 'name') else str(case_thread_id)),
            ("Alts Reported", str(len(potential_alts))),
        ], emoji="📨")

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
