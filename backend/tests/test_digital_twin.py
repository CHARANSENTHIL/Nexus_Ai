import pytest
from app.digital_twin.service import SystemStateCollector, DigitalTwinService, DigitalTwinClient
from app.digital_twin.models import DigitalTwinState

def test_collector_cpu_ram_disk():
    cpu = SystemStateCollector.collect_cpu()
    assert cpu.usage_percent >= 0.0
    assert cpu.count_logical >= 1

    ram = SystemStateCollector.collect_ram()
    assert ram.total_bytes > 0
    assert 0.0 <= ram.percent <= 100.0

    disk = SystemStateCollector.collect_disk()
    assert disk.total_bytes > 0

def test_digital_twin_service():
    service = DigitalTwinService()
    state1 = service.get_state()
    assert isinstance(state1, DigitalTwinState)
    
    state2 = service.get_state()
    assert state1.timestamp == state2.timestamp

    state3 = service.update_state()
    assert state3 is not None

def test_digital_twin_client():
    state = DigitalTwinClient.get_current_state()
    assert isinstance(state, DigitalTwinState)
    assert state.cpu is not None
    assert state.ram is not None
    assert state.disk is not None
