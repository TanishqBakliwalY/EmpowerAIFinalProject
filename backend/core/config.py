"""Paths, model, prices and safety limits shared by every module."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # the repo folder

# Keys: the repo's own .env first, then the .env one folder above the repo (how the graders run it).
# load_dotenv never overrides a value that is already set, so the repo's .env wins.
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


# ---- data -------------------------------------------------------------------
# data/seed is the synthetic demo dataset shipped in the repo. Point EMPOWER_DATA_DIR at a folder with
# the same files (e.g. _private/data) to run on real company data.
DATA_DIR = _env_path("EMPOWER_DATA_DIR", ROOT / "data" / "seed")
SAMPLE_BRIEFS = ROOT / "data" / "sample_briefs.json"
DEMO_RUNS_DIR = ROOT / "data" / "demo_runs"  # example deals saved from real runs, loaded on first start
RUNTIME_DIR = _env_path("EMPOWER_RUNTIME_DIR", ROOT / "data" / "runtime")
DB_PATH = RUNTIME_DIR / "app.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# ---- model ------------------------------------------------------------------
# The course key allows only gpt-6-luna, so the model is fixed in code, not read from the environment.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_TIMEOUT_SECONDS = 180

# USD per 1M tokens, used to turn measured token counts into money. Published gpt-6-luna rates (Oct 2026):
# $0.10 input, $0.01 cached input, $0.50 output (above 272K-token prompts it is higher; our prompts stay far below).
# Override in .env if the price sheet changes; costs shown in the app are always recomputed from token counts.
PRICE_INPUT_PER_M = _env_float("PRICE_INPUT_PER_M", 0.10)
PRICE_CACHED_INPUT_PER_M = _env_float("PRICE_CACHED_INPUT_PER_M", 0.01)
PRICE_OUTPUT_PER_M = _env_float("PRICE_OUTPUT_PER_M", 0.50)

# ---- safety and spend limits ---------------------------------------------------
RUN_REQUEST_LIMIT = 70            # model round-trips across all agents in one deal run
RUN_TOOL_CALLS_LIMIT = 100        # tool executions across all agents in one deal run
RUN_TOTAL_TOKENS_LIMIT = 600_000  # input + output tokens across one deal run
DAILY_BUDGET_USD = _env_float("DAILY_BUDGET_USD", 5.0)  # all runs on this server, per UTC day
RUNS_PER_HOUR_PER_CLIENT = 8      # per browser IP
CHATS_PER_HOUR_PER_CLIENT = 40    # staffing questions per browser IP
MAX_BRIEF_CHARS = 40_000            # ~10k tokens: room for a real RFP, still a bounded cost
MAX_ATTACHMENT_BYTES = 10_000_000   # uploaded PDF/TXT
MAX_ATTACHMENT_PAGES = 60
MAX_ATTACHMENT_CHARS = 40_000
COPILOT_REQUEST_LIMIT = 14          # model round-trips per chat message (incl. sub-agents it calls)
COPILOT_TOOL_CALLS_LIMIT = 24       # tool executions per chat message (incl. sub-agents)
COPILOT_TOTAL_TOKENS_LIMIT = 150_000
COPILOT_MESSAGES_PER_HOUR = 60      # per browser IP
COPILOT_HISTORY_MESSAGES = 16       # most recent messages replayed to the model
MIN_BRIEF_CHARS = 40
MAX_REVISION_ROUNDS = 1           # Deal Critic may send work back once
AGENT_OUTPUT_RETRIES = 2
TRACE_TEXT_LIMIT = 3_000          # longest single string kept in a trace event

# A marker placed in every system prompt. If it ever shows up in something we hand to a client,
# the prompt leaked and the output is blocked.
PROMPT_CANARY = "EMPWR-CANARY-7731"
