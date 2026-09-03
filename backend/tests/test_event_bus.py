"""
Unit and Integration Tests for Event-Driven Architecture (Redis Streams Event Bus & Workers).
"""
import asyncio
import pytest
from app.events.event_models import (
    EventType,
    NexusEvent,
    TaskCreatedPayload,
    TaskClassifiedPayload,
    ActionRequestedPayload,
    ActionCompletedPayload,
)
from app.events.event_bus import RedisEventBus
from app.events.task_tracker import TaskTracker
from app.events.workers.router_worker import RouterWorker
from app.events.workers.planner_worker import PlannerWorker
from app.events.workers.security_worker import SecurityWorker
from app.events.workers.windows_worker import WindowsWorker
from app.events.workers.recovery_worker import RecoveryWorker


class TestEventModels:
    def test_nexus_event_serialization(self):
        event = NexusEvent(
            event_type=EventType.TASK_CREATED,
            task_id="t123",
            user_id="user01",
            payload={"command": "open notepad"},
            source_agent="telegram_bot",
        )
        d = event.to_dict()
        assert d["event_type"] == "TASK_CREATED"
        assert d["task_id"] == "t123"
        assert d["payload"]["command"] == "open notepad"

        restored = NexusEvent.from_dict(d)
        assert restored.event_type == EventType.TASK_CREATED
        assert restored.task_id == "t123"
        assert restored.payload["command"] == "open notepad"


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_timeline(self):
        bus = RedisEventBus()
        event = NexusEvent(
            event_type=EventType.TASK_CREATED,
            task_id="task_bus_1",
            user_id="123",
            payload={"command": "check cpu"},
        )
        msg_id = await bus.publish(event)
        assert msg_id is not None

        timeline = await bus.get_task_timeline("task_bus_1")
        assert len(timeline) == 1
        assert timeline[0].event_type == EventType.TASK_CREATED


class TestTaskTracker:
    @pytest.mark.asyncio
    async def test_task_state_lifecycle(self):
        bus = RedisEventBus()
        tracker = TaskTracker(bus=bus)

        await tracker.register_task("t_track_1", "u1", "open calculator")
        state = await tracker.get_task_state("t_track_1")
        assert state["status"] == "CREATED"

        # Update with CLASSIFIED
        evt_classified = NexusEvent(
            event_type=EventType.TASK_CLASSIFIED,
            task_id="t_track_1",
            payload={"intent": "open_app", "domain": "pc_tools", "subtasks": []},
        )
        await tracker.update_task_from_event(evt_classified)
        state = await tracker.get_task_state("t_track_1")
        assert state["status"] == "CLASSIFIED"

        # Update with TASK_COMPLETED
        evt_done = NexusEvent(
            event_type=EventType.TASK_COMPLETED,
            task_id="t_track_1",
            payload={"final_output": "Opened Calculator"},
        )
        await tracker.update_task_from_event(evt_done)
        res = await tracker.wait_for_completion("t_track_1", timeout=2.0)
        assert res["status"] == "COMPLETED"
        assert res["success"] is True
        assert "Opened Calculator" in res["final_output"]


