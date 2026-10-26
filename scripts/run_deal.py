"""Run one Deal Desk deal from the command line (no web server) and print what each agent did.

    python scripts/run_deal.py --sample dental-us
    python scripts/run_deal.py --file my_brief.txt --client "Acme" --country US --currency USD
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import SAMPLE_BRIEFS  # noqa: E402
from backend.modules.deal_desk import pipeline  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="id from data/sample_briefs.json")
    ap.add_argument("--file", help="text file with the client's request")
    ap.add_argument("--client", default="")
    ap.add_argument("--country", default="")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--out", help="write the full run JSON here")
    args = ap.parse_args()

    if args.sample:
        s = next(b for b in json.loads(SAMPLE_BRIEFS.read_text(encoding="utf-8")) if b["id"] == args.sample)
        inp = {"brief": s["brief"], "client_name": s["client_name"], "client_country": s["client_country"],
               "currency": s["currency"], "desired_start": ""}
    else:
        inp = {"brief": Path(args.file).read_text(encoding="utf-8"), "client_name": args.client,
               "client_country": args.country, "currency": args.currency, "desired_start": ""}

    run_id = pipeline.uuid.uuid4().hex[:10]
    state = pipeline.new_state(run_id, inp, "cli")
    await pipeline.DealRun(run_id, state).run()

    print(f"\nRun {run_id}: {state['status']}  {state.get('error') or ''}")
    for s in state["steps"].values():
        u = s.get("usage") or {}
        print(f"  {s['label']:<22} {s['status']:<8} {s.get('seconds', 0):>6}s  in={u.get('input_tokens', 0):>7} "
              f"cached={u.get('cached_tokens', 0):>7} out={u.get('output_tokens', 0):>6} ${u.get('cost_usd', 0):.4f}  | {s.get('summary', '')}")
    u = state["usage"]
    print(f"  TOTAL: in={u['input_tokens']} cached={u['cached_tokens']} ({u['cache_hit_pct']}%) out={u['output_tokens']} "
          f"reasoning={u['reasoning_tokens']} requests={u['requests']} tools={u['tool_calls']} cost=${u['cost_usd']:.4f}")
    if args.out:
        Path(args.out).write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"  saved -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
