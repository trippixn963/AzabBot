"""
Jail Bars GIF Generator
=======================

Generates animated GIF of jail bars closing over a user's avatar.
Includes avatar caching for performance optimization.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import io
import asyncio
from typing import Optional, Dict, Tuple

import aiohttp
from PIL import Image, ImageDraw

from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

# GIF dimensions
GIF_SIZE = 256

# Jail bar settings
BAR_COLOR = (40, 40, 40)  # Dark gray
BAR_WIDTH = 12
BAR_SPACING = 40
BAR_HIGHLIGHT = (60, 60, 60)  # Slightly lighter for 3D effect

# Animation settings
TOTAL_FRAMES = 12  # Frames for animation
FRAME_DURATION = 60  # ms per frame (animation)


# =============================================================================
# Avatar Cache
# =============================================================================

# Cache: user_id -> (avatar_image, avatar_url_hash)
# We store url hash to detect if avatar changed
_avatar_cache: Dict[int, Tuple[Image.Image, str]] = {}


def _get_url_hash(url: str) -> str:
    """Get a simple hash of avatar URL to detect changes."""
    # Discord avatar URLs contain a hash, extract it
    # Format: .../avatars/user_id/hash.png?size=...
    if "/avatars/" in url:
        try:
            parts = url.split("/avatars/")[1].split("/")
            if len(parts) >= 2:
                return parts[1].split(".")[0].split("?")[0]
        except Exception:
            pass
    return url  # Fallback to full URL


def get_cached_avatar(user_id: int, avatar_url: str) -> Optional[Image.Image]:
    """Get avatar from cache if available and URL hasn't changed."""
    if user_id in _avatar_cache:
        cached_img, cached_hash = _avatar_cache[user_id]
        current_hash = _get_url_hash(avatar_url)
        if cached_hash == current_hash:
            return cached_img.copy()  # Return copy to avoid mutations
    return None


def cache_avatar(user_id: int, avatar_url: str, avatar: Image.Image) -> None:
    """Store avatar in cache."""
    url_hash = _get_url_hash(avatar_url)
    _avatar_cache[user_id] = (avatar.copy(), url_hash)


def clear_avatar_cache() -> int:
    """Clear all cached avatars. Returns count of cleared entries."""
    count = len(_avatar_cache)
    _avatar_cache.clear()
    if count > 0:
        logger.tree("Avatar Cache Cleared", [
            ("Entries Cleared", str(count)),
        ], emoji="🧹")
    return count


def get_cache_stats() -> Dict[str, int]:
    """Get cache statistics."""
    return {
        "cached_avatars": len(_avatar_cache),
    }


# =============================================================================
# Avatar Fetching
# =============================================================================

async def fetch_avatar(
    avatar_url: str,
    user_id: Optional[int] = None,
    size: int = GIF_SIZE,
) -> Optional[Image.Image]:
    """Fetch and resize user avatar, using cache if available."""
    # Check cache first
    if user_id is not None:
        cached = get_cached_avatar(user_id, avatar_url)
        if cached is not None:
            return cached

    # Fetch from Discord
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()

        avatar = Image.open(io.BytesIO(data))
        avatar = avatar.convert("RGBA")
        avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)

        # Cache for future use
        if user_id is not None:
            cache_avatar(user_id, avatar_url, avatar)

        return avatar
    except Exception as e:
        logger.error("Failed to fetch avatar", [
            ("URL", avatar_url[:50]),
            ("Error", str(e)[:50]),
        ])
        return None


