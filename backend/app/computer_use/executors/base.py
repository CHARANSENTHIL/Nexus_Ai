"""
Base Executor abstract class for Computer Use Layer.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from app.computer_use.models import ActionRequest, ActionResult, ExecutionMethod


class BaseExecutor(ABC):
    """Abstract base class for all technology-specific executors."""

    def __init__(self, method: ExecutionMethod):
        self.method = method

    @abstractmethod
    def can_handle(self, request: ActionRequest) -> bool:
        """Return True if this executor can reliably handle the action request."""
        pass

    @abstractmethod
    async def execute(self, request: ActionRequest) -> ActionResult:
        """Execute the action and return a structured ActionResult."""
        pass
