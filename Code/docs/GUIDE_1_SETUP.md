---
title: "ClaimClear — Guide 1: Making the code work, step by step"
subtitle: "From the zip file to a running multi-agent audit, on Windows, macOS or Linux"
---

# ClaimClear — Guide 1: Making the code work, step by step

This guide takes you from `ClaimClear_combined.zip` to a working system: first a demo that needs no servers, then the live system with all five MCP servers, then the tests and the full evaluation. Every command here was run on a fresh copy of the zip before this guide was written.

**Time needed:** about 15 minutes, most of it package downloads.

**What you will have at the end:**

* two Python environments, one for the servers and one for the agents;
* the SET-01 settlement audited end to end, with ₹8,522.86 found disputable and a grievance filed (as a dry run) after your approval;
* every test suite run.

---

## Contents

* The short way: one command
* Step 0: what you need
* Step 1: unzip the project
* Step 2: create the servers' environment (`.venv`)
* Step 3: create the agents' environment (`.venv-agents`)
* Step 4: first run, with no servers (offline demo)
* Step 5: check the five MCP servers start
* Step 6: run the live system
* Step 7: try the other paths (clean case, a question, edit or reject)
* Step 8: run the tests
* Step 9: run every development case through the graph
* Step 10 (optional): servers over HTTP, and the approval-gate secret
* Step 11 (optional): use the graph from your own code
* Step 12 (optional): keep paused cases across restarts
* Step 13 (optional): let an LLM read the documents, and explain in another language
* Troubleshooting

---

## The short way: one command

| System | Command (from the `ClaimClear` folder) |
|---|---|
| Windows (CMD) | `start.bat` |
| macOS / Linux | `./start.sh` |
| Any | `python start.py` |

It starts with **any Python 3.8 or newer, including 3.15**. The libraries ClaimClear depends on are published for Python 3.12–3.14 only, so the launcher builds the environments with one of those: your Python if it is one of them, otherwise another one it finds on the machine, otherwise a private copy of Python 3.13 that it downloads into the project's `.python` folder (nothing is installed system-wide). The first run takes a few minutes: it creates both Python environments, installs everything, tries to install Tesseract OCR, loads the development cases and builds the policy index. Later runs skip all that and start in a few seconds. It then starts the five MCP servers in the background.

It then opens **ClaimClear in your browser**: a chat assistant, much like Claude's chat window, for your hospital records and your claim.

* **Attach documents** with the 📎 button or by dropping them on the page: the hospital bill, discharge summary, settlement letter and policy schedule. Or click a sample case.
* **Watch the agents work live** in a collapsible "Checking your claim…" block. Then you get what was found (insurer paid, policy allows, may be disputable, row by row with policy clauses), any question the engine needs answered, and a grievance letter you can edit, approve or decline.
* **Ask anything** about your medical records, the settlement or the policy: "What was my diagnosis?", "Why was R3 deducted?", "Is cataract surgery covered?". Answers stream in as they are written and remember the conversation. Every rupee amount is checked as it streams: if a model writes an amount that isn't in your documents, the audit or the policy, the answer is withdrawn and replaced by a checked one.
* **Everything keeps running in the background until you close the page** (or press *Close ClaimClear*, or Ctrl+C in the terminal). Then the web UI and the five servers stop by themselves. Reloading the page keeps your session.

**Choosing the model.** Two kinds of model are supported: a **local LLM** on this computer, or **OpenRouter**.

**A local LLM is chosen by default.** At every start, `start.py` checks whether one is running: Ollama (port 11434), LM Studio (port 1234) or a llama.cpp server (port 8080). If it finds one, the chat and the document reader use it, so your medical records never leave this computer. The start-up window says which model it picked. Otherwise OpenRouter is used if a key is saved, or no model at all. `--no-local-llm` turns this off for one run.

**Starting a local LLM, with a choice of model.** Run the second launcher:

```bash
start_llm.bat                      # Windows
./start_llm.sh                     # macOS / Linux
```

