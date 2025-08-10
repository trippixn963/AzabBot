# =============================================================================
# SaydnayaBot - Conversation Memory Service
# =============================================================================
# Provides persistent memory of user interactions, enabling the bot to
# remember previous conversations, track user patterns, and build profiles
# for more effective responses.
# =============================================================================

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
import hashlib

from src.services.base_service import BaseService, ServiceStatus, HealthCheckResult
from src.core.logger import get_logger


@dataclass
class UserMemory:
    """Stores memory about a specific user."""
    user_id: int
    username: str
    total_interactions: int = 0
    last_seen: Optional[datetime] = None
    personality_profile: Dict[str, Any] = None
    trigger_words: List[str] = None
    response_effectiveness: Dict[str, float] = None  # Track what works
    conversation_topics: List[str] = None
    emotional_state_history: List[str] = None
    debate_wins: int = 0
    debate_losses: int = 0
    ignored_responses: int = 0
    
    def __post_init__(self):
        if self.personality_profile is None:
            self.personality_profile = {
                "aggression_tolerance": 0.5,
                "humor_appreciation": 0.5,
                "debate_skill": 0.5,
                "emotional_volatility": 0.5,
                "attention_seeking": 0.5
            }
        if self.trigger_words is None:
            self.trigger_words = []
        if self.response_effectiveness is None:
            self.response_effectiveness = {}
        if self.conversation_topics is None:
            self.conversation_topics = []
        if self.emotional_state_history is None:
            self.emotional_state_history = []


@dataclass
class ConversationContext:
    """Stores context about ongoing conversations."""
    channel_id: int
    message_history: List[Dict[str, Any]]  # Last 20 messages
    current_topic: Optional[str] = None
    participant_dynamics: Dict[int, str] = None  # user_id -> role
    escalation_level: int = 0  # 0-10 scale
    last_bot_message: Optional[str] = None
    last_bot_strategy: Optional[str] = None
    
    def __post_init__(self):
        if self.participant_dynamics is None:
            self.participant_dynamics = {}


