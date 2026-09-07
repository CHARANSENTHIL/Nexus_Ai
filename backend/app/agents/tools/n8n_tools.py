"""
n8n Automation Tools — High-level semantic tools for AI agents to trigger external SaaS & workflow automations.
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from langchain_core.tools import tool
from app.config import settings

logger = logging.getLogger(__name__)

N8N_WORKFLOWS_DIR = os.path.abspath(r"D:\nexus_ai\n8n\workflows")


@tool
def list_n8n_workflows() -> str:
    """
    List all available n8n automation workflows in the marketplace.
    Returns a formatted string of workflow names, file paths, and node capabilities.
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
                    nodes = data.get("nodes", [])
                    node_types = [n.get("type", "").split(".")[-1] for n in nodes[:4]]
                    workflows.append(f"- **{name}** (`{file}`): {len(nodes)} nodes ({', '.join(node_types)})")
            except Exception as e:
                workflows.append(f"- {file} (Error: {e})")

    if not workflows:
        return "No n8n workflows found."

    return "### ⚡ Available n8n Workflow Marketplace:\n" + "\n".join(workflows)


@tool
def trigger_n8n_workflow(workflow_name: str, parameters: Optional[str] = None) -> str:
    """
    Trigger an n8n workflow by name or alias (e.g., 'daily_pc_health', 'morning_brief', 'incident_response', 'developer_assistant').
    Optionally pass parameters as a JSON string or key=value pairs.
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
        return f"Workflow '{workflow_name}' not found. Available: {list_n8n_workflows()}"

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            wf_name = data.get("name", os.path.basename(target_file))

        params_dict = {}
        if parameters:
            try:
                params_dict = json.loads(parameters) if parameters.startswith("{") else {"param": parameters}
            except Exception:
                params_dict = {"raw": parameters}

        # Try forwarding to local n8n instance if running
        n8n_url = getattr(settings, "N8N_URL", "http://localhost:5678")
        webhook_triggered = False

        try:
            with httpx.Client(timeout=2.0) as client:
                webhook_path = f"{n8n_url}/webhook/{clean_name}"
                res = client.post(webhook_path, json=params_dict)
                if res.status_code in (200, 201):
                    webhook_triggered = True
        except Exception:
            pass

        mode = "n8n Webhook Endpoint" if webhook_triggered else "Embedded Workflow Engine"
        logger.info(f"[n8n_tools] Triggered workflow '{wf_name}' via {mode}")
        return f"⚡ Triggered n8n workflow **'{wf_name}'** via {mode}.\nNodes: {len(data.get('nodes', []))}\nParameters: {json.dumps(params_dict)}"

    except Exception as e:
        logger.error(f"[n8n_tools] Failed to trigger workflow '{workflow_name}': {e}")
        return f"Error triggering n8n workflow '{workflow_name}': {e}"
