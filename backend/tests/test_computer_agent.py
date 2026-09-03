import pytest
import asyncio
from app.vision.screen_action_memory import screen_memory
from app.vision.computer_agent import computer_agent

def test_screen_action_memory_telemetry():
    screen_memory.record_action(
        task_id="test_t1",
        action="click",
        target="Search Box",
        expected="Search Active",
        actual="Search Active",
        success=True,
        duration_ms=120.0,
    )
    screen_memory.record_task_summary(
        task_id="test_t1",
        goal="Search Marvel on YouTube",
        total_steps=2,
        successful_steps=2,
        retries=0,
        final_success=True,
    )
    
    metrics = screen_memory.get_telemetry_metrics()
    assert metrics["total_tasks"] >= 1
    assert metrics["total_actions"] >= 1
    assert "task_success_rate" in metrics
    assert "vision_accuracy" in metrics

@pytest.mark.asyncio
async def test_computer_agent_observation():
    obs = await computer_agent.observe_screen("test_search")
    assert obs is not None
    assert "screenshot_path" in obs
    assert "ocr_text" in obs

def test_computer_agent_ui_action():
    res = computer_agent.execute_ui_action(action_type="click", coords=(100, 100))
    assert res is not None
    assert res["success"] is True
