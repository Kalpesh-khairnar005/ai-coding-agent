"""Agent graph: explicit nodes, conditional transitions, bounded self-repair loop.

A small custom runner is used instead of LangGraph: the flow is linear with one conditional edge
(validate -> repair), so a dependency would add weight without adding capability.
"""
from __future__ import annotations

from typing import Callable, Optional

from agent.nodes.analyzer import analyze_task
from agent.nodes.coder import apply_changes, generate_changes
from agent.nodes.inspector import inspect_codebase, select_relevant_files
from agent.nodes.planner import create_plan
from agent.nodes.summarizer import generate_summary
from agent.nodes.validator import run_validation
from agent.state import AgentContext, AgentState
from core.config import Settings
from core.errors import AgentError
from core.llm import LLMClient
from core.logging import get_logger
from core.security import Workspace

log = get_logger("agent.graph")

NODES = {
    "analyze_task": analyze_task,
    "inspect_codebase": inspect_codebase,
    "select_relevant_files": select_relevant_files,
    "create_plan": create_plan,
    "generate_changes": generate_changes,
    "apply_changes": apply_changes,
    "run_validation": run_validation,
    "generate_summary": generate_summary,
}
STAGES = [
    ("analyze_task", "Understanding task"),
    ("inspect_codebase", "Inspecting codebase"),
    ("select_relevant_files", "Selecting relevant files"),
    ("create_plan", "Creating implementation plan"),
    ("generate_changes", "Generating changes"),
    ("apply_changes", "Applying changes"),
    ("run_validation", "Running tests"),
    ("generate_summary", "Generating diff & summary"),
]


def run_agent(
    task: str, ws: Workspace, llm: LLMClient, settings: Settings,
    on_event: Optional[Callable[[AgentState], None]] = None,
) -> AgentState:
    """Run the full workflow. Never raises for expected failures: errors are recorded in the state."""
    state = AgentState(user_task=(task or "").strip(), project_path=ws.root.name, status="running")
    state.stages = [{"key": k, "label": v, "status": "pending", "detail": ""} for k, v in STAGES]
    ctx = AgentContext(ws=ws, llm=llm, settings=settings, state=state, on_event=on_event)
    if not state.user_task:
        state.status, state.errors = "error", ["Please describe a coding task first."]
        return state

    log.info("agent start: task_len=%d provider=%s", len(state.user_task), llm.name)
    node = "analyze_task"
    while node != "END":
        try:
            node = NODES[node](ctx)
        except AgentError as exc:
            log.error("node %s failed: %s", node, exc)
            ctx.stage(node, "failed", str(exc))
            state.errors.append(f"{dict(STAGES)[node]}: {exc}")
            state.status = "error"
            break
        except Exception as exc:  # last-resort guard: one bad node must not crash the UI
            log.exception("unexpected error in %s", node)
            ctx.stage(node, "failed", type(exc).__name__)
            state.errors.append(f"Unexpected error in '{node}': {type(exc).__name__}")
            state.status = "error"
            break
    if state.status == "error" and state.originals:  # still show whatever was changed before the failure
        from tools import generate_diff
        state.diff, state.files_changed = generate_diff(ws, state.originals)
    for item in state.stages:
        if item["status"] == "pending":
            item["status"] = "skipped"
    if on_event:
        on_event(state)
    log.info("agent finished: status=%s files_changed=%d", state.status, len(state.files_changed))
    return state
