from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".agent"}


def project_tree(root: Path, max_depth: int = 4) -> str:
    lines: list[str] = [str(root.name) + "/"]

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if e.name not in SKIP_DIRS]
        for i, entry in enumerate(entries):
            last = i == len(entries) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                extension = "    " if last else "│   "
                walk(entry, prefix + extension, depth + 1)

    walk(root, "", 1)
    return "\n".join(lines)


def detect_stack(project: Path) -> str:
    if (project / "pyproject.toml").exists() or (project / "pytest.ini").exists():
        return "python"

    def _is_project_python_test(path: Path) -> bool:
        rel = path.relative_to(project).as_posix()
        # Host-seeded acceptance stubs must not force the "python" stack.
        return not rel.startswith("tests/acceptance_generated/")

    if any(_is_project_python_test(p) for p in project.glob("tests/**/*.py")) or any(
        project.glob("test_*.py")
    ):
        return "python"
    if (project / "package.json").exists():
        return "node"
    if (project / "go.mod").exists():
        return "go"
    return "unknown"