It finds Ollama, or offers to install it (with `winget` on Windows or `brew` on a Mac; elsewhere it gives the download link). It then starts Ollama in the background and shows a numbered menu: the models you already have, then recommended ones to download:

| Model | Good for | Download |
|---|---|---|
| `llama3.1:8b` | a good all-rounder (about 8 GB of RAM) | 4.9 GB |
| `qwen2.5:7b` | tables and figures (about 8 GB of RAM) | 4.7 GB |
| `mistral:7b` | fast, plain English (about 8 GB of RAM) | 4.1 GB |
| `gemma2:9b` | careful answers, a little slower (about 10 GB of RAM) | 5.4 GB |
| `llama3.2:3b` | older computers (about 4 GB of RAM) | 2.0 GB |

Type a number, or any model name from ollama.com/library. It downloads the model if needed, loads it into memory and saves the choice in `.env`. Then start ClaimClear as usual. Other options:

| Option | What it does |
|---|---|
| `--model qwen2.5:7b` | Use this model without asking (downloaded if needed) |
| `--list` | Show installed and recommended models; change nothing |
| `--start` | Start ClaimClear afterwards (other options are passed on, e.g. `--start --no-browser`) |

If LM Studio or a llama.cpp server is already running and Ollama isn't installed, the menu shows the models loaded there instead.

**Changing the model in the page.** Click the model name at the top right of the page (**⚙ No model configured · set up** when there is none), choose **Local model**, **OpenRouter** (paste your key from openrouter.ai; model names look like `openai/gpt-4.1-mini`) or **No model**, then press **Save and test**. ClaimClear sends the model a one-word test message, and only if it answers does it save the choice and switch to it, with no restart. The key is kept only on this computer, in the `.env` file next to `start.py`, and is never shown again. Choosing OpenRouter or No model here is remembered: later starts no longer switch to a local LLM by themselves (they do again once you run `start_llm` or choose Local model).

| Choice | What you need | Where your records go |
|---|---|---|
| **Local model** (default when running) | `start_llm.bat` / `./start_llm.sh`, or any running Ollama / LM Studio / llama.cpp | **Never leave this computer** |
| **OpenRouter** | An API key from openrouter.ai → Keys | Sent to OpenRouter and the model you chose |
| **No model** | Nothing | Nowhere: answers come from your records, the audit and the policy (rows, amounts, clauses, diagnosis, dates, bill items), but not free-form questions |

If the test fails, the dialog says why (for example *Is the local model running?* or *too little credit*), and nothing is saved. The test asks for a one-word reply, and every answer has a length limit (`CLAIMCLEAR_MAX_TOKENS`, default 1,500 tokens), so a key with a small credit limit works. You can also write the settings into `.env` by hand; see `.env.example`.

**Your data is not kept.** Uploaded documents, chats and dry-run filings exist only while ClaimClear runs. They are deleted when you close the page, and at the next start if ClaimClear was stopped abruptly. A new launch never shows a previous conversation. **🗑 Clear my data** in the sidebar deletes everything at once. To keep data between runs, start with `--keep-data`. The sample cases are synthetic test data that ships with the project.

| Option | What it does |
|---|---|
| `--console` | The terminal console instead of the web page |
| `--no-browser` | Doesn't open the browser; open the printed address yourself |
| `--keep-data` | Keeps uploaded documents, chats and filings after closing (default: deleted) |
| `--no-local-llm` | Doesn't switch to a running local LLM for this run (uses the saved setting) |
| `--auto SET-01` | Runs one case with no prompts, approves, and exits: a self-check |
| `--servers-only` | Just keeps the five servers running (Ctrl+C stops them) |
| `--reinstall` | Rebuilds both environments |
| `--download-python` | Always builds the environments with the private downloaded Python 3.13 |

The steps below do the same things by hand, one at a time. Follow them if you want to understand the set-up, run the tests, or if the one-command start fails.

---

## Step 0: what you need