class TestAgentWorkers:
    @pytest.mark.asyncio
    async def test_router_worker_keyword_command(self):
        bus = RedisEventBus()
        router = RouterWorker(bus=bus)

        created_evt = NexusEvent(
            event_type=EventType.TASK_CREATED,
            task_id="t_router_1",
            user_id="u1",
            payload={"command": "check cpu"},
        )
        out_events = await router.handle_event(created_evt)
        assert len(out_events) == 1
        assert out_events[0].event_type == EventType.TASK_CLASSIFIED
        assert out_events[0].payload["domain"] == "pc_tools"
        assert len(out_events[0].payload["subtasks"]) > 0

    @pytest.mark.asyncio
    async def test_planner_worker_emits_action_requested(self):
        bus = RedisEventBus()
        planner = PlannerWorker(bus=bus)

        classified_evt = NexusEvent(
            event_type=EventType.TASK_CLASSIFIED,
            task_id="t_plan_1",
            user_id="u1",
            payload={
                "intent": "check_cpu",
                "domain": "pc_tools",
                "subtasks": [{"tool": "get_system_state", "tool_input": {}}],
            },
        )
        out_events = await planner.handle_event(classified_evt)
        assert len(out_events) == 1
        assert out_events[0].event_type == EventType.ACTION_REQUESTED
        assert out_events[0].payload["action"] == "get_system_state"

    @pytest.mark.asyncio
    async def test_security_worker_blocks_critical_and_approves_safe(self):
        bus = RedisEventBus()
        sec = SecurityWorker(bus=bus)

        # Safe action
        safe_evt = NexusEvent(
            event_type=EventType.ACTION_REQUESTED,
            task_id="t_sec_1",
            user_id="u1",
            payload={"action": "get_system_state", "tool_input": {}, "domain": "pc_tools"},
        )
        safe_out = await sec.handle_event(safe_evt)
        assert len(safe_out) == 1
        assert safe_out[0].event_type == EventType.ACTION_APPROVED

        # Critical dangerous action
        dangerous_evt = NexusEvent(
            event_type=EventType.ACTION_REQUESTED,
            task_id="t_sec_2",
            user_id="u1",
            payload={"action": "run_shell_command", "tool_input": {"command": "Set-MpPreference -DisableRealtimeMonitoring $true"}},
        )
        dangerous_out = await sec.handle_event(dangerous_evt)
        assert len(dangerous_out) == 1
        assert dangerous_out[0].event_type == EventType.ACTION_BLOCKED

    @pytest.mark.asyncio
    async def test_windows_worker_executes_tool(self):
        bus = RedisEventBus()
        win = WindowsWorker(bus=bus)

        approved_evt = NexusEvent(
            event_type=EventType.ACTION_APPROVED,
            task_id="t_win_1",
            user_id="u1",
            payload={
                "action": "get_disk_usage",
                "tool_input": {"path": "C:\\"},
                "domain": "pc_tools",
                "subtask_index": 0,
            },
        )
        out_events = await win.handle_event(approved_evt)
        assert len(out_events) == 2
        assert out_events[0].event_type == EventType.ACTION_COMPLETED
        assert out_events[1].event_type == EventType.TASK_COMPLETED
        assert out_events[0].payload["success"] is True

    @pytest.mark.asyncio
    async def test_recovery_worker_handles_failure(self):
        bus = RedisEventBus()
        rec = RecoveryWorker(bus=bus)

        failed_evt = NexusEvent(
            event_type=EventType.ACTION_FAILED,
            task_id="t_rec_1",
            user_id="u1",
            payload={"action": "run_shell_command", "error": "Unknown arbitrary unrecoverable error"},
        )
        out_events = await rec.handle_event(failed_evt)
        assert len(out_events) >= 2
        assert out_events[0].event_type == EventType.RECOVERY_STARTED
        assert out_events[-1].event_type == EventType.TASK_FAILED


class TestEventDrivenEndToEnd:
    @pytest.mark.asyncio
    async def test_complete_event_pipeline_flow(self):
        """
        Simulates end-to-end event bus flow:
        TASK_CREATED -> Router -> TASK_CLASSIFIED -> Planner -> ACTION_REQUESTED ->
        Security -> ACTION_APPROVED -> Windows -> ACTION_COMPLETED & TASK_COMPLETED.
        """
        from app.events.task_tracker import task_tracker
        bus = RedisEventBus()

        router = RouterWorker(bus=bus)
        planner = PlannerWorker(bus=bus)
        security = SecurityWorker(bus=bus)
        windows = WindowsWorker(bus=bus)

        task_id = "t_e2e_full"
        await task_tracker.register_task(task_id, "user_test", "check cpu")

        # Step 1: TASK_CREATED
        step1 = NexusEvent(
            event_type=EventType.TASK_CREATED,
            task_id=task_id,
            user_id="user_test",
            payload={"command": "check cpu"},
        )
        classified_events = await router.handle_event(step1)
        assert len(classified_events) == 1
        assert classified_events[0].event_type == EventType.TASK_CLASSIFIED

        # Step 2: Planner generates ACTION_REQUESTED
        req_events = await planner.handle_event(classified_events[0])
        assert len(req_events) == 1
        assert req_events[0].event_type == EventType.ACTION_REQUESTED

        # Step 3: Security checks and emits ACTION_APPROVED
        approved_events = await security.handle_event(req_events[0])
        assert len(approved_events) == 1
        assert approved_events[0].event_type == EventType.ACTION_APPROVED

        # Step 4: Windows Worker executes and emits ACTION_COMPLETED & TASK_COMPLETED
        final_events = await windows.handle_event(approved_events[0])
        assert len(final_events) == 2
        assert final_events[0].event_type == EventType.ACTION_COMPLETED
        assert final_events[1].event_type == EventType.TASK_COMPLETED

        # Check final task state
        res = await task_tracker.wait_for_completion(task_id, timeout=2.0)
        assert res["status"] == "COMPLETED"
        assert res["success"] is True

