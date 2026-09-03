"""
Action → Observation → Verification — Core Pydantic Data Models.

Every automated step in Nexus AI is represented as a structured Action.
After execution, the system captures a multi-layer Observation and runs
the VerificationEngine to produce a VerificationResult before proceeding.
"""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ── Action Types & Global Timeouts ─────────────────────────────────────────────
ACTION_TIMEOUTS: Dict[str, float] = {
    "click": 5.0,
    "type": 5.0,
    "hotkey": 5.0,
    "open_application": 15.0,
    "open_url": 30.0,
    "browser_navigate": 30.0,
    "browser_click": 10.0,
    "browser_type": 10.0,
    "search_web": 30.0,
    "run_shell_command": 60.0,
    "complex_task": 300.0,
    "default": 30.0,
}


def default_timeout(tool: str) -> float:
    """Return the default timeout for a given tool name."""
    for key in ACTION_TIMEOUTS:
        if key in tool:
            return ACTION_TIMEOUTS[key]
    return ACTION_TIMEOUTS["default"]


# ── Action ──────────────────────────────────────────────────────────────────────
class Action(BaseModel):
    """
    Represents a single agentic action to be executed, observed, and verified.

    expected_state keys (used by VerificationEngine to pick verifiers):
      - process: str                    → ProcessVerifier checks process running
      - window_title: str               → WindowVerifier checks foreground window
      - url_contains: str               → BrowserVerifier checks page URL
      - page_title_contains: str        → BrowserVerifier checks page title
      - file_exists: str                → FileVerifier checks path exists
      - http_ok: str                    → NetworkVerifier checks URL returns 200
      - ocr_contains: str | list[str]   → OCRVerifier scans screenshot text
      - vision_prompt: str              → VisionVerifier (last resort, Gemma3)
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    expected_state: Dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=30.0)
    retry_limit: int = Field(default=3)
    description: str = ""  # human-readable label for logs

    @classmethod
    def create(cls, tool: str, arguments: Dict[str, Any], expected_state: Dict[str, Any],
               description: str = "", retry_limit: int = 3) -> "Action":
        """Factory: auto-derives timeout from tool name."""
        return cls(
            tool=tool,
            arguments=arguments,
            expected_state=expected_state,
            timeout=default_timeout(tool),
            retry_limit=retry_limit,
            description=description or tool,
        )


# ── Observation ─────────────────────────────────────────────────────────────────
class Observation(BaseModel):
    """
    Multi-layer system state snapshot captured BEFORE and AFTER each action.

    Layers:
      process_state   — running processes snapshot (psutil)
      window_state    — foreground window title, rect (win32gui)
      screen_state    — OCR text, screenshot file path, resolution
      browser_state   — current URL, page title, HTTP status (Playwright)
      files           — checked file paths and their existence/size
      errors          — any capture errors (non-fatal)
    """
    process_state: Dict[str, Any] = Field(default_factory=dict)
    window_state: Dict[str, Any] = Field(default_factory=dict)
    screen_state: Dict[str, Any] = Field(default_factory=dict)
    browser_state: Dict[str, Any] = Field(default_factory=dict)
    files: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


# ── Individual Check ────────────────────────────────────────────────────────────
class VerificationCheck(BaseModel):
    """One verifier's result within a VerificationResult."""
    name: str           # e.g. "ProcessVerifier", "BrowserVerifier"
    passed: bool
    confidence: float   # 0.0 = inconclusive, 1.0 = certain
    detail: str = ""    # human-readable explanation


# ── VerificationResult ──────────────────────────────────────────────────────────
class VerificationResult(BaseModel):
    """
    Aggregated result from all verifiers that ran for a given action.

    success is True when at least one check passes with confidence ≥ 0.8,
    OR when the majority of lower-confidence checks agree.
    """
    success: bool
    confidence: float   # 0.0 – 1.0, highest passing check confidence
    checks: List[VerificationCheck] = Field(default_factory=list)
    reason: str = ""    # human-readable summary


# ── Pipeline Result ─────────────────────────────────────────────────────────────
class PipelineResult(BaseModel):
    """Final result returned by ActionPipeline.run() for a single action."""
    success: bool
    action_id: str = ""
    skipped: bool = False          # True if idempotency check said already done
    recovered: bool = False        # True if succeeded after a recovery attempt
    attempt: int = 0               # which attempt succeeded (0 = first try)
    observation: Optional[Observation] = None
    verification: Optional[VerificationResult] = None
    reason: str = ""               # failure reason if success=False
    latency_ms: int = 0
