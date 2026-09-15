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


# ── Fast Compound Keyword Decomposer ──────────────────────────────────────────
def _keyword_decompose_standalone(goal: str) -> List[Dict]:
    """Fast keyword-based decomposition for compound tasks (search + download + email)."""
    g = goal.lower()
    tasks = []

    # 0. Check for Presentation + Email compound tasks
    has_presentation = any(w in g for w in ("ppt", "pptx", "powerpoint", "presentation", "slides", "slide deck", "pitch deck"))
    has_email = any(w in g for w in ("email", "mail", "send to", "@"))
    if has_presentation and has_email:
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", goal)
        recipient = email_match.group(0) if email_match else ""
        return [
            {
                "id": "task_1",
                "title": f"Create Presentation: {goal[:40]}",
                "description": f"Generate modern presentation deck: {goal}",
                "agent": "application",
                "tool": "create_presentation",
                "tool_input": {"prompt": goal},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            },
            {
                "id": "task_2",
                "title": f"Send presentation to {recipient or 'recipient'}",
                "description": f"Send generated presentation to {recipient}: {goal}",
                "agent": "application",
                "tool": "send_intelligent_email",
                "tool_input": {"prompt": goal, "recipient": recipient},
                "dependencies": ["task_1"],
                "risk_level": "medium",
                "requires_approval": False,
            }
        ]

    # 1. Check for compound actions (e.g., search + download + email)
    is_from_folder = bool(re.search(r"\b(?:from|in)\s+downloads?\b", g))
    has_search = any(w in g for w in ("search for", "google for", "find online", "lookup online")) or (("search" in g or "google" in g) and not is_from_folder and "download" not in g)
    has_download = (any(w in g for w in ("download images", "download photos", "save image", "save photo", "save file", "fetch image")) or ("download" in g and not is_from_folder))

    if (has_search and has_download) or (has_download and has_email and not is_from_folder) or (has_search and has_email and not is_from_folder):
        # Extract possible email recipient
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", goal)
        recipient = email_match.group(0) if email_match else ""

        # Extract search query
        search_match = re.search(r"(?i)(?:search|google|find|lookup|look up)\s+(?:for\s+)?(.*?)(?=\s+(?:and|then|after that|to|download|email|mail|\d+)|$)", goal)
        clean_search = search_match.group(1).strip() if search_match else goal
        if not clean_search:
            clean_search = goal

        # Extract count if mentioned
        goal_no_email = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "", goal)
        count_match = re.search(r'\b(\d+)\b', goal_no_email)
        word_numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20}
        img_count = 10
        if count_match:
            img_count = int(count_match.group(1))
        else:
            for word, num in word_numbers.items():
                if word in g:
                    img_count = num
                    break

        is_image_query = any(w in g for w in ("photo", "photos", "image", "images", "picture", "pictures", "wallpaper", "wallpapers", "pic", "pics"))

        if is_image_query:
            # Clean image query terms: "india photo" -> "india"
            clean_search = re.sub(r"(?i)\b(photo|photos|image|images|picture|pictures|wallpaper|wallpapers|pic|pics|hd)\b", "", clean_search).strip()
            if not clean_search:
                clean_search = "india"
            tasks.append({
                "id": f"task_{len(tasks)+1}",
                "title": f"Search & download {img_count} image(s) of '{clean_search[:30]}'",
                "description": f"Search web for images of {clean_search} and download to local disk",
                "agent": "application",
                "tool": "download_images_from_web",
                "tool_input": {"query": clean_search, "count": img_count if img_count != 10 else 3},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            })
        elif has_search and not has_download:
            tasks.append({
                "id": f"task_{len(tasks)+1}",
                "title": f"Search web for '{clean_search[:40]}'",
                "description": f"Deep web search via Playwright for: {clean_search}",
                "agent": "application",
                "tool": "search_web",
                "tool_input": {"query": clean_search},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            })
        elif has_search and has_download:
            tasks.append({
                "id": f"task_{len(tasks)+1}",
                "title": f"Search & download {img_count} images of '{clean_search[:30]}'",
                "description": f"Search web for images of {clean_search} and download {img_count} to local disk",
                "agent": "application",
                "tool": "download_images_from_web",
                "tool_input": {"query": clean_search, "count": img_count},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            })
        elif has_download:
            tasks.append({
                "id": f"task_{len(tasks)+1}",
                "title": f"Download {img_count} images of '{clean_search[:30]}'",
                "description": f"Download {img_count} images related to: {clean_search}",
                "agent": "application",
                "tool": "download_images_from_web",
                "tool_input": {"query": clean_search, "count": img_count},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            })

        if has_email:
            tasks.append({
                "id": f"task_{len(tasks)+1}",
                "title": f"Send email to {recipient or 'recipient'}",
                "description": f"Prepare and send intelligent email: {goal}",
                "agent": "application",
                "tool": "send_intelligent_email",
                "tool_input": {"prompt": goal, "recipient": recipient},
                "dependencies": [f"task_{len(tasks)}"] if tasks else [],
                "risk_level": "medium",
                "requires_approval": True,
            })

        if tasks:
            return tasks

    return []


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

        # ── Check for compound multi-step search/download/email/presentation tasks first (0ms) ──
        compound_res = _keyword_decompose_standalone(goal)
        if compound_res:
            return compound_res

        # ── Presentation / PPT / Pitch Deck Generation (instant, 0ms) ──
        if any(w in g for w in ("ppt", "pptx", "powerpoint", "presentation", "pitch deck", "slides", "slide deck", "create presentation", "make presentation", "generate presentation", "make slides")):
            return [{
                "id": "task_1",
                "title": f"Create Presentation: {goal[:40]}",
                "description": f"Generate modern responsive presentation deck: {goal}",
                "agent": "application",
                "tool": "create_presentation",
                "tool_input": {"prompt": goal},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Blender 3D Scene / Model Generation (instant, 0ms) ──
        if "blender" in g or any(w in g for w in ("create 3d", "make 3d", "render 3d", "3d animation", "3d scene", "3d model")):
            blend_match = re.search(r"(\w+)\.blend", goal, re.IGNORECASE)
            fname = f"{blend_match.group(1)}.blend" if blend_match else "scene.blend"
            is_anim = any(w in g for w in ("animation", "animate", "moving", "video", "frames"))
            return [{
                "id": "task_1",
                "title": f"Create 3D Blender Scene: {goal[:40]}",
                "description": f"Generate procedural 3D scene in Blender with bpy and render: {goal}",
                "agent": "application",
                "tool": "create_blender_scene",
                "tool_input": {
                    "prompt": goal,
                    "filename": fname,
                    "render_image": True,
                    "is_animation": is_anim,
                },
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Email / n8n Workflow (instant, 0ms) ──
        if "@" in g or any(w in g for w in ("send email", "send an email", "send a mail", "send mail", "mail to", "email to", "send my project", "send the report", "send report to", "mail my", "send update to", "send my report", "send project report", "mail regarding", "email regarding")):
            email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", goal)
            recipient = email_match.group(0) if email_match else ""
            return [{
                "id": "task_1",
                "title": f"Send email to {recipient or 'recipient'}",
                "description": f"Draft context-aware email and dispatch via SMTP/n8n: {goal}",
                "agent": "email",
                "tool": "send_intelligent_email",
                "tool_input": {"prompt": goal, "recipient": recipient},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── Financial & Market Intelligence Sentinel (instant, 0ms) ──
        if any(w in g for w in ("stock price", "crypto price", "bitcoin price", "btc price", "eth price", "market analysis", "candlestick chart", "stock chart", "crypto chart", "crypto analysis", "share price")) or (any(w in g for w in ("price of", "chart for", "analysis of", "how is", "track")) and any(s in g for s in ("btc", "eth", "sol", "doge", "bitcoin", "ethereum", "solana", "aapl", "apple", "tsla", "tesla", "nvda", "nvidia", "msft", "nifty", "sensex", "gold", "silver"))):
            sym_match = re.search(r"\b(btc|eth|sol|doge|bitcoin|ethereum|solana|aapl|tsla|nvda|msft|googl|meta|nifty|sensex|gold|silver|crude|[\^A-Za-z0-9\.\-=]{2,10})\b", goal, re.IGNORECASE)
            symbol = sym_match.group(0) if sym_match else "BTC-USD"
            return [{
                "id": "task_1",
                "title": f"Market Analysis for {symbol}",
                "description": f"Fetch real-time data, technical chart, and AI analysis for {symbol}",
                "agent": "application",
                "tool": "get_market_analysis",
                "tool_input": {"symbol": symbol, "period": "1mo", "generate_chart": True},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Autonomous Browser Work Agent (instant, 0ms) ──
        if any(w in g for w in ("download grade", "download report", "download invoice", "grade report", "portal", "student portal", "college portal", "login to", "fill out form", "web workflow", "browser workflow", "scrape web", "extract web")):
            url_match = re.search(r"https?://[^\s]+", goal)
            target_url = url_match.group(0) if url_match else ""
            return [{
                "id": "task_1",
                "title": f"Browser Work Agent: {goal[:40]}",
                "description": f"Execute autonomous closed-loop browser workflow: {goal}",
                "agent": "application",
                "tool": "run_autonomous_browser_workflow",
                "tool_input": {"goal": goal, "url": target_url},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── Autonomous Software Engineering & Code Repair (instant, 0ms) ──
        if any(w in g for w in ("fix bug", "repair code", "debug function", "modify code", "fix error in", "coding agent", "software engineer", "patch code")):
            file_match = re.search(r"([a-zA-Z0-9_\-\\\/\.]+\.py)", goal)
            target_file = file_match.group(1) if file_match else ""
            return [{
                "id": "task_1",
                "title": f"Autonomous Coding Agent: {goal[:40]}",
                "description": f"AST symbol diagnosis and targeted patch with verification: {goal}",
                "agent": "application",
                "tool": "autonomous_coding_task",
                "tool_input": {"goal": goal, "target_file": target_file},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── DevOps & Codebase Testing / Diagnostics (instant, 0ms) ──
        if any(w in g for w in ("run tests", "run pytest", "test codebase", "diagnose tests", "fix tests", "codebase health", "pytest")):
            return [{
                "id": "task_1",
                "title": "Run & Diagnose Tests",
                "description": "Execute pytest suite, analyze failures with LLM, and suggest fixes",
                "agent": "application",
                "tool": "test_and_repair_codebase",
                "tool_input": {"target_dir": "D:\\nexus_ai\\backend", "auto_fix": False, "prompt": goal},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── Document & PDF Q&A (instant, 0ms) ──
        if any(w in g for w in ("analyze document", "summarize pdf", "read pdf", "query document", "ask document", "document qa")):
            file_match = re.search(r"([a-zA-Z0-9_\-\\\/\.]+\.(?:pdf|txt|md|docx))", goal)
            fpath = file_match.group(1) if file_match else ""
            tool_name = "analyze_document" if any(w in g for w in ("summarize", "analyze", "ingest", "read")) else "query_document"
            return [{
                "id": "task_1",
                "title": f"Document Task: {goal[:40]}",
                "description": f"Analyze or query document: {goal}",
                "agent": "application",
                "tool": tool_name,
                "tool_input": {"file_path": fpath, "prompt": goal, "question": goal},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Proactive Morning Briefing (instant, 0ms) ──
        if any(w in g for w in ("morning briefing", "daily briefing", "what's up today", "morning report", "daily digest", "morning update")):
            return [{
                "id": "task_1",
                "title": "Daily Morning Briefing",
                "description": "Fetch weather, market pulse, top tech headlines, and system vitals",
                "agent": "application",
                "tool": "get_morning_briefing",
                "tool_input": {"location": "Chennai"},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Autonomous Deep Research Agent (instant, 0ms) ──
        if any(w in g for w in ("deep research", "research report", "investigate in depth", "deep analysis of", "comprehensive research on")):
            topic = re.sub(r"^(?:deep research|research report on|investigate in depth|deep analysis of|comprehensive research on)\s*", "", goal, flags=re.IGNORECASE).strip() or goal
            return [{
                "id": "task_1",
                "title": f"Deep Research: {topic[:40]}",
                "description": f"Execute multi-hop search, evidence synthesis, and dossier generation for {topic}",
                "agent": "application",
                "tool": "conduct_deep_research",
                "tool_input": {"topic": topic, "depth": "comprehensive"},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Self-Evolving Tool & Skill Creator (instant, 0ms) ──
        if any(w in g for w in ("create a tool to", "create tool to", "write a tool to", "make a tool to", "synthesize tool", "new tool to")):
            tool_name_match = re.search(r"tool\s+(?:called|named)?\s*([a-zA-Z0-9_]+)", goal, re.IGNORECASE)
            t_name = tool_name_match.group(1) if tool_name_match else "custom_agent_tool"
            return [{
                "id": "task_1",
                "title": f"Synthesize New Tool: {t_name}",
                "description": f"Synthesize and hot-reload dynamic Python tool: {goal}",
                "agent": "application",
                "tool": "create_new_tool",
                "tool_input": {"tool_name": t_name, "purpose": goal},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── Autonomous GitHub & Dev Documentation Hub (instant, 0ms) ──
        if any(w in g for w in ("git changelog", "generate changelog", "release notes", "git summary", "draft dev post", "draft linkedin post")):
            if "linkedin" in g or "social" in g or "post" in g:
                platform = "twitter" if "twitter" in g or "tweet" in g else "linkedin"
                return [{
                    "id": "task_1",
                    "title": f"Draft {platform.upper()} Dev Update",
                    "description": "Synthesize recent git commits into an engaging developer post",
                    "agent": "application",
                    "tool": "draft_developer_social_post",
                    "tool_input": {"repo_path": "D:\\nexus_ai", "platform": platform},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                }]
            else:
                return [{
                    "id": "task_1",
                    "title": "Generate Git Changelog",
                    "description": "Analyze recent commit history and produce markdown release notes",
                    "agent": "application",
                    "tool": "generate_git_changelog",
                    "tool_input": {"repo_path": "D:\\nexus_ai", "max_commits": 15},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                }]

        # ── Autonomous Python & App Architect (instant, 0ms) ──
        if any(w in g for w in ("build a", "build an", "create an app", "create a python app", "create a web app", "create a website", "build a website", "build app", "build software", "scaffold app", "scaffold a", "develop an app", "make an app", "make a python app", "build a grocery", "build a face", "generate app", "build application")) or (("build" in g or "create" in g or "scaffold" in g or "develop" in g) and any(w in g for w in ("app", "application", "website", "webapp", "system", "tool", "project", "program"))):
            name_match = re.search(r"(?:app|application|website|project)\s+(?:called|named)?\s*([a-zA-Z0-9_]+)", goal, re.IGNORECASE)
            app_n = name_match.group(1) if name_match else None
            return [{
                "id": "task_1",
                "title": f"Build Application: {goal[:40]}",
                "description": f"Provision virtual environment, install dependencies, and build complete software: {goal}",
                "agent": "application",
                "tool": "build_autonomous_application",
                "tool_input": {"prompt": goal, "app_name": app_n},
                "dependencies": [],
                "risk_level": "medium",
                "requires_approval": False,
            }]

        # ── SecOps & Security Auditor (instant, 0ms) ──
        if any(w in g for w in ("audit security", "scan security", "check vulnerabilities", "secops audit", "security scorecard", "audit codebase")):
            return [{
                "id": "task_1",
                "title": "SecOps Codebase Security Audit",
                "description": "Perform static analysis, secret leak detection, and compute Security Grade",
                "agent": "application",
                "tool": "audit_codebase_security",
                "tool_input": {"target_path": "D:\\nexus_ai\\backend"},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Second Brain & Personal Knowledge Graph (instant, 0ms) ──
        if any(w in g for w in ("take a note", "take note", "save note", "remember that", "add task", "second brain", "search notes", "query vault")):
            if any(w in g for w in ("search notes", "query vault", "search second brain", "find note")):
                q = re.sub(r"^(?:search notes|query vault|search second brain|find note)\s*(?:for|about)?\s*", "", goal, flags=re.IGNORECASE).strip() or goal
                return [{
                    "id": "task_1",
                    "title": f"Search Second Brain: {q[:30]}",
                    "description": f"Search Obsidian vault notes for '{q}'",
                    "agent": "application",
                    "tool": "query_second_brain",
                    "tool_input": {"query": q},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                }]
            else:
                return [{
                    "id": "task_1",
                    "title": f"Capture Thought: {goal[:30]}",
                    "description": f"File note/task into Second Brain vault: {goal}",
                    "agent": "application",
                    "tool": "capture_thought_or_note",
                    "tool_input": {"text": goal, "category": "auto"},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                }]

        # ── Live Meeting & Audio Note-Taking Assistant (instant, 0ms) ──
        if any(w in g for w in ("summarize meeting", "meeting minutes", "meeting summary", "meeting notes")):
            return [{
                "id": "task_1",
                "title": "Executive Meeting Minutes",
                "description": f"Extract summary, decisions, and action items matrix: {goal}",
                "agent": "application",
                "tool": "summarize_meeting_audio",
                "tool_input": {"transcript_text": goal, "meeting_title": "Executive Session"},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # ── Council of Experts Multi-Agent Debate (instant, 0ms) ──
        if any(w in g for w in ("council debate", "ask council", "expert debate", "council of experts", "debate with council")):
            topic = re.sub(r"^(?:council debate|ask council|expert debate|council of experts|debate with council)\s*(?:on|about)?\s*", "", goal, flags=re.IGNORECASE).strip() or goal
            return [{
                "id": "task_1",
                "title": f"Council of Experts: {topic[:40]}",
                "description": f"3-expert adversarial debate (Visionary, Skeptic, Pragmatist) on {topic}",
                "agent": "application",
                "tool": "deliberate_with_council",
                "tool_input": {"topic": topic},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

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
    # Blender 3D scene descriptions often contain commas (bed, desk, chair) - do NOT treat as compound
    if "blender" in g or any(w in g for w in ("create 3d", "make 3d", "render 3d", "3d scene", "3d animation")):
        return False

    # Email requests often mention recipients or multiple clauses ("now send a mail to X regarding Y") - do NOT treat as compound
    if "@" in g or any(w in g for w in ("send email", "send an email", "send a mail", "send mail", "mail to", "email to")):
        return False

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
        set_system_volume, open_url_in_browser, send_intelligent_email,
        download_images_from_web,
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
    from app.agents.tools.blender_tools import (
        create_blender_scene,
    )
    from app.agents.tools.presentation_tools import (
        create_presentation,
    )
    from app.agents.tools.document_tools import (
        analyze_document, query_document,
    )
    from app.agents.tools.devops_tools import (
        test_and_repair_codebase,
    )
    from app.agents.tools.finance_tools import (
        get_market_analysis,
    )
    from app.agents.tools.skill_creator_tools import (
        create_new_tool, list_custom_tools,
    )
    from app.agents.tools.gui_tools import (
        execute_gui_actions, click_screen_text,
    )
    from app.agents.tools.research_tools import (
        conduct_deep_research,
    )
    from app.agents.tools.sentinel_tools import (
        get_morning_briefing, check_system_sentinel,
    )
    from app.agents.tools.github_tools import (
        generate_git_changelog, draft_developer_social_post,
    )
    from app.agents.tools.app_architect_tools import (
        build_autonomous_application,
    )
    from app.agents.tools.secops_tools import (
        audit_codebase_security,
    )
    from app.agents.tools.second_brain_tools import (
        capture_thought_or_note, query_second_brain,
    )
    from app.agents.tools.meeting_tools import (
        summarize_meeting_audio,
    )
    from app.agents.tools.council_tools import (
        deliberate_with_council,
    )
    from app.agents.tools.browser_tools import (
        open_browser, open_url, search_web, read_page,
        click_element, fill_form, download_file, upload_file,
        take_browser_screenshot, get_page_text, close_browser,
        inject_domain_credentials, autofill_profile_form,
        run_autonomous_browser_workflow,
    )
    from app.agents.tools.coding_tools import (
        search_codebase_symbols, get_file_symbol_outline,
        get_symbol_implementation, apply_targeted_diff,
        run_unit_tests, manage_dev_server,
    )
    from app.agents.autonomous_coding_agent import autonomous_coding_agent
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
        "send_intelligent_email": send_intelligent_email.func,
        "download_images_from_web": download_images_from_web.func,
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
        # Blender 3D tools
        "create_blender_scene": create_blender_scene.func,
        # Presentation generation
        "create_presentation": create_presentation.func,
        # Document Q&A tools
        "analyze_document": analyze_document.func,
        "query_document": query_document.func,
        # DevOps maintainer
        "test_and_repair_codebase": test_and_repair_codebase.func,
        # Financial sentinel
        "get_market_analysis": get_market_analysis.func,
        # Self-Evolving Tool Creator
        "create_new_tool": create_new_tool.func,
        "list_custom_tools": list_custom_tools.func,
        # Omni-GUI Computer Copilot
        "execute_gui_actions": execute_gui_actions.func,
        "click_screen_text": click_screen_text.func,
        # Deep Research Agent
        "conduct_deep_research": conduct_deep_research.func,
        # Proactive Sentinel & Briefing
        "get_morning_briefing": get_morning_briefing.func,
        "check_system_sentinel": check_system_sentinel.func,
        # GitHub & Dev Hub
        "generate_git_changelog": generate_git_changelog.func,
        "draft_developer_social_post": draft_developer_social_post.func,
        # App Architect (Venv + Pip + Code)
        "build_autonomous_application": build_autonomous_application.func,
        # SecOps Sentinel
        "audit_codebase_security": audit_codebase_security.func,
        # Second Brain Vault
        "capture_thought_or_note": capture_thought_or_note.func,
        "query_second_brain": query_second_brain.func,
        # Meeting Assistant
        "summarize_meeting_audio": summarize_meeting_audio.func,
        # Council of Experts
        "deliberate_with_council": deliberate_with_council.func,
        # Browser tools (Playwright & Autonomous Work Agent)
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
        "inject_domain_credentials": inject_domain_credentials.func,
        "autofill_profile_form": autofill_profile_form.func,
        "run_autonomous_browser_workflow": run_autonomous_browser_workflow.func,
        # Autonomous Software Engineer & Codebase Intelligence
        "search_codebase_symbols": search_codebase_symbols.func,
        "get_file_symbol_outline": get_file_symbol_outline.func,
        "get_symbol_implementation": get_symbol_implementation.func,
        "apply_targeted_diff": apply_targeted_diff.func,
        "run_unit_tests": run_unit_tests.func,
        "manage_dev_server": manage_dev_server.func,
        "autonomous_coding_task": lambda goal, target_file=None: asyncio.run(autonomous_coding_agent.execute_task(goal=goal, target_file=target_file)),
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
        elif tool_name == "download_images_from_web":
            if result.get("success"):
                files = result.get("downloaded", [])
                file_list = "\n".join(f"  📷 {os.path.basename(f)}" for f in files[:10])
                return (
                    f"📥 Downloaded {len(files)} images to: {result.get('download_dir', '?')}\n"
                    f"{file_list}"
                )
            return f"❌ Image download failed: {result.get('error', 'Unknown')}"
        elif tool_name == "send_intelligent_email":
            if result.get("success"):
                return (
                    f"📧 Email sent to {result.get('recipient', '?')}\n"
                    f"  Subject: {result.get('subject', '?')}\n"
                    f"  Attachments: {', '.join(result.get('attachments', [])) or 'None'}\n"
                    f"  Engine: {result.get('message', 'Dispatched')}"
                )
            return f"❌ Email failed: {result.get('error', 'Unknown')}"
        elif tool_name == "create_presentation":
            if result.get("success"):
                return (
                    f"📊 Presentation Generated Successfully!\n"
                    f"  Topic: {result.get('topic', 'Presentation')}\n"
                    f"  Slides: {result.get('total_slides', 0)}\n"
                    f"  File: {result.get('file_path', '')}\n"
                    f"  Format: {result.get('format', 'HTML5 Deck')}"
                )
            return f"❌ Presentation generation failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "get_market_analysis":
            if result.get("success"):
                return result.get("formatted_summary", f"Market data for {result.get('symbol')}: ${result.get('current_price')}")
            return f"❌ Market data fetch failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "test_and_repair_codebase":
            if result.get("success"):
                if result.get("status") == "ALL_PASSED":
                    return f"✅ {result.get('summary', 'All tests passed!')}"
                diag = result.get("analysis", "")
                fix = result.get("proposed_fix", "")
                return (
                    f"⚠️ {result.get('summary')}\n\n"
                    f"🔍 Diagnostics:\n{diag}\n\n"
                    f"💡 Suggested Fix:\n{fix}"
                )
            return f"❌ DevOps test runner failed: {result.get('error', 'Unknown error')}"
        elif tool_name in ("analyze_document", "query_document"):
            if result.get("success"):
                if tool_name == "analyze_document":
                    takeaways = "\n".join(f"• {t}" for t in result.get("key_takeaways", []))
                    return (
                        f"📄 Document Analyzed ({result.get('filename')}, {result.get('total_pages', 1)} pages, {result.get('word_count', 0)} words):\n\n"
                        f"📝 Summary:\n{result.get('summary', '')}\n\n"
                        f"📌 Key Takeaways:\n{takeaways}"
                    )
                else:
                    return f"❓ Q&A Result ({result.get('source_document', 'Doc')}):\n\n{result.get('answer', '')}"
            return f"❌ Document processing failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "create_new_tool":
            if result.get("success"):
                return f"🧠 Tool '{result.get('tool_name')}' Synthesized & Registered!\n  File: {result.get('file_path')}\n  Status: {result.get('message')}"
            return f"❌ Tool synthesis failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "list_custom_tools":
            if result.get("success"):
                tools = result.get("tools", [])
                lines = "\n".join(f"  • {t['name']}" for t in tools) if tools else "  None created yet."
                return f"🧠 Dynamic Custom Tools ({result.get('count', 0)}):\n{lines}"
            return f"❌ Failed to list tools: {result.get('error')}"
        elif tool_name in ("execute_gui_actions", "click_screen_text"):
            if result.get("success"):
                steps = "\n".join(f"  {s}" for s in result.get("executed_steps", [])) if result.get("executed_steps") else f"  {result.get('message')}"
                return f"👁️ GUI Copilot Execution:\n{steps}"
            return f"❌ GUI action failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "conduct_deep_research":
            if result.get("success"):
                return (
                    f"🔬 Deep Research Dossier Generated ({result.get('topic')})!\n"
                    f"  Evidence Sources: {result.get('sources_count', 0)}\n"
                    f"  Markdown Dossier: {result.get('report_md_path')}\n"
                    f"  HTML Dossier: {result.get('report_html_path')}\n\n"
                    f"📝 Executive Summary:\n{result.get('executive_summary', '')}"
                )
            return f"❌ Deep research failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "get_morning_briefing":
            if result.get("success"):
                return result.get("briefing_text", "Morning briefing ready.")
            return f"❌ Morning briefing failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "check_system_sentinel":
            if result.get("success"):
                st = result.get("stats", {})
                alerts = ", ".join(result.get("alerts", [])) if result.get("alerts") else "All thresholds nominal."
                return f"🛡️ Sentinel Check:\n  CPU: {st.get('cpu')}% | RAM: {st.get('ram')}%\n  Status: {alerts}"
            return f"❌ Sentinel check failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "generate_git_changelog":
            if result.get("success"):
                return f"🐙 Git Changelog ({result.get('branch', 'main')}, {result.get('commits_analyzed', 0)} commits):\n\n{result.get('changelog', '')}"
            return f"❌ Changelog failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "draft_developer_social_post":
            if result.get("success"):
                return f"📱 Developer Social Post ({result.get('platform', 'Dev')})\n\n{result.get('post_content', '')}"
            return f"❌ Social post draft failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "build_autonomous_application":
            if result.get("success"):
                return result.get("summary", "Application built successfully.")
            return f"❌ Application build failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "audit_codebase_security":
            if result.get("success"):
                return result.get("formatted_report", "Security audit complete.")
            return f"❌ Security audit failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "capture_thought_or_note":
            if result.get("success"):
                return f"🧠 Second Brain: {result.get('message')}\n  File: {result.get('file_path')}"
            return f"❌ Note capture failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "query_second_brain":
            if result.get("success"):
                lines = "\n".join(f"  • {r['file']}: {r['snippet'][:80]}..." for r in result.get('results', []))
                return f"🧠 Second Brain Vault Search ({result.get('count', 0)} matches):\n{lines or '  No notes found.'}"
            return f"❌ Vault search failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "summarize_meeting_audio":
            if result.get("success"):
                return f"📋 Meeting Minutes Generated ({result.get('meeting_title')}):\n\n{result.get('minutes', '')}"
            return f"❌ Meeting processing failed: {result.get('error', 'Unknown error')}"
        elif tool_name == "deliberate_with_council":
            if result.get("success"):
                return result.get("deliberation", "Council debate complete.")
            return f"❌ Council debate failed: {result.get('error', 'Unknown error')}"
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
            m = getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")
            logger.info(f"[Planner] Attempting decomposition with local Ollama: {m}")
            current_llm = get_llm(m)
            prompt_val = await DECOMPOSITION_PROMPT.ainvoke({
                "goal": goal,
                "system_state": state_str,
                "memory_context": memory_context[:400],
            })
            raw = await current_llm.ainvoke(prompt_val.to_string())
            cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
            
            import json
            for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```", r"(\[[\s\S]*\])"]:
                match = re.search(pattern, cleaned)
                if match:
                    try:
                        res = json.loads(match.group(1))
                        if isinstance(res, list):
                            logger.info(f"[Planner] Successful decomposition using local Ollama ({len(res)} subtasks)")
                            return res
                    except Exception:
                        continue
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
        if not raw_subtasks:
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

        if not raw_subtasks:
            logger.info(f"[Planner] Falling back to keyword decomposer for: {goal[:60]}")
            raw_subtasks = self._keyword_decompose(goal)

        if not raw_subtasks:
            raw_subtasks = [{
                "id": "task_1",
                "title": f"Execute request: {goal[:50]}",
                "description": goal,
                "agent": "system",
                "tool": "run_shell_command",
                "tool_input": {"command": goal},
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

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

        # 0. Blender 3D Scene / Model Generation (instant, 0ms)
        if "blender" in g or any(w in g for w in ("create 3d", "make 3d", "render 3d", "3d animation", "3d scene", "3d model")):
            blend_match = re.search(r"(\w+)\.blend", goal, re.IGNORECASE)
            fname = f"{blend_match.group(1)}.blend" if blend_match else "scene.blend"
            is_anim = any(w in g for w in ("animation", "animate", "moving", "video", "frames"))
            return [{
                "id": "task_1",
                "title": f"Create 3D Blender Scene: {goal[:40]}",
                "description": f"Generate procedural 3D scene in Blender with bpy and render: {goal}",
                "agent": "application",
                "tool": "create_blender_scene",
                "tool_input": {
                    "prompt": goal,
                    "filename": fname,
                    "render_image": True,
                    "is_animation": is_anim,
                },
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]

        # 1. Check for compound actions (e.g., search + download + email)
        has_search = any(w in g for w in ("search", "google", "find online", "lookup", "look up"))
        has_download = any(w in g for w in ("download", "save image", "save photo", "save file", "fetch image"))
        has_email = any(w in g for w in ("email", "mail", "send to", "@"))

        if has_search or has_download or has_email:
            # Extract possible email recipient
            email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", goal)
            recipient = email_match.group(0) if email_match else ""

            # Extract search query
            search_match = re.search(r"(?i)(?:search|google|find|lookup|look up)\s+(?:for\s+)?(.*?)(?=\s+(?:and|then|after that|to|download|email|mail|\d+)|$)", goal)
            clean_search = search_match.group(1).strip() if search_match else goal
            if not clean_search:
                clean_search = goal

            # Extract count if mentioned (e.g. "download ten images")
            # Strip email addresses first so digits inside them aren't matched
            goal_no_email = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "", goal)
            count_match = re.search(r'\b(\d+)\b', goal_no_email)
            word_numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20}
            img_count = 10
            if count_match:
                img_count = int(count_match.group(1))
            else:
                for word, num in word_numbers.items():
                    if word in g:
                        img_count = num
                        break

            is_image_query = any(w in g for w in ("photo", "photos", "image", "images", "picture", "pictures", "wallpaper", "wallpapers", "pic", "pics"))

            if is_image_query:
                # Clean image query terms: "india photo" -> "india"
                clean_search = re.sub(r"(?i)\b(photo|photos|image|images|picture|pictures|wallpaper|wallpapers|pic|pics|hd)\b", "", clean_search).strip()
                if not clean_search:
                    clean_search = "india"
                tasks.append({
                    "id": f"task_{len(tasks)+1}",
                    "title": f"Search & download {img_count} image(s) of '{clean_search[:30]}'",
                    "description": f"Search web for images of {clean_search} and download to local disk",
                    "agent": "application",
                    "tool": "download_images_from_web",
                    "tool_input": {"query": clean_search, "count": img_count if img_count != 10 else 3},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                })
            elif has_search and not has_download:
                # Pure search → use search_web (Playwright deep search)
                tasks.append({
                    "id": f"task_{len(tasks)+1}",
                    "title": f"Search web for '{clean_search[:40]}'",
                    "description": f"Deep web search via Playwright for: {clean_search}",
                    "agent": "application",
                    "tool": "search_web",
                    "tool_input": {"query": clean_search},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                })
            elif has_search and has_download:
                # Search + Download → use download_images_from_web (does both)
                tasks.append({
                    "id": f"task_{len(tasks)+1}",
                    "title": f"Search & download {img_count} images of '{clean_search[:30]}'",
                    "description": f"Search web for images of {clean_search} and download {img_count} to local disk",
                    "agent": "application",
                    "tool": "download_images_from_web",
                    "tool_input": {"query": clean_search, "count": img_count},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                })
            elif has_download:
                # Download only
                tasks.append({
                    "id": f"task_{len(tasks)+1}",
                    "title": f"Download {img_count} images of '{clean_search[:30]}'",
                    "description": f"Download {img_count} images related to: {clean_search}",
                    "agent": "application",
                    "tool": "download_images_from_web",
                    "tool_input": {"query": clean_search, "count": img_count},
                    "dependencies": [],
                    "risk_level": "low",
                    "requires_approval": False,
                })

            if has_email:
                tasks.append({
                    "id": f"task_{len(tasks)+1}",
                    "title": f"Send email to {recipient or 'recipient'}",
                    "description": f"Prepare and send intelligent email: {goal}",
                    "agent": "application",
                    "tool": "send_intelligent_email",
                    "tool_input": {"prompt": goal, "recipient": recipient},
                    "dependencies": [f"task_{len(tasks)}"] if tasks else [],
                    "risk_level": "medium",
                    "requires_approval": True,
                })

            if tasks:
                return tasks

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