def draw_jail_bars(
    frame: Image.Image,
    progress: float,
    size: int = GIF_SIZE,
) -> Image.Image:
    """
    Draw jail bars on frame with given progress (0.0 to 1.0).

    Progress 0.0 = bars fully above image (not visible)
    Progress 1.0 = bars fully covering image
    """
    if progress <= 0:
        return frame

    draw = ImageDraw.Draw(frame)

    # Calculate the visible height of the bars descending from top
    # At progress 0, visible_height = 0 (nothing shows)
    # At progress 1, visible_height = size (full coverage)
    visible_height = int(size * progress)

    if visible_height <= 0:
        return frame

    # Draw vertical bars - only the visible portion from top
    x = BAR_SPACING // 2
    while x < size:
        # Main bar (dark) - from top of image to current descent point
        draw.rectangle(
            [x, 0, x + BAR_WIDTH, visible_height],
            fill=BAR_COLOR,
        )
        # Highlight on left edge for 3D effect
        draw.rectangle(
            [x, 0, x + 2, visible_height],
            fill=BAR_HIGHLIGHT,
        )
        x += BAR_SPACING

    # Draw horizontal bar at the bottom edge of descending bars (leading edge)
    bar_y = visible_height - BAR_WIDTH
    if bar_y >= 0:
        draw.rectangle(
            [0, bar_y, size, visible_height],
            fill=BAR_COLOR,
        )
        draw.rectangle(
            [0, bar_y, size, bar_y + 2],
            fill=BAR_HIGHLIGHT,
        )

    # Draw top horizontal bar once bars have descended enough
    if progress > 0.1:
        draw.rectangle(
            [0, 0, size, BAR_WIDTH],
            fill=BAR_COLOR,
        )
        draw.rectangle(
            [0, 0, size, 2],
            fill=BAR_HIGHLIGHT,
        )

    # Draw bottom horizontal bar once fully closed
    if progress >= 1.0:
        bottom_y = size - BAR_WIDTH
        draw.rectangle(
            [0, bottom_y, size, size],
            fill=BAR_COLOR,
        )
        draw.rectangle(
            [0, bottom_y, size, bottom_y + 2],
            fill=BAR_HIGHLIGHT,
        )

    return frame


def generate_jail_gif_sync(avatar: Image.Image) -> io.BytesIO:
    """
    Generate jail bars GIF synchronously.

    Returns BytesIO containing the GIF data.
    """
    frames = []
    durations = []

    # First frame: just the avatar (no bars) - brief pause
    frame = avatar.copy().convert("RGBA")
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(200)  # Brief pause before animation starts

    # Generate animation frames (bars closing from top)
    for i in range(TOTAL_FRAMES):
        # Progress from 0 to 1 (bars descending)
        progress = (i + 1) / TOTAL_FRAMES

        # Create frame with avatar
        frame = avatar.copy().convert("RGBA")

        # Draw jail bars at current progress
        frame = draw_jail_bars(frame, progress)

        # Convert for GIF
        frame = frame.convert("RGB")
        frames.append(frame)
        durations.append(FRAME_DURATION)

    # Final frame stays forever (very long duration simulates static)
    # We already have the last frame from the loop, just extend its duration
    durations[-1] = 10000  # 10 seconds - effectively static

    # Save as GIF - loop=1 means play only once then stop
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=1,  # Play once then stop on last frame
        optimize=True,
    )
    output.seek(0)

    return output


def generate_unjail_gif_sync(avatar: Image.Image) -> io.BytesIO:
    """
    Generate jail bars OPENING GIF synchronously (reverse of jail).

    Returns BytesIO containing the GIF data.
    """
    frames = []
    durations = []

    # First frame: avatar with full jail bars - brief pause
    frame = avatar.copy().convert("RGBA")
    frame = draw_jail_bars(frame, 1.0)  # Full bars
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(200)  # Brief pause before animation starts

    # Generate animation frames (bars opening/lifting up)
    for i in range(TOTAL_FRAMES):
        # Progress from 1 to 0 (bars lifting up)
        progress = 1.0 - ((i + 1) / TOTAL_FRAMES)

        # Create frame with avatar
        frame = avatar.copy().convert("RGBA")

        # Draw jail bars at current progress
        frame = draw_jail_bars(frame, progress)

        # Convert for GIF
        frame = frame.convert("RGB")
        frames.append(frame)
        durations.append(FRAME_DURATION)

    # Final frame: just avatar, no bars - stays forever
    frame = avatar.copy().convert("RGBA")
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(10000)  # 10 seconds - effectively static

    # Save as GIF - loop=1 means play only once then stop
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=1,  # Play once then stop on last frame
        optimize=True,
    )
    output.seek(0)

    return output


