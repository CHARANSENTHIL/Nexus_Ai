"""
Base Agent Worker Class for Event-Driven Micro-Agents.
"""
from abc import ABC, abstractmethod
import asyncio
import logging
from typing import List, Optional

from app.events.event_bus import RedisEventBus, event_bus
from app.events.event_models import EventType, NexusEvent

logger = logging.getLogger(__name__)


class AgentWorker(ABC):
    """
    Base asynchronous worker that subscribes to streams and reacts to events.
    """

    name: str = "base_worker"
    listen_stream: str = "task_events"
    consumer_group: str = "base_group"
    listen_event_types: List[EventType] = []

    def __init__(self, bus: Optional[RedisEventBus] = None):
        self.bus = bus or event_bus
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    @abstractmethod
    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        """
        Process incoming event and optionally return downstream events to emit.
        """
        raise NotImplementedError

    async def _on_event_received(self, event: NexusEvent):
        """Internal callback invoked when a subscribed event arrives."""
        try:
            outgoing_events = await self.handle_event(event)
            if outgoing_events:
                for out_event in outgoing_events:
                    out_event.task_id = event.task_id
                    out_event.user_id = event.user_id
                    out_event.source_agent = self.name
                    await self.bus.publish(out_event)
        except Exception as e:
            logger.exception(f"[{self.name}] Error handling event {event.event_type.value}: {e}")

    async def start(self):
        """Start listening for events in the background."""
        self._stop_event.clear()
        consumer_name = f"{self.name}_consumer_1"
        logger.info(f"[{self.name}] 🚀 Starting worker on stream '{self.listen_stream}'")
        self._task = asyncio.create_task(
            self.bus.listen_stream(
                stream_name=self.listen_stream,
                group_name=self.consumer_group,
                consumer_name=consumer_name,
                target_event_types=self.listen_event_types,
                callback=self._on_event_received,
                stop_event=self._stop_event,
            )
        )

    async def stop(self):
        """Stop worker gracefully."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.name}] 🛑 Worker stopped.")
