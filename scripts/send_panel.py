#!/usr/bin/env python3
"""One-time script to send the ticket panel."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, '/root/AzabBot')

# Load env
env_path = Path('/root/AzabBot/.env')
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key] = value

import discord
from src.core.config import get_config, EmbedColors
from src.utils.footer import FOOTER_TEXT
from src.services.ticket_service import (
    TicketPanelView,
    TICKET_EMOJI,
    PARTNERSHIP_EMOJI,
    SUGGESTION_EMOJI,
)

CHANNEL_ID = 1406750411779604561

async def send_panel():
    config = get_config()
    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            # Get developer avatar
            dev_avatar = None
            try:
                developer = await bot.fetch_user(config.developer_id)
                dev_avatar = developer.display_avatar.url
            except Exception:
                pass

            embed = discord.Embed(
                description=(
                    f"ㅤㅤㅤㅤㅤㅤ**SUPPORT TICKETS**\n\n"
                    "Open a ticket to get in touch with our staff team.\n"
                    "Select a category below that best fits your inquiry.\n\n"
                    f"ㅤ{TICKET_EMOJI} ▸ **Support**\n"
                    f"ㅤㅤㅤ*Questions, issues, or general help*\n\n"
                    f"ㅤ{PARTNERSHIP_EMOJI} ▸ **Partnership**\n"
                    f"ㅤㅤㅤ*Business inquiries & collaborations*\n\n"
                    f"ㅤ{SUGGESTION_EMOJI} ▸ **Suggestion**\n"
                    f"ㅤㅤㅤ*Ideas & feedback for the server*"
                ),
                color=EmbedColors.GREEN,
            )
            embed.set_footer(text=FOOTER_TEXT, icon_url=dev_avatar)
            view = TicketPanelView()
            await channel.send(embed=embed, view=view)
            print('Panel sent!')
        else:
            print('Channel not found!')
        await bot.close()

    await bot.start(config.discord_token)

if __name__ == "__main__":
    asyncio.run(send_panel())
