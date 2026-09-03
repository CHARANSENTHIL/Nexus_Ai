"""
Computer Use Layer for Nexus AI — Unified Hardware/Software-Agnostic Abstraction.
Exports the standard `computer` interface and data models.
"""
from app.computer_use.models import (
    ActionRequest,
    ActionResult,
    ActionType,
    ExecutionMethod,
)
from app.computer_use.interface import ComputerInterface, computer
from app.computer_use.router import ExecutionRouter

__all__ = [
    "computer",
    "ComputerInterface",
    "ExecutionRouter",
    "ActionRequest",
    "ActionResult",
    "ActionType",
    "ExecutionMethod",
]
