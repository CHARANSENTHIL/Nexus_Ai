import os
import subprocess
import time
import sys
import logging
import shutil
import glob
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional
import psutil
from langchain.tools import tool

logger = logging.getLogger(__name__)

# ── Quick aliases for common names users type ─────────────────────────────────
APP_ALIASES: Dict[str, str] = {
    # Browsers
    "chrome": "google chrome", "google": "google chrome",
    "edge": "microsoft edge", "msedge": "microsoft edge",
    "firefox": "mozilla firefox",
    # Dev
    "vscode": "visual studio code", "vs code": "visual studio code", "code": "visual studio code",
    "terminal": "windows terminal", "wt": "windows terminal",
    "powershell": "powershell", "cmd": "command prompt",
    # System
    "explorer": "file explorer", "files": "file explorer",
    "notepad": "notepad", "paint": "paint", "mspaint": "paint",
    "calculator": "calculator", "calc": "calculator",
    "taskmgr": "task manager", "task manager": "task manager",
    "settings": "settings", "control panel": "control panel",
    # Store / Communication
    "store": "microsoft store", "microsoft store": "microsoft store",
    "teams": "microsoft teams", "outlook": "outlook",
    "telegram": "telegram", "whatsapp": "whatsapp",
    "discord": "discord", "slack": "slack", "zoom": "zoom",
    # Media
    "spotify": "spotify", "vlc": "vlc media player",
    # Other
    "obs": "obs studio", "steam": "steam",
    "word": "word", "excel": "excel", "powerpoint": "powerpoint",
}

# ── UWP / Microsoft Store App Family Names ────────────────────────────────────
UWP_APP_IDS: Dict[str, str] = {
    "microsoft store": "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    "calculator": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "settings": "ms-settings:",
    "control panel": "control",
    "photos": "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
    "camera": "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    "maps": "Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
    "mail": "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
    "calendar": "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
    "xbox": "Microsoft.XboxApp_8wekyb3d8bbwe!Microsoft.XboxApp",
    "clock": "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "weather": "Microsoft.BingWeather_8wekyb3d8bbwe!App",
    "sticky notes": "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
    "screen snip": "ms-screenclip:",
    "snipping tool": "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "wordpad": "wordpad.exe",
    "disk cleanup": "cleanmgr.exe",
    "device manager": "devmgmt.msc",
    "remote desktop": "mstsc.exe",
}

# ── Start Menu shortcut cache (built once, reused) ────────────────────────────
_start_menu_cache: Optional[Dict[str, str]] = None


def _build_start_menu_cache() -> Dict[str, str]:
    """Scan Start Menu folders for .lnk shortcuts. Returns {lowercase_name: lnk_path}."""
    global _start_menu_cache
    if _start_menu_cache is not None:
        return _start_menu_cache

    cache: Dict[str, str] = {}
    start_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]
    for sd in start_dirs:
        if not os.path.isdir(sd):
            continue
        for root, dirs, files in os.walk(sd):
            for f in files:
                if f.lower().endswith(".lnk"):
                    name = f[:-4].lower()  # strip .lnk
                    cache[name] = os.path.join(root, f)
    _start_menu_cache = cache
    return cache


