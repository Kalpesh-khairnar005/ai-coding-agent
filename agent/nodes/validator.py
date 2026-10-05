from agent.state import AgentContext
from tools import run_tests


def run_validation(ctx: AgentContext) -> str:
    state = ctx.state
    ctx.stage("run_validation", "running", f"attempt {state.repair_attempts + 1}")
    result = run_tests(ctx.ws, timeout=ctx.settings.test_timeout)
    state.test_command, state.test_output, state.test_status = result.command, result.output, result.status
    state.test_runs.append({**result.to_dict(), "repair_attempt": state.repair_attempts})
    summary = f"{result.status}: {result.passed} passed, {result.failed} failed, {result.errors} errors"
    ctx.stage("run_validation", "done" if result.status == "passed" else "failed", summary)
    if result.status == "failed" and state.repair_attempts < ctx.settings.max_repair_attempts:
        state.repair_attempts += 1
        return "generate_changes"  # conditional transition: self-repair loop (bounded)
    return "generate_summary"
