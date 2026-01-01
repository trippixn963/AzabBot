#!/usr/bin/env python3
"""
One-time script to set up AutoMod rule for prison channel.
Blocks all mentions by anyone in prison channels.
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord
from dotenv import load_dotenv

load_dotenv()


async def setup_automod():
    """Create AutoMod rule to block mentions in prison channel."""

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")

        # Get config values from env
        # Use LOGGING_GUILD_ID (main server where prison is)
        guild_id = int(os.getenv("LOGGING_GUILD_ID", 0))
        prison_channel_ids = os.getenv("PRISON_CHANNEL_IDS", "")
        mod_role_id = int(os.getenv("MODERATION_ROLE_ID", 0))

        if not guild_id:
            print("ERROR: GUILD_ID not set")
            await client.close()
            return

        guild = client.get_guild(guild_id)
        if not guild:
            print(f"ERROR: Could not find guild {guild_id}")
            await client.close()
            return

        print(f"Found guild: {guild.name}")

        # Parse prison channel IDs
        channel_ids = []
        if prison_channel_ids:
            for cid in prison_channel_ids.split(","):
                cid = cid.strip()
                if cid.isdigit():
                    channel_ids.append(int(cid))

        if not channel_ids:
            print("ERROR: No prison channel IDs configured")
            await client.close()
            return

        print(f"Prison channels: {channel_ids}")

        # Check for existing rule with same name
        existing_rules = await guild.fetch_automod_rules()
        for rule in existing_rules:
            if rule.name == "Prison - No Mentions":
                print(f"Rule already exists (ID: {rule.id}). Deleting to recreate...")
                await rule.delete(reason="Recreating prison automod rule")
                break

        # Build exempt roles (mods can mention)
        exempt_roles = []
        if mod_role_id:
            mod_role = guild.get_role(mod_role_id)
            if mod_role:
                exempt_roles.append(mod_role)
                print(f"Exempt role: {mod_role.name}")

        # Build exempt channels (all channels EXCEPT prison)
        # This makes the rule only apply to prison channels
        exempt_channels = []
        prison_channel_set = set(channel_ids)
        for channel in guild.channels:
            # Only text-based channels can be exempted
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel)):
                if channel.id not in prison_channel_set:
                    exempt_channels.append(channel)

        print(f"Exempting {len(exempt_channels)} channels (rule applies only to prison)")

        # Create the AutoMod rule
        # Trigger: mention_spam with limit of 1 (blocks ANY mention)
        # Action: Block message + Timeout 1 hour
        try:
            rule = await guild.create_automod_rule(
                name="Prison - No Mentions",
                event_type=discord.AutoModRuleEventType.message_send,
                trigger=discord.AutoModTrigger(
                    type=discord.AutoModRuleTriggerType.mention_spam,
                    mention_total_limit=1,  # Block after just 1 mention
                ),
                actions=[
                    discord.AutoModRuleAction(
                        type=discord.AutoModRuleActionType.block_message,
                        custom_message="Prisoners cannot mention others.",
                    ),
                    discord.AutoModRuleAction(
                        type=discord.AutoModRuleActionType.timeout,
                        duration=timedelta(hours=1),
                    ),
                ],
                enabled=True,
                exempt_roles=exempt_roles if exempt_roles else discord.utils.MISSING,
                exempt_channels=exempt_channels if exempt_channels else discord.utils.MISSING,
                reason="Auto-setup: Block mentions in prison channels",
            )

            print(f"\n✅ AutoMod rule created successfully!")
            print(f"   Rule ID: {rule.id}")
            print(f"   Name: {rule.name}")
            print(f"   Trigger: Block after 1 mention")
            print(f"   Actions: Block message + 1 hour timeout")
            print(f"   Applies to: Prison channel(s) only")
            print(f"   Exempt roles: {[r.name for r in exempt_roles] if exempt_roles else 'None'}")

        except discord.Forbidden:
            print("ERROR: Bot lacks permissions to create AutoMod rules")
            print("Required: Manage Server permission")
        except discord.HTTPException as e:
            print(f"ERROR: Failed to create rule: {e}")

        await client.close()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set")
        return

    await client.start(token)


if __name__ == "__main__":
    asyncio.run(setup_automod())
