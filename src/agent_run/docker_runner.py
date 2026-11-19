from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_run import exit_codes
from agent_run.errors import AgentRunError


@dataclass
class ContainerResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def combined_tail(self) -> str:
        text = (self.stdout or "") + "\n" + (self.stderr or "")
        return text[-3000:]


class DockerRunner:
    def __init__(self, image: str | None = None) -> None:
        self.image = image or os.environ.get("AGENT_RUN_SANDBOX_IMAGE", "dev-agent-sandbox:0.1.0")

    def ensure_image(self) -> None:
        r = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise AgentRunError(
                f"Docker image not found: {self.image}. Build with: docker build -t {self.image} sandbox/",
                exit_codes.DOCKER_ERROR,
            )

    def run(
        self,
        project: Path,
        command: list[str],
        *,
        ro_agent: bool = False,
        env: dict[str, str] | None = None,
        workdir: str = "/workspace",
    ) -> ContainerResult:
        self.ensure_image()
        project = project.resolve()
        cmd = [
            "docker",
            "run",
            "--rm",
            "--memory=2g",
            "--cpus=1.5",
            "--network=bridge",
            "-w",
            workdir,
            "-v",
            f"{project}:/workspace:rw",
        ]

        agent_dir = project / ".agent"
        acc_dir = project / "tests" / "acceptance_generated"
        if ro_agent:
            if agent_dir.is_dir():
                cmd.extend(["-v", f"{agent_dir}:/workspace/.agent:ro"])
            if acc_dir.is_dir():
                cmd.extend(["-v", f"{acc_dir}:/workspace/tests/acceptance_generated:ro"])

        env_file = project / ".env"
        if env_file.exists():
            cmd.extend(["-v", "/dev/null:/workspace/.env:ro"])

        merged_env = {
            "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
            "HOME": "/tmp",
        }
        if env:
            merged_env.update(env)
        for k, v in merged_env.items():
            if v:
                cmd.extend(["-e", f"{k}={v}"])

        cmd.append(self.image)
        cmd.extend(command)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise AgentRunError("docker CLI not found", exit_codes.DOCKER_ERROR) from exc
        except Exception as exc:
            raise AgentRunError(f"docker run failed: {exc}", exit_codes.DOCKER_ERROR) from exc

        return ContainerResult(proc.returncode, proc.stdout, proc.stderr)

    def run_tests(self, project: Path, *, ro_agent: bool = True) -> ContainerResult:
        return self.run(
            project,
            ["bash", "/workspace/.agent/run_tests.sh"],
            ro_agent=ro_agent,
        )

    def run_aider(
        self,
        project: Path,
        *,
        model: str,
        message_file: Path,
        editable: list[str],
        read_only: list[str] | None = None,
        ro_agent: bool = False,
    ) -> ContainerResult:
        # message file must be under project; path inside container
        rel_msg = message_file.relative_to(project.resolve()).as_posix()
        cmd = [
            "aider",
            "--yes-always",
            "--no-auto-commits",
            "--no-git",
            "--no-stream",
            "--no-check-update",
            "--no-show-model-warnings",
            f"--model=openrouter/{model}" if not model.startswith("openrouter/") else f"--model={model}",
            "--message-file",
            f"/workspace/{rel_msg}",
        ]
        for path in read_only or []:
            cmd.extend(["--read", path if path.startswith("/workspace") else f"/workspace/{path}"])
        for path in editable:
            cmd.append(path if path.startswith("/workspace") else f"/workspace/{path}")

        return self.run(project, cmd, ro_agent=ro_agent)
