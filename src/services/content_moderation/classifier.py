"""
AzabBot - Content Classifier
============================

OpenAI-powered content classification for rule violations.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

import aiohttp

from src.core.logger import logger

from .constants import (
    MAX_MESSAGE_LENGTH,
    MAX_TOKENS,
    OPENAI_MODEL,
    SYSTEM_PROMPT,
    TEMPERATURE,
    USER_PROMPT_TEMPLATE,
)

if TYPE_CHECKING:
    pass


@dataclass
class ClassificationResult:
    """Result of content classification."""
    violation: bool
    confidence: float
    reason: str
    error: Optional[str] = None


class ContentClassifier:
    """
    OpenAI-powered content classifier.

    Uses gpt-4o-mini for fast, cost-effective classification.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self._session: Optional[aiohttp.ClientSession] = None

        if not self.api_key:
            logger.warning("Content Classifier Disabled", [
                ("Reason", "OPENAI_API_KEY not set"),
            ])
        else:
            logger.tree("Content Classifier Initialized", [
                ("Model", OPENAI_MODEL),
                ("Max Tokens", str(MAX_TOKENS)),
            ], emoji="🤖")

    @property
    def enabled(self) -> bool:
        """Check if classifier is enabled (has API key)."""
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def classify(self, content: str) -> ClassificationResult:
        """
        Classify message content for rule violations.

        Args:
            content: The message content to classify.

        Returns:
            ClassificationResult with violation status and confidence.
        """
        if not self.enabled:
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Classifier disabled",
                error="No API key",
            )

        # Truncate if too long
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH] + "..."

        try:
            session = await self._get_session()

            payload = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT_TEMPLATE.format(message=content)},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("OpenAI API Error", [
                        ("Status", str(response.status)),
                        ("Error", error_text[:100]),
                    ])
                    return ClassificationResult(
                        violation=False,
                        confidence=0.0,
                        reason="API error",
                        error=f"HTTP {response.status}",
                    )

                data = await response.json()

            # Parse response
            response_text = data["choices"][0]["message"]["content"].strip()

            # Extract JSON from response (handle potential markdown wrapping)
            if response_text.startswith("```"):
                # Remove markdown code block
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            result = json.loads(response_text)

            return ClassificationResult(
                violation=result.get("violation", False),
                confidence=float(result.get("confidence", 0.0)),
                reason=result.get("reason", "No reason provided"),
            )

        except json.JSONDecodeError as e:
            logger.warning("Classification Parse Error", [
                ("Error", str(e)[:50]),
                ("Response", response_text[:100] if 'response_text' in locals() else "N/A"),
            ])
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Parse error",
                error=str(e),
            )
        except aiohttp.ClientError as e:
            logger.warning("Classification Network Error", [
                ("Error", str(e)[:50]),
            ])
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Network error",
                error=str(e),
            )
        except Exception as e:
            logger.error("Classification Failed", [
                ("Error", str(e)[:50]),
                ("Type", type(e).__name__),
            ])
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Unknown error",
                error=str(e),
            )
