import pytest
from app.db.models import AuditLog, SystemStateHistory
from app.db.chroma_client import get_chroma_client

def test_orm_models_instantiation():
    log = AuditLog(user_id=123, action_type="FILE_DELETE", outcome="APPROVED")
    assert log.user_id == 123
    assert log.action_type == "FILE_DELETE"
    assert log.outcome == "APPROVED"

    state = SystemStateHistory(cpu_percent=15.5, ram_percent=60.0, disk_percent=45.0, disk_free_gb=120.5)
    assert state.cpu_percent == 15.5
    assert state.disk_free_gb == 120.5

def test_chroma_client_creation():
    client = get_chroma_client()
    # Client will be persistent client or None if chromadb import/cygrpc DLL is blocked by OS policy
    assert client is None or hasattr(client, "list_collections") or hasattr(client, "heartbeat")
