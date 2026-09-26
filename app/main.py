"""Launch Lang-Bridge: the API on 127.0.0.1 plus a native window.

    python -m app              native window (pywebview / WebView2)
    python -m app --browser    open in the default browser instead
    python -m app --serve      API only (for `npm run dev` in web/)
    --data <folder>            use another library folder (default: data/), e.g. a sandbox
"""
from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser

import uvicorn


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


def serve(port: int) -> uvicorn.Server:
    from .api import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", help="library folder (database, projects, settings)")
    a = ap.parse_args()
    if a.data:  # before the app modules load: they read the folder at import
        os.environ["LANGBRIDGE_DATA"] = os.path.abspath(a.data)
    from .api import app
    if a.serve:
        uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="info")
        return
    port = free_port(a.port)
    serve(port)
    url = f"http://127.0.0.1:{port}/"
    if a.browser:
        webbrowser.open(url)
        print("Lang-Bridge at", url, "(Ctrl+C to quit)")
        while True:
            time.sleep(3600)
    import webview

    webview.create_window("Lang-Bridge", url, width=1360, height=860, min_size=(900, 600))
    webview.start()


if __name__ == "__main__":
    main()
