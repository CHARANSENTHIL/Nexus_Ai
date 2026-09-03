# Project: Nexus AI

## Architecture
Nexus AI is a local-first autonomous desktop AI agent framework for Windows.
- **Backend Stack**: Python 3.11+, FastAPI, AsyncIO, Pydantic v2, SQLAlchemy, ChromaDB (vector store), PostgreSQL (relational DB), Redis (cache/queue), pywin32, psutil, pyautogui.
- **AI Core**: LangChain, CrewAI, Llama 3 via Ollama (`http://host.docker.internal:11434` in Docker or `http://localhost:11434` locally).
- **Interface & Messaging**: Telegram Bot (`aiogram` / `python-telegram-bot`), structured Pydantic message models, REST API, WebSockets / SSE.
- **Automation**: Self-hosted n8n container integration with custom REST API webhooks.
- **Frontend**: Next.js 14+ / React dashboard with real-time SSE metrics, approval management, execution traces, audit log.
- **DevOps**: Docker Compose, GitHub Actions CI, offline zero-paid-API footprint.

## Code Layout
```
nexus_ai/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── auth/            # JWT authentication & whitelist validation
│   │   ├── db/              # SQLAlchemy models, Postgres & Redis connections
│   │   ├── digital_twin/    # In-memory & DB system state model
│   │   ├── health_monitor/  # Background worker for trend & predictive disk alerts
│   │   ├── memory/          # ChromaDB vector store integration
│   │   ├── agents/          # CrewAI/LangChain Planner, System, App, File agents
│   │   │   ├── planner.py
│   │   │   ├── system_agent.py
│   │   │   ├── application_agent.py
│   │   │   ├── file_agent.py
│   │   │   └── tools/       # Windows OS native tools (psutil, pywin32, pyautogui)
│   │   ├── approval/        # Self-healing executor & Approval Center logic
│   │   ├── telegram_bot/    # Telegram bot listener & notification sender
│   │   └── api/             # FastAPI REST router & WebSocket/SSE endpoints
│   ├── tests/               # Unit tests (≥10 tests covering agent tools)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js pages & dashboard layout
│   │   ├── components/      # System metrics, charts, approval queue, traces
│   │   ├── lib/             # API client, WebSocket/SSE connection handlers
│   │   └── types/           # TypeScript interfaces matching backend models
│   ├── Dockerfile
│   └── package.json
├── n8n/
│   └── workflows/           # 5 production-ready JSON workflow definitions
├── tests_e2e/
│   ├── runner.py            # Comprehensive E2E test suite runner
│   ├── test_tier1.py        # Tier 1: Feature Coverage (≥5 per feature)
│   ├── test_tier2.py        # Tier 2: Boundary & Corner Cases
│   ├── test_tier3.py        # Tier 3: Cross-Feature Interactions (Pairwise)
│   └── test_tier4.py        # Tier 4: Real-World Scenarios
├── docker-compose.yml
├── README.md
└── .github/
    └── workflows/
        └── ci.yml
```

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| Track E2E | E2E Testing Track | Requirement-driven opaque-box test suite (Tiers 1-4). Publishes `TEST_READY.md`. | none | IN_PROGRESS (308e74c3) |
| M1 | Core Infra & Digital Twin | Backend skeleton, Postgres/Redis/ChromaDB schemas, Digital Twin, Health Monitor, JWT auth (R3, R8 part) | none | IN_PROGRESS (1363259d) |
| M2 | Multi-Agent AI Core & Memory | LangChain + CrewAI + Llama 3 agents (Planner, System, App, File), Pydantic messaging, ChromaDB semantic memory (R1, R4) | M1 | PLANNED |
| M3 | Telegram Bot, Self-Healing & Approvals | Telegram bot interface, progress streaming, self-healing retries, dangerous action Approval Center + audit log (R2, R5) | M1, M2 | PLANNED |
| M4 | n8n Workflows | 5 production n8n workflows (Morning Brief, Backup, Coding Workspace, Download Org, Security Mon) + REST API integration (R6) | M1, M2 | IN_PROGRESS (sub_orch_m4) |
| M5 | Frontend Dashboard | Next.js/React web dashboard with live SSE metrics, task reasoning traces, UI approval queue, logs (R7) | M1, M3 | PLANNED |
| M6 | Final Integration & E2E Validation | Docker Compose, GitHub Actions CI, README.md, E2E test suite 100% pass (Phase 1) + Tier 5 Hardening (Phase 2) (R8) | M1, M2, M3, M4, M5, Track E2E | PLANNED |

## Interface Contracts

### Backend API ↔ Digital Twin
- `GET /api/v1/digital-twin/state` -> returns `DigitalTwinState` (CPU, RAM, disk, battery, processes, active windows, network, clipboard).
- `POST /api/v1/digital-twin/update` -> internal update endpoint.

### Agents ↔ Digital Twin
- Agents must call `DigitalTwinClient.get_current_state()` or read via REST API; direct `psutil` or OS calls inside agent execution routines are forbidden.

### Planner ↔ Specialized Agents
- Structured typed messages via `Pydantic` models: `TaskRequest`, `TaskResponse`, `SubtaskExecutionPlan`, `AgentActionResult`.

### Telegram ↔ Approval Center
- Approval Request: Inline keyboard `[ Approve | Reject ]` sent on dangerous action (file delete, shutdown, process kill, registry).
- Audit log entry: `AuditLog(id, timestamp, user_id, action_type, details, outcome)`.

### n8n ↔ AI Planner REST API
- `POST /api/v1/planner/execute` with body `{ "goal": string, "context": dict }`.
- Returns `{ "task_id": string, "status": string, "subtasks": list, "result": dict }`.
