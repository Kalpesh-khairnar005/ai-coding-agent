from agent.state import AgentContext
from core.errors import AgentError


def create_plan(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("create_plan", "running")
    out = ctx.ask("plan", {
        "task": state.user_task, "understanding": state.task_understanding,
        "relevant_files": state.relevant_files,
        "contents": {e["path"]: state.file_contents.get(e["path"], "")[:4000] for e in state.relevant_files},
    })
    plan = [str(step).strip() for step in out["plan"] if str(step).strip()]
    if not plan:
        raise AgentError("The agent returned an empty implementation plan.")
    state.plan = plan[:10]
    ctx.stage("create_plan", "done", f"{len(state.plan)} steps")
    return "generate_changes"
