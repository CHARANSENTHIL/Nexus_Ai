import pytest
import asyncio
from app.agents.langgraph_orchestrator import execute_nexus_graph, build_nexus_graph

@pytest.mark.asyncio
async def test_langgraph_graph_compilation():
    graph = build_nexus_graph()
    assert graph is not None

@pytest.mark.asyncio
async def test_langgraph_execution_flow():
    res = await execute_nexus_graph("check system state", user_id="test_user")
    assert res is not None
    assert "final_output" in res
    assert "intent" in res
    assert "route" in res
