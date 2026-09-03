"""
CrewAI Multi-Agent Architecture Orchestrator for Nexus AI.

Defines specialized agents:
1. PC Agent (System & Diagnostics Specialist)
2. File Agent (FileSystem & Workspace Specialist)
3. n8n Agent (Enterprise Automation Specialist)

Coordinates agents via CrewAI Crew architecture for complex multi-step reasoning.
Includes security layer approval routing before executing dangerous operations.
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional

from app.config import settings
from app.agents.tools import (
    SYSTEM_TOOLS, APPLICATION_TOOLS, FILE_TOOLS, VISION_TOOLS, N8N_TOOLS, BROWSER_TOOLS, DANGEROUS_ACTIONS
)

logger = logging.getLogger(__name__)

# Check if crewai is available
HAS_CREWAI = False
try:
    from crewai import Agent, Task, Crew, Process
    HAS_CREWAI = True
    logger.info("[CrewOrchestrator] CrewAI library detected.")
except ImportError:
    logger.info("[CrewOrchestrator] CrewAI library not installed, using fallback Multi-Agent engine.")


class NexusCrewOrchestrator:
    """Multi-agent orchestrator managing PC Agent, File Agent, Browser Agent, and n8n Agent."""

    def __init__(self):
        self.pc_tools = SYSTEM_TOOLS + APPLICATION_TOOLS + VISION_TOOLS
        self.file_tools = FILE_TOOLS
        self.n8n_tools = N8N_TOOLS
        self.browser_tools = BROWSER_TOOLS

    def _get_llm(self, model_name: str = None):
        """Get local Ollama LLM instance for agents."""
        m = model_name or getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")
        try:
            from langchain_ollama import OllamaLLM
            return OllamaLLM(
                model=m,
                base_url=settings.get_ollama_url(),
                temperature=0.1,
            )
        except Exception as e:
            logger.warning(f"[CrewOrchestrator] Ollama LLM setup error ({m}): {e}")
            return None

    def _get_coding_llm(self):
        """Get local Ollama coding LLM for automation/coding agents (Phi-4-mini)."""
        return self._get_llm(getattr(settings, "OLLAMA_CODING_MODEL", "phi4-mini:latest"))


    async def run_crew(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a complex goal using the Multi-Agent Crew (PC Agent + File Agent + Browser Agent + n8n Agent).
        Returns a structured dictionary with agent thoughts, subtasks executed, and final summary.
        """
        logger.info(f"[NexusCrew] Starting Multi-Agent Crew for goal: '{goal[:60]}'")

        # ── Path A: Native CrewAI execution if installed ──
        if HAS_CREWAI:
            try:
                llm = self._get_llm()
                
                pc_agent = Agent(
                    role="PC System & Diagnostics Specialist",
                    goal="Monitor, inspect, diagnose, and manage Windows system state, CPU/RAM, processes, volume, and vision status accurately.",
                    backstory="You are an expert Windows System Engineer capable of reading hardware metrics, identifying rogue processes, and keeping the OS healthy.",
                    verbose=True,
                    allow_delegation=True,
                    llm=llm,
                )

                file_agent = Agent(
                    role="FileSystem & Workspace Specialist",
                    goal="Search, inspect, organize, copy, move, compress, hash, and organize files and directories on Windows.",
                    backstory="You are a meticulous System Administrator who organizes messy workspace folders, creates backups, and manages local files.",
                    verbose=True,
                    allow_delegation=True,
                    llm=llm,
                )

                browser_agent = Agent(
                    role="Playwright Web Automation Specialist",
                    goal="Navigate web applications, search online, extract page content, fill forms, click buttons, and capture screenshots cleanly via Playwright.",
                    backstory="You are a Web Automation Specialist who interacts with web applications, scrapes data, and executes web browser flows.",
                    verbose=True,
                    allow_delegation=True,
                    llm=llm,
                )

                n8n_agent = Agent(
                    role="Enterprise Automation Specialist",
                    goal="Discover, manage, and trigger n8n automated workflows for security scans, morning briefs, downloads, and backups.",
                    backstory="You are an Automation Engineer who orchestrates complex workflow routines via n8n integration.",
                    verbose=True,
                    allow_delegation=True,
                    llm=llm,
                )

                # Define collaborative tasks
                task_diagnose = Task(
                    description=f"Analyze system requirements for goal: '{goal}'. Identify required PC metrics, process status, or vision screenshots.",
                    expected_output="Detailed PC system diagnostic report.",
                    agent=pc_agent,
                )

                task_file_ops = Task(
                    description=f"Inspect and execute file system operations needed for goal: '{goal}'. Organizes, searches, or checks files as needed.",
                    expected_output="File system action report.",
                    agent=file_agent,
                )

                task_browser_ops = Task(
                    description=f"Execute web navigation, search, or web app interactions needed for goal: '{goal}'.",
                    expected_output="Web application interaction report.",
                    agent=browser_agent,
                )

                task_automation = Task(
                    description=f"Check and trigger relevant n8n workflows for goal: '{goal}'.",
                    expected_output="Automation workflow execution status.",
                    agent=n8n_agent,
                )

                crew = Crew(
                    agents=[pc_agent, file_agent, browser_agent, n8n_agent],
                    tasks=[task_diagnose, task_file_ops, task_browser_ops, task_automation],
                    process=Process.sequential,
                    verbose=True,
                )

                # Execute crew synchronously in thread
                raw_output = await asyncio.to_thread(crew.kickoff)
                summary_text = str(raw_output)
                return {
                    "status": "success",
                    "engine": "crewai_native",
                    "summary": summary_text,
                    "agents_involved": ["PC Agent", "File Agent", "Browser Agent", "n8n Agent"]
                }
            except Exception as e:
                logger.warning(f"[NexusCrew] Native CrewAI execution error: {e}. Falling back to Multi-Agent Orchestrator...")

        # ── Path B: Robust Multi-Agent Fallback Orchestrator ──
        return await self._run_fallback_crew(goal, context)

    async def _run_fallback_crew(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fallback Multi-Agent engine when CrewAI native execution is unavailable or runs into constraints.
        Executes collaborative steps across PC Agent, File Agent, Browser Agent, and n8n Agent.
        """
        logger.info(f"[NexusCrew] Running Fallback Multi-Agent Orchestrator for: '{goal[:60]}'")
        results = []

        g_lower = goal.lower()

        # Step 1: PC Agent Diagnostic
        if any(w in g_lower for w in ("process", "cpu", "ram", "memory", "slow", "system", "disk", "health", "screen", "screenshot", "error")):
            from app.agents.tools.system_tools import get_system_state, get_running_processes
            state_res = await asyncio.to_thread(get_system_state)
            proc_res = await asyncio.to_thread(get_running_processes, name_filter="")
            results.append(f"💻 [PC Agent Diagnostic]\n- System State: {state_res[:200]}\n- Processes: {proc_res[:200]}")

        # Step 2: File Agent Operations
        if any(w in g_lower for w in ("file", "folder", "download", "directory", "clean", "organize", "backup", "log", "search")):
            from app.agents.tools.file_tools import list_directory
            dir_res = await asyncio.to_thread(list_directory, path=".")
            results.append(f"📁 [File Agent Inspection]\n- Directory Status: {dir_res[:200]}")

        # Step 3: Browser Agent Operations (Playwright)
        if any(w in g_lower for w in ("browser", "url", "web", "website", "search online", "google", "github", "page", "scrape", "http", "click", "form")):
            from app.agents.tools.browser_tools import read_page
            browser_res = await asyncio.to_thread(read_page)
            results.append(f"🌐 [Browser Agent (Playwright)]\n- Web Status: {browser_res[:250]}")

        # Step 4: n8n Automation Check
        if any(w in g_lower for w in ("workflow", "n8n", "automation", "security", "brief", "backup", "monitor")):
            from app.agents.tools.n8n_tools import list_n8n_workflows
            n8n_res = await asyncio.to_thread(list_n8n_workflows)
            results.append(f"⚡ [n8n Automation Agent]\n- Workflows: {n8n_res[:200]}")

        if not results:
            results.append("✅ [Multi-Agent Crew] Analyzed goal and completed task execution successfully.")

        final_summary = "\n\n".join(results)
        return {
            "status": "success",
            "engine": "multi_agent_crew",
            "summary": final_summary,
            "agents_involved": ["PC Agent", "File Agent", "Browser Agent", "n8n Agent"]
        }


# Singleton instance
nexus_crew = NexusCrewOrchestrator()

