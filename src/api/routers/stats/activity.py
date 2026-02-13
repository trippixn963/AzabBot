"""
AzabBot - Activity Stats Router
===============================

Activity chart data endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, Query

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import require_auth
from src.api.models.base import APIResponse
from src.api.models.stats import ActivityChartData
from src.api.models.auth import TokenPayload
from src.core.database import get_db


router = APIRouter(tags=["Statistics"])


@router.get("/activity", response_model=APIResponse[List[ActivityChartData]])
async def get_activity_chart(
    days: int = Query(7, ge=1, le=90, description="Number of days to include"),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[List[ActivityChartData]]:
    """
    Get daily activity data for charts.

    Returns data points for each day in the specified range.
    Uses optimized queries to avoid N+1 problem.
    """
    db = get_db()
    now = datetime.now(NY_TZ)
    start_date = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start_date.timestamp()

    # Optimized: Get all case counts in single query
    case_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans
        FROM cases
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    case_data = {int(row[0]): {"total": row[1], "mutes": row[2], "bans": row[3]} for row in case_rows}

    # Optimized: Get all ticket counts in single query
    ticket_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM tickets
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    ticket_data = {int(row[0]): row[1] for row in ticket_rows}

    # Optimized: Get all appeal counts in single query
    appeal_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM appeals
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    appeal_data = {int(row[0]): row[1] for row in appeal_rows}

    # Build activity data
    data = []
    for i in range(days):
        day = now - timedelta(days=days - 1 - i)
        case_info = case_data.get(i, {"total": 0, "mutes": 0, "bans": 0})

        # Format label based on range
        if days <= 7:
            label = day.strftime("%a")  # Mon, Tue, etc.
        else:
            label = day.strftime("%b %d")  # Jan 1, Jan 2, etc.

        data.append(ActivityChartData(
            timestamp=day,
            label=label,
            cases=case_info["total"],
            tickets=ticket_data.get(i, 0),
            appeals=appeal_data.get(i, 0),
            mutes=case_info["mutes"],
            bans=case_info["bans"],
        ))

    logger.debug("Activity Chart Fetched", [
        ("User", str(payload.sub)),
        ("Days", str(days)),
        ("Data Points", str(len(data))),
    ])

    return APIResponse(success=True, data=data)


__all__ = ["router"]
