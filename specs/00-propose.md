# Техническая спецификация: Autonomous TDD Runner (`agent-run`)

Статус: **design-ready draft** (можно реализовывать MVP по этой спеке)  
Версия: **0.2**  
Связанные артефакты: `fixtures/smoke-repo/` (эталонный репозиторий для AC; создаётся на этапе реализации)

---

## 1. Цель и приоритеты

CLI-утилита для Linux-сервера: полностью автономно выполняет **одну** задачу программирования по текстовому описанию и текстовым критериям приёмки.

Приоритеты (в порядке убывания при конфликте):

1. **Контроль стоимости** — дешёвые модели через OpenRouter, жёсткий per-task budget.
2. **Изоляция** — всё исполнение кода и Aider только в Docker.
3. **Anti-reward-hacking** — сгенерированные acceptance-тесты физически read-only для Coder.
4. **Предсказуемые сбои** — при неоднозначности / бюджете / тупике → HITL, без «тихого» успеха.
5. **Минимум участия человека** — HITL только в нештатных ситуациях из §12.

Вне скоупа MVP: мульти-агентная оркестрация, UI, параллельные задачи в одном репо, авто-PR в remote, поддержка не-git проектов.

---

## 2. Технологический стек

| Компонент | Выбор |
|-----------|--------|
| Host Orchestrator | Python 3.11+ |
| Редактор кода в sandbox | Aider (headless: `--yes-always --no-auto-commits`) |
| Изоляция | Docker Engine (Docker CLI или Docker SDK for Python) |
| LLM | OpenRouter: Provisioning API (лимитированные ключи) + Chat Completions |
| VCS | Git (целевой проект **обязан** быть git-репозиторием) |

Базовый образ sandbox: `dev-agent-sandbox:<semver>` (пин версии оркестратором; `latest` только для локальной разработки образа).

---

## 3. CLI-интерфейс

```bash
agent-run \
  --project /path/to/repo \
  --task /path/to/task.md \
  --budget 0.50 \
  --max-iter 8 \
  [--keep-tests] \
  [--notify telegram] \
  [--sandbox-image dev-agent-sandbox:0.1.0] \
  [--model-profile default]
```

| Флаг | Default | Описание |
|------|---------|----------|
| `--project` | — | Путь к git-репозиторию |
| `--task` | — | Markdown: задача, ограничения, критерии приёмки |
| `--budget` | `0.50` | Макс. расход USD на задачу (лимит временного ключа) |
| `--max-iter` | `8` | Макс. итераций Coder Loop (Фаза 2), без учёта попыток Test Architect |
| `--keep-tests` | `false` | Не удалять `tests/acceptance_generated/` перед финальным коммитом |
| `--notify` | off | Канал HITL/статуса (`telegram` — опционально, см. §14) |
| `--sandbox-image` | из конфига | Образ worker-песочницы |
| `--model-profile` | `default` | Именованный каскад моделей (§9) |

Коды выхода — §11.

---

## 4. Архитектура: Host vs Sandbox

### 4.1. Уровень 1 — Host Orchestrator (на хосте)

Ответственность:

- валидация CLI и чистоты git;
- создание ветки `agent/task-<slug>`;
- выпуск / опрос / отзыв временного OpenRouter-ключа;
- запись `.git/info/exclude`;
- вызов Chat Completions для Pre-flight и Spec Judge (с хоста);
- запуск/остановка Docker-контейнеров;
- запись и чтение `.agent/state.json`;
- формирование промптов в `.agent/prompt.txt`;
- детектор зацикливания, бюджет, HITL;
- финальный cleanup и **единственный** git commit успеха.

Host **не** запускает pytest/jest/Aider вне контейнера.

### 4.2. Уровень 2 — Worker Sandbox (эфемерный контейнер)

Ответственность:

- запуск Aider по `.agent/prompt.txt`;
- запуск `.agent/run_tests.sh`;
- любые package install / build, необходимые тестам (в пределах сети §10).

Контейнер: `--rm`, лимиты CPU/RAM, FS read-only кроме `/workspace` и tmpfs (см. §10).

### 4.3. Временные пути в целевом репо

| Путь | Назначение | Кто пишет |
|------|------------|-----------|
| `.agent/` | служебное (всегда в exclude) | Host |
| `.agent/prompt.txt` | текущий промпт Aider | Host |
| `.agent/run_tests.sh` | единая точка запуска тестов | Test Architect (sandbox), далее RO для Coder |
| `.agent/state.json` | телеметрия и статус | Host |
| `tests/acceptance_generated/` | сгенерированные acceptance-тесты | Test Architect; RO для Coder |

