"""
Time utilities for AzabBot.
Ensures consistent EST timezone usage across the project.
"""

from datetime import datetime, timezone, timedelta
import pytz


def get_est_time() -> datetime:
    """
    Get current time in EST timezone.
    
    Returns:
        datetime: Current time in EST
    """
    est = pytz.timezone('US/Eastern')
    return datetime.now(est)


def get_est_timestamp() -> str:
    """
    Get formatted EST timestamp for logging.
    
    Returns:
        str: Formatted timestamp like "[08/10 03:00 PM EST]"
    """
    est_time = get_est_time()
    return est_time.strftime("[%m/%d %I:%M %p EST]")


def utc_to_est(utc_dt: datetime) -> datetime:
    """
    Convert UTC datetime to EST.
    
    Args:
        utc_dt: UTC datetime object
        
    Returns:
        datetime: EST datetime
    """
    if utc_dt.tzinfo is None:
        # Assume naive datetime is UTC
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    
    est = pytz.timezone('US/Eastern')
    return utc_dt.astimezone(est)


def est_to_utc(est_dt: datetime) -> datetime:
    """
    Convert EST datetime to UTC.
    
    Args:
        est_dt: EST datetime object
        
    Returns:
        datetime: UTC datetime
    """
    if est_dt.tzinfo is None:
        # Assume naive datetime is EST
        est = pytz.timezone('US/Eastern')
        est_dt = est.localize(est_dt)
    
    return est_dt.astimezone(timezone.utc)


def get_current_date_est() -> str:
    """
    Get current date in EST as string.
    
    Returns:
        str: Date in YYYY-MM-DD format
    """
    return get_est_time().strftime("%Y-%m-%d")


def get_current_datetime_iso_est() -> str:
    """
    Get current datetime in ISO format with EST timezone.
    
    Returns:
        str: ISO formatted datetime
    """
    return get_est_time().isoformat()


# For backwards compatibility - replace datetime.utcnow() calls
def now_est() -> datetime:
    """
    Replacement for datetime.utcnow() that returns EST time.
    
    Returns:
        datetime: Current time in EST (timezone-aware)
    """
    return get_est_time()


def now_est_naive() -> datetime:
    """
    Get current EST time as naive datetime (no timezone info).
    Useful for database operations that don't support timezone-aware datetimes.
    
    Returns:
        datetime: Current EST time without timezone info
    """
    return get_est_time().replace(tzinfo=None)