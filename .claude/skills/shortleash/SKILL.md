---
name: shortleash
description: >-
  Runs Shortleash (autonomous TDD agent: Aider-in-Docker, soft budget, RO
  acceptance tests) against any local git repo from a Markdown task file. Use
  whenever the user asks for shortleash, agent-run, to run aider on a task,
  delegate coding to the autonomous agent, «запусти агента», «сделай через
  shortleash/aider», or wants hands-off implement-from-acceptance-criteria
  work in the current or another project — even if that project has no
  Shortleash sources. Do not re-implement the task yourself when the user
  wants the agent to run it.
---

# Shortleash — автономный TDD-агент в чужом репо

Целевой проект **не** должен содержать исходники Shortleash. Оркестратор живёт отдельно; скилл только готовит `task.md` и запускает CLI (`agent-run`).

## Preconditions (проверить до запуска)

| Требование | Как проверить |
|---|---|
| Репо Shortleash | `SHORTLEASH_HOME` (см. резолв ниже) |
| venv | `$SHORTLEASH_HOME/.venv/bin/agent-run` существует |
| Docker-образ | `docker image inspect "${AGENT_RUN_SANDBOX_IMAGE:-dev-agent-sandbox:0.1.0}"` |
| API key | `OPENROUTER_API_KEY` в env или в `$SHORTLEASH_HOME/.env` |
| Целевой git | `--project` — git-репо с **чистым** working tree |

### Резолв `SHORTLEASH_HOME` (без хардкода путей машины)

1. Если задан env `SHORTLEASH_HOME` или `AGENT_RUN_HOME` — использовать его.
2. Иначе, если скилл подключён симлинком из clone Shortleash:
   `SHORTLEASH_HOME="$(cd "$(dirname "$(readlink -f "$HOME/.claude/skills/shortleash/SKILL.md)")/../.." && pwd)"`
3. Иначе — спросить у пользователя путь к clone репозитория `shortleash`.

Если venv/образа нет — сначала в `$SHORTLEASH_HOME`:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker build -t dev-agent-sandbox:0.1.0 sandbox/
```

Если дерево грязное — **не** запускать: попросить пользователя закоммитить/stash (exit 20).

## Workflow

### 1. Уточни только если неясно

- путь к проекту (default: текущий git root);
- бюджет USD (default: `0.50`);
- `max-iter` (default: `8`).

Не расписывай архитектуру агента — сразу готовь задачу и запуск.

### 2. Создай task.md

Положи файл **вне** продукта или во временный путь, например `/tmp/shortleash-tasks/<slug>.md`.

Обязательные секции (заголовки точно такие):

```markdown
## Task

<что сделать>

## Constraints

<ограничения; можно «None»>

## Acceptance Criteria

1. <проверяемое условие>
2. <…>
```

Критерии должны быть однозначными и проверяемыми автотестами. Неясные → агент остановится с HITL `ambiguous_task`.

Шаблон: `references/task-template.md` (читать при сомнении в формате).

### 3. Запусти агент

```bash
# Resolve SHORTLEASH_HOME as in Preconditions
export SHORTLEASH_HOME="${SHORTLEASH_HOME:-${AGENT_RUN_HOME:?set SHORTLEASH_HOME to your shortleash clone}}"
export AGENT_RUN_SANDBOX_IMAGE="${AGENT_RUN_SANDBOX_IMAGE:-dev-agent-sandbox:0.1.0}"
set -a
# shellcheck disable=SC1091
[[ -f "$SHORTLEASH_HOME/.env" ]] && source "$SHORTLEASH_HOME/.env"
set +a

"$SHORTLEASH_HOME/.venv/bin/agent-run" \
  --project /ABS/PATH/TO/TARGET/REPO \
  --task /ABS/PATH/TO/task.md \
  --budget 0.50 \
  --max-iter 8
```

Опционально: `--keep-tests` — оставить `tests/acceptance_generated/`.

Долгие прогоны (минуты) — не убивать процесс раньше времени; дождаться JSON-отчёта в stdout.

### 4. Разбери результат

Последняя строка stdout — JSON:

```json
{"status":"SUCCESS|HITL","branch":"agent/task-…","iterations":N,"spent_usd":0.0,"hitl_reason":null,"commit":"abc or null"}
```

| Exit | Значение | Что сказать пользователю |
|---|---|---|
| 0 | SUCCESS | ветка + commit; краткий diff |
| 10 | ambiguous_task | показать QUESTIONS; уточнить ТЗ |
| 11 | budget_exceeded | поднять `--budget` или сузить задачу |
| 12 | stuck_loop | агент зациклился; нужна ручная помощь |
| 13 | tests_not_runnable | починить формулировку критериев |
| 14 | max_iter_exceeded | больше итераций / яснее задача |
| 15 | tests_already_green | критерии уже выполнены или слишком слабые |
| 20 | dirty / not git | commit/stash |
| 21 | docker | собрать образ |
| 22 | openrouter | ключ / rate limit |
| 23 | bad CLI/task.md | починить секции task.md |

При HITL прогресс остаётся в ветке `agent/task-*` и (часто) в `.agent/` — не удалять без спроса.

### 5. После SUCCESS

Кратко отчитайся: branch, commit, spent_usd, iterations. Предложи `git log` / `git show` в целевом репо. **Не** пушь без явной просьбы.

## Чего не делать

- Не копировать `src/agent_run` в целевой проект.
- Не запускать Aider на хосте напрямую — только через Shortleash CLI `agent-run` (песочница + RO acceptance).
- Не реализовывать задачу руками, если пользователь просил агента.
- Не коммитить `.env` / ключи.

## Env reference

| Variable | Role |
|---|---|
| `SHORTLEASH_HOME` / `AGENT_RUN_HOME` | путь к clone Shortleash |
| `OPENROUTER_API_KEY` | единый ключ (soft budget) |
| `AGENT_RUN_SANDBOX_IMAGE` | default `dev-agent-sandbox:0.1.0` |
| `AGENT_RUN_MODELS_FILE` | optional `models.yaml` |

Подробности дизайна: `$SHORTLEASH_HOME/specs/00-propose.md` (читать только если нужна отладка пайплайна).
