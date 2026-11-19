from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent_run import exit_codes
from agent_run.errors import AgentRunError

REQUIRED = ("Task", "Constraints", "Acceptance Criteria")


@dataclass
class TaskDoc:
    path: Path
    raw: str
    task: str
    constraints: str
    acceptance: str


def _section(raw: str, title: str) -> str | None:
    pattern = rf"(?im)^##\s+{re.escape(title)}\s*\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, raw, re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def load_task(path: Path) -> TaskDoc:
    if not path.is_file():
        raise AgentRunError(f"Task file not found: {path}", exit_codes.CLI_OR_TASK_INVALID)
    raw = path.read_text(encoding="utf-8")
    missing = [t for t in REQUIRED if _section(raw, t) is None]
    if missing:
        raise AgentRunError(
            f"task.md missing required sections: {', '.join(missing)}",
            exit_codes.CLI_OR_TASK_INVALID,
        )
    acceptance = _section(raw, "Acceptance Criteria") or ""
    if not acceptance:
        raise AgentRunError("Acceptance Criteria section is empty", exit_codes.CLI_OR_TASK_INVALID)
    return TaskDoc(
        path=path,
        raw=raw,
        task=_section(raw, "Task") or "",
        constraints=_section(raw, "Constraints") or "",
        acceptance=acceptance,
    )
