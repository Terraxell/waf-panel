# Sprint 9 — drift, explanations, Lua subrequest (week 10)

- Окно: неделя 10 из 12
- Драйвер: после ввода online-инференса (Sprint 8) дашборду нужно
  *объяснение* решения и *гарантия* стабильности качества во времени.
  Параллельно цепляем Lua-subrequest на nginx-стороне (за фичефлагом),
  чтобы Sprint 10 мог открыть block-mode.

## Definition of Done

- [ ] `ml-service`: `POST /explain` возвращает top-K вклад признаков
      в текущее предсказание. Реализация через
      `model.feature_importances_` (XGBoost) или `model.coef_` (LR);
      heavy SHAP dependency *не* добавляется в образ.
- [ ] `ml/src/waf_ml/drift.py`: PSI и Kolmogorov–Smirnov метрики
      между baseline и current распределениями. CLI
      `python -m waf_ml.drift --baseline X.csv --current Y.csv`.
- [ ] `proxy/Dockerfile.openresty` — альтернативная сборка с
      `lua-nginx-module`. `infra/nginx/lua/score.lua` делает
      `ngx.location.capture("/ml/score", ...)` с бюджетом 5 ms и
      fail-open. Включается переменной `PROXY_FLAVOR=openresty` в
      compose (по умолчанию остаётся `crs-nginx`, образ ModSecurity
      без Lua).
- [ ] Frontend: на странице Incidents в строке инцидента видна
      колонка `ML prob` (или «—» при fallback). Hover открывает
      tooltip с топ-3 вкладами признаков из `/api/v1/ml/inspect`
      и нового `/api/v1/ml/explain`.
- [ ] Тесты:
      - `ml-service/tests/test_explain.py` — формат ответа,
        N контрибьюторов, сумма абс. весов = 1.0.
      - `ml/tests/test_drift.py` — PSI идентичных distros = 0,
        PSI сильно сдвинутых > 0.25, KS p-value под threshold.

## Out of scope

- **Block-mode** на основе ML — Sprint 10, после калибровки FPR на
  CSIC/CICIDS.
- **AWS WAF-адаптер** — Sprint 10, за фичефлагом.
- **Real SHAP** TreeExplainer — отложено в ADR-0011 (heavy
  dependency, ~200 MB на образ; built-in importances хватает для
  CP-3 demo).
- **Auto-retraining loop** при сработавшем drift — Sprint 11+.

## Архитектура — что меняется

```
client ─▶ proxy ──┬─▶ DVWA      (без изменений)
                  │
                  └─▶ [Lua subrequest if PROXY_FLAVOR=openresty]
                            │
                            └─▶ ml-service:/score    (≤ 5 ms)
                                  ▲
                                  └─ Redis cache (TTL 30 s)

panel ─▶ FastAPI ─┬─▶ /api/v1/ml/inspect → ml-service:/score
                  └─▶ /api/v1/ml/explain → ml-service:/explain (NEW)

trainer (offline) ─▶ ml/models/<v>/ ──┬─▶ joblib (active)
                                       └─▶ baseline_features.csv (NEW)
                                              ▲
                                              └─ drift.py: PSI/KS
                                                  vs current ClickHouse window
```

## Контракт `/explain`

```json
POST /explain
{ same shape as /score request }

→ {
    "prob": 0.987,
    "model": "xgboost",
    "model_version": "csic-2010-...",
    "contributors": [
        {"feature": "tok_union_select", "weight": 0.42},
        {"feature": "ua_is_bot",        "weight": 0.21},
        {"feature": "tok_or_1_eq_1",    "weight": 0.18}
    ],
    "method": "feature_importances"
}
```

`method` — провенанс веса: `"coef"` для LR, `"feature_importances"`
для XGBoost. Поле сохраняется и в JSON-логе `audit_log`.

## Drift — формулы и пороги

**PSI** (Population Stability Index):
```
PSI(p, q) = Σ (p_i - q_i) · ln(p_i / q_i)
```
По бинам распределения (B=10, equal-frequency на baseline). Пороги:

| PSI         | Интерпретация                         |
|-------------|---------------------------------------|
| < 0.10      | без drift                             |
| 0.10 – 0.25 | warning, наблюдать                    |
| ≥ 0.25      | alert, кандидат на retrain            |

**KS-test** (Kolmogorov–Smirnov, scipy.stats.ks_2samp): p-value < 0.05
→ выборки считаются разными. Дополнение к PSI на хвосты.

CLI:
```bash
python -m waf_ml.drift \
    --baseline ml/models/active/baseline_features.csv \
    --current  /tmp/last_24h.csv \
    --report   drift.json
```

Sprint 11 поднимет фоновую задачу: pull последних 24 ч из ClickHouse
+ запуск `drift.py` + write `incidents` row при alert.

## Lua-subrequest — почему за фичефлагом

Образ `owasp/modsecurity-crs:nginx-alpine` не несёт `lua-nginx-module`.
Включение Lua требует:

1. Сборка nginx с `--add-module=ngx_devel_kit + lua-nginx-module + luajit`.
2. Совместимая сборка libmodsecurity + ModSecurity-nginx.
3. Перенос всех текущих CRS-конфигов и тестов под новый образ.

В Sprint 9 мы:
- Поддерживаем оба образа: `proxy/Dockerfile` (текущий) и
  `proxy/Dockerfile.openresty` (новый, с Lua).
- В `docker-compose.yml` `proxy.build.dockerfile` берётся из
  `${PROXY_FLAVOR_DOCKERFILE:-Dockerfile}`.
- Default остаётся `Dockerfile` (CP-2 demo не ломаем).
- Документируем переключение в `docs/troubleshooting.md` с граблями.

## Risks

- **OpenResty + ModSec build hang.** Сборка с нуля занимает ~20 минут;
  CP-2 demo не требует Lua, поэтому переключение — opt-in.
- **`feature_importances_` глобальный, не локальный.** Это не SHAP:
  важность одна на модель, не на запрос. Документируем в UI как
  «общая важность признака для модели», в Sprint 10 заменим на
  TreeExplainer если успеем.
- **Drift baseline drift.** Если baseline сам собрали на грязных
  данных — все PSI будут низкими. Sprint 11 добавит ручной
  rebaseline-flow.

## Carry-over в Sprint 10

- Block-mode: `prob > θ → 403`, θ калибруется по FPR-budget из CP-2.
- Attack bench: ZAP / sqlmap / WAFNinja прогоны, замеры FPR/FNR.
- AWS WAF-адаптер за фичефлагом.
- Per-prediction TreeSHAP за `--shap` опцией в `/explain`.