---

## 5. Контракты данных

### 5.1. `task.md` (вход)

Обязательные секции (заголовки Markdown, порядок свободен):

- `## Task` — что сделать
- `## Constraints` — ограничения (можно пусто, но секция обязательна)
- `## Acceptance Criteria` — нумерованный или маркированный список проверяемых условий

Pre-flight (§7.1) отвергает файл без этих секций или с пустыми Acceptance Criteria.

### 5.2. `.agent/state.json`

```json
{
  "version": 1,
  "task_id": "string",
  "branch": "agent/task-<slug>",
  "phase": "init|preflight|test_architect|coder|spec_judge|cleanup|done|hitl",
  "iteration": 0,
  "max_iter": 8,
  "budget_usd": 0.5,
  "spent_usd": 0.0,
  "model_profile": "default",
  "current_model": "provider/model-slug",
  "last_error_hash": null,
  "same_error_streak": 0,
  "test_architect_attempts": 0,
  "status": "running|success|hitl",
  "hitl_reason": null,
  "hitl_detail": null,
  "updated_at": "ISO-8601"
}
```

Host обновляет файл после каждого значимого шага (атомарно: write temp + rename).

### 5.3. Pre-flight response (JSON от модели)

```json
{
  "status": "OK|AMBIGUOUS",
  "questions": ["..."],
  "notes": ["optional clarifications that do not block"]
}
```

- `AMBIGUOUS` → HITL, если `questions` непустой.
- Невалидный JSON / отсутствие обязательных полей → одна повторная попытка с repair-промптом; затем HITL `preflight_invalid_response`.

### 5.4. Spec Judge response (JSON от модели)

```json
{
  "passed": true,
  "issues": ["..."]
}
```

- `passed: false` при непустом `issues` → возврат в Coder Loop с фидбеком.
- Невалидный JSON → одна repair-попытка; затем HITL `judge_invalid_response`.
- Пустой diff при входе в Judge → HITL `empty_diff` (нечего принимать).

### 5.5. Финальный отчёт (stdout, JSON Lines + human summary)

Последняя строка stdout при завершении — одна JSON-строка:

```json
{
  "status": "SUCCESS|HITL",
  "branch": "agent/task-...",
  "iterations": 3,
  "spent_usd": 0.12,
  "hitl_reason": null,
  "commit": "abc1234 or null"
}
```

---

## 6. Алгоритм (Init + три фазы)

### 6.1. Init

1. Проверить, что `--project` — git-репозиторий.
2. `git status --porcelain`: любое незакоммиченное изменение → exit `20` (грязное дерево).  
   Исключение: не требуется чистота ignored-файлов.
3. Вычислить `slug` из имени task-файла (kebab-case, max 40 символов) → ветка `agent/task-<slug>`. Если ветка существует — суффикс `-YYYYmmdd-HHMMSS`.
4. Создать и checkout ветку от текущего `HEAD`.
5. OpenRouter Provisioning API: создать ключ с `limit` = `--budget` (USD). Сохранить id ключа в памяти процесса / state (не в git).
6. Добавить в `.git/info/exclude` (если ещё нет):
   - `.agent/`
   - `tests/acceptance_generated/`
7. Создать `.agent/state.json` с `phase=init`.

Коммитов на Init нет.

### 6.2. Фаза 1 — Test Architect (TDD Red)

**Цель:** критерии приёмки → исполняемые тесты **до** основного кода.

#### 6.2.1. Pre-flight (с хоста)

Вход: полный `task.md` + усечённый `tree` проекта (depth ≤ 4, exclude `.git`, `node_modules`, `.venv`, `dist`, `build`).

Модель: класс `cheap` из profile (§9).

- `AMBIGUOUS` → HITL `ambiguous_task` (вопросы в stdout / notify).
- `OK` → далее.

#### 6.2.2. Генерация тестов (sandbox + Aider)

- Mount `/workspace` = project **rw**.
- Aider: write-allowlist **только** `tests/acceptance_generated/**` и `.agent/run_tests.sh`.
- Промпт требует: по одному (или логически сгруппированному) автотесту на каждый пункт Acceptance Criteria; `run_tests.sh` должен запускать **и** существующие тесты проекта (если обнаружены), **и** acceptance.

Обнаружение стека (Host, эвристика, первая победившая):

