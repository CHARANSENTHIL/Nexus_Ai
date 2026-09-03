import sys
from datetime import datetime, timezone
from typing import Optional, List
import psutil
from app.digital_twin.models import (
    CPUState, RAMState, DiskState, BatteryState, ProcessInfo,
    WindowInfo, NetworkState, ClipboardState, DigitalTwinState
)

class SystemStateCollector:
    @staticmethod
    def collect_cpu() -> CPUState:
        freq = psutil.cpu_freq()
        return CPUState(
            usage_percent=psutil.cpu_percent(interval=None),
            count_logical=psutil.cpu_count(logical=True) or 1,
            count_physical=psutil.cpu_count(logical=False) or 1,
            frequency_mhz=freq.current if freq else 0.0
        )

    @staticmethod
    def collect_ram() -> RAMState:
        mem = psutil.virtual_memory()
        return RAMState(
            total_bytes=mem.total,
            available_bytes=mem.available,
            used_bytes=mem.used,
            percent=mem.percent
        )

    @staticmethod
    def collect_disk(path: str = "C:\\") -> DiskState:
        try:
            usage = psutil.disk_usage(path)
        except Exception:
            usage = psutil.disk_usage("/")
        return DiskState(
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            percent=usage.percent,
            mount_point=path
        )

    @staticmethod
    def collect_battery() -> Optional[BatteryState]:
        bat = psutil.sensors_battery()
        if not bat:
            return None
        return BatteryState(
            percent=bat.percent,
            power_plugged=bat.power_plugged,
            time_left_seconds=bat.secsleft if bat.secsleft != psutil.POWER_TIME_UNLIMITED else None
        )

    @staticmethod
    def collect_processes(limit: int = 15) -> List[ProcessInfo]:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                info = p.info
                procs.append(ProcessInfo(
                    pid=info['pid'],
                    name=info['name'] or "unknown",
                    cpu_percent=info['cpu_percent'] or 0.0,
                    memory_percent=info['memory_percent'] or 0.0,
                    status=info['status'] or "running"
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x.cpu_percent, reverse=True)
        return procs[:limit]

    @staticmethod
    def collect_active_windows() -> List[WindowInfo]:
        windows = []
        if sys.platform == "win32":
            try:
                import win32gui, win32process
                def enum_windows_callback(hwnd, extra):
                    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        p_name = "unknown"
                        try:
                            p_name = psutil.Process(pid).name()
                        except Exception:
                            pass
                        windows.append(WindowInfo(hwnd=hwnd, title=title, process_name=p_name))
                win32gui.EnumWindows(enum_windows_callback, None)
            except Exception:
                pass
        return windows[:10]

    @staticmethod
    def collect_network() -> NetworkState:
        io = psutil.net_io_counters()
        return NetworkState(
            bytes_sent=io.bytes_sent,
            bytes_recv=io.bytes_recv,
            is_connected=True
        )

    @staticmethod
    def collect_clipboard() -> ClipboardState:
        preview = ""
        if sys.platform == "win32":
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    preview = str(data)[:50]
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        return ClipboardState(content_type="text", content_preview=preview)

    @classmethod
    def collect_full_state(cls) -> DigitalTwinState:
        return DigitalTwinState(
            timestamp=datetime.now(timezone.utc),
            cpu=cls.collect_cpu(),
            ram=cls.collect_ram(),
            disk=cls.collect_disk(),
            battery=cls.collect_battery(),
            processes=cls.collect_processes(),
            active_windows=cls.collect_active_windows(),
            network=cls.collect_network(),
            clipboard=cls.collect_clipboard()
        )


class DigitalTwinService:
    def __init__(self):
        self._cached_state: Optional[DigitalTwinState] = None

    def update_state(self) -> DigitalTwinState:
        state = SystemStateCollector.collect_full_state()
        self._cached_state = state
        return state

    def get_state(self) -> DigitalTwinState:
        if self._cached_state is None:
            return self.update_state()
        return self._cached_state

digital_twin_service = DigitalTwinService()

class DigitalTwinClient:
    """Client interface for AI Agents to access Digital Twin state without making OS system calls."""
    @staticmethod
    def get_current_state() -> DigitalTwinState:
        return digital_twin_service.get_state()