def _search_registry_app_paths(app_name: str) -> Optional[str]:
    """Search Windows Registry App Paths for an executable."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + app_name + ".exe"
        )
        val, _ = winreg.QueryValueEx(key, None)
        winreg.CloseKey(key)
        if val and os.path.exists(val):
            return val
    except (OSError, FileNotFoundError):
        pass
    return None


def _search_program_files(app_name: str) -> Optional[str]:
    """Search common installation directories for an executable."""
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        os.path.expandvars(r"%LOCALAPPDATA%"),
    ]
    for base in search_dirs:
        if not os.path.isdir(base):
            continue
        # Search 2 levels deep for matching exe
        for root, dirs, files in os.walk(base):
            depth = root.replace(base, "").count(os.sep)
            if depth > 2:
                dirs.clear()
                continue
            for f in files:
                if f.lower().endswith(".exe") and app_name.replace(" ", "") in f.lower().replace(" ", ""):
                    return os.path.join(root, f)
    return None


def _resolve_app_path(app_name: str) -> tuple[str, str]:
    """
    Universal app resolver. Returns (launch_command, method_used).
    Searches in order:
      1. UWP / Store app IDs
      2. Start Menu shortcuts (.lnk files)
      3. Registry App Paths
      4. shutil.which (PATH lookup)
      5. Program Files deep search
      6. PowerShell Get-AppxPackage (dynamic UWP discovery)
    """
    name_lower = app_name.lower().strip()

    # Expand aliases
    canonical = APP_ALIASES.get(name_lower, name_lower)

    # 1. Known UWP apps
    if canonical in UWP_APP_IDS:
        app_id = UWP_APP_IDS[canonical]
        if app_id.startswith("ms-"):
            return app_id, "uri"
        if app_id.endswith(".exe"):
            return app_id, "exe"
        return app_id, "uwp"

    # 2. Start Menu shortcuts (covers almost everything installed)
    cache = _build_start_menu_cache()
    # Try exact match first
    if canonical in cache:
        return cache[canonical], "lnk"
    # Try partial match
    for cached_name, lnk_path in cache.items():
        if canonical in cached_name or cached_name in canonical:
            return lnk_path, "lnk"

    # Also try the original name (before alias expansion)
    if name_lower != canonical:
        if name_lower in cache:
            return cache[name_lower], "lnk"
        for cached_name, lnk_path in cache.items():
            if name_lower in cached_name or cached_name in name_lower:
                return lnk_path, "lnk"

    # 3. Registry App Paths
    for try_name in [canonical, name_lower, name_lower.replace(" ", "")]:
        reg_path = _search_registry_app_paths(try_name)
        if reg_path:
            return reg_path, "registry"

    # 4. PATH lookup
    for try_name in [canonical, name_lower, name_lower.replace(" ", ""), name_lower + ".exe"]:
        which_result = shutil.which(try_name)
        if which_result:
            return which_result, "path"

    # 5. Program Files search
    pf_result = _search_program_files(canonical)
    if pf_result:
        return pf_result, "program_files"
    if name_lower != canonical:
        pf_result = _search_program_files(name_lower)
        if pf_result:
            return pf_result, "program_files"

    # 6. Dynamic UWP search via PowerShell
    try:
        ps_cmd = f'Get-AppxPackage -Name "*{name_lower.replace(" ", "*")}*" | Select-Object -First 1 -ExpandProperty PackageFamilyName'
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5
        )
        family = result.stdout.strip()
        if family:
            return family + "!App", "uwp_dynamic"
    except Exception:
        pass

    # Nothing found — return raw name as last resort
    return name_lower, "fallback"


WEB_APP_URLS: Dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "reddit": "https://www.reddit.com",
    "amazon": "https://www.amazon.com",
}


@tool
def open_application(app_name: str, args: str = "") -> Dict[str, Any]:
    """Open ANY Windows application by name (e.g. 'chrome', 'spotify', 'telegram',
    'microsoft store', 'discord', 'obs', 'whatsapp', 'vs code', 'calculator', etc.).
    Searches Start Menu, UWP Store apps, Registry, and installed programs automatically."""
    target = app_name.lower().strip()
    if target in WEB_APP_URLS:
        web_url = WEB_APP_URLS[target]
        logger.info(f"open_application: '{app_name}' is a web app → opening {web_url}")
        fn_open_url = getattr(open_url_in_browser, "func", open_url_in_browser)
        return fn_open_url(web_url, browser="chrome")

    resolved, method = _resolve_app_path(target)
    logger.info(f"open_application: '{app_name}' → '{resolved}' (via {method})")


    try:
        if method == "uri":
            # ms-settings:, ms-screenclip:, etc.
            proc = subprocess.Popen(f'start "" "{resolved}"', shell=True)
            pid = getattr(proc, "pid", 0)
            return {"success": True, "message": f"Opened '{app_name}'", "pid": pid}

        elif method == "uwp" or method == "uwp_dynamic":
            # Launch UWP app via shell:AppsFolder
            proc = subprocess.Popen(
                f'start "" "shell:AppsFolder\\{resolved}"', shell=True
            )
            pid = getattr(proc, "pid", 0)
            return {"success": True, "message": f"Opened '{app_name}'", "pid": pid}

        elif method == "lnk":
            # Launch .lnk shortcut
            cmd = f'start "" "{resolved}" {args}'.strip() if args else f'start "" "{resolved}"'
            proc = subprocess.Popen(cmd, shell=True)
            pid = getattr(proc, "pid", 0)
            return {"success": True, "message": f"Launched '{app_name}'", "pid": pid}

        elif method in ("registry", "path", "program_files"):
            # Direct .exe path
            cmd = f'"{resolved}" {args}'.strip() if args else f'start "" "{resolved}"'
            proc = subprocess.Popen(cmd, shell=True)
            pid = getattr(proc, "pid", 0)
            return {"success": True, "message": f"Launched '{app_name}'", "pid": pid}

        elif method == "exe":
            # Simple system exe (taskmgr.exe, explorer.exe, etc.)
            proc = subprocess.Popen(f'start "" "{resolved}"', shell=True)
            pid = getattr(proc, "pid", 0)
            return {"success": True, "message": f"Opened '{app_name}'", "pid": pid}

        else:
            # Fallback: check if executable or command exists before calling start
            if shutil.which(resolved) or os.path.exists(resolved):
                proc = subprocess.Popen(f'start "" "{resolved}"', shell=True)
                pid = getattr(proc, "pid", 0)
                return {"success": True, "message": f"Attempted to launch '{app_name}'", "pid": pid}
            else:
                return {"success": False, "error": f"Application '{app_name}' not found on this system.", "pid": 0}


    except FileNotFoundError:
        return {"success": False, "error": f"Application '{app_name}' not found on this system.", "pid": 0}
    except Exception as e:
        return {"success": False, "error": str(e), "pid": 0}


@tool
def close_application(app_name: str) -> Dict[str, Any]:
    """Close a running application by process name (e.g. 'chrome.exe', 'code.exe').
    DANGEROUS for critical system processes — requires approval."""
    closed = []
    errors = []
    target = app_name.lower().replace(".exe", "")
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if target in proc.info["name"].lower():
                proc.terminate()
                closed.append({"name": proc.info["name"], "pid": proc.info["pid"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            errors.append(str(e))
    if closed:
        return {"success": True, "closed": closed, "errors": errors}
    return {"success": False, "error": f"No running process found matching '{app_name}'"}


@tool
def list_running_applications() -> List[Dict[str, Any]]:
    """List all currently running applications (user-visible processes with windows)."""
    apps = set()
    result = []
    for proc in psutil.process_iter(["pid", "name", "status"]):
        try:
            name = proc.info["name"]
            if name and name not in apps and proc.info["status"] == "running":
                apps.add(name)
                result.append({"pid": proc.info["pid"], "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(result, key=lambda x: x["name"])[:60]


@tool
def open_url_in_browser(url: str, browser: str = "edge") -> Dict[str, Any]:
    """Open a URL or search query in Microsoft Edge or Chrome browser."""
    url = url.strip()
    url_lower = url.lower()

    # 1. Smart YouTube handling: route directly to YouTube instead of Google search
    if "youtube" in url_lower or ("play " in url_lower and ("video" in url_lower or "channel" in url_lower or "song" in url_lower)):
        import urllib.parse, re
        clean_query = re.sub(r"(?i)^(open\s+youtube\s+and\s+(play|search)?|open\s+youtube|play|watch|search\s+for)\s*", "", url).strip()
        if not clean_query:
            url = "https://www.youtube.com"
        elif not clean_query.startswith(("http://", "https://")):
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
    elif not url.startswith(("http://", "https://")):
        if "." in url and " " not in url:
            url = "https://" + url
        else:
            import urllib.parse
            url = f"https://www.google.com/search?q={urllib.parse.quote(url)}"

    try:
        if sys.platform == "win32":
            target = "msedge" if browser.lower() in ("edge", "msedge", "microsoft edge") else ("chrome" if browser.lower() == "chrome" else "")
            if target:
                subprocess.Popen(f'start {target} "{url}"', shell=True)
            else:
                subprocess.Popen(f'start "" "{url}"', shell=True)
            return {"success": True, "message": f"Opened {url} in {target or 'browser'}"}
        else:
            import webbrowser
            webbrowser.open(url)
            return {"success": True, "message": f"Opened {url} in browser"}
    except Exception as e:
        return {"success": False, "error": str(e)}



@tool
def run_shell_command(command: str, timeout: int = 15) -> Dict[str, Any]:
    """Run a shell command and return the output. Use for terminal operations.
    DANGEROUS for destructive commands — requires approval."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,  # Prevents hanging on input() or interactive prompts
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:1000],
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@tool
def set_system_volume(level: int) -> Dict[str, Any]:
    """Set Windows system volume to a level between 0 and 100."""
    if not 0 <= level <= 100:
        return {"success": False, "error": "Volume level must be between 0 and 100"}

    # Method 1: Use pycaw (Python Core Audio Windows)
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        vol = speakers.EndpointVolume
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return {"success": True, "message": f"Volume set to {level}%"}
    except Exception:
        pass

    # Method 2: PowerShell fallback using Windows Core Audio COM
    try:
        ps_script = f"""
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    int _0(); int _1(); int _2(); int _3(); int _4(); int _5(); int _6(); int _7(); int _8(); int _9(); int _10(); int _11();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{
    int Activate(ref System.Guid iid, int dwClsCtx, System.IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
}}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {{}}
public class Audio {{
    public static void SetVolume(float level) {{
        var enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
        IMMDevice dev;
        enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
        var iid = typeof(IAudioEndpointVolume).GUID;
        object obj;
        dev.Activate(ref iid, 1, System.IntPtr.Zero, out obj);
        var vol = (IAudioEndpointVolume)obj;
        vol.SetMasterVolumeLevelScalar(level, System.Guid.Empty);
    }}
}}
'@
[Audio]::SetVolume({level / 100.0})
"""
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"success": True, "message": f"Volume set to {level}%"}
        return {"success": False, "error": result.stderr[:300] if result.stderr else "PowerShell volume control failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def send_intelligent_email(
    prompt: str,
    recipient: str = "",
    subject: str = "",
    body: str = "",
) -> Dict[str, Any]:
    """
    Intelligently drafts an email, discovers relevant local attachments, and dispatches via n8n Gmail workflow.
    Requires security approval for high-risk operations.
    """
    import asyncio
    import concurrent.futures
    from app.agents.email_workflow import email_agent

    async def _execute():
        draft = await email_agent.plan_and_draft_email(
            user_prompt=prompt,
            recipient_override=recipient,
            subject_override=subject,
            body_override=body,
        )
        res = await email_agent.dispatch_to_n8n(draft)
        return {
            "success": res.get("success", True),
            "recipient": draft.get("to"),
            "subject": draft.get("subject"),
            "attachments": draft.get("attachment_names", []),
            "message": res.get("message", "Email workflow completed."),
            "error": res.get("error", ""),
        }

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _execute()).result()
        else:
            return asyncio.run(_execute())
    except Exception as e:
        return {"success": False, "error": f"Email workflow error: {e}"}


