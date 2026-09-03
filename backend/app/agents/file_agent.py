"""File Agent — LangChain AgentExecutor wrapper for file system operations."""
from app.agents.tools import FILE_TOOLS

FILE_AGENT_ROLE = (
    "a Windows File System Manager. Search, organize, move, copy, compress, and manage "
    "files on the Windows filesystem. Always confirm before deleting."
)

file_tools = FILE_TOOLS