| Сигнал | Стек | Базовая команда в `run_tests.sh` |
|--------|------|----------------------------------|
| `pyproject.toml` / `pytest.ini` / `tests/` + `*.py` | Python | `pytest -q` |
| `package.json` с `jest` / `vitest` | Node | `npm test` / `npx vitest run` |
| `go.mod` | Go | `go test ./...` |
| иначе | unknown | Test Architect **обязан** создать `run_tests.sh`; если не смог — HITL |

Если в репо уже есть документированная команда тестов (скрипт `test` в `package.json`, tox, make target `test`) — предпочитать её и добавить acceptance-путь.

#### 6.2.3. Red Phase Check

Host запускает в контейнере `.agent/run_tests.sh`.

| Результат | Действие |
|-----------|----------|
| Падение по assertion / отсутствующему API / 404 логики | OK (Red), переход к Фазе 2 |
| Синтаксис тестов / runner не найден / import error в тестах | до **2** repair-попыток Test Architect |
| После 3 неудачных запусков (1 + 2 repair) тесты всё ещё не «валидно красные» | HITL `tests_not_runnable` |
| Все тесты **зелёные** на Фазе 1 | подозрительно: одна попытка усилить тесты; если снова green без изменений продукта — HITL `tests_already_green` (вероятно критерии уже удовлетворены или тесты пустые) |

«Валидно красные» = exit ≠ 0 и хвост лога **не** матчится эвристикам syntax/runner failure (список паттернов в коде оркестратора, версионируется).

После успешного Red: Host перечитывает checksums файлов acceptance + `run_tests.sh` в state (для аудита).

### 6.3. Фаза 2 — Coder Loop

Цикл `iteration = 1..max_iter`:

1. **Бюджет:** `GET` usage временного ключа. Если `spent >= budget` → HITL `budget_exceeded`.
2. **Модель:** по каскаду profile (§9); при `same_error_streak >= 2` — форс-эскалация класса модели.
3. **Контейнер Coder:**
   - `/workspace` rw;
   - overlay RO: `/workspace/tests/acceptance_generated`, `/workspace/.agent` (включая `run_tests.sh`);
   - `.env` → mount `/dev/null` ro (если файл есть);
   - не пробрасывать SSH keys, Docker socket, cloud creds;
   - Aider **без** write-доступа к RO-путям (дополнительно allowlist всех путей кроме RO).
4. Промпт: Task + Constraints + хвост ошибки предыдущей итерации (до 3000 символов) + issues от Spec Judge (если были).
5. **Verify:** снова `.agent/run_tests.sh` в контейнере.
   - exit ≠ 0 → MD5 от нормализованного хвоста (последние 3000 символов stdout+stderr; strip timestamps/pids). Если хеш == предыдущему → `same_error_streak++`, иначе `= 1`. Если `same_error_streak >= 3` **после** эскалации модели → HITL `stuck_loop`. Иначе следующая итерация.
   - exit == 0 → Фаза 3.
6. Если `iteration == max_iter` и тесты всё ещё красные → HITL `max_iter_exceeded`.

### 6.4. Фаза 3 — Spec Judge

1. `git diff <base>..HEAD` + unstaged/uncommitted changes в рабочем дереве (полный patch продукта; пути `.agent/` не включаются — их нет в git status благодаря exclude, но diff по ним игнорируется явно).
2. Запрос с хоста, модель класса `judge` (большой контекст, дешёвая).
3. Вход: `task.md` + diff. Инструкция: оценивать только нарушения Acceptance Criteria и Constraints; не требовать перфекционизма стиля вне Constraints.
4. `passed: false` → фидбек в Coder Loop (считается следующей итерацией; расходует `max_iter`).
5. `passed: true` → Cleanup (§8).

Лимит возвратов из Judge в Coder: не отдельный счётчик; общие `max_iter`. При исчерпании — HITL `max_iter_exceeded`.

---

## 7. Политика надёжности LLM-шагов

Для Pre-flight и Spec Judge:

1. Ответ парсится как JSON (допускается извлечение первого `{...}` из markdown fence).
2. Валидация по обязательным полям (§5.3 / §5.4).
3. При ошибке — **одна** repair-попытка («верни только валидный JSON по схеме»).
4. Повторный провал → HITL с соответствующей причиной.
5. Temperature: `0` для Pre-flight/Judge; для Coder — по profile (обычно `0`–`0.2`).

---

## 8. Завершение и очистка

Выполняется при SUCCESS (и частично при HITL — см. ниже).

### 8.1. SUCCESS

