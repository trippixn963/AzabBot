"""
AzabBot - Tag Management
========================

Mixin for forum tag management.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Dict, List

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from .service import CaseLogService


class CaseLogTagsMixin:
    """Mixin for case forum tag management."""

    # =========================================================================
    # Forum Tag Definitions
    # =========================================================================

    # Action type tags
    TAG_MUTE = ("🔇 Mute", discord.Colour.orange())
    TAG_BAN = ("🔨 Ban", discord.Colour.dark_red())
    TAG_WARN = ("⚠️ Warn", discord.Colour.gold())
    TAG_FORBID = ("🚫 Forbid", discord.Colour.purple())

    ALL_TAGS = [TAG_MUTE, TAG_BAN, TAG_WARN, TAG_FORBID]

    # =========================================================================
    # Forum Tag Management
    # =========================================================================

    async def ensure_forum_tags(self: "CaseLogService") -> bool:
        """
        Ensure all required tags exist on the case forum.
        Creates missing tags and caches all tag references.

        Returns:
            True if tags are ready, False if failed.
        """
        if self._tags_initialized:
            return True

        if not self.enabled:
            return False

        try:
            forum = await self._get_forum()
            if not forum:
                logger.warning("Case Log: Cannot ensure tags - forum not found")
                return False

            # Cache all existing tags first
            existing_tags = {tag.name: tag for tag in forum.available_tags}
            for tag in forum.available_tags:
                self._tag_cache[tag.name] = tag

            # Find which tags we need to create
            tags_to_create_names = []
            for tag_name, tag_color in self.ALL_TAGS:
                if tag_name not in existing_tags:
                    tags_to_create_names.append(tag_name)

            # Create missing tags (need to update forum with all tags)
            created_count = 0
            if tags_to_create_names:
                # Build new tags list - existing + new
                new_tags = list(forum.available_tags)
                for tag_name in tags_to_create_names:
                    new_tags.append(discord.ForumTag(name=tag_name, emoji=None, moderated=False))

                # Discord limits to 20 tags
                if len(new_tags) > 20:
                    logger.warning("Case Log: Too many tags, cannot add all")
                    new_tags = new_tags[:20]

                try:
                    await forum.edit(available_tags=new_tags)
                    created_count = len(tags_to_create_names)

                    # Refresh forum to get new tag IDs
                    forum = await self.bot.fetch_channel(self.config.case_log_forum_id)
                    if forum and isinstance(forum, discord.ForumChannel):
                        for tag in forum.available_tags:
                            self._tag_cache[tag.name] = tag

                except discord.HTTPException as e:
                    # If tags already exist (race condition), just cache what we have
                    if "unique" in str(e).lower() or "40061" in str(e):
                        logger.debug("Case Log: Tags already exist, using existing tags")
                    else:
                        raise

            self._tags_initialized = True

            if created_count > 0:
                logger.tree("Case Forum Tags Created", [
                    ("Created", str(created_count)),
                    ("Total Tags", str(len(self._tag_cache))),
                ], emoji="🏷️")
            else:
                logger.tree("Case Forum Tags Ready", [
                    ("Tags Cached", str(len(self._tag_cache))),
                ], emoji="🏷️")

            return True

        except discord.Forbidden:
            logger.error("Case Log: No permission to manage forum tags")
            return False
        except Exception as e:
            logger.error("Case Log: Failed to ensure forum tags", [
                ("Error", str(e)[:100]),
            ])
            return False

    def get_tags_for_case(self: "CaseLogService", action_type: str) -> List[discord.ForumTag]:
        """
        Get the appropriate tags for a case.

        Args:
            action_type: The action type (mute, ban, warn, forbid).

        Returns:
            List of ForumTag objects to apply.
        """
        tags: List[discord.ForumTag] = []

        # Action type tag
        action_tag_map = {
            "mute": self.TAG_MUTE[0],
            "timeout": self.TAG_MUTE[0],
            "ban": self.TAG_BAN[0],
            "warn": self.TAG_WARN[0],
            "forbid": self.TAG_FORBID[0],
        }

        action_tag_name = action_tag_map.get(action_type.lower())
        if action_tag_name:
            action_tag = self._tag_cache.get(action_tag_name)
            if action_tag:
                tags.append(action_tag)

        return tags


__all__ = ["CaseLogTagsMixin"]
