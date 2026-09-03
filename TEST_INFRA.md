# Nexus AI E2E Test Suite Infrastructure & Architecture Specification (`TEST_INFRA.md`)

**Project**: Nexus AI — Local-First Autonomous Desktop AI Agent Framework for Windows  
**Document Type**: End-to-End Test Suite Infrastructure Blueprint & Execution Specification  
**Version**: 1.0.0  
**Scope**: Tiers 1–4 Opaque-Box E2E Testing Framework (`tests_e2e/`)

---

## 1. Executive Summary & Testing Philosophy

Nexus AI is a local-first autonomous desktop AI agent framework designed for Windows. To guarantee 100% operational integrity, zero regressions, and full compliance with core requirements R1–R8, this document establishes the specification for the **Opaque-Box End-to-End (E2E) Test Suite**.

### Core Testing Principles
1. **Opaque-Box (Black-Box / Gray-Box) Contract Testing**: Tests interact strictly with public system boundaries — REST endpoints, WebSockets / SSE streams, Telegram Bot message handlers, n8n REST webhooks, and CLI commands. No internal implementation details or private agent states are accessed directly.
2. **100% Offline & Zero Paid API Footprint**: All external integrations (Ollama LLM, Telegram API servers, n8n webhooks) are handled via deterministic local mock harnesses (`tests_e2e/utils.py`). No live paid LLM APIs or external network calls are made during test execution.
3. **Requirement-Driven Verification**: Test cases are systematically constructed to map directly to core requirements R1 through R8 using industry-standard test design techniques:
   - **Category-Partition Method**: Systematic input domain partitioning.
   - **Boundary Value Analysis (BVA)**: Critical limits, thresholds, power states, and disk projections.
   - **Pairwise Combination Testing**: Multi-subsystem interaction matrices.
   - **Workload & Real-World Scenario Testing**: Complete end-to-end user workflows.

---

## 2. Feature Inventory Matrix (R1–R8)

| Requirement ID | Module Name | Scope & Core Responsibilities | Test Contract Boundary |
|---|---|---|---|
| **R1** | AI Multi-Agent Core | LangChain + CrewAI + Llama 3 local LLM. Planner Agent decomposes goals into dependency graphs (≥5 subtasks). Specialized agents: System, Application, File. Structured Pydantic messaging. | Task graph resolution, subtask dispatch, Pydantic model validation, tool payload verification. |
| **R2** | Telegram NL Interface | Natural language interaction via Telegram bot. Progress update streaming (>3s tasks), final summary delivery, whitelist authorization, JWT internal token authentication. | Whitelist enforcement, HTTP 401/403 rejection, SSE / Telegram stream updates, summary formatting. |
| **R3** | Digital Twin & Health Monitor | In-memory + DB system model (CPU, RAM, disk, battery, processes, active windows, network, clipboard). Health Monitor background worker generating predictive alerts (e.g. disk full in <14 days). | `GET /api/v1/digital-twin/state`, OS abstraction enforcement, predictive alert generation. |
| **R4** | Long-Term Memory | ChromaDB vector store + PostgreSQL/Redis. Personalization, preference retrieval across sessions (e.g. IDE path session 1 -> session 2), semantic top-3 search. | Multi-session recall, top-3 semantic match relevance, user/session scope isolation. |
| **R5** | Self-Healing & Approval Center | Fault-tolerant executor wrapper. Automatic retry with alternative strategy on failure. Root cause delivery via Telegram (<30s). Approval Center for dangerous actions (file delete, shutdown, process kill, registry) via Telegram inline keyboard & UI audit log. | Retry loop trigger, error report delivery, dangerous action blockage, inline keyboard approve/reject handling, audit log persistence. |
| **R6** | n8n Workflow Integration | 5 workflows: Morning Brief, Automatic Backup, Coding Workspace, Download Organizer, Security Monitor. REST API integration via `POST /api/v1/planner/execute`. Approval flow pausing. | REST webhook payload handling, workflow execution output, approval pause & resume state machine. |
| **R7** | Frontend Dashboard | React/Next.js UI displaying real-time metrics (CPU, RAM, network refresh ≤5s), AI reasoning trace history (last 10 tasks), UI approval queue, audit log, workflow statuses. | SSE / WebSocket stream payload validation, UI approval/rejection REST API, reasoning trace array integrity. |
| **R8** | Production Engineering | Docker Compose containerization, zero paid API offline operation, GitHub Actions CI workflow, env variable secret management, unit tests covering tool functions (≥10 test cases). | Docker stack readiness, CI execution, zero external network calls verification, CLI exit code 0. |

