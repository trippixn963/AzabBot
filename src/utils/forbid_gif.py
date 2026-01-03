"""
Forbid GIF Generator
====================

Generates animated GIF of chains wrapping around a user's avatar for forbid actions.
Chains unwrap for unforbid actions.
Reuses avatar caching from jail_gif module.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import io
import asyncio
import math
from typing import Optional

from PIL import Image, ImageDraw

from src.core.logger import logger
from src.utils.jail_gif import fetch_avatar, _avatar_cache


# =============================================================================
# Constants
# =============================================================================

GIF_SIZE = 256

# Animation settings
TOTAL_FRAMES = 12
FRAME_DURATION = 60  # ms per frame

# Chain settings
CHAIN_COLOR = (90, 90, 90)  # Gray metal
CHAIN_HIGHLIGHT = (130, 130, 130)  # Lighter for 3D effect
CHAIN_SHADOW = (50, 50, 50)  # Darker shadow
CHAIN_LINK_WIDTH = 20  # Width of chain link
CHAIN_LINK_HEIGHT = 12  # Height of chain link
CHAIN_THICKNESS = 5  # Thickness of chain line


# =============================================================================
# Chain Drawing
# =============================================================================

def draw_chain_link(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    horizontal: bool = True,
) -> None:
    """Draw a single chain link at position."""
    if horizontal:
        # Horizontal oval link
        w, h = CHAIN_LINK_WIDTH, CHAIN_LINK_HEIGHT
    else:
        # Vertical oval link
        w, h = CHAIN_LINK_HEIGHT, CHAIN_LINK_WIDTH

    # Draw outer oval (shadow)
    draw.ellipse(
        [x - w // 2 - 1, y - h // 2 - 1, x + w // 2 + 1, y + h // 2 + 1],
        outline=CHAIN_SHADOW,
        width=CHAIN_THICKNESS + 2,
    )

    # Draw main oval
    draw.ellipse(
        [x - w // 2, y - h // 2, x + w // 2, y + h // 2],
        outline=CHAIN_COLOR,
        width=CHAIN_THICKNESS,
    )

    # Draw highlight on top edge
    draw.arc(
        [x - w // 2, y - h // 2, x + w // 2, y + h // 2],
        start=200,
        end=340,
        fill=CHAIN_HIGHLIGHT,
        width=2,
    )


def draw_chains(
    frame: Image.Image,
    progress: float,
    size: int = GIF_SIZE,
) -> Image.Image:
    """
    Draw chains wrapping around the frame.

    Progress 0.0 = no chains visible
    Progress 1.0 = fully wrapped in chains

    Chains come from corners and wrap diagonally.
    """
    if progress <= 0:
        return frame

    result = frame.copy().convert("RGBA")
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Number of chain links visible based on progress
    total_links_per_chain = 10
    visible_links = int(total_links_per_chain * progress)

    if visible_links == 0:
        return frame

    # Chain 1: Top-left to bottom-right diagonal
    chain1_start = (-20, -20)
    chain1_end = (size + 20, size + 20)

    # Chain 2: Top-right to bottom-left diagonal
    chain2_start = (size + 20, -20)
    chain2_end = (-20, size + 20)

    # Draw chain 1 (diagonal \)
    for i in range(visible_links):
        t = i / total_links_per_chain
        x = int(chain1_start[0] + (chain1_end[0] - chain1_start[0]) * t)
        y = int(chain1_start[1] + (chain1_end[1] - chain1_start[1]) * t)
        horizontal = (i % 2 == 0)
        draw_chain_link(draw, x, y, horizontal)

    # Draw chain 2 (diagonal /)
    for i in range(visible_links):
        t = i / total_links_per_chain
        x = int(chain2_start[0] + (chain2_end[0] - chain2_start[0]) * t)
        y = int(chain2_start[1] + (chain2_end[1] - chain2_start[1]) * t)
        horizontal = (i % 2 == 0)
        draw_chain_link(draw, x, y, horizontal)

    # Add horizontal chain across middle (appears later)
    if progress > 0.5:
        mid_progress = (progress - 0.5) / 0.5
        mid_links = int(8 * mid_progress)
        y_mid = size // 2

        for i in range(mid_links):
            x = int((i + 0.5) * size / 8)
            horizontal = (i % 2 == 0)
            draw_chain_link(draw, x, y_mid, horizontal)

    # Add vertical chain down middle (appears later)
    if progress > 0.6:
        vert_progress = (progress - 0.6) / 0.4
        vert_links = int(8 * vert_progress)
        x_mid = size // 2

        for i in range(vert_links):
            y = int((i + 0.5) * size / 8)
            horizontal = (i % 2 == 1)  # Alternate orientation
            draw_chain_link(draw, x_mid, y, horizontal)

    # Composite chains onto frame
    result = Image.alpha_composite(result, overlay)

    return result


def generate_forbid_gif_sync(avatar: Image.Image) -> io.BytesIO:
    """
    Generate forbid GIF synchronously (chains wrapping).

    Returns BytesIO containing the GIF data.
    """
    frames = []
    durations = []

    # First frame: just the avatar (no chains) - brief pause
    frame = avatar.copy().convert("RGBA")
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(200)  # Brief pause before animation

    # Generate animation frames (chains wrapping)
    for i in range(TOTAL_FRAMES):
        progress = (i + 1) / TOTAL_FRAMES

        # Create frame with avatar
        frame = avatar.copy().convert("RGBA")

        # Draw chains at current progress
        frame = draw_chains(frame, progress)

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


def generate_unforbid_gif_sync(avatar: Image.Image) -> io.BytesIO:
    """
    Generate unforbid GIF synchronously (chains unwrapping - reverse).

    Returns BytesIO containing the GIF data.
    """
    frames = []
    durations = []

    # First frame: avatar with full chains - brief pause
    frame = avatar.copy().convert("RGBA")
    frame = draw_chains(frame, 1.0)  # Full chains
    frame = frame.convert("RGB")
    frames.append(frame)
    durations.append(200)  # Brief pause before animation

    # Generate animation frames (chains unwrapping)
    for i in range(TOTAL_FRAMES):
        # Progress from 1 to 0 (chains removing)
        progress = 1.0 - ((i + 1) / TOTAL_FRAMES)

        # Create frame with avatar
        frame = avatar.copy().convert("RGBA")

        # Draw chains at current progress
        frame = draw_chains(frame, progress)

        # Convert for GIF
        frame = frame.convert("RGB")
        frames.append(frame)
        durations.append(FRAME_DURATION)

    # Final frame: just avatar, no chains - stays longer
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


async def generate_forbid_gif(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """
    Generate forbid GIF (chains wrapping) for a user avatar.

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
            logger.warning("Forbid GIF: Could not fetch avatar", [
                ("URL", avatar_url[:50]),
            ])
            return None

        # Generate GIF in executor (CPU-bound)
        loop = asyncio.get_event_loop()
        gif_data = await loop.run_in_executor(
            None,
            generate_forbid_gif_sync,
            avatar,
        )

        cached = "Yes" if user_id and user_id in _avatar_cache else "No"
        logger.tree("Forbid GIF Generated", [
            ("Size", f"{gif_data.getbuffer().nbytes / 1024:.1f} KB"),
            ("Cached", cached),
        ], emoji="🔗")

        return gif_data

    except Exception as e:
        logger.error("Forbid GIF Generation Failed", [
            ("Error", str(e)[:100]),
        ])
        return None


async def generate_unforbid_gif(
    avatar_url: str,
    user_id: Optional[int] = None,
) -> Optional[io.BytesIO]:
    """
    Generate unforbid GIF (chains unwrapping) for a user avatar.

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
            logger.warning("Unforbid GIF: Could not fetch avatar", [
                ("URL", avatar_url[:50]),
            ])
            return None

        # Generate GIF in executor (CPU-bound)
        loop = asyncio.get_event_loop()
        gif_data = await loop.run_in_executor(
            None,
            generate_unforbid_gif_sync,
            avatar,
        )

        cached = "Yes" if user_id and user_id in _avatar_cache else "No"
        logger.tree("Unforbid GIF Generated", [
            ("Size", f"{gif_data.getbuffer().nbytes / 1024:.1f} KB"),
            ("Cached", cached),
        ], emoji="🔓")

        return gif_data

    except Exception as e:
        logger.error("Unforbid GIF Generation Failed", [
            ("Error", str(e)[:100]),
        ])
        return None


__all__ = [
    "generate_forbid_gif",
    "generate_unforbid_gif",
]
