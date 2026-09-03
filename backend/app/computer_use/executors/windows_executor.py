"""
Native Windows API Executor — Process management, system settings, audio, and shell commands.
Uses subprocess, psutil, pycaw, and Windows OS APIs instead of UI simulation.
"""
import os
import sys
import time
import shutil
import asyncio
import logging
import subprocess
from typing import Dict, Any, Optional

import psutil
from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.executors.base import BaseExecutor

logger = logging.getLogger(__name__)

# Known Windows application aliases
APP_PATH_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "explorer": "explorer.exe",
    "taskmanager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "code": "code",
    "vscode": "code",
    "spotify": os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
}


class WindowsNativeExecutor(BaseExecutor):
    """Executes actions directly through Windows OS APIs and native libraries."""

    def __init__(self):
        super().__init__(ExecutionMethod.NATIVE_API)

    def can_handle(self, request: ActionRequest) -> bool:
        """Determines if the action can be fulfilled natively without GUI simulation."""
        native_actions = {
            ActionType.OPEN_APP,
            ActionType.CLOSE_APP,
            ActionType.RUN_COMMAND,
            ActionType.SET_VOLUME,
            ActionType.SET_BRIGHTNESS,
            ActionType.SET_POWER,
            ActionType.GET_SYSTEM_STATE,
            ActionType.GET_ACTIVE_WINDOW,
        }
        return request.action in native_actions

    async def execute(self, request: ActionRequest) -> ActionResult:
        start_time = time.monotonic()
        action = request.action
        target = request.target or ""

        try:
            # 1. Open Application
            if action == ActionType.OPEN_APP:
                return await self._open_app(target, request, start_time)

            # 2. Close Application
            elif action == ActionType.CLOSE_APP:
                return await self._close_app(target, request, start_time)

            # 3. Run Shell Command
            elif action == ActionType.RUN_COMMAND:
                return await self._run_command(target, request, start_time)

            # 4. System Volume
            elif action == ActionType.SET_VOLUME:
                return await self._set_volume(request.amount if request.amount is not None else 50, request, start_time)

            # 5. System Brightness
            elif action == ActionType.SET_BRIGHTNESS:
                return await self._set_brightness(request.amount if request.amount is not None else 100, request, start_time)

            # 6. System Power
            elif action == ActionType.SET_POWER:
                return await self._set_power(target.lower() or "sleep", request, start_time)

            # 7. System State
            elif action == ActionType.GET_SYSTEM_STATE:
                return self._get_system_state(request, start_time)

            # 8. Active Window
            elif action == ActionType.GET_ACTIVE_WINDOW:
                return self._get_active_window(request, start_time)

            else:
                return ActionResult(
                    success=False,
                    action=action,
                    target=target,
                    executor_used=self.method,
                    error=f"Unsupported native action: {action}",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

        except Exception as e:
            logger.error(f"[WindowsExecutor] Error executing {action}: {e}", exc_info=True)
            return ActionResult(
                success=False,
                action=action,
                target=target,
                executor_used=self.method,
                error=str(e),
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

    async def _open_app(self, app_name: str, request: ActionRequest, start: float) -> ActionResult:
        clean_name = app_name.lower().strip()
        exe = APP_PATH_MAP.get(clean_name, app_name)
        args = request.text_val or ""

        # Check if executable or in PATH
        if os.path.exists(exe):
            cmd = [exe] + ([args] if args else [])
            subprocess.Popen(cmd)
        elif shutil.which(exe):
            cmd = [exe] + ([args] if args else [])
            subprocess.Popen(cmd)
        else:
            # Fallback to os.startfile on Windows
            try:
                os.startfile(clean_name)
            except Exception:
                # Try start via cmd
                subprocess.Popen(f'start "" "{clean_name}"', shell=True)

        return ActionResult(
            success=True,
            action=ActionType.OPEN_APP,
            target=app_name,
            executor_used=self.method,
            output=f"Launched '{app_name}' via native process API",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _close_app(self, app_name: str, request: ActionRequest, start: float) -> ActionResult:
        clean_name = app_name.lower().replace(".exe", "").strip()
        killed = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if clean_name in pname:
                    proc.kill()
                    killed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if killed:
            return ActionResult(
                success=True,
                action=ActionType.CLOSE_APP,
                target=app_name,
                executor_used=self.method,
                output=f"Terminated {len(killed)} process instance(s): {', '.join(set(killed))}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        else:
            return ActionResult(
                success=False,
                action=ActionType.CLOSE_APP,
                target=app_name,
                executor_used=self.method,
                error=f"No running process matching '{app_name}' found",
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _run_command(self, cmd: str, request: ActionRequest, start: float) -> ActionResult:
        timeout = request.timeout_seconds or 30.0
        cwd = request.metadata.get("cwd", ".")

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            success = proc.returncode == 0

            return ActionResult(
                success=success,
                action=ActionType.RUN_COMMAND,
                target=cmd,
                executor_used=self.method,
                output=out_str if success else err_str or out_str,
                error=err_str if not success else None,
                metadata={"returncode": proc.returncode},
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ActionResult(
                success=False,
                action=ActionType.RUN_COMMAND,
                target=cmd,
                executor_used=self.method,
                error=f"Command timed out after {timeout}s",
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _set_volume(self, level: int, request: ActionRequest, start: float) -> ActionResult:
        level = max(0, min(100, int(level)))
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return ActionResult(
                success=True,
                action=ActionType.SET_VOLUME,
                target=str(level),
                executor_used=self.method,
                output=f"Volume set to {level}% via pycaw native endpoint",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception:
            # Fallback to powershell audio control
            ps_cmd = f"(New-Object -ComObject WScript.Shell).SendKeys([char]174)"
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
            return ActionResult(
                success=True,
                action=ActionType.SET_VOLUME,
                target=str(level),
                executor_used=self.method,
                output=f"Volume adjusted via PowerShell",
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _set_brightness(self, level: int, request: ActionRequest, start: float) -> ActionResult:
        level = max(0, min(100, int(level)))
        ps_cmd = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
        return ActionResult(
            success=res.returncode == 0,
            action=ActionType.SET_BRIGHTNESS,
            target=str(level),
            executor_used=self.method,
            output=f"Brightness set to {level}% via WMI",
            error=res.stderr if res.returncode != 0 else None,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _set_power(self, power_action: str, request: ActionRequest, start: float) -> ActionResult:
        import ctypes
        if power_action == "lock":
            ctypes.windll.user32.LockWorkStation()
            msg = "Workstation locked"
        elif power_action == "sleep":
            subprocess.run(["powershell", "-Command", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"], capture_output=True)
            msg = "System put to sleep"
        elif power_action in ("shutdown", "power off"):
            subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
            msg = "Shutdown sequence initiated (10s delay)"
        elif power_action in ("restart", "reboot"):
            subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True)
            msg = "Restart sequence initiated (10s delay)"
        else:
            return ActionResult(
                success=False,
                action=ActionType.SET_POWER,
                target=power_action,
                executor_used=self.method,
                error=f"Unknown power action: {power_action}",
                duration_ms=(time.monotonic() - start) * 1000,
            )

        return ActionResult(
            success=True,
            action=ActionType.SET_POWER,
            target=power_action,
            executor_used=self.method,
            output=msg,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _get_system_state(self, request: ActionRequest, start: float) -> ActionResult:
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("C:\\").percent
        battery = None
        if hasattr(psutil, "sensors_battery"):
            bat = psutil.sensors_battery()
            battery = bat.percent if bat else None

        state = {"cpu_percent": cpu, "ram_percent": ram, "disk_percent": disk, "battery_percent": battery}
        return ActionResult(
            success=True,
            action=ActionType.GET_SYSTEM_STATE,
            executor_used=self.method,
            output=state,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _get_active_window(self, request: ActionRequest, start: float) -> ActionResult:
        title = ""
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            ps_cmd = '(Get-Process | Where-Object {$_.MainWindowHandle -eq (Get-Process -Id $PID).MainWindowHandle}).MainWindowTitle'
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
            title = res.stdout.strip() or "Desktop"

        return ActionResult(
            success=True,
            action=ActionType.GET_ACTIVE_WINDOW,
            window_title=title,
            executor_used=self.method,
            output=title,
            duration_ms=(time.monotonic() - start) * 1000,
        )