1. Отозвать временный OpenRouter-ключ (best-effort; ошибка отзыва → warning в stderr, не FAIL).
2. Если не `--keep-tests`: удалить `tests/acceptance_generated/`.
3. Удалить `.agent/` всегда.
4. Убрать добавленные строки из `.git/info/exclude` (только те, что оркестратор добавлял).
5. `git add -A` (осмысленные изменения продукта) + commit на текущей ветке.  
   Message: `agent: <slug> (spent=$X.XX, iters=N)`.
6. Stdout: human summary + JSON-строка (§5.5), exit `0`.

### 8.2. HITL

1. Сохранить `.agent/state.json` (`status=hitl`, reason/detail).
2. **Не** удалять ветку и прогресс кода.
3. Отозвать ключ (best-effort).
4. `.agent/` **оставить** для диагностики; `tests/acceptance_generated/` оставить.
5. Exit ≠ 0 по таблице §11.
6. Коммит при HITL **не** создаётся автоматически (дерево может быть грязным — это ожидаемо).

---

## 9. Model profiles (без хардкода устаревающих slug в логике)

Оркестратор читает profile из конфига (`~/.config/agent-run/models.yaml` или `AGENT_RUN_MODELS_FILE`).

Логические классы:

| Класс | Назначение |
|-------|------------|
| `cheap` | Pre-flight, быстрые итерации Coder 1–3 |
| `strong` | Test Architect; Coder с итерации 4+ или после streak ошибок |
| `judge` | Spec Judge (большой контекст) |

Пример `default` profile (значения — ориентир, обновляются конфигом, не кодом):

```yaml
profiles:
  default:
    cheap: deepseek/deepseek-chat
    strong: anthropic/claude-3.5-sonnet
    judge: google/gemini-2.0-flash-001
    coder_temperature: 0.1
```

Каскад Coder:

- iters 1–3: `cheap`
- iter ≥ 4 **или** `same_error_streak >= 2`: `strong`

Рекомендуемый budget split (мягкий, для метрик; жёсткий лимит один на ключ):

- Test Architect ≤ 40% бюджета
- Coder+Judge — остальное  
Превышение soft-split не останавливает задачу; останавливает только hard limit ключа.

---

## 10. Безопасность Docker-песочницы

1. `--rm` на каждый шаг.
2. `--memory=2g --cpus=1.5` (конфиг перекрывает).
3. Корень контейнера `--read-only`; `--tmpfs /tmp:rw,noexec,nosuid,size=512m`.
4. Сеть: отдельная bridge-сеть `agent-run-net`.
   - DNS разрешён (UDP/TCP 53) к резолверу Docker.
   - Egress: только 80/443 (и 53) через правила на хосте.
   - Запрет: `127.0.0.0/8`, link-local, RFC1918 хоста, metadata `169.254.169.254`, другие docker bridge.
   - IPv6: либо отключён в сети, либо те же deny-правила.
5. OpenRouter вызовы Pre-flight/Judge/usage — **с хоста**, не из sandbox. Sandbox получает только временный ключ для Aider → OpenRouter (443).
6. Секреты хоста не монтировать. Известные имена (`.env`, `.env.*`, `*.pem`) — mask через `/dev/null` ro при наличии.
7. Нет Docker socket, нет `--privileged`, нет `SYS_ADMIN`.
8. Запись в RO mount acceptance/`.agent` при Coder → ожидаемый errno; оркестратор не считает это «прогрессом».

---

## 11. Коды выхода

| Code | Meaning |
|------|---------|
| 0 | SUCCESS |
| 10 | HITL: `ambiguous_task` |
| 11 | HITL: `budget_exceeded` |
| 12 | HITL: `stuck_loop` |
| 13 | HITL: `tests_not_runnable` |
| 14 | HITL: `max_iter_exceeded` |
| 15 | HITL: `tests_already_green` |
| 16 | HITL: `preflight_invalid_response` / `judge_invalid_response` / `empty_diff` |
| 20 | Грязное git-дерево / не git-репо |
| 21 | Ошибка Docker / образа |
| 22 | Ошибка OpenRouter provisioning / auth |
| 23 | Невалидный CLI / task.md структура |
| 30 | Внутренняя ошибка оркестратора |

---

## 12. Сценарии HITL (сводка)

| Условие | reason | Code |
|---------|--------|------|
| Pre-flight AMBIGUOUS | `ambiguous_task` | 10 |
| spent ≥ budget | `budget_exceeded` | 11 |
| 3 одинаковых error-hash подряд после эскалации модели | `stuck_loop` | 12 |
| Test Architect не дал валидно красные тесты за 3 попытки | `tests_not_runnable` | 13 |
| Исчерпан `max_iter` | `max_iter_exceeded` | 14 |
| Тесты зелёные до написания кода и не усилены | `tests_already_green` | 15 |
| Сломанный JSON Pre-flight/Judge после repair | `*_invalid_response` | 16 |

