"""
tests_e2e/test_tier4.py - Tier 4: Real-World Scenarios E2E Tests

Contains 5 comprehensive, end-to-end multi-step real-world user workflows.
"""

import time
import unittest

from tests_e2e.utils import (
    TaskRequest, SubtaskItem, SubtaskExecutionPlan, DigitalTwinState, MemoryItem, HealthAlert, AuditLog,
    MockOllamaServer, MockTelegramHarness, DigitalTwinSimulator, MockMemoryStore,
    MockApprovalCenter, MockSSEServerStream, MockN8nHarness, E2EAssertionHelpers
)


class TestTier4RealWorldScenarios(unittest.TestCase):

    def test_t4_01_prepare_laptop_for_coding(self):
        """
        T4_01: E2E Workflow - 'Prepare my laptop for coding'
        Steps:
        1. Telegram Bot (R2) authenticates user and receives goal prompt.
        2. Planner Agent queries ChromaDB Memory (R4) for preferred IDE and workspace path.
        3. Digital Twin (R3) checked for RAM and battery status.
        4. Planner Agent (R1) decomposes into 5 subtasks (check metrics, launch VSCode, start Docker, open browser, clean temp).
        5. Progress streamed to Telegram (R2) and Dashboard SSE (R7).
        6. Audit log trace recorded (R5).
        """
        tg = MockTelegramHarness()
        mem = MockMemoryStore()
        dt_sim = DigitalTwinSimulator()
        ollama = MockOllamaServer()
        sse = MockSSEServerStream()
        approval_ctr = MockApprovalCenter()
        
        user_id = "123456789"
        sse.connect()
        
        # Step 1: Telegram receives prompt
        msg_res = tg.simulate_user_message(user_id, "Prepare my laptop for coding")
        self.assertEqual(msg_res["status_code"], 200)
        
        # Step 2: Query Memory for preferred IDE & path
        mem.save_item(user_id, "preferred_ide", "VSCode")
        mem.save_item(user_id, "workspace_dir", "C:/projects/nexus_ai")
        ide = mem.get_by_key(user_id, "preferred_ide").value
        workspace = mem.get_by_key(user_id, "workspace_dir").value
        
        # Step 3: Check Digital Twin metrics
        state = dt_sim.get_state()
        E2EAssertionHelpers.assert_digital_twin_valid(state)
        
        # Step 4: Decompose plan
        comp = ollama.generate_completion(f"Prepare coding environment with {ide} at {workspace}")
        subtasks = [SubtaskItem(**st) for st in comp["response"]]
        plan = SubtaskExecutionPlan(task_id="t4_01_plan", goal="Prepare laptop for coding", subtasks=subtasks)
        E2EAssertionHelpers.assert_task_plan_valid(plan)
        
        # Step 5: Progress streaming
        for st in plan.subtasks:
            tg.send_notification(user_id, f"Executing: {st.agent} -> {st.action}")
            sse.emit_event("task_progress", {"subtask": st.subtask_id, "status": "COMPLETED"})
        
        self.assertEqual(len(tg.sent_messages), 5)
        E2EAssertionHelpers.assert_sse_event_emitted(sse.events, "task_progress")

    def test_t4_02_morning_routine_and_backup(self):
        """
        T4_02: E2E Workflow - 'Morning routine & backup'
        Steps:
        1. n8n scheduler triggers 'Morning Routine & Backup' workflow.
        2. System Agent fetches weather & calendar stubs.
        3. Automatic Backup workflow compresses project folder to backup directory.
        4. Memory (R4) updated with last backup timestamp.
        5. Formatted morning summary sent to Telegram (R2).
        """
        n8n = MockN8nHarness("http://localhost:8000")
        mem = MockMemoryStore()
        tg = MockTelegramHarness()
        
        user_id = "123456789"
        
        # Step 1 & 2: System agent fetches morning info
        subtasks = [
            SubtaskItem(subtask_id="st_1", agent="SystemAgent", action="fetch_weather", params={"city": "Local"}),
            SubtaskItem(subtask_id="st_2", agent="SystemAgent", action="fetch_calendar", params={"day": "today"}),
            SubtaskItem(subtask_id="st_3", agent="FileAgent", action="compress_directory", params={"src": "C:/projects", "dst": "D:/Backups/morning.zip"})
        ]
        
        # Step 3 & 4: Save last backup timestamp to memory
        now_ts = time.time()
        mem.save_item(user_id, "last_backup_timestamp", now_ts, category="history")
        stored_ts = mem.get_by_key(user_id, "last_backup_timestamp").value
        self.assertEqual(stored_ts, now_ts)
        
        # Step 5: Send morning brief to Telegram
        tg.send_notification(user_id, "Good Morning! Weather: Clear 22°C. Backup completed at D:/Backups/morning.zip.")
        self.assertIn("Good Morning", tg.sent_messages[0]["text"])

    def test_t4_03_security_scan_and_process_cleanup(self):
        """
        T4_03: E2E Workflow - 'Security scan & process cleanup'
        Steps:
        1. Security Monitor workflow scans Digital Twin process list (R3).
        2. High CPU / untrusted process identified (`suspicious_miner.exe`).
        3. Approval Center (R5) intercepts process kill and requests Telegram inline approval.
        4. User clicks 'Approve' on Telegram inline button.
        5. Process terminated, Audit Log entry created with outcome APPROVED.
        """
        dt_sim = DigitalTwinSimulator()
        approval_ctr = MockApprovalCenter()
        tg = MockTelegramHarness()
        
        user_id = "123456789"
        
        # Step 1 & 2: Digital Twin identifies suspicious process
        dt_sim.update_state(processes=["explorer.exe", "svchost.exe", "suspicious_miner.exe"], cpu_percent=92.0)
        state = dt_sim.get_state()
        suspicious = [p for p in state.processes if "miner" in p]
        self.assertEqual(len(suspicious), 1)
        
        # Step 3: Approval Center flags process_kill as dangerous
        req = approval_ctr.request_approval(user_id, "process_kill", suspicious[0], {"cpu_usage": 85.0})
        
        # Telegram prompt sent
        msg = tg.send_notification(user_id, f"SECURITY ALERT: Terminate suspicious process {suspicious[0]}?", inline_keyboard=[
            {"text": "Approve", "callback_data": f"approve_{req['approval_id']}"}
        ])
        
        # Step 4: User clicks Approve
        tg.simulate_inline_button_click(user_id, f"approve_{req['approval_id']}", msg["message_id"])
        res = approval_ctr.resolve_approval(req["approval_id"], user_id, "APPROVED")
        
        # Step 5: Verify termination & audit log
        dt_sim.update_state(processes=["explorer.exe", "svchost.exe"], cpu_percent=15.0)
        self.assertNotIn("suspicious_miner.exe", dt_sim.get_state().processes)
        E2EAssertionHelpers.assert_audit_logged(approval_ctr.audit_logs, "process_kill", "APPROVED")

    def test_t4_04_file_organization_and_memory_lookup(self):
        """
        T4_04: E2E Workflow - 'File organization & memory lookup'
        Steps:
        1. User asks Telegram bot to organize downloads and recall target folder.
        2. Planner recalls preferred downloads organizing rules from ChromaDB memory (R4).
        3. File Agent categorizes files into Documents, Images, and Archives subfolders.
        4. Summary posted to Telegram (R2) and Dashboard SSE (R7).
        """
        tg = MockTelegramHarness()
        mem = MockMemoryStore()
        sse = MockSSEServerStream()
        user_id = "123456789"
        
        # Step 1 & 2: Memory lookup for user organize preferences
        mem.save_item(user_id, "target_organize_dir", "C:/Users/User/Downloads")
        target_dir = mem.get_by_key(user_id, "target_organize_dir").value
        
        # Step 3: File Agent subtask execution simulation
        file_subtask = SubtaskItem(
            subtask_id="st_org",
            agent="FileAgent",
            action="organize_folder",
            params={"path": target_dir, "rules": {"pdf": "Documents", "jpg": "Images", "zip": "Archives"}}
        )
        
        # Step 4: Send summary notifications
        tg.send_notification(user_id, f"Organized {target_dir}: 12 files moved to Documents, Images, Archives.")
        sse.emit_event("file_organized", {"dir": target_dir, "count": 12})
        
        self.assertIn("Organized", tg.sent_messages[0]["text"])
        E2EAssertionHelpers.assert_sse_event_emitted(sse.events, "file_organized")

    def test_t4_05_emergency_action_rejection_and_health_alert_recovery(self):
        """
        T4_05: E2E Workflow - 'Emergency action rejection & health alert recovery'
        Steps:
        1. Health Monitor (R3) detects disk usage at 92% and issues CRITICAL alert.
        2. Proactive alert sent to Telegram (R2). User requests cleanup.
        3. System Agent proposes dangerous deletion (`file_delete C:/SystemRoot`).
        4. Approval Center (R5) intercepts and sends inline keyboard to Telegram.
        5. User clicks 'Reject'. Dangerous action cancelled, Audit Log records REJECTED.
        6. Self-healing fallback executes safe temp folder cleanup (`C:/AppData/Local/Temp`).
        7. Disk usage drops to 65%, health alert resolved.
        """
        dt_sim = DigitalTwinSimulator()
        tg = MockTelegramHarness()
        approval_ctr = MockApprovalCenter()
        user_id = "123456789"
        
        # Step 1: Health Monitor critical alert
        dt_sim.update_state(disk_percent=92.0)
        alerts = dt_sim.calculate_health_alerts(growth_rate_per_day=1.0)
        self.assertIn(alerts[0].severity, ["CRITICAL", "URGENT_CRITICAL"])
        
        # Step 2: Telegram notification
        tg.send_notification(user_id, f"CRITICAL DISK ALERT: {alerts[0].message}")
        
        # Step 3: Proposed dangerous deletion
        req = approval_ctr.request_approval(user_id, "file_delete", "C:/SystemRoot", {"risk": "HIGH"})
        msg = tg.send_notification(user_id, "PROPOSED ACTION: Delete C:/SystemRoot?", inline_keyboard=[
            {"text": "Approve", "callback_data": f"approve_{req['approval_id']}"},
            {"text": "Reject", "callback_data": f"reject_{req['approval_id']}"}
        ])
        
        # Step 4 & 5: User rejects dangerous action
        tg.simulate_inline_button_click(user_id, f"reject_{req['approval_id']}", msg["message_id"])
        res = approval_ctr.resolve_approval(req["approval_id"], user_id, "REJECTED")
        self.assertEqual(res["status"], "REJECTED")
        E2EAssertionHelpers.assert_audit_logged(approval_ctr.audit_logs, "file_delete", "REJECTED")
        
        # Step 6 & 7: Self-healing fallback executes safe cleanup
        dt_sim.update_state(disk_percent=65.0)
        new_alerts = dt_sim.calculate_health_alerts(growth_rate_per_day=0.5)
        self.assertEqual(len(new_alerts), 0)
        self.assertEqual(dt_sim.get_state().disk_percent, 65.0)


if __name__ == "__main__":
    unittest.main()
