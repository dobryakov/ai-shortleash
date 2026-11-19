from pathlib import Path

import pytest

from agent_run import git_ops


def _git_init(repo: Path) -> None:
    git_ops._run(repo, "init")
    git_ops._run(repo, "config", "user.email", "test@example.com")
    git_ops._run(repo, "config", "user.name", "Test")
    (repo / "README").write_text("base\n", encoding="utf-8")
    git_ops._run(repo, "add", "README")
    git_ops._run(repo, "commit", "-m", "init")


def test_is_service_path_keep_tests():
    assert git_ops.is_service_path(".aider.chat.history.md", keep_tests=False)
    assert git_ops.is_service_path(".agent/state.json", keep_tests=False)
    assert git_ops.is_service_path("tests/acceptance_generated/t.py", keep_tests=False)
    assert not git_ops.is_service_path("tests/acceptance_generated/t.py", keep_tests=True)
    assert not git_ops.is_service_path("hello.php", keep_tests=False)


def test_promote_deliverables_keeps_service_on_agent_only(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git_init(repo)
    base_branch = git_ops.current_branch(repo)
    base_sha = git_ops.head_sha(repo)

    agent = git_ops.create_branch(repo, "demo")
    (repo / "hello.php").write_text("<?php echo 1;\n", encoding="utf-8")
    (repo / ".aider.chat.history.md").write_text("# chat\n", encoding="utf-8")
    (repo / ".agent").mkdir()
    (repo / ".agent" / "state.json").write_text("{}\n", encoding="utf-8")

    agent_sha = git_ops.commit_agent_branch(repo, "agent full", keep_tests=False)
    assert agent_sha
    # Agent tip has service + product
    files_agent = git_ops._run(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines()
    assert "hello.php" in files_agent
    assert ".aider.chat.history.md" in files_agent
    assert ".agent/state.json" in files_agent

    base_sha_short = git_ops.promote_deliverables_to_base(
        repo,
        base_branch=base_branch,
        agent_branch=agent,
        base_sha=base_sha,
        keep_tests=False,
        message="agent deliverables",
    )
    assert base_sha_short
    # SUCCESS leaves the user on the base branch (no manual merge / branch browsing).
    assert git_ops.current_branch(repo) == base_branch

    files_base = git_ops._run(repo, "ls-tree", "-r", "--name-only", base_branch).stdout.splitlines()
    assert "hello.php" in files_base
    assert ".aider.chat.history.md" not in files_base
    assert ".agent/state.json" not in files_base
    assert "README" in files_base

    files_agent = git_ops._run(repo, "ls-tree", "-r", "--name-only", agent).stdout.splitlines()
    assert ".aider.chat.history.md" in files_agent
    assert ".agent/state.json" in files_agent


def test_keep_tests_promotes_acceptance(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git_init(repo)
    base_branch = git_ops.current_branch(repo)
    base_sha = git_ops.head_sha(repo)
    agent = git_ops.create_branch(repo, "keep")

    (repo / "app.py").write_text("x=1\n", encoding="utf-8")
    acc = repo / "tests" / "acceptance_generated"
    acc.mkdir(parents=True)
    (acc / "test_acceptance.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / ".aider.chat.history.md").write_text("hist\n", encoding="utf-8")

    git_ops.commit_agent_branch(repo, "agent full", keep_tests=True)
    git_ops.promote_deliverables_to_base(
        repo,
        base_branch=base_branch,
        agent_branch=agent,
        base_sha=base_sha,
        keep_tests=True,
        message="deliverables",
    )
    assert git_ops.current_branch(repo) == base_branch
    files_base = git_ops._run(repo, "ls-tree", "-r", "--name-only", base_branch).stdout.splitlines()
    assert "app.py" in files_base
    assert "tests/acceptance_generated/test_acceptance.py" in files_base
    assert ".aider.chat.history.md" not in files_base
