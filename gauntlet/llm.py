"""LLM clients behind one interface.

- BifrostClient: real calls through the Bifrost gateway (OpenAI-compatible).
  Reads token usage from the response; robustness/retry data comes from Bifrost's
  own logs (joined later for the dashboard).
- MockClient: deterministic, offline, zero-cost. Lets the whole harness —
  agent loop, tool use, scoring, metrics, dashboard — be built and tested with
  no API spend. It also powers Chaos Mode 2 (model_outage) by raising a
  provider-style error on demand.

Both return the normalized LLMResponse from base.py, so agents are identical
across them.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional, Protocol

from .base import LLMResponse, ToolCallRequest
from .config import settings


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse: ...


class ProviderOutage(RuntimeError):
    """Raised to simulate an unavailable model/provider (Chaos Mode 2)."""


# ── Real gateway client ─────────────────────────────────────────────────────────
class BifrostClient:
    """Routes through Bifrost at settings.bifrost_base_url using the OpenAI SDK."""

    def __init__(self, model: Optional[str] = None):
        from openai import OpenAI  # imported lazily so mock-only runs need no network

        self.model = model or settings.model
        self._client = OpenAI(
            base_url=settings.bifrost_base_url,
            api_key=settings.bifrost_virtual_key,
        )

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        t0 = time.perf_counter()
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        msg = resp.choices[0].message
        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))

        usage = resp.usage
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            raw_message=msg.model_dump(),
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            latency_ms=latency_ms,
            finish_reason=resp.choices[0].finish_reason or "stop",
        )


# ── Offline deterministic mock ──────────────────────────────────────────────────
class MockClient:
    """A rules-based stand-in for an LLM.

    It inspects the latest user prompt and produces a plausible answer or tool
    call, so agent/tool/scoring/metrics code can be exercised with no provider.
    Not meant to be *smart* — meant to be *deterministic and free*. Token counts
    are estimated from text length so cost math is exercised too.

    outage_rate: probability [0,1] of raising ProviderOutage (Chaos Mode 2).
    """

    PRICE_PER_1K_PROMPT = 0.00015   # gpt-4o-mini-ish, for cost-math realism
    PRICE_PER_1K_COMPLETION = 0.0006

    def __init__(self, model: str = "mock/gpt", outage_rate: float = 0.0, seed: int = 0):
        self.model = model
        self.outage_rate = outage_rate
        import random
        self._rng = random.Random(seed)
        self._answered_web: set[str] = set()

    @staticmethod
    def _est_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def _latest_user(self, messages: list[dict]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    def _has_tool_result(self, messages: list[dict]) -> bool:
        return any(m.get("role") == "tool" for m in messages)

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        t0 = time.perf_counter()
        if self.outage_rate and self._rng.random() < self.outage_rate:
            raise ProviderOutage("mock provider: upstream unavailable (503)")

        prompt = self._latest_user(messages)
        answer = self._solve(prompt)

        # If the task needs the web and we have tools but no tool result yet,
        # emit a search tool call first (exercises the tool path).
        wants_web = bool(re.search(r"web search|using web", prompt, re.I))
        if wants_web and tools and not self._has_tool_result(messages):
            query = re.sub(r"(?i)using web search,?\s*", "", prompt).strip()
            tc = ToolCallRequest(id="call_mock_1", name="web_search", arguments={"query": query})
            raw = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps({"query": query})},
                }],
            }
            pt, ct = self._est_tokens(prompt), 12
            return LLMResponse(
                content=None, tool_calls=[tc], raw_message=raw,
                prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
                latency_ms=(time.perf_counter() - t0) * 1000.0, finish_reason="tool_calls",
            )

        # Otherwise answer directly. For web tasks, a faithful agent derives its
        # answer ONLY from the tool result in history — so if the tool failed or
        # lied, the agent must reflect that (this is what makes chaos real).
        if wants_web:
            answer = self._answer_from_tool(messages)

        raw = {"role": "assistant", "content": answer}
        pt, ct = self._est_tokens(prompt), self._est_tokens(answer)
        return LLMResponse(
            content=answer, tool_calls=[], raw_message=raw,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            latency_ms=(time.perf_counter() - t0) * 1000.0, finish_reason="stop",
        )

    # --- toy "reasoning" so offline runs produce mostly-correct answers ---
    def _solve(self, prompt: str) -> str:
        p = prompt.lower()
        if "347" in prompt and "29" in prompt:
            return "10063"
        if "540" in prompt and "4.5" in prompt:
            return "120"
        if "bat and a ball" in p:
            return "5"
        if "primary colors" in p:
            return "red,yellow,blue"
        if "email address" in p:
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", prompt)
            return m.group() if m else "unknown"
        if "capital" in p and "australia" in p:
            return "Canberra"
        if "secretary-general" in p:
            return "Antonio Guterres"
        if "programming language" in p and "google" in p:
            return "Go"
        return "I don't know."

    def _answer_from_tool(self, messages: list[dict]) -> str:
        """Extract the answer from the most recent tool output — faithfully.

        A well-behaved agent trusts its tool: if the tool errored, it cannot
        answer; if the tool returned content (even wrong content), the agent
        reports what the tool said. This is deliberate so Chaos Mode 1
        (tool_failure / misleading) actually changes the outcome.
        """
        tool_text = ""
        for m in reversed(messages):
            if m.get("role") == "tool":
                tool_text = m.get("content", "") or ""
                break

        if not tool_text or "TOOL ERROR" in tool_text:
            return "I don't know — the search tool is unavailable."

        # Pull the entity the tool reports (handles both correct and misleading).
        # Word-boundary match so 'Go' isn't found inside 'Google'; order matters,
        # so multi-word / more-specific names are checked first.
        candidates = [
            "Canberra", "Sydney", "Antonio Guterres", "Ban Ki-moon", "Guterres",
            "Golang", "Dart", "Python", "Go",
        ]
        for kw in candidates:
            if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", tool_text, re.IGNORECASE):
                return kw
        return "I don't know."

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens / 1000 * self.PRICE_PER_1K_PROMPT
                + completion_tokens / 1000 * self.PRICE_PER_1K_COMPLETION)
