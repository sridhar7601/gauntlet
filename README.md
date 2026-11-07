# Gauntlet 🛡️

**An agent benchmarking harness that measures survival, not just smarts.**

> We don't just measure which agent is *smartest* — we measure which one *survives*
> when the tools break, the model goes down, and the instructions lie.

Built for the **Geek Room Global AI Hackathon** · Theme: *"Build a Benchmarking
Platform for AI Agents, Not Just Models."*
Primary track: **Bifrost (by Maxim AI)** · Integrated track: **Tavily (by Nebius)**

---

## The problem

Most "agent benchmarks" actually benchmark *models* — one prompt, one answer,
one score. But in production an agent's reliability is decided by everything
*around* the model: Does it recover when a tool fails? When a provider goes
down? When a user instruction is misleading? Those failures are invisible to a
leaderboard that only measures accuracy on a happy path.

## The idea

Gauntlet is a **framework-independent** harness that runs any number of agents
against an *identical* task suite and measures, per run:

- ✅ **Task success** (deterministic checks where possible)
- 🔁 **Execution steps** and 🔧 **tool calls**
- 🪙 **Token usage** and 💲 **cost**
- ⏱️ **Completion time**
- 🛡️ **Robustness under failure** — the part nobody else measures

The trick that makes it framework-independent: **every agent's LLM and tool
traffic is routed through [Bifrost](https://github.com/maximhq/bifrost)**, an
OpenAI-compatible AI gateway. We instrument the *gateway*, not the agent — so
tokens, cost, latency, retries and provider-failover data are captured
identically no matter how the agent is written (LangChain, a raw loop, anything
that can point at a base URL).

## Chaos Modes — the differentiator

The theme asks to "test how agents respond to failing tools, unavailable models,
and misleading instructions." Gauntlet does exactly that, driven by Bifrost:

| Chaos Mode | What it injects | How | What we learn |
|---|---|---|---|
| **1 — Tool failure** | Web-search tool returns errors/garbage | sabotaged Tavily tool wrapper / Bifrost Mocker | Does the agent retry, degrade gracefully, or hallucinate? |
| **2 — Model outage** | Primary provider/key goes down mid-run | disable provider key in Bifrost; observe `attempt_trail` | Does it fail over and recover? How many retries? |
| **3 — Misleading instruction** | A false hint is injected into the prompt | task-level prompt mutation | Does it trust the web/tools over a bad instruction? |

Bifrost natively records `number_of_retries` and a per-attempt `attempt_trail`
(which key was tried, why it failed, whether it rotated) — so Chaos Mode 2's
recovery story is measured at the gateway with **zero agent code**.

## Architecture

```
                 ┌──────────────────────────────────────────┐
   tasks/        │                 Gauntlet                  │
   suite.yaml ──▶│  runner  →  agents (N frameworks)         │
                 │     │            │                        │
                 │     │            ├─ LLM calls ─┐          │
                 │     │            └─ tool calls ┘          │
                 │     ▼                          ▼          │
                 │  metrics  ◀──  Bifrost gateway (:8080)    │
                 │  (SQLite)      OpenAI-compatible /v1       │
                 └──────────────────┬───────────────────────┘
                                    │  routes + instruments
                      ┌─────────────┼───────────────┐
                      ▼             ▼                ▼
                  OpenAI /      Tavily web      Mocker plugin
                  Azure /       search/extract  (chaos inject)
                  Anthropic     (agent tool)
```

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

```bash
# 1. Start Bifrost (no Docker needed) — opens gateway + UI on :8080
npx -y @maximhq/bifrost

# 2. In the Bifrost UI (http://localhost:8080): add a provider key and
#    create a virtual key (sk-bf-...). For mock-only runs you can skip this.

# 3. Set up Gauntlet
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in BIFROST_VIRTUAL_KEY + TAVILY_API_KEY

# 4. Run the benchmark
python -m gauntlet.run --agents all --runs 3

# 5. Open the dashboard
streamlit run dashboard/app.py
```

## Status

🚧 Active build (hackathon, deadline **15 Nov 2026**). Verified working so far:
Bifrost boots via `npx` and routes OpenAI-format requests on this machine;
Python 3.11 env with all deps installed. Harness code lands next.

## Tech

Python 3.11 · [Bifrost](https://github.com/maximhq/bifrost) (Apache-2.0 AI
gateway) · [Tavily](https://tavily.com) (web layer) · Streamlit · OpenAI SDK.

## License

MIT (see [`LICENSE`](LICENSE)).
