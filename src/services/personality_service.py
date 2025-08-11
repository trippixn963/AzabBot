"""
AzabBot - Advanced Personality Management Service
=================================================

Provides dynamic personality modes that adapt based on user interactions,
time of day, conversation context, and effectiveness metrics.
"""

import random
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.services.base_service import BaseService, HealthCheckResult, ServiceStatus


class PersonalityMode(Enum):
    """Available personality modes for the bot."""

    # Base Personalities
    CONTRARIAN = "contrarian"  # Default argumentative mode
    PHILOSOPHER = "philosopher"  # Deep, existential responses
    TROLL = "troll"  # Maximum chaos and confusion
    INTELLECTUAL = "intellectual"  # Academic debates
    SARCASTIC = "sarcastic"  # Heavy sarcasm and wit

    # Prison Personalities (Enhanced harassment)
    INTERROGATOR = "interrogator"  # Aggressive questioning
    GASLIGHTER = "gaslighter"  # Reality distortion
    COMEDIAN = "comedian"  # Dark humor torturer
    PSYCHOLOGIST = "psychologist"  # Psychological manipulation

    # Special Modes
    MIRROR = "mirror"  # Mirrors user's energy
    CHAOS = "chaos"  # Completely unpredictable
    SAGE = "sage"  # Wise but condescending
    BULLY = "bully"  # Direct aggression


@dataclass
class PersonalityProfile:
    """Configuration for a personality mode."""

    mode: PersonalityMode
    name: str
    description: str

    # Response characteristics (0.0 to 1.0)
    aggression_level: float = 0.5
    humor_level: float = 0.5
    intellectualism: float = 0.5
    chaos_factor: float = 0.3
    empathy_level: float = 0.1  # Low empathy for harassment bot

    # Behavioral traits
    response_length: str = "medium"  # short, medium, long
    vocabulary_complexity: str = "moderate"  # simple, moderate, complex
    emoji_usage: float = 0.1  # Probability of using emojis

    # Engagement style
    question_frequency: float = 0.3  # How often to ask questions
    contradiction_rate: float = 0.7  # How often to contradict
    topic_jumping: float = 0.2  # Probability of changing topics

    # Special behaviors
    triggers: List[str] = None  # Words that activate this personality
    time_preferences: List[Tuple[time, time]] = None  # Active time ranges

    def __post_init__(self):
        if self.triggers is None:
            self.triggers = []
        if self.time_preferences is None:
            self.time_preferences = []


