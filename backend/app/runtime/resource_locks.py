"""
Resource Lock Manager — Concurrency and mutual exclusion for shared OS/Browser/Hardware resources.
Prevents concurrent agents from colliding on mouse/keyboard, active browser sessions, or filesystem workspaces.
"""
import asyncio
import logging
from typing import Dict, Optional, Set
from contextlib import asynccontextmanager
from enum import Enum

logger = logging.getLogger(__name__)


class ResourceScope(str, Enum):
    SCREEN_INPUT = "SCREEN_INPUT"        # Mouse & Keyboard (PyAutoGUI)
    ACTIVE_BROWSER = "ACTIVE_BROWSER"    # Playwright active tab/window
    DEV_SERVER = "DEV_SERVER"            # Local dev ports / background processes
    MODEL_GPU = "MODEL_GPU"              # VRAM/Ollama heavy inference


class ResourceLockManager:
    """
    Asynchronous lock broker for managing named hardware and logical resource scopes.
    """

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._holders: Dict[str, str] = {}  # scope -> task_id

    def _get_lock(self, scope: str) -> asyncio.Lock:
        if scope not in self._locks:
            self._locks[scope] = asyncio.Lock()
        return self._locks[scope]

    @asynccontextmanager
    async def acquire_lock(self, scope: str, task_id: str, timeout: float = 30.0):
        """
        Asynchronously acquire lock with timeout and automatic release on context exit.
        """
        lock = self._get_lock(scope)
        logger.debug(f"[ResourceLock] Task '{task_id}' requesting lock for '{scope}'...")
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            self._holders[scope] = task_id
            logger.info(f"[ResourceLock] 🔒 Task '{task_id}' ACQUIRED lock '{scope}'")
            yield
        except asyncio.TimeoutError:
            holder = self._holders.get(scope, "unknown")
            logger.warning(f"[ResourceLock] ⏱️ Timeout acquiring lock '{scope}' for task '{task_id}' (Held by '{holder}')")
            raise TimeoutError(f"Could not acquire resource lock '{scope}', currently held by '{holder}'")
        finally:
            if lock.locked() and self._holders.get(scope) == task_id:
                self._holders.pop(scope, None)
                lock.release()
                logger.info(f"[ResourceLock] 🔓 Task '{task_id}' RELEASED lock '{scope}'")

    def is_locked(self, scope: str) -> bool:
        """Check if a resource scope is currently locked."""
        lock = self._locks.get(scope)
        return lock.locked() if lock else False

    def get_lock_status(self) -> Dict[str, Any]:
        return {
            scope: {
                "locked": lock.locked(),
                "holder": self._holders.get(scope)
            }
            for scope, lock in self._locks.items()
        }


# Singleton instance
resource_lock_manager = ResourceLockManager()
