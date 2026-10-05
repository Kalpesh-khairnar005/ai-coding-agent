"""AI Coding Agent - Streamlit UI."""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from agent.graph import run_agent
from agent.mock_llm import MockLLM
from agent.state import AgentState
from core.config import DEMO_TASK, SAMPLE_PROJECT, load_settings
from core.errors import AgentError
from core.llm import OpenAICompatibleClient
from core.logging import get_logger, register_secret
from core.security import Workspace
from tools import copy_project

log = get_logger("ui")
ICONS = {"pending": "⚪", "running": "⏳", "done": "✅", "failed": "❌", "skipped": "➖"}
PROVIDER_API, PROVIDER_MOCK = "OpenAI-compatible API", "Offline demo (scripted, no LLM)"

st.set_page_config(page_title="AI Coding Agent", page_icon="🤖", layout="wide")
st.markdown(
    "<style>.block-container{padding-top:2rem;max-width:1200px}"
    ".subtitle{color:#8b949e;font-size:1.1rem;margin-top:-0.8rem;margin-bottom:1rem}</style>",
    unsafe_allow_html=True,
)


# ---------- workspace (isolated sandbox copy; the original project is never modified) ----------
def reset_workspace(source: Path) -> None:
    old = st.session_state.get("ws_root")
    if old:
        shutil.rmtree(old, ignore_errors=True)
    root = Path(tempfile.mkdtemp(prefix="aicoder_"))
    copy_project(source, root)
    st.session_state.update(ws_root=str(root), ws_source=str(source), result=None)


def plain(text: object) -> str:
    """Neutralise markdown links/images in model- or file-derived text (blocks image-URL data exfiltration)."""
    return re.sub(r"([!\[\]])", r"\\\1", str(text))


def render_stages(state: AgentState, placeholder) -> None:
    """Live progress panel: stage checklist, and the plan as soon as it exists (before any code is changed)."""
    lines = []
    for s in state.stages:
        detail = f" — _{plain(s['detail'])}_" if s["detail"] else ""
        lines.append(f"{ICONS[s['status']]} **{s['label']}**{detail}")
    text = "\n\n".join(lines)
    if state.plan and state.status == "running":
        text += "\n\n---\n**Plan** (shown before changes are applied)\n\n" + "\n".join(
            f"{i}. {plain(step)}" for i, step in enumerate(state.plan, 1))
        if state.relevant_files:
            text += "\n\n**Relevant files:** " + ", ".join(f"`{e['path']}`" for e in state.relevant_files)
    placeholder.markdown(text)


# ---------- result panels ----------
def render_plan(state: AgentState) -> None:
    st.markdown("#### Task understanding")
    st.info(plain(state.task_understanding) or "—")
    st.markdown("#### Implementation plan")
    for i, step in enumerate(state.plan, 1):
        st.markdown(f"{i}. {plain(step)}")
    st.markdown("#### Relevant files")
    for item in state.relevant_files:
        st.markdown(f"**`{item['path']}`**  \n{plain(item['reason'])}")


def render_changes(state: AgentState, ws_root: str) -> None:
    if not state.files_changed:
        st.warning("No files were changed.")
    else:
        st.markdown("**Files changed:**")
        for path in state.files_changed:
            st.markdown(f"- `{path}`")
        st.markdown("#### Unified diff")
        st.code(state.diff, language="diff")
        st.download_button("⬇ Download patch (.patch)", state.diff, file_name="agent_changes.patch", mime="text/x-diff")
        st.markdown("#### Before / after")
        for path in state.files_changed:
            with st.expander(path):
                before, after = st.columns(2)
                old = state.originals.get(path)
                try:
                    new = (Path(ws_root) / path).read_text(encoding="utf-8")
                except OSError:
                    new = "(unreadable)"
                before.caption("Before")
                before.code(old if old is not None else "(new file)", language="python")
                after.caption("After")
                after.code(new, language="python")
    rejected = [c for c in state.changes if c["status"] != "applied"]
    for c in rejected:
        st.error(f"Rejected change to `{c['file']}` (attempt {c['attempt'] + 1}): {plain(c['error'])}")


