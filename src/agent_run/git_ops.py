from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from agent_run import exit_codes
from agent_run.errors import AgentRunError

EXCLUDE_LINES = [
    ".agent/",
    "tests/acceptance_generated/",
    ".aider*",
    ".aider.chat.history.md",
    ".aider.input.history",
    ".aider.tags.cache.v4/",
]


def _run(project: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        text=True,
        capture_output=True,
        check=check,
    )


def ensure_git_repo(project: Path) -> None:
    r = _run(project, "rev-parse", "--is-inside-work-tree", check=False)
    if r.returncode != 0 or r.stdout.strip() != "true":
        raise AgentRunError(f"Not a git repository: {project}", exit_codes.DIRTY_OR_NOT_GIT)


def ensure_clean(project: Path) -> None:
    r = _run(project, "status", "--porcelain")
    if r.stdout.strip():
        raise AgentRunError(
            "Working tree is dirty; commit or stash changes first.\n" + r.stdout,
            exit_codes.DIRTY_OR_NOT_GIT,
        )


def head_sha(project: Path) -> str:
    return _run(project, "rev-parse", "HEAD").stdout.strip()


def slugify(name: str, max_len: int = 40) -> str:
    base = Path(name).stem.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return (base or "task")[:max_len]


def branch_exists(project: Path, branch: str) -> bool:
    r = _run(project, "show-ref", "--verify", f"refs/heads/{branch}", check=False)
    return r.returncode == 0


def create_branch(project: Path, slug: str) -> str:
    branch = f"agent/task-{slug}"
    if branch_exists(project, branch):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch = f"agent/task-{slug}-{stamp}"
    _run(project, "checkout", "-b", branch)
    return branch


def ensure_excludes(project: Path) -> None:
    exclude = project / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = existing.splitlines()
    changed = False
    for item in EXCLUDE_LINES:
        if item not in lines:
            lines.append(item)
            changed = True
    if changed:
        if lines and lines[-1] != "":
            lines.append("")
        exclude.write_text("\n".join(lines), encoding="utf-8")


def remove_excludes(project: Path) -> None:
    exclude = project / ".git" / "info" / "exclude"
    if not exclude.exists():
        return
    lines = [ln for ln in exclude.read_text(encoding="utf-8").splitlines() if ln not in EXCLUDE_LINES]
    exclude.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def working_diff(project: Path, base_sha: str) -> str:
    committed = _run(project, "diff", f"{base_sha}..HEAD", check=False).stdout
    unstaged = _run(project, "diff", check=False).stdout
    untracked = _run(project, "ls-files", "--others", "--exclude-standard", check=False).stdout
    parts = [committed, unstaged]
    for path in untracked.splitlines():
        if path.startswith(".agent/") or path.startswith("tests/acceptance_generated/"):
            continue
        file_path = project / path
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            parts.append(f"--- /dev/null\n+++ b/{path}\n" + "".join(f"+{ln}" for ln in content.splitlines(True)))
    return "\n".join(p for p in parts if p).strip()


def commit_all(project: Path, message: str) -> str:
    _run(project, "add", "-A")
    # Drop agent artifacts if somehow staged
    _run(project, "reset", "-q", "--", ".agent", "tests/acceptance_generated", check=False)
    status = _run(project, "status", "--porcelain").stdout.strip()
    if not status:
        raise AgentRunError("Nothing to commit after SUCCESS", exit_codes.INTERNAL)
    _run(project, "commit", "-m", message)
    return _run(project, "rev-parse", "--short", "HEAD").stdout.strip()
