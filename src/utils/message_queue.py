"""
Message Queue System for AzabBot
=================================

Batch processing system for handling torture messages efficiently.
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
import time
from src.core.logger import get_logger

@dataclass
class QueuedMessage:
    """Represents a queued torture message."""
    user_id: int
    message: str
    priority: int = 0  # Higher priority = processed first
    timestamp: float = field(default_factory=time.time)
    retries: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

class MessageQueue:
    """Centralized message queue for batch processing."""
    
    def __init__(self, batch_size: int = 10, batch_interval: float = 1.0):
        """
        Initialize message queue.
        
        Args:
            batch_size: Maximum messages to process in one batch
            batch_interval: Seconds between batch processing
        """
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.queue: List[QueuedMessage] = []
        self.processing = False
        self.logger = get_logger()
        self._lock = asyncio.Lock()
        self._process_task: Optional[asyncio.Task] = None
        self._processor: Optional[Callable] = None
        
        # Statistics
        self.stats = {
            "messages_queued": 0,
            "messages_processed": 0,
            "messages_failed": 0,
            "batches_processed": 0,
            "avg_batch_time": 0.0
        }
    
    async def start(self, processor: Callable):
        """
        Start the queue processor.
        
        Args:
            processor: Async function to process batches
        """
        self._processor = processor
        self._process_task = asyncio.create_task(self._process_loop())
        self.logger.log_info("Message queue started")
    
    async def stop(self):
        """Stop the queue processor."""
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
        
        # Process remaining messages
        if self.queue:
            await self._process_batch()
        
        self.logger.log_info(
            "Message queue stopped"
        )
    
    async def add(self, message: QueuedMessage):
        """Add message to queue."""
        async with self._lock:
            self.queue.append(message)
            self.stats["messages_queued"] += 1
            
            # Sort by priority (higher first) then timestamp (older first)
            self.queue.sort(
                key=lambda m: (-m.priority, m.timestamp)
            )
            
            self.logger.log_debug(
                f"Message queued for user {message.user_id}"
            )
    
    async def _process_loop(self):
        """Main processing loop."""
        while True:
            try:
                await asyncio.sleep(self.batch_interval)
                
                if self.queue:
                    await self._process_batch()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Error in queue processing: {e}")
    
    async def _process_batch(self):
        """Process a batch of messages."""
        async with self._lock:
            if not self.queue or not self._processor:
                return
            
            # Get batch
            batch = self.queue[:self.batch_size]
            self.queue = self.queue[self.batch_size:]
            
        if not batch:
            return
        
        start_time = time.perf_counter()
        
        try:
            # Process batch
            self.logger.log_debug(
                f"Processing batch of {len(batch)} messages"
            )
            
            results = await self._processor(batch)
            
            # Handle failed messages
            for i, (msg, success) in enumerate(zip(batch, results)):
                if success:
                    self.stats["messages_processed"] += 1
                else:
                    msg.retries += 1
                    if msg.retries < msg.max_retries:
                        # Re-queue with lower priority
                        msg.priority = max(0, msg.priority - 1)
                        await self.add(msg)
                        self.logger.log_debug(
                            f"Re-queued message for user {msg.user_id} (retry {msg.retries})"
                        )
                    else:
                        self.stats["messages_failed"] += 1
                        self.logger.log_error(
                            f"Message for user {msg.user_id} failed after {msg.max_retries} retries"
                        )
            
            # Update statistics
            elapsed = time.perf_counter() - start_time
            self.stats["batches_processed"] += 1
            
            # Update rolling average
            avg = self.stats["avg_batch_time"]
            self.stats["avg_batch_time"] = (
                (avg * (self.stats["batches_processed"] - 1) + elapsed) /
                self.stats["batches_processed"]
            )
            
            self.logger.log_debug(
                f"Batch processed in {elapsed:.2f}s"
            )
            
        except Exception as e:
            self.logger.log_error(f"Batch processing failed: {e}")
            
            # Re-queue all messages
            async with self._lock:
                for msg in batch:
                    msg.retries += 1
                    if msg.retries < msg.max_retries:
                        self.queue.append(msg)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            **self.stats,
            "current_queue_size": len(self.queue),
            "oldest_message_age": (
                time.time() - min(m.timestamp for m in self.queue)
                if self.queue else 0
            )
        }
    
    async def clear(self):
        """Clear the queue."""
        async with self._lock:
            cleared = len(self.queue)
            self.queue.clear()
            self.logger.log_info(f"Cleared {cleared} messages from queue")
            return cleared

class PriorityMessageQueue(MessageQueue):
    """Extended queue with priority lanes."""
    
    def __init__(self, batch_size: int = 10, batch_interval: float = 1.0):
        """Initialize priority queue."""
        super().__init__(batch_size, batch_interval)
        
        # Priority lanes
        self.high_priority: List[QueuedMessage] = []
        self.normal_priority: List[QueuedMessage] = []
        self.low_priority: List[QueuedMessage] = []
    
    async def add(self, message: QueuedMessage):
        """Add message to appropriate priority lane."""
        async with self._lock:
            if message.priority >= 7:
                self.high_priority.append(message)
            elif message.priority >= 4:
                self.normal_priority.append(message)
            else:
                self.low_priority.append(message)
            
            self.stats["messages_queued"] += 1
            
            self.logger.log_debug(
                f"Message queued in {'high' if message.priority >= 7 else 'normal' if message.priority >= 4 else 'low'} priority lane"
            )
    
    async def _get_batch(self) -> List[QueuedMessage]:
        """Get next batch respecting priorities."""
        batch = []
        
        # Process high priority first
        while self.high_priority and len(batch) < self.batch_size:
            batch.append(self.high_priority.pop(0))
        
        # Then normal priority
        while self.normal_priority and len(batch) < self.batch_size:
            batch.append(self.normal_priority.pop(0))
        
        # Finally low priority
        while self.low_priority and len(batch) < self.batch_size:
            batch.append(self.low_priority.pop(0))
        
        return batch
    
    async def _process_batch(self):
        """Process a batch from priority lanes."""
        async with self._lock:
            if not self._processor:
                return
            
            batch = await self._get_batch()
        
        if not batch:
            return
        
        # Process batch (reuse parent implementation)
        await super()._process_batch()