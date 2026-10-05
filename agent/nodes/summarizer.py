"""Final diff and explanation. The validation verdict is computed from tool output, never from the LLM."""
from __future__ import annotations

from agent.state import AgentContext
from core.errors import AgentError
from tools import generate_diff


def _validation_line(state) -> str:
    if not state.test_runs:
        return "Tests were NOT run (no change was applied)."
    last = state.test_runs[-1]
    counts = f"{last['passed']} passed, {last['failed']} failed, {last['errors']} errors"
    verdict = {"passed": "PASSED", "failed": "FAILED", "no_tests": "NO TESTS FOUND", "timeout": "TIMED OUT",
               "error": "COULD NOT RUN"}[last["status"]]
    retries = f" after {state.repair_attempts} automatic repair attempt(s)" if state.repair_attempts else ""
    return f"`{last['command']}` → **{verdict}** ({counts}){retries}."


def generate_summary(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("generate_summary", "running")
    state.diff, state.files_changed = generate_diff(ctx.ws, state.originals)

    if state.test_status == "passed":
        state.status = "success"
    elif state.files_changed and state.test_runs:
        state.status = "failed"
    else:
        state.status = "no_changes"

    try:
        out = ctx.ask("summary", {
            "task": state.user_task, "plan": state.plan, "files_changed": state.files_changed,
            "changes": [c for c in state.changes if c["status"] == "applied"],
            "rejected": [c for c in state.changes if c["status"] != "applied"],
            "diff": state.diff[:6000], "test_status": state.test_status,
        })
    except AgentError as exc:  # explanation is best-effort; facts below are always accurate
        state.errors.append(f"Could not generate the narrative explanation: {exc}")
        out = {"what_changed": "; ".join(c["description"] for c in state.changes if c["status"] == "applied")
               or "No changes were applied.", "why": "", "tests_added": [], "limitations": []}
    state.summary = {
        "what_changed": str(out.get("what_changed", "")),
        "why": str(out.get("why", "")),
        "tests_added": [str(t) for t in out.get("tests_added", [])],
        "limitations": [str(t) for t in out.get("limitations", [])],
        "files_modified": state.files_changed,
        "validation": _validation_line(state),
    }
    state.final_summary = state.summary["what_changed"]
    ctx.stage("generate_summary", "done", f"{len(state.files_changed)} file(s) changed")
    return "END"
