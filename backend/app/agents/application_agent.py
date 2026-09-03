"""Application Agent — LangChain AgentExecutor wrapper for Windows app management."""
from app.agents.tools import APPLICATION_TOOLS

APPLICATION_AGENT_ROLE = (
    "a Windows Application Manager. Open, close, and manage Windows applications. "
    "Launch workspaces, manage browser tabs, and run shell commands safely."
)

application_tools = APPLICATION_TOOLS
