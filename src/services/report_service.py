# =============================================================================
# AzabBot - Report Generation Service
# =============================================================================
# Generates comprehensive reports on prisoner activity, torture effectiveness,
# and Azab's performance. Provides analytics and insights for prison management.
# =============================================================================

from datetime import date, datetime
from typing import Any, Dict, Optional

from src.core.exceptions import ServiceError
from src.services.base_service import BaseService, HealthCheckResult, ServiceStatus


class ReportService(BaseService):
    """
    Service for generating reports on prisoner activities and torture effectiveness.

    Features:
    - Daily activity reports
    - Individual prisoner profiles
    - Torture effectiveness metrics
    - Azab performance analytics
    - Memorable interaction highlights
    """

    def __init__(self, name: str = "ReportService"):
        """Initialize the report service."""
        super().__init__(name, dependencies=["PrisonerDatabaseService"])

        self.db_service = None  # Will be injected
        self._report_cache: Dict[str, Any] = {}
        self._cache_ttl = 300  # 5 minutes

    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """Initialize the report service."""
        self.db_service = kwargs.get("PrisonerDatabaseService")

        if not self.db_service:
            raise ServiceError("ReportService", "PrisonerDatabaseService not available")

        self.logger.log_info("Report service initialized")

    async def start(self) -> None:
        """Start the report service."""
        self.logger.log_info("Report service started")

    async def stop(self) -> None:
        """Stop the report service."""
        self._report_cache.clear()
        self.logger.log_info("Report service stopped")

    async def health_check(self) -> HealthCheckResult:
        """Perform health check."""
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message="Report service operational",
            details={"cached_reports": len(self._report_cache)},
        )

    async def generate_daily_summary(self) -> str:
        """Generate a formatted daily summary report."""
        try:
            # Get today's report data
            report_data = await self.db_service.generate_daily_report()

            if not report_data:
                return "📊 **Daily Report**: No data available"

            prisoner_stats = report_data.get("prisoner_statistics", {})
            session_stats = report_data.get("session_statistics", {})
            most_active = report_data.get("most_active_prisoners", [])

            # Format report
            report = f"""📊 **SEDNAYA PRISON DAILY REPORT** 📊
*Date: {date.today().strftime('%B %d, %Y')}*

**🔒 Prisoner Statistics**
• Total Active: **{prisoner_stats.get('total_prisoners', 0)}**
• New Arrivals: **{prisoner_stats.get('new_prisoners', 0)}**
• Broken Spirits: **{prisoner_stats.get('broken_prisoners', 0)}**
• Showing Resistance: **{prisoner_stats.get('resistant_prisoners', 0)}**

**💬 Torture Session Summary**
• Total Sessions: **{session_stats.get('total_sessions', 0)}**
• Messages Processed: **{session_stats.get('total_messages', 0)}**
• Average Confusion Level: **{session_stats.get('avg_confusion_level', 0):.1f}/10**
• Average Effectiveness: **{session_stats.get('avg_effectiveness', 0):.1f}/5**

**🏆 Most Active Prisoners**"""

            for i, prisoner in enumerate(most_active[:5], 1):
                report += f"\n{i}. **{prisoner['display_name'] or prisoner['username']}** - {prisoner['message_count']} messages"

            report += "\n\n*Azab continues his psychological operations with optimal efficiency.*"

            return report

        except Exception as e:
            self.logger.log_error(f"Failed to generate daily summary: {e}")
            return "📊 **Daily Report**: Error generating report"

    async def generate_prisoner_profile(self, prisoner_identifier: str) -> str:
        """Generate a detailed prisoner profile report."""
        try:
            # Try to find prisoner by username or discord ID
            report_data = await self.db_service.generate_prisoner_report(
                prisoner_identifier
            )

            if not report_data:
                return f"❌ No prisoner found with identifier: {prisoner_identifier}"

            prisoner = report_data.get("prisoner", {})
            stats = report_data.get("session_statistics", {})
            techniques = report_data.get("top_confusion_techniques", [])
            emotions = report_data.get("emotional_state_distribution", [])
            quotes = report_data.get("memorable_quotes", [])

            # Format profile
            profile = f"""📁 **PRISONER PROFILE** 📁

**Subject**: {prisoner.get('display_name') or prisoner.get('username')}
**ID**: #{prisoner.get('discord_id')}
**Status**: {prisoner.get('status', 'active').upper()}
**First Contact**: {self._format_date(prisoner.get('first_seen'))}
**Last Seen**: {self._format_date(prisoner.get('last_seen'))}

**📊 Interaction Metrics**
• Total Messages: **{prisoner.get('total_messages', 0)}**
• Torture Sessions: **{stats.get('total_sessions', 0)}**
• Average Confusion: **{stats.get('avg_confusion', 0):.1f}/10**
• Effectiveness Score: **{prisoner.get('torture_effectiveness_score', 0):.1f}**

**🎭 Psychological Analysis**"""

            if prisoner.get("psychological_profile"):
                profile += f"\n{prisoner['psychological_profile'][:200]}..."

            if prisoner.get("vulnerability_notes"):
                profile += f"\n\n**Known Vulnerabilities**: {prisoner['vulnerability_notes'][:150]}..."

            # Top confusion techniques
            if techniques:
                profile += "\n\n**🔧 Most Effective Techniques**"
                for tech in techniques[:3]:
                    profile += f"\n• {tech['technique'].replace('_', ' ').title()}: {tech['count']} uses"

            # Emotional states
            if emotions:
                profile += "\n\n**😰 Emotional State Distribution**"
                for emotion in emotions[:3]:
                    profile += f"\n• {emotion['state'].title()}: {emotion['count']} occurrences"

            # Memorable quotes
            if quotes:
                profile += "\n\n**💬 Notable Interactions**"
                for i, quote in enumerate(quotes[:2], 1):
                    profile += f"\n\n**Exchange {i}:**"
                    profile += f"\n*Prisoner*: \"{quote['prisoner_message'][:100]}...\""
                    profile += f"\n*Azab*: \"{quote['azab_response'][:100]}...\""

            return profile

        except Exception as e:
            self.logger.log_error(f"Failed to generate prisoner profile: {e}")
            return "📁 **Prisoner Profile**: Error generating profile"

    async def generate_effectiveness_report(self) -> str:
        """Generate torture effectiveness report."""
        try:
            # Get effectiveness metrics from database
            async with self.db_service._get_connection() as conn:
                # Get confusion technique effectiveness
                cursor = await conn.execute(
                    """
                    SELECT
                        confusion_technique,
                        COUNT(*) as usage_count,
                        AVG(CASE WHEN mq.effectiveness_rating IS NOT NULL
                            THEN mq.effectiveness_rating ELSE 3 END) as avg_rating
                    FROM conversation_history ch
                    LEFT JOIN memorable_quotes mq ON ch.session_id = mq.session_id
                    WHERE ch.confusion_technique IS NOT NULL
                    GROUP BY confusion_technique
                    ORDER BY avg_rating DESC, usage_count DESC
                    """
                )
                techniques = await cursor.fetchall()

                # Get overall metrics
                cursor = await conn.execute(
                    """
                    SELECT
                        COUNT(DISTINCT prisoner_id) as total_prisoners,
                        AVG(torture_effectiveness_score) as avg_effectiveness,
                        COUNT(CASE WHEN status = 'broken' THEN 1 END) as broken_count,
                        COUNT(CASE WHEN torture_effectiveness_score > 7 THEN 1 END) as highly_affected
                    FROM prisoners
                    WHERE total_messages > 0
                    """
                )
                overall = dict(await cursor.fetchone())

            # Format report
            report = f"""🎯 **TORTURE EFFECTIVENESS REPORT** 🎯
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*

**📈 Overall Performance**
• Total Subjects: **{overall['total_prisoners']}**
• Average Effectiveness: **{overall['avg_effectiveness']:.1f}/10**
• Broken Prisoners: **{overall['broken_count']}**
• Highly Affected: **{overall['highly_affected']}**

**🔧 Technique Effectiveness Rankings**"""

            for i, tech in enumerate(techniques[:5], 1):
                tech_name = tech["confusion_technique"].replace("_", " ").title()
                report += f"\n{i}. **{tech_name}**"
                report += f"\n   • Used: {tech['usage_count']} times"
                report += f"\n   • Rating: {tech['avg_rating']:.1f}/5"

            # Success rate
            if overall["total_prisoners"] > 0:
                success_rate = (
                    overall["broken_count"] / overall["total_prisoners"]
                ) * 100
                report += f"\n\n**Success Rate**: {success_rate:.1f}% prisoners broken"

            report += (
                "\n\n*Azab's psychological warfare continues to evolve and improve.*"
            )

            return report

        except Exception as e:
            self.logger.log_error(f"Failed to generate effectiveness report: {e}")
            return "🎯 **Effectiveness Report**: Error generating report"

    async def generate_azab_status(self) -> str:
        """Generate Azab's current operational status."""
        try:
            # Get current statistics
            async with self.db_service._get_connection() as conn:
                # Today's activity
                cursor = await conn.execute(
                    """
                    SELECT
                        COUNT(DISTINCT prisoner_id) as prisoners_today,
                        COUNT(*) as messages_today,
                        COUNT(DISTINCT session_id) as sessions_today
                    FROM conversation_history
                    WHERE DATE(timestamp) = DATE('now')
                    AND message_type = 'azab'
                    """
                )
                today_stats = dict(await cursor.fetchone())

                # Get recent memorable quotes
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) as quote_count
                    FROM memorable_quotes
                    WHERE DATE(created_at) >= DATE('now', '-7 days')
                    """
                )
                recent_quotes = await cursor.fetchone()

            # Format status
            status = f"""🤖 **AZAB OPERATIONAL STATUS** 🤖

**Current Mode**: {'ACTIVE' if today_stats['messages_today'] > 0 else 'STANDBY'}
**Confusion Protocol**: ENGAGED
**Empathy Module**: NOT FOUND

**📊 Today's Activity**
• Prisoners Tortured: **{today_stats['prisoners_today']}**
• Confusion Messages: **{today_stats['messages_today']}**
• Active Sessions: **{today_stats['sessions_today']}**

**Recent Performance**
• Memorable Quotes (7 days): **{recent_quotes['quote_count']}**
• Primary Method: **Contextual Confusion**
• Secondary Method: **Topic Displacement**

*"I heard you mention suffering? That reminds me of my grandmother's lemon cake recipe..."* - Azab
"""

            return status

        except Exception as e:
            self.logger.log_error(f"Failed to generate Azab status: {e}")
            return "🤖 **Azab Status**: Experiencing technical difficulties"

    def _format_date(self, date_str: Optional[str]) -> str:
        """Format date string for display."""
        if not date_str:
            return "Unknown"

        try:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%b %d, %Y")
        except Exception:
            return date_str
