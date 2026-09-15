"""
NLP Intent Parser — understands natural language commands via Llama 3.
Ported from JIN/JARVIS IntentParser. Sits between the fast IntentRouter
and the heavy LLM decomposition as a lightweight classification step.

Flow: User text → IntentRouter (keyword) → IntentParser (LLM classify) → Full Decomposition
"""
import json
import re
import logging
from typing import Dict, List, Optional

from langchain_ollama import OllamaLLM
from app.config import settings

logger = logging.getLogger(__name__)

# Focused intent classification prompt — much faster than full decomposition
INTENT_CLASSIFY_PROMPT = """You are the Nexus AI intent classifier. Given a user's natural language message, classify it into exactly ONE intent and extract parameters.

User message: "{user_input}"

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "intent": "<intent_type>",
  "agent": "<agent_type>",
  "tool": "<tool_name>",
  "tool_input": {{<parameters>}},
  "confidence": <0.0-1.0>
}}

Intent types and their tools:
- "system_health" → agent: "system", tool: "get_system_state", tool_input: {{}}
- "check_cpu" → agent: "system", tool: "get_system_state", tool_input: {{}}
- "check_disk" → agent: "system", tool: "get_disk_usage", tool_input: {{"path": "C:\\\\"}}
- "check_network" → agent: "system", tool: "check_network_connectivity", tool_input: {{"host": "8.8.8.8"}}
- "list_processes" → agent: "system", tool: "get_running_processes", tool_input: {{"name_filter": ""}}
- "kill_process" → agent: "system", tool: "kill_process", tool_input: {{"pid": <number>}}
- "open_app" → agent: "application", tool: "open_application", tool_input: {{"app_name": "<name>", "args": ""}}
- "close_app" → agent: "application", tool: "close_application", tool_input: {{"app_name": "<name>"}}
- "run_command" → agent: "application", tool: "run_shell_command", tool_input: {{"command": "<cmd>", "timeout": 30}}
- "search_files" → agent: "file", tool: "search_files", tool_input: {{"directory": ".", "pattern": "<pattern>"}}
- "list_files" → agent: "file", tool: "list_directory", tool_input: {{"path": "<dir>"}}
- "organize_downloads" → agent: "file", tool: "organize_downloads", tool_input: {{"downloads_dir": "C:\\\\Users\\\\Downloads"}}
- "set_brightness" → agent: "system", tool: "set_system_brightness", tool_input: {{"level": <number>}}
- "set_volume" → agent: "application", tool: "set_system_volume", tool_input: {{"level": <number>}}
- "sleep_pc" → agent: "system", tool: "set_system_power", tool_input: {{"action": "sleep"}}
- "shutdown_pc" → agent: "system", tool: "set_system_power", tool_input: {{"action": "shutdown"}}
- "restart_pc" → agent: "system", tool: "set_system_power", tool_input: {{"action": "restart"}}
- "lock_pc" → agent: "system", tool: "set_system_power", tool_input: {{"action": "lock"}}
- "delete_file" → agent: "file", tool: "delete_file", tool_input: {{"path": "<path>"}}
- "copy_file" → agent: "file", tool: "copy_file", tool_input: {{"source": "<src>", "destination": "<dst>"}}
- "take_screenshot" → agent: "vision", tool: "take_screenshot", tool_input: {{}}
- "ocr_screen" → agent: "vision", tool: "ocr_screen", tool_input: {{}}
- "find_errors" → agent: "vision", tool: "find_error_on_screen", tool_input: {{}}
- "analyze_desktop" → agent: "vision", tool: "analyze_desktop", tool_input: {{}}
- "vision_status" → agent: "vision", tool: "get_vision_status", tool_input: {{}}
- "complex_goal" → Use this ONLY if the request requires multiple steps (e.g., "prepare my laptop for coding")
- "chitchat" → Use this for greetings, jokes, casual conversation

Examples:
"can you open chrome for me" → {{"intent":"open_app","agent":"application","tool":"open_application","tool_input":{{"app_name":"chrome","args":""}},"confidence":0.95}}
"how much battery is left" → {{"intent":"system_health","agent":"system","tool":"get_system_state","tool_input":{{}},"confidence":0.92}}
"take a screenshot of my desktop" → {{"intent":"take_screenshot","agent":"vision","tool":"take_screenshot","tool_input":{{}},"confidence":0.95}}
"I need to browse the internet" → {{"intent":"open_app","agent":"application","tool":"open_application","tool_input":{{"app_name":"chrome","args":""}},"confidence":0.88}}
"what apps are running right now" → {{"intent":"list_processes","agent":"system","tool":"get_running_processes","tool_input":{{"name_filter":""}},"confidence":0.90}}
"prepare my laptop for coding" → {{"intent":"complex_goal","agent":"system","tool":"","tool_input":{{}},"confidence":0.85}}
"hey how are you" → {{"intent":"chitchat","agent":"system","tool":"","tool_input":{{}},"confidence":0.90}}
"""


class IntentParser:
    """
    Lightweight NLP intent classifier using Llama 3.
    Much faster than full task decomposition — single focused LLM call.
    """

    def __init__(self):
        url = settings.get_ollama_url()
        model_name = getattr(settings, "OLLAMA_ROUTER_MODEL", "qwen3:1.7b")
        logger.info(f"[IntentParser] Using local Ollama LLM: {model_name}")
        self.llm = OllamaLLM(
            model=model_name,
            base_url=url,
            temperature=0.1,
            num_predict=256,  # Short response — just JSON
        )


    def _extract_json(self, text: str) -> Optional[Dict]:
        """Robustly extract JSON from LLM output, stripping reasoning tags if present."""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fences
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```", r"(\{[\s\S]*\})"]:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return None

    async def classify(self, user_input: str) -> Optional[Dict]:
        """
        Classify a natural language input into an intent + tool mapping.
        Returns a subtask dict if classified, None if it's a complex_goal
        or classification fails (caller should use full LLM decomposition).
        """
        prompt = INTENT_CLASSIFY_PROMPT.format(user_input=user_input)

        try:
            raw = await self.llm.ainvoke(prompt)
            result = self._extract_json(raw)

            if not result:
                logger.warning(f"[IntentParser] Could not parse LLM response for: {user_input[:50]}")
                return None

            intent = result.get("intent", "")
            confidence = result.get("confidence", 0.0)

            # If it's a complex goal or chitchat, let the caller handle it
            if intent in ("complex_goal", "chitchat", "unknown") or confidence < 0.6:
                logger.info(f"[IntentParser] Intent '{intent}' (conf={confidence}) → delegating to decomposer")
                return None

            tool = result.get("tool", "")
            if not tool:
                return None

            # Build subtask dict
            logger.info(f"[IntentParser] NLP classified: '{user_input[:40]}' → {intent} / {tool} (conf={confidence})")
            return {
                "id": "task_1",
                "title": result.get("intent", "").replace("_", " ").title(),
                "description": user_input,
                "agent": result.get("agent", "system"),
                "tool": tool,
                "tool_input": result.get("tool_input", {}),
                "dependencies": [],
                "risk_level": "high" if tool in ("delete_file", "kill_process", "set_system_power", "run_shell_command") else "low",
                "requires_approval": tool in ("delete_file", "kill_process", "set_system_power", "run_shell_command"),
            }

        except Exception as e:
            logger.warning(f"[IntentParser] LLM classify failed: {e}")
            return None


# Singleton
intent_parser = IntentParser()
