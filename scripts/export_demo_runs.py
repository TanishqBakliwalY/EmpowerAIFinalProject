"""Save finished runs from the local database as example runs that ship with the repo.

    python scripts/export_demo_runs.py 9705724507 2e923a94f3                 # Deal Desk deals
    python scripts/export_demo_runs.py --module scope_guard <run_id> ...      # other modules

They load automatically the first time the app starts on a fresh install (when that module has no runs).
Deal Desk examples go to data/demo_runs/, other modules to data/demo_runs/<module>/.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import store  # noqa: E402
from backend.core.config import DEMO_RUNS_DIR  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--module", default="deal_desk")
ap.add_argument("run_ids", nargs="+")
args = ap.parse_args()
folder = DEMO_RUNS_DIR if args.module == "deal_desk" else DEMO_RUNS_DIR / args.module
folder.mkdir(parents=True, exist_ok=True)
for i, run_id in enumerate(args.run_ids, start=1):
    d = store.get_run(run_id)
    if not d:
        print(f"no run {run_id}")
        continue
    d.pop("client_ip", None)
    d["decision"] = None
    if d.get("status") in ("approved", "rejected", "changes_requested"):
        d["status"] = "ready"
    out = folder / f"{i:02d}-{run_id}.json"
    out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {out} ({out.stat().st_size // 1024} KB) - {d.get('title')}")
