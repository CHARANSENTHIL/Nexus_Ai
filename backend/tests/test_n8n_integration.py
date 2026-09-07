"""
Tests for n8n Automation & SaaS Integration Layer.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.agents.tools.n8n_tools import list_n8n_workflows, trigger_n8n_workflow


@pytest.mark.asyncio
class TestN8nAPIEndpoints:
    """Test FastAPI endpoints exposed for n8n automation layer."""

    async def test_n8n_pc_health_endpoint(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/v1/n8n/pc/health")
            assert res.status_code == 200
            data = res.json()
            assert "status" in data
            assert "cpu_percent" in data
            assert "ram_percent" in data
            assert "disk_percent" in data
            assert "top_processes" in data
            assert isinstance(data["top_processes"], list)

    async def test_n8n_pc_execute_native_command(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/n8n/pc/execute",
                json={"action": "run_command", "target": "echo n8n_integration_test"}
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert "n8n_integration_test" in str(data["output"])

    async def test_n8n_agent_analyze_pc_health(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "context_type": "pc_health",
                "data": {"cpu_percent": 45, "ram_percent": 60, "disk_percent": 88, "warnings": ["Disk usage is high"]}
            }
            res = await client.post("/api/v1/n8n/agent/analyze", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["severity"] in ("MEDIUM", "HIGH")
            assert len(data["recommendations"]) > 0

    async def test_n8n_github_webhook_bridge(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "action": "opened",
                "issue": {"title": "Fix login bug", "body": "Login fails on mobile"},
                "repository": {"full_name": "owner/repo"}
            }
            res = await client.post("/api/v1/n8n/webhook/github-event", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "accepted"
            assert "task_id" in data

    async def test_n8n_approval_lifecycle(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Request approval
            req_res = await client.post(
                "/api/v1/n8n/approval/request",
                json={
                    "task_id": "test_task_999",
                    "action_type": "delete_files",
                    "target": "D:\\tmp",
                    "risk_level": "HIGH",
                    "reason": "Bulk cleanup of 500 files"
                }
            )
            assert req_res.status_code == 200
            assert req_res.json()["status"] == "pending_approval"

            # 2. Respond approval
            resp_res = await client.post(
                "/api/v1/n8n/approval/response",
                json={
                    "task_id": "test_task_999",
                    "approved": True,
                    "approved_by": "telegram_admin"
                }
            )
            assert resp_res.status_code == 200
            assert resp_res.json()["decision"] == "APPROVED"

    async def test_n8n_workflows_list_endpoint(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/n8n/workflows")
            assert res.status_code == 200
            data = res.json()
            assert "workflows" in data
            assert data["count"] >= 5


class TestN8nAgentTools:
    """Test LangGraph / AI agent tools for n8n workflow discovery and triggering."""

    def test_list_n8n_workflows_tool(self):
        result = list_n8n_workflows.invoke({})
        assert "Available n8n Workflow Marketplace" in result
        assert "Daily PC Intelligence Report" in result or "daily_pc_health" in result

    def test_trigger_n8n_workflow_tool(self):
        result = trigger_n8n_workflow.invoke({"workflow_name": "daily_pc_health"})
        assert "Triggered n8n workflow" in result
