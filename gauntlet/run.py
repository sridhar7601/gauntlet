"""Gauntlet CLI runner.

Runs agents against the task suite, N times each, optionally under a chaos mode,
scores deterministically, and writes metrics.

Examples:
    python -m gauntlet.run --mock --runs 3
    python -m gauntlet.run --mock --chaos tool_failure --runs 3
    python -m gauntlet.run --mock --chaos model_outage --outage-rate 0.5 --runs 5
    python -m gauntlet.run --agents raw_agent --runs 2        # real Bifrost path
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from .base import Task
from .agents.raw_agent import RawAgent
from .llm import BifrostClient, MockClient
from .metrics import write_results
from .tools.web_search import make_web_search

console = Console()
SUITE = Path(__file__).resolve().parent.parent / "tasks" / "suite.yaml"

CHAOS_MODES = {"none", "tool_failure", "misleading", "model_outage"}


def load_tasks() -> list[Task]:
    raw = yaml.safe_load(SUITE.read_text())
    return [Task(id=t["id"], prompt=t["prompt"], needs_web=bool(t.get("needs_web")),
                 check=t["check"]) for t in raw]


def build_agents(agent_names, mock: bool, chaos: str, outage_rate: float):
    """Return list of (agent_label, agent_instance)."""
    # tool chaos only affects the web tool; model_outage affects the client
    tool_chaos = chaos if chaos in ("tool_failure", "misleading") else None
    web = make_web_search(mock=mock, chaos=tool_chaos)

    agents = []
    if "raw_agent" in agent_names:
        if mock:
            rate = outage_rate if chaos == "model_outage" else 0.0
            client = MockClient(outage_rate=rate)
        else:
            client = BifrostClient()
        agents.append(("raw_agent", RawAgent(client=client, tool=web)))
    return agents


def main():
    ap = argparse.ArgumentParser(prog="gauntlet.run")
    ap.add_argument("--agents", default="raw_agent",
                    help="comma list or 'all' (default: raw_agent)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--chaos", default="none", choices=sorted(CHAOS_MODES))
    ap.add_argument("--outage-rate", type=float, default=0.5,
                    help="model_outage probability per model call (mock only)")
    ap.add_argument("--mock", action="store_true",
                    help="use offline MockClient (zero API spend)")
    args = ap.parse_args()

    agent_names = {"raw_agent"} if args.agents == "all" else set(args.agents.split(","))
    tasks = load_tasks()
    agents = build_agents(agent_names, args.mock, args.chaos, args.outage_rate)
    if not agents:
        console.print(f"[red]No agents built for {agent_names}[/red]")
        return

    mode_label = f"[bold]{args.chaos}[/bold]" + (" (mock)" if args.mock else " (bifrost)")
    console.print(f"Running {len(agents)} agent(s) × {len(tasks)} tasks × {args.runs} runs "
                  f"| chaos={mode_label}")

    results = []
    for label, agent in agents:
        for task in tasks:
            for i in range(args.runs):
                run_id = f"{uuid.uuid4().hex[:8]}"
                res = agent.run(task, run_id=run_id, chaos_mode=args.chaos)
                results.append(res)

    n = write_results(results)

    # summary leaderboard
    table = Table(title=f"Gauntlet results — chaos={args.chaos}")
    for col in ["agent", "runs", "success%", "avg steps", "avg tool calls",
                "avg tokens", "avg cost $", "avg latency ms", "errors"]:
        table.add_column(col, justify="right")
    for label, _ in agents:
        rs = [r for r in results if r.agent == label]
        ok = sum(r.success for r in rs)
        errs = sum(1 for r in rs if r.error)
        table.add_row(
            label, str(len(rs)), f"{100*ok/len(rs):.0f}%",
            f"{sum(r.steps for r in rs)/len(rs):.1f}",
            f"{sum(r.tool_calls for r in rs)/len(rs):.1f}",
            f"{sum(r.total_tokens for r in rs)/len(rs):.0f}",
            f"{sum(r.cost_usd for r in rs)/len(rs):.6f}",
            f"{sum(r.latency_ms for r in rs)/len(rs):.1f}",
            str(errs),
        )
    console.print(table)
    console.print(f"[green]wrote {n} rows[/green] → results/runs.jsonl + results/gauntlet.sqlite")


if __name__ == "__main__":
    main()
