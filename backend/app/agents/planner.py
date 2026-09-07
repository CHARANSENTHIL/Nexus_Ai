"""
Planner Agent — LangChain + Llama 3 (Ollama) + CrewAI-style intent routing.
Architecture:
  1. Fast-path intent detection (keyword match, no LLM) — instant
  2. LLM decomposes complex goals into subtasks — ~30s
  3. Tools execute DIRECTLY via registry — instant
  4. Self-healing retries on failure

Merged features from JIN/JARVIS: CrewAI intent routing, vision agent support.
"""
import asyncio
import logging
import os
import re
import sys
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional



from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from app.config import settings
from app.agents.models import (
    AgentType, TaskGraph, TaskNode, TaskStatus,
    SubtaskExecutionPlan, RiskLevel,
)

logger = logging.getLogger(__name__)


# ── LLM Setup ────────────────────────────────────────────────────────────────
def get_llm(model: str = None):
    url = settings.get_ollama_url()
    m = model or getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")
    logger.info(f"[Planner] Using local Ollama LLM: {m}")
    return OllamaLLM(
        model=m,
        base_url=url,
        temperature=0.1,
    )



# ── Decomposition prompt (single LLM call) ───────────────────────────────────
DECOMPOSITION_PROMPT = PromptTemplate(
    input_variables=["goal", "system_state", "memory_context"],
    template="""You are the Nexus AI Planner. Decompose user goals into executable subtasks.

User Goal: {goal}

Current System State: {system_state}

Relevant Memory: {memory_context}

Return ONLY a valid JSON array of subtasks. Each subtask:
- "id": unique string like "task_1"
- "title": short description
- "description": what to do
- "agent": one of "system", "application", "file", "vision"
- "tool": exact tool name to call (see list below)
- "tool_input": JSON object with the tool's input parameters
- "dependencies": list of task IDs (empty = no deps)
- "risk_level": "low", "medium", "high", or "critical"
- "requires_approval": true if destructive/irreversible

Available tools:
SYSTEM: get_system_state (no input), get_running_processes (name_filter: str), kill_process (pid: int), get_disk_usage (path: str), set_system_power (action: str), check_network_connectivity (host: str)
APPLICATION: open_application (app_name: str, args: str), close_application (app_name: str), run_shell_command (command: str, timeout: int)
FILE: search_files (directory: str, pattern: str), list_directory (path: str), copy_file (source: str, destination: str), delete_file (path: str), compress_files (paths: list, output: str), get_file_hash (path: str, algorithm: str), organize_downloads (downloads_dir: str)
VISION: take_screenshot (filename: str), ocr_screen (screenshot_path: str), find_error_on_screen (screenshot_path: str), analyze_desktop (screenshot_path: str), get_vision_status (no input)

Example for "Check my system health":
[
  {{"id":"task_1","title":"Get system state","description":"Check CPU, RAM, battery, disk","agent":"system","tool":"get_system_state","tool_input":{{}},"dependencies":[],"risk_level":"low","requires_approval":false}},
  {{"id":"task_2","title":"Check network","description":"Verify internet connectivity","agent":"system","tool":"check_network_connectivity","tool_input":{{"host":"8.8.8.8"}},"dependencies":[],"risk_level":"low","requires_approval":false}}
]

Example for "Take a screenshot and analyze it":
[
  {{"id":"task_1","title":"Capture screen","description":"Take a screenshot","agent":"vision","tool":"take_screenshot","tool_input":{{}},"dependencies":[],"risk_level":"low","requires_approval":false}},
  {{"id":"task_2","title":"Analyze screen","description":"OCR the screenshot for text","agent":"vision","tool":"ocr_screen","tool_input":{{}},"dependencies":["task_1"],"risk_level":"low","requires_approval":false}}
]

Example for "Prepare my laptop for coding":
[
  {{"id":"task_1","title":"Check system health","description":"Get CPU, RAM, battery status","agent":"system","tool":"get_system_state","tool_input":{{}},"dependencies":[],"risk_level":"low","requires_approval":false}},
  {{"id":"task_2","title":"Check network","description":"Verify internet","agent":"system","tool":"check_network_connectivity","tool_input":{{"host":"8.8.8.8"}},"dependencies":[],"risk_level":"low","requires_approval":false}},
  {{"id":"task_3","title":"Open VS Code","description":"Launch Visual Studio Code","agent":"application","tool":"open_application","tool_input":{{"app_name":"code","args":""}},"dependencies":["task_1"],"risk_level":"low","requires_approval":false}},
  {{"id":"task_4","title":"Start Docker","description":"Open Docker Desktop","agent":"application","tool":"open_application","tool_input":{{"app_name":"Docker Desktop","args":""}},"dependencies":["task_1"],"risk_level":"low","requires_approval":false}},
  {{"id":"task_5","title":"Open GitHub","description":"Open GitHub in browser","agent":"application","tool":"open_application","tool_input":{{"app_name":"chrome","args":"https://github.com"}},"dependencies":[],"risk_level":"low","requires_approval":false}}
]
""",
)


