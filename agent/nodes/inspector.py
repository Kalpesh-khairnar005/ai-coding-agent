"""Codebase inspection: an LLM-driven tool loop, then relevant-file selection with reasons."""
from __future__ import annotations

from agent.state import AgentContext
from core.errors import AgentError, ToolError
from tools import list_files, read_file, search_code

CONTENT_BUDGET = 40_000  # total characters of file content gathered for the LLM
PER_FILE_CHARS = 8_000


def _execute(ctx: AgentContext, action: str, args: dict) -> dict:
    """Run one exploration tool. Errors become observations so the loop never crashes."""
    state = ctx.state
    try:
        if action == "search_code":
            query = str(args.get("query", ""))
            hits = search_code(ctx.ws, query)
            state.search_hits.extend(hits)
            counts: dict = {}
            for hit in hits:
                counts[hit["path"]] = counts.get(hit["path"], 0) + 1
            ctx.trace("search_code", {"query": query}, f"{len(hits)} hits in {len(counts)} files")
            return {"tool": action, "args": {"query": query}, "summary": f"{len(hits)} hits",
                    "hit_files": counts, "hits": hits[:12]}
        if action == "read_file":
            path = str(args.get("path", ""))
            if path in state.file_contents:
                return {"tool": action, "args": {"path": path}, "summary": "already read"}
            if sum(map(len, state.file_contents.values())) > CONTENT_BUDGET:
                return {"tool": action, "args": {"path": path}, "summary": "ERROR: context budget exhausted"}
            state.file_contents[path] = read_file(ctx.ws, path, max_chars=PER_FILE_CHARS)
            ctx.trace("read_file", {"path": path}, f"{len(state.file_contents[path])} chars")
            return {"tool": action, "args": {"path": path}, "summary": f"read {len(state.file_contents[path])} chars"}
        if action == "list_files":
            ctx.trace("list_files", {}, f"{len(state.files)} files")
            return {"tool": action, "args": {}, "summary": f"{len(state.files)} files (see file_tree)"}
        return {"tool": str(action), "args": {}, "summary": f"ERROR: unknown tool '{action}'"}
    except ToolError as exc:
        ctx.trace(action, args, f"ERROR: {exc}")
        return {"tool": action, "args": args, "summary": f"ERROR: {exc}"}


def inspect_codebase(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("inspect_codebase", "running")
    state.files = list_files(ctx.ws)
    if not state.files:
        raise AgentError("The project contains no readable source files.")
    ctx.trace("list_files", {}, f"{len(state.files)} files")

    observations: list = []
    for step in range(ctx.settings.max_explore_steps):
        out = ctx.ask("explore", {
            "task": state.user_task, "understanding": state.task_understanding,
            "keywords": state.keywords, "file_tree": state.files,
            "observations": observations, "steps_left": ctx.settings.max_explore_steps - step,
        })
        action = out.get("action")
        if action == "finish":
            break
        args = out.get("args") if isinstance(out.get("args"), dict) else {}
        observations.append(_execute(ctx, action, args))

    if not state.file_contents:  # safety net: the LLM read nothing, so read the top candidates
        ranked = sorted({h["path"] for h in state.search_hits} or {f["path"] for f in state.files})
        for path in [p for p in ranked if p.endswith(".py")][:5]:
            _execute(ctx, "read_file", {"path": path})
    ctx.stage("inspect_codebase", "done", f"{len(state.files)} files scanned, {len(state.file_contents)} read")
    return "select_relevant_files"


def select_relevant_files(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("select_relevant_files", "running")
    known = {f["path"] for f in state.files}
    out = ctx.ask("select", {
        "task": state.user_task, "understanding": state.task_understanding, "keywords": state.keywords,
        "file_tree": state.files, "search_hits": state.search_hits[:40],
        "contents": {p: c[:3000] for p, c in state.file_contents.items()},
    })
    selected = []
    for item in out["relevant_files"]:
        path = item.get("path") if isinstance(item, dict) else None
        if path in known and all(path != s["path"] for s in selected):
            selected.append({"path": path, "reason": str(item.get("reason", "")).strip() or "Selected by the agent."})
    if not selected:
        raise AgentError("The agent could not identify any relevant files for this task.")
    state.relevant_files = selected[:8]
    for entry in state.relevant_files:  # make sure content is available for planning and coding
        if entry["path"] not in state.file_contents:
            _execute(ctx, "read_file", {"path": entry["path"]})
    ctx.trace("select_relevant_files", {}, ", ".join(e["path"] for e in state.relevant_files))
    ctx.stage("select_relevant_files", "done", f"{len(state.relevant_files)} relevant files")
    return "create_plan"
