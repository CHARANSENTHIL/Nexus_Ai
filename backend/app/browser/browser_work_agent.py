"""
Browser Work Agent — Autonomous web objective completion agent.
Coordinates multi-page navigation, semantic DOM interaction, safe credential injection,
CAPTCHA/2FA human handoff, and download verification.
"""
import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

from app.config import settings
from app.browser.playwright_manager import playwright_manager
from app.handoff.handoff_engine import handoff_engine
from app.handoff.handoff_models import HandoffTrigger, HandoffState
from app.security.credential_manager import credential_manager
from app.memory.user_profile_store import user_profile_store

logger = logging.getLogger(__name__)

BROWSER_DECISION_PROMPT = PromptTemplate(
    input_variables=["goal", "current_url", "interactive_elements", "history"],
    template="""You are an Autonomous Browser Work Agent.
Your objective: {goal}

Current Page URL: {current_url}

Interactive Elements on Page:
{interactive_elements}

Action History:
{history}

Decide the SINGLE next best action to advance towards the goal.
Valid action types:
1. "click": {{"action": "click", "selector": "#id or selector or text", "reason": "why"}}
2. "fill": {{"action": "fill", "selector": "#id or input selector", "value": "text to type", "reason": "why"}}
3. "inject_credentials": {{"action": "inject_credentials", "reason": "Login form detected"}}
4. "autofill_profile": {{"action": "autofill_profile", "reason": "Registration/Profile form detected"}}
5. "navigate": {{"action": "navigate", "url": "https://...", "reason": "why"}}
6. "finish": {{"action": "finish", "summary": "Detailed explanation of what was achieved and found"}}

Respond with ONLY valid JSON for the chosen action. Do NOT output any markdown ticks other than standard JSON.
"""
)


class BrowserWorkAgent:
    """Autonomous closed-loop browser agent capable of end-to-end task completion."""

    def __init__(self):
        self.manager = playwright_manager

    def _get_llm(self):
        url = settings.get_ollama_url()
        model_name = getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")
        return OllamaLLM(model=model_name, base_url=url, temperature=0.1)

    async def run_objective(
        self,
        goal: str,
        initial_url: Optional[str] = None,
        task_id: str = "browser_task",
        user_id: str = "default_user",
        max_steps: int = 10,
    ) -> Dict[str, Any]:
        """
        Executes a complete web workflow from start to finish.
        """
        logger.info(f"[BrowserWorkAgent] 🌐 Starting browser objective: '{goal}' (initial_url={initial_url})")

        # 1. Initialize browser if not open
        await self.manager.initialize(browser_name="msedge", headless=False)

        # 2. Navigate to start URL or search
        if initial_url:
            await self.manager.open_url(initial_url)
        else:
            await self.manager.search_web(goal)

        history: List[str] = []
        llm = self._get_llm()

        for step in range(1, max_steps + 1):
            logger.info(f"[BrowserWorkAgent] Step {step}/{max_steps} on {self.manager._current_url}")

            # A. Check for CAPTCHA or 2FA/OTP
            captcha_or_otp, challenge_type = await self.manager.detect_captcha_or_otp()
            if captcha_or_otp:
                trigger = (
                    HandoffTrigger.OTP_REQUIRED
                    if challenge_type == "OTP_REQUIRED"
                    else HandoffTrigger.CAPTCHA_DETECTED
                )
                screenshot = await self.manager.take_screenshot()
                logger.warning(f"[BrowserWorkAgent] Challenge detected ({challenge_type})! Triggering Human Handoff...")

                checkpoint = await handoff_engine.trigger_handoff(
                    task_id=task_id,
                    user_id=user_id,
                    agent_name="browser_work_agent",
                    trigger=trigger,
                    reason=f"Browser encountered {challenge_type}. Please resolve in browser.",
                    target_url=self.manager._current_url,
                    screenshot_path=screenshot,
                )

                # Wait for user resolution
                resolved_cp = await handoff_engine.wait_for_resolution(
                    checkpoint.checkpoint_id,
                    verifiers=[lambda: not (self.manager.detect_captcha_or_otp()[0])]
                )

                if resolved_cp.state != HandoffState.RESUMED:
                    return {
                        "success": False,
                        "error": f"Human handoff failed: {resolved_cp.verification_notes}",
                        "steps_completed": step,
                    }

            # B. Extract DOM interactive elements
            elements = await self.manager.get_interactive_dom_elements()
            elements_repr = "\n".join(
                f"[{e['index']}] <{e['tag']}> id='{e['id']}' text='{e['text']}' type='{e['type']}' selector='{e['selector']}'"
                for e in elements[:30]
            )

            # C. Check for Login page automatically
            has_password_field = any(e.get("type") == "password" for e in elements)
            if has_password_field and "injected credentials" not in " ".join(history).lower():
                logger.info("[BrowserWorkAgent] Detected login password field! Injecting credentials...")
                inj_res = await self.manager.inject_credentials()
                if inj_res.get("success"):
                    history.append("Injected saved credentials into login form.")
                    # Find and click submit/login button
                    submit_btn = next((e for e in elements if "log" in e["text"].lower() or "sign" in e["text"].lower() or e["type"] == "submit"), None)
                    if submit_btn:
                        await self.manager.click_element(submit_btn["selector"])
                        await asyncio.sleep(3)
                    continue

            # D. Query LLM for next action
            try:
                prompt_text = BROWSER_DECISION_PROMPT.format(
                    goal=goal,
                    current_url=self.manager._current_url,
                    interactive_elements=elements_repr or "No interactive elements found.",
                    history="\n".join(history[-4:]) if history else "None",
                )
                raw_decision = await asyncio.to_thread(llm.invoke, prompt_text)
                
                clean_json = raw_decision.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()

                decision = json.loads(clean_json)
                action = decision.get("action")

                if action == "finish":
                    summary = decision.get("summary", "Goal completed successfully.")
                    logger.info(f"[BrowserWorkAgent] ✅ Goal finished: {summary}")
                    return {
                        "success": True,
                        "summary": summary,
                        "url": self.manager._current_url,
                        "steps": step,
                    }

                elif action == "click":
                    sel = decision.get("selector", "")
                    await self.manager.click_element(sel)
                    history.append(f"Clicked {sel}")
                    await asyncio.sleep(2)

                elif action == "fill":
                    sel = decision.get("selector", "")
                    val = decision.get("value", "")
                    await self.manager.fill_form(sel, val)
                    history.append(f"Filled {sel} with '{val}'")

                elif action == "inject_credentials":
                    inj_res = await self.manager.inject_credentials()
                    history.append(f"Injected credentials: {inj_res.get('success')}")

                elif action == "autofill_profile":
                    auto_res = await self.manager.autofill_profile_fields()
                    history.append(f"Autofilled profile fields: {auto_res.get('filled_fields_count', 0)}")

                elif action == "navigate":
                    target_url = decision.get("url", "")
                    await self.manager.open_url(target_url)
                    history.append(f"Navigated to {target_url}")

            except Exception as e:
                logger.error(f"[BrowserWorkAgent] Step {step} error: {e}")
                history.append(f"Error on step {step}: {e}")

        # If loop reached max_steps, extract page content summary
        page_summary = await self.manager.read_page()
        return {
            "success": True,
            "summary": f"Completed {max_steps} autonomous navigation steps.\n\n{page_summary[:800]}",
            "url": self.manager._current_url,
            "steps": max_steps,
        }


# Singleton instance
browser_work_agent = BrowserWorkAgent()