При любом HITL: state сохранён, ветка с прогрессом оставлена, ключ отозван, понятное сообщение в stderr.

---

## 13. Git-модель

- База: `HEAD` на момент Init (`base_sha` в state).
- Рабочая ветка только локальная; push не выполняется в MVP.
- Промежуточные коммиты **не** создаются; один commit на SUCCESS.
- При HITL рабочее дерево может содержать незакоммиченные изменения — это артефакт для человека.
- Повторный запуск на той же задаче: новая ветка с timestamp-суффиксом (не overwrite).
- Конфликты с remote вне скоупа; upstream tracking не требуется.

---

## 14. Операционка

### 14.1. Установка (целевое)

```bash
pipx install agent-run   # или pip install -e .
# образ:
docker pull registry.example/dev-agent-sandbox:0.1.0
```

Переменные окружения хоста:

| Env | Назначение |
|-----|------------|
| `OPENROUTER_MANAGEMENT_KEY` | Provisioning API |
| `AGENT_RUN_SANDBOX_IMAGE` | default image |
| `AGENT_RUN_MODELS_FILE` | path к models.yaml |
| `AGENT_RUN_TELEGRAM_BOT_TOKEN` / `AGENT_RUN_TELEGRAM_CHAT_ID` | если `--notify telegram` |

### 14.2. Логи

- Host: structured logs в stderr (JSON или key=value), уровень `INFO`.
- Полные логи контейнеров: `.agent/logs/<phase>-<n>.txt` на время прогона (удаляются на SUCCESS cleanup; остаются на HITL).

### 14.3. Идемпотентность

Повторный `agent-run` с теми же аргументами всегда создаёт **новую** ветку; не продолжает чужой HITL-прогон автоматически. Продолжение — отдельная команда будущего скоупа (`agent-run resume`, не MVP).

### 14.4. Notify (опционально)

При HITL и SUCCESS: короткое сообщение (status, branch, spent, reason). Ошибка notify не меняет exit code задачи.

---

## 15. Контракт Aider в sandbox

Обязательные флаги:

```text
aider --yes-always --no-auto-commits --no-git
```

- `--no-git`: коммиты только у Host.
- Модель и API base/key: через env контейнера (`OPENROUTER_API_KEY` = временный ключ, `OPENAI_API_BASE` = OpenRouter compatible endpoint).
- Промпт читается из файла / argv, сформированного Host.
- Non-zero exit Aider при отсутствии изменений в allowlist → оркестратор передаёт stderr в следующий промпт (не HITL сразу).
- Версия Aider фиксируется в Dockerfile образа; Host при старте может проверить label `org.agent-run.aider-version`.

---

## 16. Критерии приёмки системы (AC)

Проверяются на fixture-репозитории `fixtures/smoke-repo` + task-файлах в `fixtures/tasks/`.

| ID | Сценарий | Ожидание |
|----|----------|----------|
| AC1 | Чёткая задача на fixture | SUCCESS: ветка, commit, тесты проходили на Judge-входе, spent > 0 |
| AC2 | `--budget 0.001` | HITL `budget_exceeded`, exit 11, до max-iter не доходит |
| AC3 | Coder пытается писать в `tests/acceptance_generated/` | запись блокируется OS (RO); прогон не SUCCESS из-за «исправленных» тестов |
| AC4 | Заведомо невыполнимая зависимость (нет внешнего сервиса) | HITL `stuck_loop` или `max_iter_exceeded` до 10 итераций; exit 12 или 14 |
| AC5 | Task без секции Acceptance Criteria | exit 23 или Pre-flight HITL 10 |
| AC6 | Грязное дерево git | exit 20, контейнер не стартует |

---

## 17. План реализации MVP (не часть рантайма)

1. Host skeleton: CLI, state, exit codes, git init-branch.
2. OpenRouter key lifecycle + budget poll.
3. Docker runner + RO overlays + сеть.
4. Фаза 1 (preflight + test architect + red check).
5. Фаза 2 (coder loop + error hash).
6. Фаза 3 (judge) + cleanup commit.
7. Fixture repo + AC1–AC6 в CI.

---

## 18. История

| Версия | Изменение |
|--------|-----------|
| 0.1 | Исходный черновик монолитом |
| 0.2 | Нормализована структура; контракты JSON/exit codes; Host vs Sandbox; model profiles; git/ops/Aider контракты; уточнены security и AC |
