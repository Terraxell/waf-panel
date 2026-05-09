# Sprint 9 — итоги (drift, объяснения, Lua subrequest)

- Окно: неделя 10 из 12
- Цель: дать дашборду *объяснение* решения ML, гарантировать
  стабильность качества во времени и подготовить инфраструктуру для
  block-mode (Sprint 10) — Lua-subrequest на nginx-стороне за фичефлагом.

## Что сделано

### `/explain` в ml-service

Эндпоинт `POST /explain` возвращает топ-K вкладов признаков:

```json
POST /explain?top_k=3
→ {
    "prob": 0.987,
    "model": "xgboost",
    "model_version": "csic-2010-...-xgboost",
    "method": "feature_importances",
    "contributors": [
        {"feature": "tok_union_select", "weight":  0.45},
        {"feature": "ua_is_bot",         "weight":  0.30},
        {"feature": "tok_path_traversal","weight":  0.25}
    ]
}
```

Реализация в `_model_weights()`:

- **LogisticRegression** → `model.coef_` (signed; UI красит pos/neg).
- **XGBoost** → `model.feature_importances_` (всегда ≥ 0).
- **IsolationForest / неизвестный** → `method="unsupported"`, пустой список.

Веса контрибьюторов нормализованы так, что **сумма абсолютных** равна 1.0
(после top-K выбора) — UI получает понятные «доли вклада» вместо сырых
гессианов. **Это не SHAP**: вес = `feature_importance × значение_фичи_на_запросе`.
Это честный proxy: фичи, важные глобально И активные на этом запросе,
поднимаются. Полный TreeSHAP перенесён в ADR-0011 (heavy dep, ~200 МБ
на образ).

### Backend-прокси `/api/v1/ml/explain`

Те же fail-open семантики, что и у `/inspect`: timeout/5xx/network →
`{prob: null, fallback: true, contributors: [], method: "unsupported"}`.
Параметр `top_k` пробрасывается query-string.

### Drift-модуль `ml/src/waf_ml/drift.py`

Две метрики, обе per-feature:

- **PSI** (Population Stability Index) — собственная реализация, 10
  equal-frequency бинов от baseline, smoothing `1/N` против log(0).
  Пороги: `< 0.10` clean, `0.10–0.25` warn, `≥ 0.25` alert.
- **KS-test** — `scipy.stats.ks_2samp`, alpha = 0.05. Confirmation
  signal на хвостовые сдвиги, которые PSI пропускает.

Уровень drift'а считается комбинированно (см. `_level()`):
- alert: `PSI ≥ 0.25` ИЛИ (`PSI ≥ 0.10` И `KS p < 0.05`).
- warn: `PSI ≥ 0.10` ИЛИ `KS p < 0.05`.
- clean: иначе.

CLI:
```bash
python -m waf_ml.drift \
    --baseline ml/models/active/baseline_features.csv \
    --current  /tmp/last_24h.csv \
    --report   drift.json
# exit 0 → clean, 2 → at least one feature in alert
```

`scipy` импортируется лениво — `psi()` сам по себе работает без него.

### OpenResty + Lua subrequest за фичефлагом

Создана альтернативная сборка proxy:

- `proxy/Dockerfile` — стандартный flavour: thin pass-through на
  upstream `owasp/modsecurity-crs:nginx-alpine` (default).
- `proxy/Dockerfile.openresty` — multi-stage build OpenResty 1.25.3 +
  libmodsecurity v3 + ModSecurity-nginx connector + OWASP CRS v4.10.
  ~20 минут первый билд, поэтому opt-in.

Compose выбирает Dockerfile через `${PROXY_FLAVOR_DOCKERFILE:-Dockerfile}`.
Default Sprint 1–8 demo-path сохранён.

Lua-скрипт `infra/nginx/lua/score.lua`:
- Собирает payload (method/path/query/UA/referer) и вызывает
  `ngx.location.capture("/__ml_score", ...)`.
- Бюджет 5 ms через `proxy_*_timeout` в `infra/nginx/templates/openresty.conf.template`.
- При любой ошибке (timeout, 5xx, мусор JSON) ставит заголовок
  `X-WAF-ML-Fallback` с причиной — Vector сольёт в ClickHouse,
  дашборд увидит, какие запросы прошли мимо ML.
- В **Sprint 9 — annotate-only**: `ngx.req.set_header("X-WAF-ML-Prob", ...)`.
- Sprint 10 раскомментирует `ngx.exit(403)` после калибровки порога.

### Frontend: ML-вердикт в Incidents

- Новый компонент `MlBadge.tsx` + `MlBadge.css` — chip с тремя
  уровнями: `high (≥ 0.8)`, `med (≥ 0.4)`, `low (< 0.4)`, плюс
  `na` (fallback) с пунктирной рамкой.
- Tooltip на hover: вероятность, имя модели, `cached`, топ-3 контрибьютора
  с знаком веса.
- Колонка «ML» в `Incidents.tsx`. React Query `staleTime: 30s`, чтобы не
  бомбить ml-service при пагинации.
- Типы `MlInspectRequest`, `MlInspectResponse`, `MlContributor`,
  `MlExplainResponse` в `lib/types.ts`; методы `mlInspect` / `mlExplain`
  в `lib/api.ts`.

### Тесты — 26 новых, все зелёные

| Файл                                | Что проверяет                                  |
|-------------------------------------|------------------------------------------------|
| `ml-service/tests/test_explain.py` (9) | feature_importances vs coef path, top-K       |
|                                        | normalisation, golden malicious bubbles       |
|                                        | UNION/SELECT, fallback при no-model,          |
|                                        | unsupported estimator, top_k=0 → 1            |
| `ml/tests/test_drift.py` (12)       | PSI=0 на identical, ≥ 0.25 на 2-sigma шифт,    |
|                                      | const baseline и empty corner cases, KS на    |
|                                      | identical / shifted, level mapping, CLI exit  |
|                                      | code, missing files, threshold ordering       |
| `backend/tests/test_ml_explain.py` (4) | pass-through на успехе, fail-open на          |
|                                        | timeout, 401 без auth, top_k forwarded в URL  |
| `ml-service` (контракт)             | +1 тест на новый stable-shape                  |

Полный прогон:
```
ml-service:        21 passed (было 12)
ml (offline):      42 passed (было 30)
backend:           46 passed (было 42; alembic-CLI deselected)
ruff: All checks passed!
```

## Что выходит за рамки спринта

- **Block-mode** (`prob > θ → 403`) — Sprint 10 после калибровки FPR.
- **Real TreeSHAP** в `/explain` — отложен в ADR-0011 (heavy dep).
- **AWS WAF-адаптер** — Sprint 10, за фичефлагом.
- **Auto-retraining loop** при сработавшем drift — Sprint 11+.
- **lua-resty-redis** в Lua — Sprint 11 оптимизация.

## ADR

- `docs/adr/0009-drift-detection.md` — почему PSI + KS, baseline frozen
  at train time, off-band CLI а не on-path.
- `docs/adr/0010-openresty-lua.md` — почему opt-in flavour, Lua
  subrequest contract, что точно не делаем в Sprint 9.

## Перенос в Sprint 10

1. Калибровка ML-порога θ по FPR ≤ 1% на CSIC/CICIDS.
2. Включение `ngx.exit(403)` в `score.lua` за переменной
   `ml_block_threshold` (env-driven).
3. Attack bench: ZAP / sqlmap / WAFNinja прогоны, замеры FPR/FNR.
4. AWS WAF-адаптер за `WAF_AWS_ENABLED=true`.
