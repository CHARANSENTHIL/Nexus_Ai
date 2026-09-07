"""
Nexus AI — Unified Application Launcher.
Ensures sys.path and app_dir are configured so uvicorn reloader never throws ModuleNotFoundError.
"""
import sys
import os
from pathlib import Path
import uvicorn

# Resolve root & backend directories
root_dir = Path(__file__).resolve().parent
backend_dir = root_dir / "backend"

if backend_dir.exists():
    backend_path = str(backend_dir)
else:
    backend_path = str(root_dir)

# Ensure backend is in sys.path and PYTHONPATH environment variable
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
os.environ["PYTHONPATH"] = backend_path + (os.pathsep + os.environ.get("PYTHONPATH", "") if "PYTHONPATH" in os.environ else "")

if __name__ == "__main__":
    print(f"🚀 Starting Nexus AI Backend with app_dir={backend_path}")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        app_dir=backend_path,
    )
