"""Start the app:  python run.py   (then open http://127.0.0.1:8000)"""

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Empower Ops Agents")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}"
    print(f"\n  Empower Ops Agents  ->  {url}\n  (Ctrl+C to stop)\n", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("backend.main:app", host=args.host, port=args.port, log_level="warning", app_dir=str(ROOT))
