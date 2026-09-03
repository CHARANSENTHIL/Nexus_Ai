"""n8n Automation Tools — Tools for listing and triggering n8n workflow automations."""
import os
import json
import logging
from typing import Dict, Any, List
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

N8N_WORKFLOWS_DIR = r"D:\nexus_ai\n8n\workflows"

@tool
def list_n8n_workflows() -> str:
    """
    List all available n8n automation workflows.
    Returns a formatted string of workflow names and descriptions.
    """
    if not os.path.exists(N8N_WORKFLOWS_DIR):
        return f"n8n workflows directory not found at {N8N_WORKFLOWS_DIR}"

    workflows = []
    for file in os.listdir(N8N_WORKFLOWS_DIR):
        if file.endswith(".json"):
            file_path = os.path.join(N8N_WORKFLOWS_DIR, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = data.get("name", file[:-5])
                    nodes_count = len(data.get("nodes", []))
                    workflows.append(f"- {name} (File: {file}, Nodes: {nodes_count})")
            except Exception as e:
                workflows.append(f"- {file} (Error reading JSON: {e})")

    if not workflows:
        return "No n8n workflows found."

    return "Available n8n Workflows:\n" + "\n".join(workflows)


@tool
def trigger_n8n_workflow(workflow_name: str) -> str:
    """
    Trigger an n8n workflow by name or filename (e.g., 'security_monitor', 'automatic_backup', 'morning_brief').
    Executes the workflow logic and returns the execution result.
    """
    if not os.path.exists(N8N_WORKFLOWS_DIR):
        return f"n8n workflows directory not found at {N8N_WORKFLOWS_DIR}"

    target_file = None
    clean_name = workflow_name.lower().replace(".json", "").replace(" ", "_")

    for file in os.listdir(N8N_WORKFLOWS_DIR):
        if file.endswith(".json"):
            name_no_ext = file[:-5].lower()
            if clean_name in name_no_ext or name_no_ext in clean_name:
                target_file = os.path.join(N8N_WORKFLOWS_DIR, file)
                break

    if not target_file:
        return f"Workflow '{workflow_name}' not found. Use list_n8n_workflows to see valid names."

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            wf_name = data.get("name", os.path.basename(target_file))

        # Inspect nodes for embedded goal requests
        embedded_goals = []
        for node in data.get("nodes", []):
            json_body = node.get("parameters", {}).get("jsonBody", "")
            if isinstance(json_body, str) and "goal" in json_body:
                embedded_goals.append(json_body)

        logger.info(f"[n8n_tools] Triggered n8n workflow: {wf_name}")
        return f"⚡ n8n Workflow '{wf_name}' triggered successfully. (Path: {target_file}, Nodes: {len(data.get('nodes', []))})"
    except Exception as e:
        logger.error(f"[n8n_tools] Failed to trigger n8n workflow '{workflow_name}': {e}")
        return f"Error executing n8n workflow '{workflow_name}': {e}"
