"""System Agent — LangChain AgentExecutor wrapper for OS monitoring and control."""
from app.agents.tools import SYSTEM_TOOLS

SYSTEM_AGENT_ROLE = (
    "a Windows System Monitor. Read system state from the Digital Twin API. "
    "Report CPU, RAM, battery, disk, processes, and network status accurately. "
    "Never call OS APIs directly — always use the provided tools."
)

# Tools exported for use by PlannerAgent executor
system_tools = SYSTEM_TOOLS
