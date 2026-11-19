# Shortleash

Autonomous TDD agent for a **single** coding task: turn a Markdown spec into a git branch with working code — cheaply, in Docker, with a soft spend cap.

Shortleash writes acceptance tests first, locks them read-only so the model cannot game them, loops an editor (Aider) until tests pass, then runs an LLM “spec judge” on the diff. On success it commits once. On ambiguity, budget exhaustion, or a stuck loop it stops and escalates to a human (HITL).

The target repository does **not** need Shortleash sources. You only need the CLI + sandbox image on the host, a clean git tree, and a task file.

## How it works

1. **Preflight** — cheap model checks that the task is unambiguous  
2. **Test Architect** — generates acceptance tests (TDD red)  
3. **Coder loop** — Aider edits product code in Docker; acceptance tests are mounted read-only  
4. **Spec Judge** — checks the diff against the written requirements  
5. **Commit** — one commit on `agent/task-<slug>` (or HITL with progress left on the branch)

## Requirements

- Linux host with **Docker**
- **Python 3.11+**
- **OpenRouter** API key (`OPENROUTER_API_KEY`)
- Target project: **git** repo with a **clean** working tree

MVP stack focus: **Python / pytest**. Other stacks are not fully supported yet.

## Install

```bash
git clone https://github.com/dobryakov/ai-shortleash.git
cd ai-shortleash

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

docker build -t dev-agent-sandbox:0.1.0 sandbox/

cp .env.example .env
# put your OpenRouter key in .env
```

Optional (Claude Code / Claude skills): symlink the skill into your personal skills dir:

```bash
ln -s "$(pwd)/.claude/skills/shortleash" ~/.claude/skills/shortleash
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | Required. Used for host LLM calls and Aider in the sandbox |
| `AGENT_RUN_SANDBOX_IMAGE` | Docker image (default `dev-agent-sandbox:0.1.0`) |
| `AGENT_RUN_MODELS_FILE` | Optional YAML with model profile overrides |
| `SHORTLEASH_HOME` / `AGENT_RUN_HOME` | Path to this clone (useful when invoking via the skill from another repo) |

Budget control is **soft**: Shortleash records usage at start and stops when `spent >= --budget`. There is no per-task key provisioning in MVP.

## Task file format

```markdown
## Task

What to implement.

## Constraints

Limits (or `None`).

## Acceptance Criteria

1. Concrete, testable condition
2. …
```

Vague criteria (`works well`, `clean code`) will often fail preflight or produce weak tests.

## Usage

```bash
source .venv/bin/activate
set -a && source .env && set +a

agent-run \
  --project /path/to/target/repo \
  --task /path/to/task.md \
  --budget 0.50 \
  --max-iter 8
```

Useful flags:

- `--keep-tests` — keep `tests/acceptance_generated/` after success  
- `--sandbox-image` — override the Docker image  
- `--model-profile` — named model cascade (default `default`)

The last line of stdout is a JSON report, for example:

```json
{"status":"SUCCESS","branch":"agent/task-…","iterations":1,"spent_usd":0.001,"hitl_reason":null,"commit":"abc1234"}
```

### Smoke fixture

```bash
./fixtures/smoke-repo/bootstrap_git.sh
agent-run \
  --project fixtures/smoke-repo \
  --task fixtures/tasks/implement-greet.md \
  --budget 0.50
```

Reset the fixture between runs (`git checkout main`, drop `agent/*` branches, clean tree).

## Exit codes (short)

| Code | Meaning |
|------|---------|
| 0 | Success |
| 10–16 | HITL (ambiguous task, budget, stuck loop, bad tests, …) |
| 20 | Dirty / not a git repo |
| 21 | Docker / image problem |
| 22 | OpenRouter auth / API error |
| 23 | Invalid CLI / task.md |

## Design

Full design notes: [`specs/00-propose.md`](specs/00-propose.md).

## Status

Early MVP. Expect sharp edges around model availability on OpenRouter, non-Python repos, and network hardening of the sandbox. Contributions and issue reports welcome once the repo is public.

## License

Shortleash is released under the [MIT License](LICENSE).

The coder loop is built on [Aider](https://github.com/Aider-AI/aider) ([aider.chat](https://aider.chat/)), which is licensed under the [Apache License 2.0](https://github.com/Aider-AI/aider/blob/main/LICENSE.txt).
