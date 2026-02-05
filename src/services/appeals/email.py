"""
AzabBot - Appeal Notifications
==============================

Send email and webhook notifications for appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
import os
from typing import Optional

from src.core.logger import logger


async def send_appeal_email(
    to_email: str,
    appeal_id: str,
    resolution: str,
    resolution_reason: Optional[str],
    server_name: str,
    server_invite_url: Optional[str] = None,
    max_retries: int = 3,
) -> bool:
    """
    Send email notification about appeal resolution using Resend API.
    Includes retry logic with exponential backoff.

    Args:
        to_email: Recipient email address.
        appeal_id: Appeal ID.
        resolution: "approved" or "denied".
        resolution_reason: Optional reason for the resolution.
        server_name: Name of the Discord server.
        server_invite_url: Invite URL if appeal was approved.
        max_retries: Maximum retry attempts (default 3).

    Returns:
        True if email was sent successfully.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("Appeal Email Skipped", [
            ("Reason", "RESEND_API_KEY not configured"),
            ("Appeal ID", appeal_id),
        ])
        return False

    # Build email content
    if resolution == "approved":
        subject = f"Your Appeal Has Been Approved - {server_name}"
        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #1a1a2e; color: #e0e0e0;">
            <div style="text-align: center; padding: 20px 0;">
                <div style="display: inline-block; width: 60px; height: 60px; background-color: #10b981; border-radius: 50%; line-height: 60px; font-size: 30px;">✓</div>
            </div>
            <h1 style="color: #10b981; text-align: center; margin-bottom: 10px;">Appeal Approved</h1>
            <p style="text-align: center; color: #9ca3af; margin-bottom: 30px;">Appeal ID: {appeal_id}</p>

            <div style="background-color: #16213e; border-radius: 10px; padding: 20px; margin-bottom: 20px;">
                <p style="margin: 0 0 15px 0;">Great news! Your appeal for <strong>{server_name}</strong> has been approved.</p>
                {f'<p style="margin: 0 0 15px 0;"><strong>Reason:</strong> {resolution_reason}</p>' if resolution_reason else ''}
                {f'<p style="margin: 0;"><strong>You can rejoin the server using this link:</strong></p><p style="margin: 10px 0 0 0;"><a href="{server_invite_url}" style="color: #10b981; text-decoration: none;">{server_invite_url}</a></p>' if server_invite_url else ''}
            </div>

            <p style="color: #6b7280; font-size: 12px; text-align: center; margin-top: 30px;">
                This is an automated message from {server_name}
            </p>
        </div>
        """
    else:
        subject = f"Your Appeal Has Been Denied - {server_name}"
        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #1a1a2e; color: #e0e0e0;">
            <div style="text-align: center; padding: 20px 0;">
                <div style="display: inline-block; width: 60px; height: 60px; background-color: #ef4444; border-radius: 50%; line-height: 60px; font-size: 30px;">✗</div>
            </div>
            <h1 style="color: #ef4444; text-align: center; margin-bottom: 10px;">Appeal Denied</h1>
            <p style="text-align: center; color: #9ca3af; margin-bottom: 30px;">Appeal ID: {appeal_id}</p>

            <div style="background-color: #16213e; border-radius: 10px; padding: 20px; margin-bottom: 20px;">
                <p style="margin: 0 0 15px 0;">Unfortunately, your appeal for <strong>{server_name}</strong> has been denied.</p>
                {f'<p style="margin: 0 0 15px 0;"><strong>Reason:</strong> {resolution_reason}</p>' if resolution_reason else ''}
                <p style="margin: 0; color: #9ca3af;">You may submit a new appeal in 24 hours.</p>
            </div>

            <p style="color: #6b7280; font-size: 12px; text-align: center; margin-top: 30px;">
                This is an automated message from {server_name}
            </p>
        </div>
        """

    # Retry loop with exponential backoff
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": f"{server_name} <noreply@trippixn.com>",
                        "to": [to_email],
                        "subject": subject,
                        "html": html_content,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.tree("Appeal Email Sent", [
                            ("Appeal ID", appeal_id),
                            ("To", to_email[:30] + "..." if len(to_email) > 30 else to_email),
                            ("Resolution", resolution),
                            ("Attempt", str(attempt + 1)),
                        ], emoji="📧")
                        return True
                    else:
                        error_text = await resp.text()
                        logger.warning("Appeal Email Attempt Failed", [
                            ("Appeal ID", appeal_id),
                            ("Attempt", f"{attempt + 1}/{max_retries}"),
                            ("Status", str(resp.status)),
                            ("Error", error_text[:50]),
                        ])
        except asyncio.TimeoutError:
            logger.warning("Appeal Email Timeout", [
                ("Appeal ID", appeal_id),
                ("Attempt", f"{attempt + 1}/{max_retries}"),
            ])
        except Exception as e:
            logger.warning("Appeal Email Error", [
                ("Appeal ID", appeal_id),
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Error", str(e)[:50]),
            ])

        # Exponential backoff: 1s, 2s, 4s
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)

    logger.error("Appeal Email Failed (All Retries)", [
        ("Appeal ID", appeal_id),
        ("To", to_email[:30] + "..."),
        ("Attempts", str(max_retries)),
    ])
    return False


__all__ = ["send_appeal_email"]
