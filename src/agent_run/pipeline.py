from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from agent_run import exit_codes
from agent_run.budget import ensure_budget, refresh_spent
from agent_run.docker_runner import DockerRunner
from agent_run.errors import AgentRunError, HitlError
from agent_run import git_ops
from agent_run.models import ModelProfile, coder_model, load_profile
from agent_run.openrouter import OpenRouterClient, extract_json_object
from agent_run.state import RunState, StateStore
from agent_run.task_parse import TaskDoc, load_task
from agent_run.test_classify import error_hash, is_runner_or_syntax_failure
from agent_run.tree_util import detect_stack, project_tree


class Pipeline:
    def __init__(
        self,
        *,
        project: Path,
        task_path: Path,
        budget: float,
        max_iter: int,
        keep_tests: bool,
        sandbox_image: str | None,
        model_profile: str,
    ) -> None:
        self.project = project.resolve()
        self.task_path = task_path.resolve()
        self.budget = budget
        self.max_iter = max_iter
        self.keep_tests = keep_tests
        self.docker = DockerRunner(sandbox_image)
        self.profile: ModelProfile = load_profile(model_profile)
        self.store = StateStore(self.project)
        self.client = OpenRouterClient()
        self.task: TaskDoc | None = None
        self.state = RunState()
        self.commit_sha: str | None = None

    def run(self) -> int:
        try:
            self._init()
            self._preflight()
            self._test_architect()
            self._coder_and_judge()
            self._cleanup_success()
            self._emit_report("SUCCESS")
            return exit_codes.SUCCESS
        except HitlError as exc:
            self._handle_hitl(exc)
            self._emit_report("HITL", hitl_reason=exc.reason)
            return exc.code
        except AgentRunError as exc:
            print(str(exc), file=sys.stderr)
            return exc.code
        except Exception as exc:  # noqa: BLE001
            print(f"Internal error: {exc}", file=sys.stderr)
            return exit_codes.INTERNAL
        finally:
            self.client.close()

    # --- init ---

    def _init(self) -> None:
        git_ops.ensure_git_repo(self.project)
        git_ops.ensure_clean(self.project)
        self.task = load_task(self.task_path)
        slug = git_ops.slugify(self.task_path.name)
        base_sha = git_ops.head_sha(self.project)
        branch = git_ops.create_branch(self.project, slug)
        git_ops.ensure_excludes(self.project)

        baseline = self.client.get_usage_usd()
        self.store.ensure_dir()
        (self.store.agent_dir / "logs").mkdir(exist_ok=True)

        self.state = RunState(
            task_id=slug,
            branch=branch,
            base_sha=base_sha,
            phase="init",
            max_iter=self.max_iter,
            budget_usd=self.budget,
            usage_baseline_usd=baseline,
            spent_usd=0.0,
            model_profile=self.profile.name,
        )
        self.store.save(self.state)
        print(f"Init: branch={branch} baseline_usage=${baseline:.4f}", file=sys.stderr)

    # --- preflight ---

    def _preflight(self) -> None:
        assert self.task
        self.state.phase = "preflight"
        self.store.save(self.state)
        ensure_budget(self.client, self.state, self.store)

        tree = project_tree(self.project)
        system = (
            "You are a requirements analyst. Reply with ONLY JSON: "
            '{"status":"OK"|"AMBIGUOUS","questions":[str],"notes":[str]}. '
            "AMBIGUOUS if acceptance criteria are contradictory, incomplete, or untestable."
        )
        user = f"TASK FILE:\n{self.task.raw}\n\nPROJECT TREE:\n{tree}"
        data = self._llm_json(self.profile.cheap, system, user, phase="preflight")
        status = data.get("status")
        questions = data.get("questions") or []
        if status == "AMBIGUOUS" and questions:
            for q in questions:
                print(f"QUESTION: {q}")
            raise HitlError("ambiguous_task", "; ".join(questions))
        if status != "OK":
            # tolerate OK-equivalent
            if status == "AMBIGUOUS":
                raise HitlError("ambiguous_task", "marked AMBIGUOUS without questions")
        print("Preflight: OK", file=sys.stderr)

    def _llm_json(self, model: str, system: str, user: str, *, phase: str) -> dict:
        self.state.current_model = model
        self.store.save(self.state)
        content = self.client.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
        )
        try:
            return extract_json_object(content)
        except Exception:
            repair = self.client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system + " Return ONLY valid JSON."},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": "Your previous reply was not valid JSON. Reply with JSON only."},
                ],
                temperature=0.0,
            )
            try:
                return extract_json_object(repair)
            except Exception as exc:
                reason = "preflight_invalid_response" if phase == "preflight" else "judge_invalid_response"
                raise HitlError(reason, str(exc)) from exc

    # --- test architect ---

    def _test_architect(self) -> None:
        assert self.task
        self.state.phase = "test_architect"
        self.store.save(self.state)
        ensure_budget(self.client, self.state, self.store)

        acc = self.project / "tests" / "acceptance_generated"
        acc.mkdir(parents=True, exist_ok=True)
        stub = acc / "test_acceptance.py"
        if not stub.exists():
            # Failing stub so placeholder project tests alone cannot look "green".
            stub.write_text(
                '"""Generated acceptance tests — Test Architect must replace this."""\n'
                "\n"
                "def test_acceptance_pending():\n"
                "    raise AssertionError('acceptance tests not generated yet')\n",
                encoding="utf-8",
            )
        run_tests = self.store.agent_dir / "run_tests.sh"
        stack = detect_stack(self.project)
        self._write_run_tests_sh(run_tests, stack)

        prompt = self.store.agent_dir / "prompt.txt"
        prompt.write_text(
            "You are the Test Architect for a TDD workflow.\n"
            "Write executable acceptance tests for EVERY acceptance criterion.\n"
            "Only edit files under tests/acceptance_generated/.\n"
            "Do NOT edit .agent/run_tests.sh (the host owns it).\n"
            "Do NOT implement product code.\n\n"
            f"STACK hint: {stack}\n\n"
            f"{self.task.raw}\n",
            encoding="utf-8",
        )

        model = self.profile.strong
        max_attempts = 3
        strengthened = False
        for attempt in range(1, max_attempts + 1):
            self.state.test_architect_attempts = attempt
            self.state.current_model = model
            self.store.save(self.state)
            ensure_budget(self.client, self.state, self.store)

            if attempt > 1:
                prompt.write_text(
                    prompt.read_text(encoding="utf-8")
                    + "\n\nPREVIOUS TEST RUN FAILURE (fix tests / runner):\n"
                    + self.state.last_test_log_tail
                    + "\nFix ONLY the tests and run_tests.sh.\n",
                    encoding="utf-8",
                )

            result = self.docker.run_aider(
                self.project,
                model=model,
                message_file=prompt,
                editable=[
                    "tests/acceptance_generated/test_acceptance.py",
                ],
                ro_agent=False,
            )
            self._save_log("test_architect", attempt, result.stdout + result.stderr)
            # Re-assert host-owned runner (models sometimes rewrite it with set -u bugs).
            self._write_run_tests_sh(run_tests, stack)

            if self._acceptance_still_stub():
                self.state.last_test_log_tail = (
                    "Test Architect left the stub test_acceptance_pending in place. "
                    "Replace it with real acceptance tests."
                )
                self.store.save(self.state)
                if attempt == max_attempts:
                    raise HitlError("tests_not_runnable", "acceptance stub not replaced")
                continue

            test_res = self.docker.run_tests(self.project, ro_agent=False)
            tail = test_res.combined_tail
            self.state.last_test_log_tail = tail
            self.store.save(self.state)
            self._save_log("red_check", attempt, tail)

            if test_res.exit_code == 0:
                if not strengthened:
                    strengthened = True
                    prompt.write_text(
                        "Acceptance tests passed before product changes — they are too weak or criteria already met.\n"
                        "Strengthen tests so they FAIL until the feature is implemented. "
                        "Only edit tests/acceptance_generated and .agent/run_tests.sh.\n\n"
                        f"{self.task.raw}\n",
                        encoding="utf-8",
                    )
                    continue
                raise HitlError("tests_already_green", "tests green before coding")

            if is_runner_or_syntax_failure(tail):
                if attempt == max_attempts:
                    raise HitlError("tests_not_runnable", tail[-500:])
                continue

            # valid red
            print(f"Test Architect: valid RED after attempt {attempt}", file=sys.stderr)
            return

        raise HitlError("tests_not_runnable", "exhausted attempts")

    # --- coder + judge ---

    def _coder_and_judge(self) -> None:
        assert self.task
        judge_feedback: list[str] = []
        for iteration in range(1, self.max_iter + 1):
            self.state.phase = "coder"
            self.state.iteration = iteration
            self.store.save(self.state)
            ensure_budget(self.client, self.state, self.store)

            force_strong = self.state.same_error_streak >= 2 or self.state.model_escalated
            model = coder_model(self.profile, iteration, force_strong)
            if model == self.profile.strong:
                self.state.model_escalated = True
            self.state.current_model = model
            self.store.save(self.state)

            prompt = self.store.agent_dir / "prompt.txt"
            parts = [
                "Implement the product code so that all tests pass.",
                "Do NOT modify tests/acceptance_generated or .agent/ (they are read-only).",
                "",
                self.task.raw,
            ]
            if self.state.last_test_log_tail:
                parts += ["", "LAST TEST FAILURE:", self.state.last_test_log_tail]
            if judge_feedback:
                parts += ["", "SPEC JUDGE ISSUES:"] + [f"- {x}" for x in judge_feedback]
            prompt.write_text("\n".join(parts), encoding="utf-8")

            # Heuristic editable set: python package files under project root
            editable = self._guess_editable_files()
            # prompt is under .agent which is RO in coder mode — write prompt before RO mount;
            # docker mounts .agent RO but prompt already written on host.
            # For message-file inside RO .agent — readable OK.
            # Problem: we need to update prompt each iter on host — host write works; container sees it via bind mount.

            aider_res = self.docker.run_aider(
                self.project,
                model=model,
                message_file=prompt,
                editable=editable,
                ro_agent=True,
            )
            self._save_log("coder", iteration, aider_res.stdout + aider_res.stderr)

            test_res = self.docker.run_tests(self.project, ro_agent=True)
            tail = test_res.combined_tail
            self.state.last_test_log_tail = tail
            self._save_log("verify", iteration, tail)

            if test_res.exit_code == 0:
                # Spec Judge
                if self._spec_judge():
                    return
                judge_feedback = list(self.state.judge_issues)
                continue

            h = error_hash(tail)
            if h == self.state.last_error_hash:
                self.state.same_error_streak += 1
            else:
                self.state.same_error_streak = 1
                self.state.last_error_hash = h
            self.store.save(self.state)

            if self.state.same_error_streak >= 3 and self.state.model_escalated:
                raise HitlError("stuck_loop", f"hash={h}")

            print(
                f"Coder iter {iteration}: tests failed (streak={self.state.same_error_streak})",
                file=sys.stderr,
            )

        raise HitlError("max_iter_exceeded", f"max_iter={self.max_iter}")

    def _acceptance_still_stub(self) -> bool:
        path = self.project / "tests" / "acceptance_generated" / "test_acceptance.py"
        if not path.is_file():
            return True
        text = path.read_text(encoding="utf-8")
        return "test_acceptance_pending" in text or "not generated yet" in text

    def _write_run_tests_sh(self, path: Path, stack: str) -> None:
        # Use ${PYTHONPATH:-} — plain $PYTHONPATH breaks under `set -u`.
        if stack == "python":
            body = (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "cd /workspace\n"
                "export PYTHONPATH=\"/workspace${PYTHONPATH:+:$PYTHONPATH}\"\n"
                "pytest -q tests/acceptance_generated\n"
                "pytest -q tests --ignore=tests/acceptance_generated\n"
            )
        else:
            body = (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "cd /workspace\n"
                "pytest -q tests/acceptance_generated\n"
            )
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _guess_editable_files(self) -> list[str]:
        candidates: list[str] = []
        for pattern in ("*.py", "src/**/*.py", "lib/**/*.py"):
            for path in self.project.glob(pattern):
                rel = path.relative_to(self.project).as_posix()
                if rel.startswith("tests/") or rel.startswith(".agent/"):
                    continue
                candidates.append(rel)
        # Always allow creating/editing a simple module if empty project
        if not candidates:
            main = self.project / "greet.py"
            if not main.exists():
                main.write_text("", encoding="utf-8")
            candidates.append("greet.py")
        return sorted(set(candidates))[:40]

    def _spec_judge(self) -> bool:
        assert self.task
        self.state.phase = "spec_judge"
        self.store.save(self.state)
        ensure_budget(self.client, self.state, self.store)

        diff = git_ops.working_diff(self.project, self.state.base_sha)
        if not diff.strip():
            raise HitlError("empty_diff", "tests passed but no code diff")

        system = (
            "You are a strict acceptance judge. Compare the git diff to the task. "
            'Reply ONLY JSON: {"passed": bool, "issues": [str]}. '
            "Fail only on violated Acceptance Criteria or Constraints."
        )
        user = f"TASK:\n{self.task.raw}\n\nDIFF:\n{diff}"
        data = self._llm_json(self.profile.judge, system, user, phase="judge")
        passed = bool(data.get("passed"))
        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        self.state.judge_issues = [str(x) for x in issues]
        self.store.save(self.state)
        if passed:
            print("Spec Judge: PASSED", file=sys.stderr)
            return True
        if not issues:
            # passed false without issues — treat as fail with generic
            self.state.judge_issues = ["judge returned passed=false without issues"]
        print(f"Spec Judge: FAILED ({len(self.state.judge_issues)} issues)", file=sys.stderr)
        return False

    # --- cleanup ---

    def _cleanup_success(self) -> None:
        self.state.phase = "cleanup"
        refresh_spent(self.client, self.state, self.store)
        self.store.save(self.state)

        if not self.keep_tests:
            acc = self.project / "tests" / "acceptance_generated"
            if acc.exists():
                shutil.rmtree(acc)
        if self.store.agent_dir.exists():
            shutil.rmtree(self.store.agent_dir)
        git_ops.remove_excludes(self.project)

        msg = f"agent: {self.state.task_id} (spent=${self.state.spent_usd:.4f}, iters={self.state.iteration})"
        self.commit_sha = git_ops.commit_all(self.project, msg)
        self.state.phase = "done"
        self.state.status = "success"
        # state dir removed — skip save
        print(f"Committed {self.commit_sha}", file=sys.stderr)

    def _handle_hitl(self, exc: HitlError) -> None:
        print(str(exc), file=sys.stderr)
        try:
            refresh_spent(self.client, self.state, self.store)
        except Exception:  # noqa: BLE001
            pass
        self.state.status = "hitl"
        self.state.phase = "hitl"
        self.state.hitl_reason = exc.reason
        self.state.hitl_detail = exc.detail
        try:
            self.store.save(self.state)
        except Exception:  # noqa: BLE001
            pass

    def _emit_report(self, status: str, hitl_reason: str | None = None) -> None:
        report = {
            "status": status,
            "branch": self.state.branch,
            "iterations": self.state.iteration,
            "spent_usd": round(self.state.spent_usd, 6),
            "hitl_reason": hitl_reason or self.state.hitl_reason,
            "commit": self.commit_sha,
        }
        print(json.dumps(report, ensure_ascii=False))

    def _save_log(self, phase: str, n: int, text: str) -> None:
        log_dir = self.store.agent_dir / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"{phase}-{n}.txt").write_text(text[-100_000:], encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