---

## 3. Test Suite Architecture & File Layout

The test suite resides in `tests_e2e/` and is managed by `tests_e2e/runner.py`.

```
nexus_ai/
├── TEST_INFRA.md             # This comprehensive architecture & design document
├── TEST_READY.md             # Verification summary & test matrix table (published upon pass)
├── tests_e2e/
│   ├── __init__.py           # Package initializer
│   ├── utils.py              # Mock server harnesses, Pydantic models, SSE/WS stubs, assertions
│   ├── test_tier1.py         # Tier 1: Feature Coverage (40 tests, ≥5 per feature R1-R8)
│   ├── test_tier2.py         # Tier 2: Boundary & Corner Cases (40 tests, ≥5 per feature R1-R8)
│   ├── test_tier3.py         # Tier 3: Cross-Feature Pairwise Interactions (10 pairwise tests)
│   ├── test_tier4.py         # Tier 4: Real-World Scenarios (5 realistic workflows)
│   └── runner.py             # CLI runner with discovery, tier filtering, ASCII summary tables
```

---

## 4. Tier Breakdown & Test Catalog

### 4.1 Tier 1: Feature Coverage (40 Test Cases — ≥5 per feature R1–R8)
Validates core functional happy-paths across all features.

- **R1: AI Multi-Agent Core**
  - `test_r1_01_planner_decomposition`: Verifies prompt goal generates ≥5 subtasks with proper dependency graphs.
  - `test_r1_02_system_agent_metrics`: System agent queries Digital Twin metrics (CPU, RAM, battery).
  - `test_r1_03_application_agent_launch_close`: Application agent dispatches structured launch/close payloads.
  - `test_r1_04_file_agent_search_zip`: File agent searches directory and creates zip archive successfully.
  - `test_r1_05_pydantic_message_schemas`: Validates serialization/deserialization of `TaskRequest` and `SubtaskExecutionPlan`.

- **R2: Telegram NL Interface**
  - `test_r2_01_natural_language_goal`: Inbound natural language goal triggers pipeline execution.
  - `test_r2_02_progress_streaming`: Long-running execution (>3s) streams intermediate progress events.
  - `test_r2_03_whitelist_user_authorization`: Rejects goals from user IDs not listed in whitelist.
  - `test_r2_04_jwt_internal_authentication`: Rejects unauthenticated requests with HTTP 401 Unauthorized.
  - `test_r2_05_structured_summary_delivery`: Final execution completes with structured markdown summary.

- **R3: Digital Twin & Health Monitor**
  - `test_r3_01_digital_twin_freshness`: State update reflects in `GET /api/v1/digital-twin/state` within <5s.
  - `test_r3_02_health_monitor_trend_analysis`: Health Monitor background worker projects disk fill date.
  - `test_r3_03_predictive_disk_alert_trigger`: Predictive alert fires when disk full projection < 14 days.
  - `test_r3_04_os_abstraction_enforcement`: Agent execution routines query Digital Twin API instead of raw OS calls.
  - `test_r3_05_digital_twin_schema_validation`: Digital Twin response conforms to Pydantic `DigitalTwinState`.

- **R4: Long-Term Memory**
  - `test_r4_01_multi_session_preference_recall`: Session 1 stored preference recalled in Session 2.
  - `test_r4_02_top3_semantic_memory_search`: Vector store search returns relevant path in top 3 results.
  - `test_r4_03_user_session_scope_isolation`: Querying User A's private scope from User B token yields 0 results.
  - `test_r4_04_agent_preference_customization`: Planner selects user's preferred IDE from ChromaDB memory.
  - `test_r4_05_chromadb_vector_persistence`: Memory items persist correctly in vector store.

- **R5: Self-Healing & Approval Center**
  - `test_r5_01_self_healing_automatic_retry`: Executor retries tool execution with alternative parameters on failure.
  - `test_r5_02_failure_root_cause_delivery`: Persistent tool failure delivers root cause analysis via Telegram <30s.
  - `test_r5_03_dangerous_action_blockage`: Dangerous actions (`file_delete`, `shutdown`, `process_kill`, `registry`) flag and halt.
  - `test_r5_04_inline_keyboard_approval`: Clicking `Approve` on Telegram inline keyboard resumes execution.
  - `test_r5_05_audit_log_recording`: Approved/rejected dangerous operations insert record in `AuditLog`.

