"""Runs agents step by step and records what they did.

A RunRecorder belongs to one run (one deal, one staffing question). For every agent step it keeps:
status and timing, token usage per model call (input / cached / output / reasoning), every tool call
with its arguments and a clipped result, and the step's structured output. The UI's trace view and
the usage ledger both come from here.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RunUsage, UsageLimits

from . import store
from .config import RUN_REQUEST_LIMIT, RUN_TOOL_CALLS_LIMIT, RUN_TOTAL_TOKENS_LIMIT, TRACE_TEXT_LIMIT
from .usage import Tally

RUN_LIMITS = UsageLimits(
    request_limit=RUN_REQUEST_LIMIT,
    tool_calls_limit=RUN_TOOL_CALLS_LIMIT,
    total_tokens_limit=RUN_TOTAL_TOKENS_LIMIT,
)


def clip(value: Any, limit: int = TRACE_TEXT_LIMIT) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f" …[+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


class RunRecorder:
    def __init__(self, run_id: str, module: str, state: dict[str, Any], persist: Callable[[], None]) -> None:
        self.run_id = run_id
        self.module = module
        self.state = state
        self.persist = persist
        self.usage = RunUsage()  # shared by every agent in the run so RUN_LIMITS cap the whole run
        self.total = Tally()
        self._tallies: dict[str, Tally] = {}
        self._t0 = time.monotonic()
        state.setdefault("steps", {})
        state.setdefault("trace", [])
        state["usage"] = self.total.to_dict()

    # ------------------------------------------------------------------ events

    def event(self, agent: str, kind: str, text: str, data: Any = None) -> None:
        self.state["trace"].append({
            "t": round(time.monotonic() - self._t0, 2),
            "agent": agent,
            "kind": kind,
            "text": clip(text, 600),
            "data": clip(data) if data is not None else None,
        })

    def event_time(self) -> float:
        return round(time.monotonic() - self._t0, 2)

    def step(self, key: str) -> dict[str, Any]:
        return self.state["steps"][key]

    def start_step(self, key: str, detail: str = "") -> None:
        s = self.step(key)
        s.update(status="running", started_at=round(time.monotonic() - self._t0, 2), detail=detail)
        s.setdefault("rounds", 0)
        s["rounds"] += 1
        self.event(key, "agent_start", detail or f"{s['label']} started")
        self.persist()

    def finish_step(self, key: str, summary: str, status: str = "done") -> None:
        s = self.step(key)
        s["status"] = status
        s["ended_at"] = round(time.monotonic() - self._t0, 2)
        s["seconds"] = round(s["ended_at"] - (s.get("started_at") or 0), 1)
        s["summary"] = summary
        self.event(key, "agent_end" if status == "done" else f"agent_{status}", summary)
        self.persist()

    def skip_step(self, key: str, why: str) -> None:
        s = self.step(key)
        s.update(status="skipped", summary=why)
        self.event(key, "agent_skipped", why)

    # ------------------------------------------------------------------ the agent loop

    async def run_agent(self, key: str, agent: Agent, prompt: str, deps: Any) -> BaseModel:
        """Run one agent to completion, recording tool calls and per-call token usage."""
        step = self.step(key)
        step_tally = self._tallies.setdefault(key, Tally())  # across revision rounds (shown in the UI)
        tally = Tally()  # this round only (written to the ledger)
        try:
            async with agent.iter(prompt, deps=deps, usage=self.usage, usage_limits=RUN_LIMITS) as run:
                async for node in run:
                    if Agent.is_call_tools_node(node):
                        resp = node.model_response
                        for t in (tally, step_tally, self.total):
                            t.add_response(resp.usage)
                        for part in resp.parts:
                            if isinstance(part, ToolCallPart):
                                for t in (tally, step_tally, self.total):
                                    t.tool_calls += 1
                                self.event(key, "tool_call", part.tool_name, part.args_as_dict())
                            elif isinstance(part, TextPart) and part.content.strip():
                                self.event(key, "model_text", part.content)
                    elif Agent.is_model_request_node(node):
                        for part in node.request.parts:
                            if isinstance(part, ToolReturnPart):
                                content = part.content
                                if not isinstance(content, str):
                                    content = json.dumps(content, default=str)
                                self.event(key, "tool_result", part.tool_name, content)
                            elif isinstance(part, RetryPromptPart):
                                self.event(key, "retry", f"Output/tool validation failed; model asked to fix it ({part.tool_name or 'output'})",
                                           str(part.content))
                    step["usage"] = step_tally.to_dict()
                    self.state["usage"] = self.total.to_dict()
                output = run.result.output
        finally:
            step["usage"] = step_tally.to_dict()
            self.state["usage"] = self.total.to_dict()
            if tally.requests:
                store.add_usage(self.run_id, self.module, key, tally.to_dict())
        return output
