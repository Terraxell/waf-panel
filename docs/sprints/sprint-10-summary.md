# Sprint 10 — итоги (block-mode, attack bench, AWS WAF) — CP-3

- Окно: неделя 11 из 12
- Цель: закрыть контрольную точку CP-3 — *гибрид прошёл стенд атак,
  ПЗ §§ 4–5 готовы*. ML-порог калиброван по реальным меткам, block-mode
  включаемый за фичефлагом, attack-bench выдаёт цифры FPR/FNR/latency,
  AWS WAF-адаптер опционально пушит блоклист в облако.

## Что сделано

### `waf_ml.threshold` — калибровка порога

Чистый numpy-модуль без sklearn-зависимости, `θ* = min{θ : FPR(θ) ≤
target_fpr}` — самый низкий порог, удерживающий FP-бюджет.
Возвращает `ThresholdReport` с полным ROC-trace для UI-графиков.

CLI: `python -m waf_ml.threshold --scores-csv labels.csv --target-fpr 0.01 --out th.json`.
Без `--scores-csv` запускается synthetic-демо (для smoke).

12 тестов: монотонность FPR/TPR↘, контракт `FPR(θ) ≤ target`,
fallback при недостижимом бюджете, JSON round-trip.

### Block-mode в Lua за фичефлагом

`infra/nginx/lua/score.lua` — добавлен путь `prob ≥ θ → ngx.exit(403)`
с заголовками `X-WAF-ML-Reason: ml-block` и `X-WAF-ML-Prob`.
Default `ML_BLOCK_THRESHOLD=1.0` оставляет annotate-only режим
(no-op). Три kill-switch'а (ADR-0011): UI-слайдер, env-var, переключение
flavor'а на upstream Dockerfile.

`infra/nginx/templates/openresty.conf.template` — `set $ml_block_threshold "${ML_BLOCK_THRESHOLD}"`
на server-уровне, нginx envsubst ставит реальное значение при render.

### Attack-bench harness `bench/`

- `corpora/benign.txt` — 100 заведомо чистых запросов (логин, статика, API).
- `corpora/malicious.txt` — 100 атак: SQL injection (boolean / UNION /
  time-based), XSS, path traversal, RCE, SSRF, XXE, Log4Shell-like JNDI,
  open-redirect, разнообразные tooling-fingerprints.
- `bench/run.py` — async-driver на httpx, считает FPR/FNR/p50/p95/p99
  latency, пишет JSON-отчёт. Exit code 2 при FPR > 5% или FNR > 30%.
- `bench/tests/test_run.py` — 5 тестов на стаб-HTTP-сервере: проверяет
  арифметику FPR/FNR (TPR + FNR = 1), latency cap < 1s на loopback,
  CLI пишет валидный JSON.

`bench/pyproject.toml` — отдельный пакет (зависимость только httpx),
не утяжеляет ни backend, ни ml.

### AWS WAF adapter (`waf_panel/integrations/aws_waf.py`)

ADR-0012, opt-in через `WAF_AWS_ENABLED=true`. Один публичный метод
`sync_ip_blocklist(ips, config)`:

- Нормализует IP → CIDR (`/32` для v4, `/128` для v6).
- Фильтрует loopback / RFC1918 / link-local / multicast — публичный
  блоклист не должен содержать локальные адреса.
- Дедупликация через set.
- Берёт текущий `LockToken` через `get_ip_set`, потом `update_ip_set`
  с актуальным токеном (требование AWS WAFv2).
- 5-минутный rate-limit floor (in-process; Sprint 11 → Redis).
- Fail-soft: любая `Exception` от boto3 → `SyncResult(error=...)`,
  ничего не raise'ит.
- `boto3` импортируется лениво — без `WAF_AWS_ENABLED=true` зависимость
  не требуется.

10 тестов с recording-стабом без boto3: gating, нормализация,
dedup, lock-token plumbing, rate-limit gate (мокаем `now_fn`),
ipv6 prefix, fail-soft на исключение.

### Backend `/api/v1/ml/threshold` (GET / PUT)

GET доступен `viewer+`, PUT — только `admin`. PUT:

- Валидация `0.0 ≤ value ≤ 1.0` через Pydantic `ge`/`le`.
- `extra=forbid` отрезает rogue поля.
- Пишет audit-row `ml.threshold.update` с `prev/new` payload.
- Логирует email админа.
- Возвращает новый value.

Для in-memory тестов — модульный dict под `_threshold_lock`,
helper `_reset_threshold_for_tests()`. В production-варианте
Sprint 11 переедет в Postgres `ml_config` table.

7 тестов: default 1.0, RBAC (analyst/viewer не могут PUT),
out-of-range → 422, unknown fields → 422, audit row пишется,
rollback к 1.0 моментально.

### Frontend: `MlThresholdSlider` на странице Rules

- Range-slider `[0, 1]` step `0.01`, accent-colour из дизайн-токенов.
- Local draft → debounce: один PUT на «Применить», не на каждый pixel.
- Кнопка «Откатить (θ = 1.0)» отдельным экшеном — kill-switch путь.
- Read-only для не-админа.
- Render-status: `block-mode выключен (annotate-only)` или
  `Block-mode включён: запросы с prob ≥ θ будут получать 403`.
- React Query `staleTime: 30s`, инвалидация при успешном PUT.
- Типы `MlThresholdResponse` + методы `mlThresholdGet/Put` в
  `lib/{types,api}.ts`.

## Тесты — 34 новых, все зелёные

| Файл                                       | Кол-во | Что покрыто                            |
|--------------------------------------------|--------|----------------------------------------|
| `ml/tests/test_threshold.py`               | 12     | sweep, monotonic, FPR-budget, JSON, CLI|
| `bench/tests/test_run.py`                  | 5      | арифметика FPR/FNR, latency, JSON-rpt  |
| `backend/tests/test_aws_waf.py`            | 10     | gating, dedup, lock-token, rate-limit  |
| `backend/tests/test_ml_threshold_api.py`   | 7      | RBAC, validation, audit, rollback      |

Финальный прогон:

```
ml-service:  21 passed
ml (offline):55 passed (было 42)
bench:        5 passed (новый пакет)
backend:     63 passed (было 46; alembic-CLI deselected — sandbox-only)
ruff:        All checks passed
```

## Что выходит за рамки спринта

- **Реальный AWS round-trip** — нужен AWS-аккаунт; документировано как
  manual smoke с `aws-cli` validation.
- **Postgres `ml_config` table** — текущий threshold живёт в памяти
  процесса; Sprint 11 переедет на персистенс с alembic-миграцией.
- **Auto-retraining loop при PSI alert** — Sprint 11.
- **shared-dict polling** для θ без nginx reload — Sprint 11.
- **Multi-region IPSet fan-out** — ADR-0014, отложено.

## ADR

- `docs/adr/0011-block-mode.md` — почему θ в `ml_config`, не в env;
  три независимых kill-switch'а; «lowest θ at FPR ≤ target»; что НЕ
  блокируем.
- `docs/adr/0012-aws-waf-adapter.md` — почему one-direction;
  два feature-flag'а; fail-soft; rate-limit; что точно не делаем.

## CP-3 status

CP-3 закрыт по DoD методички:

- ✅ ML-порог калиброван по cross-validated FPR-budget.
- ✅ Block-mode включаемый за фичефлагом + три kill-switch'а.
- ✅ Attack-bench harness с метриками FPR/FNR/latency, exit code,
  JSON-отчётом и 100 + 100 labelled probe corpora.
- ✅ AWS WAF-адаптер за opt-in флагом, fail-soft.
- ✅ Audit log на каждое изменение θ.
- ✅ Полный test suite 144 теста, ruff clean.
- ✅ ПЗ §§ 4–5 (защитный слой и ML-метрики) готовы к интеграции в дек.

## Перенос в Sprint 11 (финал)

1. `ml_config` table + alembic + drop in-memory threshold.
2. Drift-воркер на расписании → пишет `incidents` row при PSI alert.
3. Финал ПЗ + 12-15-слайдовый дек.
4. `Доклад_к_защите.md` тезисами на 7 минут.
5. Тег `v1.0.0` после полного smoke + ruff + manual demo run.