| Tool | Version | Why | How to get it |
|---|---|---|---|
| Python | 3.12, 3.13 or 3.14 for the manual steps (3.12 and 3.13 tested). **Not 3.15 yet:** several libraries have no 3.15 builds, so installation fails. On 3.15, use the one-command start above, which fetches a suitable Python by itself | everything is Python | python.org, or your package manager |
| Tesseract OCR | 5.x | reads scanned bills and photos | Windows: `winget install --id UB-Mannheim.TesseractOCR -e` · macOS: `brew install tesseract` · Ubuntu/Debian: `sudo apt-get install tesseract-ocr tesseract-ocr-eng` |
| Disk space | about 1.5 GB | the two environments | — |
| Internet | while installing | to download packages | — |

Tesseract is strongly recommended. Without it, any scanned page is reported **unreadable** and the system asks for a better copy instead of guessing. That is the correct, safe behaviour, but it means the cases with scanned bills (SET-32, SET-22, SET-05) stop early.

Check that the tools work:

```bash
python --version
```

```bash
tesseract --version
```

On macOS and Linux, use `python3` wherever this guide says `python` if `python` is not found.

> **Command conventions.** This guide shows macOS / Linux paths (`.venv/bin/python`). On **Windows** (PowerShell or cmd) use `.venv\Scripts\python.exe` instead of `.venv/bin/python`, and `.venv-agents\Scripts\python.exe` instead of `.venv-agents/bin/python`. Everything else is the same.

---

## Step 1: unzip the project

Unzip `ClaimClear_combined.zip` anywhere, then open a terminal in the `ClaimClear` folder it creates:

```bash
cd ClaimClear
```

You should see these folders: `agents`, `servers`, `contracts`, `memory`, `data`, `eval`, `docs`, `scripts`, `deploy`. **Run every command in this guide from this folder** unless the step says otherwise.

---

## Step 2: create the servers' environment (`.venv`)

ClaimClear needs **two** separate Python environments. The servers use `mcp` 2.3, while the agents' MCP client library (`langchain-mcp-adapters`) needs `mcp` 1.x. They can't share one environment, so the agents start the servers as separate processes using the servers' own Python.

**2a.** Create the environment:

```bash
python -m venv .venv
```

**2b.** Install the servers' packages:

```bash
.venv/bin/python -m pip install -r requirements-servers.txt
```

**2c.** Install the five servers, the contracts and memory into it:

```bash
.venv/bin/python -m pip install -e servers/settlement_engine -e servers/case_records -e servers/policy_kb -e servers/insurer_portal -e servers/document_reader -e contracts -e memory
```

**Check:** the last line printed should start with `Successfully installed`.

> The folder name `.venv` matters: the agents look for the servers' Python at `ClaimClear/.venv`. If you put it elsewhere, set `CLAIMCLEAR_SERVER_PYTHON` to its `python` (see Troubleshooting).

---

## Step 3: create the agents' environment (`.venv-agents`)

**3a.** Create it:

```bash
python -m venv .venv-agents
```

**3b.** Install everything the agents need. This includes the toolkit, the contracts, memory, the multi-agent graph (`claimclear_graph`), LangGraph and the MCP adapters:

```bash
.venv-agents/bin/python -m pip install -r requirements-agents.txt
```

**Check:**

```bash
.venv-agents/bin/python -c "import claimclear_graph, claimclear_tools, langgraph; print('agents ready')"
```

It should print `agents ready`.

---

## Step 4: first run, a self-check

```bash
python start.py --auto SET-01
```

This starts the five servers, runs the SET-01 settlement through every agent with no questions asked, approves the grievance, files it to the **dry-run** portal (nothing is sent anywhere), and stops everything. It ends with:

```
=== Outcome: grievance_filed ===
    reference DRYRUN-62EA010D9B82 (dry_run: nothing was sent to an insurer)
[start] servers stopped
```

If you see `Outcome: grievance_filed`, both environments, the servers and the agents all work.

