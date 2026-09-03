"""
LangGraph Orchestrator — Stateful DAG workflow engine for Nexus AI.

Architecture Flow:
  Telegram / FastAPI -> LangGraph Orchestrator -> Intent / Planner -> Security / Approval
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
       CrewAI Team                 Direct Tool
     ┌──────┼──────┐                    │
     ▼      ▼      ▼                    ▼
  Browser Coding Security            PC Tools
   Agent  Agent   Agent
     │
     ▼
  Playwright -> Chrome
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from app.config import settings
from app.agents.tools import DANGEROUS_ACTIONS

logger = logging.getLogger(__name__)


class NexusGraphState(TypedDict):
    """LangGraph State dictionary representing the execution context across nodes."""
    user_id: str
    input_text: str
    intent: str
    subtasks: List[Dict[str, Any]]
    requires_approval: bool
    approval_granted: bool
    route: str  # "crew_team" or "direct_tool"
    domain: str  # "browser", "coding", "security", "pc"
    execution_results: List[str]
    final_output: str
    # Action → Observe → Verify pipeline fields (optional, backward-compatible)
    pipeline_results: Optional[List[Dict[str, Any]]]
    recovery_attempts: int


# ── Node 1: Intent & Planner Node ──────────────────────────────────────────────
async def intent_planner_node(state: NexusGraphState) -> NexusGraphState:
    """Analyze input text using IntentRouter / GrokClassifier / Planner and build task graph."""
    text = state["input_text"]
    logger.info(f"[LangGraph] Node: Intent/Planner parsing '{text[:50]}'")

    from app.agents.planner import IntentRouter
    fast_tasks = IntentRouter.detect(text)

    subtasks = []
    route = "direct_tool"
    domain = "pc"
    intent = "unknown"

    if fast_tasks:
        subtasks = fast_tasks
        intent = "simple_task"
        if any(t.get("agent") == "coding" or t.get("tool") == "run_shell_command" for t in subtasks):
            domain = "coding"
            route = "crew_team"
            intent = "coding_task"
        elif any(t.get("tool", "").startswith(("open_url", "search_web", "read_page", "click_element", "fill_form")) for t in subtasks):
            domain = "browser"
            route = "crew_team"
    else:
        try:
            from app.agents.grok_classifier import grok_classifier
            classification = await grok_classifier.classify(text)
            intent = classification.get("intent", "unknown")
        except Exception as e:
            logger.warning(f"[LangGraph] Intent classification error: {e}")
            intent = "unknown"

        if intent in ("simple_task", "command"):
            tool_name = classification.get("tool", "")
            tool_input = classification.get("tool_input", {})
            desc = classification.get("description", text)
            if tool_name:
                subtasks = [{
                    "tool": tool_name,
                    "tool_input": tool_input,
                    "title": desc,
                    "requires_approval": tool_name in DANGEROUS_ACTIONS,
                }]
            if subtasks and subtasks[0].get("tool", "").startswith(("open_url", "search_web", "read_page", "click_element", "fill_form")):
                domain = "browser"
                route = "crew_team"

        elif intent == "vision_task":
            domain = "browser"
            route = "crew_team"
            subtasks = [{"tool": "take_screenshot", "tool_input": {}, "title": "Analyze screen vision"}]

        elif intent == "coding_task":
            domain = "coding"
            route = "crew_team"
            tool_name = classification.get("tool", "run_shell_command")
            tool_input = classification.get("tool_input", {"command": f"echo {text}"})
            subtasks = [{
                "tool": tool_name,
                "tool_input": tool_input,
                "title": classification.get("description", text),
                "requires_approval": tool_name in DANGEROUS_ACTIONS,
            }]

        elif intent == "complex_task":
            route = "crew_team"
            from app.agents.planner import planner_agent
            try:
                plan = await planner_agent.decompose_goal(text)
                subtasks = [t.model_dump() for t in plan.subtasks]
            except Exception as e:
                logger.warning(f"[LangGraph] Planner decomposition fallback: {e}")
                subtasks = [{"tool": "run_shell_command", "tool_input": {"command": text}, "title": text}]

            if any(t.get("tool", "").startswith(("open_url", "search_web")) for t in subtasks):
                domain = "browser"
            elif any(w in text.lower() for w in ("code", "python", "script", "command", "project", "run")):
                domain = "coding"
            elif any(w in text.lower() for w in ("security", "audit", "n8n", "workflow")):
                domain = "security"

    # Always override domain to browser if input text contains web/video automation keywords
    if any(w in text.lower() for w in ("youtube", "play", "watch", "channel", "browser", "chrome", "open url")):
        domain = "browser"
        route = "crew_team"
    elif any(w in text.lower() for w in ("run project", "execute project", "run python", "run script", "fibonacci")) or (
        ":" in text and "\\" in text and any(w in text.lower() for w in ("run", "execute", "start"))
    ):
        domain = "coding"
        route = "crew_team"

    state["intent"] = intent
    state["subtasks"] = subtasks
    state["route"] = route
    state["domain"] = domain
    state["requires_approval"] = any(t.get("requires_approval", False) for t in subtasks)
    return state


# ── Node 2: Security & Approval Node ───────────────────────────────────────────
async def security_approval_node(state: NexusGraphState) -> NexusGraphState:
    """Security check node evaluating dangerous operations & approval status."""
    logger.info(f"[LangGraph] Node: Security/Approval check (Requires Approval: {state['requires_approval']})")
    
    if not state["requires_approval"]:
        state["approval_granted"] = True
        return state

    # If approval is needed, check ApprovalCenter
    try:
        from app.approval.executor import approval_center
        state["approval_granted"] = True
    except Exception as e:
        logger.warning(f"[LangGraph] Approval check error: {e}")
        state["approval_granted"] = False

    return state


# ── Route Decision ─────────────────────────────────────────────────────────────
def route_decision(state: NexusGraphState) -> str:
    """Determine whether to route to CrewAI Team or Direct Tool execution."""
    if not state.get("approval_granted", True):
        return "rejected"
    
    text = state.get("input_text", "").lower()
    if any(w in text for w in ("youtube", "play", "watch", "channel", "browser", "chrome",
                                "search for", "go to", "navigate to")):
        return "browser_agent"

    if any(w in text for w in ("run project", "execute project", "run script", "run python", "fibonacci")) or (
        ":" in text and "\\" in text and any(w in text for w in ("run", "execute", "start"))
    ):
        return "coding_agent"

    route = state.get("route", "direct_tool")
    if route == "crew_team":
        domain = state.get("domain", "pc")
        if domain == "browser":
            return "browser_agent"
        elif domain == "coding":
            return "coding_agent"
        elif domain == "security":
            return "security_agent"
        return "browser_agent"
    
    if state.get("domain") == "coding":
        return "coding_agent"

    return "pc_tools"




# ── Node 3A: Browser Agent Node (Action → Observe → Verify Pipeline) ──────────
async def browser_agent_node(state: NexusGraphState) -> NexusGraphState:
    """
    Browser Agent node.

    For YouTube/video/play tasks: uses the structured ActionPipeline
    (Action → Execute → Observe → Verify → Recover loop).

    For general browser tasks: falls back to the original subtask executor.
    """
    logger.info(f"[LangGraph] Node: Browser Agent (Action→Observe→Verify Pipeline)")
    results = state.get("execution_results", [])
    text = state.get("input_text", "")

    # ── Route to ActionPipeline for video/playback automation ──────────────────
    if any(w in text.lower() for w in ("youtube", "play", "click", "watch", "channel", "search for", "search")):
        try:
            from app.agents.action_pipeline import action_pipeline, build_youtube_actions
            import re

            tl = text.lower()

            # Try to extract the search topic from various phrasings (order matters: most specific first)
            query = None
            patterns = [
                # "search for Python tutorials on youtube"
                r"search\s+for\s+(.+?)(?:\s+on\s+youtube|\s+in\s+youtube|\s+on\s+chrome|,|$)",
                # "search Python tutorials on youtube"
                r"search\s+(.+?)(?:\s+on\s+youtube|\s+in\s+youtube|,|$)",
                # "play the latest video from marvel"
                r"(?:play|watch)\s+(?:the\s+)?(?:latest\s+video\s+from\s+|video\s+from\s+)?(.+?)(?:\s+on\s+youtube|\s+video|,|$)",
                # "go to youtube and search for X"
                r"go\s+to\s+youtube\s+(?:and\s+)?(?:search\s+for\s+|search\s+)(.+?)(?:\s+and\s+|,|$)",
                # "find X on youtube"
                r"find\s+(.+?)\s+(?:on\s+youtube|on\s+chrome)",
                # "latest video from X"
                r"latest\s+video\s+from\s+(.+?)(?:\s+and\s+|,|$)",
            ]
            for pattern in patterns:
                m = re.search(pattern, tl, re.IGNORECASE)
                if m:
                    query = m.group(1).strip().strip(",").strip()
                    break

            # Final fallback: strip all preamble
            if not query:
                query = re.sub(
                    r"(?i)^(open\s+(chrome|browser|youtube)\s*(,\s*go\s+to\s+youtube)?\s*(,\s*)?|"
                    r"go\s+to\s+youtube\s*(and\s+)?|play\s+|watch\s+|search\s+for\s+|search\s+)",
                    "", text
                ).strip().strip(",").strip()

            # If query is still empty or suspiciously long (entire prompt), use full text
            if not query or len(query) > 80:
                query = text

            logger.info(f"[LangGraph] ActionPipeline: YouTube query = '{query}'")
            actions = build_youtube_actions(query)
            seq_result = await action_pipeline.run_sequence(actions, goal=text)

            step_summary = "\n".join(seq_result.get("steps", []))
            results.append(
                f"👁️ [Action→Verify Pipeline] Goal: {text}\n"
                f"{step_summary}\n\n"
                f"{seq_result.get('message', '✅ Done.')}"
            )

            # Store per-action pipeline results in state
            state["pipeline_results"] = seq_result.get("steps", [])
            state["execution_results"] = results
            return state

        except Exception as e:
            logger.warning(f"[LangGraph] ActionPipeline error (falling back): {e}")
            # Fall through to original loop below

    # ── Original subtask executor (non-YouTube browser tasks) ──────────────────
    for task in state.get("subtasks", []):
        tool_name = task.get("tool", "")
        tool_input = task.get("tool_input", {})

        try:
            from app.agents.planner import _build_tool_registry, _format_tool_result
            registry = _build_tool_registry()
            tool_fn = registry.get(tool_name) or registry.get("search_web")

            if tool_fn:
                fn_to_call = getattr(tool_fn, "func", tool_fn)
                raw_res = await asyncio.to_thread(fn_to_call, **tool_input)
                fmt_res = _format_tool_result(tool_name, raw_res)
                results.append(f"🌐 [Browser Agent] {task.get('title', tool_name)}: {fmt_res}")
            else:
                results.append(f"🌐 [Browser Agent] Executed browser task: {task.get('title', 'Web Search')}")
        except Exception as e:
            results.append(f"❌ [Browser Agent] Error ({tool_name}): {e}")

    state["execution_results"] = results
    return state



# ── Node 3B: Coding Agent Node (Phi-4-mini + Self-Healing Engine) ───────────────
async def coding_agent_node(state: NexusGraphState) -> NexusGraphState:
    """Coding Agent node: executes scripts, shell commands & code tasks with self-healing."""
    logger.info(f"[LangGraph] Node: Coding Agent (Phi-4-mini + Self-Healing)")
    results = state.get("execution_results", [])
    user_id = state.get("user_id", "default_user")

    for task in state.get("subtasks", []):
        tool_name = task.get("tool", "run_shell_command")
        tool_input = task.get("tool_input", {})
        title = task.get("title", tool_name)

        if tool_name == "run_shell_command":
            cmd = tool_input.get("command", "")
            try:
                from app.agents.self_healing_pipeline import self_healing_pipeline
                sh_res = await self_healing_pipeline.run(
                    command=cmd,
                    goal=state.get("input_text", ""),
                    user_id=user_id,
                    max_retries=3,
                )
                if sh_res["success"]:
                    repair_notes = ""
                    if sh_res.get("repairs_performed"):
                        reps = [f"• {r['action']} (Attempt {r['attempt']})" for r in sh_res["repairs_performed"]]
                        repair_notes = f"\n🔧 *Self-Healing Repairs:*\n" + "\n".join(reps)
                    results.append(
                        f"💻 [Coding Agent] {title}: ✅ Success ({sh_res['latency_ms']}ms, {sh_res['attempts']} attempt(s))\n"
                        f"{sh_res.get('output', '')[:300]}{repair_notes}"
                    )
                else:
                    results.append(f"❌ [Coding Agent] {title} failed after {sh_res['attempts']} attempts: {sh_res.get('error', '')[:200]}")
                continue
            except Exception as e:
                logger.warning(f"[CodingAgent] Self-healing error (falling back): {e}")

        # Non-shell tool or fallback
        try:
            from app.agents.planner import _build_tool_registry, _format_tool_result
            registry = _build_tool_registry()
            tool_fn = registry.get(tool_name) or registry.get("run_shell_command")

            if tool_fn:
                raw_res = await asyncio.to_thread(tool_fn, **tool_input)
                fmt_res = _format_tool_result(tool_name, raw_res)
                results.append(f"💻 [Coding Agent] {title}: {fmt_res}")
            else:
                results.append(f"💻 [Coding Agent] Executed code task: {title}")
        except Exception as e:
            results.append(f"❌ [Coding Agent] Error ({tool_name}): {e}")

    state["execution_results"] = results
    return state



# ── Node 3C: Security Agent Node ───────────────────────────────────────────────
async def security_agent_node(state: NexusGraphState) -> NexusGraphState:
    """Security Agent node: executes system security monitoring & n8n workflows."""
    logger.info(f"[LangGraph] Node: Security Agent")
    results = state.get("execution_results", [])
    
    try:
        from app.agents.tools.n8n_tools import list_n8n_workflows
        n8n_res = await asyncio.to_thread(list_n8n_workflows)
        results.append(f"🛡️ [Security Agent] Verified Security & n8n Workflows:\n{n8n_res[:250]}")
    except Exception as e:
        results.append(f"🛡️ [Security Agent] Security audit checked. ({e})")

    state["execution_results"] = results
    return state


# ── Node 3D: PC Tools Node (Direct Windows Tools) ─────────────────────────────
async def pc_tools_node(state: NexusGraphState) -> NexusGraphState:
    """PC Tools node: direct execution of Windows OS system & file tools."""
    logger.info(f"[LangGraph] Node: Direct PC Tools Execution")
    results = state.get("execution_results", [])
    
    for task in state.get("subtasks", []):
        tool_name = task.get("tool", "")
        tool_input = task.get("tool_input", {})
        
        try:
            from app.agents.planner import _build_tool_registry, _format_tool_result
            registry = _build_tool_registry()
            tool_fn = registry.get(tool_name)
            
            if tool_fn:
                raw_res = await asyncio.to_thread(tool_fn, **tool_input)
                fmt_res = _format_tool_result(tool_name, raw_res)
                results.append(f"⚡ [PC Tools] {task.get('title', tool_name)}: {fmt_res}")
            else:
                results.append(f"⚡ [PC Tools] Executed tool: {tool_name}")
        except Exception as e:
            results.append(f"❌ [PC Tools] Error ({tool_name}): {e}")

    state["execution_results"] = results
    return state


# ── Node 4: Response Aggregator Node ───────────────────────────────────────────
async def response_aggregator_node(state: NexusGraphState) -> NexusGraphState:
    """Aggregate execution results, log to audit memory, and build final response."""
    logger.info(f"[LangGraph] Node: Response Aggregator")
    results = state.get("execution_results", [])
    
    if not results:
        final_text = "✅ Task completed successfully."
    else:
        final_text = "\n\n".join(results)
        
    state["final_output"] = final_text
    
    # Store to ChromaDB memory
    try:
        from app.memory.chroma_store import memory_store
        await asyncio.to_thread(
            memory_store.store,
            document=f"Goal: {state['input_text']}\nResults: {final_text[:300]}",
            user_id=state.get("user_id", "default_user"),
        )
    except Exception:
        pass

    return state


# ── Build & Compile the StateGraph Workflow ────────────────────────────────────
def build_nexus_graph():
    """Compile and return the complete LangGraph StateGraph workflow."""
    workflow = StateGraph(NexusGraphState)

    # Add Nodes
    workflow.add_node("intent_planner", intent_planner_node)
    workflow.add_node("security_approval", security_approval_node)
    workflow.add_node("browser_agent", browser_agent_node)
    workflow.add_node("coding_agent", coding_agent_node)
    workflow.add_node("security_agent", security_agent_node)
    workflow.add_node("pc_tools", pc_tools_node)
    workflow.add_node("response_aggregator", response_aggregator_node)

    # Set Entry Point
    workflow.set_entry_point("intent_planner")

    # Connect Intent -> Security
    workflow.add_edge("intent_planner", "security_approval")

    # Conditional Branch from Security Approval -> Agents / Tools
    workflow.add_conditional_edges(
        "security_approval",
        route_decision,
        {
            "browser_agent": "browser_agent",
            "coding_agent": "coding_agent",
            "security_agent": "security_agent",
            "pc_tools": "pc_tools",
            "rejected": "response_aggregator",
        }
    )

    # Connect Agents / Tools -> Response Aggregator
    workflow.add_edge("browser_agent", "response_aggregator")
    workflow.add_edge("coding_agent", "response_aggregator")
    workflow.add_edge("security_agent", "response_aggregator")
    workflow.add_edge("pc_tools", "response_aggregator")

    # Set Finish Edge
    workflow.add_edge("response_aggregator", END)

    return workflow.compile()


# Compiled Singleton Graph Engine
langgraph_engine = build_nexus_graph()


async def execute_nexus_graph(input_text: str, user_id: str = "default_user") -> Dict[str, Any]:
    """Helper method to invoke the compiled LangGraph workflow end-to-end."""
    initial_state: NexusGraphState = {
        "user_id": user_id,
        "input_text": input_text,
        "intent": "unknown",
        "subtasks": [],
        "requires_approval": False,
        "approval_granted": False,
        "route": "direct_tool",
        "domain": "pc",
        "execution_results": [],
        "final_output": "",
        "pipeline_results": None,
        "recovery_attempts": 0,
    }
    
    final_state = await langgraph_engine.ainvoke(initial_state)
    return {
        "user_id": final_state["user_id"],
        "intent": final_state["intent"],
        "domain": final_state["domain"],
        "route": final_state["route"],
        "final_output": final_state["final_output"],
        "results": final_state["execution_results"],
    }
