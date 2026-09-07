"""
Nexus AI — Backend Launcher.
"""
import sys
import os
from pathlib import Path
import uvicorn

backend_path = str(Path(__file__).resolve().parent)
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
