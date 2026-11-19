from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_run import __version__, exit_codes
from agent_run.pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-run", description="Autonomous TDD runner")
    p.add_argument("--project", required=True, type=Path, help="Path to target git repository")
    p.add_argument("--task", required=True, type=Path, help="Path to task.md")
    p.add_argument("--budget", type=float, default=0.50, help="Soft budget USD (default 0.50)")
    p.add_argument("--max-iter", type=int, default=8, dest="max_iter")
    p.add_argument("--keep-tests", action="store_true", default=False)
    p.add_argument("--sandbox-image", default=None, help="Docker image for sandbox")
    p.add_argument("--model-profile", default="default", dest="model_profile")
    p.add_argument("--version", action="version", version=f"agent-run {__version__}")
    return p


def main(argv: list[str] | None = None) -> None:
    # Load .env from CWD and from agent-run repo if present
    load_dotenv()
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.project.is_dir():
        print(f"Project path is not a directory: {args.project}", file=sys.stderr)
        raise SystemExit(exit_codes.CLI_OR_TASK_INVALID)

    pipe = Pipeline(
        project=args.project,
        task_path=args.task,
        budget=args.budget,
        max_iter=args.max_iter,
        keep_tests=args.keep_tests,
        sandbox_image=args.sandbox_image or os.environ.get("AGENT_RUN_SANDBOX_IMAGE"),
        model_profile=args.model_profile,
    )
    raise SystemExit(pipe.run())


if __name__ == "__main__":
    main()
