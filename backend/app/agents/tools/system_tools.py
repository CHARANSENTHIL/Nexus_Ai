"""System Agent tools — CPU, RAM, battery, processes, power via Digital Twin."""
import subprocess
from typing import Any, Dict
import psutil
from langchain.tools import tool


@tool
def get_system_state() -> Dict[str, Any]:
    """Get the current live state of the system (CPU, RAM, disk, battery, processes, network)
    from the Digital Twin service. Always call this before any system-level action."""
    try:
        import httpx
        resp = httpx.get("http://localhost:8000/api/v1/digital-twin/state", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    # Fallback: read directly if Digital Twin unreachable
    battery = psutil.sensors_battery()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "disk_percent": psutil.disk_usage("/").percent,
        "battery_percent": battery.percent if battery else None,
        "battery_plugged": battery.power_plugged if battery else None,
        "network_connected": len(psutil.net_if_stats()) > 0,
        "process_count": len(psutil.pids()),
    }


@tool
def get_running_processes(name_filter: str = "") -> list:
    """List currently running processes, optionally filtered by name substring."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            if name_filter.lower() in info["name"].lower():
                processes.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes[:50]  # Return top 50 matches


@tool
def kill_process(pid: int) -> Dict[str, Any]:
    """Terminate a process by PID. Requires approval for critical system processes."""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        proc.terminate()
        return {"success": True, "message": f"Process {name} (PID {pid}) terminated."}
    except psutil.NoSuchProcess:
        return {"success": False, "error": f"Process PID {pid} not found."}
    except psutil.AccessDenied:
        return {"success": False, "error": f"Access denied to terminate PID {pid}."}


@tool
def get_disk_usage(path: str = "C:\\") -> Dict[str, Any]:
    """Get disk usage statistics for a given path (default C:\\)."""
    try:
        usage = psutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "percent_used": usage.percent,
        }
    except Exception as e:
        return {"error": str(e)}


@tool
def set_system_power(action: str) -> Dict[str, Any]:
    """Control system power state. action must be one of: shutdown, restart, sleep, lock.
    DANGEROUS — requires approval before execution."""
    action = action.lower().strip()
    commands = {
        "shutdown": ["shutdown", "/s", "/t", "30"],
        "restart": ["shutdown", "/r", "/t", "30"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    }
    if action not in commands:
        return {"success": False, "error": f"Unknown power action: {action}. Use: shutdown, restart, sleep, lock"}
    try:
        subprocess.Popen(commands[action])
        return {"success": True, "message": f"System {action} initiated."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def check_network_connectivity(host: str = "8.8.8.8") -> Dict[str, Any]:
    """Check network connectivity by pinging a host (default Google DNS)."""
    try:
        result = subprocess.run(
            ["ping", "-n", "2", host],
            capture_output=True, text=True, timeout=10
        )
        connected = result.returncode == 0
        return {
            "connected": connected,
            "host": host,
            "output": result.stdout[:300],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@tool
def set_system_brightness(level: int) -> Dict[str, Any]:
    """Set screen brightness level (0 to 100)."""
    level = max(0, min(100, level))
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(level)
        return {"success": True, "message": f"Brightness set to {level}%"}
    except Exception:
        pass

    # Fallback to PowerShell WMI
    try:
        ps_cmd = f"(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return {"success": True, "message": f"Brightness adjusted to {level}%"}
        return {"success": False, "error": res.stderr or "WMI brightness control unavailable"}
    except Exception as e:
        return {"success": False, "error": str(e)}
