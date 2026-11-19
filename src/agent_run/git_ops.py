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

AIDER_CHAT_HISTORY = ".aider.chat.history.md"
# Noise — deleted before commits; not promoted and not kept on agent branch.
AIDER_COMMIT_JUNK = (
    ".aider.input.history",
    ".aider.tags.cache.v4",
)


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


def current_branch(project: Path) -> str:
    name = _run(project, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not name or name == "HEAD":
        raise AgentRunError(
            "Detached HEAD is not supported; check out a branch before agent-run",
            exit_codes.DIRTY_OR_NOT_GIT,
        )
    return name


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


def is_service_path(rel: str, *, keep_tests: bool) -> bool:
    """Paths that stay on agent/task-* only and must not land on the base branch."""
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if rel == AIDER_CHAT_HISTORY or rel.startswith(".aider"):
        return True
    if rel == ".agent" or rel.startswith(".agent/"):
        return True
    if rel.startswith("tests/acceptance_generated/"):
        # With --keep-tests these are deliverables; otherwise ephemeral.
        return not keep_tests
    if (
        rel == ".pytest_cache"
        or rel.startswith(".pytest_cache/")
        or rel == "__pycache__"
        or rel.endswith("/__pycache__")
        or "/__pycache__/" in f"/{rel}/"
    ):
        return True
    return False


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


def commit_agent_branch(project: Path, message: str, *, keep_tests: bool) -> str:
    """Commit deliverables + service files on the current agent/task-* branch."""
    _run(project, "add", "-A")
    # Drop noise / ephemeral paths if staged.
    reset_paths = [".pytest_cache", "__pycache__", *AIDER_COMMIT_JUNK]
    if not keep_tests:
        reset_paths.append("tests/acceptance_generated")
    _run(project, "reset", "-q", "--", *reset_paths, check=False)

    # Force-add service artifacts that may still match leftover excludes.
    if (project / ".agent").exists():
        _run(project, "add", "-f", "--", ".agent")
    hist = project / AIDER_CHAT_HISTORY
    if hist.is_file():
        _run(project, "add", "-f", "--", AIDER_CHAT_HISTORY)
    if keep_tests and (project / "tests" / "acceptance_generated").exists():
        _run(project, "add", "-f", "--", "tests/acceptance_generated")

    status = _run(project, "status", "--porcelain").stdout.strip()
    if not status:
        raise AgentRunError("Nothing to commit after SUCCESS", exit_codes.INTERNAL)
    _run(project, "commit", "-m", message)
    return _run(project, "rev-parse", "--short", "HEAD").stdout.strip()


def _parse_name_status(line: str) -> tuple[str, str, str | None]:
    """Return (status_letter, path, old_path_for_rename)."""
    parts = line.split("\t")
    status = parts[0][0]
    if status in {"R", "C"} and len(parts) >= 3:
        return status, parts[2], parts[1]
    return status, parts[-1], None


def deliverable_changes(
    project: Path,
    base_sha: str,
    agent_tip: str,
    *,
    keep_tests: bool,
) -> list[tuple[str, str, str | None]]:
    """List (status, path, old_path) for product files between base and agent tip."""
    r = _run(project, "diff", "--name-status", f"{base_sha}..{agent_tip}", check=False)
    out: list[tuple[str, str, str | None]] = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        status, path, old = _parse_name_status(line)
        if is_service_path(path, keep_tests=keep_tests):
            continue
        if old and is_service_path(old, keep_tests=keep_tests):
            continue
        out.append((status, path, old))
    return out


def promote_deliverables_to_base(
    project: Path,
    *,
    base_branch: str,
    agent_branch: str,
    base_sha: str,
    keep_tests: bool,
    message: str,
    leave_on_base: bool = True,
) -> str | None:
    """
    Commit only deliverables onto base_branch (from agent tip).

    By default leaves HEAD on base_branch (automatic “merge” of product into main).
    Agent branch keeps the full service trail and is not deleted.
    Returns short SHA of the base commit, or None if there was nothing to promote.
    """
    agent_tip = head_sha(project)
    changes = deliverable_changes(project, base_sha, agent_tip, keep_tests=keep_tests)

    _run(project, "checkout", base_branch)
    try:
        if not changes:
            return None

        checkout_paths: list[str] = []
        delete_paths: list[str] = []
        for status, path, old in changes:
            if status == "D":
                delete_paths.append(path)
            elif status in {"R", "C"} and old:
                delete_paths.append(old)
                checkout_paths.append(path)
            else:
                checkout_paths.append(path)

        if checkout_paths:
            _run(project, "checkout", agent_tip, "--", *checkout_paths)
            _run(project, "add", "-A", "--", *checkout_paths)
        for path in delete_paths:
            _run(project, "rm", "-f", "--", path, check=False)

        status = _run(project, "status", "--porcelain").stdout.strip()
        if not status:
            return None
        _run(project, "commit", "-m", message)
        return _run(project, "rev-parse", "--short", "HEAD").stdout.strip()
    finally:
        if not leave_on_base:
            _run(project, "checkout", agent_branch)


# Back-compat alias used by older call sites / docs.
def commit_all(project: Path, message: str) -> str:
    return commit_agent_branch(project, message, keep_tests=False)
