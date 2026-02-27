"""
AzabBot - Content Classifier
============================

OpenAI-powered content classification for rule violations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

from src.core.logger import logger
from src.utils.http import http_session, WEBHOOK_TIMEOUT

from .constants import (
    MAX_MESSAGE_LENGTH,
    MAX_TOKENS,
    OPENAI_MODEL,
    SYSTEM_PROMPT,
    TEMPERATURE,
    USER_PROMPT_TEMPLATE,
)


# Rate limit retry config
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds


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

    async def close(self) -> None:
        """No-op for backward compatibility. HTTP session is managed globally."""
        pass

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
            logger.debug("Content Truncated", [("From", str(original_length)), ("To", str(MAX_MESSAGE_LENGTH))])

        try:
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

            logger.debug("OpenAI API Call", [("Chars", str(len(content)))])

            # Retry loop for rate limits
            data = None
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    async with http_session.post(
                        "https://api.openai.com/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=WEBHOOK_TIMEOUT,  # 10s - OpenAI can be slow
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            break
                        elif response.status == 429:
                            # Rate limited - get retry delay from header or use exponential backoff
                            retry_after = response.headers.get("Retry-After")
                            if retry_after:
                                delay = float(retry_after)
                            else:
                                delay = BASE_RETRY_DELAY * (2 ** attempt)

                            if attempt < MAX_RETRIES - 1:
                                logger.debug("OpenAI Rate Limited", [
                                    ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                                    ("Retry After", f"{delay:.1f}s"),
                                ])
                                await asyncio.sleep(delay)
                                continue
                            else:
                                error_text = await response.text()
                                logger.warning("OpenAI Rate Limit Exhausted", [
                                    ("Attempts", str(MAX_RETRIES)),
                                    ("Error", error_text[:100]),
                                ])
                                last_error = f"Rate limited after {MAX_RETRIES} retries"
                        else:
                            error_text = await response.text()
                            logger.error("OpenAI API Error", [
                                ("Status", str(response.status)),
                                ("Error", error_text[:100]),
                            ])
                            last_error = f"HTTP {response.status}"
                            break  # Don't retry non-429 errors
                except asyncio.TimeoutError:
                    if attempt < MAX_RETRIES - 1:
                        logger.debug("OpenAI Timeout, Retrying", [
                            ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                        ])
                        await asyncio.sleep(BASE_RETRY_DELAY)
                        continue
                    last_error = "Timeout after retries"

            if data is None:
                return ClassificationResult(
                    violation=False,
                    confidence=0.0,
                    reason="API error",
                    error=last_error or "Unknown error",
                )

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

            logger.debug("Classification Result", [("Violation", str(classification.violation)), ("Confidence", f"{classification.confidence:.0%}")])

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


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ClassificationResult", "ContentClassifier"]
