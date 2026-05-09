# Sprint 11 — hotfix по результатам аудита

После закрытия Sprint 11 был проведён мульти-перспективный аудит (security,
programming, logic, design, functionality, recruiting, end-user). Из
выявленных пунктов отсортированы пять блокирующих и закрыты hotfix-ом
этим же спринтом.

## 1. Drift worker → 25 признаков

**Что было.** `backend/src/waf_panel/workers/drift_worker.py` тянул
6 numerical-колонок из `traffic_features` и сравнивал PSI/KS только
по ним. Реальный drift в распределении атак — появление новых SQLi /
XSS / path-traversal векторов — не триггерил alarm никогда, потому что
все 8 token-флагов оставались за бортом.

**Что стало.** Worker теперь pull'ит сырые HTTP-поля (method, path,
query, ua, referer) из `traffic_log` и прогоняет их через тот же
`waf_ml.features.featurize`, что использовал тренер. Сравнение PSI/KS
идёт по всем 25 признакам, включая `tok_union_select`, `tok_script`,
`tok_path_traversal` и т.д. Новый regression-тест
`test_drift_worker_compares_all_25_features` фиксирует контракт
`n_features_compared == 25`.

Дополнительно SQL фильтрует `event_type = 'access'` — иначе ModSec-
заблокированный attack-burst поднял бы alert против собственной
baseline'ы, ложно-положительно.

## 2. IsolationForest score normalization (sigmoid)

**Что было.** `_model_prob` в ml-service нормализовал
`decision_function` через `(df - df.min()) / (df.max() - df.min())`.
На batch=1 (онлайн-инференс) `df.max == df.min`, нормализация
коллапсировала в `0`, IF становился бесполезным онлайн.

**Что стало.** Sigmoid с фиксированным `scale=4`:

```
prob = 1 / (1 + exp(scale * decision_function))
```

`decision_function ≥ 0` (inlier) → prob → 0; `< 0` (anomaly) → prob → 1.
Стабильно для любого batch-size, monotonic. Регрессионный тест
`test_iforest_decision_function_does_not_collapse_on_batch_1` фиксирует:
benign и malicious одиночные запросы дают `prob > 0.05` и
`prob_mal > prob_benign`.

## 3. Rate-limit на /api/v1/auth/login

**Что было.** Login-эндпоинт без rate-limit'а — открыт для брутфорса.
argon2id специально медленный (десятки мс), без верхней границы это
переходит в CPU-exhaustion DoS.

**Что стало.** Sliding-window backend в `security_rate_limit.py`:
5 попыток per `(remote_ip, lower(email))` per 60 сек. На 6-й — 429.
**Fail-open на ошибку** — даже если limiter упадёт (memory pressure /
нестыковка часов), легитимный пользователь не залочен. Email
лоуэркейзится в ключе — `Admin@x.com` и `admin@x.com` бьют по одному
бакету. 6 unit-тестов: успех в окне, 6-я попытка → 429, разные email
→ независимые бакеты, case-insensitive ключ, fail-open на исключении,
прямой unit-test самого helper'а.

`X-Forwarded-For` уважается (мы за nginx), с fallback на `request.client.host`.

## 4. JWT secret sanity-check на старте

**Что было.** В `init.sql` зашит дефолтный admin (`admin@example.com /
admin`); в config — дефолтный `JWT_SECRET="dev-secret-do-not-use"`.
Никаких стартовых проверок — забыл оператор ротировать перед прод-
деплоем, и панель сразу уязвима для JWT-replay.

**Что стало.** `Settings.waf_env` (default `development`) + функция
`_validate_settings()` в `main.py`:

- При `waf_env=production` (case-insensitive) и `JWT_SECRET` из
  blocklist дефолтов (`dev-secret-do-not-use`,
  `change_me_in_a_real_deployment`, `test-secret-test-secret-test`) —
  `RuntimeError` с человекочитаемой подсказкой `openssl rand -hex 32`.
- При `waf_env=production` и длине секрета < 32 — также отказ.
- В development / testing — guard no-op, ничего не ломает.

7 тестов покрывают оба пути и e2e через `create_app()`.

## 5. GitHub Actions CI workflow

**Что было.** Тесты есть (156+ штук), CI-конфига нет — никакой
автоматической верификации на push/PR.

**Что стало.** `.github/workflows/ci.yml` с 6 jobs:

| Job          | Что делает                                              |
|--------------|---------------------------------------------------------|
| backend      | ruff + pytest (Postgres service-container на 5432)      |
| ml           | ruff + pytest (sklearn / xgboost / scipy)               |
| ml-service   | ruff + pytest (импортирует waf_ml из sibling-пакета)    |
| bench        | ruff + pytest (stdlib HTTP stub-server)                 |
| frontend     | npm install + tsc --noEmit + eslint + vite build        |
| ci-ok        | Aggregator (single name для branch-protection rule)     |

Concurrency-group + `cancel-in-progress` чтобы не плодить параллельные
прогоны на быстрых push'ах.

## Финальный прогон после hotfix

```
ml-service:  22 passed (было 21, +1 IF batch=1)
ml-offline:  55 passed
bench:        5 passed
backend:     81 passed (было 68, +5 drift, +6 rate-limit, +7 jwt-guard, −7 удалённых)
ИТОГО:      163 passed
ruff:       All checks passed
CI workflow: 6 jobs, agregated by `ci-ok`
```

Все 5 блокеров из аудита закрыты, регрессионные тесты есть на каждый —
если кто-то откатит фикс, тест моментально поймает. Остальные пункты
аудита (SHAP, security-headers middleware, mTLS между сервисами, dark
mode, search-bar на инцидентах, observability) — backlog и не блокеры
защиты.
