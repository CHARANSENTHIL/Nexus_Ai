"""
Formal Tool Registry — Strongly-typed registry of all Nexus AI capabilities.
Enforces capability levels, input schemas, timeouts, and verification strategies.
"""
import logging
import asyncio
from typing import Dict, Any, Optional, List

from app.runtime.task_models import CapabilityLevel, ToolDefinition

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central repository for all system, application, browser, coding, and multimedia tools.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def register_tool(self, tool_def: ToolDefinition):
        self._tools[tool_def.name] = tool_def
        logger.debug(f"[ToolRegistry] Registered tool '{tool_def.name}' (Level {tool_def.capability_level.value})")

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def _register_default_tools(self):
        """Populate initial core tool definitions with capability levels."""
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
        )
        from app.agents.tools.vision_tools import (
            take_screenshot, ocr_screen, find_error_on_screen,
            analyze_desktop, get_vision_status,
        )
        from app.agents.tools.browser_tools import (
            open_browser, open_url, search_web, read_page,
            click_element, fill_form, download_file,
            take_browser_screenshot, get_page_text, close_browser,
            inject_domain_credentials, autofill_profile_form,
            run_autonomous_browser_workflow,
        )
        from app.agents.tools.coding_tools import (
            search_codebase_symbols, get_file_symbol_outline,
            get_symbol_implementation, apply_targeted_diff,
            run_unit_tests, manage_dev_server,
        )
        from app.agents.tools.presentation_tools import create_presentation
        from app.agents.tools.blender_tools import create_blender_scene
        from app.agents.tools.document_tools import analyze_document, query_document
        from app.agents.tools.finance_tools import get_market_analysis
        from app.agents.tools.devops_tools import test_and_repair_codebase

        # ── LEVEL 0: READ-ONLY TOOLS ──────────────────────────────────────────
        self.register_tool(ToolDefinition(
            name="get_system_state",
            description="Inspect system CPU, RAM, battery, and disk status",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_system_state.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_running_processes",
            description="List running OS processes with memory/CPU stats",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_running_processes.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_disk_usage",
            description="Get disk storage usage for drives",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_disk_usage.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="check_network_connectivity",
            description="Check ping and internet connectivity",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=check_network_connectivity.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="search_files",
            description="Find files matching pattern in a directory",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=search_files.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="list_directory",
            description="List directory contents",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=list_directory.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="take_screenshot",
            description="Capture full screen image",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=take_screenshot.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="ocr_screen",
            description="Extract text from screenshot via OCR",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=ocr_screen.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="search_codebase_symbols",
            description="AST symbol search for functions and classes",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=search_codebase_symbols.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_file_symbol_outline",
            description="Get structural AST outline of a file",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_file_symbol_outline.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_symbol_implementation",
            description="Extract function source code slice",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_symbol_implementation.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="read_page",
            description="Extract readable text from browser webpage",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=read_page.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="search_web",
            description="Search the web for query",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=search_web.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="take_browser_screenshot",
            description="Capture browser tab screenshot",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=take_browser_screenshot.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_page_text",
            description="Extract inner text from browser tab",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_page_text.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_file_hash",
            description="Calculate SHA256 or MD5 hash of a file",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_file_hash.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="find_error_on_screen",
            description="Locate errors or dialogs on screen via vision/OCR",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=find_error_on_screen.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="analyze_desktop",
            description="Analyze desktop UI elements and windows",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=analyze_desktop.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_vision_status",
            description="Get vision system readiness and screen metrics",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_vision_status.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="analyze_document",
            description="Analyze document content and structure",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=analyze_document.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="query_document",
            description="Query document for specific information",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=query_document.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="get_market_analysis",
            description="Fetch financial market analysis and quotes",
            capability_level=CapabilityLevel.LEVEL_0_READ,
            execute_fn=get_market_analysis.func,
            verification_strategy="general",
        ))

        # ── LEVEL 1: SAFE WRITE TOOLS ─────────────────────────────────────────
        self.register_tool(ToolDefinition(
            name="open_application",
            description="Launch installed desktop application",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=open_application.func,
            verification_strategy="process_running",
        ))
        self.register_tool(ToolDefinition(
            name="open_browser",
            description="Launch browser session",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=open_browser.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="open_url",
            description="Navigate browser to target URL",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=open_url.func,
            verification_strategy="browser_navigated",
        ))
        self.register_tool(ToolDefinition(
            name="click_element",
            description="Click element on web page",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=click_element.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="fill_form",
            description="Fill text into input element",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=fill_form.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="download_file",
            description="Download file from URL",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=download_file.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="close_browser",
            description="Close active browser session",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=close_browser.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="manage_dev_server",
            description="Inspect or manage background dev server",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=manage_dev_server.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="open_url_in_browser",
            description="Open a URL in user's default browser",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=open_url_in_browser.func,
            verification_strategy="browser_navigated",
        ))
        self.register_tool(ToolDefinition(
            name="create_presentation",
            description="Generate a 16:9 widescreen PowerPoint deck",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=create_presentation.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="create_blender_scene",
            description="Generate a procedural 3D scene in Blender",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=create_blender_scene.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="download_images_from_web",
            description="Search and download image files to disk",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=download_images_from_web.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="apply_targeted_diff",
            description="Apply AST-validated diff patch to file",
            capability_level=CapabilityLevel.LEVEL_3_DESTRUCTIVE,
            execute_fn=apply_targeted_diff.func,
            requires_approval=True,
            verification_strategy="code_syntax",
        ))
        self.register_tool(ToolDefinition(
            name="run_unit_tests",
            description="Execute pytest/unittest test runner",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=run_unit_tests.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="copy_file",
            description="Copy file from source to destination",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=copy_file.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="organize_downloads",
            description="Classify and move files in downloads folder",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=organize_downloads.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="set_system_volume",
            description="Set Windows master audio volume level (0-100)",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=set_system_volume.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="set_system_brightness",
            description="Adjust display brightness level (0-100)",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=set_system_brightness.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="close_application",
            description="Gracefully close an open application window",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=close_application.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="rename_file",
            description="Rename a file or folder",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=rename_file.func,
            verification_strategy="file_exists",
        ))
        self.register_tool(ToolDefinition(
            name="compress_files",
            description="Create zip archive from files/folders",
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
            execute_fn=compress_files.func,
            verification_strategy="file_exists",
        ))

        # ── LEVEL 2: SENSITIVE TOOLS ──────────────────────────────────────────
        self.register_tool(ToolDefinition(
            name="send_intelligent_email",
            description="Draft and dispatch email with attachments",
            capability_level=CapabilityLevel.LEVEL_2_SENSITIVE,
            execute_fn=send_intelligent_email.func,
            requires_approval=True,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="inject_domain_credentials",
            description="Inject stored credentials into web form",
            capability_level=CapabilityLevel.LEVEL_2_SENSITIVE,
            execute_fn=inject_domain_credentials.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="autofill_profile_form",
            description="Autofill web form using Profile Store",
            capability_level=CapabilityLevel.LEVEL_2_SENSITIVE,
            execute_fn=autofill_profile_form.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="run_autonomous_browser_workflow",
            description="Autonomous multi-step browser objective",
            capability_level=CapabilityLevel.LEVEL_2_SENSITIVE,
            execute_fn=run_autonomous_browser_workflow.func,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="test_and_repair_codebase",
            description="Run test suite and attempt automated AST fixes",
            capability_level=CapabilityLevel.LEVEL_2_SENSITIVE,
            execute_fn=test_and_repair_codebase.func,
            requires_approval=True,
            verification_strategy="general",
        ))

        # ── LEVEL 3: DESTRUCTIVE TOOLS ────────────────────────────────────────
        self.register_tool(ToolDefinition(
            name="delete_file",
            description="Delete a file from disk",
            capability_level=CapabilityLevel.LEVEL_3_DESTRUCTIVE,
            execute_fn=delete_file.func,
            requires_approval=True,
            verification_strategy="file_deleted",
        ))
        self.register_tool(ToolDefinition(
            name="kill_process",
            description="Terminate a running process by PID",
            capability_level=CapabilityLevel.LEVEL_3_DESTRUCTIVE,
            execute_fn=kill_process.func,
            requires_approval=True,
            verification_strategy="process_killed",
        ))
        self.register_tool(ToolDefinition(
            name="set_system_power",
            description="Put system to sleep, hibernate, or lock screen",
            capability_level=CapabilityLevel.LEVEL_3_DESTRUCTIVE,
            execute_fn=set_system_power.func,
            requires_approval=True,
            verification_strategy="general",
        ))
        self.register_tool(ToolDefinition(
            name="run_shell_command",
            description="Execute arbitrary PowerShell or cmd shell command",
            capability_level=CapabilityLevel.LEVEL_3_DESTRUCTIVE,
            execute_fn=run_shell_command.func,
            requires_approval=True,
            verification_strategy="general",
        ))


# Singleton instance
tool_registry = ToolRegistry()
