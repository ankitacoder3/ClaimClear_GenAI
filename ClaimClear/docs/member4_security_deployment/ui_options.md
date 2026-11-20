# ClaimClear chat UI: options analysis

**Author:** Mithun Dhali (Member 4: control, security and deployment) · **Date:** 20 Nov 2026

Goal: use a **standard, configurable chat interface** in front of the existing agent graph, instead of building and
maintaining our own front end. The UI is only an interface: it calls the graph (plan, specialists, critic loop,
approval gate) and the MCP servers that already exist.

## Selected: Chainlit (inside FastAPI)

Chainlit covers every must-have with the least code of our own, stays in Python, runs inside FastAPI as the course
asks, and calls the existing agent graph as a library through a thin adapter. Details (adapter design, upload flow,
pauses, theming, deployment) to follow.

```
FastAPI app (one process)
├── /chat         Chainlit UI ── adapter ──► agent graph ──► toolkit ──► 5 MCP servers
├── /api/upload   upload → case records (also accepts a policy wording on its own)
├── /health       for Docker
└── /metrics      Prometheus (cost, latency, errors, rupees deducted by reason)
```

## Requirements

| # | Requirement | Must / nice | Notes |
|---|---|---|---|
| R1 | Chat interface | must | conversation view, streaming replies |
| R2 | Upload files in the chat | must | bill, settlement letter, policy schedule, policy wording (PDF / image); also a wording or a single document on its own |
| R3 | Ask free-form questions | must | about the claim or the policy, with the case's documents as context |
| R4 | Ask the user and wait for the answer | must | approve / reject the grievance draft, answer the engine's questions. **A dedicated button is not required**: suggestion chips ("Approve", "Don't file") or a typed reply are enough |
| R5 | Show the agents' progress | nice | each step the graph takes, collapsible |
| R6 | Show results clearly | must | verdict table per deduction, amounts, clause citations (markdown table is fine) |
| R7 | Little custom code | must | configure and theme rather than write a front end; Python preferred (the team's language) |
| R8 | Fits the course stack | must | FastAPI service with streaming, Docker Compose, metrics, guardrails, login if needed |

## Comparison

| | Chainlit | LangChain Agent Chat UI | Gradio |
|---|---|---|---|
| What it is | Python framework for LLM / agent chat apps | LangChain's open-source chat app for LangGraph agents | Python library for quick ML / LLM web UIs |
| Language | Python | TypeScript (Next.js) | Python |
| Chat with streaming (R1) | yes | yes | yes |
| Upload files in chat (R2) | yes | yes (PDF, images) | yes |
| Free-form questions (R3) | yes | yes | yes |
| Ask and wait, approval (R4) | yes: actions, chips or typed reply | yes: built-in interrupts | yes: chips or typed reply; we manage pause / resume |
| Agent steps (R5) | built in (Steps) | built in | partial ("thoughts" metadata) |
| Verdict table (R6) | markdown table | markdown / custom | markdown table |
| Custom code we maintain (R7) | low: ~200-line adapter | medium: reshape graph or adapter graph | medium: more glue for pauses |
| FastAPI / course stack (R8) | mounts inside FastAPI; course-listed | separate Node app + LangGraph server | runs with FastAPI; course-listed |
| Login, chat history | built in (optional) | via LangGraph server | partial |
| Fits our graph as-is | yes, thin adapter | needs reshaping (`messages` state, HumanInterrupt pauses) | yes, more glue |
| Maturity | community-maintained since May 2025, active releases | official LangChain project | widely used, actively developed |

Also looked at and dropped: the **current hand-written page** (works, but is custom code we would keep extending)
and **Open WebUI** (a complete ChatGPT-style product whose uploads and flow are built around chatting with a model,
not around our case store and agent pipeline).

## The options in brief

### Chainlit (Python)

**Why it's good:** made specifically for LLM and agent chat apps; a few decorators give a complete chat UI; runs
inside a FastAPI app; listed by the course guide.

- **Pros:** file upload, streaming, collapsible agent **Steps**, actions / chips and prompts that wait for an answer
  (`AskUserMessage`, `AskActionMessage`, `AskFileMessage`) all built in; calls the graph in-process with no change
  to it; configured via `config.toml` (name, theme, features), optional login and history; Python only.
- **Cons:** community-maintained since May 2025 (releases continue, 2.12 on PyPI, but no company behind it); deep
  visual changes need custom CSS / JS; a thin adapter (~200 lines) is ours.

### LangChain Agent Chat UI (Next.js)

**Why it's good:** LangChain's own front end for LangGraph agents; understands LangGraph pauses (human-in-the-loop)
natively.

- **Pros:** built-in interrupts and approvals, PDF and image uploads, official and LangGraph-native, polished look.
- **Cons:** TypeScript and a Node build pipeline; expects the graph behind a LangGraph server with a `messages`
  state and "HumanInterrupt" pauses, which our graph doesn't use, so it needs reshaping or an adapter graph;
  uploads arrive as message content, not as registered case documents.

### Gradio (Python)

**Why it's good:** the quickest way to put Python behind a web UI; widely used; listed by the course guide.

- **Pros:** pure Python, very little code; `ChatInterface` with file upload and streaming; approval and questions as
  typed replies or example chips; "thoughts" metadata for intermediate steps.
- **Cons:** less suited to long, pausing multi-step agent runs (we manage pause / resume state); feels like a demo
  tool rather than a product UI; limited theming.

## Where FastAPI fits

FastAPI is **not a chat UI**. It is the Python web / API layer: it receives HTTP and WebSocket requests and runs our
code. It is built on Starlette (which the current page already uses) and adds request validation (Pydantic),
automatic API docs at `/docs`, and dependency injection.

**Why use it**
- The course asks for it: "Serve the app through FastAPI with streaming".
- One place for everything around the chat: `/api/upload`, `/health` for Docker, `/metrics` for Prometheus, login,
  and later the hooks' audit endpoints.
- Chainlit mounts inside a FastAPI app (`mount_chainlit`), so the chat UI and the API share one process and port.
- Streaming is standard: `StreamingResponse` with server-sent events (SSE) for any non-chat client.
- Typed request / response models give input validation for free, useful for the guardrails.
- Small migration: existing Starlette routes run in FastAPI almost unchanged.

**Why not (or not alone)**
- On its own it gives no chat interface; it must be paired with a UI.

**Decision:** FastAPI is the outer app whichever UI we pick; the chat UI lives inside it.

## Sources

- Chainlit on PyPI: https://pypi.org/project/chainlit/ ; maintenance note: https://github.com/caltechqi/chainlit
- Chainlit messaging (AskActionMessage, AskFileMessage): https://tessl.io/registry/tessl/pypi-chainlit/files/docs/messaging.md
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts/index.html
- LangChain UI / Agent Chat UI: https://docs.langchain.com/oss/python/ui ; https://context7.com/langchain-ai/agent-chat-ui
- SSE vs WebSockets for LLM streaming: https://render.com/articles/sse-vs-websockets-llm-streaming
- Course guide (UI options, FastAPI with streaming): `capstone_fullstack_projects.pdf`
