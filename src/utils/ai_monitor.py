"""
Azab Discord Bot - AI Usage Monitor
===================================

Tracks real OpenAI API usage and costs using actual API response data.

Features:
- Real token usage tracking from API responses
- Cost calculation based on OpenAI pricing (GPT-3.5-turbo)
- Usage statistics and reporting
- Daily/monthly usage tracking
- Session-based tracking
- Automatic data persistence (every 10 requests)
- Human-readable usage reports
- Old data cleanup (30+ days)
- Support for multiple model pricing

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path

from src.core.logger import logger


class AIUsageMonitor:
    """Monitor and track OpenAI API usage with real data"""

    # OpenAI GPT-3.5-turbo pricing (as of 2024)
    # Check https://openai.com/pricing for current rates
    PRICING = {
        'gpt-3.5-turbo': {
            'input': 0.0005 / 1000,   # $0.0005 per 1K input tokens
            'output': 0.0015 / 1000,   # $0.0015 per 1K output tokens
        },
        'gpt-3.5-turbo-16k': {
            'input': 0.003 / 1000,    # $0.003 per 1K input tokens
            'output': 0.004 / 1000,    # $0.004 per 1K output tokens
        }
    }

    def __init__(self):
        """Initialize the usage monitor"""
        self.usage_file = Path('data/ai_usage.json')
        self.usage_file.parent.mkdir(exist_ok=True)
        self.current_session = {
            'start_time': datetime.now().isoformat(),
            'requests': 0,
            'total_tokens': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'estimated_cost': 0.0
        }
        self._load_usage_data()

    def _load_usage_data(self) -> None:
        """Load historical usage data from file"""
        if self.usage_file.exists():
            try:
                with open(self.usage_file, 'r') as f:
                    self.usage_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load usage data: {e}")
                self.usage_data = self._create_empty_data()
        else:
            self.usage_data = self._create_empty_data()

    def _create_empty_data(self) -> Dict[str, Any]:
        """Create empty usage data structure"""
        return {
            'total': {
                'requests': 0,
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'estimated_cost': 0.0,
                'first_tracked': datetime.now().isoformat()
            },
            'daily': {},
            'monthly': {},
            'sessions': []
        }

    def _save_usage_data(self) -> None:
        """Save usage data to file"""
        try:
            with open(self.usage_file, 'w') as f:
                json.dump(self.usage_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save usage data: {e}")

    def track_usage(self, response: Dict[str, Any], model: str = 'gpt-3.5-turbo') -> Dict[str, Any]:
        """
        Track usage from actual OpenAI API response.

        Args:
            response: OpenAI API response object
            model: Model name for pricing calculation

        Returns:
            Usage statistics dictionary
        """
        # Extract real usage data from OpenAI response
        usage = response.get('usage', {})

        if not usage:
            logger.warning("No usage data in OpenAI response")
            return {}

        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)

        # Calculate cost based on model pricing
        pricing = self.PRICING.get(model, self.PRICING['gpt-3.5-turbo'])
        input_cost = prompt_tokens * pricing['input']
        output_cost = completion_tokens * pricing['output']
        total_cost = input_cost + output_cost

        # Update current session
        self.current_session['requests'] += 1
        self.current_session['prompt_tokens'] += prompt_tokens
        self.current_session['completion_tokens'] += completion_tokens
        self.current_session['total_tokens'] += total_tokens
        self.current_session['estimated_cost'] += total_cost

        # Update total usage
        self.usage_data['total']['requests'] += 1
        self.usage_data['total']['prompt_tokens'] += prompt_tokens
        self.usage_data['total']['completion_tokens'] += completion_tokens
        self.usage_data['total']['total_tokens'] += total_tokens
        self.usage_data['total']['estimated_cost'] += total_cost

        # Update daily usage
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in self.usage_data['daily']:
            self.usage_data['daily'][today] = {
                'requests': 0,
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'estimated_cost': 0.0
            }

        self.usage_data['daily'][today]['requests'] += 1
        self.usage_data['daily'][today]['prompt_tokens'] += prompt_tokens
        self.usage_data['daily'][today]['completion_tokens'] += completion_tokens
        self.usage_data['daily'][today]['total_tokens'] += total_tokens
        self.usage_data['daily'][today]['estimated_cost'] += total_cost

        # Update monthly usage
        month = datetime.now().strftime('%Y-%m')
        if month not in self.usage_data['monthly']:
            self.usage_data['monthly'][month] = {
                'requests': 0,
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'estimated_cost': 0.0
            }

        self.usage_data['monthly'][month]['requests'] += 1
        self.usage_data['monthly'][month]['prompt_tokens'] += prompt_tokens
        self.usage_data['monthly'][month]['completion_tokens'] += completion_tokens
        self.usage_data['monthly'][month]['total_tokens'] += total_tokens
        self.usage_data['monthly'][month]['estimated_cost'] += total_cost

        # Save data periodically (every 10 requests)
        if self.current_session['requests'] % 10 == 0:
            self._save_usage_data()

        # Log usage
        logger.info(f"AI Usage: {prompt_tokens} in, {completion_tokens} out, ${total_cost:.4f}")

        return {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cost': total_cost,
            'model': model
        }

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get comprehensive usage statistics"""
        today = datetime.now().strftime('%Y-%m-%d')
        month = datetime.now().strftime('%Y-%m')

        return {
            'current_session': self.current_session,
            'today': self.usage_data['daily'].get(today, self._empty_usage()),
            'this_month': self.usage_data['monthly'].get(month, self._empty_usage()),
            'all_time': self.usage_data['total']
        }

    def get_daily_usage(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get daily usage for the last N days"""
        usage_list = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            if date in self.usage_data['daily']:
                usage = self.usage_data['daily'][date].copy()
                usage['date'] = date
                usage_list.append(usage)

        return usage_list

    def get_monthly_usage(self) -> List[Dict[str, Any]]:
        """Get monthly usage statistics"""
        usage_list = []
        for month, data in sorted(self.usage_data['monthly'].items()):
            usage = data.copy()
            usage['month'] = month
            usage_list.append(usage)

        return usage_list

    def format_usage_report(self) -> str:
        """Format a human-readable usage report"""
        stats = self.get_usage_stats()

        report = "📊 **AI Usage Report**\n"
        report += "=" * 40 + "\n\n"

        # Current session
        session = stats['current_session']
        report += "**Current Session:**\n"
        report += f"• Requests: {session['requests']}\n"
        report += f"• Tokens: {session['total_tokens']:,} "
        report += f"({session['prompt_tokens']:,} in / {session['completion_tokens']:,} out)\n"
        report += f"• Cost: ${session['estimated_cost']:.4f}\n\n"

        # Today
        today = stats['today']
        report += "**Today:**\n"
        report += f"• Requests: {today['requests']}\n"
        report += f"• Tokens: {today['total_tokens']:,}\n"
        report += f"• Cost: ${today['estimated_cost']:.4f}\n\n"

        # This month
        month = stats['this_month']
        report += "**This Month:**\n"
        report += f"• Requests: {month['requests']}\n"
        report += f"• Tokens: {month['total_tokens']:,}\n"
        report += f"• Cost: ${month['estimated_cost']:.4f}\n\n"

        # All time
        total = stats['all_time']
        report += "**All Time:**\n"
        report += f"• Requests: {total['requests']}\n"
        report += f"• Tokens: {total['total_tokens']:,}\n"
        report += f"• Cost: ${total['estimated_cost']:.4f}\n"
        report += f"• Tracking since: {total.get('first_tracked', 'Unknown')[:10]}\n"

        return report

    def _empty_usage(self) -> Dict[str, Any]:
        """Return empty usage dictionary"""
        return {
            'requests': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
            'estimated_cost': 0.0
        }

    def reset_session(self) -> None:
        """Reset current session statistics"""
        self.current_session = {
            'start_time': datetime.now().isoformat(),
            'requests': 0,
            'total_tokens': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'estimated_cost': 0.0
        }

    def cleanup_old_data(self, days_to_keep: int = 30) -> None:
        """Clean up old daily data to save space"""
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')

        # Remove old daily data
        old_dates = [date for date in self.usage_data['daily'] if date < cutoff_date]
        for date in old_dates:
            del self.usage_data['daily'][date]

        if old_dates:
            logger.info(f"Cleaned up {len(old_dates)} old daily usage records")
            self._save_usage_data()


# Global instance
ai_monitor = AIUsageMonitor()