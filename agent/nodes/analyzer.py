from agent.state import AgentContext


def analyze_task(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("analyze_task", "running")
    out = ctx.ask("analyze", {"task": state.user_task})
    state.task_understanding = str(out["task_understanding"]).strip() or state.user_task
    state.keywords = [k.strip().lower() for k in out.get("keywords", []) if isinstance(k, str) and k.strip()][:4]
    ctx.stage("analyze_task", "done", f"keywords: {', '.join(state.keywords) or '-'}")
    return "inspect_codebase"
