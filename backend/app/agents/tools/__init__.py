"""Agent tools package — exports all tool lists for each specialized agent."""
from app.agents.tools.system_tools import (
    get_system_state,
    get_running_processes,
    kill_process,
    get_disk_usage,
    set_system_power,
    check_network_connectivity,
    set_system_brightness,
)
from app.agents.tools.app_tools import (
    open_application,
    close_application,
    list_running_applications,
    open_url_in_browser,
    run_shell_command,
    set_system_volume,
)
from app.agents.tools.file_tools import (
    search_files,
    move_file,
    copy_file,
    delete_file,
    compress_files,
    list_directory,
    get_file_hash,
    organize_downloads,
    rename_file,
    search_and_rename_folder,
)
from app.agents.tools.vision_tools import (
    take_screenshot,
    ocr_screen,
    find_error_on_screen,
    analyze_desktop,
    get_vision_status,
)
from app.agents.tools.n8n_tools import (
    list_n8n_workflows,
    trigger_n8n_workflow,
)
from app.agents.tools.browser_tools import (
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    download_file,
    upload_file,
    take_browser_screenshot,
    get_page_text,
    close_browser,
)
from app.agents.tools.blender_tools import (
    create_blender_scene,
)
from app.agents.tools.presentation_tools import (
    create_presentation,
)
from app.agents.tools.document_tools import (
    analyze_document,
    query_document,
)
from app.agents.tools.devops_tools import (
    test_and_repair_codebase,
)
from app.agents.tools.finance_tools import (
    get_market_analysis,
)
from app.agents.tools.skill_creator_tools import (
    create_new_tool,
    list_custom_tools,
)
from app.agents.tools.gui_tools import (
    execute_gui_actions,
    click_screen_text,
)
from app.agents.tools.research_tools import (
    conduct_deep_research,
)
from app.agents.tools.sentinel_tools import (
    get_morning_briefing,
    check_system_sentinel,
)
from app.agents.tools.github_tools import (
    generate_git_changelog,
    draft_developer_social_post,
)
from app.agents.tools.app_architect_tools import (
    build_autonomous_application,
)
from app.agents.tools.secops_tools import (
    audit_codebase_security,
)
from app.agents.tools.second_brain_tools import (
    capture_thought_or_note,
    query_second_brain,
)
from app.agents.tools.meeting_tools import (
    summarize_meeting_audio,
)
from app.agents.tools.council_tools import (
    deliberate_with_council,
)

SYSTEM_TOOLS = [
    get_system_state,
    get_running_processes,
    kill_process,
    get_disk_usage,
    set_system_power,
    check_network_connectivity,
    set_system_brightness,
]

APPLICATION_TOOLS = [
    open_application,
    close_application,
    list_running_applications,
    open_url_in_browser,
    run_shell_command,
    set_system_volume,
]

FILE_TOOLS = [
    search_files,
    move_file,
    copy_file,
    delete_file,
    compress_files,
    list_directory,
    get_file_hash,
    organize_downloads,
    rename_file,
    search_and_rename_folder,
]

VISION_TOOLS = [
    take_screenshot,
    ocr_screen,
    find_error_on_screen,
    analyze_desktop,
    get_vision_status,
]

N8N_TOOLS = [
    list_n8n_workflows,
    trigger_n8n_workflow,
]

BROWSER_TOOLS = [
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    download_file,
    upload_file,
    take_browser_screenshot,
    get_page_text,
    close_browser,
]

BLENDER_TOOLS = [
    create_blender_scene,
]

PRESENTATION_TOOLS = [
    create_presentation,
]

DOCUMENT_TOOLS = [
    analyze_document,
    query_document,
]

DEVOPS_TOOLS = [
    test_and_repair_codebase,
]

FINANCE_TOOLS = [
    get_market_analysis,
]

SKILL_CREATOR_TOOLS = [
    create_new_tool,
    list_custom_tools,
]

GUI_TOOLS = [
    execute_gui_actions,
    click_screen_text,
]

RESEARCH_TOOLS = [
    conduct_deep_research,
]

SENTINEL_TOOLS = [
    get_morning_briefing,
    check_system_sentinel,
]

GITHUB_TOOLS = [
    generate_git_changelog,
    draft_developer_social_post,
]

APP_ARCHITECT_TOOLS = [
    build_autonomous_application,
]

SECOPS_TOOLS = [
    audit_codebase_security,
]

SECOND_BRAIN_TOOLS = [
    capture_thought_or_note,
    query_second_brain,
]

MEETING_TOOLS = [
    summarize_meeting_audio,
]

COUNCIL_TOOLS = [
    deliberate_with_council,
]

# Actions that require explicit user approval before execution
DANGEROUS_ACTIONS = {
    "delete_file",
    "kill_process",
    "set_system_power",
    "run_shell_command",
    "close_application",
    "download_file",
    "upload_file",
}