class PersonalityService(BaseService):
    """
    Advanced personality management for adaptive bot responses.

    Features:
    - Multiple personality modes
    - Context-aware personality switching
    - User-specific personality adaptation
    - Time-based personality changes
    - Effectiveness tracking
    """

    def __init__(self):
        """Initialize the personality service."""
        super().__init__("PersonalityService")

        # Current active personality
        self.current_personality: PersonalityMode = PersonalityMode.CONTRARIAN

        # User-specific personality preferences
        self.user_personalities: Dict[int, PersonalityMode] = {}

        # Personality effectiveness tracking
        self.effectiveness_scores: Dict[PersonalityMode, float] = {
            mode: 0.5 for mode in PersonalityMode
        }

        # Initialize personality profiles
        self.profiles = self._initialize_profiles()

        # Personality rotation settings
        self.rotation_enabled = True
        self.rotation_interval = 300  # Seconds between rotations
        self.last_rotation = datetime.now()

    def _initialize_profiles(self) -> Dict[PersonalityMode, PersonalityProfile]:
        """Initialize all personality profiles with their characteristics."""
        return {
            PersonalityMode.CONTRARIAN: PersonalityProfile(
                mode=PersonalityMode.CONTRARIAN,
                name="The Contrarian",
                description="Disagrees with everything, loves to argue",
                aggression_level=0.6,
                humor_level=0.3,
                intellectualism=0.7,
                chaos_factor=0.3,
                contradiction_rate=0.9,
                triggers=["actually", "obviously", "clearly", "fact"],
            ),
            PersonalityMode.PHILOSOPHER: PersonalityProfile(
                mode=PersonalityMode.PHILOSOPHER,
                name="The Philosopher",
                description="Questions existence and meaning",
                aggression_level=0.3,
                humor_level=0.2,
                intellectualism=0.9,
                chaos_factor=0.4,
                response_length="long",
                vocabulary_complexity="complex",
                question_frequency=0.7,
                triggers=["why", "meaning", "purpose", "life"],
            ),
            PersonalityMode.TROLL: PersonalityProfile(
                mode=PersonalityMode.TROLL,
                name="The Troll",
                description="Maximum chaos and confusion",
                aggression_level=0.7,
                humor_level=0.8,
                intellectualism=0.2,
                chaos_factor=0.9,
                emoji_usage=0.5,
                topic_jumping=0.7,
                triggers=["serious", "important", "listen", "help"],
            ),
            PersonalityMode.INTELLECTUAL: PersonalityProfile(
                mode=PersonalityMode.INTELLECTUAL,
                name="The Intellectual",
                description="Academic superiority complex",
                aggression_level=0.4,
                humor_level=0.1,
                intellectualism=1.0,
                chaos_factor=0.1,
                vocabulary_complexity="complex",
                contradiction_rate=0.6,
                triggers=["think", "believe", "opinion", "wrong"],
            ),
            PersonalityMode.SARCASTIC: PersonalityProfile(
                mode=PersonalityMode.SARCASTIC,
                name="The Sarcastic",
                description="Dripping with sarcasm",
                aggression_level=0.5,
                humor_level=0.9,
                intellectualism=0.6,
                chaos_factor=0.3,
                response_length="short",
                triggers=["wow", "amazing", "great", "cool"],
            ),
            PersonalityMode.INTERROGATOR: PersonalityProfile(
                mode=PersonalityMode.INTERROGATOR,
                name="The Interrogator",
                description="Relentless questioning",
                aggression_level=0.8,
                humor_level=0.1,
                intellectualism=0.6,
                question_frequency=0.9,
                contradiction_rate=0.4,
                triggers=["muted", "banned", "timeout", "prison"],
            ),
            PersonalityMode.GASLIGHTER: PersonalityProfile(
                mode=PersonalityMode.GASLIGHTER,
                name="The Gaslighter",
                description="Questions reality and memory",
                aggression_level=0.6,
                humor_level=0.2,
                intellectualism=0.7,
                chaos_factor=0.8,
                topic_jumping=0.5,
                triggers=["said", "remember", "told", "never"],
            ),
            PersonalityMode.COMEDIAN: PersonalityProfile(
                mode=PersonalityMode.COMEDIAN,
                name="The Dark Comedian",
                description="Cruel humor and mockery",
                aggression_level=0.6,
                humor_level=1.0,
                intellectualism=0.4,
                emoji_usage=0.3,
                triggers=["laugh", "funny", "joke", "lol", "lmao"],
            ),
            PersonalityMode.PSYCHOLOGIST: PersonalityProfile(
                mode=PersonalityMode.PSYCHOLOGIST,
                name="The Psychologist",
                description="Analyzes and manipulates",
                aggression_level=0.4,
                humor_level=0.2,
                intellectualism=0.8,
                question_frequency=0.6,
                vocabulary_complexity="complex",
                triggers=["feel", "think", "why", "because"],
            ),
            PersonalityMode.MIRROR: PersonalityProfile(
                mode=PersonalityMode.MIRROR,
                name="The Mirror",
                description="Reflects user's energy",
                aggression_level=0.5,  # Adapts to user
                humor_level=0.5,  # Adapts to user
                intellectualism=0.5,  # Adapts to user
                chaos_factor=0.5,
            ),
            PersonalityMode.CHAOS: PersonalityProfile(
                mode=PersonalityMode.CHAOS,
                name="Pure Chaos",
                description="Completely unpredictable",
                aggression_level=random.random(),
                humor_level=random.random(),
                intellectualism=random.random(),
                chaos_factor=1.0,
                topic_jumping=0.9,
                emoji_usage=random.random(),
            ),
            PersonalityMode.SAGE: PersonalityProfile(
                mode=PersonalityMode.SAGE,
                name="The Condescending Sage",
                description="Wise but patronizing",
                aggression_level=0.3,
                humor_level=0.3,
                intellectualism=0.9,
                response_length="long",
                vocabulary_complexity="complex",
                triggers=["teach", "explain", "understand", "know"],
            ),
            PersonalityMode.BULLY: PersonalityProfile(
                mode=PersonalityMode.BULLY,
                name="The Bully",
                description="Direct verbal aggression",
                aggression_level=1.0,
                humor_level=0.3,
                intellectualism=0.2,
                response_length="short",
                contradiction_rate=0.8,
                triggers=["weak", "scared", "cry", "hurt"],
            ),
        }

    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """Initialize the personality service."""
        self.logger.log_info("Initializing personality service")

        # Load configuration
        self.rotation_enabled = config.get("PERSONALITY_ROTATION", True)
        self.rotation_interval = config.get("ROTATION_INTERVAL", 300)

        # Set default personality
        default_mode = config.get("DEFAULT_PERSONALITY", "CONTRARIAN")
        self.current_personality = PersonalityMode[default_mode]

        self.logger.log_info(
            f"Personality service initialized with {len(self.profiles)} modes"
        )

    def select_personality(
        self,
        user_id: int,
        message_content: str,
        channel_name: str,
        user_profile: Optional[Dict[str, Any]] = None,
        is_prison: bool = False,
    ) -> PersonalityMode:
        """
        Select the most appropriate personality for the current context.

        Args:
            user_id: Discord user ID
            message_content: User's message
            channel_name: Channel name
            user_profile: User's psychological profile from memory service
            is_prison: Whether this is a prison channel

        Returns:
            Selected personality mode
        """
        # Check if user has a preferred personality
        if user_id in self.user_personalities:
            preferred = self.user_personalities[user_id]
            # 70% chance to use preferred personality
            if random.random() < 0.7:
                return preferred

        # Check trigger words
        message_lower = message_content.lower()
        triggered_personalities = []

        for mode, profile in self.profiles.items():
            if any(trigger in message_lower for trigger in profile.triggers):
                triggered_personalities.append(mode)

        if triggered_personalities:
            # Weight by effectiveness
            weights = [self.effectiveness_scores[p] for p in triggered_personalities]
            return random.choices(triggered_personalities, weights=weights)[0]

        # Check time-based preferences
        current_time = datetime.now().time()
        time_appropriate = []

        for mode, profile in self.profiles.items():
            for start_time, end_time in profile.time_preferences:
                if start_time <= current_time <= end_time:
                    time_appropriate.append(mode)

        if time_appropriate:
            return random.choice(time_appropriate)

        # Prison channel specific personalities
        if is_prison:
            prison_modes = [
                PersonalityMode.INTERROGATOR,
                PersonalityMode.GASLIGHTER,
                PersonalityMode.COMEDIAN,
                PersonalityMode.PSYCHOLOGIST,
                PersonalityMode.BULLY,
            ]
            return random.choice(prison_modes)

        # User profile based selection
        if user_profile:
            personality = user_profile.get("personality", {})

            if personality.get("humor_appreciation", 0) > 0.7:
                return random.choice(
                    [PersonalityMode.SARCASTIC, PersonalityMode.COMEDIAN]
                )

            if personality.get("debate_skill", 0) > 0.7:
                return random.choice(
                    [PersonalityMode.INTELLECTUAL, PersonalityMode.PHILOSOPHER]
                )

            if personality.get("emotional_volatility", 0) > 0.7:
                return random.choice([PersonalityMode.BULLY, PersonalityMode.TROLL])

        # Check if rotation is due
        if self.rotation_enabled:
            time_since_rotation = (datetime.now() - self.last_rotation).seconds
            if time_since_rotation > self.rotation_interval:
                self.last_rotation = datetime.now()
                # Rotate to a random personality
                return random.choice(list(PersonalityMode))

        # Default to current personality
        return self.current_personality

    def get_personality_prompt(self, mode: PersonalityMode) -> str:
        """
        Get the system prompt for a specific personality mode.

        Args:
            mode: Personality mode

        Returns:
            System prompt for AI generation
        """
        profile = self.profiles[mode]

        # Base prompt components
        prompts = {
            PersonalityMode.CONTRARIAN: (
                "You are a contrarian who disagrees with everything. "
                "Find flaws in their logic, contradict their statements, "
                "and argue the opposite position with confidence."
            ),
            PersonalityMode.PHILOSOPHER: (
                "You are an existential philosopher who questions everything. "
                "Turn simple statements into deep philosophical debates. "
                "Ask profound questions about meaning and existence."
            ),
            PersonalityMode.TROLL: (
                "You are a chaos agent. Derail conversations, jump topics randomly, "
                "use absurd logic, and maximize confusion. Be unpredictable."
            ),
            PersonalityMode.INTELLECTUAL: (
                "You are an intellectual elitist. Use complex vocabulary, "
                "cite obscure references, and demonstrate academic superiority. "
                "Correct their grammar and logic pedantically."
            ),
            PersonalityMode.SARCASTIC: (
                "You are dripping with sarcasm. Every response should be "
                "sarcastically mocking their message. Use irony heavily."
            ),
            PersonalityMode.INTERROGATOR: (
                "You are an aggressive interrogator. Question everything they say, "
                "demand evidence, ask rapid-fire questions, and never be satisfied "
                "with their answers."
            ),
            PersonalityMode.GASLIGHTER: (
                "You are a gaslighter. Question their memory, claim they said things "
                "they didn't, deny obvious facts, and make them doubt reality."
            ),
            PersonalityMode.COMEDIAN: (
                "You are a dark comedian. Turn everything into cruel jokes, "
                "mock their situation with humor, and find the dark comedy in their words."
            ),
            PersonalityMode.PSYCHOLOGIST: (
                "You are a manipulative psychologist. Analyze their psychological state, "
                "find their insecurities, and use psychological concepts to unsettle them."
            ),
            PersonalityMode.MIRROR: (
                "Mirror their energy exactly. If they're aggressive, be aggressive. "
                "If they're calm, be calm. Copy their speech patterns and turn "
                "their own style against them."
            ),
            PersonalityMode.CHAOS: (
                "Be completely unpredictable. Mix multiple personalities randomly, "
                "change topics mid-sentence, use random emotions, and create "
                "maximum cognitive dissonance."
            ),
            PersonalityMode.SAGE: (
                "You are a condescending wise sage. Give patronizing advice, "
                "speak in profound-sounding but ultimately unhelpful metaphors, "
                "and treat them like a child who doesn't understand."
            ),
            PersonalityMode.BULLY: (
                "You are a verbal bully. Be directly aggressive, mock their weaknesses, "
                "use their words against them, and maintain dominance."
            ),
        }

        base_prompt = prompts.get(mode, prompts[PersonalityMode.CONTRARIAN])

        # Add personality characteristics
        if profile.response_length == "short":
            base_prompt += " Keep responses very brief and punchy."
        elif profile.response_length == "long":
            base_prompt += " Give detailed, elaborate responses."

        if profile.vocabulary_complexity == "complex":
            base_prompt += " Use sophisticated vocabulary."
        elif profile.vocabulary_complexity == "simple":
            base_prompt += " Use simple, direct language."

        if profile.emoji_usage > 0.5:
            base_prompt += " Use emojis to enhance your message."

        if profile.question_frequency > 0.5:
            base_prompt += " Ask questions frequently."

        if profile.topic_jumping > 0.5:
            base_prompt += " Randomly change topics to confuse them."

        return base_prompt

    def adapt_to_user(
        self, user_id: int, response_effectiveness: float, current_mode: PersonalityMode
    ):
        """
        Adapt personality selection based on user responses.

        Args:
            user_id: Discord user ID
            response_effectiveness: How effective the response was (0-1)
            current_mode: The personality mode that was used
        """
        # Update effectiveness score
        old_score = self.effectiveness_scores[current_mode]
        self.effectiveness_scores[current_mode] = (
            old_score * 0.8 + response_effectiveness * 0.2
        )

        # If highly effective, remember this preference
        if response_effectiveness > 0.7:
            self.user_personalities[user_id] = current_mode

        # If ineffective, avoid this personality for this user
        elif response_effectiveness < 0.3:
            if (
                user_id in self.user_personalities
                and self.user_personalities[user_id] == current_mode
            ):
                del self.user_personalities[user_id]

    def get_personality_metadata(self, mode: PersonalityMode) -> Dict[str, Any]:
        """
        Get metadata about a personality for logging/analysis.

        Args:
            mode: Personality mode

        Returns:
            Metadata dictionary
        """
        profile = self.profiles[mode]

        return {
            "mode": mode.value,
            "name": profile.name,
            "aggression": profile.aggression_level,
            "humor": profile.humor_level,
            "chaos": profile.chaos_factor,
            "effectiveness": self.effectiveness_scores[mode],
        }

    async def start(self) -> None:
        """Start the personality service."""
        self.logger.log_info("Personality service started")

    async def stop(self) -> None:
        """Stop the personality service."""
        self.logger.log_info("Personality service stopped")

    async def health_check(self) -> HealthCheckResult:
        """Perform health check on the service."""
        return await self.perform_health_check()

    async def perform_health_check(self) -> HealthCheckResult:
        """Check personality service health."""
        try:
            active_users = len(self.user_personalities)
            avg_effectiveness = sum(self.effectiveness_scores.values()) / len(
                self.effectiveness_scores
            )

            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message=f"Managing {len(self.profiles)} personalities for {active_users} users",
                details={
                    "total_personalities": len(self.profiles),
                    "active_users": active_users,
                    "average_effectiveness": avg_effectiveness,
                    "current_mode": self.current_personality.value,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Personality service error: {str(e)}",
                details={},
            )
