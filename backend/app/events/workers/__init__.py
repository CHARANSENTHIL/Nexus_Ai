"""
Micro-Agent Workers for Redis Streams Event Bus
"""
from app.events.workers.router_worker import RouterWorker, router_worker
from app.events.workers.planner_worker import PlannerWorker, planner_worker
from app.events.workers.security_worker import SecurityWorker, security_worker
from app.events.workers.windows_worker import WindowsWorker, windows_worker
from app.events.workers.browser_worker import BrowserWorker, browser_worker
from app.events.workers.vision_worker import VisionWorker, vision_worker
from app.events.workers.recovery_worker import RecoveryWorker, recovery_worker

ALL_WORKERS = [
    router_worker,
    planner_worker,
    security_worker,
    windows_worker,
    browser_worker,
    vision_worker,
    recovery_worker,
]

__all__ = [
    "RouterWorker",
    "router_worker",
    "PlannerWorker",
    "planner_worker",
    "SecurityWorker",
    "security_worker",
    "WindowsWorker",
    "windows_worker",
    "BrowserWorker",
    "browser_worker",
    "VisionWorker",
    "vision_worker",
    "RecoveryWorker",
    "recovery_worker",
    "ALL_WORKERS",
]
