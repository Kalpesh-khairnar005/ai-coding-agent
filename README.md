# AI Coding Agent

**Understand • Plan • Modify • Test** — a small agentic coding assistant that takes a natural-language task, explores a codebase with tools, plans, patches the code, shows a diff, and runs the tests.

**Deployed app:** `<paste your live URL here>`  |  **Repository:** `<paste your GitHub URL here>`

## Overview

A developer types a request such as *"Add validation so age cannot be negative and write a test for it."* The agent explores a sandboxed copy of a sample project, selects and justifies the relevant files, shows a plan, applies validated patches, runs the test suite, and explains the result. The LLM decides *what* to do; deterministic tools do the reading, patching, diffing and testing.

## Problem Statement

Build and deploy an AI coding agent that understands a codebase, accepts a developer task, makes or proposes changes, and shows the result clearly (see the assignment brief).

## Features

- Streamlit UI: stage checklist, plan, relevant files with reasons, unified diff, before/after, test results, final explanation, tool trace
- LLM-driven exploration loop (`search_code` / `read_file` / `list_files`) rather than dumping the repo into a prompt
- Patch-based edits (exact search/replace, must match once, Python syntax-checked before writing)
- Real test execution with a bounded self-repair loop (max 3 attempts)
- Truthful reporting: the pass/fail verdict comes from the test runner, never from the LLM
- The plan and relevant files appear **live while the agent runs**, before any file is changed
- Patch rejections are fed back to the model for a bounded retry (the model is told *why* an edit failed)
- Downloadable `.patch` file of the final diff
- Workspace sandbox: edits happen in a temporary copy; the original project is never modified
- Provider-agnostic (any OpenAI-compatible API) plus an **offline demo mode** that needs no key

## Architecture

```
User → Streamlit UI (app.py)
         │
         ▼
   run_agent()  ── agent/graph.py (nodes + conditional edges)
         │
 analyze_task → inspect_codebase → select_relevant_files → create_plan
         → generate_changes → apply_changes → run_validation ─┐
                                   ▲                          │ tests failed and attempts < 3
                                   └──────── repair ──────────┘
         → generate_summary → UI

 Tools (tools/)  ←→  Workspace boundary (core/security.py)  ←→  Sandbox copy of the project
 LLM (core/llm.py, OpenAI-compatible)  |  Offline demo provider (agent/mock_llm.py)
```

## Agent Workflow

| Node | What happens |
|---|---|
| `analyze_task` | LLM restates the task and proposes search keywords |
| `inspect_codebase` | `list_files`, then an LLM tool loop (`search_code`, `read_file`) under a step and context budget |
| `select_relevant_files` | LLM picks files **with a reason each**; paths are validated against the real file list |
| `create_plan` | LLM writes an ordered plan, shown in the UI before any change is applied |
| `generate_changes` | LLM proposes minimal edits using current file contents (and prior test output when repairing) |
| `apply_changes` | `apply_patch` validates and writes each edit; bad or unsafe edits are rejected and shown |
| `run_validation` | `run_tests`; on failure, loops back to `generate_changes` up to 3 times (also retried when every edit was rejected) |
| `generate_summary` | `generate_diff`, the LLM's explanation, and a tool-derived validation line |

If nothing could be applied, the agent reports **"no changes"** and does not run tests or claim success.

## Tools

`list_files`, `read_file`, `search_code`, `write_file`, `apply_patch`, `generate_diff`, `run_tests` (in `tools/`). All go through `Workspace.resolve()`.

## Tech Stack

Python 3.11+, Streamlit, `requests` (OpenAI-compatible HTTP), `python-dotenv`, pytest, `difflib`. A small custom graph runner is used instead of LangGraph: the flow is linear with one conditional edge, so the extra dependency would add weight without adding capability.

## Project Structure

```
app.py                  Streamlit UI
agent/                  graph.py, state.py, prompts.py, mock_llm.py, nodes/{analyzer,inspector,planner,coder,validator,summarizer}.py
tools/                  filesystem.py, search.py, patch.py, diff.py, testing.py
core/                   config.py, security.py, llm.py, logging.py, errors.py
sample_project/         target codebase (Users API, standard library only)
tests/                  test_security.py, test_tools.py, test_agent.py
```

## Installation

```bash
git clone <your-repo-url> ai-coding-agent && cd ai-coding-agent
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then edit .env
```

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `LLM_API_KEY` | API key for the provider (required for real LLM mode) | — |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |
| `LLM_BASE_URL` | Any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Ollama `http://localhost:11434/v1`, …) | `https://api.openai.com/v1` |
| `MAX_REPAIR_ATTEMPTS` | Auto-repair attempts (capped at 3) | `3` |
| `TEST_TIMEOUT` | Seconds before a test run is stopped | `60` |
| `MAX_RUNS_PER_SESSION` | Runs per browser session when the shared server key is used (protects a public deployment) | `5` |
| `ALLOW_CUSTOM_PROJECT` | Show a "custom local path" option (keep `false` when deployed) | `false` |