- **R6: n8n Workflow Integration**
  - `test_r6_01_morning_brief_workflow`: `POST /api/v1/planner/execute` runs Morning Brief workflow.
  - `test_r6_02_automatic_backup_workflow`: Automatic Backup workflow compresses target directories.
  - `test_r6_03_coding_workspace_workflow`: Coding Workspace workflow launches IDE, terminal, and browser.
  - `test_r6_04_download_organizer_workflow`: Download Organizer workflow categorizes files into subfolders.
  - `test_r6_05_security_monitor_workflow`: Security Monitor workflow scans running processes and generates report.

- **R7: Frontend Dashboard**
  - `test_r7_01_realtime_metrics_sse_stream`: SSE stream `/api/v1/metrics/stream` emits JSON metrics with ≤5s refresh.
  - `test_r7_02_reasoning_trace_list`: REST endpoint returns list of last 10 task execution traces.
  - `test_r7_03_dashboard_approval_queue`: Dashboard approval queue returns list of pending dangerous items.
  - `test_r7_04_ui_approve_reject_endpoints`: POST to `/api/v1/approval/{id}/approve` removes item and unblocks execution.
  - `test_r7_05_live_audit_log_sse`: Audit log events broadcast live over SSE event channel.

- **R8: Production Engineering**
  - `test_r8_01_docker_stack_health`: Querying backend health endpoint confirms service readiness.
  - `test_r8_02_zero_paid_api_compliance`: Network traffic analyzer verifies 0 outbound paid API calls.
  - `test_r8_03_env_secret_resolution`: Missing secret token triggers clear configuration exception.
  - `test_r8_04_unit_test_tool_coverage`: Unit test suite verifies system/application/file agent tool functions.
  - `test_r8_05_ci_runner_execution`: E2E test runner executes to completion returning exit code 0.

---

### 4.2 Tier 2: Boundary & Corner Cases (40 Test Cases — ≥5 per feature R1–R8)
Validates system resilience against extreme values, unexpected states, timeouts, and authorization failures.

- **R1 Boundary Cases**:
  - `test_r2_r1_01_empty_prompt_goal`: Empty prompt string returns user-friendly guidance.
  - `test_r2_r1_02_oversized_prompt_10k`: 10,000 character goal prompt handled cleanly without crash.
  - `test_r2_r1_03_max_subtask_dependency_depth`: Plan with 15 nested dependencies resolves execution order correctly.
  - `test_r2_r1_04_tool_execution_timeout`: Tool hanging for >30s raises execution timeout.
  - `test_r2_r1_05_invalid_pydantic_schema_payload`: Malformed Pydantic JSON payload raises validation error.

- **R2 Boundary Cases**:
  - `test_r2_r2_01_unwhitelisted_telegram_id`: Inbound message from unauthorized user ID dropped cleanly.
  - `test_r2_r2_02_expired_jwt_token`: API request with expired JWT token returns HTTP 401.
  - `test_r2_r2_03_malformed_authorization_header`: Header `Authorization: InvalidFormat` returns HTTP 401.
  - `test_r2_r2_04_rapid_duplicate_telegram_messages`: Duplicate message IDs deduplicated cleanly.
  - `test_r2_r2_05_telegram_api_network_timeout`: Network timeout on Telegram API handled with retry pool.

- **R3 Boundary Cases**:
  - `test_r2_r3_01_disk_full_100_percent`: Digital Twin disk at 100% usage triggers URGENT CRITICAL alert.
  - `test_r2_r3_02_battery_zero_percent`: Battery level at 0% unplugged logs critical power warning.
  - `test_r2_r3_03_process_count_spike_1000`: Process list spike of 1,000 items parsed without memory leak.
  - `test_r2_r3_04_digital_twin_down_fallback`: Digital Twin endpoint offline triggers agent retry fallback.
  - `test_r2_r3_05_negative_metrics_rejection`: Negative CPU/RAM values rejected by schema validator.

- **R4 Boundary Cases**:
  - `test_r2_r4_01_empty_chromadb_query`: Semantic search on empty collection returns empty list without error.
  - `test_r2_r4_02_nonexistent_user_memory`: Querying memory for non-existent user returns empty results.
  - `test_r2_r4_03_special_character_memory_key`: Memory key with special characters (`/\\:?*<>|`) handled cleanly.
  - `test_r2_r4_04_unmatched_semantic_query`: Irrelevant query returns low relevance scores below threshold.
  - `test_r2_r4_05_max_vector_item_overflow`: Inserting 10,000 vector items maintains top-3 lookup speed.

