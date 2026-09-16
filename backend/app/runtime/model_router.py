"""
Hardware-Aware Model Router & Scheduler for Sovereign Local Inference.
Dynamically inspects available RAM, VRAM, and task complexity to route to the optimal local model.
"""
import psutil
import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TaskComplexity(str, Enum):
    FAST_PATH = "FAST_PATH"      # Simple intents, status checks, arithmetic
    CODING = "CODING"            # AST diffs, code generation, diagnostics
    REASONING = "REASONING"      # Multi-step planning, debate, policy analysis
    VISION = "VISION"            # Screen OCR, image QA


class ModelRouter:
    """
    Routes execution to optimal local Ollama models based on hardware capacity and task complexity.
    """

    def __init__(
        self,
        default_model: str = "llama3:latest",
        coding_model: str = "qwen2.5-coder:latest",
        fast_model: str = "phi4-mini:latest",
        vision_model: str = "gemma3:4b",
    ):
        self.default_model = default_model
        self.coding_model = coding_model
        self.fast_model = fast_model
        self.vision_model = vision_model
        self._pinned_model: Optional[str] = None

    def inspect_hardware_state(self) -> Dict[str, Any]:
        """Inspect current system RAM, CPU, and estimated memory headroom."""
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.1)
        return {
            "ram_total_gb": round(mem.total / (1024 ** 3), 2),
            "ram_available_gb": round(mem.available / (1024 ** 3), 2),
            "ram_percent_used": mem.percent,
            "cpu_percent": cpu_pct,
            "low_memory_mode": mem.available < (3.0 * (1024 ** 3))
        }

    def route_model(self, task_goal: str, complexity: Optional[TaskComplexity] = None) -> str:
        """
        Select best model based on goal context, complexity, and hardware constraints.
        """
        hw = self.inspect_hardware_state()
        goal_lower = task_goal.lower()

        # If system is in low memory mode (< 3GB RAM free), force lightweight model
        if hw["low_memory_mode"]:
            logger.warning(f"[ModelRouter] Low memory detected ({hw['ram_available_gb']} GB free). Pinning fast model.")
            return self.fast_model

        # If explicitly pinned by user/config
        if self._pinned_model:
            return self._pinned_model

        # Complexity-based routing
        if complexity == TaskComplexity.CODING or any(k in goal_lower for k in ["code", "refactor", "ast", "python", "diff", "function"]):
            return self.default_model  # Primary capable model

        if complexity == TaskComplexity.FAST_PATH or any(k in goal_lower for k in ["status", "time", "ping", "check", "system"]):
            return self.default_model

        return self.default_model

    def pin_model(self, model_name: str):
        """Pin a specific model to avoid multi-model thrashing in Ollama."""
        self._pinned_model = model_name
        logger.info(f"[ModelRouter] Model pinned to: {model_name}")

    def unpin_model(self):
        self._pinned_model = None


# Singleton instance
model_router = ModelRouter()
