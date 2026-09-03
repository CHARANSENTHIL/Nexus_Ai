"""
Metrics SSE stream endpoint — GET /api/v1/metrics/stream
Streams live system metrics via Server-Sent Events every 3 seconds.
"""
import asyncio
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.digital_twin.service import digital_twin_service

logger = logging.getLogger(__name__)
router = APIRouter()


async def metrics_event_generator():
    """Generate SSE events with live system metrics."""
    while True:
        try:
            state = digital_twin_service.get_state()
            data = {
                "cpu_percent": state.cpu.usage_percent if state.cpu else 0.0,
                "ram_percent": state.ram.percent if state.ram else 0.0,
                "ram_available_gb": round(state.ram.available_bytes / (1024**3), 2) if state.ram else 0.0,
                "disk_percent": state.disk.percent if state.disk else 0.0,
                "battery_percent": state.battery.percent if state.battery else None,
                "battery_plugged": state.battery.power_plugged if state.battery else None,
                "network_connected": state.network.is_connected if state.network else False,
                "process_count": len(state.processes) if state.processes else 0,
                "top_processes": [p.model_dump() for p in state.processes[:5]] if state.processes else [],
                "active_windows": [w.model_dump() for w in state.active_windows[:5]] if state.active_windows else [],
                "timestamp": state.timestamp.isoformat() if state.timestamp else None,
            }
            yield f"data: {json.dumps(data)}\n\n"
        except Exception as e:
            logger.warning(f"SSE metrics error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        await asyncio.sleep(3)


@router.get("/metrics/stream")
async def stream_metrics():
    """SSE endpoint — streams live system metrics every 3 seconds."""
    return StreamingResponse(
        metrics_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
