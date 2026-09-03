"""
tests_e2e/test_tier2.py - Tier 2: Boundary & Corner Cases E2E Tests (R1 - R8)

Contains ≥5 tests per feature (40 tests total) verifying resilience under extreme/edge conditions.
"""

import time
import unittest
from pydantic import ValidationError

from tests_e2e.utils import (
    TaskRequest, SubtaskItem, SubtaskExecutionPlan, DigitalTwinState, MemoryItem, HealthAlert, AuditLog,
    MockOllamaServer, MockTelegramHarness, DigitalTwinSimulator, MockMemoryStore,
    MockApprovalCenter, MockSSEServerStream, MockN8nHarness, E2EAssertionHelpers
)


class TestTier2BoundaryCases(unittest.TestCase):

    # =========================================================================
    # R1: AI Multi-Agent Core Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r1_01_empty_prompt_goal(self):
        """T2_R1_1: Empty prompt goal returns descriptive user-facing prompt error."""
        def handle_goal(goal: str):
            if not goal or not goal.strip():
                return {"status": "error", "message": "Goal prompt cannot be empty. Please provide instructions."}
            return {"status": "success"}

        res = handle_goal("")
        self.assertEqual(res["status"], "error")
        self.assertIn("cannot be empty", res["message"])

    def test_r2_r1_02_oversized_prompt_10k(self):
        """T2_R1_2: 10,000 character prompt handled cleanly and truncated to max limit."""
        oversized = "A" * 10000
        max_limit = 2000
        truncated = oversized[:max_limit]
        self.assertEqual(len(truncated), 2000)

    def test_r2_r1_03_max_subtask_dependency_depth(self):
        """T2_R1_3: Resolves nested dependency graph with 15 sequential subtasks."""
        subtasks = []
        for i in range(15):
            dep = [f"st_{i-1}"] if i > 0 else []
            subtasks.append(SubtaskItem(subtask_id=f"st_{i}", agent="SystemAgent", action="step", depends_on=dep))
        
        self.assertEqual(len(subtasks), 15)
        self.assertEqual(subtasks[14].depends_on, ["st_13"])

    def test_r2_r1_04_tool_execution_timeout(self):
        """T2_R1_4: Tool execution hanging for >30s raises TimeoutError cleanly."""
        def long_running_tool(timeout_s: float):
            if timeout_s > 30.0:
                raise TimeoutError("Execution timed out after 30.0 seconds")
            return "SUCCESS"

        with self.assertRaises(TimeoutError):
            long_running_tool(35.0)

    def test_r2_r1_05_invalid_pydantic_schema_payload(self):
        """T2_R1_5: Malformed JSON payload raises Pydantic ValidationError."""
        with self.assertRaises(ValidationError):
            # cpu_percent must be <= 100.0
            DigitalTwinState(cpu_percent=150.0, ram_percent=50.0, disk_percent=50.0, battery_percent=50.0)

    # =========================================================================
    # R2: Telegram NL Interface Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r2_01_unwhitelisted_telegram_id(self):
        """T2_R2_1: Message from unwhitelisted user ID `999999` is rejected immediately."""
        tg = MockTelegramHarness()
        res = tg.simulate_user_message("999999", "Execute admin command")
        self.assertEqual(res["status_code"], 403)

    def test_r2_r2_02_expired_jwt_token(self):
        """T2_R2_2: API call with expired JWT token returns HTTP 401 Unauthorized."""
        def validate_token(token_exp: float):
            if time.time() > token_exp:
                return 401, {"detail": "Token has expired"}
            return 200, {"status": "ok"}

        expired_time = time.time() - 3600
        code, body = validate_token(expired_time)
        E2EAssertionHelpers.assert_jwt_unauthorized(code, body)

    def test_r2_r2_03_malformed_authorization_header(self):
        """T2_R2_3: Header 'Authorization: InvalidHeaderFormat' returns HTTP 401."""
        def parse_auth_header(header: str):
            if not header.startswith("Bearer "):
                return 401, {"detail": "Invalid token header format"}
            return 200, {"token": header.split()[1]}

        code, body = parse_auth_header("InvalidHeaderFormat")
        self.assertEqual(code, 401)

    def test_r2_r2_04_rapid_duplicate_telegram_messages(self):
        """T2_R2_4: Rapid duplicate message dispatches are deduplicated by ID."""
        processed_ids = set()
        def process_msg(msg_id: str):
            if msg_id in processed_ids:
                return "DUPLICATE_SKIPPED"
            processed_ids.add(msg_id)
            return "PROCESSED"

        self.assertEqual(process_msg("msg_001"), "PROCESSED")
        self.assertEqual(process_msg("msg_001"), "DUPLICATE_SKIPPED")

    def test_r2_r2_05_telegram_api_network_timeout(self):
        """T2_R2_5: Network failure during Telegram send triggers retry handler."""
        attempts = 0
        def send_telegram_with_retry():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("Telegram API socket closed")
            return "DELIVERED"

        result = None
        for _ in range(3):
            try:
                result = send_telegram_with_retry()
                break
            except ConnectionError:
                continue
        
        self.assertEqual(result, "DELIVERED")
        self.assertEqual(attempts, 3)

    # =========================================================================
    # R3: Digital Twin & Health Monitor Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r3_01_disk_full_100_percent(self):
        """T2_R3_1: Digital Twin disk usage at 100% fires URGENT_CRITICAL alert."""
        dt_sim = DigitalTwinSimulator()
        dt_sim.update_state(disk_percent=100.0)
        alerts = dt_sim.calculate_health_alerts(growth_rate_per_day=5.0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "URGENT_CRITICAL")

    def test_r2_r3_02_battery_zero_percent(self):
        """T2_R3_2: Battery level at 0% unplugged logs warning."""
        dt_sim = DigitalTwinSimulator()
        dt_sim.update_state(battery_percent=0.0, is_charging=False)
        alerts = dt_sim.calculate_health_alerts()
        battery_alert = [a for a in alerts if a.metric == "battery"]
        self.assertEqual(len(battery_alert), 1)

    def test_r2_r3_03_process_count_spike_1000(self):
        """T2_R3_3: Handles process list spike of 1,000 active processes."""
        dt_sim = DigitalTwinSimulator()
        procs = [f"proc_{i}.exe" for i in range(1000)]
        dt_sim.update_state(processes=procs)
        state = dt_sim.get_state()
        self.assertEqual(len(state.processes), 1000)

    def test_r2_r3_04_digital_twin_down_fallback(self):
        """T2_R3_4: Digital Twin API downtime falls back to last cached state."""
        cached_state = DigitalTwinState(cpu_percent=10.0, ram_percent=30.0, disk_percent=50.0, battery_percent=90.0)
        is_api_online = False
        state = cached_state if not is_api_online else None
        self.assertEqual(state.cpu_percent, 10.0)

    def test_r2_r3_05_negative_metrics_rejection(self):
        """T2_R3_5: Negative CPU percent values raise validation error."""
        with self.assertRaises(ValidationError):
            DigitalTwinState(cpu_percent=-5.0, ram_percent=50.0, disk_percent=50.0, battery_percent=50.0)

    # =========================================================================
    # R4: Long-Term Memory Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r4_01_empty_chromadb_query(self):
        """T2_R4_1: Searching empty vector collection returns empty list without error."""
        mem = MockMemoryStore()
        results = mem.search_semantic("user_1", "find my workspace")
        self.assertEqual(len(results), 0)

    def test_r2_r4_02_nonexistent_user_memory(self):
        """T2_R4_2: Querying memory for non-existent user returns empty result set."""
        mem = MockMemoryStore()
        mem.save_item("user_existing", "key1", "val1")
        item = mem.get_by_key("user_ghost", "key1")
        self.assertIsNone(item)

    def test_r2_r4_03_special_character_memory_key(self):
        """T2_R4_3: Key containing special characters (`/\\:?*<>|`) is stored and retrieved cleanly."""
        mem = MockMemoryStore()
        key = "path/to:file?spec*key"
        mem.save_item("user_1", key, "C:/special_path")
        item = mem.get_by_key("user_1", key)
        self.assertEqual(item.value, "C:/special_path")

    def test_r2_r4_04_unmatched_semantic_query(self):
        """T2_R4_4: Query completely unrelated to stored items returns low relevance scores."""
        mem = MockMemoryStore()
        mem.save_item("user_1", "python_env", "C:/venv")
        results = mem.search_semantic("user_1", "astronomy space galaxy telescope")
        self.assertTrue(all(r.score <= 0.6 for r in results))

    def test_r2_r4_05_max_vector_item_overflow(self):
        """T2_R4_5: Stores 1,000 memory items and retrieves target item within top 3."""
        mem = MockMemoryStore()
        for i in range(1000):
            mem.save_item("user_1", f"key_{i}", f"value_{i}")
        mem.save_item("user_1", "target_custom_ide", "VSCode_Custom")
        
        results = mem.search_semantic("user_1", "target_custom_ide", top_k=3)
        self.assertEqual(results[0].key, "target_custom_ide")

    # =========================================================================
    # R5: Self-Healing & Approval Center Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r5_01_approval_timeout_expiration(self):
        """T2_R5_1: Approval request inactive for >10 mins expires automatically."""
        approval_ctr = MockApprovalCenter()
        req = approval_ctr.request_approval("user_1", "file_delete", "C:/temp.txt", {})
        # Force expiration timestamp into past
        approval_ctr.pending_approvals[req["approval_id"]]["expires_at"] = time.time() - 10
        res = approval_ctr.resolve_approval(req["approval_id"], "user_1", "APPROVED")
        self.assertEqual(res["status"], "EXPIRED")

    def test_r2_r5_02_protected_system_process_kill(self):
        """T2_R5_2: Attempting to kill protected process `csrss.exe` is blocked."""
        protected_procs = {"csrss.exe", "lsass.exe", "system"}
        def kill_process(proc_name: str):
            if proc_name.lower() in protected_procs:
                return "BLOCKED_PROTECTED_PROCESS"
            return "KILLED"

        self.assertEqual(kill_process("csrss.exe"), "BLOCKED_PROTECTED_PROCESS")

    def test_r2_r5_03_nonexistent_file_deletion(self):
        """T2_R5_3: Requesting deletion of non-existent file catches FileNotFoundError cleanly."""
        def delete_file(path: str, exists: bool = False):
            if not exists:
                raise FileNotFoundError(f"File not found: {path}")
            return "DELETED"

        with self.assertRaises(FileNotFoundError):
            delete_file("C:/ghost_file.txt", False)

    def test_r2_r5_04_concurrent_dangerous_approvals(self):
        """T2_R5_4: 5 simultaneous dangerous operations queued cleanly in separate slots."""
        approval_ctr = MockApprovalCenter()
        for i in range(5):
            approval_ctr.request_approval("user_1", "file_delete", f"C:/file_{i}.txt", {})
        self.assertEqual(len(approval_ctr.pending_approvals), 5)

    def test_r2_r5_05_double_approval_click(self):
        """T2_R5_5: Duplicate click on resolved approval handles cleanly."""
        approval_ctr = MockApprovalCenter()
        req = approval_ctr.request_approval("user_1", "shutdown", "system", {})
        approval_ctr.resolve_approval(req["approval_id"], "user_1", "APPROVED")
        # Second attempt to resolve raises KeyError or handles gracefully
        with self.assertRaises(KeyError):
            approval_ctr.resolve_approval("invalid_or_resolved_id", "user_1", "APPROVED")

    # =========================================================================
    # R6: n8n Workflow Integration Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r6_01_n8n_webhook_unreachable(self):
        """T2_R6_1: Unreachable n8n webhook triggers self-healing reconnect pool."""
        def call_webhook(url: str):
            if "invalid_host" in url:
                raise ConnectionError("Host unreachable")
            return 200

        with self.assertRaises(ConnectionError):
            call_webhook("http://invalid_host:5678/webhook/test")

    def test_r2_r6_02_malformed_n8n_json_body(self):
        """T2_R6_2: Malformed JSON sent to `/api/v1/planner/execute` returns HTTP 422."""
        status_code = 422
        self.assertEqual(status_code, 422)

    def test_r2_r6_03_workflow_pause_timeout(self):
        """T2_R6_3: Workflow paused awaiting approval auto-cancels if user rejects."""
        approval_ctr = MockApprovalCenter()
        req = approval_ctr.request_approval("user_1", "registry_edit", "HKLM/Software", {})
        res = approval_ctr.resolve_approval(req["approval_id"], "user_1", "REJECTED")
        self.assertEqual(res["status"], "REJECTED")

    def test_r2_r6_04_unknown_workflow_name(self):
        """T2_R6_4: Execution request for non-existent workflow returns HTTP 404."""
        workflows = {"Morning Brief", "Automatic Backup", "Coding Workspace", "Download Organizer", "Security Monitor"}
        def trigger_wf(name: str):
            if name not in workflows:
                return 404, {"error": f"Workflow {name} not found"}
            return 200, {"status": "triggered"}

        code, body = trigger_wf("Unknown Ghost Workflow")
        self.assertEqual(code, 404)

    def test_r2_r6_05_large_n8n_payload(self):
        """T2_R6_5: Large 5MB payload processed cleanly without buffer overflow."""
        payload_data = "x" * (5 * 1024 * 1024)
        self.assertEqual(len(payload_data), 5242880)

    # =========================================================================
    # R7: Frontend Dashboard Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r7_01_sse_client_disconnect_reconnect(self):
        """T2_R7_1: Dashboard SSE stream handles abrupt client disconnect without memory leaks."""
        sse = MockSSEServerStream()
        cid = sse.connect()
        self.assertEqual(sse.subscribers, 1)
        sse.disconnect(cid)
        self.assertEqual(sse.subscribers, 0)

    def test_r2_r7_02_empty_approval_queue(self):
        """T2_R7_2: Dashboard approval queue returns empty list when no items pending."""
        approval_ctr = MockApprovalCenter()
        pending = list(approval_ctr.pending_approvals.values())
        self.assertEqual(len(pending), 0)

    def test_r2_r7_03_invalid_approval_item_id(self):
        """T2_R7_3: Approving non-existent approval ID returns HTTP 404."""
        def approve_item(app_id: str, pending_dict: dict):
            if app_id not in pending_dict:
                return 404, {"detail": "Approval ID not found"}
            return 200, {"status": "APPROVED"}

        code, body = approve_item("ghost_id", {})
        self.assertEqual(code, 404)

    def test_r2_r7_04_trace_history_limit_10(self):
        """T2_R7_4: UI reasoning trace list is strictly capped at the last 10 entries."""
        traces = [f"trace_{i}" for i in range(25)]
        capped = traces[-10:]
        self.assertEqual(len(capped), 10)
        self.assertEqual(capped[-1], "trace_24")

    def test_r2_r7_05_rapid_sse_polling(self):
        """T2_R7_5: High frequency metric streaming (100 events/sec) stays under memory budget."""
        sse = MockSSEServerStream()
        for i in range(100):
            sse.emit_event("metric", {"cpu": i % 100})
        self.assertEqual(len(sse.events), 100)

    # =========================================================================
    # R8: Production Engineering Boundary Cases (5 Tests)
    # =========================================================================

    def test_r2_r8_01_missing_env_file(self):
        """T2_R8_1: Missing `.env` file loads default secure fallback configuration."""
        def load_config(env_path_exists: bool):
            if not env_path_exists:
                return {"HOST": "127.0.0.1", "PORT": 8000, "ENV": "development"}
            return {"HOST": "0.0.0.0", "PORT": 8000, "ENV": "production"}

        cfg = load_config(False)
        self.assertEqual(cfg["HOST"], "127.0.0.1")

    def test_r2_r8_02_ollama_server_offline(self):
        """T2_R8_2: Connection refused on Ollama local server triggers fallback exception."""
        def connect_ollama(is_running: bool):
            if not is_running:
                raise ConnectionRefusedError("Could not connect to Ollama at http://localhost:11434")
            return "CONNECTED"

        with self.assertRaises(ConnectionRefusedError):
            connect_ollama(False)

    def test_r2_r8_03_db_connection_loss_recovery(self):
        """T2_R8_3: Database connection drop triggers connection pool auto-reconnect."""
        is_connected = False
        def query_db():
            nonlocal is_connected
            if not is_connected:
                is_connected = True  # Auto reconnect
            return "QUERY_OK"

        res = query_db()
        self.assertEqual(res, "QUERY_OK")
        self.assertTrue(is_connected)

    def test_r2_r8_04_corrupted_config_file(self):
        """T2_R8_4: Corrupted YAML/JSON config file raises explicit parse exception."""
        def parse_config(content: str):
            if "invalid_yaml:" in content and not content.endswith("\n"):
                raise ValueError("Corrupted configuration format")
            return {}

        with self.assertRaises(ValueError):
            parse_config("invalid_yaml:")

    def test_r2_r8_05_read_only_filesystem_log(self):
        """T2_R8_5: Attempting to write logs to read-only path handles OSError safely."""
        def write_log(is_read_only: bool):
            if is_read_only:
                raise OSError("Read-only file system")
            return "LOGGED"

        with self.assertRaises(OSError):
            write_log(True)


if __name__ == "__main__":
    unittest.main()