> On Windows, if the ₹ sign prints as `?`, `start.bat` already switches the window to UTF-8; with `python start.py` run `set PYTHONIOENCODING=utf-8` first.

---

## Step 5: check the five MCP servers start

```bash
.venv/bin/python scripts/dev_servers.py --check
```

This starts each server over HTTP, checks that it answers, and stops it. Among the log lines you should see:

```
settlement-engine  http://127.0.0.1:8101/mcp   up
case-records       http://127.0.0.1:8102/mcp   up
policy-kb          http://127.0.0.1:8103/mcp   up
insurer-portal     http://127.0.0.1:8104/mcp   up
document-reader    http://127.0.0.1:8105/mcp   up
```

All five `up` means the servers' environment is complete. If one says `down`, see Troubleshooting.

---

## Step 6: run the live system

```bash
python start.py
```

The browser opens ClaimClear. Click a sample case or attach your own documents, watch the agents work, ask questions, and approve or decline the grievance. Close the page when you are done: the servers stop by themselves.

---

## Step 7: try the other paths

| Command | What happens |
|---|---|
| `python start.py --auto SET-02` | A clean settlement: every deduction matches the policy, `Outcome: no_grievance` |
| `python start.py --auto SET-32` | The engine needs to know the type of condition; the self-check answers `illness` and the audit continues (needs Tesseract) |
| `python start.py --console` | The same as the web UI, in the terminal: pick a case, answer, then approve, edit or reject |

---

## Step 8: run the tests

**The multi-agent graph, every agent and the web UI** (480 tests, about 85 seconds; details in `agents/orchestration/TESTING.md`):

```bash
cd agents/orchestration
```

```bash
../../.venv-agents/bin/python -m pytest -o addopts=""
```

```bash
cd ../..
```

Expected: `479 passed, 1 skipped` (the skipped one needs PostgreSQL).

**The agents' toolkit** (45 tests, live):

```bash
cd agents/toolkit
```

```bash
../../.venv-agents/bin/python -m pytest -o addopts=""
```

```bash
cd ../..
```

**A server suite**, for example the insurer portal (repeat for `servers/settlement_engine`, `servers/policy_kb`, `servers/case_records`, `servers/document_reader`):

```bash
cd servers/insurer_portal
```

```bash
../../.venv/bin/python -m pytest -o addopts=""
```

```bash
cd ../..
```

**Memory and contracts** (one folder level, so `../.venv`):

```bash
cd memory
```

```bash
../.venv/bin/python -m pytest -o addopts=""
```

```bash
cd ..
```

**Expected results:**

| Suite | Expected |
|---|---|
| agents/orchestration | 479 passed, 1 skipped |
| agents/toolkit | 45 passed |
| servers/policy_kb | 110 passed, 5 skipped |
| servers/insurer_portal | 13 passed |
| memory | 49 passed, 42 skipped (the skipped ones need PostgreSQL) |
| contracts | 22 passed |
| servers/settlement_engine | 315 passed, 6 skipped |
| servers/document_reader | 69 passed, 11 skipped |
| servers/case_records | 25 passed, 34 skipped |

The skipped tests in the last three rows read the **held-out split** (`data/dataset/heldout/`), which is not in this zip; pytest shows the reason "needs the held-out split". Three of the case-records skips need PostgreSQL. Copy `data/dataset/heldout` in from the original repository and the held-out tests run again.

---

## Step 9: run every development case through the graph

```bash
.venv-agents/bin/python eval/graph_dev_cases/run.py
```

This runs all 42 development cases through the multi-agent graph against the live servers (about 30 seconds) and scores them against their answer files. It writes `eval/graph_dev_cases/results/graph_dev_cases.md`, which should begin:

| Cases | Ran to the end (audit produced) | Overall verdict right | Row verdicts right | Payable right (±₹1) | Disputable right (±₹1) | Same overall verdict as C0 |
|---|---|---|---|---|---|---|
| 42 | 41 | 34/42 | 88/94 | 26/30 | 34/38 | 42/42 |

