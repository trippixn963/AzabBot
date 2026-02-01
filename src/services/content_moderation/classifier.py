"""
AzabBot - Content Classifier
============================

OpenAI-powered content classification for rule violations.

Author: John Hamwi
Server: discord.gg/syria
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

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


@dataclass
class ClassificationResult:
    """
    Result of content classification.

    Attributes:
        violation: Whether the content violates rules.
        confidence: Confidence score (0.0 - 1.0).
        reason: AI-provided reason for the classification.
        error: Error message if classification failed.
    """

    violation: bool
    confidence: float
    reason: str
    error: Optional[str] = None


class ContentClassifier:
    """
    OpenAI-powered content classifier.

    Uses gpt-4o-mini for fast, cost-effective classification of
    message content against server rules.

    Attributes:
        api_key: OpenAI API key from environment.
        enabled: Whether the classifier is enabled (has API key).
    """

    def __init__(self) -> None:
        """Initialize the content classifier."""
        self.api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self._session: Optional[aiohttp.ClientSession] = None

        if not self.api_key:
            logger.warning("Content Classifier Disabled", [
                ("Reason", "OPENAI_API_KEY not set"),
            ])
        else:
            logger.tree("Content Classifier Initialized", [
                ("Model", OPENAI_MODEL),
                ("Max Tokens", str(MAX_TOKENS)),
                ("Temperature", str(TEMPERATURE)),
            ], emoji="🤖")

    @property
    def enabled(self) -> bool:
        """Check if classifier is enabled (has API key)."""
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create HTTP session for API calls.

        Returns:
            Active aiohttp ClientSession.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session and release resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Content Classifier session closed")

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
        original_length = len(content)
        if original_length > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH] + "..."
            logger.debug(f"Content truncated from {original_length} to {MAX_MESSAGE_LENGTH} chars")

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

            logger.debug(f"OpenAI API call: {len(content)} chars")

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
            json_text = response_text
            if json_text.startswith("```"):
                # Remove markdown code block
                parts = json_text.split("```")
                if len(parts) >= 2:
                    json_text = parts[1]
                    if json_text.startswith("json"):
                        json_text = json_text[4:]
                    json_text = json_text.strip()

            result = json.loads(json_text)

            classification = ClassificationResult(
                violation=result.get("violation", False),
                confidence=float(result.get("confidence", 0.0)),
                reason=result.get("reason", "No reason provided"),
            )

            logger.debug(f"Classification result: violation={classification.violation}, confidence={classification.confidence:.0%}")

            return classification

        except json.JSONDecodeError as e:
            logger.warning("Classification Parse Error", [
                ("Error", str(e)[:50]),
                ("Response", response_text[:100] if "response_text" in locals() else "N/A"),
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
        except asyncio.TimeoutError:
            logger.warning("Classification Timeout", [
                ("Timeout", "10s"),
            ])
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Request timeout",
                error="Timeout",
            )
        except KeyError as e:
            logger.error("Classification Response Format Error", [
                ("Missing Key", str(e)),
            ])
            return ClassificationResult(
                violation=False,
                confidence=0.0,
                reason="Invalid response format",
                error=f"Missing key: {e}",
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


# Required for asyncio.TimeoutError
import asyncio
