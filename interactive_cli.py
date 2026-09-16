#!/usr/bin/env python3
"""
Nexus AI — Interactive Real-Time Terminal Interface
Allows you to prompt Nexus AI with live tasks, watch step-by-step tool execution,
approve sensitive actions, and query memory in real-time.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add backend to Python path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ANSI Color codes for clean terminal output
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def prompt_user_approval(task_id: str, tool_name: str, parameters: dict, reason: str) -> bool:
    """Handle interactive human approval in the terminal for sensitive actions."""
    print(f"\n{YELLOW}{BOLD}⚠️  HUMAN APPROVAL REQUIRED{RESET}")
    print(f"  {BOLD}Tool:{RESET} {tool_name}")
    print(f"  {BOLD}Parameters:{RESET} {parameters}")
    print(f"  {BOLD}Reason:{RESET} {reason}")
    
    while True:
        try:
            choice = input(f"{YELLOW}Allow this action? [y/N]: {RESET}").strip().lower()
            if choice in ("y", "yes"):
                return True
            elif choice in ("n", "no", ""):
                return False
        except (KeyboardInterrupt, EOFError):
            return False


async def on_progress(task_id: str, message: str, state: str):
    """Callback to print live task progress."""
    print(f"  {CYAN}▸ [{state.upper()}]{RESET} {message}")


async def run_single_goal(runtime, goal: str, user_id: str = "interactive_user"):
    """Execute a single goal through the Nexus runtime with live output."""
    print(f"\n{BOLD}🎯 Goal:{RESET} {goal}")
    print(f"{CYAN}⏳ Planning and executing...{RESET}")
    
    try:
        task = await runtime.execute_goal(
            goal=goal,
            user_id=user_id,
            approval_notifier=prompt_user_approval
        )
        
        print(f"\n{BOLD}🏁 Task Finished:{RESET} {task.task_id}")
        print(f"  {BOLD}Status:{RESET} " + (f"{GREEN}COMPLETED{RESET}" if task.state.value == "completed" else f"{RED}{task.state.value.upper()}{RESET}"))
        print(f"  {BOLD}Steps Executed:{RESET} {task.current_step}/{len(task.subtasks)}")
        
        # Display individual step outcomes
        if task.subtasks:
            print(f"\n{BOLD}📋 Execution Steps:{RESET}")
            for idx, st in enumerate(task.subtasks, 1):
                status_color = GREEN if st.state.value == "completed" else (RED if st.state.value == "failed" else YELLOW)
                print(f"  {idx}. [{status_color}{st.state.value.upper()}{RESET}] {st.description}")
                if st.tool:
                    print(f"     Tool: {MAGENTA}{st.tool}{RESET} | Input: {st.tool_input}")
                if st.result:
                    res_summary = str(st.result)[:140] + ("..." if len(str(st.result)) > 140 else "")
                    print(f"     Result: {res_summary}")
                if st.error:
                    print(f"     {RED}Error: {st.error}{RESET}")
                    
    except Exception as e:
        print(f"\n{RED}❌ Execution Failed:{RESET} {e}")


async def interactive_session():
    """Main interactive REPL loop."""
    print(f"""
{CYAN}{BOLD}===========================================================================
  ⚡ NEXUS AI — REAL-TIME AUTONOMOUS COMPUTER AGENT INTERFACE
==========================================================================={RESET}
{BOLD}Available Commands:{RESET}
  • Type any natural language goal (e.g. {GREEN}'open notepad'{RESET}, {GREEN}'get system status'{RESET})
  • {YELLOW}/memory <fact>{RESET} : Store a permanent memory fact
  • {YELLOW}/forget <fact>{RESET} : Revoke/delete a memory fact
  • {YELLOW}/recall <query>{RESET} : Search memory for relevant context
  • {YELLOW}/help{RESET}          : Show example commands
  • {YELLOW}/exit{RESET} or {YELLOW}Ctrl+C{RESET} : Exit interface
""")

    # Initialize unified runtime
    from app.runtime.nexus_runtime import get_nexus_runtime
    from app.memory.tiered_memory import tiered_memory
    
    runtime = get_nexus_runtime()
    runtime.register_progress_callback(on_progress)

    while True:
        try:
            user_input = input(f"\n{BOLD}{GREEN}nexus>{RESET} ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("/exit", "exit", "quit", ":q"):
                print(f"{CYAN}👋 Goodbye!{RESET}")
                break

            elif user_input.lower() == "/help":
                print(f"""
{BOLD}Example Real-Time Goals to Try:{RESET}
  1. {CYAN}PC Control & Apps:{RESET}
     • 'open notepad'
     • 'check running processes for chrome'
     • 'get system disk and CPU usage'
     • 'take a screenshot and analyze desktop'

  2. {CYAN}Web & Browser:{RESET}
     • 'search web for latest AI breakthrough'
     • 'open google.com and find python documentation'

  3. {CYAN}Coding & Files:{RESET}
     • 'list files in backend directory'
     • 'create a python script that prints fibonacci numbers'

  4. {CYAN}Memory & Recall:{RESET}
     • 'remember that my preferred code formatting is black'
     • 'what is my preferred code formatting?'
     • '/forget preferred code formatting'
""")
                continue

            elif user_input.startswith("/memory "):
                fact = user_input[8:].strip()
                tiered_memory.store_semantic_fact(key=fact[:30], value=fact, source="user_cli")
                print(f"{GREEN}✓ Stored in permanent semantic memory:{RESET} {fact}")
                continue

            elif user_input.startswith("/forget "):
                pattern = user_input[8:].strip()
                tiered_memory.forget_memory(pattern=pattern)
                print(f"{YELLOW}✓ Revoked and deleted memory matching:{RESET} {pattern}")
                continue

            elif user_input.startswith("/recall "):
                query = user_input[8:].strip()
                results = tiered_memory.query_semantic_memory(query=query)
                print(f"{CYAN}🧠 Memory Results for '{query}':{RESET}")
                if not results:
                    print("  (No matching memory records found)")
                for r in results:
                    print(f"  • {BOLD}{r.get('key')}{RESET}: {r.get('value')} (Source: {r.get('source')})")
                continue

            # Run standard goal through agent pipeline
            await run_single_goal(runtime, user_input)

        except KeyboardInterrupt:
            print(f"\n{CYAN}👋 Exiting Nexus AI CLI.{RESET}")
            break
        except Exception as e:
            print(f"{RED}Error:{RESET} {e}")


def main():
    try:
        asyncio.run(interactive_session())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
