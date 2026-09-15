"""Council of Experts (Multi-Agent Consensus Engine) for Nexus AI.

Simulates an adversarial deliberative council of 3 distinct personas:
1. 🚀 The Visionary (Scale, Innovation, Upside)
2. 🛡️ The Skeptic (Risk, Security, Maintenance Pitfalls)
3. ⚖️ The Pragmatic Lead (Deadlines, Simplicity, ROI)
Conducts multi-perspective debate and produces a Consensus Decision Matrix.
"""
import os
import re
import logging
import asyncio
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
COUNCIL_MODEL = os.getenv("COUNCIL_MODEL", "phi4-mini:latest")


class CouncilAgent:
    """Agent orchestrating multi-perspective expert debates and consensus synthesis."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = COUNCIL_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def deliberate(self, topic: str, rounds: int = 2) -> Dict[str, Any]:
        """Runs an adversarial multi-agent debate on a question or strategic decision."""
        logger.info(f"[CouncilAgent] Assembling Council of Experts for: '{topic}'...")

        prompt = (
            f"You are the Chair of the Nexus AI Council of Experts. "
            f"Conduct an intensive, 3-expert deliberative debate on the following topic:\n"
            f"**Topic / Strategic Decision**: \"{topic}\"\n\n"
            f"Simulate these 3 personas:\n"
            f"1. 🚀 **The Visionary**: Champions innovation, extreme scale, and competitive edge.\n"
            f"2. 🛡️ **The Skeptic**: Exposes hidden tail-risks, security traps, maintenance debt, and failure modes.\n"
            f"3. ⚖️ **The Pragmatic Lead**: Focuses on resource constraints, time-to-market, and simple execution.\n\n"
            f"Format requirements:\n"
            f"# 🏛️ Council of Experts: Consensus Verdict\n"
            f"**Dilemma**: {topic}\n\n"
            f"## 1. Expert Perspectives & Arguments\n"
            f"- 🚀 **Visionary Stance**:\n"
            f"- 🛡️ **Skeptic Critique**:\n"
            f"- ⚖️ **Pragmatist Assessment**:\n\n"
            f"## 2. Adversarial Cross-Examination & Rebuttals\n\n"
            f"## 3. Final Consensus Decision Matrix\n"
            f"| Criterion | Verdict | Confidence |\n"
            f"| :--- | :--- | :--- |\n"
            f"| **Primary Path** | [Recommendation] | High/Med |\n"
            f"| **Key Mitigations** | [Mitigations] | High |\n"
            f"| **Kill Criteria** | [When to Pivot] | High |\n\n"
            f"## 4. Final Executive Verdict\n"
            f"[Direct, unambiguous action plan in 3 bullet points.]"
        )

        for m in [self.model, "qwen3:4b", "phi4-mini:latest"]:
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": m, "prompt": prompt, "stream": False}
                    )
                    if resp.status_code == 200:
                        debate_text = resp.json().get("response", "").strip()
                        return {
                            "success": True,
                            "topic": topic,
                            "deliberation": debate_text
                        }
            except Exception as e:
                logger.warning(f"[CouncilAgent] Debate model {m} error: {e}")
                continue

        return {
            "success": False,
            "error": "Failed to complete Council debate via local LLM."
        }


council_agent = CouncilAgent()