class MemoryService(BaseService):
    """
    Advanced memory system for tracking user interactions and conversations.
    
    Features:
    - User profile building
    - Conversation context tracking
    - Pattern recognition
    - Effectiveness tracking
    - Personality adaptation
    """
    
    def __init__(self):
        """Initialize the memory service."""
        super().__init__("MemoryService")
        # Create data directory if it doesn't exist
        from pathlib import Path
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        self.db_path = data_dir / "memory.db"
        self.connection = None
        
        # In-memory caches for fast access
        self.user_memories: Dict[int, UserMemory] = {}
        self.conversation_contexts: Dict[int, ConversationContext] = {}
        self.short_term_memory: Dict[int, List[str]] = defaultdict(list)  # Last 10 messages per user
        
    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """Initialize the memory service and database."""
        self.logger.log_info("Initializing memory service")
        
        # Create database connection
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        
        # Create tables
        self._create_tables()
        
        # Load existing memories
        self._load_memories()
        
        self.logger.log_info("Memory service initialized")
        
    def _create_tables(self):
        """Create database tables for persistent storage."""
        cursor = self.connection.cursor()
        
        # User memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                total_interactions INTEGER DEFAULT 0,
                last_seen TIMESTAMP,
                personality_profile TEXT,
                trigger_words TEXT,
                response_effectiveness TEXT,
                conversation_topics TEXT,
                emotional_states TEXT,
                debate_wins INTEGER DEFAULT 0,
                debate_losses INTEGER DEFAULT 0,
                ignored_responses INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Conversation history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                message_content TEXT,
                bot_response TEXT,
                response_strategy TEXT,
                effectiveness_score REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES user_memories (user_id)
            )
        """)
        
        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_timestamp ON conversation_history(user_id, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_channel_timestamp ON conversation_history(channel_id, timestamp)")
        
        self.connection.commit()
        
    def _load_memories(self):
        """Load existing memories from database."""
        cursor = self.connection.cursor()
        
        # Load user memories
        cursor.execute("SELECT * FROM user_memories")
        for row in cursor.fetchall():
            user_memory = UserMemory(
                user_id=row['user_id'],
                username=row['username'],
                total_interactions=row['total_interactions'],
                last_seen=datetime.fromisoformat(row['last_seen']) if row['last_seen'] else None,
                personality_profile=json.loads(row['personality_profile']) if row['personality_profile'] else None,
                trigger_words=json.loads(row['trigger_words']) if row['trigger_words'] else None,
                response_effectiveness=json.loads(row['response_effectiveness']) if row['response_effectiveness'] else None,
                conversation_topics=json.loads(row['conversation_topics']) if row['conversation_topics'] else None,
                emotional_state_history=json.loads(row['emotional_states']) if row['emotional_states'] else None,
                debate_wins=row['debate_wins'],
                debate_losses=row['debate_losses'],
                ignored_responses=row['ignored_responses']
            )
            self.user_memories[row['user_id']] = user_memory
            
    def remember_user_interaction(self, user_id: int, username: str, message: str, 
                                 channel_id: int, bot_response: str = None,
                                 strategy: str = None) -> UserMemory:
        """
        Record a user interaction and update their profile.
        
        Args:
            user_id: Discord user ID
            username: User's display name
            message: User's message content
            channel_id: Channel where interaction occurred
            bot_response: Bot's response if any
            strategy: Strategy used for response
            
        Returns:
            Updated UserMemory object
        """
        # Get or create user memory
        if user_id not in self.user_memories:
            self.user_memories[user_id] = UserMemory(user_id=user_id, username=username)
            
        memory = self.user_memories[user_id]
        
        # Update basic stats
        memory.total_interactions += 1
        memory.last_seen = datetime.now()
        memory.username = username  # Update in case it changed
        
        # Add to short-term memory
        self.short_term_memory[user_id].append(message)
        if len(self.short_term_memory[user_id]) > 10:
            self.short_term_memory[user_id].pop(0)
            
        # Analyze message for patterns
        self._analyze_message_patterns(memory, message)
        
        # Save to database
        self._save_user_memory(memory)
        self._save_conversation_history(user_id, channel_id, message, bot_response, strategy)
        
        return memory
        
    def _analyze_message_patterns(self, memory: UserMemory, message: str):
        """Analyze message for patterns and update user profile."""
        message_lower = message.lower()
        
        # Detect emotional indicators
        if any(word in message_lower for word in ['angry', 'mad', 'pissed', 'fuck', 'shit']):
            memory.personality_profile["emotional_volatility"] = min(1.0, 
                memory.personality_profile["emotional_volatility"] + 0.05)
                
        if any(word in message_lower for word in ['lol', 'haha', 'lmao', '😂', '🤣']):
            memory.personality_profile["humor_appreciation"] = min(1.0,
                memory.personality_profile["humor_appreciation"] + 0.05)
                
        # Detect debate engagement
        if any(word in message_lower for word in ['actually', 'wrong', 'prove', 'source', 'evidence']):
            memory.personality_profile["debate_skill"] = min(1.0,
                memory.personality_profile["debate_skill"] + 0.03)
                
        # Detect attention seeking
        if len(message) > 200 or message.isupper():
            memory.personality_profile["attention_seeking"] = min(1.0,
                memory.personality_profile["attention_seeking"] + 0.04)
                
    def get_user_context(self, user_id: int) -> Dict[str, Any]:
        """
        Get comprehensive context about a user for AI response generation.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            Dictionary with user context information
        """
        if user_id not in self.user_memories:
            return {
                "is_new_user": True,
                "interactions": 0,
                "personality": "unknown",
                "suggested_approach": "exploratory"
            }
            
        memory = self.user_memories[user_id]
        
        # Determine suggested approach based on personality
        personality = memory.personality_profile
        if personality["emotional_volatility"] > 0.7:
            approach = "calculated_provocation"
        elif personality["humor_appreciation"] > 0.7:
            approach = "sarcastic_humor"
        elif personality["debate_skill"] > 0.7:
            approach = "intellectual_challenge"
        elif personality["attention_seeking"] > 0.7:
            approach = "dismissive_superiority"
        else:
            approach = "adaptive_testing"
            
        return {
            "is_new_user": False,
            "interactions": memory.total_interactions,
            "personality": personality,
            "recent_messages": self.short_term_memory.get(user_id, []),
            "trigger_words": memory.trigger_words,
            "suggested_approach": approach,
            "debate_record": f"{memory.debate_wins}W-{memory.debate_losses}L",
            "last_seen": memory.last_seen.isoformat() if memory.last_seen else None
        }
        
    def get_conversation_context(self, channel_id: int) -> Dict[str, Any]:
        """
        Get context about the current conversation in a channel.
        
        Args:
            channel_id: Discord channel ID
            
        Returns:
            Dictionary with conversation context
        """
        if channel_id not in self.conversation_contexts:
            self.conversation_contexts[channel_id] = ConversationContext(
                channel_id=channel_id,
                message_history=[]
            )
            
        context = self.conversation_contexts[channel_id]
        
        return {
            "current_topic": context.current_topic,
            "escalation_level": context.escalation_level,
            "last_bot_message": context.last_bot_message,
            "last_strategy": context.last_bot_strategy,
            "participant_dynamics": context.participant_dynamics,
            "recent_messages": context.message_history[-5:] if context.message_history else []
        }
        
    def update_response_effectiveness(self, user_id: int, strategy: str, 
                                     effectiveness: float):
        """
        Update how effective a response strategy was for a user.
        
        Args:
            user_id: Discord user ID
            strategy: Strategy that was used
            effectiveness: Score from 0-1 (1 being most effective)
        """
        if user_id in self.user_memories:
            memory = self.user_memories[user_id]
            
            # Update effectiveness tracking
            if strategy not in memory.response_effectiveness:
                memory.response_effectiveness[strategy] = effectiveness
            else:
                # Weighted average with more weight on recent
                old = memory.response_effectiveness[strategy]
                memory.response_effectiveness[strategy] = (old * 0.7) + (effectiveness * 0.3)
                
            # Update debate record based on effectiveness
            if effectiveness > 0.7:
                memory.debate_wins += 1
            elif effectiveness < 0.3:
                memory.debate_losses += 1
            elif effectiveness < 0.1:
                memory.ignored_responses += 1
                
            self._save_user_memory(memory)
            
    def _save_user_memory(self, memory: UserMemory):
        """Save user memory to database."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO user_memories 
            (user_id, username, total_interactions, last_seen, personality_profile,
             trigger_words, response_effectiveness, conversation_topics, emotional_states,
             debate_wins, debate_losses, ignored_responses, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            memory.user_id,
            memory.username,
            memory.total_interactions,
            memory.last_seen.isoformat() if memory.last_seen else None,
            json.dumps(memory.personality_profile),
            json.dumps(memory.trigger_words),
            json.dumps(memory.response_effectiveness),
            json.dumps(memory.conversation_topics),
            json.dumps(memory.emotional_state_history),
            memory.debate_wins,
            memory.debate_losses,
            memory.ignored_responses
        ))
        
        self.connection.commit()
        
    def _save_conversation_history(self, user_id: int, channel_id: int, 
                                  message: str, bot_response: str, strategy: str):
        """Save conversation to history."""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            INSERT INTO conversation_history 
            (user_id, channel_id, message_content, bot_response, response_strategy)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, channel_id, message, bot_response, strategy))
        
        self.connection.commit()
        
    async def cleanup(self) -> None:
        """Clean up old memories and optimize database."""
        cursor = self.connection.cursor()
        
        # Delete old conversation history (older than 30 days)
        cutoff = datetime.now() - timedelta(days=30)
        cursor.execute("""
            DELETE FROM conversation_history 
            WHERE timestamp < ?
        """, (cutoff.isoformat(),))
        
        # Optimize database
        cursor.execute("VACUUM")
        
        self.connection.commit()
        
    async def start(self) -> None:
        """Start the memory service."""
        self.logger.log_info("Memory service started")
        
    async def stop(self) -> None:
        """Stop the memory service."""
        if self.connection:
            self.connection.close()
        self.logger.log_info("Memory service stopped")
        
    async def health_check(self) -> HealthCheckResult:
        """Perform health check on the service."""
        return await self.perform_health_check()
    
    async def perform_health_check(self) -> HealthCheckResult:
        """Check memory service health."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM user_memories")
            user_count = cursor.fetchone()[0]
            
            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message=f"Tracking {user_count} users, {len(self.short_term_memory)} active",
                metrics={
                    "total_users": user_count,
                    "active_users": len(self.short_term_memory),
                    "cache_size": len(self.user_memories)
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Database error: {str(e)}",
                metrics={}
            )