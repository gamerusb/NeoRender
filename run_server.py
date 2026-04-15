"""
Запуск NeoRender API + UI с автоподбором порта, если 8765 занят.

  py run_server.py
  set NEORENDER_PORT=9000 && py run_server.py
"""

from __future__ import annotations

import os
import socket
import sys


def _find_port(start: int = 8765, attempts: int = 24) -> int:
    env = os.environ.get("NEORENDER_PORT", "").strip()
    if env.isdigit():
        return int(env)
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def main() -> None:
    port = _find_port()
    host = os.environ.get("NEORENDER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    print(f"NeoRender Pro: http://{host}:{port}/ui/", flush=True)
    try:
        import uvicorn
    except ImportError:
        print("Установите uvicorn: py -m pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)
    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        reload=os.environ.get("NEORENDER_RELOAD", "").strip() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
