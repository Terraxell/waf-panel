# Sprint 8 — online ML-инференс (week 9)

- Окно: неделя 9 из 12
- Драйвер: вывести offline-обученные модели «на провод».
  Backend-шлюз проверяет HTTP-запрос через `ml-service`, получает
  вероятность атаки и работает в режиме `score-augment` (метка к
  инциденту в Postgres) — не блокирует трафик в этом спринте, но
  даёт UI-стороне числа на дашборд.

## Definition of Done

- [ ] `ml-service/` — отдельный контейнер: FastAPI + `joblib.load`
      на старте, активная модель из `ml_models WHERE is_active`.
- [ ] `POST /score` принимает HTTP-запрос (method/path/query/body/ua),
      возвращает `{prob: float, model: str, model_version: str,
      latency_ms: float}`. **Никаких side-effects.**
- [ ] `GET /healthz` — liveness. `GET /readyz` — модель загружена.
- [ ] `waf_ml.features` импортируется из `ml-service` без копи-паста.
      ML-сервис монтирует ту же `features.py`, что использовал тренер.
- [ ] Redis-кэш по `(method, path_hash, query_hash)` c TTL 30 s.
      Fail-open: при недоступном Redis сервис продолжает считать.
- [ ] Backend-прокси `/api/v1/ml/inspect` с бюджетом 20 ms p99 →
      при таймауте отдаёт `{prob: null, fallback: true}`. SAFETY:
      ML-ошибка никогда не должна валить запрос пользователя.
- [ ] `docker-compose.yml`: сервис `ml-service` + healthcheck,
      переменные `ML_SERVICE_URL`, `ML_SERVICE_TIMEOUT_MS`.
- [ ] Тесты:
      - `ml-service/tests/test_score.py` — smoke на golden malicious
        и benign request, формат ответа, latency_ms ≥ 0.
      - `backend/tests/test_ml_inspect.py` — fail-open при таймауте,
        корректный пробрасывание prob при успехе.

## Out of scope

- **nginx Lua subrequest** (`access_by_lua_block` → `/score`).
  Образ `owasp/modsecurity-crs:nginx-alpine` не несёт `lua-nginx-module`;
  переход на OpenResty + ModSecurity — самостоятельная миграция.
  Этот пункт ушёл в Sprint 9 за фичефлаг `WAF_USE_LUA`.
- AWS WAF-адаптер (boto3) — Sprint 10, под фичефлаг.
- SHAP / contributors — Sprint 9.
- Drift detection (PSI, KS) — Sprint 9.
- Block-mode на основе ML (`prob > 0.95 → 403`) — Sprint 10, после
  attack-bench-замера FPR на CSIC/CICIDS.

## Архитектура

```
client ─▶ nginx + ModSec ─▶ DVWA (без изменений)
                  │
                  └─▶ vector ─▶ ClickHouse
                                    ▲
panel-ui ─▶ FastAPI ─┬─▶ Postgres (rules, incidents, audit)
                     │
                     └─▶ ml-service (FastAPI + joblib)
                              │     ▲
                              ▼     │
                            Redis  ml_models pkl
                            (cache)  (active row)
```

ML живёт **рядом** с backend, не на критическом пути ModSecurity.
В этом спринте мы в score-augment режиме: dashboard видит
`prob` рядом с инцидентом, ModSec блокирует/пропускает по своим
правилам. Sprint 10 включит блок-мод после калибровки порога.

## Контракт `/score`

Запрос:
```json
{
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT * FROM users--",
    "body": "",
    "headers": {"User-Agent": "sqlmap/1.7.2"}
}
```

Ответ (успех):
```json
{
    "prob": 0.987,
    "model": "xgboost",
    "model_version": "csic-2010-2026-05-08T10:00:00+00:00-xgboost",
    "latency_ms": 4.3,
    "cached": false
}
```

Ответ (нет активной модели):
```json
{
    "prob": null,
    "model": null,
    "model_version": null,
    "latency_ms": 0.0,
    "cached": false,
    "fallback_reason": "no_active_model"
}
```

Backend-прокси при таймауте/5xx ставит `fallback: true` и копирует
эти же поля. UI отображает `prob = "—"` и иконку «ML недоступен».

## Бюджеты

- `/score` p50 ≤ 3 ms, p95 ≤ 8 ms, p99 ≤ 15 ms (на CPU, batch=1,
  XGBoost-дерево глубиной 4, 200 деревьев).
- Backend → ml-service: timeout 20 ms p99, retries=0. SAFETY: ретрай
  на критическом пути увеличивает хвост, не уменьшает его.
- Redis-cache lookup: 1 ms target, fail-open при недоступности.

## Риски

- **Image bloat.** `ml-service` тянет numpy/scipy/scikit-learn/xgboost
  + joblib. Целимся в multi-stage build, runtime ≤ 600 MB. Альтернатива
  — `manylinux2014` wheel-only установка.
- **Версия features.py drift.** Решено: `ml-service` импортирует
  `waf_ml.features` из той же `ml/`-папки через volume / pip-install.
  Sprint 9 закроет это пакетом `waf-ml-features` в общий wheel.
- **Cold-start latency.** Первый `joblib.load` — десятки миллисекунд.
  Контейнер ждёт `readyz=true` прежде чем backend начинает слать запросы;
  compose healthcheck гарантирует это.
- **Нет активной модели в registry.** Сервис стартует, но возвращает
  `fallback_reason="no_active_model"`. Не падает.

## Carry-over в Sprint 9

- Lua-subrequest в nginx (миграция на OpenResty + ModSecurity сборка).
- SHAP-объяснения: топ-3 признака на UI карточке инцидента.
- Drift PSI/KS-метрики, фоновые задачи в Redis Streams.