async def generate_jail_gif(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """
    Generate jail bars GIF for a user avatar.

    Args:
        avatar_url: URL of the user's avatar
        user_id: Optional user ID for caching

    Returns:
        BytesIO containing GIF data, or None if failed
    """
    try:
        # Fetch avatar (uses cache if available)
        avatar = await fetch_avatar(avatar_url, user_id=user_id)
        if not avatar:
            logger.warning("Jail GIF: Could not fetch avatar", [
                ("URL", avatar_url[:50]),
            ])
            return None

        # Generate GIF in executor (CPU-bound)
        loop = asyncio.get_event_loop()
        gif_data = await loop.run_in_executor(
            None,
            generate_jail_gif_sync,
            avatar,
        )

        cached = "Yes" if user_id and user_id in _avatar_cache else "No"
        logger.tree("Jail GIF Generated", [
            ("Size", f"{gif_data.getbuffer().nbytes / 1024:.1f} KB"),
            ("Cached", cached),
        ], emoji="🎬")

        return gif_data

    except Exception as e:
        logger.error("Jail GIF Generation Failed", [
            ("Error", str(e)[:100]),
        ])
        return None


async def generate_unjail_gif(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """
    Generate jail bars OPENING GIF for a user avatar (unmute animation).

    Args:
        avatar_url: URL of the user's avatar
        user_id: Optional user ID for caching

    Returns:
        BytesIO containing GIF data, or None if failed
    """
    try:
        # Fetch avatar (uses cache if available)
        avatar = await fetch_avatar(avatar_url, user_id=user_id)
        if not avatar:
            logger.warning("Unjail GIF: Could not fetch avatar", [
                ("URL", avatar_url[:50]),
            ])
            return None

        # Generate GIF in executor (CPU-bound)
        loop = asyncio.get_event_loop()
        gif_data = await loop.run_in_executor(
            None,
            generate_unjail_gif_sync,
            avatar,
        )

        cached = "Yes" if user_id and user_id in _avatar_cache else "No"
        logger.tree("Unjail GIF Generated", [
            ("Size", f"{gif_data.getbuffer().nbytes / 1024:.1f} KB"),
            ("Cached", cached),
        ], emoji="🎬")

        return gif_data

    except Exception as e:
        logger.error("Unjail GIF Generation Failed", [
            ("Error", str(e)[:100]),
        ])
        return None


def generate_jail_static(avatar: Image.Image) -> io.BytesIO:
    """Generate static PNG of jailed avatar (final frame)."""
    frame = avatar.copy().convert("RGBA")
    frame = draw_jail_bars(frame, 1.0)  # Full bars
    frame = frame.convert("RGB")

    output = io.BytesIO()
    frame.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def generate_unjail_static(avatar: Image.Image) -> io.BytesIO:
    """Generate static PNG of free avatar (no bars)."""
    frame = avatar.copy().convert("RGBA")
    frame = frame.convert("RGB")

    output = io.BytesIO()
    frame.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def generate_jail_static_png(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """Generate static jailed PNG for a user avatar."""
    try:
        avatar = await fetch_avatar(avatar_url, user_id=user_id)
        if not avatar:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, generate_jail_static, avatar)
    except Exception:
        return None


async def generate_unjail_static_png(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """Generate static free avatar PNG."""
    try:
        avatar = await fetch_avatar(avatar_url, user_id=user_id)
        if not avatar:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, generate_unjail_static, avatar)
    except Exception:
        return None


__all__ = [
    # GIF generation
    "generate_jail_gif",
    "generate_unjail_gif",
    "generate_jail_static_png",
    "generate_unjail_static_png",
    # Cache management
    "clear_avatar_cache",
    "get_cache_stats",
]