No person is present during this run, so the engine's questions are left unanswered and every grievance is **rejected** at the gate. Nothing is filed.

To compare, run Member 2's fixed (non-agent) workflow on the same cases:

```bash
.venv-agents/bin/python eval/dev_cases/run.py
```

---

## Step 10 (optional): servers over HTTP, and the approval-gate secret

By default the agents start the servers themselves (stdio). To run the servers once and connect to them, which is how Docker would do it:

**Terminal 1**, start all five and leave them running:

```bash
.venv/bin/python scripts/dev_servers.py
```

**Terminal 2**, point the agents at them:

```bash
export CLAIMCLEAR_MCP_MODE=http
```

On Windows PowerShell: `$env:CLAIMCLEAR_MCP_MODE="http"`. Then run any agent command, for example:

```bash
.venv-agents/bin/python eval/graph_dev_cases/run.py --http
```

In HTTP mode the servers use their default data locations under `var/`. Fill them once (Member 2's steps):

```bash
cd servers/case_records
```

```bash
../../.venv/bin/python -m case_records.register_dataset --split dev
```

```bash
cd ../policy_kb
```

```bash
../../.venv/bin/python -m policy_kb build --wording ../../data/wordings/policy-wordings-arogya-sanjeevani-policy-go-digit.pdf
```

```bash
cd ../..
```

**The approval-gate secret.** Set the same secret in the terminal that runs the servers **and** the one that runs the agents:

```bash
export CLAIMCLEAR_GATE_SECRET="choose-a-long-random-value"
```

The insurer portal then accepts only approval tokens the gate issued for that exact text (an HMAC of its SHA-256). Without it, the portal checks only that a token is present, which is fine for development but not for production.

---

## Step 11 (optional): use the graph from your own code

```python
import asyncio
from claimclear_tools import ClaimClearToolkit
from claimclear_graph import Services, build_claimclear_graph, initial_state, HumanApprovalGateway

async def audit(case_id: str, claim: dict, letter: dict):
    async with ClaimClearToolkit() as tk:                      # starts / connects to the servers
        graph = build_claimclear_graph(Services(toolkit=tk))
        cfg = {"configurable": {"thread_id": case_id}}         # one thread per case
        state = await graph.ainvoke(initial_state(case_id, claim=claim, letter=letter), cfg)
        gate = HumanApprovalGateway(graph)
        if await gate.pending_questions(cfg):                 # the engine needs an answer
            state = await gate.answer_questions(cfg, {"Q-CONDITION-TYPE": "illness"})
        if await gate.is_paused_for_approval(cfg):             # a grievance is ready
            text, sha = await gate.get_pending_grievance(cfg)  # show `text` to the user
            state = await gate.approve_and_resume(cfg)         # or edited_text=..., or gate.reject(cfg)
        return state["outcome"], state.get("explanation")
```

* `case_id` comes from the case-records store (the app's upload step).
* `claim` and `letter` are the settlement engine's `ClaimIn` and `LetterIn` shapes. Alternatively, pass `Services(toolkit=tk, extractor=llm_extractor(your_chat_model))` (from `claimclear_graph.extraction`) to have the document reader extract them from the documents.
* Add `memory_store=MemoryStore()` (from `claimclear_memory`) and `user_id=...` to remember verified claims. This needs the user's consent: `MemoryStore().for_user(user_id).grant_consent("app")`.

---

## Step 12 (optional): keep paused cases across restarts

A case can wait at a question or at the approval gate for days. By default the graph keeps its state in memory, so a paused case is lost when the app restarts. To store it on disk, set:

```bash
export CLAIMCLEAR_CHECKPOINTS="sqlite:///var/graph/checkpoints.db"
```

Then open the store in your code. Rebuild the graph on the same file after a restart and the gateway finds the case where it was left (same `thread_id`):

```python
from claimclear_graph import open_checkpointer

async with open_checkpointer() as saver:          # reads CLAIMCLEAR_CHECKPOINTS
    graph = build_claimclear_graph(Services(toolkit=tk), checkpointer=saver)
```

For PostgreSQL, install `langgraph-checkpoint-postgres` into `.venv-agents` and use `postgresql://user:password@host/db`.

---

## Step 13 (optional): let an LLM read the documents, and explain in another language

Both use the same model as the chat: a local LLM (start one with `start_llm`), or OpenRouter with a key in `.env` (copy `.env.example`) or exported:

```bash
export OPENROUTER_API_KEY="your-key"
```

**Measure how well the LLM reads the documents.** Every dev case goes through the graph with the LLM extracting the bill and the letter (the stand-in values are withheld). Each extraction is then compared with the stand-in:

```bash
.venv-agents/bin/python eval/graph_dev_cases/run.py --llm-extract
```

The results go to `eval/graph_dev_cases/results/graph_dev_cases_llm.md`. The model is the chat model; change it with `CLAIMCLEAR_EXTRACTION_MODEL`.

**Explain in plain language or another language.** In your code:

```python
from claimclear_graph.chat import chat_model_from_env
from claimclear_graph.language import llm_rewriter

llm = chat_model_from_env()          # the local LLM, else OpenRouter (as in the web UI)
services = Services(toolkit=tk, rewriter=llm_rewriter(llm), language="hi")   # en, hi, mr, ta, te, bn, kn, gu
```

The critic checks the rewritten text. If the model changes, rounds or invents a single ₹ amount, the user gets the plain verdict table instead.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Model settings: *Error code: 402 … requires more credits, or fewer max_tokens* | Older ClaimClear versions sent no reply limit, so the provider reserved the model's whole maximum (65,536 tokens) against your credit limit | Fixed: update to this version. If it still appears, add credit with the provider, raise the key's credit limit, or set `CLAIMCLEAR_MAX_TOKENS=800` in `.env` |
| Installation fails on Python 3.15 (errors building `pydantic-core`, `PyYAML`, `pymupdf` or similar) | Those libraries are not published for 3.15 yet | Use `start.bat` / `./start.sh`: it works from any Python and builds the environments with Python 3.12–3.14, downloading one if needed. If an environment was already half-built with 3.15, the launcher replaces it |
| `server virtual environment not found under …/.venv` | The agents can't find the servers' Python | Create `.venv` in the `ClaimClear` folder (Step 2), or set `CLAIMCLEAR_SERVER_PYTHON` to the full path of the servers' `python` |
| `ClaimClear repository not found; set CLAIMCLEAR_REPO` | Running from outside the project | `cd` into `ClaimClear`, or set `CLAIMCLEAR_REPO` to its full path |
| pip error mentioning `mcp` versions | Both requirement files installed into one environment | Delete the environment and follow Steps 2 and 3 exactly: two environments |
| `Outcome: missing_document` and `unreadable pages` | Tesseract isn't installed or isn't on the PATH | Install it (Step 0); check `tesseract --version` |
| A server shows `down` in Step 5 | Port 8101–8105 already in use, or the servers' install was incomplete | Close whatever uses the port; re-run Step 2c |
| `UnicodeEncodeError` or `?` instead of ₹ (Windows) | Console encoding | Set `PYTHONIOENCODING=utf-8` |
| `PermissionError: insurer portal refused the filing: APPROVAL_REQUIRED` | The gate secret differs between the agents and the portal server | Use the same `CLAIMCLEAR_GATE_SECRET` in both terminals |
| Server tests are *skipped* with "needs the held-out split" | The held-out split isn't in the zip | Expected: see the table in Step 8 |
| `pytest` prints only dots and no totals | The project sets `addopts = -q` | Add `-o addopts=""`, as in this guide |
| Offline demo: `no recorded result for …` | The code now makes a call the recording doesn't have | Re-record: `.venv-agents/bin/python agents/orchestration/examples/record_fixtures.py` |

**Where next:** [Guide 2](GUIDE_2_CODE_WALKTHROUGH.md) explains what every part of the code does and walks through a simple and a complex case step by step.