def render_tests(state: AgentState) -> None:
    if not state.test_runs:
        st.warning("Tests were not run because no change was applied.")
        return
    last = state.test_runs[-1]
    label = {"passed": "✅ PASSED", "failed": "❌ FAILED", "no_tests": "⚠️ NO TESTS FOUND",
             "timeout": "⏱️ TIMED OUT", "error": "❌ COULD NOT RUN"}[last["status"]]
    st.markdown(f"**Command:** `{last['command']}`   |   **Result:** {label}")
    cols = st.columns(4)
    cols[0].metric("Passed", last["passed"])
    cols[1].metric("Failed", last["failed"])
    cols[2].metric("Errors", last["errors"])
    cols[3].metric("Duration", f"{last['duration']}s")
    st.code(last["output"] or "(no output)", language="text")
    if len(state.test_runs) > 1:
        with st.expander(f"All test runs ({len(state.test_runs)}) — automatic repair attempts: {state.repair_attempts}"):
            for i, run in enumerate(state.test_runs, 1):
                st.markdown(f"**Run {i}** — {run['status']} ({run['passed']} passed, {run['failed']} failed)")
                st.code(run["output"][-1500:], language="text")


def render_summary(state: AgentState) -> None:
    s = state.summary
    if not s:
        st.warning("No summary was produced.")
        return
    st.markdown("#### What changed")
    st.write(plain(s["what_changed"]) or "—")
    st.markdown("#### Why")
    st.write(plain(s["why"]) or "—")
    st.markdown("#### Files modified")
    st.write(", ".join(f"`{p}`" for p in s["files_modified"]) or "None")
    st.markdown("#### Tests added")
    st.write("\n".join(f"- `{plain(t)}`" for t in s["tests_added"]) or "None reported")
    st.markdown("#### Validation result")
    st.markdown(s["validation"])
    st.markdown("#### Limitations")
    st.write("\n".join(f"- {plain(t)}" for t in s["limitations"]) or "None reported")


def render_result(state: AgentState, ws_root: str) -> None:
    banner = {
        "success": st.success, "failed": st.error, "no_changes": st.warning, "error": st.error,
    }.get(state.status, st.info)
    headline = {
        "success": "Done — changes applied and the test suite passes.",
        "failed": "Changes were applied, but the tests FAILED. Review the output before using this patch.",
        "no_changes": "The agent finished without applying any changes.",
        "error": "The agent stopped because of an error.",
    }.get(state.status, state.status)
    banner(headline)
    for err in state.errors:
        st.error(plain(err))
    tabs = st.tabs(["📋 Plan", "🧩 Code changes", "🧪 Test results", "📝 Final explanation", "🔧 Tool trace"])
    with tabs[0]:
        render_plan(state)
    with tabs[1]:
        render_changes(state, ws_root)
    with tabs[2]:
        render_tests(state)
    with tabs[3]:
        render_summary(state)
    with tabs[4]:
        st.caption("Every tool call the agent made, in order.")
        for i, call in enumerate(state.tool_trace, 1):
            st.markdown(f"{i}. `{call['tool']}` {plain(call['args'] or '')} → {plain(call['summary'])}")


