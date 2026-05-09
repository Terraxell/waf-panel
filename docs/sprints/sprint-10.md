# Sprint 10 — block-mode, attack bench, AWS WAF (week 11) — CP-3

- Окно: неделя 11 из 12
- Driver: закрыть контрольную точку CP-3 — *гибрид прошёл стенд атак,
  ПЗ §§ 4–5 готовы*. Это означает: ML-порог калиброван по реальным
  данным, block-mode включаем за фичефлагом, attack-bench даёт цифры
  FPR/FNR/latency, и опционально wire-в AWS WAF за вторым флагом.

## Definition of Done

- [ ] `ml/src/waf_ml/threshold.py` — модуль калибровки. Принимает
      `(y_true, scores, target_fpr=0.01)` и возвращает `θ` + полный
      ROC-trace для дашборда. CLI:
      `python -m waf_ml.threshold --report ml/models/active/report.json
      --target-fpr 0.01`.
- [ ] `infra/nginx/lua/score.lua` — поддержка block-mode за
      переменной `ml_block_threshold` (env-driven через nginx
      `set $ml_block_threshold $env_var`). Default `1.0` (никогда не
      блокирует), `< 1.0` включает `ngx.exit(403)` при `prob ≥ θ`.
      По-прежнему fail-open на любую ошибку ML-сервиса.
- [ ] `bench/` — attack-bench harness:
      - `bench/corpora/benign.txt` — 100 заведомо чистых запросов
        (логин-страницы, статика, API-вызовы из реальных RUM-логов).
      - `bench/corpora/malicious.txt` — 100 атак (sqlmap, ZAP, XSS,
        path traversal, RCE, LFI, SSRF, command injection).
      - `bench/run.py` — драйвер: бьёт целевой URL, считает FPR/FNR
        по статус-коду 403, замеряет p50/p95/p99 latency.
      - JSON-отчёт `bench/reports/<timestamp>.json`.
      - `pytest` против стаб-HTTP-сервера на `aiohttp.test_utils`.
- [ ] `backend/src/waf_panel/integrations/aws_waf.py` — adapter за
      `WAF_AWS_ENABLED=true`. Один публичный метод `sync_ip_blocklist`
      (берёт top-N atakeров из ClickHouse, апдейтит IPSet через boto3).
      Ошибки AWS — мягкий fallback с `audit_log` записью.
- [ ] `backend/api/ml.py`: `GET /ml/threshold` (текущее θ из БД),
      `PUT /ml/threshold` (RBAC admin only) — конфиг живёт в новой
      таблице `ml_config(key, value, updated_at, updated_by)`.
- [ ] Frontend: на странице Rules — слайдер «ML block threshold»,
      кнопка «Recalibrate from latest model». Read-only для
      analyst/viewer, edit для admin.
- [ ] Тесты:
      - `ml/tests/test_threshold.py` — sweep, monotonic FPR ↘ при
        растущем θ, target-fpr ≤ 0.01 на synthetic.
      - `bench/tests/test_run.py` — стаб-сервер с ModSec-like
        логикой (regex по UNION/SELECT и `<script>`); driver
        выдаёт FPR близкий к 0, FNR < 0.5.
      - `backend/tests/test_aws_waf.py` — moto-style mock boto3;
        `sync_ip_blocklist` строит правильный IPSet update payload
        и пишет audit row при ошибке.
      - `backend/tests/test_threshold_api.py` — RBAC, ml_config CRUD.

## Out of scope

- **Real cloud round-trip** в AWS — нужен AWS аккаунт, документируем
  в `docs/troubleshooting.md` как ручной шаг с `aws-cli` validation.
- **Auto-retraining loop при PSI alert** — Sprint 11.
- **Multi-region IPSet sync** — Sprint 11.
- **TreeSHAP в `/explain`** — отложен в ADR-0011 от Sprint 9, всё ещё
  опционально.

## Calibration math

Для каждого порога `θ ∈ [0, 1]`:
```
TP = Σ (scores ≥ θ ∧ y_true = 1)
FP = Σ (scores ≥ θ ∧ y_true = 0)
TN = Σ (scores <  θ ∧ y_true = 0)
FN = Σ (scores <  θ ∧ y_true = 1)
FPR = FP / (FP + TN)
TPR = TP / (TP + FN)
```

Возвращаем `min{θ : FPR(θ) ≤ target_fpr}` — самый низкий порог,
который ещё умещается в budget'е ложноположительных. **Не средний**,
не медианный: мы хотим максимизировать recall при ограничении FPR.

## Block-mode rollout

1. Калибровка → пишем θ в `ml_config(key='ml_block_threshold')`.
2. nginx читает `ML_BLOCK_THRESHOLD` env → `$ml_block_threshold` через
   `set` на server-уровне.
3. `score.lua` сравнивает `body.prob` с `tonumber(ngx.var.ml_block_threshold) or 1.0`.
4. Если `prob ≥ θ` → `ngx.exit(403)` с заголовком `X-WAF-ML-Reason: ml-block`.
5. Vector логирует в ClickHouse с `event_type='ml_block'` (новое
   значение enum'а).
6. Dashboard отрисовывает `ml_block` как третью категорию рядом с
   `access` и `modsec`.

**Откат**: оператор кладёт `θ = 1.0` через UI слайдер или env →
блок-мод выключен моментально, ML продолжает аннотировать.

## Risks

- **Synthetic-калиброванное θ переоценивает уверенность.** Synthetic
  слишком очевидна; на CSIC θ будет другим. Документируем: запуск
  `make calibrate` после `make train` — обязательный шаг при первом
  включении block-mode.
- **AWS WAF rate limits.** UpdateIPSet — 1 RPS на API-ключ, 10000
  IPs на IPSet. Обновляем не чаще, чем раз в 5 минут;
  rate-limited cron в Sprint 11.
- **Lua `ngx.exit` после buffered body.** Если `client_max_body_size`
  превышен и nginx уже стримит body — exit(403) после headers вышлет
  «прерванный» ответ. Документируем в troubleshooting; реальное решение
  — per-route opt-out в Sprint 11.

## Carry-over в Sprint 11

- Drift-воркер на расписании (Redis Streams) → запись в `incidents`.
- Финал ПЗ + 12-15-слайдовый дек.
- Доклад тезисами на 7 минут.
- Тег `v1.0.0` после полного smoke + ruff + mypy.
