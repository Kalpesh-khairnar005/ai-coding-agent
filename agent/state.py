"""Structured agent state and the shared run context."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from agent.prompts import REQUIRED_KEYS, STAGES, SYSTEM
from core.config import Settings
from core.errors import LLMError
from core.llm import LLMClient
from core.logging import get_logger
from core.security import Workspace

log = get_logger("agent")


@dataclass
class AgentState:
    user_task: str = ""
    project_path: str = ""
    task_understanding: str = ""
    keywords: list = field(default_factory=list)
    files: list = field(default_factory=list)
    file_contents: dict = field(default_factory=dict)
    search_hits: list = field(default_factory=list)
    tool_trace: list = field(default_factory=list)
    relevant_files: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    proposed: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    originals: dict = field(default_factory=dict)
    diff: str = ""
    files_changed: list = field(default_factory=list)
    test_command: str = ""
    test_output: str = ""
    test_status: str = ""
    test_runs: list = field(default_factory=list)
    repair_attempts: int = 0
    summary: dict = field(default_factory=dict)
    final_summary: str = ""
    errors: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    status: str = "idle"  # idle | running | success | failed | no_changes | error

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentContext:
    ws: Workspace
    llm: LLMClient
    settings: Settings
    state: AgentState
    on_event: Optional[Callable[[AgentState], None]] = None

    def stage(self, key: str, status: str, detail: str = "") -> None:
        for item in self.state.stages:
            if item["key"] == key:
                item["status"] = status
                if detail:
                    item["detail"] = detail
        if self.on_event:
            self.on_event(self.state)

    def ask(self, stage: str, payload: dict) -> dict:
        """Call the LLM for a stage and verify the structured response has the required keys."""
        out = self.llm.complete_json(stage, f"{SYSTEM}\n\nSTAGE: {STAGES[stage]}", payload)
        missing = [k for k in REQUIRED_KEYS[stage] if k not in out]
        if missing:
            raise LLMError(f"LLM response for '{stage}' is missing required field(s): {', '.join(missing)}.")
        return out

    def trace(self, tool: str, args: dict, summary: str) -> None:
        log.info("tool=%s args=%s -> %s", tool, args, summary)
        self.state.tool_trace.append({"tool": tool, "args": args, "summary": summary})
