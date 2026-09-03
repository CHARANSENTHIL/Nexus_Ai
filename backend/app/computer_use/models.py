"""
Data models and schemas for the Computer Use Abstraction Layer.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class ExecutionMethod(str, Enum):
    """Execution technology / layer selected by the Execution Router."""
    NATIVE_API = "native_api"        # Windows OS API, subprocess, psutil, pycaw, powershell
    BROWSER_DOM = "browser_dom"      # Playwright DOM selectors, page navigation
    VISION_GUI = "vision_gui"        # mss + Gemma Vision / OCR locator + PyAutoGUI
    SHELL_SCRIPT = "shell_script"    # PowerShell / Cmd shell execution
    DRY_RUN = "dry_run"              # Mock / testing environment


class ActionType(str, Enum):
    """Semantic action requested by the AI agent."""
    CLICK = "click"
    CLICK_ELEMENT = "click_element"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    TYPE_ELEMENT = "type_element"
    PRESS = "press"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    MOVE = "move"
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    NAVIGATE = "navigate"
    SCREENSHOT = "screenshot"
    GET_ACTIVE_WINDOW = "get_active_window"
    GET_SYSTEM_STATE = "get_system_state"
    SET_VOLUME = "set_volume"
    SET_BRIGHTNESS = "set_brightness"
    SET_POWER = "set_power"
    RUN_COMMAND = "run_command"


class ActionRequest(BaseModel):
    """Structured request submitted to the ComputerInterface."""
    action: ActionType
    target: Optional[str] = None                     # Element name, URL, app name, command, or selector
    coordinates: Optional[Tuple[int, int]] = None    # (x, y) if coordinates are explicitly known
    text_val: Optional[str] = None                   # Text to type
    keys: Optional[List[str]] = None                 # Key combination e.g. ["ctrl", "c"]
    amount: Optional[int] = None                     # Scroll amount or level
    preferred_method: Optional[ExecutionMethod] = None
    timeout_seconds: float = 15.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Structured result returned by the Computer Use Layer."""
    success: bool
    action: ActionType
    target: Optional[str] = None
    executor_used: ExecutionMethod
    duration_ms: float = 0.0
    coordinates: Optional[Tuple[int, int]] = None
    window_title: Optional[str] = None
    output: Optional[Any] = None
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)
