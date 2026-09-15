"""Sentinel Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.sentinel.sentinel_scheduler import sentinel_scheduler

logger = logging.getLogger(__name__)


@tool
def get_morning_briefing(location: str = "Chennai") -> Dict[str, Any]:
    """
    Generates a full morning briefing including weather, financial market pulse, top tech headlines, and system vitals.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    sentinel_scheduler.generate_morning_briefing(location=location)
                ).result()
        else:
            return asyncio.run(sentinel_scheduler.generate_morning_briefing(location=location))
    except Exception as e:
        logger.error(f"[SentinelTools] get_morning_briefing error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def check_system_sentinel() -> Dict[str, Any]:
    """
    Runs a hardware and system health check, detecting memory pressure, CPU spikes, or low disk space.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    sentinel_scheduler.check_hardware_health()
                ).result()
        else:
            return asyncio.run(sentinel_scheduler.check_hardware_health())
    except Exception as e:
        logger.error(f"[SentinelTools] check_system_sentinel error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