# ---------- sidebar ----------
settings = load_settings()
with st.sidebar:
    st.header("⚙️ Configuration")
    st.subheader("Project")
    options = ["Sample project (users API)"] + (["Custom local path"] if settings.allow_custom_project else [])
    choice = st.selectbox("Project", options, label_visibility="collapsed")
    source = SAMPLE_PROJECT
    if choice == "Custom local path":
        custom = st.text_input("Path to a Python project", help="Copied into an isolated sandbox; the original is never modified.")
        source = Path(custom) if custom else SAMPLE_PROJECT

    st.subheader("Model / provider")
    default_provider = PROVIDER_API if settings.has_api_key else PROVIDER_MOCK
    provider = st.radio("Provider", [PROVIDER_API, PROVIDER_MOCK], index=[PROVIDER_API, PROVIDER_MOCK].index(default_provider))
    api_key, model, base_url = settings.api_key, settings.model, settings.base_url
    typed_key = ""
    if provider == PROVIDER_API:
        base_url = st.text_input("Base URL", value=settings.base_url)
        model = st.text_input("Model", value=settings.model)
        typed_key = st.text_input("API key", type="password", placeholder="Uses LLM_API_KEY if left empty")
        api_key = typed_key or settings.api_key
    else:
        st.caption("Runs the real tools with a scripted planner. Only supports two scripted demo tasks.")

    st.subheader("Agent settings")
    repairs = st.slider("Max automatic repair attempts", 0, 3, settings.max_repair_attempts)
    timeout = st.slider("Test timeout (s)", 10, 120, settings.test_timeout)

    if st.button("🔄 Reset workspace", use_container_width=True):
        try:
            reset_workspace(source)
            st.success("Workspace reset to the original project.")
        except AgentError as exc:
            st.error(str(exc))

    with st.expander("ℹ️ About / architecture"):
        st.markdown(
            "**Flow:** analyze → inspect (tool loop) → select files → plan → generate changes → apply patch → "
            "run tests → (repair ≤3×) → diff & summary.\n\n"
            "**Tools:** `list_files`, `read_file`, `search_code`, `apply_patch`, `generate_diff`, `run_tests`.\n\n"
            "**Safety:** all paths are confined to a sandbox copy of the project; secrets and `.env` files are blocked."
        )

# ---------- main ----------
st.title("🤖 AI Coding Agent")
st.markdown('<div class="subtitle">Understand • Plan • Modify • Test</div>', unsafe_allow_html=True)


def _use_demo() -> None:
    st.session_state["task"] = DEMO_TASK


st.text_area("Coding task", key="task", height=110, placeholder="Describe the coding task...",
             label_visibility="collapsed")
left, right, _ = st.columns([1, 1, 4])
run_clicked = left.button("▶ Run agent", type="primary", use_container_width=True)
right.button("✨ Demo task", on_click=_use_demo, use_container_width=True)

missing_key = provider == PROVIDER_API and not api_key.strip()
uses_server_key = provider == PROVIDER_API and not typed_key  # visitor is spending the deployer's key
runs_used = st.session_state.get("runs_used", 0)
over_quota = uses_server_key and runs_used >= settings.max_runs_per_session
if missing_key:
    st.warning("No API key found. Set `LLM_API_KEY` (see `.env.example`), enter a key in the sidebar, "
               "or switch the provider to **Offline demo** to try the workflow without an LLM.")

status_box = st.empty()
if run_clicked:
    task = (st.session_state.get("task") or "").strip()
    if not task:
        st.error("Please describe a coding task first.")
    elif missing_key:
        st.error("Cannot run: the API key is missing.")
    elif over_quota:
        st.error(f"Run limit reached ({settings.max_runs_per_session} per session with the shared key). "
                 "Enter your own API key in the sidebar, or switch to **Offline demo**.")
    else:
        try:
            reset_workspace(source)  # every run starts from the pristine project
            ws = Workspace(st.session_state["ws_root"])
            if provider == PROVIDER_API:
                register_secret(api_key)
                llm = OpenAICompatibleClient(api_key, model, base_url, settings.llm_timeout)
            else:
                llm = MockLLM()
            run_settings = load_settings(max_repair_attempts=repairs, test_timeout=timeout)
            if uses_server_key:
                st.session_state["runs_used"] = runs_used + 1
            with st.spinner("Agent is working…"):
                result = run_agent(task, ws, llm, run_settings, on_event=lambda s: render_stages(s, status_box))
            st.session_state["result"] = result
        except AgentError as exc:
            st.error(str(exc))
        except Exception:  # never crash the UI
            log.exception("unexpected UI error")
            st.error("Unexpected error. Check the server logs for details.")

result = st.session_state.get("result")
if result is not None:
    if not run_clicked:
        render_stages(result, status_box)
    render_result(result, st.session_state["ws_root"])
else:
    st.caption("Click **Demo task**, then **Run agent** to see the full workflow.")
