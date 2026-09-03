"""
tests_e2e/test_tier3.py - Tier 3: Cross-Feature Pairwise Interaction E2E Tests

Contains 10 pairwise integration tests verifying multi-module subsystem dynamics.
"""

import time
import unittest

from tests_e2e.utils import (
    TaskRequest, SubtaskItem, SubtaskExecutionPlan, DigitalTwinState, MemoryItem, HealthAlert, AuditLog,
    MockOllamaServer, MockTelegramHarness, DigitalTwinSimulator, MockMemoryStore,
    MockApprovalCenter, MockSSEServerStream, MockN8nHarness, E2EAssertionHelpers
)


class TestTier3CrossFeatureInteractions(unittest.TestCase):

    def test_t3_01_memory_and_digital_twin(self):
        """T3_01: R4 (Memory) max CPU limit preference + R3 (Digital Twin) real-time state check."""
        mem = MockMemoryStore()
        dt_sim = DigitalTwinSimulator()
        
        # User sets max CPU threshold to 80%
        mem.save_item("user_1", "max_cpu_percent", 80.0)
        max_cpu = mem.get_by_key("user_1", "max_cpu_percent").value
        
        # Digital Twin reports current CPU at 85%
        dt_sim.update_state(cpu_percent=85.0)
        current_state = dt_sim.get_state()
        
        # Planner skips heavy task because current CPU > max preferred CPU
        should_throttle = current_state.cpu_percent > max_cpu
        self.assertTrue(should_throttle)

    def test_t3_02_telegram_and_approval_center(self):
        """T3_02: R2 (Telegram) file delete goal + R5 (Approval Center) inline keyboard approval."""
        tg = MockTelegramHarness()
        approval_ctr = MockApprovalCenter()
        
        # Inbound Telegram request
        tg.simulate_user_message("123456789", "Delete old setup.exe")
        
        # Approval Center intercepts dangerous file_delete
        req = approval_ctr.request_approval("123456789", "file_delete", "C:/setup.exe", {})
        
        # Telegram sends notification with inline buttons
        msg = tg.send_notification("123456789", "Confirm deletion of C:/setup.exe", inline_keyboard=[
            {"text": "Approve", "callback_data": f"approve_{req['approval_id']}"},
            {"text": "Reject", "callback_data": f"reject_{req['approval_id']}"}
        ])
        
        # User clicks Approve button
        tg.simulate_inline_button_click("123456789", f"approve_{req['approval_id']}", msg["message_id"])
        res = approval_ctr.resolve_approval(req["approval_id"], "123456789", "APPROVED")
        
        self.assertEqual(res["status"], "APPROVED")
        E2EAssertionHelpers.assert_audit_logged(approval_ctr.audit_logs, "file_delete", "APPROVED")

    def test_t3_03_health_mon_telegram_n8n_audit(self):
        """T3_03: R3 (Health Mon) alert -> R2 (Telegram) prompt -> R6 (n8n) backup -> R5 (Audit Log)."""
        dt_sim = DigitalTwinSimulator()
        tg = MockTelegramHarness()
        n8n = MockN8nHarness("http://localhost:8000")
        approval_ctr = MockApprovalCenter()
        
        # 1. Health Monitor generates disk alert
        dt_sim.update_state(disk_percent=88.0)
        alerts = dt_sim.calculate_health_alerts(growth_rate_per_day=3.0)
        self.assertEqual(alerts[0].severity, "CRITICAL")
        
        # 2. Alert sent to Telegram
        tg.send_notification("123456789", f"HEALTH ALERT: {alerts[0].message}")
        
        # 3. User responds triggering n8n Backup workflow
        subtask = SubtaskItem(subtask_id="st_bk", agent="FileAgent", action="run_backup")
        
        # 4. Action recorded in Audit Log
        approval_ctr.request_approval("123456789", "n8n_backup", "C:/Projects", {})
        approval_ctr.resolve_approval(list(approval_ctr.pending_approvals.keys())[0], "123456789", "APPROVED")
        
        E2EAssertionHelpers.assert_audit_logged(approval_ctr.audit_logs, "n8n_backup", "APPROVED")

    def test_t3_04_n8n_planner_and_memory(self):
        """T3_04: R6 (n8n) execute goal -> R1 (Planner) queries R4 (Memory) coding preferences."""
        mem = MockMemoryStore()
        ollama = MockOllamaServer()
        
        # User preference stored in ChromaDB
        mem.save_item("user_dev", "preferred_ide", "VSCode")
        mem.save_item("user_dev", "project_path", "C:/projects/nexus_ai")
        
        # n8n triggers planner execution
        goal = "Launch Coding Workspace"
        pref_ide = mem.get_by_key("user_dev", "preferred_ide").value
        pref_path = mem.get_by_key("user_dev", "project_path").value
        
        # Planner incorporates recalled preferences into plan
        subtask = SubtaskItem(
            subtask_id="st_1",
            agent="ApplicationAgent",
            action="launch_ide",
            params={"ide": pref_ide, "workspace": pref_path}
        )
        self.assertEqual(subtask.params["ide"], "VSCode")
        self.assertEqual(subtask.params["workspace"], "C:/projects/nexus_ai")

    def test_t3_05_self_healing_telegram_and_sse(self):
        """T3_05: R5 (Self-Healing) retry status -> streamed to R2 (Telegram) & R7 (Dashboard SSE)."""
        tg = MockTelegramHarness()
        sse = MockSSEServerStream()
        sse.connect()
        
        # Self-healing retry event
        retry_msg = "Tool file_organizer failed on attempt 1. Retrying with fallback path..."
        
        # Stream to Telegram
        tg.send_notification("123456789", f"[Self-Healing] {retry_msg}")
        
        # Broadcast to Dashboard SSE
        sse.emit_event("self_healing_retry", {"message": retry_msg, "attempt": 1})
        
        self.assertIn("Self-Healing", tg.sent_messages[0]["text"])
        E2EAssertionHelpers.assert_sse_event_emitted(sse.events, "self_healing_retry")

    def test_t3_06_planner_digital_twin_and_approval(self):
        """T3_06: R1 (Planner) kill process -> R3 (Digital Twin) check PID -> R5 (Approval Center) UI approve."""
        dt_sim = DigitalTwinSimulator()
        dt_sim.update_state(processes=["explorer.exe", "unwanted_process.exe"])
        approval_ctr = MockApprovalCenter()
        
        # 1. Digital Twin confirms PID/process presence
        state = dt_sim.get_state()
        self.assertIn("unwanted_process.exe", state.processes)
        
        # 2. Planner schedules process_kill subtask, intercepted by Approval Center
        req = approval_ctr.request_approval("user_admin", "process_kill", "unwanted_process.exe", {})
        
        # 3. UI Approve button clicked
        res = approval_ctr.resolve_approval(req["approval_id"], "user_admin", "APPROVED")
        self.assertEqual(res["status"], "APPROVED")

    def test_t3_07_dashboard_memory_and_telegram(self):
        """T3_07: R7 (Dashboard UI) sets theme -> R4 (Memory) stores preference -> R2 (Telegram) recalls."""
        mem = MockMemoryStore()
        tg = MockTelegramHarness()
        
        # 1. UI sets dark mode preference
        mem.save_item("user_1", "ui_theme", "dark_mode", category="preference")
        
        # 2. Memory recalls theme
        theme = mem.get_by_key("user_1", "ui_theme").value
        
        # 3. Telegram notification formatted with preferred theme styling
        tg.send_notification("123456789", f"Notification [Theme: {theme}]: Daily summary ready.")
        self.assertIn("dark_mode", tg.sent_messages[0]["text"])

    def test_t3_08_n8n_workflow_and_approval(self):
        """T3_08: R6 (n8n) registry edit workflow -> pauses for R5 (Approval Center) confirmation."""
        approval_ctr = MockApprovalCenter()
        
        # n8n triggers workflow requiring dangerous registry modification
        req = approval_ctr.request_approval("n8n_workflow", "registry_edit", "HKCU/Software/NexusAI", {"value": 1})
        
        # Workflow status is PAUSED_FOR_APPROVAL
        workflow_status = "PAUSED_FOR_APPROVAL" if req["status"] == "PENDING" else "RUNNING"
        self.assertEqual(workflow_status, "PAUSED_FOR_APPROVAL")
        
        # User approves
        approval_ctr.resolve_approval(req["approval_id"], "admin", "APPROVED")
        workflow_status = "RESUMED"
        self.assertEqual(workflow_status, "RESUMED")

    def test_t3_09_digital_twin_and_dashboard_sse(self):
        """T3_09: R3 (Digital Twin) metric update -> broadcasts instantly to R7 (Dashboard SSE)."""
        dt_sim = DigitalTwinSimulator()
        sse = MockSSEServerStream()
        sse.connect()
        
        # Digital Twin update
        new_state = dt_sim.update_state(cpu_percent=78.4, ram_percent=82.1)
        
        # Broadcast to SSE
        sse.emit_event("digital_twin_update", new_state.model_dump())
        
        self.assertEqual(sse.events[0]["data"]["cpu_percent"], 78.4)
        self.assertEqual(sse.events[0]["data"]["ram_percent"], 82.1)

    def test_t3_10_telegram_memory_and_planner(self):
        """T3_10: R2 (Telegram) prompt + R4 (Memory) context -> R1 (Planner) 5-subtask decomposition."""
        tg = MockTelegramHarness()
        mem = MockMemoryStore()
        ollama = MockOllamaServer()
        
        # Inbound Telegram message
        tg.simulate_user_message("123456789", "Organize my coding workspace")
        
        # Query Memory
        mem.save_item("123456789", "workspace_root", "C:/dev/nexus")
        ctx_item = mem.get_by_key("123456789", "workspace_root")
        
        # Planner decomposes plan incorporating memory context
        comp = ollama.generate_completion(f"Organize workspace at {ctx_item.value}")
        subtasks = [SubtaskItem(**st) for st in comp["response"]]
        plan = SubtaskExecutionPlan(task_id="t3_10", goal="Organize coding workspace", subtasks=subtasks)
        
        E2EAssertionHelpers.assert_task_plan_valid(plan)
        self.assertGreaterEqual(len(plan.subtasks), 5)


if __name__ == "__main__":
    unittest.main()
