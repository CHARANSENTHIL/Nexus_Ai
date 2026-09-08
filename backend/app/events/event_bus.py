"""
Redis Streams Event Bus for Nexus AI.
Supports Redis Streams with Consumer Groups and graceful In-Memory fallback for standalone/local tests.
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional
import redis.asyncio as aioredis

from app.config import settings
from app.events.event_models import EventType, NexusEvent

logger = logging.getLogger(__name__)


class RedisEventBus:
    """
    Central Pub/Sub Event Bus backed by Redis Streams with consumer groups.
    Includes in-memory message queue fallback when Redis is offline.
    """

    STREAM_MAP = {
        EventType.TASK_CREATED: "task_events",
        EventType.TASK_CLASSIFIED: "task_events",
        EventType.TASK_COMPLETED: "task_events",
        EventType.TASK_FAILED: "task_events",
        EventType.ACTION_REQUESTED: "action_events",
        EventType.ACTION_APPROVED: "action_events",
        EventType.ACTION_BLOCKED: "security_events",
        EventType.APPROVAL_REQUIRED: "security_events",
        EventType.ACTION_COMPLETED: "action_events",
        EventType.ACTION_FAILED: "action_events",
        EventType.VERIFICATION_PASSED: "vision_events",
        EventType.VERIFICATION_FAILED: "vision_events",
        EventType.SCREEN_CAPTURED: "vision_events",
        EventType.SCREEN_VERIFIED: "vision_events",
        EventType.RECOVERY_STARTED: "recovery_events",
        EventType.RECOVERY_SUCCEEDED: "recovery_events",
        EventType.RECOVERY_FAILED: "recovery_events",
        EventType.SYSTEM_HEALTH_CHECK: "system_events",
        EventType.ANOMALY_DETECTED: "system_events",
    }

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[aioredis.Redis] = None
        self._in_memory_group_queues: Dict[tuple, asyncio.Queue] = {}
        self._timeline_store: Dict[str, List[NexusEvent]] = {}
        self._is_redis_available = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Connect to Redis and create consumer groups."""
        try:
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3.0,
                socket_timeout=None,
            )

            await self._redis.ping()
            self._is_redis_available = True
            logger.info(f"[EventBus] Connected to Redis Streams at {self.redis_url}")
            return True
        except Exception as e:
            self._is_redis_available = False
            logger.warning(f"[EventBus] Redis unavailable ({e}). Using In-Memory Event Bus with Consumer Group isolation.")
            return False

    @property
    def is_connected(self) -> bool:
        return self._is_redis_available and self._redis is not None

    def _get_stream_for_event(self, event_type: EventType) -> str:
        return self.STREAM_MAP.get(event_type, "task_events")

    async def publish(self, event: NexusEvent) -> str:
        """
        Publish an event to the appropriate Redis Stream and record in timeline.
        """
        stream_name = self._get_stream_for_event(event.event_type)

        # Store in task timeline
        async with self._lock:
            if event.task_id not in self._timeline_store:
                self._timeline_store[event.task_id] = []
            self._timeline_store[event.task_id].append(event)

        logger.info(
            f"[EventBus] 📢 {event.event_type.value} | task={event.task_id} | src={event.source_agent}"
        )

        event_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "task_id": event.task_id,
            "user_id": event.user_id,
            "timestamp": str(event.timestamp),
            "source_agent": event.source_agent,
            "payload": json.dumps(event.payload),
        }

        if self.is_connected:
            try:
                # XADD with auto-trimming (max 10,000 entries)
                msg_id = await self._redis.xadd(
                    name=stream_name,
                    fields=event_data,
                    maxlen=10000,
                    approximate=True,
                )
                return str(msg_id)
            except Exception as e:
                logger.warning(f"[EventBus] Redis XADD failed ({e}), falling back to in-memory.")

        # In-Memory Group Isolation Dispatch: Broadcast to all consumer groups registered on this stream
        async with self._lock:
            for (s_name, g_name), q in list(self._in_memory_group_queues.items()):
                if s_name == stream_name:
                    await q.put(event)

        return event.event_id

    async def ensure_group(self, stream_name: str, group_name: str):
        """Create consumer group if it doesn't already exist."""
        if not self.is_connected:
            return
        try:
            await self._redis.xgroup_create(
                name=stream_name,
                groupname=group_name,
                id="0",
                mkstream=True,
            )
        except Exception as e:
            # BUSYGROUP Consumer Group name already exists
            if "BUSYGROUP" not in str(e):
                logger.debug(f"[EventBus] Group creation note: {e}")

    async def listen_stream(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        target_event_types: List[EventType],
        callback: Callable[[NexusEvent], Any],
        stop_event: Optional[asyncio.Event] = None,
        poll_interval: float = 0.05,
    ):
        """
        Continuous stream listener loop with consumer group load-balancing.
        """
        await self.ensure_group(stream_name, group_name)
        target_type_values = {et.value for et in target_event_types}

        # Ensure in-memory group queue is registered
        group_key = (stream_name, group_name)
        async with self._lock:
            if group_key not in self._in_memory_group_queues:
                self._in_memory_group_queues[group_key] = asyncio.Queue()

        while stop_event is None or not stop_event.is_set():
            try:
                if self.is_connected:
                    # Read from Redis Consumer Group with auto-recovery
                    try:
                        entries = await self._redis.xreadgroup(
                            groupname=group_name,
                            consumername=consumer_name,
                            streams={stream_name: ">"},
                            count=10,
                            block=int(poll_interval * 1000),
                        )
                    except Exception as xrg_err:
                        err_str = str(xrg_err).lower()
                        if "nogroup" in err_str:
                            await self.ensure_group(stream_name, group_name)
                            await asyncio.sleep(0.5)
                            continue
                        elif "timeout" in err_str:
                            # Idle polling timeout is normal on empty stream
                            continue
                        raise xrg_err


                    if entries:
                        for stream, msg_list in entries:
                            for msg_id, fields in msg_list:
                                try:
                                    event = NexusEvent.from_dict(fields)
                                    if event.event_type.value in target_type_values:
                                        await callback(event)
                                    # Acknowledge processed message
                                    await self._redis.xack(stream_name, group_name, msg_id)
                                except Exception as proc_err:
                                    logger.error(f"[EventBus] Error processing stream msg {msg_id}: {proc_err}")
                else:
                    # In-Memory Consumer Group Queue polling
                    q = self._in_memory_group_queues.get(group_key)
                    if q:
                        try:
                            event = await asyncio.wait_for(q.get(), timeout=poll_interval)
                            if event.event_type.value in target_type_values:
                                await callback(event)
                            q.task_done()
                        except asyncio.TimeoutError:
                            pass
                    else:
                        await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error(f"[EventBus] Listener loop error on {stream_name}: {loop_err}")
                await asyncio.sleep(1.0)


    async def get_task_timeline(self, task_id: str) -> List[NexusEvent]:
        """Get the full chronological event timeline for a specific task."""
        async with self._lock:
            return list(self._timeline_store.get(task_id, []))


# Global singleton instance
event_bus = RedisEventBus()
