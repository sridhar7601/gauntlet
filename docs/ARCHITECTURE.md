# Gauntlet — Architecture

## One-line thesis
Benchmark **agents, not models**, by routing every agent's LLM + tool traffic
through the **Bifrost** gateway and measuring at the gateway — so the metrics are
identical and fair across any agent framework, and failure can be injected
centrally.

## Why route through Bifrost?
A benchmark that calls each framework's own callbacks to collect token/cost data
is *not* framework-independent — every framework reports differently (or not at
all). Bifrost exposes **one OpenAI-compatible endpoint** (`/v1/chat/completions`)
and records, for every request, the input, output, token usage, cost, latency,
retries and provider-failover trail. Point any agent at
`BIFROST_BASE_URL` and we get uniform, trustworthy numbers for free.

This also makes the **failure-injection** story clean: instead of hacking each
agent, we degrade the shared gateway/tool layer and watch how each agent copes.

## Components

### 1. Task suite (`tasks/suite.yaml`)
Identical tasks run against every agent. Each task declares a deterministic
`check` (numeric / regex / substring) so MVP scoring needs no LLM judge. Tasks
flagged `needs_web: true` require the Tavily tool and are the subjects for
Chaos Mode 1.

### 2. Agents (`gauntlet/agents/`) — the subjects under test
At least two, deliberately different frameworks, to prove framework-independence:
- **`raw_agent`** — a minimal function-calling loop using the OpenAI SDK pointed
  at Bifrost. Full control; no framework magic.
- **`langchain_agent`** — a LangChain ReAct agent, same Bifrost base URL.

Every agent implements the same interface: `run(task) -> AgentResult` returning
the final answer plus a trace (steps, tool calls). Metrics that must be fair
(tokens/cost/latency) come from Bifrost, not from the agent's self-report.

### 3. Tools (`gauntlet/tools/`)
- **`web_search`** — wraps Tavily Search/Extract. In normal mode it returns clean
  results; in Chaos Mode 1 a sabotaged variant returns errors or misleading
  content, to test tool-failure resilience.

### 4. Gateway layer — Bifrost (`:8080`)
- OpenAI-compatible routing + provider resolution.
- **Observability**: per-request tokens, cost, latency; `number_of_retries` and
  `attempt_trail` (which key tried, why it failed, whether it rotated).
- **Governance** (optional, stretch): a virtual key per agent run with a budget
  cap, to demonstrate per-agent spend isolation.
- **Mocker plugin** (chaos): fake provider responses / failures without touching
  real providers — doubles as our zero-cost dev mode.

### 5. Metrics store (`results/`)
Each run writes a row: `{run_id, agent, task_id, success, steps, tool_calls,
prompt_tokens, completion_tokens, cost_usd, latency_ms, retries, chaos_mode,
error}`. Stored as JSON lines + a small SQLite file the dashboard reads.

### 6. Dashboard (`dashboard/app.py`, Streamlit)
- **Leaderboard**: success rate, avg cost, avg latency, robustness score per agent.
- **Chaos comparison**: same agents, happy-path vs each chaos mode side by side.
- **Trace drill-down**: per-run step/tool-call timeline + the Bifrost attempt
  trail, so a judge can see *why* an agent won or failed.

## Request lifecycle (one task, one agent)
```
runner picks task ──▶ agent.run(task)
   agent → OpenAI SDK → Bifrost /v1/chat/completions
       Bifrost: resolve provider, (maybe) inject chaos, call upstream,
                record tokens/cost/latency/attempt_trail
   agent (maybe) → web_search tool → Tavily  (or sabotaged in Chaos 1)
   agent loops until final answer or step cap
runner scores answer via task.check ──▶ writes metrics row
```

## Metrics definitions (so the leaderboard is honest)
- **success**: deterministic `check` passed (1/0).
- **steps**: agent reasoning iterations (model turns).
- **tool_calls**: number of tool invocations.
- **tokens / cost / latency**: from Bifrost's per-request record (authoritative).
- **retries**: Bifrost `number_of_retries` for the run's requests.
- **robustness score** (stretch): success rate under chaos ÷ success rate on
  happy path — how much of its capability survives failure.

## Why this wins the theme
The theme's exact asks map 1:1 onto Bifrost features we measure at the gateway:
success/steps/tool-calls/tokens/cost/time (observability), failing tools
(sabotaged tool + Mocker), unavailable models (disable key + attempt_trail),
misleading instructions (prompt mutation), and a comparison UI with execution
traces (dashboard). Nothing is hand-waved; every number has a source.