A real LLM provider may be paid; this repository contains no keys. Without a key the app shows a clear message and offers **Offline demo** mode.

## Running Locally

```bash
streamlit run app.py
```

## Example Usage

1. Open the app, click **✨ Demo task**, then **▶ Run agent**.
2. Watch the stages complete, then browse the **Plan**, **Code changes**, **Test results** and **Final explanation** tabs.

## Demo Tasks

> Add validation so age cannot be negative and write a test for it.  → edits `app/models.py` and `tests/test_api.py`; suite goes from 5 to 8 passing tests.

> Add input validation to this API and write a test for it.  *(the example from the assignment brief)* → email-shape and name-length validation plus tests; suite goes from 5 to 7 passing tests.

**Offline demo mode is a scripted stand-in, not an LLM.** The tools and test runs are real, but the reasoning is scripted and only supports these two tasks. For any other task, use a real provider (any OpenAI-compatible endpoint; Groq and OpenRouter have free tiers).

## Testing

```bash
pytest -q
```

43 tests cover path security (traversal, absolute paths, symlinks, secrets), file listing/reading, search, patching, the unsafe-code policy, diff generation, test execution (pass, fail, timeout, secret isolation), the LLM client, and the full agent workflow including failure paths, rejected-patch retry and the bounded repair loop. `tests/test_llm_http.py` runs a complete agent task through the real HTTP client against a local fake OpenAI-compatible server, so the provider code path is exercised without an API key. If pytest is not installed, the agent falls back to `python -m unittest` for the project under test and reports the command it actually used.

## Deployment

**Streamlit Community Cloud**

1. Push this repository to GitHub (`.env` is git-ignored).
2. Open https://share.streamlit.io and sign in with GitHub.
3. Click **New app** and select the repository and branch.
4. Set **Main file path** to `app.py` (Advanced settings → Python 3.11 or newer).
5. In **Advanced settings → Secrets**, add:
   ```toml
   LLM_API_KEY = "your-key"
   LLM_MODEL = "gpt-4o-mini"
   LLM_BASE_URL = "https://api.openai.com/v1"
   ```
6. Click **Deploy**.

**Docker (Render, Railway, Hugging Face Spaces)** — a `Dockerfile` is included (listens on `$PORT`, default 7860; on Spaces choose the Docker SDK and set `app_port: 7860`). It has not been built in the authoring environment, so build it once before relying on it.

Without any key configured, the deployed app still works: visitors can use **Offline demo** mode. If you set `LLM_API_KEY` as a secret, each visitor session is capped by `MAX_RUNS_PER_SESSION`.

## Security Considerations

- Every path is validated against a workspace root: `..`, absolute paths, symlink escapes, `.git`/venv dirs, `.env`, key files and anything named like secrets/credentials are rejected.
- The agent edits a temp **copy** of the project; the original is never touched.
- Tests run in a subprocess with a minimal environment, so API keys are not visible to code under test.
- Test commands come from a fixed allowlist; the LLM cannot run arbitrary shell commands.
- Code written by the LLM is parsed (AST) before it is written: imports such as `subprocess`/`socket`/`requests` and calls such as `eval`/`exec`/`os.system` are rejected, because the test run would otherwise execute them. This is defence in depth, **not** a sandbox.
- File contents and test output are marked as untrusted data in the system prompt, and model/file-derived text is rendered with markdown links/images neutralised in the UI.
- A per-session run cap protects a publicly shared API key.
- Logs redact API keys and bearer tokens; file contents are not logged.
- Limitation: running a project's tests executes its code, and the AST policy can be bypassed by determined obfuscation. Only use trusted projects, and prefer a container/VM for untrusted ones.

## Approach (short)

The LLM never touches the disk. It only *chooses* tool calls and *proposes* edits; deterministic tools read, search, patch, diff and run tests inside a sandbox copy. Each step has a validation gate (paths, exact-match patches, syntax and safety checks, real test results), and the final verdict is computed from the test runner rather than the model's own claims.

## Assumptions

- Target projects are Python and have tests that run with pytest or unittest.
- The LLM can return JSON (JSON mode is used when the provider supports it).
- The sample project is standard-library only so it runs anywhere; the agent itself is not tied to any web framework.

## Limitations

- Edits require the model to quote exact existing text; large or highly repetitive files can cause rejected patches (the agent then reports it).
- Context is limited (40k chars of gathered file content, 12k per file in the coding step); very large repositories are only partially visible.
- Only text/source file types are supported; no dependency installation and no network access for the project under test.
- The offline provider cannot repair failures or handle tasks other than its two scripted ones.
- The real-LLM path was verified against a local fake OpenAI-compatible server, not a live model; output quality and JSON reliability vary by model.
- The UI was exercised with Streamlit's `AppTest` harness (no browser); do a quick visual check after deploying.

## Future Improvements

- Tool-calling API (native function calling) instead of JSON action messages
- Streaming progress of LLM output
- Per-language test runners, container-based sandboxing, embedding-based file retrieval for large repos

## Author

Your Name — replace before submitting.
