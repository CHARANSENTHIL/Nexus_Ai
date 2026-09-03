"""
Unit and integration tests for the Computer Use Abstraction Layer (ComputerInterface & ExecutionRouter).
"""
import pytest
from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.router import ExecutionRouter
from app.computer_use.interface import ComputerInterface, computer


class TestExecutionRouter:
    """Test routing decisions based on priority hierarchy."""

    def test_native_app_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.OPEN_APP, target="notepad")
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.NATIVE_API

    def test_native_volume_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.SET_VOLUME, amount=75)
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.NATIVE_API

    def test_native_command_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.RUN_COMMAND, target="echo test")
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.NATIVE_API

    def test_browser_navigation_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.NAVIGATE, target="https://youtube.com")
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.BROWSER_DOM

    def test_browser_dom_selector_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.CLICK_ELEMENT, target="#submit-btn", metadata={"in_browser": True})
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.BROWSER_DOM

    def test_vision_gui_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.CLICK, coordinates=(500, 300))
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.VISION_GUI

    def test_vision_hotkey_routing(self):
        router = ExecutionRouter()
        req = ActionRequest(action=ActionType.HOTKEY, keys=["ctrl", "c"])
        executor = router.select_executor(req)
        assert executor.method == ExecutionMethod.VISION_GUI


@pytest.mark.asyncio
class TestComputerInterface:
    """Test semantic capability methods on ComputerInterface."""

    async def test_run_command_native(self):
        res = await computer.run_command("echo Hello ComputerLayer")
        assert res.success is True
        assert res.executor_used == ExecutionMethod.NATIVE_API
        assert "Hello ComputerLayer" in str(res.output)
        assert res.duration_ms > 0

    async def test_get_system_state(self):
        res = await computer.get_system_state()
        assert res.success is True
        assert res.executor_used == ExecutionMethod.NATIVE_API
        assert isinstance(res.output, dict)
        assert "cpu_percent" in res.output
        assert "ram_percent" in res.output

    async def test_get_active_window(self):
        res = await computer.get_active_window()
        assert res.success is True
        assert res.executor_used == ExecutionMethod.NATIVE_API
        assert res.window_title is not None

    async def test_set_system_volume(self):
        res = await computer.set_system_volume(50)
        assert res.success is True
        assert res.executor_used == ExecutionMethod.NATIVE_API

    async def test_screenshot_action(self):
        res = await computer.screenshot()
        assert res.action == ActionType.SCREENSHOT
        assert res.executor_used == ExecutionMethod.VISION_GUI

    async def test_hotkey_action(self):
        res = await computer.hotkey("ctrl", "alt", "t")
        assert res.success is True
        assert res.action == ActionType.HOTKEY
        assert res.executor_used == ExecutionMethod.VISION_GUI

    async def test_structured_action_result_schema(self):
        res = await computer.run_command("echo schema_test")
        schema_dict = res.model_dump()
        assert "success" in schema_dict
        assert "action" in schema_dict
        assert "executor_used" in schema_dict
        assert "duration_ms" in schema_dict
        assert "timestamp" in schema_dict
