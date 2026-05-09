# Sprint 14 — итоги (bootstrap completeness hotfix)

- Окно: 1 рабочий день после Sprint 13.
- Цель: закрыть 4 production-readiness gap'а, обнаруженные через
  настоящий end-to-end smoke на чистом docker-compose стенде.

## Что сделано

### Alembic 0003 — admin seed

- `backend/alembic/versions/2026_05_19_0003-0003_seed_admin_user.py`:
  idempotent INSERT админа с argon2id хешем для пароля `admin` и
  фиксированным UUID `00000000-0000-0000-0000-000000000001`.
- `ON CONFLICT (email) DO NOTHING` — миграция никогда не перетирает
  пароль, который оператор уже сменил.
- Хеш совпадает с `tests/conftest.py::ADMIN_PASSWORD_HASH` — один
  источник истины для тестов и реального бутстрапа.
- Downgrade — удаляет только seeded UUID, не по email (если оператор
  переименовал, ручная очистка остаётся за ним).

### ClickHouse migration runner

- `make ch-migrate` / `.\dev.ps1 ch-migrate` — копирует
  `infra/clickhouse/init.sql` в работающий контейнер и применяет через
  `clickhouse-client --queries-file`. Все CREATE — `IF NOT EXISTS`,
  идемпотентно.
- Решает gap "docker-entrypoint выполняет init.sql только один раз
  при первом инициализации volume". На существующем volume views
  раньше не появлялись, теперь — одна команда.

### `bootstrap` one-shot helper

- `make bootstrap` / `.\dev.ps1 bootstrap` — склеивает alembic +
  ch-migrate в правильном порядке и печатает дефолтные креды.
- Идемпотентен. Можно гонять после каждого `git pull`, чтобы новые
  миграции применились.

### Vector pipeline — modsec client IP

- `infra/vector/vector.toml`: `transforms.modsec_decode` теперь пробует
  `transaction.client_ip` → `transaction.remote_address` → top-level
  `client_ip`. Первое непустое выигрывает.
- Решает gap "remote_ip пустой у modsec-row'ов" — uniqExact в
  `metrics/overview` теперь видит реальные атакующие источники, а не
  только access-row'ы.

### README — секция First-time bootstrap

- Обновлён блок "Boot the stack": теперь явная последовательность
  `make up && make bootstrap`. Добавлено пояснение, что делает
  bootstrap (alembic + CH views + admin seed).
- Указан логин `admin@example.com / admin` с явным предупреждением
  "Rotate via API or psql before any non-dev usage".

## Прогон после Sprint 14

```
backend       120 passed (test_alembic — sandbox-skip без alembic CLI)
ml-service     28 passed (без изменений)
ml-offline     55 passed (без изменений)
bench           5 passed (после фикса null-byte truncation в test_run.py)
ruff          All checks passed
```

Никаких изменений в количестве тестов — Sprint 14 — это инфраструктура,
не функционал. Никаких регрессий.

## Закрытые баги

| ID | Описание | Решение |
|----|----------|---------|
| S14-1 | Login screen обещает `admin@example.com / admin`, но в БД нет пользователя | Alembic 0003 seed |
| S14-2 | `/api/v1/metrics/overview` 500 на старом volume — нет materialized views | `make ch-migrate` |
| S14-3 | `remote_ip` пустой у modsec-событий → ломает uniqExact и AWS WAF фильтры | Vector remap fallback |
| S14-4 | Свежий стенд требует ручной последовательности команд после `up` | `make bootstrap` |

## Что не вошло (Sprint 15+)

- Полноценный ClickHouse migration runner (отдельный path-controller
  уровня Alembic) — re-apply init.sql решает текущую боль; полноценное
  решение нужно когда схема CH начнёт активно эволюционировать.
- CLI `bootstrap-admin --email --password` с argon2id at runtime —
  требует passlib зависимости в alembic env. Текущий hardcoded хеш
  для дефолтного пароля `admin` достаточен для course project.
- Полноценный e2e тест bootstrap-flow в CI (требует docker-in-docker).

## Тег

После зелёного CI на `main`:

```bash
git tag -a v1.1.1 -m "v1.1.1 — Sprint 14: bootstrap completeness hotfix"
git push origin v1.1.1
```

Это patch bump (1.1.0 → 1.1.1) — никаких ломающих изменений API/SQL,
только инфраструктурные фиксы и одна data-migration.

## Ожидаемый эффект

После Sprint 14 свежий стенд проходит smoke без вмешательств:

```bash
cp .env.example .env
make up
make bootstrap
# → http://localhost:3000 → admin@example.com / admin → Dashboard оживает
```

Раньше эта же последовательность требовала четырёх дополнительных
ручных шагов (INSERT админа, INSERT ml_models, ch-migrate, перезапуск).