# ── CrewAI-style Intent Router (fast path, no LLM) ───────────────────────────
class IntentRouter:
    """
    JIN/JARVIS-style keyword intent detection. Detects common commands instantly
    without calling the LLM, cutting response time from ~30s to ~0.1s.
    """

    @staticmethod
    def detect(goal: str) -> Optional[List[Dict]]:
        """
        Detect intent from goal text. Returns subtask list if matched,
        None if LLM decomposition is needed.
        """
        g = goal.lower().strip()

        # ── Check for compound multi-step goals ──
        # If prompt contains "then", "after that", or multiple distinct action types (e.g. open + health),
        # yield to LLM / NLP planner to decompose all steps.
        if _is_compound_goal(g):
            return None

        # ── Greetings / Conversational Chat (instant, 0ms) ──
        greetings = (
            "hi", "hello", "hey", "hola", "hi nexus", "hello nexus", "hey nexus",
            "greetings", "good morning", "good evening", "good afternoon",
            "who are you", "what can you do", "help", "howdy", "yo", "sup", "hlo"
        )
        if g in greetings or any(g.startswith(x + " ") for x in ("hi", "hello", "hey", "hola", "greetings")):
            return [{
                "id": "task_1",
                "title": "Reply to Greeting",
                "description": "Send friendly conversational greeting and capabilities",
                "agent": "chat",
                "tool": "chat_response",
                "tool_input": {"prompt": goal},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Screenshot / Vision ──

        if any(w in g for w in ("screenshot", "screen shot", "capture screen", "snap screen")):
            tasks = [{"id": "task_1", "title": "Take screenshot", "description": "Capture screen",
                       "agent": "vision", "tool": "take_screenshot", "tool_input": {},
                       "dependencies": [], "risk_level": "low", "requires_approval": False}]
            if any(w in g for w in ("analyze", "read", "ocr", "text", "what")):
                tasks.append({"id": "task_2", "title": "OCR analysis", "description": "Extract text from screenshot",
                               "agent": "vision", "tool": "ocr_screen", "tool_input": {},
                               "dependencies": ["task_1"], "risk_level": "low", "requires_approval": False})
            return tasks

        if any(w in g for w in ("find error", "check error", "error on screen", "scan for error")):
            return [
                {"id": "task_1", "title": "Scan for errors", "description": "Find errors on screen",
                 "agent": "vision", "tool": "find_error_on_screen", "tool_input": {},
                 "dependencies": [], "risk_level": "low", "requires_approval": False},
            ]

        if any(w in g for w in ("desktop items", "what on desktop", "analyze desktop", "desktop analysis")):
            return [
                {"id": "task_1", "title": "Analyze desktop", "description": "Find items on desktop",
                 "agent": "vision", "tool": "analyze_desktop", "tool_input": {},
                 "dependencies": [], "risk_level": "low", "requires_approval": False},
            ]

        if any(w in g for w in ("vision status", "vision capabilities", "can you see")):
            return [
                {"id": "task_1", "title": "Vision status", "description": "Check vision capabilities",
                 "agent": "vision", "tool": "get_vision_status", "tool_input": {},
                 "dependencies": [], "risk_level": "low", "requires_approval": False},
            ]

        # ── System health (instant) ──
        if any(w in g for w in ("health", "system status", "system state", "how is my")):
            tasks = [{"id": "task_1", "title": "System health check", "description": "Get system state",
                       "agent": "system", "tool": "get_system_state", "tool_input": {},
                       "dependencies": [], "risk_level": "low", "requires_approval": False}]
            if any(w in g for w in ("network", "internet", "connection")):
                tasks.append({"id": "task_2", "title": "Network check", "description": "Check connectivity",
                               "agent": "system", "tool": "check_network_connectivity", "tool_input": {"host": "8.8.8.8"},
                               "dependencies": [], "risk_level": "low", "requires_approval": False})
            return tasks

        # ── CPU/RAM/Disk (instant) ──
        if any(w in g for w in ("cpu", "ram", "memory usage", "battery")):
            return [{"id": "task_1", "title": "System metrics", "description": "Get CPU/RAM/battery",
                     "agent": "system", "tool": "get_system_state", "tool_input": {},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        if any(w in g for w in ("disk", "storage", "space", "drive")):
            return [{"id": "task_1", "title": "Disk usage", "description": "Check disk space",
                     "agent": "system", "tool": "get_disk_usage", "tool_input": {"path": "C:\\"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── Network (instant) ──
        if any(w in g for w in ("network", "internet", "ping", "connectivity", "wifi")):
            return [{"id": "task_1", "title": "Network check", "description": "Check connectivity",
                     "agent": "system", "tool": "check_network_connectivity", "tool_input": {"host": "8.8.8.8"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── Process list (instant) ──
        if any(w in g for w in ("process", "running apps", "task manager", "what is running")):
            return [{"id": "task_1", "title": "List processes", "description": "Get running processes",
                     "agent": "system", "tool": "get_running_processes", "tool_input": {"name_filter": ""},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── YouTube specific search/play (instant) ──
        if "youtube" in g or ("play " in g and ("video" in g or "song" in g or "channel" in g)):
            clean_query = re.sub(r"(?i)^(open\s+youtube\s+and\s+(play|search)?|open\s+youtube|play|watch|search)\s*", "", g).strip()
            clean_query = re.sub(r"(?i)^(the\s+latest\s+video\s+from\s+)", "", clean_query).strip()
            target_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query or 'youtube')}"
            return [{"id": "task_1", "title": f"Play '{clean_query or 'YouTube'}' on YouTube", "description": f"Open YouTube for {clean_query}",
                     "agent": "application", "tool": "open_url_in_browser",
                     "tool_input": {"url": target_url, "browser": "chrome"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── General Web search / URL open (instant) ──
        is_local = any(w in g for w in ("file", "folder", "in my pc", "on my pc", "in my computer", "on my computer", "drive", "local", "directory"))
        if not is_local and (any(w in g for w in ("search ", "google ", "find online ")) or ("open " in g and "and search " in g)):
            query = re.sub(r"(?i)^(open\s+\w+\s+and\s+search|search|google|find online)\s+", "", g).strip()
            browser = "chrome" if "chrome" in g else "msedge" if "edge" in g else "chrome"
            return [{"id": "task_1", "title": f"Search '{query}' in {browser}", "description": f"Search for {query}",
                     "agent": "application", "tool": "open_url_in_browser",
                     "tool_input": {"url": query, "browser": browser},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]


        # ── App open/close (instant) ──
        if any(w in g for w in ("open ", "launch ", "start ")):
            url_match = re.search(r"open\s+(https?://\S+|\S+\.(com|org|io|net|edu|dev))", g)
            if url_match:
                target_url = url_match.group(1)
                return [{"id": "task_1", "title": f"Open {target_url}", "description": f"Open URL {target_url}",
                         "agent": "application", "tool": "open_url_in_browser",
                         "tool_input": {"url": target_url, "browser": "chrome"},
                         "dependencies": [], "risk_level": "low", "requires_approval": False}]

            app = _extract_app_name(g)
            return [{"id": "task_1", "title": f"Open {app}", "description": f"Launch {app}",
                     "agent": "application", "tool": "open_application",
                     "tool_input": {"app_name": app, "args": ""},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        if any(w in g for w in ("close ", "quit ", "exit ")):
            app = _extract_app_name(g)
            return [{"id": "task_1", "title": f"Close {app}", "description": f"Close {app}",
                     "agent": "application", "tool": "close_application",
                     "tool_input": {"app_name": app},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── Project / Script Execution (instant) ──
        if (any(w in g for w in ("run project", "run the project", "execute project", "start project", "run python", "run script", "run my project"))
                or re.search(r"(?i)\b(?:run|execute)\s+[a-zA-Z]:\\", goal)):
            m = re.search(r"(?i)(?:run|execute|start)(?:\s+the|\s+my)?\s+(?:project|script|code|file)?\s*['\"]?([A-Za-z]:\\[^\n'\"]+|\./\S+|/\S+|[A-Za-z0-9_\-\s]+)['\"]?", goal)

            if m:
                target_path = m.group(1).strip()
                resolved = _resolve_project_target(target_path)
                if resolved:
                    return [{
                        "id": "task_1",
                        "title": resolved["title"],
                        "description": f"Run project {target_path}",
                        "agent": "coding",
                        "tool": "run_shell_command",
                        "tool_input": {"command": resolved["command"], "cwd": resolved.get("cwd", ".")},
                        "dependencies": [],
                        "risk_level": "low",
                        "requires_approval": False,
                    }]

        # ── Folder Search & Rename (instant) ──

        if "folder" in g and "rename" in g:
            search_match = re.search(r"folder\s*(?:name[d]?|called)?\s*['\"]?([a-zA-Z0-9_\-]+)['\"]?", g)
            rename_match = re.search(r"rename\s*(?:it|folder)?\s*to\s*['\"]?([a-zA-Z0-9_\-]+)['\"]?", g)
            s_name = search_match.group(1) if search_match else "antigravity"
            r_name = rename_match.group(1) if rename_match else "charan"
            return [{"id": "task_1", "title": f"Search folder '{s_name}' and rename to '{r_name}'",
                     "description": f"Find and rename folder {s_name}",
                     "agent": "file", "tool": "search_and_rename_folder",
                     "tool_input": {"search_name": s_name, "new_name": r_name},
                     "dependencies": [], "risk_level": "medium", "requires_approval": False}]


        # ── File operations (instant) ──
        if any(w in g for w in ("organize download", "clean download")):
            return [{"id": "task_1", "title": "Organize downloads", "description": "Organize files",
                     "agent": "file", "tool": "organize_downloads",
                     "tool_input": {"downloads_dir": "C:\\Users\\Downloads"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        if any(w in g for w in ("list files", "show files", "what files")):
            return [{"id": "task_1", "title": "List directory", "description": "List files",
                     "agent": "file", "tool": "list_directory", "tool_input": {"path": "."},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── Brightness & Volume ──
        if any(w in g for w in ("brightness", "bright", "dim")):
            val = _extract_number(g)
            if val is None:
                val = 100
            return [{"id": "task_1", "title": f"Set brightness to {val}%", "description": f"Set brightness to {val}",
                     "agent": "system", "tool": "set_system_brightness", "tool_input": {"level": val},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        if any(w in g for w in ("volume", "sound", "audio", "mute")):
            val = _extract_number(g)
            if val is None:
                val = 0 if "mute" in g else 100
            return [{"id": "task_1", "title": f"Set volume to {val}%", "description": f"Set volume to {val}",
                     "agent": "application", "tool": "set_system_volume", "tool_input": {"level": val},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # ── System Power Control (Sleep, Shutdown, Restart, Lock) ──
        if any(w in g for w in ("sleep", "standby")):
            return [{"id": "task_1", "title": "Put system to sleep", "description": "System sleep",
                     "agent": "system", "tool": "set_system_power", "tool_input": {"action": "sleep"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        if any(w in g for w in ("shutdown", "power off", "turn off pc")):
            return [{"id": "task_1", "title": "Shutdown PC", "description": "System shutdown",
                     "agent": "system", "tool": "set_system_power", "tool_input": {"action": "shutdown"},
                     "dependencies": [], "risk_level": "high", "requires_approval": True}]

        if any(w in g for w in ("restart", "reboot")):
            return [{"id": "task_1", "title": "Restart PC", "description": "System restart",
                     "agent": "system", "tool": "set_system_power", "tool_input": {"action": "restart"},
                     "dependencies": [], "risk_level": "high", "requires_approval": True}]

        if any(w in g for w in ("lock pc", "lock screen", "lock computer")):
            return [{"id": "task_1", "title": "Lock PC", "description": "System lock",
                     "agent": "system", "tool": "set_system_power", "tool_input": {"action": "lock"},
                     "dependencies": [], "risk_level": "low", "requires_approval": False}]

        # No fast match → needs LLM
        return None


def _is_compound_goal(g: str) -> bool:
    """
    Check if a prompt contains multiple distinct requests combined together.
    Multi-step → return True → IntentRouter returns None → falls through to LangGraph.
    """
    # Explicit multi-step conjunctions
    if any(w in g for w in ("then", "after that", "and then", "first", "finally", "next")):
        return True

    # "and tell me", "and let me know", "and check" — implies a follow-up step
    if any(p in g for p in ("and tell me", "and let me know", "and check", "and report", "and notify")):
        return True

    # "go to" combined with any other action word → multi-step navigation task
    if "go to" in g and any(w in g for w in ("open", "search", "play", "watch", "click", "find")):
        return True

    # "search for X" as part of a larger instruction (not a standalone search)
    if "search for" in g and any(w in g for w in ("open", "go", "navigate", "youtube", "chrome", "browser")):
        return True

    # Comma-separated instructions: "open X, go to Y, do Z" → at least 2 commas = multi-step
    if g.count(",") >= 2:
        return True

    # Yield multi-action visual web/video tasks to LangGraph Orchestrator Engine
    if any(w in g for w in ("play", "watch", "click", "channel", "video", "search and", "look at")):
        return True

    actions = 0
    if any(w in g for w in ("open ", "launch ", "start ")):
        actions += 1
    if any(w in g for w in ("close ", "quit ", "exit ")):
        actions += 1
    if any(w in g for w in ("health", "system status", "cpu", "ram", "metrics")):
        actions += 1
    if any(w in g for w in ("screenshot", "screen shot", "ocr")):
        actions += 1
    if any(w in g for w in ("volume", "sound", "mute")):
        actions += 1
    if any(w in g for w in ("brightness", "bright")):
        actions += 1
    if any(w in g for w in ("sleep", "shutdown", "restart", "lock")):
        actions += 1

    return actions > 1


def _extract_number(text: str) -> Optional[int]:
    import re
    match = re.search(r"\b(\d{1,3})\b", text)
    return int(match.group(1)) if match else None


def _resolve_project_target(path_or_text: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a project directory or script path to an executable command with active python environment.
    """
    import os, sys, glob
    raw_path = path_or_text.strip().strip("'").strip('"')

    # If it's directly a file
    if os.path.isfile(raw_path):
        if raw_path.endswith(".py"):
            return {
                "command": f'"{sys.executable}" "{raw_path}"',
                "cwd": os.path.dirname(raw_path) or ".",
                "title": f"Execute Python script {os.path.basename(raw_path)}",
                "project_dir": os.path.dirname(raw_path),
            }
        elif raw_path.endswith(".js"):
            return {
                "command": f'node "{raw_path}"',
                "cwd": os.path.dirname(raw_path) or ".",
                "title": f"Execute Node script {os.path.basename(raw_path)}",
                "project_dir": os.path.dirname(raw_path),
            }

    # If it's a directory
    if os.path.isdir(raw_path):
        # 1. Check for standard Python entrypoints
        standard_py = ["main.py", "app.py", "server.py", "run.py", "index.py", "api.py"]
        for sp in standard_py:
            candidate = os.path.join(raw_path, sp)
            if os.path.isfile(candidate):
                return {
                    "command": f'"{sys.executable}" "{candidate}"',
                    "cwd": raw_path,
                    "title": f"Run project ({sp}) in {raw_path}",
                    "project_dir": raw_path,
                }

        # 2. Check for any Python files in directory
        py_files = glob.glob(os.path.join(raw_path, "*.py"))
        if py_files:
            target_py = py_files[0]
            return {
                "command": f'"{sys.executable}" "{target_py}"',
                "cwd": raw_path,
                "title": f"Run project ({os.path.basename(target_py)}) in {raw_path}",
                "project_dir": raw_path,
            }

        # 3. Check for Node/npm
        if os.path.isfile(os.path.join(raw_path, "package.json")):
            return {
                "command": "npm start",
                "cwd": raw_path,
                "title": f"Run npm project in {raw_path}",
                "project_dir": raw_path,
            }

        # 4. Fallback for directory
        return {
            "command": f'"{sys.executable}" -m unittest discover',
            "cwd": raw_path,
            "title": f"Run tests in {raw_path}",
            "project_dir": raw_path,
        }

    return None



def _extract_app_name(text: str) -> str:
    """Extract app name from command text."""
    app_aliases = {
        "vscode": "code", "visual studio code": "code", "vs code": "code",
        "chrome": "chrome", "google chrome": "chrome",
        "firefox": "firefox", "edge": "msedge",
        "notepad": "notepad", "calculator": "calc",
        "terminal": "wt", "powershell": "powershell",
        "explorer": "explorer", "file manager": "explorer",
        "docker": "Docker Desktop", "spotify": "spotify",
    }
    for alias, name in app_aliases.items():
        if alias in text:
            return name
    # Fallback: last word
    words = text.split()
    return words[-1] if words else "notepad"


# ── Tool Registry (name → callable) ──────────────────────────────────────────
def _build_tool_registry() -> Dict[str, Any]:
    """Build a flat registry mapping tool names to their callable .func references."""
    from app.agents.tools.system_tools import (
        get_system_state, get_running_processes, kill_process,
        get_disk_usage, set_system_power, check_network_connectivity,
        set_system_brightness,
    )
    from app.agents.tools.app_tools import (
        open_application, close_application, run_shell_command,
        set_system_volume, open_url_in_browser,
    )
    from app.agents.tools.file_tools import (
        search_files, list_directory, copy_file, delete_file,
        compress_files, get_file_hash, organize_downloads, rename_file,
        search_and_rename_folder,
    )
    from app.agents.tools.vision_tools import (
        take_screenshot, ocr_screen, find_error_on_screen,
        analyze_desktop, get_vision_status,
    )
    from app.agents.tools.n8n_tools import (
        list_n8n_workflows, trigger_n8n_workflow,
    )
    from app.agents.tools.browser_tools import (
        open_browser, open_url, search_web, read_page,
        click_element, fill_form, download_file, upload_file,
        take_browser_screenshot, get_page_text, close_browser,
    )
    return {
        # System tools
        "get_system_state": get_system_state.func,
        "get_running_processes": get_running_processes.func,
        "kill_process": kill_process.func,
        "get_disk_usage": get_disk_usage.func,
        "set_system_power": set_system_power.func,
        "check_network_connectivity": check_network_connectivity.func,
        "set_system_brightness": set_system_brightness.func,
        # Application tools
        "open_application": open_application.func,
        "close_application": close_application.func,
        "run_shell_command": run_shell_command.func,
        "set_system_volume": set_system_volume.func,
        "open_url_in_browser": open_url_in_browser.func,
        # File tools
        "search_files": search_files.func,
        "list_directory": list_directory.func,
        "copy_file": copy_file.func,
        "delete_file": delete_file.func,
        "compress_files": compress_files.func,
        "get_file_hash": get_file_hash.func,
        "organize_downloads": organize_downloads.func,
        "rename_file": rename_file.func,
        "search_and_rename_folder": search_and_rename_folder.func,
        # Vision tools
        "take_screenshot": take_screenshot.func,
        "ocr_screen": ocr_screen.func,
        "find_error_on_screen": find_error_on_screen.func,
        "analyze_desktop": analyze_desktop.func,
        "get_vision_status": get_vision_status.func,
        # n8n Automation tools
        "list_n8n_workflows": list_n8n_workflows.func,
        "trigger_n8n_workflow": trigger_n8n_workflow.func,
        # Browser tools (Playwright)
        "open_browser": open_browser.func,
        "open_url": open_url.func,
        "search_web": search_web.func,
        "read_page": read_page.func,
        "click_element": click_element.func,
        "fill_form": fill_form.func,
        "download_file": download_file.func,
        "upload_file": upload_file.func,
        "take_browser_screenshot": take_browser_screenshot.func,
        "get_page_text": get_page_text.func,
        "close_browser": close_browser.func,
    }




def _format_tool_result(tool_name: str, result: Any) -> str:
    """Format a raw tool result into a human-readable string."""
    if isinstance(result, dict):
        if tool_name == "get_system_state":
            return (
                f"🖥️ System Health:\n"
                f"  CPU: {result.get('cpu_percent', '?')}%\n"
                f"  RAM: {result.get('ram_percent', '?')}% ({result.get('ram_available_gb', '?')} GB free)\n"
                f"  Disk: {result.get('disk_percent', '?')}%\n"
                f"  Battery: {result.get('battery_percent', 'N/A')}%"
                f"{' (plugged in)' if result.get('battery_plugged') else ' (on battery)'}\n"
                f"  Network: {'✅ Connected' if result.get('network_connected') else '❌ Offline'}\n"
                f"  Processes: {result.get('process_count', '?')}"
            )
        elif tool_name == "check_network_connectivity":
            status = "✅ Connected" if result.get("connected") else "❌ Offline"
            return f"Network: {status} (pinged {result.get('host', '?')})"
        elif tool_name == "get_disk_usage":
            return f"Disk ({result.get('path', '?')}): {result.get('free_gb', '?')} GB free / {result.get('total_gb', '?')} GB total ({result.get('percent_used', '?')}% used)"
        elif tool_name == "take_screenshot":
            if result.get("success"):
                return f"📸 Screenshot captured: {result.get('path', '')}"
            return f"📸 Screenshot unavailable: {result.get('error', 'unknown')}"
        elif tool_name == "ocr_screen":
            if result.get("success"):
                return f"📝 OCR Result ({result.get('char_count', 0)} chars):\n{result.get('text', '')[:500]}"
            return f"📝 OCR unavailable: {result.get('error', 'unknown')}"
        elif tool_name == "find_error_on_screen":
            count = result.get("errors_found", 0)
            if count > 0:
                errors = "\n".join(f"  ⚠️ {e}" for e in result.get("errors", []))
                return f"🔍 Found {count} error(s):\n{errors}"
            return "🔍 No errors detected on screen"
        elif tool_name == "analyze_desktop":
            items = result.get("items", [])
            if items:
                return f"🖥️ Desktop items ({len(items)}):\n" + "\n".join(f"  • {i}" for i in items[:20])
            return f"🖥️ {result.get('message', 'No items found')}"
        elif tool_name == "get_vision_status":
            cap = "✅" if result.get("capture") else "❌"
            ocr = "✅" if result.get("ocr") else "❌"
            return f"👁️ Vision Status:\n  Screen Capture: {cap}\n  OCR: {ocr}"
        elif "success" in result:
            if result["success"]:
                return f"✅ {result.get('message', 'Done')}"
            else:
                return f"❌ {result.get('error', 'Failed')}"
        else:
            parts = [f"{k}: {v}" for k, v in result.items()]
            return "\n".join(parts)
    elif isinstance(result, list):
        if tool_name == "get_running_processes":
            if not result:
                return "No matching processes found."
            lines = [f"  {p.get('name', '?')} (PID {p.get('pid', '?')}) — CPU {p.get('cpu_percent', 0)}%" for p in result[:10]]
            return f"Running Processes ({len(result)} found):\n" + "\n".join(lines)
        return str(result)[:500]
    return str(result)[:500]


class PlannerAgent:
    """
    Orchestrates goal decomposition via LLM + direct tool execution.
    Enhanced with CrewAI-style intent routing (fast path) and self-healing.
    """

    def __init__(self):
        self.llm = get_llm()
        self.chain = DECOMPOSITION_PROMPT | self.llm | JsonOutputParser()
        self._tool_registry = None
        self._intent_router = IntentRouter()

        # Self-healing (lazy import to avoid circular deps)
        self._error_handler = None

    @property
    def tool_registry(self) -> Dict[str, Any]:
        if self._tool_registry is None:
            self._tool_registry = _build_tool_registry()
        return self._tool_registry

    @property
    def error_handler(self):
        if self._error_handler is None:
            from app.self_heal.error_handler import error_handler
            self._error_handler = error_handler
        return self._error_handler

    async def decompose_goal(
        self,
        goal: str,
        system_state: Dict[str, Any] = None,
        memory_context: str = "",
    ) -> SubtaskExecutionPlan:
        """
        Decompose a natural language goal into a SubtaskExecutionPlan.
        
        Strategy (CrewAI-style multi-tier routing):
        1. Fast path: Keyword intent router (instant ~0.1s, exact matches)
        2. Medium path: NLP Intent Parser via Llama 3 (~1-2s intent classification)
        3. Heavy path: Full DAG decomposition via Llama 3 (~30s multi-step graph)
        4. Fallback: Keyword decomposer
        """
    async def _decompose_with_fallbacks(self, goal: str, state_str: str, memory_context: str) -> List[Dict]:
        """Attempt LLM decomposition using local Ollama."""
        try:
            m = getattr(settings, "OLLAMA_MODEL", "llama3")
            logger.info(f"[Planner] Attempting decomposition with local Ollama: {m}")
            current_llm = get_llm()
            current_chain = DECOMPOSITION_PROMPT | current_llm | JsonOutputParser()
            
            result = await current_chain.ainvoke({
                "goal": goal,
                "system_state": state_str,
                "memory_context": memory_context[:400],
            })
            
            if isinstance(result, list):
                logger.info(f"[Planner] Successful decomposition using local Ollama")
                return result
        except Exception as e:
            logger.warning(f"[Planner] Local Ollama decomposition failed: {e}")
        
        return []

    async def decompose_goal(
        self,
        goal: str,
        system_state: Dict[str, Any] = None,
        memory_context: str = "",
    ) -> SubtaskExecutionPlan:
        """
        Decompose a natural language goal into a SubtaskExecutionPlan.
        
        Strategy (CrewAI-style multi-tier routing):
        1. Fast path: Keyword intent router (instant ~0.1s, exact matches)
        2. Medium path: NLP Intent Parser via Llama 3 (~1-2s intent classification)
        3. Heavy path: Full DAG decomposition via Llama 3 (~30s multi-step graph)
        4. Fallback: Keyword decomposer
        """
        raw_subtasks = None

        # ── Tier 1: Keyword intent router ──
        fast_result = self._intent_router.detect(goal)
        if fast_result is not None:
            logger.info(f"[Planner] Tier 1 Keyword match for: {goal[:60]}")
            raw_subtasks = fast_result

        # ── Tier 2: NLP Intent Parser (lightweight LLM classification) ──
        if raw_subtasks is None:
            try:
                from app.agents.intent_parser import intent_parser
                nlp_task = await intent_parser.classify(goal)
                if nlp_task is not None:
                    logger.info(f"[Planner] Tier 2 NLP Intent Parser match for: {goal[:60]}")
                    raw_subtasks = [nlp_task]
            except Exception as e:
                logger.warning(f"[Planner] NLP Intent Parser error: {e}")

        # ── Tier 3: Full LLM DAG Decomposition ──
        if raw_subtasks is None:
            logger.info(f"[Planner] Tier 3 Full LLM decomposition for: {goal[:60]}")
            state_str = str(system_state or {})[:800]
            try:
                raw_subtasks = await self._decompose_with_fallbacks(
                    goal=goal,
                    state_str=state_str,
                    memory_context=memory_context,
                )
            except Exception as e:
                logger.warning(f"LLM decomposition failed ({e}), using keyword fallback")
                raw_subtasks = self._keyword_decompose(goal)

        nodes: Dict[str, TaskNode] = {}
        execution_order: List[str] = []
        requires_approval = False
        approval_actions: List[str] = []
        overall_risk = RiskLevel.LOW

        for subtask in raw_subtasks:
            node_id = subtask.get("id", str(uuid.uuid4())[:8])
            agent_str = subtask.get("agent", "system").upper()
            try:
                agent_type = AgentType[agent_str]
            except KeyError:
                agent_type = AgentType.SYSTEM

            node = TaskNode(
                id=node_id,
                title=subtask.get("title", ""),
                description=subtask.get("description", ""),
                assigned_agent=agent_type,
                dependencies=subtask.get("dependencies", []),
                input_data={
                    "risk_level": subtask.get("risk_level", "low"),
                    "tool": subtask.get("tool", ""),
                    "tool_input": subtask.get("tool_input", {}),
                },
            )
            nodes[node_id] = node
            execution_order.append(node_id)

            if subtask.get("requires_approval"):
                requires_approval = True
                approval_actions.append(node_id)

            risk = subtask.get("risk_level", "low")
            if risk in ("critical", "high"):
                overall_risk = RiskLevel.HIGH
            elif risk == "medium" and overall_risk == RiskLevel.LOW:
                overall_risk = RiskLevel.MEDIUM

        graph = TaskGraph(
            graph_id=str(uuid.uuid4()),
            goal=goal,
            nodes=nodes,
            execution_order=execution_order,
        )
        return SubtaskExecutionPlan(
            plan_id=str(uuid.uuid4()),
            goal=goal,
            task_graph=graph,
            estimated_steps=len(nodes),
            risk_level=overall_risk,
            requires_approval=requires_approval,
            approval_actions=approval_actions,
        )

    def _keyword_decompose(self, goal: str) -> List[Dict]:
        """Fast keyword-based decomposition when LLM is unavailable or fails."""
        g = goal.lower()
        tasks = []

        # Vision tasks
        if any(w in g for w in ("screenshot", "capture", "snap")):
            tasks.append({"id": "task_1", "title": "Take screenshot", "description": "Capture screen", "agent": "vision", "tool": "take_screenshot", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("ocr", "read screen", "extract text")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "OCR screen", "description": "Extract text", "agent": "vision", "tool": "ocr_screen", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("error on screen", "find error", "scan error")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Find errors", "description": "Scan for errors", "agent": "vision", "tool": "find_error_on_screen", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("desktop items", "analyze desktop")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Analyze desktop", "description": "Find desktop items", "agent": "vision", "tool": "analyze_desktop", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})

        # System tasks
        if any(w in g for w in ("health", "system", "status", "cpu", "ram", "battery", "check")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "System health check", "description": "Get system state", "agent": "system", "tool": "get_system_state", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("network", "internet", "connection", "wifi", "ping")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Network check", "description": "Check connectivity", "agent": "system", "tool": "check_network_connectivity", "tool_input": {"host": "8.8.8.8"}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("disk", "storage", "space")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Disk usage", "description": "Check disk space", "agent": "system", "tool": "get_disk_usage", "tool_input": {"path": "C:\\"}, "dependencies": [], "risk_level": "low", "requires_approval": False})
        if any(w in g for w in ("process", "running", "task manager")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "List processes", "description": "Get running processes", "agent": "system", "tool": "get_running_processes", "tool_input": {"name_filter": ""}, "dependencies": [], "risk_level": "low", "requires_approval": False})

        # App tasks
        if any(w in g for w in ("open", "launch", "start", "code", "vscode", "browser", "chrome")):
            app = _extract_app_name(g)
            tasks.append({"id": f"task_{len(tasks)+1}", "title": f"Open {app}", "description": f"Launch {app}", "agent": "application", "tool": "open_application", "tool_input": {"app_name": app, "args": ""}, "dependencies": [], "risk_level": "low", "requires_approval": False})

        # File tasks
        if any(w in g for w in ("organize", "download", "clean")):
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Organize downloads", "description": "Organize files", "agent": "file", "tool": "organize_downloads", "tool_input": {"downloads_dir": "C:\\Users\\Downloads"}, "dependencies": [], "risk_level": "low", "requires_approval": False})

        # Composite: coding workspace
        if any(w in g for w in ("coding", "prepare", "workspace", "setup")):
            if not tasks:
                tasks.append({"id": "task_1", "title": "System health", "description": "Check system state", "agent": "system", "tool": "get_system_state", "tool_input": {}, "dependencies": [], "risk_level": "low", "requires_approval": False})
            tasks.append({"id": f"task_{len(tasks)+1}", "title": "Open VS Code", "description": "Launch editor", "agent": "application", "tool": "open_application", "tool_input": {"app_name": "code", "args": ""}, "dependencies": [], "risk_level": "low", "requires_approval": False})

        return tasks

    async def execute_plan(self, plan: SubtaskExecutionPlan) -> Dict[str, Any]:
        """Execute plan by calling tools DIRECTLY with self-healing retry."""
        results = {}

        for node_id in plan.task_graph.execution_order:
            node = plan.task_graph.nodes.get(node_id)
            if not node:
                continue

            tool_name = node.input_data.get("tool", "")
            tool_input = node.input_data.get("tool_input", {})

            # If LLM didn't provide a tool name, infer from description
            if not tool_name:
                tool_name = self._infer_tool(node.description, AgentType(node.assigned_agent))

            try:
                tool_fn = self.tool_registry.get(tool_name)
                if tool_fn:
                    # Execute with self-healing retry
                    try:
                        raw_result = await asyncio.to_thread(
                            self.error_handler.wrap, tool_fn, **tool_input
                        )
                    except Exception:
                        # Self-heal exhausted retries, try once without wrapper
                        raw_result = await asyncio.to_thread(tool_fn, **tool_input)
                    output = _format_tool_result(tool_name, raw_result)
                else:
                    output = f"Unknown tool: {tool_name}"

                plan.task_graph.mark_node_status(
                    node_id, TaskStatus.COMPLETED,
                    output_data={"output": output[:500]}
                )
                results[node_id] = output
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                plan.task_graph.mark_node_status(
                    node_id, TaskStatus.FAILED, error=str(e)
                )
                results[node_id] = f"❌ Error: {e}"

        completed = sum(1 for n in plan.task_graph.nodes.values() if n.status == TaskStatus.COMPLETED)
        return {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "completed_steps": completed,
            "total_steps": plan.estimated_steps,
            "results": results,
            "summary": f"Completed {completed}/{plan.estimated_steps} tasks for: {plan.goal}",
        }

    def _infer_tool(self, description: str, agent_type: AgentType) -> str:
        """Infer the best tool from the task description when LLM didn't specify one."""
        d = description.lower()
        if agent_type == AgentType.SYSTEM:
            if any(w in d for w in ("health", "cpu", "ram", "battery", "state", "status")):
                return "get_system_state"
            elif any(w in d for w in ("process", "running")):
                return "get_running_processes"
            elif any(w in d for w in ("network", "internet", "connect", "ping")):
                return "check_network_connectivity"
            elif any(w in d for w in ("disk", "storage", "space")):
                return "get_disk_usage"
            return "get_system_state"
        elif agent_type == AgentType.APPLICATION:
            if any(w in d for w in ("close", "stop", "quit")):
                return "close_application"
            elif any(w in d for w in ("run", "command", "shell", "execute")):
                return "run_shell_command"
            return "open_application"
        elif agent_type == AgentType.FILE:
            if any(w in d for w in ("search", "find")):
                return "search_files"
            elif any(w in d for w in ("organize", "download")):
                return "organize_downloads"
            elif any(w in d for w in ("copy", "move")):
                return "copy_file"
            elif any(w in d for w in ("delete", "remove")):
                return "delete_file"
            elif any(w in d for w in ("compress", "zip")):
                return "compress_files"
            return "list_directory"
        elif agent_type == AgentType.VISION:
            if any(w in d for w in ("screenshot", "capture", "snap")):
                return "take_screenshot"
            elif any(w in d for w in ("ocr", "text", "read")):
                return "ocr_screen"
            elif any(w in d for w in ("error", "scan")):
                return "find_error_on_screen"
            elif any(w in d for w in ("desktop", "items")):
                return "analyze_desktop"
            return "take_screenshot"
        return "get_system_state"


# Singleton
planner_agent = PlannerAgent()
