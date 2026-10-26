"""Bench Optimizer data: internal initiatives and the course catalogue (data/seed/bench/).

Everything else (people, assignments, deals) comes from the shared company data and the Deal Desk.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ...core.config import DATA_DIR


@lru_cache(maxsize=1)
def bench_data() -> dict:
    folder = DATA_DIR / "bench"
    missing = [f for f in ("internal_work.json", "courses.json") if not (folder / f).exists()]
    if missing:
        raise FileNotFoundError(f"{folder} is missing {', '.join(missing)}. Run: python scripts/generate_bench_data.py")
    return {
        "internal_work": json.loads((folder / "internal_work.json").read_text(encoding="utf-8")),
        "courses": json.loads((folder / "courses.json").read_text(encoding="utf-8")),
    }


def internal_work() -> list[dict]:
    return bench_data()["internal_work"]


def courses() -> list[dict]:
    return bench_data()["courses"]
