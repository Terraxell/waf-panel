# Sprint 8 — итоги (online ML-инференс)

- Окно: неделя 9 из 12
- Цель: вывести offline-обученные модели «на провод».
  Score-augment режим: dashboard видит вероятность атаки рядом
  с инцидентом, ModSec продолжает блокировать по своим правилам.

## Что сделано

### Отдельный пакет `ml-service/`

Свой `pyproject.toml`, свой Dockerfile, свой `tests/`. **Зачем
изолированно от backend:** sklearn + xgboost + numpy/scipy добавляют
~400 МБ к runtime-образу. Если ML-сервис упадёт — backend этого
не заметит, и наоборот.

Структура:
```
ml-service/
├── Dockerfile             # multi-stage venv + libgomp1 для xgboost
├── pyproject.toml         # fastapi, uvicorn, joblib, sklearn, redis, psycopg
├── src/waf_ml_service/
│   ├── main.py            # FastAPI app: /score /healthz /readyz
│   ├── schemas.py         # Pydantic v2 ScoreRequest/ScoreResponse
│   ├── config.py          # env-driven Settings
│   ├── model_loader.py    # registry path + filesystem fallback
│   └── cache.py           # Redis-кэш с fail-open семантикой
└── tests/                 # pytest + TestClient
```

### Контракт `/score`

```json
POST /score
{
    "method": "GET",
    "path": "/login.php",
    "query": "id=1' UNION SELECT * FROM users--",
    "user_agent": "sqlmap/1.7.2"
}

→ {
    "prob": 0.987,
    "model": "xgboost",
    "model_version": "csic-2010-...-xgboost",
    "latency_ms": 4.3,
    "cached": false,
    "fallback_reason": null
}
```

Если активной модели нет — `prob=null`, `fallback_reason="no_active_model"`.
Сервис стартует, но честно говорит «не могу».

### Загрузка модели — registry + filesystem fallback

`model_loader.py` пробует по порядку:

1. **Registry path** (`ML_USE_REGISTRY=true`): `waf_ml.registry.get_active(algo=...)`
   → `joblib.load(artifact_path)`.
2. **Filesystem path** (default): `<ML_MODEL_DIR>/<algo>.pkl` напрямую.
   Используется в dev/CI и когда trainer писал артефакты в bind-mount,
   но Postgres не запущен.
3. **Fallback algo** (default `lr`): если основной (`xgboost`) не найден.
4. **None**: сервис стартует в degraded-режиме.

### Redis-кэш — best-effort, не зависимость

Ключ: `sha1(method + path + query)[:24]`, TTL 30 s, namespace
`ml:score:`. Любая ошибка Redis (недоступен, таймаут, мусор в
ответе) → trait как cache miss, **никогда не валит запрос**.
Класс `ScoreCache` ловит исключения внутри `.get()`/`.set()`.

### Backend-прокси `/api/v1/ml/inspect` с бюджетом 20 ms

`waf_panel/api/ml.py` — async-эндпоинт за RBAC (`viewer+`):

- `httpx.AsyncClient(timeout=20ms)` к `ml-service:8001/score`.
- При `TimeoutException` → `{prob: null, fallback: true, fallback_reason: "timeout"}`.
- При network error → `fallback_reason="network"`.
- При HTTP 5xx → `fallback_reason="error_5xx"`.
- 0 retries — ретрай на критическом пути увеличивает хвост, не уменьшает.

### docker-compose

Новый сервис `ml-service`:

```yaml
ml-service:
  build: ./ml-service
  depends_on: { redis: { condition: service_healthy } }
  environment:
    ML_MODEL_DIR: /app/models
    ML_MODEL_ALGO: xgboost
    ML_FALLBACK_ALGO: lr
    ML_USE_REGISTRY: false
  volumes:
    - ./ml/models/active:/app/models:ro
  healthcheck: curl /readyz
```

Backend ждёт `service_started` (не `_healthy`) — gateway должен
встать, даже если модели нет ещё.

`make ml-promote` / `dev.ps1 ml-promote` копирует последний
`ml/models/v*/` в `ml/models/active/` атомарно.

### Тесты

| Файл                              | Что проверяет                                    |
|-----------------------------------|--------------------------------------------------|
| `ml-service/tests/test_score.py` (8) | /healthz, /readyz, golden malicious/benign,    |
|                                      | shape ответа, fallback при no model, cache hit |
| `ml-service/tests/test_cache.py` (4) | None client → graceful, flaky redis → no raise,|
|                                      | key зависит от method/path/query, round-trip   |
| `backend/tests/test_ml_inspect.py` (6)| pass-through на успехе, fail-open на timeout/  |
|                                      | 5xx/network, 401 без auth, no_active_model     |

Прогон:

```
ml-service:   12 passed
backend:      42 passed (включая 6 новых ml_inspect)
ml (offline): 30 passed (без регрессий)
ruff: clean
```

### Стиль ответа

`InspectResponse` (backend) добавляет к ответу ml-service поле
`fallback: bool`, чтобы UI смотрел на одно булево вместо `prob is None`
(их два варианта: «нет модели» и «timeout»). Источник причины —
`fallback_reason`.

## Что выходит за рамки спринта

- **nginx Lua-subrequest.** Образ `owasp/modsecurity-crs:nginx-alpine`
  не несёт `lua-nginx-module`. Миграция на OpenResty + ModSecurity —
  Sprint 9 за фичефлагом `WAF_USE_LUA`.
- **Block-mode** (`prob > 0.95 → 403`). Sprint 10, после калибровки FPR.
- **SHAP / contributors.** Sprint 9, отдельный `/explain`.
- **Drift detection** (PSI, KS). Sprint 9.
- **AWS WAF-адаптер.** Sprint 10 за фичефлагом.

## ADR

`docs/adr/0008-online-inference.md` — почему отдельный контейнер,
почему 20 ms timeout без retry, почему fail-open, что НЕ делаем
в этом спринте.

## Перенос в Sprint 9

1. OpenResty + ModSecurity-build → Lua subrequest на `/score`.
2. SHAP per-prediction explanations (top-3 признака для UI).
3. Drift PSI/KS, фоновые задачи в Redis Streams.
4. UI карточка инцидента с ML-вердиктом и контрибьюторами.