- **R5 Boundary Cases**:
  - `test_r2_r5_01_approval_timeout_expiration`: Unanswered approval prompt expires after 10 minutes (status `EXPIRED`).
  - `test_r2_r5_02_protected_system_process_kill`: Request to kill `csrss.exe` / `system` blocked by guardrails.
  - `test_r2_r5_03_nonexistent_file_deletion`: Delete missing file catches `FileNotFoundError` cleanly.
  - `test_r2_r5_04_concurrent_dangerous_approvals`: 5 simultaneous dangerous actions queued cleanly in separate slots.
  - `test_r2_r5_05_double_approval_click`: Clicking `Approve` twice on same callback button handles gracefully.

- **R6 Boundary Cases**:
  - `test_r2_r6_01_n8n_webhook_unreachable`: Unreachable n8n endpoint triggers self-healing retry logic.
  - `test_r2_r6_02_malformed_n8n_json_body`: Invalid JSON body to `/api/v1/planner/execute` returns HTTP 422.
  - `test_r2_r6_03_workflow_pause_timeout`: Paused workflow awaiting approval auto-cancels if rejected.
  - `test_r2_r6_04_unknown_workflow_name`: Request for unknown workflow name returns HTTP 404.
  - `test_r2_r6_05_large_n8n_payload`: 5MB n8n payload accepted and processed within limits.

- **R7 Boundary Cases**:
  - `test_r2_r7_01_sse_client_disconnect_reconnect`: SSE stream handles abrupt client disconnect without server leak.
  - `test_r2_r7_02_empty_approval_queue`: Dashboard queue returns empty list when no actions pending.
  - `test_r2_r7_03_invalid_approval_item_id`: Approving non-existent approval ID returns HTTP 404.
  - `test_r2_r7_04_trace_history_limit_10`: UI reasoning traces capped at last 10 entries.
  - `test_r2_r7_05_rapid_sse_polling`: High frequency metric streaming stays under CPU budget.

- **R8 Boundary Cases**:
  - `test_r2_r8_01_missing_env_file`: Missing `.env` file loads default secure fallback configuration.
  - `test_r2_r8_02_ollama_server_offline`: Ollama local LLM connection refused triggers descriptive error.
  - `test_r2_r8_03_db_connection_loss_recovery`: Database connection drop triggers connection pool auto-reconnect.
  - `test_r2_r8_04_corrupted_config_file`: Malformed configuration file raises explicit parse exception.
  - `test_r2_r8_05_read_only_filesystem_log`: Writing logs to read-only dir handles exception safely.

---

### 4.3 Tier 3: Cross-Feature Pairwise Interactions (10 Test Cases)
Validates inter-subsystem dynamics when two or more modules interact.

- `test_t3_01_memory_and_digital_twin`: Memory (R4) CPU threshold + Digital Twin (R3) real-time state check.
- `test_t3_02_telegram_and_approval_center`: Telegram (R2) dangerous file deletion prompt + Approval Center (R5) inline button click.
- `test_t3_03_health_mon_telegram_n8n_audit`: Health Monitor (R3) low disk alert -> Telegram (R2) notification -> n8n Backup workflow (R6) -> Audit Log (R5) entry.
- `test_t3_04_n8n_planner_and_memory`: n8n (R6) execute goal -> AI Planner (R1) fetches ChromaDB (R4) user coding preferences.
- `test_t3_05_self_healing_telegram_and_sse`: Tool retry failure (R5) streams status to Telegram (R2) and Dashboard SSE (R7).
- `test_t3_06_planner_digital_twin_and_approval`: Planner (R1) process kill -> Digital Twin (R3) PID verify -> Approval Center (R5) UI approval.
- `test_t3_07_dashboard_memory_and_telegram`: Dashboard UI (R7) sets theme -> stored in Memory (R4) -> recalled in Telegram bot (R2).
- `test_t3_08_n8n_workflow_and_approval`: n8n registry edit workflow (R6) pauses for Approval Center (R5) confirmation.
- `test_t3_09_digital_twin_and_dashboard_sse`: Digital Twin (R3) metric change broadcasts instantly to Dashboard SSE (R7).
- `test_t3_10_telegram_memory_and_planner`: Telegram prompt (R2) + Memory context (R4) -> Planner (R1) 5-subtask decomposition.

---

