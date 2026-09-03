from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

class CPUState(BaseModel):
    usage_percent: float = Field(..., description="Overall CPU usage percentage")
    count_logical: int
    count_physical: int
    frequency_mhz: float

class RAMState(BaseModel):
    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent: float

class DiskState(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float
    mount_point: str = "C:\\"

class BatteryState(BaseModel):
    percent: float
    power_plugged: bool
    time_left_seconds: Optional[int] = None

class ProcessInfo(BaseModel):
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    status: str

class WindowInfo(BaseModel):
    hwnd: int
    title: str
    process_name: str

class NetworkState(BaseModel):
    bytes_sent: int
    bytes_recv: int
    is_connected: bool

class ClipboardState(BaseModel):
    content_type: str = "text"
    content_preview: str = ""

class DigitalTwinState(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cpu: CPUState
    ram: RAMState
    disk: DiskState
    battery: Optional[BatteryState] = None
    processes: List[ProcessInfo] = []
    active_windows: List[WindowInfo] = []
    network: NetworkState
    clipboard: ClipboardState
