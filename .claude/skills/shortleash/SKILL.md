---
name: shortleash
description: >-
  Runs Shortleash (autonomous TDD agent: Aider-in-Docker, soft budget, RO
  acceptance tests) against any local git repo from a Markdown task file. Use
  whenever the user asks for shortleash, agent-run, to run aider on a task,
  delegate coding to the autonomous agent, «запусти агента», «сделай через
  shortleash/aider», or wants hands-off implement-from-acceptance-criteria
  work in the current or another project — even if that project has no
  Shortleash sources.   Do not re-implement the task yourself when the user
  wants the agent to run it. If the target repo is dirty, ask
  commit-or-stash before running; if stashed, stash pop after the run.
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
| Целевой git | `--project` — git-репо; перед запуском дерево должно стать чистым (см. §1a) |

### Резолв `SHORTLEASH_HOME` (без хардкода путей машины)

Никогда не вшивай абсолютные пути хоста (`/home/…`, `/Users/…`, буквы дисков) в скилл, правила, спеки или примеры — репозиторий публичный.

1. Если задан env `SHORTLEASH_HOME` или `AGENT_RUN_HOME` — использовать его.
2. Иначе найти clone Shortleash **обходом вверх** от реального файла скилла (после `readlink -f`), пока не появится маркер репо (`pyproject.toml` + каталог `sandbox/` + entrypoint `.venv/bin/agent-run` или `src/agent_run/`):

```bash
skill_md="$(readlink -f "${HOME}/.claude/skills/shortleash/SKILL.md")"
d="$(dirname "$skill_md")"
SHORTLEASH_HOME=""
while [[ "$d" != "/" ]]; do
  if [[ -f "$d/pyproject.toml" && -d "$d/sandbox" ]]; then
    SHORTLEASH_HOME="$d"
    break
  fi
  d="$(dirname "$d")"
done
```

3. Если не нашли — спросить у пользователя путь к clone (не записывать его обратно в скилл/репо).

Если venv/образа нет — сначала в `$SHORTLEASH_HOME`:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker build -t dev-agent-sandbox:0.1.0 sandbox/
```

## Workflow

### 1. Уточни только если неясно

- путь к проекту (default: текущий git root);
- бюджет USD (default: `0.50`);
- `max-iter` (default: `8`).

Не расписывай архитектуру агента — сразу готовь задачу и запуск.

### 1a. Грязное дерево — спросить commit или stash

Перед `agent-run` проверь `git status --porcelain` в `--project`.

Если дерево **чистое** — продолжай.

Если **грязное** — **не** решай сам и **не** запускай агента. Покажи краткий список изменений и спроси пользователя одним вопросом:

> В целевом репо есть незакоммиченные изменения. Закоммитить их или убрать в stash на время прогона?

| Ответ | Действие |
|---|---|
| **commit** | закоммитить изменения (сообщение уточни, если не дали); дождись чистого дерева |
| **stash** | `git stash push -u -m "shortleash: auto-stash before agent-run"` (или с явным pathspec, если пользователь указал что именно); запомни, что stash сделан тобой для этого прогона |
| отказ / отмена | остановись, не запускай |

После **stash** обязательно восстанови в конце прогона (SUCCESS, HITL или сбой CLI) — см. §5a.
Не делай silent stash/commit без ответа пользователя. Не путай этот stash с чужими записями в `git stash list`: pop только тот, что создал этот прогон (по сообщению / `stash@{0}` сразу после push, если список не трогали).

### 2. Создай task.md

Положи файл **вне** продукта или во временный путь, например `"${TMPDIR:-/tmp}/shortleash-tasks/<slug>.md"` (вне продукта).

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
  --project "$TARGET_REPO" \
  --task "$TASK_FILE" \
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
| 20 | dirty / not git | дерево всё ещё грязное / не git — пройти §1a или инициализировать репо |
| 21 | docker | собрать образ |
| 22 | openrouter | ключ / rate limit |
| 23 | bad CLI/task.md | починить секции task.md |

При HITL прогресс остаётся в ветке `agent/task-*` и (часто) в `.agent/` — не удалять без спроса.

### 5. После SUCCESS

Кратко отчитайся: `branch` (agent), `base_branch`, `commit` (deliverables на базе), `agent_commit` (полный на agent), spent_usd, iterations. Предложи `git log` / `git show` в целевом репо. **Не** пушь без явной просьбы.

Два commit’а, затем автопереключение на базу:
- `agent/task-*` — полный след: deliverables + служебное (`.agent/`, `.aider.chat.history.md`, …); ветка сохраняется для аудита, смотреть её не нужно;
- базовая ветка (`master`/`main`/…) — **только** deliverables (+ `tests/acceptance_generated/` если был `--keep-tests`); HEAD после SUCCESS на базе.

### 5a. Восстановить stash (обязательно, если §1a = stash)

Если перед прогоном делали stash по выбору пользователя — **после** разбора результата (и при HITL/ошибке тоже) верни изменения:

```bash
cd "$TARGET_REPO"
git stash pop
# при конфликте — не потеряй stash: сообщи пользователю, покажи conflict files, оставь stash в списке
```

Делай это на той ветке, где оказался HEAD после `agent-run` (обычно база после SUCCESS). Сообщи, что локальные незакоммиченные файлы восстановлены.  
Если stash не делали — ничего не pop’ай.

## Чего не делать

- Не копировать `src/agent_run` в целевой проект.
- Не запускать Aider на хосте напрямую — только через Shortleash CLI `agent-run` (песочница + RO acceptance).
- Не реализовывать задачу руками, если пользователь просил агента.
- Не коммитить `.env` / ключи.
- Не хардкодить в скилле/доках/правилах абсолютные пути машины (`/home/…`, `/Users/…`); только `$HOME`, `$SHORTLEASH_HOME`, `$TARGET_REPO`, обход вверх от скилла.
- Не stash/commit грязного дерева молча — только после явного выбора пользователя (§1a).
- Не забывать `git stash pop` в конце, если в §1a выбрали stash.

## Env reference

| Variable | Role |
|---|---|
| `SHORTLEASH_HOME` / `AGENT_RUN_HOME` | путь к clone Shortleash |
| `OPENROUTER_API_KEY` | единый ключ (soft budget) |
| `AGENT_RUN_SANDBOX_IMAGE` | default `dev-agent-sandbox:0.1.0` |
| `AGENT_RUN_MODELS_FILE` | optional `models.yaml` |

Подробности дизайна: `$SHORTLEASH_HOME/specs/00-propose.md` (читать только если нужна отладка пайплайна).