@tool
def download_images_from_web(query: str, count: int = 10) -> Dict[str, Any]:
    """
    Search the web for images matching a query and download them to local disk.
    Uses Wikimedia Commons, Wikipedia PageImages, and Web Search.
    Returns a dict with success status and list of downloaded file paths.
    """
    import httpx
    import hashlib
    import re
    import urllib.parse
    from pathlib import Path

    # Clean query: "search the brad pitt photo" -> "brad pitt"
    clean_q = re.sub(r"(?i)\b(search|the|photo|photos|image|images|picture|pictures|wallpaper|hd|of|and|download)\b", " ", query)
    clean_q = re.sub(r"\s+", " ", clean_q).strip()
    if not clean_q or len(clean_q) < 2:
        clean_q = query.strip()

    download_dir = Path.home() / "Downloads" / "nexus_images" / re.sub(r"[^\w\s-]", "", clean_q)[:40].strip()
    download_dir.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "NexusAI/1.0 (Desktop Assistant; charan@nexus.ai)"}
    image_urls = []
    downloaded = []
    errors = []

    try:
        # Strategy 1: Wikimedia Commons Search API
        try:
            commons_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrsearch={urllib.parse.quote(clean_q)}&gsrlimit={count * 3}&prop=imageinfo&iiprop=url|size&format=json"
            with httpx.Client(headers=headers, timeout=12.0) as client:
                r = client.get(commons_url)
                if r.status_code == 200:
                    pages = r.json().get("query", {}).get("pages", {})
                    for pid, p in pages.items():
                        info = p.get("imageinfo", [{}])[0]
                        u = info.get("url")
                        if u and any(ext in u.lower() for ext in (".jpg", ".png", ".jpeg", ".webp")):
                            image_urls.append(u)
        except Exception as ce:
            errors.append(f"Wikimedia Commons search: {ce}")

        # Strategy 2: Wikipedia PageImages API
        if len(image_urls) < count:
            try:
                wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(clean_q)}&gsrlimit=10&prop=pageimages&piprop=original|thumbnail&pithumbsize=800&format=json"
                with httpx.Client(headers=headers, timeout=12.0) as client:
                    r = client.get(wiki_url)
                    if r.status_code == 200:
                        pages = r.json().get("query", {}).get("pages", {})
                        for pid, p in pages.items():
                            orig = p.get("original", {}).get("source") or p.get("thumbnail", {}).get("source")
                            if orig and orig not in image_urls:
                                image_urls.append(orig)
            except Exception as we:
                errors.append(f"Wikipedia search: {we}")

        # Deduplicate
        seen = set()
        unique_urls = []
        for url in image_urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        image_urls = unique_urls[:count * 2]

        # Download images
        with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
            for idx, img_url in enumerate(image_urls):
                if len(downloaded) >= count:
                    break
                try:
                    img_resp = client.get(img_url)
                    if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                        content_type = img_resp.headers.get("content-type", "")
                        ext = ".jpg"
                        if "png" in content_type:
                            ext = ".png"
                        elif "webp" in content_type:
                            ext = ".webp"
                        elif "gif" in content_type:
                            ext = ".gif"

                        safe_name = re.sub(r"[^\w\s-]", "", clean_q).replace(" ", "_")[:20]
                        filename = f"{safe_name}_{idx + 1}{ext}"
                        filepath = download_dir / filename

                        with open(filepath, "wb") as f:
                            f.write(img_resp.content)

                        downloaded.append(str(filepath))
                        logger.info(f"[ImageDownload] Downloaded: {filepath} ({len(img_resp.content)} bytes)")
                except Exception as e:
                    errors.append(f"Failed to download {img_url[:60]}: {e}")

    except Exception as e:
        return {"success": False, "error": f"Image search/download failed: {e}", "downloaded": downloaded}

    if downloaded:
        return {
            "success": True,
            "message": f"Downloaded {len(downloaded)} image(s) for '{clean_q}' to {download_dir}",
            "downloaded": downloaded,
            "download_dir": str(download_dir),
            "errors": errors[:3] if errors else [],
        }
    else:
        return {
            "success": False,
            "error": f"Could not download any images for '{clean_q}'. Tried {len(errors)} sources.",
            "downloaded": [],
            "errors": errors[:5],
        }