### 4.4 Tier 4: Real-World Scenarios (5 Comprehensive Workflows)
Simulates end-to-end multi-step user workflows.

1. **`test_t4_01_prepare_laptop_for_coding`**:
   - Telegram goal: "Prepare my laptop for coding".
   - JWT Auth (R2) -> Memory check for VSCode & project dir (R4) -> Digital Twin RAM/battery check (R3) -> Launch VSCode, start Docker containers, open browser, clean temp files (R1) -> Progress streamed to Telegram & Dashboard (R2, R7) -> Trace logged (R5).
2. **`test_t4_02_morning_routine_and_backup`**:
   - n8n scheduled trigger "Morning Routine" (R6) -> System Agent fetches weather & calendar stubs (R1) -> Automatic Backup workflow compresses project folder -> Memory updated (R4) -> Summary delivered to Telegram (R2).
3. **`test_t4_03_security_scan_and_process_cleanup`**:
   - Security Monitor workflow triggered (R6) -> Digital Twin scans process list (R3) -> Suspicious process identified -> Approval Center halts and sends Telegram inline keyboard prompt (R5) -> User approves -> Process terminated -> Audit Log entry created (R5).
4. **`test_t4_04_file_organization_and_memory_lookup`**:
   - User prompt: "Organize my downloads and recall my project folder" (R2) -> Planner recalls preferred project path from ChromaDB (R4) -> File Agent categorizes downloads into Documents/Images/Archives (R1) -> Structured summary sent to Telegram & Dashboard (R2, R7).
5. **`test_t4_05_emergency_action_rejection_and_health_recovery`**:
   - Health Monitor detects disk usage at 92% (R3) -> Proactive Telegram alert sent (R2) -> User triggers emergency cleanup -> System Agent proposes deleting root system folder (dangerous action) -> Approval Center flags action (R5) -> User clicks `REJECT` on Telegram button -> Dangerous delete cancelled -> Alternative safe temp folder cleanup executed -> Disk usage drops to 65% -> Health alert resolved -> Audit log records REJECTED action (R5).

---

## 5. Mock Harnesses & Assertion Utilities (`tests_e2e/utils.py`)

`tests_e2e/utils.py` contains standalone mock server harnesses and typed Pydantic models:

- **Pydantic Data Models**: `TaskRequest`, `SubtaskExecutionPlan`, `DigitalTwinState`, `MemoryItem`, `HealthAlert`, `AuditLog`.
- **`MockOllamaServer`**: In-memory mock server simulating Llama 3 LLM completions.
- **`MockTelegramHarness`**: In-memory Telegram Bot API simulator handling inbound messages and inline button clicks.
- **`MockN8nHarness`**: REST helper for testing n8n workflow API executions.
- **`DigitalTwinSimulator`**: In-memory system state provider for Digital Twin endpoints.
- **`E2EAssertionHelpers`**: Reusable assertion methods (`assert_task_plan_valid`, `assert_jwt_unauthorized`, `assert_audit_logged`, `assert_sse_event_emitted`).

---

## 6. CLI Test Suite Runner (`tests_e2e/runner.py`)

`runner.py` provides execution, filtering, formatted reporting, and exit code enforcement:

- **Command Line Arguments**:
  - `--tier {1,2,3,4}`: Run test cases within a specific tier.
  - `--feature {R1,R2,R3,R4,R5,R6,R7,R8}`: Run test cases targeting a specific requirement.
  - `-v`, `--verbose`: Show detailed line-by-line test execution logs.
  - `--json-out PATH`: Save execution results as a structured JSON report.
- **Terminal Summary**: Displays rich ASCII tables breaking down test counts, pass/fail status, duration, and feature coverage.
- **Exit Code**: Returns `0` if 100% of discovered tests pass; returns `1` if any test fails.

---

## 7. Execution Guide

Run all E2E tests using the project virtual environment:

```bash
# Full E2E Test Suite Execution
.venv\Scripts\python.exe tests_e2e/runner.py

# Filter by Tier
.venv\Scripts\python.exe tests_e2e/runner.py --tier 1
.venv\Scripts\python.exe tests_e2e/runner.py --tier 2
.venv\Scripts\python.exe tests_e2e/runner.py --tier 3
.venv\Scripts\python.exe tests_e2e/runner.py --tier 4

# Filter by Requirement
.venv\Scripts\python.exe tests_e2e/runner.py --feature R1

# Verbose Execution
.venv\Scripts\python.exe tests_e2e/runner.py -v
```
