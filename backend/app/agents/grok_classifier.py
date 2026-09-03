"""
Intent Classifier — Uses local Ollama (Llama 3) to classify user messages.
Replaces keyword-based routing with intelligent NLP classification.
"""
import json
import logging
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

# Available tools the system can execute
TOOL_DESCRIPTIONS = """
Available system tools:
- open_application: Open any app (chrome, edge, vscode, spotify, telegram, discord, calculator, settings, etc.)
- close_application: Close/kill a running app
- get_system_state: Get CPU, RAM, battery, disk, network status
- get_running_processes: List running apps/processes
- get_disk_usage: Check disk space
- check_network_connectivity: Check internet connection
- set_system_volume: Set volume (0-100)
- set_system_brightness: Set screen brightness (0-100)
- set_system_power: Sleep, shutdown, restart, lock the PC
- take_screenshot: Capture the screen
- ocr_screen: Read text from the screen
- find_error_on_screen: Scan screen for errors
- analyze_desktop: List desktop items
- search_files: Search for files/folders on the PC
- rename_file: Rename a file
- search_and_rename_folder: Find and rename a folder
- copy_file: Copy a file
- delete_file: Delete a file
- compress_files: Zip files
- organize_downloads: Organize the Downloads folder
- list_directory: List files in a directory
- run_shell_command: Execute a shell/terminal command
- open_url_in_browser: Open a URL in the browser
"""

CLASSIFY_PROMPT = """You are Nexus AI's intent classifier. Classify the user's message into exactly ONE of these five categories:

1. "chat" — casual conversation, greetings, simple questions, jokes, opinions, feelings
2. "simple_task" — a single straightforward PC command (e.g. open chrome, lock PC, get system state, set volume to 50, list directory, search files)
3. "complex_task" — a multi-step task requiring planning, sequence of operations, or crew coordination (e.g. "prepare my PC for coding", "check health, clean old files, and do a backup")
4. "vision_task" — requests requiring visual inspection of the screen or screenshot content (e.g. "what is on my screen?", "explain the active window", "extract text from screen", "OCR this screen")
5. "coding_task" — developer/programming requests (e.g. "write a python script to run a local server", "run python script to organize logs", "write code for binary search")

If "simple_task", also extract:
- "tool": the best matching tool name from the list below
- "tool_input": a JSON object with the tool's parameters
- "description": brief description of what to do

{tools}

Respond ONLY with valid JSON. Examples:

User: "hi"
{{"intent": "chat"}}

User: "open chrome"
{{"intent": "simple_task", "tool": "open_application", "tool_input": {{"app_name": "chrome"}}, "description": "Open Google Chrome"}}

User: "what apps are running"
{{"intent": "simple_task", "tool": "get_running_processes", "tool_input": {{"name_filter": ""}}, "description": "List running processes"}}

User: "what's open on my screen right now?"
{{"intent": "vision_task", "description": "Analyze screen content"}}

User: "write a python script that prints hello world"
{{"intent": "coding_task", "description": "Write hello world python script"}}

User: "prepare my PC for coding"
{{"intent": "complex_task", "description": "Prepare PC for coding"}}

User: "check CPU and lock my PC"
{{"intent": "complex_task", "description": "Check CPU and lock PC"}}

Now classify this message:
User: "{message}"
"""


class GrokClassifier:
    """Intent classifier using local Ollama LLM."""

    def __init__(self):
        self.available = True
        self.model = getattr(settings, 'OLLAMA_ROUTER_MODEL', 'qwen3:1.7b')
        try:
            get_url = getattr(settings, 'get_ollama_url', None)
            self.ollama_url = get_url() if callable(get_url) else 'http://localhost:11434'
        except Exception:
            self.ollama_url = 'http://localhost:11434'
        logger.info(f"[GrokClassifier] Initialized with local Ollama Router ({self.model} at {self.ollama_url})")

    async def classify(self, message: str) -> Dict[str, Any]:
        """
        Classify a user message using local Ollama.
        Returns: {"intent": "chat"|"simple_task"|"complex_task"|"vision_task"|"coding_task", "tool": "...", "tool_input": {...}, "description": "..."}
        """
        prompt = CLASSIFY_PROMPT.format(
            tools=TOOL_DESCRIPTIONS,
            message=message.replace('"', '\\"')
        )

        try:
            import httpx
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                raw = data.get("response", "").strip()

            logger.info(f"[GrokClassifier] Raw response: {raw[:200]}")

            # Parse JSON from response (handle markdown code blocks)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)
            return result

        except Exception as e:
            logger.warning(f"[GrokClassifier] Ollama API error/fallback: {e}")
            msg_lower = message.lower()
            if any(w in msg_lower for w in ("youtube", "play", "watch", "channel")):
                return {"intent": "complex_task", "description": message}
            elif any(w in msg_lower for w in ("browser", "chrome", "website", "open url")):
                return {"intent": "simple_task", "tool": "open_url_in_browser", "tool_input": {"url": message}, "description": message}
            elif any(w in msg_lower for w in ("screen", "screenshot", "ocr", "look at", "desktop")):
                return {"intent": "vision_task", "description": message}
            elif any(w in msg_lower for w in ("code", "python", "script", "command")):
                return {"intent": "coding_task", "description": message}
            return {"intent": "unknown"}




# Singleton
grok_classifier = GrokClassifier()

