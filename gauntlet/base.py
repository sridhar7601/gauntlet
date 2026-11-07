"""Shared types for Gauntlet: tasks, LLM responses, tool calls, run results.

Agents are written against these types, not against any provider SDK — so the
same agent runs on the real Bifrost gateway or on a local mock unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


# ── Benchmark tasks ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    needs_web: bool
    check: dict  # {"type": "numeric_equals"|"contains_any"|"contains_all"|"regex", "value": ...}


# ── LLM abstraction (provider-agnostic) ───────────────────────────────────────
@dataclass
class ToolCallRequest:
    """A tool call the model wants to make."""
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """One model turn, normalized across Bifrost and the local mock."""
    content: Optional[str]
    tool_calls: list[ToolCallRequest]
    raw_message: dict  # OpenAI-format assistant message, appended to history verbatim
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"


# ── Tools ─────────────────────────────────────────────────────────────────────
@dataclass
class ToolResult:
    content: str
    ok: bool = True
    error: Optional[str] = None


# ── Per-(agent, task, run) outcome ────────────────────────────────────────────
@dataclass
class AgentResult:
    run_id: str
    agent: str
    task_id: str
    chaos_mode: str          # "none" | "tool_failure" | "model_outage" | "misleading"
    success: bool
    final_answer: str
    steps: int               # model turns taken
    tool_calls: int          # tool invocations
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float        # summed model latency across turns
    retries: int             # gateway retries (from Bifrost; 0 for mock)
    error: Optional[str] = None
    trace: list[dict] = field(default_factory=list)  # step-by-step for drill-down

    def flat_row(self) -> dict:
        """Row for SQLite / leaderboard (trace excluded)."""
        d = asdict(self)
        d.pop("trace", None)
        return d
