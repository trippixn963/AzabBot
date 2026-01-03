"""
Ban GIF Generator
=================

Generates animated GIF of red overlay with "BANNED" stamp for ban actions.
Reuses avatar caching from jail_gif module.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import io
import asyncio
import math
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.core.logger import logger
from src.utils.jail_gif import fetch_avatar, _avatar_cache


# =============================================================================
# Constants
# =============================================================================

GIF_SIZE = 256

# Animation settings
TOTAL_FRAMES = 12
FRAME_DURATION = 60  # ms per frame

# Ban overlay settings
BAN_RED_TINT = (200, 0, 0)  # Red tint color
BAN_TINT_ALPHA = 0.4  # How strong the red tint is (0-1)
STAMP_COLOR = (220, 20, 20)  # Bright red for stamp text
STAMP_OUTLINE_COLOR = (100, 0, 0)  # Dark red outline


# =============================================================================
# Ban Animation Drawing
# =============================================================================

def apply_red_tint(frame: Image.Image, intensity: float) -> Image.Image:
    """
    Apply red tint overlay to frame.

    Args:
        frame: The image to tint
        intensity: 0.0 to 1.0, how strong the tint is

    Returns:
        Tinted image
    """
    if intensity <= 0:
        return frame

    # Create red overlay
    red_overlay = Image.new("RGBA", frame.size, (*BAN_RED_TINT, int(255 * BAN_TINT_ALPHA * intensity)))

    # Composite
    result = frame.copy()
    result = Image.alpha_composite(result.convert("RGBA"), red_overlay)

    return result


def draw_banned_stamp(
    frame: Image.Image,
    progress: float,
    size: int = GIF_SIZE,
) -> Image.Image:
    """
    Draw "BANNED" stamp on frame with animation progress.

    Progress 0.0 = stamp not visible
    Progress 0.5 = stamp appearing (scaling up)
    Progress 1.0 = stamp fully visible with slight rotation
    """
    if progress <= 0.3:
        return frame

    # Adjust progress for stamp appearance (starts at 0.3)
    stamp_progress = (progress - 0.3) / 0.7

    # Create stamp overlay
    stamp_size = int(size * 0.8)  # Stamp is 80% of image size
    stamp = Image.new("RGBA", (stamp_size, stamp_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)

    # Scale effect - stamp grows from small to full size
    scale = 0.5 + (stamp_progress * 0.5)  # 50% to 100%

    # Try to use a bold font, fallback to default
    font_size = int(stamp_size * 0.25 * scale)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    text = "BANNED"

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center position
    x = (stamp_size - text_width) // 2
    y = (stamp_size - text_height) // 2

    # Draw outline/shadow
    outline_offset = max(2, int(font_size * 0.08))
    for ox in range(-outline_offset, outline_offset + 1):
        for oy in range(-outline_offset, outline_offset + 1):
            if ox != 0 or oy != 0:
                draw.text((x + ox, y + oy), text, font=font, fill=(*STAMP_OUTLINE_COLOR, 255))

    # Draw main text
    alpha = int(255 * min(1.0, stamp_progress * 1.5))
    draw.text((x, y), text, font=font, fill=(*STAMP_COLOR, alpha))

    # Draw border rectangle around text
    padding = int(font_size * 0.3)
    rect_coords = [
        x - padding,
        y - padding,
        x + text_width + padding,
        y + text_height + padding,
    ]
    draw.rectangle(rect_coords, outline=(*STAMP_COLOR, alpha), width=max(3, int(font_size * 0.1)))

    # Rotate stamp slightly for "stamped" effect
    rotation = -15  # Slight counter-clockwise rotation
    stamp = stamp.rotate(rotation, expand=False, resample=Image.Resampling.BICUBIC)

    # Scale the stamp based on progress
    if scale < 1.0:
        new_size = int(stamp_size * scale)
        stamp = stamp.resize((new_size, new_size), Image.Resampling.LANCZOS)
        # Center the smaller stamp
        paste_x = (size - new_size) // 2
        paste_y = (size - new_size) // 2
    else:
        paste_x = (size - stamp_size) // 2
        paste_y = (size - stamp_size) // 2

    # Composite stamp onto frame
    result = frame.copy().convert("RGBA")
    result.paste(stamp, (paste_x, paste_y), stamp)

    return result


def generate_ban_gif_sync(avatar: Image.Image) -> io.BytesIO:
    """
    Generate ban GIF synchronously.

    Animation:
    1. Avatar normal (brief pause)
    2. Red tint fades in
    3. "BANNED" stamp appears and scales up

    Returns BytesIO containing the GIF data.
    """
    frames = []
    durations = []

    # First frame: just the avatar (no effect) - brief pause
    frame = avatar.copy().convert("RGBA")
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(200)  # Brief pause before animation

    # Generate animation frames
    for i in range(TOTAL_FRAMES):
        progress = (i + 1) / TOTAL_FRAMES

        # Create frame with avatar
        frame = avatar.copy().convert("RGBA")

        # Apply red tint (fades in over first half)
        tint_progress = min(1.0, progress * 2)
        frame = apply_red_tint(frame, tint_progress)

        # Draw BANNED stamp (appears in second half)
        frame = draw_banned_stamp(frame, progress)

        # Convert for GIF
        frame = frame.convert("RGB")
        frames.append(frame)
        durations.append(FRAME_DURATION)

    # Final frame stays longer
    durations[-1] = 10000  # 10 seconds - effectively static

    # Save as GIF
    output = io.BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=1,  # Play once then stop
        optimize=True,
    )
    output.seek(0)

    return output


async def generate_ban_gif(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """
    Generate ban GIF for a user avatar.

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
            logger.warning("Ban GIF: Could not fetch avatar", [
                ("URL", avatar_url[:50]),
            ])
            return None

        # Generate GIF in executor (CPU-bound)
        loop = asyncio.get_event_loop()
        gif_data = await loop.run_in_executor(
            None,
            generate_ban_gif_sync,
            avatar,
        )

        cached = "Yes" if user_id and user_id in _avatar_cache else "No"
        logger.tree("Ban GIF Generated", [
            ("Size", f"{gif_data.getbuffer().nbytes / 1024:.1f} KB"),
            ("Cached", cached),
        ], emoji="🔨")

        return gif_data

    except Exception as e:
        logger.error("Ban GIF Generation Failed", [
            ("Error", str(e)[:100]),
        ])
        return None


__all__ = [
    "generate_ban_gif",
]
