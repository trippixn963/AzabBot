"""
Memory Optimization for AzabBot
================================

Monitors and optimizes memory usage.
"""

import gc
import asyncio
import psutil
import sys
import weakref
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import tracemalloc
from src.core.logger import get_logger

class MemoryOptimizer:
    """Optimizes and monitors memory usage."""
    
    def __init__(self, threshold_mb: int = 500):
        """
        Initialize memory optimizer.
        
        Args:
            threshold_mb: Memory threshold in MB to trigger cleanup
        """
        self.threshold_bytes = threshold_mb * 1024 * 1024
        self.logger = get_logger()
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None
        
        # Track large objects
        self.large_objects: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
        
        # Memory statistics
        self.stats = {
            "peak_memory_mb": 0,
            "cleanups_triggered": 0,
            "objects_freed": 0,
            "last_cleanup": None
        }
        
        # Start tracemalloc for detailed tracking
        if not tracemalloc.is_tracing():
            tracemalloc.start()
    
    async def start(self, check_interval: int = 60):
        """
        Start memory monitoring.
        
        Args:
            check_interval: Seconds between memory checks
        """
        self.monitoring = True
        self.monitor_task = asyncio.create_task(
            self._monitor_loop(check_interval)
        )
        
        # Initial memory snapshot
        snapshot = self._get_memory_info()
        self.logger.log_info(
            f"Memory optimizer started (RSS: {snapshot['rss_mb']:.1f}MB)"
        )
    
    async def stop(self):
        """Stop memory monitoring."""
        self.monitoring = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # Final cleanup
        await self.optimize()
        
        self.logger.log_info(
            f"Memory optimizer stopped (cleanups: {self.stats['cleanups_triggered']}, freed: {self.stats['objects_freed']} objects)"
        )
    
    async def _monitor_loop(self, interval: int):
        """Monitor memory usage periodically."""
        while self.monitoring:
            try:
                await asyncio.sleep(interval)
                
                memory_info = self._get_memory_info()
                
                # Update peak memory
                current_mb = memory_info["rss_mb"]
                if current_mb > self.stats["peak_memory_mb"]:
                    self.stats["peak_memory_mb"] = current_mb
                
                # Check if cleanup needed
                if memory_info["rss_bytes"] > self.threshold_bytes:
                    self.logger.log_warning(
                        f"Memory threshold exceeded: {current_mb:.1f}MB",
                        context=memory_info
                    )
                    await self.optimize()
                
                # Log if memory is high
                if current_mb > self.threshold_bytes / 1024 / 1024 * 0.8:
                    self.logger.log_debug(
                        f"Memory usage high: {current_mb:.1f}MB",
                        context=memory_info
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Memory monitor error: {e}")
    
    async def optimize(self) -> Dict[str, Any]:
        """
        Perform memory optimization.
        
        Returns:
            Optimization results
        """
        self.logger.log_debug("Starting memory optimization")
        
        before = self._get_memory_info()
        freed_objects = 0
        
        try:
            # Clear caches
            freed_objects += self._clear_caches()
            
            # Clean up large objects
            freed_objects += self._cleanup_large_objects()
            
            # Force garbage collection
            gc.collect()
            gc.collect()  # Second pass for cyclic references
            gc.collect(2)  # Collect oldest generation
            
            # Clear frame locals in traceback
            self._clear_frames()
            
            after = self._get_memory_info()
            
            freed_mb = (before["rss_bytes"] - after["rss_bytes"]) / 1024 / 1024
            
            # Update statistics
            self.stats["cleanups_triggered"] += 1
            self.stats["objects_freed"] += freed_objects
            self.stats["last_cleanup"] = datetime.now().isoformat()
            
            result = {
                "freed_mb": freed_mb,
                "freed_objects": freed_objects,
                "before_mb": before["rss_mb"],
                "after_mb": after["rss_mb"],
                "gc_stats": gc.get_stats()
            }
            
            if freed_mb > 0:
                self.logger.log_info(
                    f"Memory optimized: freed {freed_mb:.1f}MB (before: {result['before_mb']:.1f}MB, after: {result['after_mb']:.1f}MB)"
                )
            
            return result
            
        except Exception as e:
            self.logger.log_error(f"Optimization error: {e}")
            return {"error": str(e)}
    
    def _get_memory_info(self) -> Dict[str, Any]:
        """Get current memory information."""
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss_bytes": memory_info.rss,
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
            "percent": process.memory_percent(),
            "available_mb": psutil.virtual_memory().available / 1024 / 1024
        }
    
    def _clear_caches(self) -> int:
        """Clear various caches."""
        cleared = 0
        
        # Clear functools caches
        import functools
        if hasattr(functools, "lru_cache"):
            for obj in gc.get_objects():
                if hasattr(obj, "cache_clear"):
                    try:
                        obj.cache_clear()
                        cleared += 1
                    except:
                        pass
        
        # Clear module caches
        sys.modules.clear()
        cleared += 1
        
        return cleared
    
    def _cleanup_large_objects(self) -> int:
        """Clean up tracked large objects."""
        cleaned = 0
        
        # Remove dead references
        dead_keys = []
        for key in list(self.large_objects.keys()):
            if key not in self.large_objects:
                dead_keys.append(key)
        
        cleaned = len(dead_keys)
        
        return cleaned
    
    def _clear_frames(self):
        """Clear frame locals to free memory."""
        for obj in gc.get_objects():
            if isinstance(obj, type(sys._getframe())):
                obj.clear()
    
    def track_large_object(self, name: str, obj: Any):
        """
        Track a large object for monitoring.
        
        Args:
            name: Identifier for the object
            obj: The object to track
        """
        self.large_objects[name] = obj
        
        size_mb = sys.getsizeof(obj) / 1024 / 1024
        if size_mb > 1:
            self.logger.log_debug(
                f"Tracking large object: {name} ({size_mb:.1f}MB)"
            )
    
    def get_memory_snapshot(self) -> List[tuple]:
        """Get detailed memory snapshot."""
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")
        
        return [
            {
                "file": stat.traceback.format()[0] if stat.traceback else "unknown",
                "size_mb": stat.size / 1024 / 1024,
                "count": stat.count
            }
            for stat in top_stats[:10]
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimizer statistics."""
        return {
            **self.stats,
            "current_memory": self._get_memory_info(),
            "gc_stats": gc.get_stats()[0] if gc.get_stats() else {},
            "tracked_objects": len(self.large_objects)
        }

class MemoryLeakDetector:
    """Detects potential memory leaks."""
    
    def __init__(self):
        """Initialize leak detector."""
        self.logger = get_logger()
        self.baseline: Optional[Dict] = None
        self.snapshots: List[Dict] = []
        self.max_snapshots = 10
    
    def take_snapshot(self) -> Dict[str, Any]:
        """Take a memory snapshot."""
        snapshot = {
            "timestamp": datetime.now(),
            "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024,
            "object_counts": self._count_objects()
        }
        
        self.snapshots.append(snapshot)
        
        # Keep only recent snapshots
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots.pop(0)
        
        return snapshot
    
    def _count_objects(self) -> Dict[str, int]:
        """Count objects by type."""
        counts = {}
        
        for obj in gc.get_objects():
            obj_type = type(obj).__name__
            counts[obj_type] = counts.get(obj_type, 0) + 1
        
        # Return top 20 types
        sorted_counts = sorted(
            counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        return dict(sorted_counts[:20])
    
    def detect_leaks(self) -> List[str]:
        """
        Detect potential memory leaks.
        
        Returns:
            List of potential leak warnings
        """
        if len(self.snapshots) < 3:
            return []
        
        warnings = []
        
        # Check for continuous memory growth
        memory_values = [s["memory_mb"] for s in self.snapshots[-5:]]
        if all(memory_values[i] <= memory_values[i+1] 
               for i in range(len(memory_values)-1)):
            growth = memory_values[-1] - memory_values[0]
            if growth > 50:  # 50MB growth
                warnings.append(
                    f"Continuous memory growth detected: +{growth:.1f}MB"
                )
        
        # Check for growing object counts
        if len(self.snapshots) >= 2:
            old_counts = self.snapshots[-5]["object_counts"]
            new_counts = self.snapshots[-1]["object_counts"]
            
            for obj_type, new_count in new_counts.items():
                old_count = old_counts.get(obj_type, 0)
                if new_count > old_count * 1.5 and new_count > 1000:
                    warnings.append(
                        f"Object leak suspected: {obj_type} "
                        f"({old_count} -> {new_count})"
                    )
        
        return warnings

# Global memory optimizer instance
_memory_optimizer = MemoryOptimizer()

def get_memory_optimizer() -> MemoryOptimizer:
    """Get global memory optimizer."""
    return _memory_optimizer