"""Code modification: the LLM proposes edits, the patch tool validates and applies them."""
from __future__ import annotations

from agent.state import AgentContext
from core.errors import ToolError
from tools import apply_patch, read_file

FILE_CHARS = 12_000


def generate_changes(ctx: AgentContext) -> str:
    state = ctx.state
    repair = state.repair_attempts > 0
    ctx.stage("generate_changes", "running", f"repair attempt {state.repair_attempts}" if repair else "")
    files = {}
    paths = [e["path"] for e in state.relevant_files] + [c["file"] for c in state.changes if c.get("status") == "applied"]
    for path in dict.fromkeys(paths):  # always send the CURRENT content from disk
        try:
            files[path] = read_file(ctx.ws, path, max_chars=FILE_CHARS)
        except ToolError:
            continue
    rejected = [{"file": c["file"], "error": c["error"]} for c in state.changes
                if c["status"] == "rejected" and c["attempt"] == state.repair_attempts - 1] if repair else []
    out = ctx.ask("changes", {
        "task": state.user_task, "plan": state.plan, "files": files,
        "attempt": state.repair_attempts,
        "previous_test_output": state.test_output[-4000:] if repair and not rejected else "",
        "previous_patch_errors": rejected,
    })
    state.proposed = [c for c in out["changes"] if isinstance(c, dict) and c.get("file")]
    ctx.stage("generate_changes", "done", f"{len(state.proposed)} file change(s) proposed")
    return "apply_changes"


def apply_changes(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("apply_changes", "running")
    applied = rejected = 0
    for change in state.proposed:
        path = str(change["file"])
        record = {"file": path, "description": str(change.get("description", "")), "status": "applied",
                  "error": "", "attempt": state.repair_attempts}
        try:
            apply_patch(ctx.ws, path, edits=change.get("edits"), new_content=change.get("new_content"),
                        originals=state.originals)
            applied += 1
            ctx.trace("apply_patch", {"file": path}, "applied")
        except ToolError as exc:  # SecurityError and PatchError are ToolErrors
            rejected += 1
            record.update(status="rejected", error=str(exc))
            ctx.trace("apply_patch", {"file": path}, f"REJECTED: {exc}")
        state.changes.append(record)
    state.proposed = []
    if applied == 0 and rejected and state.repair_attempts < ctx.settings.max_repair_attempts:
        state.repair_attempts += 1  # bounded retry: tell the model exactly why its edits were rejected
        ctx.stage("apply_changes", "running", f"{rejected} edit(s) rejected, retrying ({state.repair_attempts})")
        return "generate_changes"
    if applied == 0:
        detail = "no valid changes could be applied"
        ctx.stage("apply_changes", "failed", detail)
        state.errors.append("The agent did not produce any change that could be applied safely.")
        return "generate_summary"
    ctx.stage("apply_changes", "done", f"{applied} file(s) patched")
    return "run_validation"
