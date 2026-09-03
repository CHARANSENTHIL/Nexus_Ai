"""
Vision Agent Worker: Listens for ACTION_COMPLETED and performs screenshot capture & OCR verification.
"""
import asyncio
import logging
from typing import List

from app.events.agent_worker import AgentWorker
from app.events.event_models import (
    EventType,
    NexusEvent,
    VerificationResultPayload,
)
from app.events.task_tracker import task_tracker
from app.vision.screen_reader import screen_reader

logger = logging.getLogger(__name__)


class VisionWorker(AgentWorker):
    name = "vision_agent"
    listen_stream = "action_events"
    consumer_group = "vision_group"
    listen_event_types = [EventType.ACTION_COMPLETED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        action = event.payload.get("action", "")
        # Only verify visual actions or explicit screen requests
        if action in ("open_application", "open_url", "browse", "run_visual_action_sequence"):
            logger.info(f"[VisionWorker] 📸 Capturing verification screenshot for action '{action}'")

            try:
                # Capture screenshot to disk
                screenshot_path = await asyncio.to_thread(screen_reader.take_screenshot)

                # Emit screen capture metadata (path only, no large binary blobs in Redis)
                captured_evt = NexusEvent(
                    event_type=EventType.SCREEN_CAPTURED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload={"screenshot_path": screenshot_path, "action": action},
                )
                await task_tracker.update_task_from_event(captured_evt)

                # Run lightweight OCR text scan for errors
                errors = await asyncio.to_thread(screen_reader.find_errors_on_screen)
                if errors:
                    ver_payload = VerificationResultPayload(
                        verified=False,
                        detail=f"Visual error detected on screen: {', '.join(errors[:2])}",
                        screenshot_path=screenshot_path,
                    )
                    ver_evt = NexusEvent(
                        event_type=EventType.VERIFICATION_FAILED,
                        task_id=event.task_id,
                        user_id=event.user_id,
                        source_agent=self.name,
                        payload=ver_payload.model_dump(),
                    )
                else:
                    ver_payload = VerificationResultPayload(
                        verified=True,
                        detail="Screen state verified successfully with no visual errors.",
                        screenshot_path=screenshot_path,
                    )
                    ver_evt = NexusEvent(
                        event_type=EventType.VERIFICATION_PASSED,
                        task_id=event.task_id,
                        user_id=event.user_id,
                        source_agent=self.name,
                        payload=ver_payload.model_dump(),
                    )

                await task_tracker.update_task_from_event(ver_evt)
                return [captured_evt, ver_evt]

            except Exception as e:
                logger.warning(f"[VisionWorker] Verification error: {e}")
                return []

        return []


# Global instance
vision_worker = VisionWorker()
