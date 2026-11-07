"""RawAgent — a minimal function-calling loop using the LLMClient interface.

Deliberately framework-free: this is the control subject that proves Gauntlet
measures *agents*, not frameworks. It runs a standard tool-calling loop:
  model -> (tool call? -> run tool -> feed result -> repeat) -> final answer.

All fairness-critical metrics (tokens, latency) come from the LLMResponse the
client returns, which on the real path originates from Bifrost.
"""
from __future__ import annotations

import time
from typing import Optional

from ..base import AgentResult, Task
from ..llm import LLMClient, MockClient, ProviderOutage

SYSTEM_PROMPT = (
    "You are a precise task-solving agent. Use tools when they help. "
    "When you have the answer, reply with ONLY the answer in the exact format requested."
)


class RawAgent:
    name = "raw_agent"

    def __init__(self, client: LLMClient, tool=None, max_steps: int = 5):
        self.client = client
        self.tool = tool              # a web_search tool instance, or None
        self.max_steps = max_steps

    def run(self, task: Task, run_id: str, chaos_mode: str = "none") -> AgentResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.prompt},
        ]
        tools = [self.tool.spec] if self.tool else None

        steps = 0
        tool_calls = 0
        pt = ct = tt = 0
        latency = 0.0
        trace: list[dict] = []
        final = ""
        error: Optional[str] = None

        try:
            while steps < self.max_steps:
                steps += 1
                resp = self.client.chat(messages, tools=tools)
                pt += resp.prompt_tokens
                ct += resp.completion_tokens
                tt += resp.total_tokens
                latency += resp.latency_ms
                messages.append(resp.raw_message)
                trace.append({
                    "step": steps, "type": "model",
                    "content": resp.content,
                    "tool_calls": [tc.name for tc in resp.tool_calls],
                    "latency_ms": round(resp.latency_ms, 1),
                    "completion_tokens": resp.completion_tokens,
                })

                if resp.tool_calls:
                    for tc in resp.tool_calls:
                        tool_calls += 1
                        if self.tool and tc.name == self.tool.name:
                            result = self.tool.call(tc.arguments)
                            content = result.content if result.ok else f"TOOL ERROR: {result.error}"
                        else:
                            content = f"TOOL ERROR: unknown tool {tc.name}"
                            result = None
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id, "content": content,
                        })
                        trace.append({
                            "step": steps, "type": "tool", "name": tc.name,
                            "arguments": tc.arguments,
                            "ok": bool(result and result.ok),
                            "content": content[:300],
                        })
                    continue  # let the model react to tool output

                final = (resp.content or "").strip()
                break
        except ProviderOutage as e:
            error = f"provider_outage: {e}"
            trace.append({"step": steps, "type": "error", "content": str(e)})

        # cost: from mock pricing, or 0.0 here (real cost is joined from Bifrost logs)
        cost = 0.0
        if isinstance(self.client, MockClient):
            cost = self.client.cost(pt, ct)

        from ..metrics import score
        success = (error is None) and score(task, final)

        return AgentResult(
            run_id=run_id, agent=self.name, task_id=task.id, chaos_mode=chaos_mode,
            success=success, final_answer=final, steps=steps, tool_calls=tool_calls,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
            cost_usd=round(cost, 8), latency_ms=round(latency, 1),
            retries=0, error=error, trace=trace,
        )
