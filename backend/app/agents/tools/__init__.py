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


