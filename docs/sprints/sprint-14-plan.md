# Sprint 14 — план (bootstrap completeness hotfix)

- Окно: ~1 рабочий день после Sprint 13.
- Цель: закрыть production-readiness пробелы, обнаруженные через
  настоящий end-to-end smoke на чистом docker-compose стенде.

## Откуда взялись задачи

Sprint 13 закрыл C-список аудита. Все unit-тесты зелёные, все четыре
test-suite'а проходят, и UI с Sprint 13 фичами (dark mode, popover,
mobile) работает в проде. Однако **первый запуск свежего стенда** на
Windows + Docker Desktop вскрыл четыре gap'а, которые не ловятся
тестами и не описаны в `docs/troubleshooting.md`:

1. **Нет seed-механизма для админа.** `infra/postgres/init.sql`
   создаёт таблицу `users`, но не вставляет ни одного пользователя.
   Login screen заявляет дефолтный `admin@example.com / admin`, а в
   БД его нет — попытка логина возвращает 401.

2. **ClickHouse `init.sql` не отрабатывает на старом volume.**
   docker-entrypoint выполняет `*.sql` только при первом инициализации.
   Если schema поменялась после, materialized views не появляются.
   Endpoint `/api/v1/metrics/overview` возвращает 500 (404 от ClickHouse
   на отсутствующую view `top_attacks_lifetime`).

3. **`remote_ip` пустой у modsec-событий.** Vector remap пытается
   достать `transaction.remote_address`, но в JSON ModSec audit сейчас
   это поле либо отсутствует, либо называется `client_ip`. Результат:
   uniqExact(remote_ip) считает только access-row'ы, теряя реальные
   атакующие источники.

4. **`init.sql` отстал от финальной schema.** Колонка `artifact_path`
   в `ml_models` появилась через alembic-миграцию, в init.sql её нет.
   Прямые INSERT'ы в БД на бутстрапе ML-модели падают на
   `not-null constraint`.

Ни один из них не блокировал unit-тесты (тесты гоняются на in-memory
repos и моках) — но все четыре блокировали реальный smoke-flow.

## Скоуп

**Что входит** (минимальный hotfix, без переписывания):

- Alembic 0003 миграция: idempotent INSERT админа с argon2id-хешем.
- `make ch-migrate` / `.\dev.ps1 ch-migrate` — re-apply init.sql на
  работающий ClickHouse.
- `make bootstrap` / `.\dev.ps1 bootstrap` — однострочник, склеивающий
  alembic + ch-migrate в правильном порядке.
- Vector remap fix: пробуем `client_ip`, потом `remote_address`, потом
  верхний `client_ip`. Первое непустое выигрывает.
- README: новая секция "First-time bootstrap" с явной инструкцией.
- Sprint 14 plan + summary доки.

**Что не входит** (отложено в Sprint 15+):

- ClickHouse migration tool (отдельный path-controller). Re-apply init.sql
  через bootstrap-таргет — рабочий минимум; полноценный migration-runner
  уровня Alembic — отдельная проектная задача.
- Custom CLI `bootstrap-admin --email --password` через argon2id at
  runtime — требует дополнительной зависимости в alembic env. Текущий
  hardcoded хеш для пароля `admin` совпадает с `tests/conftest.py`,
  один источник истины.
- AWS WAF integration test, mTLS — не Sprint 14 темы.

## Тесты

Sprint 14 — это инфраструктура и миграции, а не новый функционал.
Регрессионные риски:

- Alembic 0003 не должна ломать существующие тесты (они уже работают
  с in-memory `seed_users`, не зависят от реальной БД).
- Vector конфиг — статически валиден; для модсек-IP сделаем запрос
  через прокси, проверим, что новая строка в `traffic_log` имеет
  непустой `remote_ip`.

Финальный прогон: backend / ml / ml-service / bench + ruff. Должны быть
≈210 тестов pass без изменений в количестве.

## Артефакты

- `backend/alembic/versions/0003_seed_admin_user.py` — миграция.
- `dev.ps1` + `Makefile` — таргеты `ch-migrate`, `bootstrap`.
- `infra/vector/vector.toml` — modsec_decode remap fix.
- `README.md` — обновлённая секция "Boot the stack".
- `docs/sprints/sprint-14-plan.md`, `sprint-14-summary.md` — этот документ
  и итоги.

## Ожидаемый эффект

После Sprint 14 на чистом стенде:

```bash
make up
make bootstrap       # ← теперь это всё, что нужно
```

→ login `admin@example.com / admin` сразу работает,
→ Dashboard показывает realtime метрики,
→ Incidents page заполняется, modsec-row'ы имеют корректный `remote_ip`,
→ Sprint 13 фичи (dark mode, popover, security headers) работают как
   подтверждено в Sprint 13 summary.
