from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunState:
    version: int = 1
    task_id: str = ""
    branch: str = ""
    base_branch: str = ""
    base_sha: str = ""
    phase: str = "init"
    iteration: int = 0
    max_iter: int = 8
    budget_usd: float = 0.5
    usage_baseline_usd: float = 0.0
    spent_usd: float = 0.0
    model_profile: str = "default"
    current_model: str = ""
    last_error_hash: str | None = None
    same_error_streak: int = 0
    model_escalated: bool = False
    test_architect_attempts: int = 0
    status: str = "running"
    hitl_reason: str | None = None
    hitl_detail: str | None = None
    judge_issues: list[str] = field(default_factory=list)
    last_test_log_tail: str = ""
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class StateStore:
    def __init__(self, project: Path) -> None:
        self.agent_dir = project / ".agent"
        self.path = self.agent_dir / "state.json"

    def ensure_dir(self) -> None:
        self.agent_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: RunState) -> None:
        self.ensure_dir()
        state.touch()
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=self.agent_dir, prefix=".state.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            tmp_path.replace(self.path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def load(self) -> RunState:
        return RunState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
