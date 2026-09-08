"""
Tests for Intelligent Email Workflow & n8n Gmail Integration.
"""
import pytest
from app.agents.email_workflow import email_agent
from app.agents.tools.app_tools import send_intelligent_email
from app.agents.planner import IntentRouter


@pytest.mark.asyncio
class TestEmailWorkflow:
    """Test Email Agent and n8n integration."""

    async def test_plan_and_draft_professor_email(self):
        prompt = "Send my project report to my professor"
        draft = await email_agent.plan_and_draft_email(prompt, user_name="Charan")

        assert "professor" in draft["to"].lower()
        assert "Report" in draft["subject"]
        assert "Dear Professor" in draft["body"]
        assert "Charan" in draft["body"]

    async def test_plan_and_draft_team_update(self):
        prompt = "Send today's project update to my team"
        draft = await email_agent.plan_and_draft_email(prompt, user_name="Charan")

        assert "team" in draft["to"].lower()
        assert "Update" in draft["subject"]
        assert "Team" in draft["body"]

    async def test_dispatch_to_n8n(self):
        draft = {
            "to": "test_user@example.com",
            "subject": "Test Project Report",
            "body": "Please find attached the report.",
            "attachments": [],
        }
        res = await email_agent.dispatch_to_n8n(draft)
        assert res["success"] is True
        assert "test_user@example.com" in res["message"]

    def test_intent_router_email_detection(self):
        subtasks = IntentRouter.detect("Send my project report to my professor")
        assert subtasks is not None
        assert len(subtasks) == 1
        assert subtasks[0]["tool"] == "send_intelligent_email"
        assert subtasks[0]["requires_approval"] is True

    def test_send_intelligent_email_tool(self):
        fn = getattr(send_intelligent_email, "func", send_intelligent_email)
        res = fn("Send my project report to my professor")
        assert res["success"] is True
        assert "recipient" in res
        assert "subject" in res
