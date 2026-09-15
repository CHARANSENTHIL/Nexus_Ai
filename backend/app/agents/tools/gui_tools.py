"""Omni-GUI Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool

from app.agents.gui_copilot_agent import gui_copilot_agent

logger = logging.getLogger(__name__)


@tool
def execute_gui_actions(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executes a sequence of visual mouse/keyboard actions on the Windows desktop.
    Supported action dicts:
    - {"type": "click", "x": 500, "y": 300, "clicks": 1, "button": "left"}
    - {"type": "double_click", "x": 500, "y": 300}
    - {"type": "type", "text": "hello world", "interval": 0.05}
    - {"type": "hotkey", "keys": "ctrl+s"}
    - {"type": "press", "key": "enter"}
    - {"type": "wait", "seconds": 2.0}
    - {"type": "scroll", "amount": -500}
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
                    gui_copilot_agent.execute_action_sequence(actions=actions)
                ).result()
        else:
            return asyncio.run(gui_copilot_agent.execute_action_sequence(actions=actions))
    except Exception as e:
        logger.error(f"[GUITools] execute_gui_actions error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def click_screen_text(text: str) -> Dict[str, Any]:
    """
    Locates text anywhere on the visible Windows desktop using OCR and clicks on it.
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
                    gui_copilot_agent.find_and_click_text(text_target=text)
                ).result()
        else:
            return asyncio.run(gui_copilot_agent.find_and_click_text(text_target=text))
    except Exception as e:
        logger.error(f"[GUITools] click_screen_text error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
