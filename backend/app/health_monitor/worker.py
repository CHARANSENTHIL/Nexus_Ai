import asyncio
import logging
from typing import List
from app.config import settings
from app.digital_twin.service import digital_twin_service
from app.health_monitor.analyzer import HealthAnalyzer, DiskTrendPoint

logger = logging.getLogger("health_monitor")

class HealthMonitorWorker:
    def __init__(self):
        self.history: List[DiskTrendPoint] = []
        self._is_running = False

    async def run(self, stop_event: asyncio.Event):
        self._is_running = True
        logger.info("Health Monitor Worker started.")
        while not stop_event.is_set():
            try:
                state = digital_twin_service.update_state()
                now_epoch = state.timestamp.timestamp()
                point = DiskTrendPoint(timestamp_epoch=now_epoch, free_bytes=float(state.disk.free_bytes))
                
                self.history.append(point)
                if len(self.history) > 100:
                    self.history.pop(0)

                alert = HealthAnalyzer.check_disk_alert(
                    self.history,
                    threshold_days=settings.DISK_ALERT_THRESHOLD_DAYS
                )
                if alert:
                    logger.warning(f"HEALTH ALERT GENERATED: {alert['message']}")

            except Exception as e:
                logger.error(f"Error in Health Monitor loop: {e}")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.HEALTH_MONITOR_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
                
        logger.info("Health Monitor Worker stopped.")

health_monitor_worker = HealthMonitorWorker()
