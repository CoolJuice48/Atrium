#!/usr/bin/env python3
"""
One-click dev runner: backend + frontend.
Usage: python scripts/dev.py
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "3000"))
API_BASE = f"http://localhost:{BACKEND_PORT}"


def port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    os.chdir(ROOT)
    venv = ROOT / ".venv"
    if not venv.exists():
        print("No .venv found. Run: make setup")
        sys.exit(1)

    if port_in_use(BACKEND_PORT):
        print(f"Port {BACKEND_PORT} is in use. Stop the process or set BACKEND_PORT=<port>")
        sys.exit(1)
    if port_in_use(FRONTEND_PORT):
        print(f"Port {FRONTEND_PORT} is in use. Stop the process or set FRONTEND_PORT=<port>")
        sys.exit(1)

    print()
    print(f"  Backend:  {API_BASE}/docs")
    print(f"  Frontend: http://localhost:{FRONTEND_PORT}")
    print()

    env = os.environ.copy()
    env["NEXT_PUBLIC_API_BASE"] = API_BASE

    uvicorn = venv / "bin" / "uvicorn"
    if sys.platform == "win32":
        uvicorn = venv / "Scripts" / "uvicorn.exe"

    backend = subprocess.Popen(
        [str(uvicorn), "server.app:app", "--reload", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
        cwd=ROOT,
        env=env,
    )

    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "-p", str(FRONTEND_PORT)],
        cwd=ROOT / "frontend",
        env=env,
    )

    def cleanup(sig=None, frame=None):
        backend.terminate()
        frontend.terminate()
        backend.wait()
        frontend.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    backend.wait()
    frontend.wait()


if __name__ == "__main__":
    main()
